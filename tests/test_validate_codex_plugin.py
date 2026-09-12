from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release" / "validate_codex_plugin.py"
PLUGIN = ROOT / "integrations" / "codex" / "plugins" / "sulde"


class CodexPluginValidationTests(unittest.TestCase):
    def test_validator_runs_without_site_packages_or_pyyaml(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-S", "-B", str(SCRIPT), str(PLUGIN)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "valid")
        self.assertFalse(result["pyyaml_required"])


if __name__ == "__main__":
    unittest.main()
