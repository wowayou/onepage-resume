"""webui.py 的测试。标准库 unittest，不引入新依赖。

    make test    或    .venv/bin/python -m unittest discover -s tests -v

盯的是几件会静默出错的事：
  · 路径闸门真的挡得住 ../ 和绝对路径（这是本服务唯一的文件边界）
  · 表单 JSON → TOML → 读回来，形状不变（网页和 fill.py 认同一份文件）
  · 预览确实走 render.py，且示例内容仍是一页
  · Host 头校验没被绕开（DNS 重绑定）
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import tomllib
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import content_io                                            # noqa: E402
import fill                                                  # noqa: E402
import render                                                # noqa: E402
import schema                                                # noqa: E402
import webui                                                 # noqa: E402

EXAMPLE = ROOT / "content.example.toml"


def example_content() -> dict:
    with EXAMPLE.open("rb") as stream:
        return tomllib.load(stream)


class DescribeTest(unittest.TestCase):
    """网页表单是照着 schema.describe() 长的，它得盖住全部字段。"""

    def test_covers_every_block_and_field(self):
        described = schema.describe()
        self.assertEqual(
            [b["key"] for b in described], [b.key for b in schema.BLOCKS]
        )
        for shown, block in zip(described, schema.BLOCKS):
            self.assertEqual(
                [f["key"] for f in shown["fields"]], [f.key for f in block.fields]
            )
            self.assertEqual(shown["repeat"], block.repeat)
            self.assertEqual(shown["section_key"], block.section_key)

    def test_is_json_serializable(self):
        json.dumps(schema.describe())          # 不抛异常就算过


class ShapeTest(unittest.TestCase):
    def test_splits_list_fields(self):
        shaped = webui.shape({"profile": {"name": "李四", "facts": ["北京", "可远程"]}})
        self.assertEqual(shaped["profile"]["facts"], ["北京", "可远程"])

    def test_rejects_string_for_list_field(self):
        with self.assertRaisesRegex(ValueError, "字符串数组"):
            webui.shape({"profile": {"facts": "北京"}})

    def test_fills_missing_blocks_without_inventing_content(self):
        shaped = webui.shape({})
        for block in schema.BLOCKS:
            self.assertIn(block.key, shaped)
        self.assertEqual(shaped["profile"]["name"], "")
        self.assertEqual(shaped["experiences"], [])
        # 空着的就该被报成空白，不能被默认值糊过去
        self.assertTrue(schema.find_blanks(shaped))

    def test_uses_section_default_when_title_missing(self):
        shaped = webui.shape({})
        self.assertEqual(shaped["skills_section"]["title"], "核心能力")

    def test_keeps_status_from_loaded_file(self):
        shaped = webui.shape({"document": {"status": "example"}})
        self.assertEqual(shaped["document"]["status"], "example")

    def test_rejects_non_dict_rows(self):
        with self.assertRaisesRegex(ValueError, "必须是表"):
            webui.shape({"skills": ["不是表", {"label": "SEO", "text": "关键词"}]})

    def test_keeps_blank_entries_visible_to_validation(self):
        shaped = webui.shape({"experiences": [{"bullets": ["做了事", "  ", ""]}]})
        self.assertEqual(shaped["experiences"][0]["bullets"], ["做了事", "  ", ""])
        self.assertTrue(any("bullets[2]" in blank for blank in schema.find_blanks(shaped)))

    def test_explicit_empty_section_title_is_not_replaced(self):
        shaped = webui.shape({"skills_section": {"title": ""}})
        self.assertEqual(shaped["skills_section"]["title"], "")
        self.assertTrue(any("skills_section" in blank for blank in schema.find_blanks(shaped)))


class PreviewShapeTest(unittest.TestCase):
    def test_adds_placeholder_row_so_skeleton_renders(self):
        preview = webui.for_preview(webui.shape({}))
        self.assertEqual(len(preview["experiences"]), 1)
        self.assertEqual(preview["experiences"][0]["company"], "")

    def test_does_not_touch_caller_dict(self):
        shaped = webui.shape({})
        webui.for_preview(shaped)
        self.assertEqual(shaped["experiences"], [])

    def test_footer_is_empty_for_what_you_see_is_what_you_get(self):
        preview = webui.for_preview(webui.shape({}))
        self.assertEqual(preview["document"]["preview_note"], "")
        self.assertEqual(preview["document"]["edition"], "")


class RoundTripTest(unittest.TestCase):
    """示例内容跑一圈：读 → shape → dump_toml → 再读，字段不许漂移。"""

    def test_example_survives_a_round_trip(self):
        original = example_content()
        reloaded = tomllib.loads(fill.dump_toml(webui.shape(original)))

        self.assertEqual(schema.find_blanks(reloaded), [])
        self.assertEqual(reloaded["profile"]["name"], original["profile"]["name"])
        self.assertEqual(len(reloaded["experiences"]), len(original["experiences"]))
        self.assertEqual(
            reloaded["experiences"][0]["bullets"], original["experiences"][0]["bullets"]
        )
        self.assertEqual(reloaded["education"]["items"], original["education"]["items"])

    def test_round_trip_keeps_example_status(self):
        reloaded = tomllib.loads(fill.dump_toml(webui.shape(example_content())))
        self.assertEqual(reloaded["document"]["status"], "example")


class ListSeparatorTest(unittest.TestCase):
    """数组字段的分隔符只认带空白的斜杠，网址才能整条写进去。

    盯的是一趟「表单里显示 → 存回去」：光按 "/" 切，crumbs 里的
    github.com/某账号/某仓库 会被拆成三段，而示例文件里正有这么一条——也就是说
    仓库自带的内容都过不了这一趟，而纸面上只是多出两个 › ，很容易看漏。
    webui/app.js 里的 LIST_SEP 必须和这里保持同一条规则。
    """

    def display(self, items: list[str]) -> str:
        # app.js 的 toInput()：数组用 " / " 拼给输入框
        return " / ".join(items)

    def test_a_url_crumb_survives_display_then_reparse(self):
        original = ["Python", "github.com/example/site-monitor"]
        self.assertEqual(fill.split_list(self.display(original)), original)

    def test_plain_crumbs_still_split(self):
        self.assertEqual(fill.split_list("a / b / c"), ["a", "b", "c"])

    def test_a_slash_with_whitespace_on_either_side_splits(self):
        for text in ("a/ b", "a /b", "a  /  b"):
            with self.subTest(text=text):
                self.assertEqual(fill.split_list(text), ["a", "b"])

    def test_a_bare_slash_does_not_split(self):
        # 网址、日期、mailto: 里的斜杠都长这样
        self.assertEqual(fill.split_list("github.com/a/b"), ["github.com/a/b"])
        self.assertEqual(fill.split_list("https://x.com/a/b"), ["https://x.com/a/b"])

    def test_every_list_field_in_the_example_survives(self):
        content = example_content()
        for block in schema.BLOCKS:
            for field in block.fields:
                if field.kind != "list":
                    continue
                node = content.get(block.key)
                entries = node if isinstance(node, list) else [node] if node else []
                for index, entry in enumerate(entries):
                    if not isinstance(entry, dict) or field.key not in entry:
                        continue
                    original = entry[field.key]
                    with self.subTest(where=f"{block.key}[{index}].{field.key}"):
                        self.assertEqual(
                            fill.split_list(self.display(original)), original
                        )


class PathGateTest(unittest.TestCase):
    """这个服务唯一的文件边界。挡不住就等于把整个磁盘开给了浏览器。"""

    def test_accepts_a_plain_matching_name(self):
        path = webui.safe_name("content.toml", webui.CONTENT_GLOB, ROOT)
        self.assertEqual(path, (ROOT / "content.toml").resolve())

    def test_rejects_traversal_and_absolute_paths(self):
        for bad in ("../content.toml", "sub/content.toml", "/etc/content.toml",
                    "content.toml/../../content.toml", ".content.toml", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    webui.safe_name(bad, webui.CONTENT_GLOB, ROOT)

    def test_rejects_names_outside_the_glob(self):
        for bad in ("theme.toml", "schema.py", "notes.txt", "content.toml.bak"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    webui.safe_name(bad, webui.CONTENT_GLOB, ROOT)

    def test_basename_cannot_escape_the_output_dir(self):
        self.assertEqual(webui.safe_basename("张三-SEO-简历"), "张三-SEO-简历")
        for name in ("../../etc/passwd", "   ", "...", "a/b", "a\\b", "C:resume", "NUL"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                webui.safe_basename(name)


class DispositionTest(unittest.TestCase):
    def test_non_ascii_name_gets_an_ascii_fallback_and_utf8_form(self):
        header = webui.disposition("张三-简历.pdf")
        self.assertIn("filename*=UTF-8''", header)
        self.assertIn(".pdf", header)
        header.encode("latin-1")           # HTTP 头必须能进 latin-1

    def test_inline_switches_only_the_disposition_kind(self):
        inline = webui.disposition("张三-简历.pdf", inline=True)
        self.assertTrue(inline.startswith("inline; "))
        self.assertIn("filename*=UTF-8''", inline)
        self.assertTrue(webui.disposition("张三-简历.pdf").startswith("attachment; "))


class OpenBrowserTest(unittest.TestCase):
    """WSL 里不能信 webbrowser：它挑 xdg-open，失败了也返回 True。

    所以 _open_browser 在 WSL 下要自己调 Windows 那边并看退出码。这里盯的是
    「开不成时必须返回 False」——谎报成功会让人对着空白桌面等一个不会来的窗口。
    """

    URL = "http://127.0.0.1:8765"

    def test_wsl_is_detected_from_the_env_var(self):
        with mock.patch.dict(webui.os.environ, {"WSL_DISTRO_NAME": "Ubuntu-24.04"}):
            self.assertTrue(webui._in_wsl())

    def test_wsl_prefers_wslview_and_reports_success(self):
        calls = []

        def which(name):
            return "/usr/bin/wslview" if name == "wslview" else None

        def run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0)

        with mock.patch.object(webui, "_in_wsl", return_value=True), \
             mock.patch.object(webui.shutil, "which", which), \
             mock.patch.object(webui.subprocess, "run", run):
            self.assertTrue(webui._open_browser(self.URL))
        self.assertEqual(calls, [["wslview", self.URL]])

    def test_wsl_falls_back_to_powershell_when_wslview_fails(self):
        calls = []

        def run(argv, **kwargs):
            calls.append(argv[0])
            return subprocess.CompletedProcess(argv, 0 if "powershell" in argv[0] else 3)

        with mock.patch.object(webui, "_in_wsl", return_value=True), \
             mock.patch.object(webui.shutil, "which", lambda name: "/x/" + name), \
             mock.patch.object(webui.subprocess, "run", run):
            self.assertTrue(webui._open_browser(self.URL))
        self.assertEqual(calls, ["wslview", "powershell.exe"])

    def test_wsl_returns_false_when_every_opener_fails(self):
        def run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 3)

        with mock.patch.object(webui, "_in_wsl", return_value=True), \
             mock.patch.object(webui.shutil, "which", lambda name: "/x/" + name), \
             mock.patch.object(webui.subprocess, "run", run):
            self.assertFalse(webui._open_browser(self.URL))

    def test_wsl_returns_false_when_no_opener_exists(self):
        with mock.patch.object(webui, "_in_wsl", return_value=True), \
             mock.patch.object(webui.shutil, "which", lambda name: None):
            self.assertFalse(webui._open_browser(self.URL))

    def test_non_wsl_goes_through_webbrowser(self):
        with mock.patch.object(webui, "_in_wsl", return_value=False), \
             mock.patch.object(webui.webbrowser, "open", return_value=True) as opened:
            self.assertTrue(webui._open_browser(self.URL))
        opened.assert_called_once_with(self.URL, new=2)

    def test_a_raising_webbrowser_is_not_reported_as_success(self):
        with mock.patch.object(webui, "_in_wsl", return_value=False), \
             mock.patch.object(webui.webbrowser, "open", side_effect=OSError("no display")):
            self.assertFalse(webui._open_browser(self.URL))


class ServerTestCase(unittest.TestCase):
    """起一个真的 HTTP 服务，按端口 0 让内核挑空闲端口。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        (cls.dir / "content.toml").write_text(
            EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8"
        )
        studio = webui.Studio(
            content_dir=cls.dir,
            out_dir=cls.dir / "build",
            css_path=render.DEFAULT_CSS,
        )
        handler = type("T", (webui.Handler,),
                       {"studio": studio, "bind_host": "127.0.0.1"})
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.tmp.cleanup()

    def get(self, path: str, host: str | None = None):
        request = urllib.request.Request(self.base + path)
        if host:
            request.add_header("Host", host)
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read(), response.headers

    def post(self, path: str, payload: dict, headers: dict | None = None):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read())

    def json_get(self, path: str):
        status, body, _ = self.get(path)
        return status, json.loads(body)


