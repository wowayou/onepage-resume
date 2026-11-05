"""Launcher contracts; helper tests never run the controller or start WSL/a service.

Linux always runs the static checks. If PowerShell is already available, dot-source
only the helpers and test argv, request configuration and in-memory pipe draining.
No WSL, HTTP requests, browser, installations or third-party dependencies are used.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "start-webui.ps1"
# WSL may expose Windows powershell.exe too: the harness passes source and data
# through stdin rather than assuming that OS paths or environment cross that boundary.
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh")


def function_body(text: str, name: str) -> str:
    match = re.search(rf"(?ms)^function {re.escape(name)} \{{(.*?)(?=^function |^# Dot-source|\Z)", text)
    if not match:
        raise AssertionError(f"Missing PowerShell function: {name}")
    return match.group(1)


class StartWebUiStaticTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="ascii")
        cls.controller = function_body(cls.text, "Invoke-WebUiController")
        cls.code = "\n".join(line for line in cls.text.splitlines() if not line.lstrip().startswith("#"))

    def test_ascii_and_windows_powershell_51_compatibility(self):
        self.assertTrue(SCRIPT.read_bytes().isascii())
        self.assertTrue(self.text.startswith("#requires -Version 5.1\n"))
        self.assertNotRegex(self.code, r"\.ArgumentList\b|\?\?|ForEach-Object\s+-Parallel|Start-ThreadJob")
        self.assertNotIn("Set-ExecutionPolicy", self.code)

    def test_one_direct_wsl_child_with_the_full_python_contract(self):
        arguments = function_body(self.text, "Get-WebUiArguments")
        self.assertIn("$prefix = @('-d', $Distro)", arguments)
        self.assertIn("$directory = $LinuxDirectory", arguments)
        self.assertIn("$directory = $Base", arguments)
        self.assertRegex(arguments, re.compile(
            r"'--cd', \$directory, '-e', '\.venv/bin/python', '-u', '-X', 'utf8',\s*"
            r"'webui.py', '--host', '127\.0\.0\.1', '--port',\s*"
            r"\$Port\.ToString\([^\n]+\),\s*'--no-open', '--launcher-id', \$LauncherId", re.S))
        self.assertEqual(self.code.count("$process.Start()"), 1)
        self.assertEqual(self.code.count("$info.FileName = 'wsl.exe'"), 1)
        self.assertIn("$info.UseShellExecute = $false", self.controller)
        self.assertIn("$info.Arguments = Join-NativeArguments -Values $arguments", self.controller)
        self.assertNotRegex(self.code, r"bash|cmd\.exe|Start-Job|Register-ObjectEvent")

    def test_native_argv_quoting_handles_quotes_and_trailing_backslashes(self):
        quote = function_body(self.text, "ConvertTo-NativeArgument")
        self.assertIn("[regex]::IsMatch($Value, '[\\s\"]')", quote)
        self.assertIn("$character -eq [char]92", quote)
        self.assertIn("$character -eq [char]34", quote)
        self.assertIn("('\\' * (2 * $backslashes + 1))", quote)
        self.assertIn("('\\' * (2 * $backslashes))", quote)
        self.assertIn("return $Value", quote)  # Simple -d Ubuntu must not acquire literal quotes.
        self.assertIn("ConvertTo-NativeArgument $value", function_body(self.text, "Join-NativeArguments"))

    def test_fresh_lowercase_id_is_bound_to_cli_and_exact_response_header(self):
        self.assertIn("$launcherId = [Guid]::NewGuid().ToString('N')", self.controller)
        self.assertIn("[ValidatePattern('(?-i)\\A[0-9a-f]{32}\\z')]", self.text)
        self.assertIn("-LauncherId $launcherId", self.controller)
        self.assertIn("$expectedHeader = 'v1;' + $launcherId", self.controller)
        self.assertIn("$readyUri = 'http://127.0.0.1:{0}/__launcher/ready' -f $port", self.controller)
        response = function_body(self.text, "Test-ReadyResponse")
        self.assertIn("$Response.StatusCode -eq [System.Net.HttpStatusCode]::OK", response)
        self.assertIn("[string]::Equals($Response.Headers['X-Onepage-Resume-Ready']", response)
        self.assertIn("$ExpectedHeader, [System.StringComparison]::Ordinal", response)
        self.assertNotRegex(response, r"-match|-like|OrdinalIgnoreCase|ToLower|Trim")
        # No query/request marker protocol: identity comes only from the bound Python handler.
        request = function_body(self.text, "New-ReadinessRequest")
        self.assertNotIn("launcherId", request)
        self.assertNotIn("ExpectedHeader", request)

    def test_head_disables_proxy_redirects_and_caching_and_never_reads_body(self):
        request = function_body(self.text, "New-ReadinessRequest")
        for setting in ("$request.Method = 'HEAD'", "$request.Proxy = $null",
                        "$request.AllowAutoRedirect = $false", "$request.KeepAlive = $false",
                        "$request.MaximumResponseHeadersLength = 16",
                        "[System.Net.Cache.RequestCacheLevel]::NoCacheNoStore",
                        "$request.Headers['Cache-Control'] = 'no-cache, no-store'",
                        "$request.Timeout = $TimeoutMilliseconds",
                        "$request.ReadWriteTimeout = $TimeoutMilliseconds"):
            self.assertIn(setting, request)
        self.assertNotRegex(self.code, r"GetResponseStream|ReadToEnd|Invoke-WebRequest|\.GetResponse\(")
        self.assertIn("$response = $exception.Response", self.controller)
        self.assertIn("if ($null -ne $response) { $response.Close() }", self.controller)

    def test_readiness_and_child_liveness_both_gate_the_only_browser_open(self):
        self.assertEqual(self.code.count("Start-Process"), 1)
        self.assertRegex(self.controller, re.compile(
            r"if \(\$identityMatched -and -not \$process\.HasExited\) \{\s*"
            r"\$ready = \$true\s*if \(-not \$NoOpen\) \{\s*try \{ Start-Process -FilePath \$browserUri -ErrorAction Stop \}", re.S))
        self.assertIn("catch [System.ComponentModel.Win32Exception], [System.InvalidOperationException]", self.controller)
        self.assertIn("Please visit manually: ", self.controller)
        self.assertIn("$identityMatched = Test-ReadyResponse -Response $response -ExpectedHeader $expectedHeader",
                      self.controller)
        loop = self.controller[self.controller.index("while ($true)"):]
        self.assertLess(loop.index("Test-StopRequested"), loop.index("Start-Process"))
        self.assertLess(loop.index("if ($process.HasExited)"), loop.index("Start-Process"))
        self.assertIn("if ($ready) { [System.Threading.Thread]::Sleep(20); continue }", loop)

    def test_both_utf8_pipes_start_async_before_supervision_and_drain_bounded_chunks(self):
        for stream in ("Output", "Error"):
            self.assertIn(f"$info.RedirectStandard{stream} = $true", self.controller)
            self.assertIn(f"$info.Standard{stream}Encoding = $utf8", self.controller)
            self.assertLess(self.controller.index(f"New-OutputDrain -Reader $process.Standard{stream}"),
                            self.controller.index("while ($true)"))
        self.assertIn("New-Object System.Text.UTF8Encoding -ArgumentList $false", self.controller)
        self.assertIn("New-Object char[] 4096", function_body(self.text, "New-OutputDrain"))
        drain = function_body(self.text, "Write-ProcessOutput")
        self.assertIn("foreach ($drain in $Drains)", drain)
        self.assertIn("$block -lt 4", drain)
        self.assertLess(drain.index("$drain.Pending.IsCompleted"), drain.index("GetAwaiter().GetResult()"))
        self.assertIn("$drain.Writer.Write($drain.Buffer, 0, $count)", drain)
        self.assertIn("$drain.Reader.ReadAsync($drain.Buffer, 0, $drain.Buffer.Length)", drain)
        self.assertNotRegex(self.code, r"ReadLine|BeginOutputReadLine|BeginErrorReadLine")
        # Flush at EOF only, not between halves of a UTF-16 surrogate pair.
        self.assertEqual(drain.count("$drain.Writer.Flush()"), 1)
        self.assertRegex(drain, r"if \(\$count -eq 0\) \{\s*\$drain.Writer.Flush\(\)")

    def test_http_wait_remains_in_the_output_keyboard_and_process_poll_loop(self):
        loop = self.controller[self.controller.index("while ($true)"):]
        pending = loop.index("elseif ($pending.IsCompleted)")
        for check in ("Write-ProcessOutput -Drains $drains", "Test-StopRequested", "if ($process.HasExited)"):
            self.assertLess(loop.index(check), pending)
        self.assertIn("$pending = $request.BeginGetResponse($null, $null)", loop)
        self.assertIn("$response = $request.EndGetResponse($pending)", loop)
        self.assertIn("if ($now -ge $probeDeadline)", loop)
        self.assertNotRegex(loop, r"\.Wait\(|\.Result\b|WaitForExit")

    def test_timeout_budget_reserves_cleanup_and_limits_each_request_to_one_second(self):
        self.assertEqual(self.text.count("[ValidateRange(2, 30)][int]$StartupTimeoutSeconds = 30"), 2)
        self.assertIn("$cleanupMilliseconds = [Math]::Min(2000, $StartupTimeoutSeconds * 500)", self.controller)
        self.assertIn("$startupMilliseconds = $StartupTimeoutSeconds * 1000 - $cleanupMilliseconds", self.controller)
        self.assertIn("[ValidateRange(1, 1000)][int]$TimeoutMilliseconds", self.text)
        self.assertIn("[Math]::Min(1000, $startupMilliseconds - $now)", self.controller)
        self.assertIn("$probeDeadline - $clock.Elapsed.TotalMilliseconds", self.controller)
        self.assertNotRegex(self.code, r"WaitForExit|Thread\]::Sleep\((?:1000|2000|30000)\)")

    def test_stdin_lifeline_closes_before_bounded_cleanup_of_only_the_owned_handle(self):
        self.assertIn("$info.RedirectStandardInput = $true", self.controller)
        cleanup = function_body(self.text, "Stop-WebUiChild")
        self.assertEqual(self.code.count("$Process.StandardInput.Close()"), 1)
        self.assertLess(cleanup.index("$Process.StandardInput.Close()"), cleanup.index("$Request.Abort()"))
        self.assertLess(cleanup.index("$Process.StandardInput.Close()"), cleanup.index("$Process.Kill()"))
        self.assertIn("if (-not $Process.HasExited)", cleanup)
        self.assertIn("$cleanup.ElapsedMilliseconds -lt $BudgetMilliseconds", cleanup)
        self.assertEqual(self.code.count(".Kill()"), 1)
        self.assertNotRegex(self.code, r"Stop-Process|taskkill|Get-Process|GetProcesses|GetProcessById|"
                            r"wsl(?:\.exe)?\s+--shutdown|killall|pkill")
        self.assertRegex(self.controller, r"if \(\$started\) \{\s*\$cleaned = Stop-WebUiChild -Process \$process")
        self.assertIn("if (-not $cleaned) { $exitCode = 1 }", self.controller)
        self.assertIn("return $false", cleanup)
        self.assertIn("return $true", cleanup)
        self.assertIn("$drain.Reader.Dispose()", self.controller)
        self.assertIn("$process.Dispose()", self.controller)

    def test_startup_exit_is_failure_runtime_exit_propagates_and_cancellation_is_distinct(self):
        self.assertRegex(self.controller, re.compile(
            r"if \(-not \$ready\) \{[^}]+Child exited before readiness[^}]+\$exitCode = 1", re.S))
        self.assertIn("$exitCode = $childCode", self.controller)
        self.assertIn("$exitCode = if ($ready) { 0 } else { 130 }", self.controller)
        self.assertIn("[Console]::Error.WriteLine('[onepage-resume] Startup timed out.", self.controller)
        self.assertIn("[Console]::Error.WriteLine('[onepage-resume] Launcher failed:", self.controller)
        self.assertIn("return $exitCode", self.controller)
        self.assertIn("exit (Invoke-WebUiController -NoOpen:$NoOpen -StartupTimeoutSeconds $StartupTimeoutSeconds)",
                      self.text)

    def test_foreground_keyboard_and_console_settings_are_restored_in_finally(self):
        keyboard = function_body(self.text, "Test-StopRequested")
        self.assertIn("[Console]::KeyAvailable", keyboard)
        self.assertIn("[Console]::ReadKey($true)", keyboard)
        self.assertIn("[ConsoleKey]::Q", keyboard)
        self.assertIn("[ConsoleModifiers]::Control", keyboard)
        self.assertIn("[Console]::TreatControlCAsInput = $true", self.controller)
        final = self.controller[self.controller.rindex("} finally {"):]
        self.assertIn("[Console]::TreatControlCAsInput = $oldControlC", final)
        self.assertIn("[Console]::OutputEncoding = $oldEncoding", final)
        self.assertIn("if ($MyInvocation.InvocationName -ne '.')", self.text)


@unittest.skipUnless(POWERSHELL, "PowerShell is not installed; static contracts still run")
class StartWebUiFunctionTest(unittest.TestCase):
    def run_helpers(self, body: str, data=None):
        command = f"""
