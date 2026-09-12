from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))
sys.path.insert(0, str(ROOT / "scripts" / "release"))

import install_codex_plugin as installer
from sulde_paths import launcher_home as canonical_launcher_home, layout


class SuldePathTests(unittest.TestCase):
    def test_fresh_codex_home_is_provider_neutral(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            user = Path(name) / "user"
            with mock.patch.object(Path, "home", return_value=user), mock.patch.dict(
                os.environ, {}, clear=False
            ):
                os.environ.pop("SULDE_HOME", None)
                os.environ.pop("SULDE_KB_HOME", None)
                selected = layout()
                neutral = (user / ".sulde").resolve()
                self.assertEqual(selected.root, neutral)
                self.assertEqual(selected.bin, neutral / "bin")
                self.assertEqual(selected.kb, neutral / "data" / "kb")
                self.assertEqual(installer.default_kb_home(), selected.kb)
                self.assertEqual(installer.launcher_home(selected.kb), selected.root)
                self.assertEqual(canonical_launcher_home(selected.kb), selected.root)

    def test_explicit_compatibility_kb_keeps_self_contained_launchers(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            explicit = Path(name) / "portable-kb"
            self.assertEqual(installer.launcher_home(explicit), explicit.resolve())
            self.assertEqual(canonical_launcher_home(explicit), explicit.resolve())

    def test_codex_hook_bridge_has_no_claude_home_dependency(self) -> None:
        for relative in (
            "integrations/codex/plugins/sulde/scripts/run-hook.sh",
            "integrations/codex/plugins/sulde/scripts/run-hook.ps1",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn(".claude/plugins/data/sulde-cc/kb", source)
            self.assertIn(".sulde", source)


if __name__ == "__main__":
    unittest.main()
