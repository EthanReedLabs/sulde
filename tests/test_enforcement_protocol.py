from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "hooks" / "lib"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class EnforcementProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(LIB))
        cls.common = load_module("test_enforcement_sulde_common", LIB / "sulde_common.py")
        # enforcement imports ``sulde_common`` by its runtime module name.
        original = sys.modules.get("sulde_common")
        sys.modules["sulde_common"] = cls.common
        try:
            cls.enforcement = load_module(
                "test_enforcement_runtime", LIB / "enforcement.py"
            )
        finally:
            if original is None:
                sys.modules.pop("sulde_common", None)
            else:
                sys.modules["sulde_common"] = original

    @classmethod
    def tearDownClass(cls) -> None:
        if sys.path and sys.path[0] == str(LIB):
            sys.path.pop(0)

    def config(self, root: Path, level: str):
        return self.common.SuldeConfig(
            config_path=root / ".sulde-config.yaml",
            project_root=root,
            role="both",
            frontends=(),
            enforcement_level=level,
            grace_period_days=0,
            lang="en",
            enabled=True,
        )

    def test_lenient_hard_warning_uses_silent_allow_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    self.enforcement.sulde_exit_or_warn(
                        self.config(Path(td), "lenient"),
                        "hard",
                        "fixture warning",
                        hook_event="PreToolUse",
                        tool_name="Write",
                    )

        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("fixture warning", stderr.getvalue())
        self.assertNotIn("permissionDecision", stderr.getvalue())

    def test_balanced_hard_violation_still_emits_structured_deny(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    self.enforcement.sulde_exit_or_warn(
                        self.config(Path(td), "balanced"),
                        "hard",
                        "fixture denial",
                        hook_event="PreToolUse",
                        tool_name="Write",
                    )

        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn('"permissionDecision": "deny"', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