$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding -ArgumentList $false
[Console]::OutputEncoding = $utf8
[Console]::InputEncoding = $utf8
$payload = ConvertFrom-Json ([Console]::In.ReadToEnd())
. ([scriptblock]::Create($payload.Script))
$data = $payload.Data
{body}
[Console]::Out.Write((ConvertTo-Json -InputObject $result -Depth 8 -Compress))
"""
        encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
        # Never include the executable entry point, even if its dot-source guard regresses.
        definitions = SCRIPT.read_text(encoding="ascii").split("\n# Dot-source", 1)[0]
        payload = dict(Script=definitions, Data=data)
        completed = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            capture_output=True, timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", errors="replace"))
        return json.loads(completed.stdout.decode("utf-8"))

    def test_real_argument_vectors_for_drive_unc_and_mapped_repo(self):
        launcher_id = "0123456789abcdef" * 2
        cases = [
            dict(Base="C:\\work space\\repo\\", Distro="", LinuxDirectory="", Port=19081, LauncherId=launcher_id),
            dict(Base="\\\\wsl.localhost\\Ubuntu\\home\\a b", Distro="Ubuntu",
                 LinuxDirectory='/home/a "b"/repo\\', Port=19082, LauncherId=launcher_id),
            dict(Base="Z:\\mapped repo", Distro="Ubuntu-24.04",
                 LinuxDirectory='/home/a\\"quoted"/repo with space\\', Port=65535, LauncherId=launcher_id),
        ]
        results = self.run_helpers("""
