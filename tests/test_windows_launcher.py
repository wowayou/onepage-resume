"""有界的 Windows->WSL 启动器集成测试。

仅在当前已是 WSL 且已有 Windows PowerShell 时运行；不执行 make boot、安装或开浏览器。
浏览器调用和键盘取消用替身，进程/管道/HTTP/退出码走真实控制器。仅回收本测试的进程。
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POWERSHELL = shutil.which("powershell.exe")
DISTRO = os.environ.get("WSL_DISTRO_NAME")


def windows_path(path: Path) -> str:
    return "\\\\wsl.localhost\\" + DISTRO + str(path).replace("/", "\\")


def ps_quote(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def powershell_arguments(code: str) -> list[str]:
    encoded = base64.b64encode(code.encode("utf-16le")).decode("ascii")
    return [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-EncodedCommand", encoded]


class ControllerSession:
    def __init__(self, directory: Path, port: int, *, timeout=15, extra=""):
        self.directory = directory
        self.stop_file = directory / "stop-controller"
        self.chunks = {"out": [], "err": []}
        self.port = port
        code = f"""
[Console]::WriteLine('OWNED_WINDOWS_PID=' + $PID + ';START=' + [Diagnostics.Process]::GetCurrentProcess().StartTime.Ticks)
$env:BASE={ps_quote(directory)}
$env:WSLDISTRO={ps_quote(DISTRO)}
$env:LINUXDIR={ps_quote(directory)}
$env:WEBUI_PORT={ps_quote(port)}
. {ps_quote(windows_path(ROOT / 'scripts/start-webui.ps1'))}
$script:openCount=0
function Start-Process {{ [CmdletBinding()]param([string]$FilePath) $script:openCount++; [Console]::WriteLine('BROWSER_CALL') }}
function Test-StopRequested {{ param([bool]$Enabled) return (Test-Path -LiteralPath {ps_quote(windows_path(self.stop_file))}) }}
{extra}
$rc=Invoke-WebUiController -StartupTimeoutSeconds {timeout}
[Console]::WriteLine('BROWSER_COUNT: '+$script:openCount)
exit $rc
"""
        self.process = subprocess.Popen(powershell_arguments(code), stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.readers = []
        for name, stream in (("out", self.process.stdout), ("err", self.process.stderr)):
            reader = threading.Thread(target=self.read_output, args=(name, stream), daemon=True)
            reader.start()
            self.readers.append(reader)

    def read_output(self, name, stream):
        while chunk := stream.read1(4096):
            self.chunks[name].append(chunk)

    def output(self, name="out"):
        return b"".join(self.chunks[name]).decode("utf-8", errors="replace")

    def wait_for(self, pattern: str):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            match = re.search(pattern, self.output())
            if match:
                return match
            if self.process.poll() is not None:
                raise AssertionError("控制器提前退出：" + self.output() + self.output("err"))
            time.sleep(0.02)
        raise AssertionError("等待控制器状态超时：" + self.output() + self.output("err"))

    def finish(self, timeout=20):
        code = self.process.wait(timeout=timeout)
        for reader in self.readers:
            reader.join(timeout=2)
            if reader.is_alive():
                raise AssertionError("控制器结束后管道没有关闭")
        return code, self.output(), self.output("err")

    def kill_owned_windows_parent(self):
        match = self.wait_for(r"OWNED_WINDOWS_PID=(\d+);START=(\d+)")
        pid, ticks = match.groups()
        # 时间戳和 PID 都来自此测试的活进程，防止错误回收或 PID 复用。
        code = (f"$p=[Diagnostics.Process]::GetProcessById({pid}); "
                f"if($p.StartTime.Ticks -ne {ticks}){{throw 'Process identity changed'}}; $p.Kill()")
        result = subprocess.run(powershell_arguments(code), capture_output=True, timeout=10)
        if result.returncode != 0 and self.process.poll() is None:
            raise AssertionError(result.stderr.decode("utf-8", errors="replace"))

    def close(self):
        if self.process.poll() is None:
            self.stop_file.touch()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.kill_owned_windows_parent()
                self.process.wait(timeout=5)
        for reader in self.readers:
            reader.join(timeout=2)
        match = re.search(r"OWNED_PYTHON_PID=(\d+)", self.output())
        if match:
            pid = int(match.group(1))
            try:
                # 本测试随机目录里的自有进程才能作为失败后的清理对象。
                if Path(f"/proc/{pid}/cwd").resolve() == self.directory:
                    os.kill(pid, signal.SIGTERM)
            except (OSError, RuntimeError):
                pass
        self.process.stdout.close()
        self.process.stderr.close()


class OtherService(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("X-Onepage-Resume-Ready", "v1;" + "0" * 32)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_HEAD

    def log_message(self, *_):
        pass


@unittest.skipUnless(DISTRO and POWERSHELL, "需要已就绪的 WSL + Windows PowerShell；不分配额外 runner")
class WindowsLauncherTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="resume window launcher ")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        (self.directory / ".venv").symlink_to(ROOT / ".venv", target_is_directory=True)

    def start(self, *, port=None, mode="normal", timeout=15, extra=""):
        if port is None:
            with socket.socket() as picker:
                picker.bind(("127.0.0.1", 0))
                port = picker.getsockname()[1]
        code = "import os, runpy, sys, time\nprint('OWNED_PYTHON_PID=' + str(os.getpid()), flush=True)\n"
        if mode == "slow-import":
            code += "time.sleep(60)\n"
        if mode == "early-exit":
            code += ("sys.stdout.write('x' * 4095 + '😀' + '输出' * 18000 + 'OUT_TAIL')\n"
                     "sys.stdout.flush()\n"
                     "sys.stderr.write('y' * 4095 + '🚀' + '错误' * 18000 + 'ERR_TAIL')\n"
                     "sys.stderr.flush()\nraise SystemExit(37)\n")
        code += (f"sys.path.insert(0, {str(ROOT)!r})\n"
                 f"sys.argv += ['--content-dir', {str(self.directory)!r}, '--out-dir', {str(self.directory / 'build')!r}]\n"
                 f"runpy.run_path({str(ROOT / 'webui.py')!r}, run_name='__main__')\n")
        (self.directory / "webui.py").write_text(code, encoding="utf-8")
        session = ControllerSession(self.directory, port, timeout=timeout, extra=extra)
        self.addCleanup(session.close)
        return session

    def other_service(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), OtherService)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def assert_child_gone(self, session):
        pid = session.wait_for(r"OWNED_PYTHON_PID=(\d+)").group(1)
        deadline = time.monotonic() + 5
        while Path(f"/proc/{pid}").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(Path(f"/proc/{pid}").exists(), "控制器退出后留下了本次 Python 服务")

    def assert_port_free(self, port):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))

    def test_other_http_200_cannot_mask_binding_failure_or_open_browser(self):
        other = self.other_service()
        session = self.start(port=other.server_port)
        code, stdout, stderr = session.finish()
        self.assertEqual(code, 1)
        self.assertIn("端口已被占用", stderr)
        self.assertIn("Child exited before readiness; exit code: 1", stderr)
        self.assertIn("BROWSER_COUNT: 0", stdout)
        self.assertNotIn("[onepage-resume] Ready:", stdout)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{other.server_port}/", timeout=2) as response:
            self.assertEqual(response.status, 200)

    def test_ready_and_controlled_stop_use_one_browser_call_and_release_socket(self):
        session = self.start()
        session.wait_for(r"\[onepage-resume\] Ready:")
        session.stop_file.touch()
        code, stdout, stderr = session.finish(timeout=5)
        self.assertEqual(code, 0, stderr)
        self.assertIn("BROWSER_COUNT: 1", stdout)
        self.assert_child_gone(session)
        self.assert_port_free(session.port)
        self.assertFalse((self.directory / "build").exists())

    def test_browser_launch_failure_keeps_the_service_available_for_manual_access(self):
        extra = """