class HttpTest(ServerTestCase):
    def test_index_and_static_are_served(self):
        status, body, _ = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"<title>", body)
        for name in ("/static/app.css", "/static/app.js"):
            with self.subTest(name=name):
                self.assertEqual(self.get(name)[0], 200)

    def test_static_refuses_traversal(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/static/../render.py")
        self.assertIn(caught.exception.code, (400, 404))

    def test_bootstrap_carries_the_field_table(self):
        status, payload = self.json_get("/api/bootstrap")
        self.assertEqual(status, 200)
        self.assertEqual(
            [b["key"] for b in payload["blocks"]], [b.key for b in schema.BLOCKS]
        )
        self.assertIn("content.toml", payload["contents"])
        self.assertIn("theme.toml", payload["themes"])
        self.assertIn(render.EXAMPLE_CONTENT, payload["protected"])
        self.assertEqual(payload["default_content_name"],
                         content_io.DEFAULT_CONTENT_NAME)

    def test_reads_a_content_file(self):
        status, payload = self.json_get("/api/content?name=content.toml")
        self.assertEqual(status, 200)
        self.assertEqual(payload["blanks"], [])
        self.assertTrue(payload["writable"])
        self.assertEqual(payload["content"]["profile"]["name"], "张三")

    def test_refuses_to_read_outside_the_content_dir(self):
        for bad in ("../render.py", "/etc/passwd", "theme.toml"):
            with self.subTest(bad=bad):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    self.get("/api/content?name=" + urllib.parse.quote(bad))
                self.assertEqual(caught.exception.code, 400)

    def test_bad_host_header_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/api/bootstrap", host="evil.example.com")
        self.assertEqual(caught.exception.code, 421)

    def test_localhost_host_header_is_fine(self):
        self.assertEqual(self.get("/api/bootstrap", host="localhost")[0], 200)

    def test_malformed_and_foreign_hosts_are_rejected(self):
        for host in ("localhost:bad", "localhost:1", "localhost@evil.example.com",
                     "localhost/extra", "[::1]junk", "localhost#fragment"):
            with self.subTest(host=host), self.assertRaises(urllib.error.HTTPError) as caught:
                self.get("/api/bootstrap", host=host)
            self.assertEqual(caught.exception.code, 421)

    def test_cross_origin_writes_are_rejected(self):
        for origin in ("https://evil.example.com", "null", "http://localhost:1"):
            with self.subTest(origin=origin), self.assertRaises(urllib.error.HTTPError) as caught:
                self.post("/api/save", {"name": "content.csrf.toml", "content": {}},
                          headers={"Origin": origin})
            self.assertEqual(caught.exception.code, 403)
        self.assertFalse((self.dir / "content.csrf.toml").exists())

    def test_text_plain_json_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/save", {"content": {}}, headers={"Content-Type": "text/plain"})
        self.assertEqual(caught.exception.code, 400)

    def test_same_origin_json_is_accepted(self):
        status, _ = self.post("/api/save", {"name": "content.origin.toml", "content": {}},
                              headers={"Origin": self.base})
        self.assertEqual(status, 200)

    def test_privacy_headers_are_present(self):
        _, _, headers = self.get("/")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_bad_content_shapes_return_400(self):
        for content in (None, [], "bad", {"skills": [1]}, {"profile": {"name": 5}},
                        {"skills_section": ["bad"]}, {"profile": {"facts": [None]}},
                        {"profile": {"name": "\ud800"}}, {"unknown": {}}):
            with self.subTest(content=content), self.assertRaises(urllib.error.HTTPError) as caught:
                self.post("/api/preview", {"content": content})
            self.assertEqual(caught.exception.code, 400)

    def test_invalid_inheritance_returns_json_without_dropping_connection(self):
        variants = {
            "missing": 'extends = "content.absent.toml"',
            "cycle": 'extends = "content.cycle.toml"',
            "empty": 'extends = ""',
            "type": 'extends = ["content.toml"]',
            "outside": 'extends = "../content.toml"',
            "glob": 'extends = "theme.toml"',
            "keep": '[keep]\nskills = ["不存在"]',
        }
        for name, text in variants.items():
            (self.dir / f"content.{name}.toml").write_text(text, encoding="utf-8")
            with self.subTest(name=name), self.assertRaises(urllib.error.HTTPError) as caught:
                self.get(f"/api/content?name=content.{name}.toml")
            self.assertEqual(caught.exception.code, 400)
            self.assertIn("error", json.loads(caught.exception.read()))
        self.assertEqual(self.get("/api/bootstrap")[0], 200)

    def test_variant_is_read_only(self):
        path = self.dir / "content.variant.toml"
        path.write_text('extends = "content.toml"\n[profile]\nintent = "新意向"', encoding="utf-8")
        _, loaded = self.json_get("/api/content?name=content.variant.toml")
        self.assertFalse(loaded["writable"])
        self.assertEqual(loaded["content"]["profile"]["intent"], "新意向")
        original = path.read_bytes()
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/save", {"name": path.name, "revision": loaded["revision"],
                                   "content": loaded["content"]})
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(path.read_bytes(), original)