$result = @(foreach ($case in $data) {
    $argv = @(Get-WebUiArguments -Base $case.Base -Distro $case.Distro -LinuxDirectory $case.LinuxDirectory -Port $case.Port -LauncherId $case.LauncherId)
    @{ Argv = $argv; Native = (Join-NativeArguments -Values $argv) }
})
""", cases)
        for case, result in zip(cases, results, strict=True):
            expected = (["-d", case["Distro"]] if case["Distro"] else []) + [
                "--cd", case["LinuxDirectory"] if case["Distro"] else case["Base"],
                "-e", ".venv/bin/python", "-u", "-X", "utf8", "webui.py", "--host", "127.0.0.1",
                "--port", str(case["Port"]), "--no-open", "--launcher-id", launcher_id,
            ]
            self.assertEqual(result["Argv"], expected)
            if case["Distro"]:
                self.assertIn("-d " + case["Distro"] + " ", result["Native"])
            if os.name == "nt":
                self.assertEqual(self.windows_argv(result["Native"]), expected)

    @staticmethod
    def windows_argv(arguments: str):
        # Parse, do not execute, the actual native command line on Windows.
        import ctypes
        shell = ctypes.WinDLL("shell32")
        kernel = ctypes.WinDLL("kernel32")
        shell.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
        shell.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        count = ctypes.c_int()
        argv = shell.CommandLineToArgvW("launcher.exe " + arguments, ctypes.byref(count))
        if not argv:
            raise ctypes.WinError()
        try:
            return [argv[i] for i in range(1, count.value)]
        finally:
            kernel.LocalFree(ctypes.cast(argv, ctypes.c_void_p))

    def test_empty_quotes_spaces_and_backslashes_round_trip(self):
        cases = [
            ("", '""'), ("Ubuntu", "Ubuntu"), ("a b", '"a b"'),
            ("C:\\a b\\", '"C:\\a b' + "\\" * 2 + '"'),
            ("C:\\a b\\\\", '"C:\\a b' + "\\" * 4 + '"'),
            ('/home/a "b"/repo', '"/home/a \\"b\\"/repo"'),
            ('a\\"b', '"a' + "\\" * 3 + '"b"'), ("\\", "\\"),
        ]
        result = self.run_helpers("$result = @(foreach ($case in $data) { ConvertTo-NativeArgument -Value $case })",
                                  [value for value, _ in cases])
        self.assertEqual(result, [expected for _, expected in cases])
        if os.name == "nt":
            self.assertEqual(self.windows_argv(" ".join(result)), [value for value, _ in cases])

    def test_request_settings_and_ordinal_ready_header_without_sending_http(self):
        expected = "v1;" + "0123456789abcdef" * 2
        cases = [(200, expected, True), (404, expected, False), (301, expected, False),
                 (200, None, False), (200, expected.upper(), False), (200, expected + " ", False),
                 (200, expected + ", " + expected, False), (200, "v1;" + "0" * 32, False)]
        result = self.run_helpers("""