function Start-Process {
    [CmdletBinding()]param([string]$FilePath)
    $script:openCount++
    throw ([System.ComponentModel.Win32Exception]::new(2))
}
"""
        session = self.start(extra=extra)
        session.wait_for(r"\[onepage-resume\] Ready:")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{session.port}/", timeout=2) as response:
            self.assertEqual(response.status, 200)
        session.stop_file.touch()
        code, stdout, stderr = session.finish(timeout=5)
        self.assertEqual(code, 0, stderr)
        self.assertIn("Please visit manually: ", stderr)
        self.assertIn("BROWSER_COUNT: 1", stdout)
        self.assert_child_gone(session)
        self.assert_port_free(session.port)

    def test_parent_hard_exit_closes_lifeline_and_releases_socket(self):
        session = self.start()
        session.wait_for(r"\[onepage-resume\] Ready:")
        session.kill_owned_windows_parent()
        session.finish(timeout=5)
        self.assert_child_gone(session)
        self.assert_port_free(session.port)

    def test_startup_cancel_cleans_up_even_before_application_imports(self):
        session = self.start(mode="slow-import")
        session.wait_for(r"OWNED_PYTHON_PID=\d+")
        session.stop_file.touch()
        code, stdout, _ = session.finish(timeout=5)
        self.assertEqual(code, 130)
        self.assertIn("BROWSER_COUNT: 0", stdout)
        self.assert_child_gone(session)
        self.assert_port_free(session.port)

    def test_early_failure_drains_both_unicode_tails_and_keeps_nonzero_status(self):
        session = self.start(mode="early-exit")
        code, stdout, stderr = session.finish()
        self.assertEqual(code, 1)
        self.assertIn("exit code: 37", stderr)
        self.assertIn("输出" * 18000 + "OUT_TAIL", stdout)
        self.assertIn("错误" * 18000 + "ERR_TAIL", stderr)
        self.assertIn("😀", stdout)
        self.assertIn("🚀", stderr)
        self.assertIn("BROWSER_COUNT: 0", stdout)
        self.assertNotIn("[onepage-resume] Ready:", stdout)

    def test_wrong_instance_response_times_out_without_reusing_other_service(self):
        other = self.other_service()
        extra = f"""
$script:originalRequest=(Get-Command New-ReadinessRequest).ScriptBlock
function New-ReadinessRequest {{
    param([string]$Uri, [int]$TimeoutMilliseconds)
    return (& $script:originalRequest -Uri 'http://127.0.0.1:{other.server_port}/__launcher/ready' -TimeoutMilliseconds $TimeoutMilliseconds)
}}
"""
        started = time.monotonic()
        session = self.start(timeout=10, extra=extra)
        code, stdout, stderr = session.finish(timeout=15)
        self.assertEqual(code, 1)
        self.assertIn("Startup timed out", stderr)
        self.assertIn("did not identify this launcher", stderr)
        self.assertIn("BROWSER_COUNT: 0", stdout)
        self.assertNotIn("[onepage-resume] Ready:", stdout)
        self.assertLess(time.monotonic() - started, 14)
        self.assert_child_gone(session)
        self.assert_port_free(session.port)


if __name__ == "__main__":
    unittest.main(verbosity=2)
