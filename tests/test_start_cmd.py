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
    """内容上的两处硬要求，改坏了双击就白跑一场。"""

    @classmethod
    def setUpClass(cls):
        cls.path = ROOT / "start.cmd"
        cls.text = cls.path.read_text(encoding="ascii")

    def test_every_goto_has_a_matching_label(self):
        import re
        targets = set(re.findall(r"(?im)^\s*(?:if\s+.*?\s+)?goto\s+(\w+)\s*$", self.text))
        labels = set(re.findall(r"(?im)^\s*:(\w+)\s*$", self.text))
        missing = sorted(targets - labels)
        self.assertEqual(missing, [], f"goto 指向了不存在的标签：{missing}")

    def test_it_starts_the_service_with_no_open(self):
        # Windows 这边自己开浏览器，WSL 里再开一个就成了两个标签。
        self.assertIn("--no-open", self.text)

    def test_it_waits_for_the_port_before_opening_the_browser(self):
        wait = self.text.index("Invoke-WebRequest")
        open_at = self.text.index('start "" http://127.0.0.1:8765')
        self.assertLess(wait, open_at, "得先等端口通，再开浏览器")

    def test_the_distro_after_dash_d_is_not_quoted(self):
        # wsl.exe 会把引号算进发行版名字里，然后报 WSL_E_DISTRO_NOT_FOUND。
        import re
        quoted = re.findall(r'-d\s+"', self.text)
        self.assertEqual(
            quoted, [],
            'wsl.exe 的 -d 后面不能加引号：它会把引号当成名字的一部分，'
            "答 WSL_E_DISTRO_NOT_FOUND",
        )

    def test_wsl_failures_are_checked_by_comparison_not_if_errorlevel(self):
        """`if errorlevel 1` 是「≥ 1」，接不住 wsl.exe 的 -1。

        括号块里例外：那里 %errorlevel% 会在解析期就被展开成定值，只能用
        `if not errorlevel 1`，而那一处判的是 powershell 的 0/1，够用。
        """
        import re
        lines = self.text.splitlines()
        depth = 0
        offenders = []
        for no, line in enumerate(lines, 1):
            stripped = line.strip()
            if re.match(r"(?i)^rem\b", stripped):
                continue
            in_block = depth > 0
            depth += line.count("(") - line.count(")")
            if in_block:
                continue
            if re.search(r"(?i)\bif\s+errorlevel\s+1\b", stripped):
                offenders.append(f"{no}: {stripped}")
        self.assertEqual(
            offenders, [],
            "这些地方用了 `if errorlevel 1`，接不住负的退出码，"
            f'请改成 `if not "%errorlevel%"=="0"`：{offenders}',
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