$request = New-ReadinessRequest -Uri 'http://127.0.0.1:19081/__launcher/ready' -TimeoutMilliseconds 1000
try {
    $matches = @(foreach ($case in $data.Cases) {
        $response = [pscustomobject]@{ StatusCode = $case[0]; Headers = @{ 'X-Onepage-Resume-Ready' = $case[1] } }
        Test-ReadyResponse -Response $response -ExpectedHeader $data.Expected
    })
    $result = @{ Method = $request.Method; NoProxy = ($null -eq $request.Proxy); Redirect = $request.AllowAutoRedirect;
                 Cache = $request.CachePolicy.Level.ToString(); Timeout = $request.Timeout; ReadTimeout = $request.ReadWriteTimeout;
                 HeaderLimit = $request.MaximumResponseHeadersLength;
                 CacheControl = $request.Headers['Cache-Control']; Matches = $matches }
} finally { $request.Abort() }
""", dict(Expected=expected, Cases=cases))
        self.assertEqual(result, dict(Method="HEAD", NoProxy=True, Redirect=False, Cache="NoCacheNoStore",
                                      Timeout=1000, ReadTimeout=1000, HeaderLimit=16, CacheControl="no-cache, no-store",
                                      Matches=[match for _, _, match in cases]))

    def test_simultaneous_bounded_utf8_draining_preserves_non_line_terminated_tails(self):
        stdout = "x" * 4095 + "\U0001f600" + "\u8f93\u51fa" * 16000 + "stdout tail without newline"
        stderr = "y" * 4095 + "\U0001f680" + "\u9519\u8bef" * 18000 + "stderr tail without newline"
        result = self.run_helpers("""
