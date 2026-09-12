#!/usr/bin/env python3
"""Run independent sedimentation-v2 paraphrases against real KB search."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / "tools" / "kb-index" / "sedimentation-paraphrase.jsonl"
kb_cli = SimpleNamespace(**runpy.run_path(str(ROOT / "hooks" / "lib" / "kb_cli.py")))

CASE_FIELDS = {
    "case_id",
    "kind",
    "query",
    "expected_doc_id",
    "expected",
    "note",
}
EXPECTED_BY_KIND = {
    "route": {"apply", "skip"},
    "outcome": {"pass", "fail"},
}
PURPOSE_BY_KIND = {"route": "route", "outcome": "solution"}
PREDICTION_BY_ROLE = {
    "route_positive": "apply",
    "route_negative": "skip",
    "outcome_positive": "pass",
    "solution": "pass",
    "outcome_negative": "fail",
}


class SearchEvaluationError(ValueError):
    pass


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def load_cases(path: Path) -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise SearchEvaluationError(f"{path}:{number}: invalid JSON: {error}") from error
        if not isinstance(value, dict) or set(value) != CASE_FIELDS:
            raise SearchEvaluationError(
                f"{path}:{number}: fields must be exactly {sorted(CASE_FIELDS)}"
            )
        if not all(isinstance(value[field], str) and value[field].strip() for field in CASE_FIELDS):
            raise SearchEvaluationError(f"{path}:{number}: every field must be a non-empty string")
        kind = value["kind"]
        if kind not in EXPECTED_BY_KIND or value["expected"] not in EXPECTED_BY_KIND[kind]:
            raise SearchEvaluationError(
                f"{path}:{number}: invalid kind/expected pair {kind}/{value['expected']}"
            )
        case_id = value["case_id"]
        if case_id in seen:
            raise SearchEvaluationError(f"{path}:{number}: duplicate case_id {case_id}")
        seen.add(case_id)
        cases.append({field: str(value[field]).strip() for field in CASE_FIELDS})
    if not cases:
        raise SearchEvaluationError(f"{path}: no cases")
    return cases


def prediction_for(result: dict[str, Any] | None) -> str:
    if not result:
        return "missing"
    if str(result.get("evidence_status") or "legacy") == "inconclusive":
        return "inconclusive"
    return PREDICTION_BY_ROLE.get(str(result.get("role") or ""), "unknown")


def evaluate_cases(
    cases: list[dict[str, str]],
    search: Callable[[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        purpose = PURPOSE_BY_KIND[case["kind"]]
        results = search(case["query"], purpose)
        if not isinstance(results, list) or any(not isinstance(item, dict) for item in results):
            raise SearchEvaluationError(f"{case['case_id']}: search result must be an object list")
        top = results[0] if results else None
        matched_rank = next(
            (
                index
                for index, item in enumerate(results, 1)
                if str(item.get("doc_id") or "") == case["expected_doc_id"]
            ),
            None,
        )
        matched = results[matched_rank - 1] if matched_rank is not None else None
        predicted = prediction_for(matched)
        actual_doc_id = str(top.get("doc_id") or "") if top else ""
        doc_correct = matched is not None
        semantic_correct = predicted == case["expected"]
        boundary_top1 = case["expected"] != "skip" or matched_rank == 1
        top1_predicted = prediction_for(top)
        top1_correct = (
            actual_doc_id == case["expected_doc_id"]
            and top1_predicted == case["expected"]
        )
        rows.append(
            {
                "case_id": case["case_id"],
                "kind": case["kind"],
                "purpose": purpose,
                "expected_doc_id": case["expected_doc_id"],
                "top_doc_id": actual_doc_id or None,
                "matched_rank": matched_rank,
                "expected": case["expected"],
                "predicted": predicted,
                "role": str(matched.get("role") or "") if matched else None,
                "score": matched.get("score") if matched else None,
                "doc_correct": doc_correct,
                "semantic_correct": semantic_correct,
                "boundary_top1": boundary_top1,
                "top1_correct": top1_correct,
                "correct": doc_correct and semantic_correct and boundary_top1,
            }
        )

    def summary(selected: list[dict[str, Any]]) -> dict[str, Any]:
        correct = sum(bool(row["correct"]) for row in selected)
        return {
            "total": len(selected),
            "correct": correct,
            "accuracy": round(correct / len(selected), 6) if selected else None,
        }

    overall = summary(rows)
    doc_correct = sum(bool(row["doc_correct"]) for row in rows)
    semantic_correct = sum(bool(row["semantic_correct"]) for row in rows)
    top1_correct = sum(bool(row["top1_correct"]) for row in rows)
    return {
        "schema": "sulde-sedimentation-search-eval-v1",
        **overall,
        "doc_accuracy": round(doc_correct / len(rows), 6) if rows else None,
        "semantic_accuracy": round(semantic_correct / len(rows), 6) if rows else None,
        "top1_correct": top1_correct,
        "top1_accuracy": round(top1_correct / len(rows), 6) if rows else None,
        "by_kind": {
            kind: summary([row for row in rows if row["kind"] == kind])
            for kind in ("route", "outcome")
        },
        "failures": [row for row in rows if not row["correct"]],
        "rows": rows,
    }


def real_search(home: Path, timeout: float, top_k: int) -> Callable[[str, str], list[dict[str, Any]]]:
    # kb_cli selects the interpreter from ``home`` while the invoked search
    # process resolves its database through this stable cross-host variable.
    os.environ["SULDE_KB_HOME"] = str(home)

    def search(query: str, purpose: str) -> list[dict[str, Any]]:
        completed = kb_cli.run_cli(
            ROOT,
            home,
            "search",
            [query, "-k", str(top_k), "--json", "--purpose", purpose],
            timeout=timeout,
        )
        if not completed.ok:
            detail = completed.stderr.strip() or completed.detail or completed.status
            raise SearchEvaluationError(f"search failed ({completed.status}): {detail}")
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise SearchEvaluationError(f"search returned invalid JSON: {error}") from error
        if not isinstance(result, list):
            raise SearchEvaluationError("search result must be a list")
        return result

    return search


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--kb-home", type=Path)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--min-rate", type=float, default=1.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.min_rate <= 1:
        parser.error("--min-rate must be between 0 and 1")
    if args.top_k < 1:
        parser.error("--top-k must be positive")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        cases = load_cases(args.data)
        home = args.kb_home.expanduser() if args.kb_home else kb_home()
        report = evaluate_cases(cases, real_search(home, args.timeout, args.top_k))
    except (OSError, UnicodeError, SearchEvaluationError) as error:
        print(f"sedimentation-search-eval: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for row in report["rows"]:
            mark = "✅" if row["correct"] else "❌"
            print(
                f"{mark} {row['case_id']} -> rank={row['matched_rank']} "
                f"{row['expected_doc_id']} [{row['role']} => {row['predicted']}] "
                f"top={row['top_doc_id']}"
            )
        print(
            f"\ncandidate@{args.top_k} + semantics: "
            f"{report['correct']}/{report['total']} = "
            f"{report['accuracy']:.1%} (minimum {args.min_rate:.1%})"
        )
        print(
            f"exact-top1={report['top1_accuracy']:.1%}; "
            f"doc@{args.top_k}={report['doc_accuracy']:.1%}; "
            f"semantic@doc={report['semantic_accuracy']:.1%}; "
            f"route={report['by_kind']['route']['accuracy']:.1%}; "
            f"outcome={report['by_kind']['outcome']['accuracy']:.1%}"
        )
    return 0 if report["accuracy"] is not None and report["accuracy"] >= args.min_rate else 1


if __name__ == "__main__":
    raise SystemExit(main())
