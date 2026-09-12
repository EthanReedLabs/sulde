from __future__ import annotations

import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from scope_freeze import Discovery, ScopeDecision, classify, closure


class ScopeFreezeTests(unittest.TestCase):
    def test_only_verified_current_blocker_expands_delivery(self) -> None:
        blocked = classify(
            Discovery("A", "functional", "acceptance_failure", "verified", True)
        )
        adjacent = classify(
            Discovery("B", "optimization", "performance", "verified", False)
        )
        unknown = classify(
            Discovery("C", "environment", "security", "inconclusive", True)
        )
        self.assertEqual(blocked.disposition, "blocker")
        self.assertEqual(adjacent.disposition, "deferred")
        self.assertEqual(unknown.disposition, "inconclusive")

    def test_closure_has_no_unexplained_pending_state(self) -> None:
        result = closure(
            [
                ScopeDecision("later", "deferred", "separate delivery"),
                ScopeDecision("unknown", "inconclusive", "needs evidence"),
            ]
        )
        self.assertTrue(result["ready"])
        self.assertEqual(result["unexplained"], [])

    def test_verified_security_issue_blocks(self) -> None:
        decision = classify(
            Discovery("seal", "environment", "security", "verified", False)
        )
        self.assertFalse(closure([decision])["ready"])


if __name__ == "__main__":
    unittest.main()