class PreviewApiTest(ServerTestCase):
    def test_example_content_previews_as_one_page(self):
        status, payload = self.post(
            "/api/preview", {"content": example_content(), "theme": "theme.toml"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["pages"], 1)
        self.assertEqual(payload["blanks"], [])
        self.assertIn("张三", payload["html"])
        self.assertEqual(payload["preview_mode"], "pdf")
        self.assertIn("data:image/png;base64,", payload["preview_html"])
        self.assertAlmostEqual(payload["width"], 210 * 96 / 25.4)

    def test_missing_converter_is_explicitly_approximate(self):
        with mock.patch.object(webui.shutil, "which", return_value=None):
            _, payload = self.post("/api/preview", {"content": example_content()})
        self.assertEqual(payload["preview_mode"], "html")
        self.assertNotIn("preview_html", payload)
        self.assertEqual(payload["pages"], 1)

    def test_overflow_preview_shows_two_actual_pages(self):
        content = example_content()
        content["experiences"] *= 3
        _, payload = self.post("/api/preview", {"content": content})
        self.assertGreater(payload["pages"], 1)
        self.assertEqual(payload["shown_pages"], 2)
        self.assertEqual(payload["preview_html"].count("data:image/png;base64,"), 2)

    def test_empty_form_still_previews_and_reports_blanks(self):
        status, payload = self.post("/api/preview", {"content": {}})
        self.assertEqual(status, 200)
        self.assertEqual(payload["pages"], 1)
        self.assertTrue(payload["blanks"])

    def test_english_theme_is_selectable(self):
        status, payload = self.post(
            "/api/preview", {"content": example_content(), "theme": "theme.en.toml"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["pages"], 1)

    def test_unknown_theme_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/preview",
                      {"content": example_content(), "theme": "../etc/theme.toml"})
        self.assertEqual(caught.exception.code, 400)


class SaveApiTest(ServerTestCase):
    def test_saves_and_backs_up(self):
        payload = {"name": "content.acme.toml", "content": example_content()}
        status, first = self.post("/api/save", payload)
        self.assertEqual(status, 200)
        self.assertIsNone(first["backup"])
        self.assertTrue((self.dir / "content.acme.toml").exists())

        _, second = self.post("/api/save", {**payload, "revision": first["revision"]})
        self.assertEqual(second["backup"], "content.acme.toml.bak")

    def test_stale_save_is_rejected_without_touching_file_or_backup(self):
        payload = {"name": "content.conflict.toml", "content": example_content()}
        _, first = self.post("/api/save", payload)
        payload["content"]["summary"]["text"] = "其他窗口的新内容"
        _, second = self.post("/api/save", {**payload, "revision": first["revision"]})
        path = self.dir / payload["name"]
        backup = path.with_suffix(".toml.bak")
        before = (path.read_bytes(), backup.read_bytes())
        for revision in (None, first["revision"]):
            with self.subTest(revision=revision), self.assertRaises(urllib.error.HTTPError) as caught:
                self.post("/api/save", {**payload, "revision": revision})
            self.assertEqual(caught.exception.code, 409)
            self.assertEqual((path.read_bytes(), backup.read_bytes()), before)
        self.assertNotEqual(first["revision"], second["revision"])

    def test_multiline_text_survives_save_and_reload(self):
        content = example_content()
        content["summary"]["text"] = '第一行\n第二行\r\n引号 " 与 \\ 制表符\t和 \x7f 😀'
        self.post("/api/save", {"name": "content.multiline.toml", "content": content})
        _, loaded = self.json_get("/api/content?name=content.multiline.toml")
        self.assertEqual(loaded["content"]["summary"]["text"], content["summary"]["text"])

    def test_saved_file_is_valid_toml_with_no_blanks(self):
        self.post("/api/save", {"name": "content.round.toml",
                                "content": example_content()})
        with (self.dir / "content.round.toml").open("rb") as stream:
            reloaded = tomllib.load(stream)
        self.assertEqual(schema.find_blanks(reloaded), [])

    def test_refuses_to_overwrite_the_tracked_example(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/save", {"name": render.EXAMPLE_CONTENT,
                                    "content": example_content()})
        self.assertEqual(caught.exception.code, 400)

    def test_refuses_a_name_outside_the_glob(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/save", {"name": "notes.toml",
                                    "content": example_content()})
        self.assertEqual(caught.exception.code, 400)


