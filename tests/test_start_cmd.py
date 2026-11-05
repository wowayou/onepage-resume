"""start.cmd 的编码与行尾不变量。

这两条不是风格问题，是「双击了什么也没打开」的直接原因，而且在 Linux 上看文件
一切正常，只有到了 Windows 才炸：

  · cmd.exe 按控制台的 OEM 代码页解析 .cmd。中文 Windows 是 CP936，UTF-8 的
    中文字节被当 GBK 读，前导字节会把行尾的换行吃掉，于是下一行被当命令执行
    （实测报错："'not_reachable' 不是内部或外部命令"——goto 的目标名被跑了）。
    写在文件里的 chcp 65001 救不了：cmd 按块读文件，同一行字节相同，只因在
    文件里的位置不同，一处能过、一处炸。所以只能纯 ASCII。
  · LF 行尾会让 goto / 标签 / 括号块错乱，和代码页无关。必须 CRLF。

.gitattributes 里的 `*.cmd text eol=crlf` 管的是检出，这里管的是工作树里
真实的那个文件——两头都钉住，才不会被一次 WSL 里的编辑悄悄改回去。
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CMD_FILES = sorted(ROOT.glob("*.cmd"))


class CmdFileEncodingTest(unittest.TestCase):
    def test_there_is_at_least_one_cmd_file_to_check(self):
        # 免得哪天文件改了名，这套测试静默变成空跑。
        self.assertTrue(CMD_FILES, "仓库根目录下没有 .cmd 文件，这套测试该跟着改")

    def test_cmd_files_are_pure_ascii(self):
        for path in CMD_FILES:
            with self.subTest(path=path.name):
                raw = path.read_bytes()
                bad = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
                self.assertEqual(
                    bad[:5], [],
                    f"{path.name} 里有非 ASCII 字节（前几个偏移：{bad[:5]}）。"
                    "cmd.exe 会按 OEM 代码页错读它们，中文说明请放 README.md。",
                )

    def test_cmd_files_use_crlf_on_every_line(self):
        for path in CMD_FILES:
            with self.subTest(path=path.name):
                raw = path.read_bytes()
                lone_lf = raw.replace(b"\r\n", b"").count(b"\n")
                self.assertEqual(
                    lone_lf, 0,
                    f"{path.name} 有 {lone_lf} 处裸 LF 行尾。cmd.exe 的 goto 和"
                    "标签需要 CRLF。",
                )

    def test_cmd_files_have_no_stray_cr(self):
        # 单独的 CR（不带 LF）同样会让 cmd 迷路，顺手一起挡掉。
        for path in CMD_FILES:
            with self.subTest(path=path.name):
                raw = path.read_bytes()
                self.assertEqual(
                    raw.replace(b"\r\n", b"").count(b"\r"), 0,
                    f"{path.name} 里有不成对的 CR",
                )


class StartCmdContentTest(unittest.TestCase):
    """cmd 保留路径/环境准备，并把监督与退出码交给前台控制器。"""

    @classmethod
    def setUpClass(cls):
        cls.path = ROOT / "start.cmd"
        cls.text = cls.path.read_text(encoding="ascii")
        cls.controller = (ROOT / "scripts" / "start-webui.ps1").read_text(encoding="ascii")
        cls.commands = "\n".join(
            line for line in cls.text.splitlines()
            if not re.match(r"(?i)^\s*rem(?:\s|$)", line)
        )

    def test_every_goto_and_subroutine_call_has_a_matching_label(self):
        targets = {name.lower() for name in re.findall(r"(?i)\bgoto\s+:?(\w+)", self.commands)}
        targets.update(name.lower() for name in re.findall(r"(?i)\bcall\s+:(\w+)", self.commands))
        targets.discard("eof")
        labels = {name.lower() for name in re.findall(r"(?m)^\s*:(\w+)\s*$", self.text)}
        missing = sorted(targets - labels)
        self.assertEqual(missing, [], f"goto/call 指向了不存在的标签：{missing}")

    def test_it_starts_the_service_with_no_open(self):
        # Windows 控制器开浏览器；Python 必须禁用 WSL 侧自动打开。
        self.assertRegex(self.controller, r"'--no-open',\s*'--launcher-id',\s*\$LauncherId")

    def test_it_delegates_startup_and_browser_to_one_foreground_controller(self):
        invocation = ('powershell.exe -NoProfile -ExecutionPolicy Bypass '
                      '-File "%BASE%\\scripts\\start-webui.ps1"')
        self.assertEqual(self.commands.count(invocation), 1)
        self.assertNotIn("Invoke-WebRequest", self.commands)
        self.assertNotRegex(self.commands, r"(?im)^\s*start\s")
        self.assertNotIn("http://", self.commands)
        # 不经 cmd 的多层转义传参数，而是继承现有路径探测结果和端口。
        for parameter, variable in (("Base", "BASE"), ("Distro", "WSLDISTRO"),
                                    ("LinuxDirectory", "LINUXDIR")):
            self.assertIn(f"-{parameter} $env:{variable}", self.controller)
        self.assertIn("[int]::TryParse($env:WEBUI_PORT, [ref]$port)", self.controller)
        self.assertIn("-Port $port -LauncherId $launcherId", self.controller)
        self.assertIn("$info.Arguments = Join-NativeArguments -Values $arguments", self.controller)

    def test_the_port_is_defined_in_exactly_one_place_and_matches_python(self):
        # 读取默认值而不 import webui（这套静态测试不启动服务或加载渲染依赖）。
        module = ast.parse((ROOT / "webui.py").read_text(encoding="utf-8"))
        defaults = [ast.literal_eval(node.value) for node in module.body
                    if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "DEFAULT_PORT"
                            for target in node.targets)]
        self.assertEqual(len(defaults), 1)
        assignment = f'set "WEBUI_PORT={defaults[0]}"'
        self.assertEqual(self.text.count(assignment), 1)
        self.assertNotIn(str(defaults[0]), self.text.replace(assignment, ""),
                         "端口只该在 WEBUI_PORT 里写一次")
        self.assertNotIn(str(defaults[0]), self.controller,
                         "控制器必须继承 WEBUI_PORT，不能另写一个默认端口")

    def test_the_distro_after_dash_d_is_not_quoted(self):
        # wsl.exe 会把引号算进发行版名字里，然后报 WSL_E_DISTRO_NOT_FOUND。
        quoted = re.findall(r'-d\s+"', self.text)
        self.assertEqual(
            quoted, [],
            'wsl.exe 的 -d 后面不能加引号：它会把引号当成名字的一部分，'
            "答 WSL_E_DISTRO_NOT_FOUND",
        )

    def test_wsl_failures_are_checked_by_comparison_not_if_errorlevel(self):
        """`if errorlevel 1` 是「>= 1」，接不住 wsl.exe 的 -1。"""
        self.assertNotRegex(self.commands, r"(?i)\bif\s+(?:not\s+)?errorlevel\s+1\b")
        for command, failure in (("where wsl >nul 2>nul", "no_wsl"),
                                 ("wsl.exe --status >nul 2>nul", "no_wsl"),
                                 ('call :runwsl "test -f Makefile"', "not_reachable"),
                                 ('call :runwsl "make boot"', "boot_failed")):
            with self.subTest(command=command):
                self.assertIn(f'{command}\nif not "%errorlevel%"=="0" goto {failure}', self.text)

    def test_existing_setup_and_path_detection_are_preserved(self):
        for contract in ('if "%BASE:~-1%"=="\\" set "BASE=%BASE:~0,-1%"',
                         'call :unc_to_parts "%BASE%"',
                         'call :drive_to_unc "%BASE:~0,2%"',
                         'call :unc_to_parts "%DRIVEUNC%%BASE:~2%"',
                         'if /i "%P:~0,16%"=="\\\\wsl.localhost\\" goto unc_strip_localhost',
                         'if /i "%P:~0,7%"=="\\\\wsl$\\" goto unc_strip_dollar',
                         'set "UNCREST="', 'set "LINUXDIR=/%UNCREST:\\=/%"',
                         'net use %~1 2^>nul',
                         'wsl.exe --cd "%BASE%" -e bash -lc "%~1"',
                         'wsl.exe -d %WSLDISTRO% --cd "%LINUXDIR%" -e bash -lc "%~1"'):
            with self.subTest(contract=contract):
                self.assertIn(contract, self.text)
        self.assertLess(self.text.index('call :runwsl "test -f Makefile"'),
                        self.text.index('call :runwsl "make boot"'))
        self.assertLess(self.text.index('call :runwsl "make boot"'),
                        self.text.index("powershell.exe -NoProfile"))

    def test_real_controller_exit_code_survives_pause_and_endlocal(self):
        self.assertIn('set "LAUNCHER_RC=1"', self.text)
        self.assertRegex(self.text, r'powershell\.exe[^\n]+\nset "LAUNCHER_RC=%errorlevel%"\ngoto end')
        self.assertEqual(len(re.findall(r'(?im)^set "LAUNCHER_RC=', self.text)), 2)
        self.assertRegex(self.text, r':end\nif not defined NO_PAUSE pause\nendlocal & exit /b %LAUNCHER_RC%\n?$')
        for label in ("say_foreign_share", "no_wsl", "not_reachable", "boot_failed"):
            block = re.search(rf"(?ms)^:{label}\n(.*?)(?=^:\w+|\Z)", self.text)
            with self.subTest(label=label):
                self.assertIsNotNone(block)
                self.assertIn("goto end", block.group(1))

    def test_nopause_is_opt_in_and_does_not_change_the_controller_arguments(self):
        self.assertIn('set "NO_PAUSE="', self.text)
        self.assertIn('if /i "%~1"=="/nopause" set "NO_PAUSE=1"', self.text)
        self.assertIn("if not defined NO_PAUSE pause", self.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
