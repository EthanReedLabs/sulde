#!/usr/bin/env python3
"""Export and score sedimentation-v2 routing/outcome regression cases."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sedimentation_schema import extract_samples, split_document  # noqa: E402


ROLE_KIND = {
    "route_positive": "route",
    "route_negative": "route",
    "outcome_positive": "outcome",
    "outcome_negative": "outcome",
}


class EvaluationError(ValueError):
    pass


def tracked_documents() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "knowledge"], cwd=ROOT
    )
    return sorted(
        (
            Path(raw.decode("utf-8"))
            for raw in output.split(b"\0")
            if raw and raw.decode("utf-8").endswith(".md")
        ),
        key=lambda path: path.as_posix(),
    )


def _case_id(doc_id: str, role: str, text: str) -> str:
    digest = hashlib.sha256(f"{doc_id}\0{role}\0{text}".encode("utf-8")).hexdigest()
    return digest[:24]


def cases_from_markdown(markdown: str, source_path: str) -> list[dict[str, str]]:
    fields, _body = split_document(markdown)
    if fields.get("sedimentation_schema") != "2":
        return []
    doc_id = fields.get("doc_id", "")
    if not doc_id:
        raise EvaluationError(f"{source_path}: missing doc_id")
    cases: list[dict[str, str]] = []
    for sample in extract_samples(markdown):
        cases.append(
            {
                "case_id": _case_id(doc_id, sample.role, sample.input_text),
                "doc_id": doc_id,
                "source_path": source_path,
                "kind": ROLE_KIND[sample.role],
                "role": sample.role,
                "input": sample.input_text,
                "expected": sample.expected,
                "reason": sample.reason,
                "sample_source": sample.source,
            }
        )
    return cases


def collect_cases(paths: Iterable[Path]) -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in paths:
        path = raw if raw.is_absolute() else ROOT / raw
        if not path.is_file():
            raise EvaluationError(f"knowledge document does not exist: {raw}")
        relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
        for case in cases_from_markdown(path.read_text(encoding="utf-8"), relative):
            if case["case_id"] in seen:
                raise EvaluationError(f"duplicate evaluation case: {case['case_id']}")
            seen.add(case["case_id"])
            cases.append(case)
    return sorted(cases, key=lambda item: (item["doc_id"], item["role"], item["case_id"]))


def load_predictions(path: Path) -> dict[str, str]:
    predictions: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise EvaluationError(f"invalid prediction JSONL line {number}: {error}") from error
        if not isinstance(record, dict) or set(record) != {"case_id", "predicted"}:
            raise EvaluationError(
                f"prediction line {number} must contain exactly case_id and predicted"
            )
        case_id = record["case_id"]
        predicted = record["predicted"]
        if not isinstance(case_id, str) or not isinstance(predicted, str):
            raise EvaluationError(f"prediction line {number} fields must be strings")
        if case_id in predictions:
            raise EvaluationError(f"duplicate prediction case_id: {case_id}")
        predictions[case_id] = predicted.lower()
    return predictions


def score_cases(
    cases: list[dict[str, str]], predictions: dict[str, str]
) -> dict[str, Any]:
    expected_ids = {case["case_id"] for case in cases}
    extra = sorted(set(predictions) - expected_ids)
    rows: list[dict[str, Any]] = []
    for case in cases:
        predicted = predictions.get(case["case_id"])
        rows.append(
            {
                "case_id": case["case_id"],
                "doc_id": case["doc_id"],
                "kind": case["kind"],
                "role": case["role"],
                "expected": case["expected"],
                "predicted": predicted,
                "correct": predicted == case["expected"],
            }
        )
    by_kind: dict[str, dict[str, Any]] = {}
    for kind in ("route", "outcome"):
        selected = [row for row in rows if row["kind"] == kind]
        correct = sum(bool(row["correct"]) for row in selected)
        by_kind[kind] = {
            "total": len(selected),
            "correct": correct,
            "accuracy": round(correct / len(selected), 6) if selected else None,
        }
    correct = sum(bool(row["correct"]) for row in rows)
    return {
        "schema": "sulde-sedimentation-eval-v1",
        "total": len(rows),
        "predicted": sum(row["predicted"] is not None for row in rows),
        "correct": correct,
        "accuracy": round(correct / len(rows), 6) if rows else None,
        "by_kind": by_kind,
        "missing_case_ids": [row["case_id"] for row in rows if row["predicted"] is None],
        "extra_case_ids": extra,
        "failures": [row for row in rows if not row["correct"]],
    }


def _paths(values: list[Path]) -> list[Path]:
    return values or tracked_documents()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser("export", help="emit golden cases as JSONL")
    export.add_argument("paths", nargs="*", type=Path)
    score = subparsers.add_parser("score", help="score case_id/predicted JSONL")
    score.add_argument("predictions", type=Path)
    score.add_argument("paths", nargs="*", type=Path)
    score.add_argument("--min-accuracy", type=float, default=1.0)
    args = parser.parse_args()
    try:
        cases = collect_cases(_paths(args.paths))
        if args.command == "export":
            for case in cases:
                print(json.dumps(case, ensure_ascii=False, sort_keys=True))
            return 0
        if not 0 <= args.min_accuracy <= 1:
            raise EvaluationError("--min-accuracy must be between 0 and 1")
        report = score_cases(cases, load_predictions(args.predictions))
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        accuracy = report["accuracy"]
        return 0 if accuracy is not None and accuracy >= args.min_accuracy else 1
    except (EvaluationError, OSError, UnicodeError, ValueError) as error:
        print(f"sedimentation-eval: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