class RenderApiTest(ServerTestCase):
    def test_renders_pdf_and_serves_it_back(self):
        status, payload = self.post(
            "/api/render",
            {"content": example_content(), "theme": "theme.toml",
             "basename": "网页版-简历"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["files"]["pdf"], "网页版-简历.pdf")
        self.assertTrue((self.dir / "build" / "网页版-简历.pdf").exists())

        name = urllib.parse.quote(payload["files"]["pdf"])
        status, body, headers = self.get("/api/artifact?name=" + name)
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"%PDF"))
        self.assertIn("attachment", headers["Content-Disposition"])

    def test_refuses_to_render_with_blanks(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/render", {"content": {}})
        self.assertEqual(caught.exception.code, 400)
        self.assertIn("空白", caught.exception.read().decode("utf-8"))

    def test_reports_overflow_instead_of_writing_two_pages(self):
        content = example_content()
        content["experiences"] = content["experiences"] * 6      # 硬撑到第二页
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/render", {"content": content})
        self.assertEqual(caught.exception.code, 422)
        self.assertIn("一页", caught.exception.read().decode("utf-8"))

    def test_artifact_inlines_pdf_and_png_but_never_html(self):
        _, payload = self.post(
            "/api/render",
            {"content": example_content(), "theme": "theme.toml", "basename": "内联-简历"},
        )
        files = {kind: name for kind, name in payload["files"].items() if name}
        self.assertIn("pdf", files)
        self.assertIn("html", files)
        for kind, expected in (("pdf", "inline"), ("png", "inline"), ("html", "attachment")):
            if kind not in files:
                continue
            name = urllib.parse.quote(files[kind])
            with self.subTest(kind=kind):
                _, _, headers = self.get(f"/api/artifact?name={name}&inline=1")
                self.assertTrue(headers["Content-Disposition"].startswith(expected),
                                headers["Content-Disposition"])
        _, _, headers = self.get("/api/artifact?name=" + urllib.parse.quote(files["pdf"]))
        self.assertTrue(headers["Content-Disposition"].startswith("attachment"))

    def test_artifact_refuses_traversal_and_other_suffixes(self):
        for bad in ("../render.py", "/etc/passwd", "resume.toml"):
            with self.subTest(bad=bad):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    self.get("/api/artifact?name=" + urllib.parse.quote(bad))
                self.assertIn(caught.exception.code, (400, 404))


if __name__ == "__main__":
    unittest.main(verbosity=2)