$utf8 = [Text.UTF8Encoding]::new($false)
$outSource = [IO.MemoryStream]::new($utf8.GetBytes($data.Out))
$errSource = [IO.MemoryStream]::new($utf8.GetBytes($data.Err))
$outSink = [IO.MemoryStream]::new()
$errSink = [IO.MemoryStream]::new()
$outWriter = [IO.StreamWriter]::new($outSink, $utf8)
$errWriter = [IO.StreamWriter]::new($errSink, $utf8)
$outWriter.AutoFlush = $true
$errWriter.AutoFlush = $true
$outDrain = New-OutputDrain -Reader ([IO.StreamReader]::new($outSource, $utf8)) -Writer $outWriter
$errDrain = New-OutputDrain -Reader ([IO.StreamReader]::new($errSource, $utf8)) -Writer $errWriter
[void](Write-ProcessOutput -Drains @($outDrain, $errDrain))
$firstOut = $outSink.Length
$firstErr = $errSink.Length
$passes = 0
while (-not $outDrain.Closed -or -not $errDrain.Closed) {
    [void](Write-ProcessOutput -Drains @($outDrain, $errDrain))
    if (++$passes -gt 1000) { throw 'Drains did not reach EOF.' }
}
$result = @{ Out = $utf8.GetString($outSink.ToArray()); Err = $utf8.GetString($errSink.ToArray()); FirstOut = $firstOut; FirstErr = $firstErr }
""", dict(Out=stdout, Err=stderr))
        self.assertEqual(result["Out"], stdout)
        self.assertEqual(result["Err"], stderr)
        for key in ("FirstOut", "FirstErr"):
            self.assertGreater(result[key], 0)
            self.assertLessEqual(result[key], 4 * 4096 * 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
