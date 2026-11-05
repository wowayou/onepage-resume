"""启动器实例协议和 stdin 生命线的真实子进程回归；不打开浏览器、不读真实简历。"""

from __future__ import annotations

import queue
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import webui

ROOT = Path(__file__).resolve().parent.parent
READY_PATH = "/__launcher/ready"
READY_HEADER = "X-Onepage-Resume-Ready"


class ChildSession:
    def __init__(self, directory: Path, launcher_id: str | None, *, preflight_pause=False):
        arguments = ["--port", "0", "--no-open", "--content-dir", str(directory),
                     "--out-dir", str(directory / "build")]
        if launcher_id is not None:
            arguments += ["--launcher-id", launcher_id]
        prefix = [sys.executable, "-u", "-X", "utf8"]
        if preflight_pause:
            code = ("import sys, time, webui\n"
                    "def pause(theme):\n"
                    "    print('PREFLIGHT', flush=True)\n"
                    "    time.sleep(60)\n"
                    "webui.render.check_fonts = pause\n"
                    "raise SystemExit(webui.main(sys.argv[1:]))\n")
            prefix += ["-c", code]
        else:
            prefix += [str(ROOT / "webui.py")]
        self.process = subprocess.Popen(
            prefix + arguments, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
        )
        self.launcher_id = launcher_id
        self.lines = []
        self.pending = queue.Queue()
        self.reader = threading.Thread(target=self.read_output, daemon=True)
        self.reader.start()

    def read_output(self):
        for line in self.process.stdout:
            self.lines.append(line)
            self.pending.put(line)
        self.pending.put(None)

    def wait_for(self, pattern: str):
        # 使用总期限，不能因持续收到无关日志而无限延长等待。
        deadline = time.monotonic() + 15
        while True:
            line = self.pending.get(timeout=max(0, deadline - time.monotonic()))
            if line is None:
                raise AssertionError("子进程提前退出：" + self.process.stderr.read())
            match = re.search(pattern, line)
            if match:
                return match

    def url(self):
        return self.wait_for(r"填空表单：\s+(http://127\.0\.0\.1:\d+)").group(1)

    def close_input(self):
        if not self.process.stdin.closed:
            self.process.stdin.close()

    def finish(self):
        code = self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        if self.reader.is_alive():
            raise AssertionError("子进程结束后输出管道没有关闭")
        return code, "".join(self.lines), self.process.stderr.read()

    def close(self):
        if self.process.poll() is None:
            if self.launcher_id is not None:
                self.close_input()
            else:
                self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()  # 只回收本测试创建的子进程。
                self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


class LauncherProtocolTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="resume-launcher-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def start(self, launcher_id: str | None, **kwargs):
        child = ChildSession(self.directory, launcher_id, **kwargs)
        self.addCleanup(child.close)
        return child

    def head(self, url: str, headers=None):
        request = urllib.request.Request(url + READY_PATH, method="HEAD", headers=headers or {})
        return self.opener.open(request, timeout=5)

    def test_ready_is_bound_to_each_instance_and_does_not_echo_request_ids(self):
        first, second = self.start("a" * 32), self.start("b" * 32)
        first_url, second_url = first.url(), second.url()
        for url, expected in ((first_url, "a" * 32), (second_url, "b" * 32)):
            with self.subTest(url=url), self.head(url, {READY_HEADER: "v1;" + "c" * 32}) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_all(READY_HEADER), ["v1;" + expected])
                self.assertEqual(response.headers["Content-Length"], "0")
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertEqual(response.read(), b"")
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.opener.open(url + READY_PATH, timeout=5)
            self.assertEqual(caught.exception.code, 404)

    def test_ready_keeps_host_and_origin_protection(self):
        child = self.start("a" * 32)
        url = child.url()
        for headers, status in (({"Host": "evil.example"}, 421),
                                ({"Origin": "https://evil.example"}, 403)):
            with self.subTest(headers=headers), self.assertRaises(urllib.error.HTTPError) as caught:
                self.head(url, headers)
            self.assertEqual(caught.exception.code, status)
            self.assertIsNone(caught.exception.headers.get(READY_HEADER))

    def test_ordinary_start_has_no_ready_identity_or_stdin_lifetime_change(self):
        child = self.start(None)
        url = child.url()
        child.close_input()
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.head(url)
        self.assertEqual(caught.exception.code, 404)
        self.assertIsNone(caught.exception.headers.get(READY_HEADER))
        self.assertIsNone(child.process.poll())
        child.process.send_signal(signal.SIGINT)
        self.assertEqual(child.finish()[0], 0)

    def test_parent_pipe_eof_stops_serving_and_releases_only_its_socket(self):
        child = self.start("a" * 32)
        url = child.url()
        port = int(url.rsplit(":", 1)[1])
        with self.head(url) as response:
            self.assertEqual(response.status, 200)
        child.close_input()
        code, stdout, stderr = child.finish()
        self.assertEqual(code, 0)
        self.assertIn("已停止", stdout)
        self.assertNotIn("Traceback", stderr)
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_parent_pipe_eof_during_preflight_returns_130_without_traceback(self):
        child = self.start("a" * 32, preflight_pause=True)
        child.wait_for("PREFLIGHT")
        child.close_input()
        code, stdout, stderr = child.finish()
        self.assertEqual(code, 130)
        self.assertIn("启动已取消", stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertNotIn("填空表单：", stdout)


class LauncherInputTest(unittest.TestCase):
    def test_eof_and_pipe_failure_cancel_only_the_current_process(self):
        for failure in (None, OSError("pipe closed")):
            done = threading.Event()
            with self.subTest(failure=failure), \
                 mock.patch.object(webui.sys, "stdin", mock.Mock()), \
                 mock.patch.object(webui.os, "read", return_value=b"", side_effect=failure), \
                 mock.patch.object(webui.os, "getpid", return_value=12345), \
                 mock.patch.object(webui.os, "kill") as kill:
                webui._watch_launcher_input(done)
                kill.assert_called_once_with(12345, signal.SIGINT)

    def test_completed_startup_does_not_receive_a_late_cancel_signal(self):
        done = threading.Event()
        done.set()
        with mock.patch.object(webui.sys, "stdin", mock.Mock()), \
             mock.patch.object(webui.os, "read", return_value=b""), \
             mock.patch.object(webui.os, "kill") as kill:
            webui._watch_launcher_input(done)
        kill.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
