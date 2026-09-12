from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kb" / "sedimentation-eval.py"
SPEC = importlib.util.spec_from_file_location("sulde_sedimentation_eval", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
EVAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVAL)


class SedimentationEvalTests(unittest.TestCase):
    def cases(self) -> list[dict[str, str]]:
        markdown = (ROOT / "tests" / "test_sedimentation_schema.py").read_text(
            encoding="utf-8"
        )
        start = markdown.index('VALID = """') + len('VALID = """')
        end = markdown.index('"""\n\n\nclass SedimentationSchemaTests', start)
        return EVAL.cases_from_markdown(markdown[start:end], "fixture.md")

    def test_exports_four_polarized_cases(self) -> None:
        cases = self.cases()
        self.assertEqual(len(cases), 4)
        self.assertEqual({case["expected"] for case in cases}, {"apply", "skip", "pass", "fail"})
        self.assertEqual({case["kind"] for case in cases}, {"route", "outcome"})

    def test_score_reports_route_and_outcome_separately(self) -> None:
        cases = self.cases()
        predictions = {case["case_id"]: case["expected"] for case in cases}
        report = EVAL.score_cases(cases, predictions)
        self.assertEqual(report["accuracy"], 1.0)
        self.assertEqual(report["by_kind"]["route"]["accuracy"], 1.0)
        self.assertEqual(report["by_kind"]["outcome"]["accuracy"], 1.0)

    def test_missing_prediction_cannot_count_as_correct(self) -> None:
        cases = self.cases()
        report = EVAL.score_cases(cases, {})
        self.assertEqual(report["accuracy"], 0.0)
        self.assertEqual(len(report["missing_case_ids"]), 4)

    def test_prediction_loader_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "predictions.jsonl"
            path.write_text(
                json.dumps({"case_id": "same", "predicted": "apply"})
                + "\n"
                + json.dumps({"case_id": "same", "predicted": "skip"})
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(Exception, "duplicate prediction"):
                EVAL.load_predictions(path)


if __name__ == "__main__":
    unittest.main()
