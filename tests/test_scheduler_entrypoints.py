from __future__ import annotations

import os
import plistlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
AUTO_DISTILL = ROOT / "scripts" / "kb" / "auto-distill.py"


class SchedulerEntrypointTests(unittest.TestCase):
    def test_mem_sync_launchagents_use_scheduled_retry_semantics(self) -> None:
        for action in ("import", "export"):
            path = (
                ROOT
                / "templates/launchagents"
                / f"com.sulde.mem-sync-{action}.plist"
            )
            with path.open("rb") as handle:
                payload = plistlib.load(handle)
            arguments = payload["ProgramArguments"]
            self.assertEqual(arguments[-2:], [action, "--scheduled"])
            self.assertEqual(payload.get("Program", arguments[0]), arguments[0])

    def test_auto_distill_declares_utf8_source(self) -> None:
        lines = AUTO_DISTILL.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[1], "# -*- coding: utf-8 -*-")

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS system Python")
    def test_auto_distill_help_under_launchagent_minimal_environment(self) -> None:
        system_python = Path("/usr/bin/python3")
        self.assertTrue(system_python.is_file(), "macOS system Python is unavailable")
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_root = Path(temp_dir) / "plugin"
            scripts = fixture_root / "scripts" / "kb"
            hook_lib = fixture_root / "hooks" / "lib"
            scripts.mkdir(parents=True)
            hook_lib.mkdir(parents=True)
            for name in ("auto-distill.py", "command_template.py"):
                shutil.copy2(ROOT / "scripts" / "kb" / name, scripts / name)
            shutil.copy2(ROOT / "hooks" / "lib" / "kb_cli.py", hook_lib / "kb_cli.py")
            launchagent_home = Path(temp_dir) / "home"
            launchagent_home.mkdir()
            environment = {
                "HOME": str(launchagent_home),
                "PATH": "/usr/bin:/bin",
                "TMPDIR": temp_dir,
                "LC_CTYPE": "UTF-8",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            completed = subprocess.run(
                [str(system_python), str(scripts / "auto-distill.py"), "--help"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=10,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("usage:", completed.stdout.lower())
            self.assertEqual(list(fixture_root.rglob("*.pyc")), [])
            self.assertEqual(list(fixture_root.rglob("__pycache__")), [])


if __name__ == "__main__":
    unittest.main()
