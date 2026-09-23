"""字段契约、无损序列化、继承边界与失败不破坏旧文件的回归测试。"""

from __future__ import annotations

import copy
import hashlib
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

import content_io
import fill
import render
import schema
import webui

ROOT = Path(__file__).resolve().parent.parent


class SerializationTest(unittest.TestCase):
    def test_every_control_character_round_trips(self):
        value = ''.join(chr(code) for code in range(128)) + '中文 😀 \\"'
        self.assertEqual(tomllib.loads('value = "' + schema.escape(value) + '"')["value"], value)

    def test_all_editable_fields_survive_round_trip(self):
        original = render.load_content(ROOT / "content.example.toml")
        reloaded = tomllib.loads(fill.dump_toml(webui.shape(original)))
        for block in schema.BLOCKS:
            rows = original[block.key] if block.repeat else [original[block.key]]
            restored = reloaded[block.key] if block.repeat else [reloaded[block.key]]
            self.assertEqual(len(rows), len(restored))
            for before, after in zip(rows, restored):
                for field in block.fields:
                    empty = [] if field.kind in ("list", "lines") else ""
                    with self.subTest(block=block.key, field=field.key):
                        self.assertEqual(before.get(field.key, empty), after.get(field.key, empty))

    def test_custom_sections_and_body_order_round_trip(self):
        """自定义板块 + body_order 经 shape → dump → 重载后结构与数据不丢。"""
        content = webui.shape(render.load_content(ROOT / "content.example.toml"))
        content["body_order"] = ["experiences", "custom:awards", "skills",
                                 "projects", "education"]
        content["custom_sections"] = [{
            "key": "awards", "title": "获奖情况", "identity": "name",
            "fields": [
                {"key": "name", "ask": "奖项", "kind": "text", "required": True},
                {"key": "when", "ask": "时间", "kind": "text", "required": False},
                {"key": "notes", "ask": "说明", "kind": "lines", "required": False},
            ],
            "items": [{"name": "最佳新人", "when": "2025",
                       "notes": ["第一行", "第二行"]}],
        }]
        # shape 只补形状不改内容，这里先确认它把两个键原样带过
        shaped = webui.shape(content)
        self.assertEqual(shaped["body_order"], content["body_order"])
        self.assertEqual(shaped["custom_sections"][0]["items"],
                         content["custom_sections"][0]["items"])

        reloaded = tomllib.loads(fill.dump_toml(shaped))
        self.assertEqual(schema.find_type_errors(reloaded), [])
        self.assertEqual(reloaded["body_order"], content["body_order"])
        section = reloaded["custom_sections"][0]
        self.assertEqual(section["key"], "awards")
        self.assertEqual(section["title"], "获奖情况")
        self.assertEqual(section["identity"], "name")
        self.assertEqual([f["key"] for f in section["fields"]],
                         ["name", "when", "notes"])
        self.assertEqual(section["items"], content["custom_sections"][0]["items"])

    def test_plain_file_dump_gains_no_new_keys(self):
        """没动过板块的老文件落盘后不该凭空多出 body_order / custom_sections。"""
        text = fill.dump_toml(webui.shape(render.load_content(ROOT / "content.example.toml")))
        self.assertNotIn("body_order", text)
        self.assertNotIn("custom_sections", text)

    def _render(self, content):
        theme = render.load_theme(ROOT / "theme.toml")
        css = render.build_stylesheet(theme, ROOT / "resume.css")
        return render.ResumeBuilder(content, theme, css).render_html()

    def test_render_is_byte_identical_for_the_untouched_example(self):
        """没有 body_order / custom_sections 的文件，渲染结果逐字节不变。

        守的是"老文件不受板块可编辑那套改造影响"。注意哈希算的是整份 HTML，
        而版式 CSS 是内联进去的——所以有意改 resume.css / theme.toml 时它也会红。
        那种情况按新的重算一遍哈希填回来（先确认渲出来的版面确实是你要的）。
        """
        content = render.load_content(ROOT / "content.example.toml")
        html = self._render(content)
        self.assertEqual(
            hashlib.sha256(html.encode("utf-8")).hexdigest(),
            "ccce04b150560ec5390d157d82cc64d5122e5741a4ca4408a77aaa39fbfef6a2")

    def test_body_order_reorders_and_deleting_a_builtin_drops_its_row(self):
        content = render.load_content(ROOT / "content.example.toml")
        # 去掉 projects，把 education 提到最前
        content["body_order"] = ["education", "skills", "experiences"]
        html = self._render(content)
        self.assertNotIn("项目作品", html, "删掉的内建块不该出现在渲染里")
        # 比竖脊栏目名的位置，别比正文里的词（正文里也可能提到"核心能力"）
        self.assertLess(html.index('<div class="rail"><span>教育背景</span>'),
                        html.index('<div class="rail"><span>核心能力</span>'),
                        "education 应当排到 skills 之前")
        # 数据仍在内容里，只是没渲染——移除是可逆的
        self.assertTrue(content["projects"])

    def test_custom_section_renders_with_generic_layout(self):
        content = render.load_content(ROOT / "content.example.toml")
        content["custom_sections"] = [{
            "key": "awards", "title": "获奖情况", "identity": "name",
            "fields": [
                {"key": "name", "kind": "text", "required": True},
                {"key": "notes", "kind": "lines", "required": False},
            ],
            "items": [{"name": "年度最佳", "notes": ["评语一", "评语二"]}],
        }]
        html = self._render(content)
        self.assertIn("获奖情况", html)
        self.assertIn("年度最佳", html)
        self.assertIn("评语一", html)
        self.assertIn('class="entry"', html, "自定义块走通用 .entry 版面")

    def test_blank_sample_uses_the_shared_separator(self):
        block = schema.Block("test", "测试", (
            schema.Field("items", "条目", example="Python / https://example.com/a/b", kind="list"),
        ))
        with mock.patch.object(schema, "BLOCKS", (block,)):
            sample = tomllib.loads(schema.blank_form(sample=True))
        self.assertEqual(sample["test"]["items"], ["Python", "https://example.com/a/b"])

    def test_blank_and_sample_forms_keep_valid_shapes(self):
        for sample in (False, True):
            content = tomllib.loads(schema.blank_form(sample=sample))
            self.assertEqual(schema.find_type_errors(content), [])
            self.assertEqual(bool(schema.find_blanks(content)), not sample)

    def test_optional_empty_list_placeholders_are_allowed(self):
        content = tomllib.loads(schema.blank_form(sample=True))
        for facts in ([], [""], ["  "]):
            content["profile"]["facts"] = facts
            with self.subTest(facts=facts):
                self.assertEqual(schema.find_blanks(content), [])

    def test_malformed_shapes_never_escape_validation(self):
        for payload in (None, [], {"skills": [False]}, {"document": {"keywords": "SEO"}},
                        {"profile": {"facts": [12]}}, {"skills_section": 9},
                        {"summary": {"typo": "text"}}):
            with self.subTest(payload=payload):
                self.assertTrue(schema.find_type_errors(payload))
                self.assertTrue(schema.find_blanks(payload))
                with self.assertRaises(ValueError):
                    webui.shape(payload)

    def test_blank_locations_cover_every_message(self):
        """每条 find_blanks() 的消息都能在 find_blank_locations() 里找到对应的位置。"""
        content = tomllib.loads(schema.blank_form(sample=False))
        messages = schema.find_blanks(content)
        locations = schema.find_blank_locations(content)
        self.assertEqual(len(messages), len(locations))
        for msg, loc in zip(messages, locations):
            self.assertEqual(msg, loc["message"])
            self.assertIn("block", loc)
            self.assertIn("index", loc)
            self.assertIn("field", loc)
            self.assertIn("item", loc)
            self.assertIn("section", loc)

    def test_blank_locations_point_at_real_fields(self):
        """location 里的 block/field 一定对应 schema 里存在的东西。"""
        content = tomllib.loads(schema.blank_form(sample=False))
        locations = schema.find_blank_locations(content)
        block_keys = {b.key for b in schema.BLOCKS}
        section_keys = {b.section_key for b in schema.BLOCKS if b.section_key}
        all_keys = block_keys | section_keys
        
        for loc in locations:
            block_name = loc["block"]
            field_name = loc["field"]
            # 类型错误可能没有 block
            if not block_name:
                continue
            self.assertIn(block_name, all_keys, f"位置 {loc} 的 block 不在 schema 里")
            # section 类型的 location 检查 section_key
            if loc["section"]:
                self.assertIn(block_name, section_keys)
                continue
            # 常规 block
            if block_name not in block_keys:
                continue
            block = next(b for b in schema.BLOCKS if b.key == block_name)
            if field_name:  # 可能是整块缺失，此时 field 为空
                field_keys = {f.key for f in block.fields}
                self.assertIn(field_name, field_keys, f"位置 {loc} 的 field 不在 {block_name} 里")


class FileTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "content.toml"
        self.content = webui.shape(render.load_content(ROOT / "content.example.toml"))
        self.text = fill.dump_toml(self.content)


class AtomicSaveTest(FileTestCase):
    def test_create_then_overwrite_leaves_a_snapshot(self):
        first = content_io.save_content(self.path, self.text, None)
        self.assertIsNone(first.snapshot)
        self.assertFalse(first.unchanged)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

        self.content["summary"]["text"] = "修改后的正文"
        modified = fill.dump_toml(self.content)
        second = content_io.save_content(self.path, modified, first.revision)
        self.assertEqual(second.snapshot.read_text(encoding="utf-8"), self.text)
        self.assertEqual(self.path.read_text(encoding="utf-8"), modified)
        self.assertNotEqual(first.revision, second.revision)

    def test_failed_replacement_keeps_old_file(self):
        first = content_io.save_content(self.path, self.text, None)
        self.content["summary"]["text"] = "改了"
        modified = fill.dump_toml(self.content)
        # 只让"替换主文件"这一步失败：快照那一步要照常成功，
        # 否则测的就不是"最后一步失败会不会毁掉旧文件"了。
        real_replace = Path.replace

        def flaky(source, target):
            if Path(target) == self.path:
                raise OSError("disk failure")
            return real_replace(source, target)

        with mock.patch.object(Path, "replace", flaky):
            with self.assertRaises(OSError):
                content_io.save_content(self.path, modified, first.revision)
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.text)
        # 临时文件不许留下（.history 是快照目录，不算残留）
        leftovers = [item.name for item in self.directory.glob(".*")
                     if item.name != content_io.HISTORY_DIR]
        self.assertEqual(leftovers, [])

    def test_invalid_toml_never_touches_existing_file(self):
        first = content_io.save_content(self.path, self.text, None)
        with self.assertRaises(ValueError):
            content_io.save_content(self.path, 'broken = "', first.revision)
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.text)
        self.assertFalse(content_io.history_dir(self.path).exists(),
                         "内容都没通过校验，不该留下快照")

    def test_history_directory_symlink_cannot_redirect_the_snapshot(self):
        """有人把 .history 换成指向别处的符号链接时，快照不能写到那边去。"""
        first = content_io.save_content(self.path, self.text, None)
        outside = self.directory / "outside"
        outside.mkdir()
        (self.directory / content_io.HISTORY_DIR).mkdir()
        content_io.history_dir(self.path).symlink_to(outside)
        self.content["summary"]["text"] = "改了"
        with self.assertRaises(ValueError):
            content_io.save_content(self.path, fill.dump_toml(self.content), first.revision)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.text)

    def test_broken_existing_file_is_not_reinterpreted_as_empty(self):
        self.path.write_text('broken = "', encoding="utf-8")
        with self.assertRaises(ValueError):
            content_io.load_toml(self.path)

    def test_blank_form_refuses_to_overwrite_existing_data(self):
        self.path.write_text(self.text, encoding="utf-8")
        result = subprocess.run([sys.executable, str(ROOT / "fill.py"), "--blank", "--out", str(self.path)],
                                capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("--blank 只用来新建空白表单", result.stdout)
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.text)

    def test_fill_check_does_not_import_weasyprint(self):
        self.path.write_text(self.text, encoding="utf-8")
        result = subprocess.run([sys.executable, "-S", str(ROOT / "fill.py"), "--check", "--out", str(self.path)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_exists_and_modified_are_distinct_errors(self):
        """新文件撞名 → ExistsError；版本不符 → ModifiedError；两者仍是 ConflictError。"""
        # 新文件撞名
        self.path.write_text(self.text, encoding="utf-8")
        with self.assertRaises(content_io.ExistsError) as ctx:
            content_io.save_content(self.path, self.text, None)
        self.assertIn("已存在", str(ctx.exception))
        
        # 版本不符
        revision = content_io.revision(self.path.read_bytes())
        self.path.write_text("[document]\noutput_basename=\"changed\"\n", encoding="utf-8")
        with self.assertRaises(content_io.ModifiedError) as ctx:
            content_io.save_content(self.path, self.text, revision)
        self.assertIn("被改过", str(ctx.exception))
        
        # 两者都是 ConflictError
        self.assertTrue(issubclass(content_io.ExistsError, content_io.ConflictError))
        self.assertTrue(issubclass(content_io.ModifiedError, content_io.ConflictError))
        
        # 旧代码仍然接得住
        try:
            content_io.save_content(self.path, self.text, None)
        except content_io.ConflictError:
            pass  # ExistsError 应该被 ConflictError 接住


class InheritanceSafetyTest(FileTestCase):
    def test_invalid_extends_values_are_rejected(self):
        for value in ('""', "false", "42", '["content.toml"]'):
            self.path.write_text(f"extends = {value}", encoding="utf-8")
            with self.subTest(value=value), self.assertRaises(ValueError):
                content_io.load_content(self.path)

    def test_empty_keep_without_extends_is_rejected(self):
        self.path.write_text("[keep]\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "extends"):
            content_io.load_content(self.path)

    def test_duplicate_identities_do_not_silently_pick_the_last_row(self):
        self.content["skills"].append(copy.deepcopy(self.content["skills"][0]))
        self.path.write_text(fill.dump_toml(self.content), encoding="utf-8")
        variant = self.directory / "content.variant.toml"
        label = self.content["skills"][0]["label"]
        variant.write_text(f'extends = "content.toml"\n[keep]\nskills = ["{label}"]', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "重复"):
            content_io.load_content(variant)

    def test_keep_does_not_mutate_the_base(self):
        original = copy.deepcopy(self.content)
        label = self.content["skills"][0]["label"]
        picked = content_io.apply_keep(self.content, {"skills": [label]}, self.path)
        self.assertEqual(self.content, original)
        self.assertEqual(len(picked["skills"]), 1)

    def test_keep_picks_from_a_custom_section_by_identity(self):
        """[keep] 能按名挑自定义板块里的条目（token 写成 custom:<key>），
        挑完只留中选的那几条，且不改到基底的原字典。"""
        base = copy.deepcopy(self.content)
        base["custom_sections"] = [{
            "key": "awards", "title": "获奖情况", "identity": "name",
            "fields": [{"key": "name", "ask": "奖项", "kind": "text", "required": True}],
            "items": [{"name": "甲"}, {"name": "乙"}, {"name": "丙"}],
        }]
        original = copy.deepcopy(base)
        picked = content_io.apply_keep(base, {"custom:awards": ["丙", "甲"]}, self.path)
        self.assertEqual(base, original, "挑选不得改到基底")
        names = [row["name"] for row in picked["custom_sections"][0]["items"]]
        self.assertEqual(names, ["丙", "甲"], "按 keep 的顺序只留中选的条目")

    def test_keep_rejects_a_name_missing_from_a_custom_section(self):
        base = copy.deepcopy(self.content)
        base["custom_sections"] = [{
            "key": "awards", "title": "获奖情况", "identity": "name",
            "fields": [{"key": "name", "ask": "奖项", "kind": "text", "required": True}],
            "items": [{"name": "甲"}],
        }]
        with self.assertRaisesRegex(ValueError, "乙"):
            content_io.apply_keep(base, {"custom:awards": ["乙"]}, self.path)

    def test_symlinks_and_non_content_parents_are_rejected_in_browser(self):
        parent = self.directory / "theme.toml"
        parent.write_text(self.text, encoding="utf-8")
        link = self.directory / "content.link.toml"
        link.symlink_to(parent)
        for name in (parent.name, link.name, "../content.toml"):
            self.path.write_text(f'extends = "{name}"', encoding="utf-8")
            with self.subTest(name=name), self.assertRaises(ValueError):
                content_io.load_content(self.path, allowed_dir=self.directory)


class RenderSafetyTest(FileTestCase):
    def setUp(self):
        super().setUp()
        self.theme = render.load_theme(render.DEFAULT_THEME)
        self.stylesheet = render.build_stylesheet(self.theme, render.DEFAULT_CSS)

    def test_screen_and_print_margins_use_the_same_tokens(self):
        css = render.build_root_css(self.theme)
        for name in ("margin-top", "margin-side", "margin-bottom"):
            self.assertIn(f"--{name}: {self.theme['page'][name]};", css)

    def test_unknown_page_size_is_not_silently_a4(self):
        self.theme["page"]["size"] = "A5"
        with self.assertRaises(ValueError):
            render.build_root_css(self.theme)

    def test_unsafe_links_are_rendered_as_plain_text(self):
        for href in ("javascript:alert(1)", "data:text/html,bad", "file:///etc/passwd",
                     "java\nscript:alert(1)"):
            self.content["contacts"] = [{"value": "联系", "href": href}]
            with self.subTest(href=href):
                self.assertNotIn("<a ", render.ResumeBuilder(self.content, self.theme, self.stylesheet).identity_line())

    def test_overflow_does_not_replace_any_previous_artifact(self):
        for kind in ("html", "pdf", "png"):
            (self.directory / f"resume.{kind}").write_bytes(b"previous")
        self.content["experiences"] *= 6
        with self.assertRaises(RuntimeError):
            render.write_outputs(self.content, self.theme, self.stylesheet, self.directory, "resume")
        for kind in ("html", "pdf", "png"):
            self.assertEqual((self.directory / f"resume.{kind}").read_bytes(), b"previous")

    def test_png_failure_does_not_replace_any_previous_artifact(self):
        for kind in ("html", "pdf", "png"):
            (self.directory / f"resume.{kind}").write_bytes(b"previous")
        with mock.patch.object(render, "render_png", side_effect=subprocess.TimeoutExpired("pdftoppm", 60)):
            with self.assertRaises(subprocess.TimeoutExpired):
                render.write_outputs(self.content, self.theme, self.stylesheet, self.directory, "resume")
        for kind in ("html", "pdf", "png"):
            self.assertEqual((self.directory / f"resume.{kind}").read_bytes(), b"previous")

    def test_if_exists_fail_refuses_when_any_suffix_exists(self):
        for kind in ("html", "pdf", "png"):
            (self.directory / f"resume.{kind}").write_bytes(b"previous")
        with self.assertRaises(render.OutputExistsError) as caught:
            render.write_outputs(self.content, self.theme, self.stylesheet,
                                 self.directory, "resume", if_exists="fail")
        self.assertEqual(caught.exception.suggested, "resume-2.pdf")
        for kind in ("html", "pdf", "png"):
            self.assertEqual((self.directory / f"resume.{kind}").read_bytes(), b"previous")

    def test_if_exists_rename_picks_next_free_across_suffixes(self):
        # 只占着 .png：仍然要跳过这一号，否则会写出"新 PDF 配旧 PNG"
        (self.directory / "resume.png").write_bytes(b"previous")
        outputs = render.write_outputs(self.content, self.theme, self.stylesheet,
                                       self.directory, "resume", if_exists="rename")
        self.assertEqual(outputs["pdf"].name, "resume-2.pdf")
        self.assertEqual(outputs["html"].name, "resume-2.html")
        self.assertEqual((self.directory / "resume.png").read_bytes(), b"previous")

        (self.directory / "resume-2.html").write_bytes(b"previous")
        again = render.write_outputs(self.content, self.theme, self.stylesheet,
                                     self.directory, "resume", if_exists="rename")
        self.assertEqual(again["pdf"].name, "resume-3.pdf")

    def test_next_free_basename_starts_at_two(self):
        self.assertEqual(render.next_free_basename(self.directory, "never-used"), "never-used-2")

    def test_if_exists_overwrite_is_the_cli_default(self):
        self.assertEqual(render.parse_args([]).if_exists, "overwrite")
        self.assertEqual(render.parse_args(["--if-exists", "rename"]).if_exists, "rename")
        with self.assertRaises(SystemExit):
            render.parse_args(["--if-exists", "whatever"])

    def test_cli_renders_twice_and_fail_mode_exits_cleanly(self):
        out = self.directory / "cli-out"
        base = [sys.executable, str(ROOT / "render.py"),
                "--content", str(ROOT / "content.example.toml"),
                "--out-dir", str(out), "--name", "cli-test"]
        first = subprocess.run(base, capture_output=True, text=True, timeout=180)
        self.assertEqual(first.returncode, 0, first.stderr)
        second = subprocess.run(base, capture_output=True, text=True, timeout=180)
        self.assertEqual(second.returncode, 0, "默认应当覆盖，不该报错")
        third = subprocess.run([*base, "--if-exists", "fail"],
                               capture_output=True, text=True, timeout=180)
        self.assertNotEqual(third.returncode, 0)
        self.assertNotIn("Traceback", third.stderr + third.stdout)
        self.assertIn("--if-exists", third.stderr + third.stdout)

    def test_cli_and_browser_reject_path_like_basenames(self):
        for name in ("../escape", "/tmp/escape", "C:\\escape", "a/b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                render.write_outputs(self.content, self.theme, self.stylesheet, self.directory, name)


if __name__ == "__main__":
    unittest.main()


class SaveModeTest(FileTestCase):
    """三种保存方式 × 四种目标状态。

    内容层面的 12 格。第 13–15 格是"目标正好是仓库里那份示例"，
    那是 webui 的 PROTECTED_CONTENT 管的，见 test_webui 里的同一张表。
    """

    def variant(self) -> Path:
        path = self.directory / "content.variant.toml"
        path.write_text('extends = "content.toml"\n', encoding="utf-8")
        return path

    def test_save_modes_matrix(self):
        example = self.text
        changed = self.text.replace("两年英文网站内容", "改过的一句话")

        # (状态, 目标文件怎么准备, 该用哪个 revision 发出去)
        states = {
            "不存在": (lambda: self.path, None),
            "存在版本对": (lambda: self._fresh(example), "current"),
            "存在版本不符": (lambda: self._fresh(example), "stale"),
            "定制版": (self.variant, None),
        }
        # (方式, {状态: 期望})；期望是 True（成功）或异常类型
        expected = {
            "create": {"不存在": True, "存在版本对": content_io.ExistsError,
                       "存在版本不符": content_io.ExistsError,
                       "定制版": content_io.VariantError},
            "update": {"不存在": content_io.ModifiedError, "存在版本对": True,
                       "存在版本不符": content_io.ModifiedError,
                       "定制版": content_io.VariantError},
            "overwrite": {"不存在": True, "存在版本对": True,
                          "存在版本不符": True, "定制版": content_io.VariantError},
        }

        for state, (prepare, revision_kind) in states.items():
            for mode in ("create", "update", "overwrite"):
                with self.subTest(state=state, mode=mode):
                    target = prepare()
                    if revision_kind == "current":
                        revision = content_io.revision(target.read_bytes())
                    elif revision_kind == "stale":
                        revision = "deadbeef"
                    else:
                        revision = None
                    want = expected[mode][state]
                    if want is True:
                        result = content_io.save_content(target, changed, revision, mode=mode)
                        self.assertEqual(result.path.read_text(encoding="utf-8"), changed)
                    else:
                        before = target.read_bytes()
                        with self.assertRaises(want):
                            content_io.save_content(target, changed, revision, mode=mode)
                        self.assertEqual(target.read_bytes(), before, "被拒绝时不该动文件")

    def _fresh(self, text: str) -> Path:
        path = self.directory / "content.fresh.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_snapshot_is_written_before_overwrite(self):
        first = content_io.save_content(self.path, self.text, None)
        changed = self.text.replace("两年英文网站内容", "换一句话")
        result = content_io.save_content(self.path, changed, first.revision)
        self.assertIsNotNone(result.snapshot)
        self.assertEqual(result.snapshot.read_text(encoding="utf-8"), self.text)
        self.assertEqual(result.snapshot.parent, content_io.history_dir(self.path))

    def test_unchanged_save_writes_nothing(self):
        first = content_io.save_content(self.path, self.text, None)
        before = (self.path.stat().st_mtime_ns, self.path.read_bytes())
        again = content_io.save_content(self.path, self.text, first.revision)
        self.assertTrue(again.unchanged)
        self.assertIsNone(again.snapshot)
        self.assertEqual((self.path.stat().st_mtime_ns, self.path.read_bytes()), before)
        self.assertEqual(content_io.snapshot_files(self.path), [])

    def test_no_bak_is_written_anymore(self):
        first = content_io.save_content(self.path, self.text, None)
        content_io.save_content(self.path, self.text.replace("两年", "仨年"), first.revision)
        self.assertFalse(self.path.with_suffix(".toml.bak").exists())

    def test_history_is_pruned_to_keep(self):
        keep = 3
        revision = None
        for index in range(6):
            body = self.text.replace("两年英文网站内容", f"第 {index} 版")
            result = content_io.save_content(self.path, body, revision, mode=None)
            revision = result.revision
        content_io.prune_history(self.path, keep=keep)
        remaining = content_io.snapshot_files(self.path)
        self.assertEqual(len(remaining), keep)
        # 留下的必须是最近的那几份
        self.assertEqual(remaining, sorted(remaining)[-keep:])

    def test_snapshot_files_are_private(self):
        first = content_io.save_content(self.path, self.text, None)
        result = content_io.save_content(
            self.path, self.text.replace("两年", "仨年"), first.revision)
        self.assertEqual(result.snapshot.stat().st_mode & 0o777, 0o600)
        self.assertEqual(content_io.history_dir(self.path).stat().st_mode & 0o777, 0o700)
        # .history 这一层也必须是 700：否则同机器的其他用户能看到你有哪些内容文件
        self.assertEqual((self.directory / content_io.HISTORY_DIR).stat().st_mode & 0o777,
                         0o700)


class HistoryTest(FileTestCase):
    def test_history_id_gate_rejects_traversal(self):
        content_io.save_content(self.path, self.text, None)
        for bad in ("../content.toml", "a/b.toml", "..", "", "./x.toml",
                    "20260101T000000Z-deadbeef.toml.bak", "sub/20260101T000000Z-deadbeef.toml"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    content_io.read_history(self.path, bad)

    def test_a_well_formed_but_absent_id_is_not_found(self):
        with self.assertRaises(FileNotFoundError):
            content_io.read_history(self.path, "20260101T000000Z-deadbeef.toml")

    def test_list_history_is_newest_first(self):
        revision = None
        for index in range(3):
            result = content_io.save_content(
                self.path, self.text.replace("两年", f"{index}年"), revision)
            revision = result.revision
        versions = content_io.list_history(self.path)
        self.assertEqual(len(versions), 2)          # 第一次是新建，没有快照
        self.assertEqual([v["id"] for v in versions], sorted(v["id"] for v in versions)[::-1])
        for version in versions:
            self.assertGreater(version["size"], 0)
            self.assertGreater(version["time"], 0)


class NormalizeNameTest(unittest.TestCase):
    def test_normalize_content_name_table(self):
        table = {
            "acme": "content.acme.toml",
            "acme.toml": "content.acme.toml",
            "content.acme": "content.acme.toml",
            "content.acme.toml": "content.acme.toml",
            "content": "content.toml",
            "content.toml": "content.toml",
            "CONTENT": "content.toml",
            "Content.Acme.TOML": "content.Acme.toml",
            "  张三-简历  ": "content.张三-简历.toml",
            "content.local": "content.local.toml",
        }
        for raw, want in table.items():
            with self.subTest(raw=raw):
                self.assertEqual(content_io.normalize_content_name(raw), want)

    def test_normalize_rejects_names_the_gate_would_never_accept(self):
        for bad in ("", "   ", "a/b", "../x", "sub/x", "NUL.toml/x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                content_io.normalize_content_name(bad)
        with self.assertRaises(ValueError):
            content_io.normalize_content_name(None)

    def test_case_insensitive_collision_counts_as_exists(self):
        directory = Path(tempfile.mkdtemp())
        try:
            (directory / "content.Acme.toml").write_text("x = 1", encoding="utf-8")
            found = content_io.content_exists(directory, "content.acme.toml")
            self.assertIsNotNone(found, "只差大小写也算已存在，否则 Windows 上会覆盖")
            self.assertEqual(found.name, "content.Acme.toml")
            self.assertIsNone(content_io.content_exists(directory, "content.other.toml"))
        finally:
            shutil.rmtree(directory, ignore_errors=True)
