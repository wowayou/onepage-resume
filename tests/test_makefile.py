"""make boot 只在需要时装 Python 依赖。

用假的 python3 / pip / bootstrap.sh 在临时目录里跑真实的 Makefile：不联网、不碰仓库的
.venv，只看 make 实际调用了哪些安装命令。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAKE = shutil.which("make")

FAKE_PYTHON3 = """#!/bin/sh
# 只模拟 `python3 -m venv DIR`：建出带假 python / pip 的目录。
echo "python3 $*" >> "$FAKE_LOG"
[ "$1" = "-m" ] && [ "$2" = "venv" ] || exit 9
mkdir -p "$3/bin"
cp "$FAKE_DIR/venv-python" "$3/bin/python"
cp "$FAKE_DIR/venv-pip" "$3/bin/pip"
"""

FAKE_VENV_PYTHON = """#!/bin/sh
echo "py $*" >> "$FAKE_LOG"
if [ "$1" = "-c" ]; then
    # 依赖检查：标记了 broken 就当解释器或 weasyprint 坏了。
    [ -e "$FAKE_DIR/broken" ] && exit 1
    exit 0
fi
exit 0
"""

FAKE_VENV_PIP = """#!/bin/sh
echo "pip $*" >> "$FAKE_LOG"
[ -e "$FAKE_DIR/pip-fails" ] && exit 1
exit 0
"""


@unittest.skipUnless(MAKE, "需要 GNU make")
class BootSetupStampTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="resume-make-")
        self.addCleanup(temporary.cleanup)
        self.dir = Path(temporary.name)
        self.fakes = self.dir / "fakes"
        self.fakes.mkdir()
        shutil.copyfile(ROOT / "Makefile", self.dir / "Makefile")
        shutil.copyfile(ROOT / "requirements.txt", self.dir / "requirements.txt")
        scripts = self.dir / "scripts"
        scripts.mkdir()
        self.write(scripts / "bootstrap.sh", "#!/bin/sh\nexit 0\n")
        self.write(self.fakes / "python3", FAKE_PYTHON3)
        self.write(self.fakes / "venv-python", FAKE_VENV_PYTHON)
        self.write(self.fakes / "venv-pip", FAKE_VENV_PIP)
        self.log = self.dir / "calls.log"
        self.stamp = self.dir / ".venv" / ".requirements-installed"

    @staticmethod
    def write(path: Path, text: str):
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)

    def make(self, target: str, check: bool = True) -> subprocess.CompletedProcess:
        self.log.write_text("", encoding="utf-8")
        env = {key: value for key, value in os.environ.items()
               if key not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEFILES")}
        env.update(PATH=f"{self.fakes}{os.pathsep}{env.get('PATH', '')}",
                   FAKE_LOG=str(self.log), FAKE_DIR=str(self.fakes))
        result = subprocess.run([MAKE, "--no-print-directory", target], cwd=self.dir,
                                env=env, capture_output=True, text=True, timeout=30)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def installs(self) -> list[str]:
        return [line for line in self.log.read_text(encoding="utf-8").splitlines()
                if line.startswith(("python3 ", "pip "))]

    def touch_later(self, path: Path):
        # 保证比标记新，不依赖文件系统时间戳精度。
        later = time.time() + 5
        os.utime(path, (later, later))

    def test_first_boot_installs_then_later_boots_skip_network(self):
        self.make("boot")
        self.assertEqual(self.installs(), [
            "python3 -m venv .venv",
            "pip install --upgrade pip",
            "pip install -r requirements.txt",
        ])
        self.assertTrue(self.stamp.exists())

        result = self.make("boot")
        self.assertEqual(self.installs(), [], "依赖没变时不该再跑 venv / pip")
        self.assertIn("跳过 make setup", result.stdout)
        self.assertIn("py render.py", self.log.read_text(encoding="utf-8"),
                      "跳过安装后仍要渲染示例冒烟")

    def test_changed_requirements_reinstall(self):
        self.make("boot")
        self.touch_later(self.dir / "requirements.txt")
        self.make("boot")
        self.assertIn("pip install -r requirements.txt", self.installs())

    def test_broken_venv_is_reinstalled_even_with_a_fresh_stamp(self):
        self.make("boot")
        (self.fakes / "broken").touch()
        self.make("boot")
        self.assertIn("pip install -r requirements.txt", self.installs())

    def test_failed_install_leaves_no_stamp_so_next_boot_retries(self):
        (self.fakes / "pip-fails").touch()
        result = self.make("boot", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.stamp.exists())
        (self.fakes / "pip-fails").unlink()
        self.make("boot")
        self.assertIn("pip install -r requirements.txt", self.installs())
        self.assertTrue(self.stamp.exists())

    def test_explicit_setup_always_reruns_install_steps(self):
        self.make("boot")
        self.make("setup")
        self.assertIn("pip install --upgrade pip", self.installs())
        self.assertIn("pip install -r requirements.txt", self.installs())


if __name__ == "__main__":
    unittest.main(verbosity=2)
