from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "kb-index"))

from search_contract import (  # noqa: E402
    PURPOSE_ROLES,
    applicability_for,
    filter_clause,
    rerank_near_ties,
)


class KbSearchPolarityTests(unittest.TestCase):
    def test_route_negative_is_skip_but_failed_outcome_is_actionable(self) -> None:
        self.assertEqual(applicability_for("route_negative", "verified"), "skip")
        self.assertEqual(applicability_for("outcome_negative", "verified"), "apply")
        self.assertEqual(applicability_for("root_cause", "inconclusive"), "inconclusive")

    def test_recall_and_solution_purposes_use_different_semantic_roles(self) -> None:
        self.assertEqual(
            PURPOSE_ROLES["route"],
            {"general", "route_positive", "route_negative"},
        )
        self.assertIn("route_negative", PURPOSE_ROLES["recall"])
        self.assertNotIn("route_negative", PURPOSE_ROLES["solution"])
        self.assertIn("solution", PURPOSE_ROLES["solution"])
        self.assertNotIn("solution", PURPOSE_ROLES["recall"])

    def test_route_purpose_excludes_mixed_applicability_prose(self) -> None:
        clause, parameters = filter_clause(None, None, "route")
        self.assertIn("c.role IN", clause)
        self.assertNotIn("applicability", parameters)
        self.assertEqual(set(parameters), PURPOSE_ROLES["route"])

    def test_role_filter_is_composed_with_container_and_platform(self) -> None:
        clause, parameters = filter_clause("anti-patterns", "ios", "recall")
        self.assertIn("c.container = ?", clause)
        self.assertIn("c.platform = ?", clause)
        self.assertIn("c.role IN", clause)
        self.assertIn("c.role != 'general' OR c.evidence_status = ''", clause)
        self.assertEqual(parameters[:2], ["anti-patterns", "ios"])
        self.assertEqual(set(parameters[2:]), PURPOSE_ROLES["recall"])

    def test_all_purpose_keeps_every_general_section(self) -> None:
        clause, parameters = filter_clause(None, None, "all")
        self.assertEqual(clause, "")
        self.assertEqual(parameters, [])

    def test_absolute_cosine_breaks_only_hybrid_near_ties(self) -> None:
        ranked = rerank_near_ties(
            [
                ("lexical-first", 0.658, 0.52),
                ("semantic-first", 0.654, 0.66),
                ("far-away", 0.50, 0.99),
            ]
        )
        self.assertEqual([item[0] for item in ranked], [
            "semantic-first", "lexical-first", "far-away"
        ])
        self.assertEqual([item[1] for item in ranked], [0.658, 0.654, 0.50])
        self.assertEqual(ranked[0][2], 0.654)

    def test_candidate_outside_near_tie_does_not_jump_by_cosine(self) -> None:
        ranked = rerank_near_ties(
            [("hybrid", 0.70, 0.40), ("cosine", 0.68, 0.99)]
        )
        self.assertEqual([item[0] for item in ranked], ["hybrid", "cosine"])


if __name__ == "__main__":
    unittest.main()
