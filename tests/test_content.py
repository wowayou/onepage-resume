"""字段契约、无损序列化、继承边界与失败不破坏旧文件的回归测试。"""

from __future__ import annotations

import copy
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
    def test_create_and_backup_are_exact(self):
        backup, revision = content_io.save_content(self.path, self.text, None)
        self.assertIsNone(backup)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.content["summary"]["text"] = "修改后的正文"
        modified = fill.dump_toml(self.content)
        backup, new_revision = content_io.save_content(self.path, modified, revision)
        self.assertEqual(backup.read_text(encoding="utf-8"), self.text)
        self.assertEqual(self.path.read_text(encoding="utf-8"), modified)
        self.assertNotEqual(revision, new_revision)

    def test_failed_replacement_keeps_old_file(self):
        _, revision = content_io.save_content(self.path, self.text, None)
        with mock.patch.object(Path, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                content_io.save_content(self.path, self.text, revision)
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.text)
        self.assertEqual(list(self.directory.glob(".*")), [])

    def test_invalid_toml_never_touches_existing_file(self):
        _, revision = content_io.save_content(self.path, self.text, None)
        with self.assertRaises(ValueError):
            content_io.save_content(self.path, 'broken = "', revision)
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.text)
        self.assertFalse(self.path.with_suffix(".toml.bak").exists())

    def test_backup_symlink_cannot_overwrite_another_file(self):
        _, revision = content_io.save_content(self.path, self.text, None)
        target = self.directory / "outside.txt"
        target.write_text("untouched", encoding="utf-8")
        self.path.with_suffix(".toml.bak").symlink_to(target)
        with self.assertRaises(ValueError):
            content_io.save_content(self.path, self.text, revision)
        self.assertEqual(target.read_text(), "untouched")
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

    def test_cli_and_browser_reject_path_like_basenames(self):
        for name in ("../escape", "/tmp/escape", "C:\\escape", "a/b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                render.write_outputs(self.content, self.theme, self.stylesheet, self.directory, name)


if __name__ == "__main__":
    unittest.main()
