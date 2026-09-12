from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kb" / "sedimentation-search-eval.py"
SPEC = importlib.util.spec_from_file_location("sulde_sedimentation_search_eval", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
EVAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVAL)

sys.path.insert(0, str(ROOT / "scripts" / "kb"))
from sedimentation_schema import extract_samples, validate_document  # noqa: E402
from tests.synthetic_sedimentation import write_examples  # noqa: E402


class SedimentationSearchEvalTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="sulde-synthetic-search-eval-")
        self.addCleanup(temporary.cleanup)
        self.data, self.doc_paths = write_examples(Path(temporary.name))
        self.cases = EVAL.load_cases(self.data)

    def test_fixture_is_balanced_independent_paraphrase_set(self) -> None:
        self.assertEqual(len(self.cases), 20)
        self.assertEqual(sum(case["kind"] == "route" for case in self.cases), 10)
        self.assertEqual(sum(case["kind"] == "outcome" for case in self.cases), 10)
        self.assertEqual({case["expected_doc_id"] for case in self.cases}, set(self.doc_paths))

        embedded = {
            sample.input_text
            for path in self.doc_paths.values()
            for sample in extract_samples(path.read_text(encoding="utf-8"))
        }
        self.assertFalse({case["query"] for case in self.cases} & embedded)
        for path in self.doc_paths.values():
            self.assertEqual(validate_document(path.read_text(encoding="utf-8"), root=ROOT, require_v2=True), [])

    def test_exact_document_and_semantics_score_full_rate(self) -> None:
        expected_by_query = {case["query"]: case for case in self.cases}
        roles = {
            "apply": "route_positive",
            "skip": "route_negative",
            "pass": "outcome_positive",
            "fail": "outcome_negative",
        }
        purposes: list[tuple[str, str]] = []

        def search(query: str, purpose: str):
            purposes.append((expected_by_query[query]["kind"], purpose))
            case = expected_by_query[query]
            return [{
                "doc_id": case["expected_doc_id"],
                "role": roles[case["expected"]],
                "evidence_status": "verified",
                "score": 0.9,
            }]

        report = EVAL.evaluate_cases(self.cases, search)
        self.assertEqual(report["accuracy"], 1.0)
        self.assertEqual(report["by_kind"]["route"]["accuracy"], 1.0)
        self.assertEqual(report["by_kind"]["outcome"]["accuracy"], 1.0)
        self.assertEqual(
            set(purposes),
            {("route", "route"), ("outcome", "solution")},
        )

    def test_wrong_document_and_wrong_role_are_reported_separately(self) -> None:
        case = self.cases[0]
        report = EVAL.evaluate_cases(
            [case],
            lambda _query, _purpose: [{
                "doc_id": "wrong-doc",
                "role": "route_negative",
                "evidence_status": "verified",
                "score": 0.8,
            }],
        )
        row = report["failures"][0]
        self.assertFalse(row["doc_correct"])
        self.assertFalse(row["semantic_correct"])
        self.assertEqual(report["accuracy"], 0.0)

    def test_apply_may_be_second_candidate_but_skip_must_be_top_one(self) -> None:
        apply_case = next(item for item in self.cases if item["expected"] == "apply")
        skip_case = next(item for item in self.cases if item["expected"] == "skip")

        def second(case):
            return [
                {
                    "doc_id": "legacy-related",
                    "role": "general",
                    "evidence_status": "legacy",
                    "score": 0.9,
                },
                {
                    "doc_id": case["expected_doc_id"],
                    "role": "route_positive" if case["expected"] == "apply" else "route_negative",
                    "evidence_status": "verified",
                    "score": 0.8,
                },
            ]

        apply_report = EVAL.evaluate_cases(
            [apply_case], lambda _query, _purpose: second(apply_case)
        )
        skip_report = EVAL.evaluate_cases(
            [skip_case], lambda _query, _purpose: second(skip_case)
        )
        self.assertEqual(apply_report["accuracy"], 1.0)
        self.assertEqual(apply_report["top1_accuracy"], 0.0)
        self.assertEqual(skip_report["accuracy"], 0.0)
        self.assertFalse(skip_report["failures"][0]["boundary_top1"])

    def test_inconclusive_result_cannot_pass(self) -> None:
        case = next(item for item in self.cases if item["expected"] == "apply")
        report = EVAL.evaluate_cases(
            [case],
            lambda _query, _purpose: [{
                "doc_id": case["expected_doc_id"],
                "role": "route_positive",
                "evidence_status": "inconclusive",
                "score": 1.0,
            }],
        )
        self.assertEqual(report["failures"][0]["predicted"], "inconclusive")


if __name__ == "__main__":
    unittest.main()
