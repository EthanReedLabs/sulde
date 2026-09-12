from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/kb/sync-self.py"
SPEC = importlib.util.spec_from_file_location("sync_self", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
SYNC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC)


class SyncSelfTests(unittest.TestCase):
    def test_syncs_constitutional_capabilities_and_preserves_runtime_reflection(self) -> None:
        template = (
            "# SELF\n\n## 我的能力阶梯\n\nNEW LADDER\n\n"
            "## 我能自主做什么\n\nNEW AUTONOMY\n\n## 目标栈\n\nTEMPLATE\n"
        )
        runtime = (
            "# SELF\n\n## 我的能力阶梯\n\nOLD LADDER\n\n"
            "## 我能自主做什么\n\nOLD AUTONOMY\n\n"
            "## 目标栈\n\nRUNTIME GOAL\n\n## 自评\n\nRUNTIME REFLECTION\n"
        )
        result = SYNC.synchronize(template, runtime)
        self.assertIn("## 我的能力阶梯\n\nNEW LADDER", result)
        self.assertIn("## 我能自主做什么\n\nNEW AUTONOMY", result)
        self.assertIn("RUNTIME GOAL", result)
        self.assertIn("RUNTIME REFLECTION", result)
        self.assertNotIn("TEMPLATE", result)

    def test_missing_runtime_section_is_refused(self) -> None:
        with self.assertRaisesRegex(SYNC.SyncError, "runtime section count"):
            SYNC.synchronize(
                "## 我的能力阶梯\n\nNEW\n\n## 我能自主做什么\n\nNEW\n",
                "# SELF\n",
            )


if __name__ == "__main__":
    unittest.main()
