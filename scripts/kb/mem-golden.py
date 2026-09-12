#!/usr/bin/env python3
"""Evaluate curated memory cases through the production recall gate."""

from __future__ import annotations

import argparse
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = REPO_ROOT / "tools" / "kb-index" / "golden-mem.jsonl"
_HOOK_LIB = REPO_ROOT / "hooks" / "lib"
kb_cli = SimpleNamespace(**runpy.run_path(str(_HOOK_LIB / "kb_cli.py")))
mem_recall = SimpleNamespace(**runpy.run_path(str(_HOOK_LIB / "mem_recall.py")))


class GoldenError(RuntimeError):
    """An input or search failure that prevents evaluation."""


def load_cases(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise GoldenError(f"cannot read cases: {error}") from error

    cases: list[dict[str, Any]] = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as error:
            raise GoldenError(f"{path}:{number}: invalid JSON: {error}") from error
        if not isinstance(case, dict):
            raise GoldenError(f"{path}:{number}: case must be an object")
        for field in ("id", "query", "project", "note"):
            if not isinstance(case.get(field), str):
                raise GoldenError(f"{path}:{number}: {field} must be a string")
        assertions = [
            key
            for key in ("expect_substring", "expect_none", "forbid_project")
            if key in case
        ]
        if len(assertions) != 1:
            raise GoldenError(
                f"{path}:{number}: exactly one recall assertion is required"
            )
        assertion = assertions[0]
        if assertion in {"expect_substring", "forbid_project"}:
            if not isinstance(case[assertion], str) or not case[assertion]:
                raise GoldenError(f"{path}:{number}: {assertion} must be non-empty")
        elif case[assertion] is not True:
            raise GoldenError(f"{path}:{number}: expect_none must be true")
        if "cross_project_ok" in case and not isinstance(case["cross_project_ok"], bool):
            raise GoldenError(f"{path}:{number}: cross_project_ok must be boolean")
        cases.append(case)
    if not cases:
        raise GoldenError(f"{path}: no cases found")
    return cases


def search(query: str, project: str) -> list[dict[str, Any]]:
    result = kb_cli.run_cli(
        REPO_ROOT,
        mem_recall._home(),
        "mem-search",
        [
            query,
            "-k",
            "5",
            "--json",
            "--project",
            project,
            "--skip-pending-embed",
        ],
        timeout=mem_recall.SEARCH_TIMEOUT_SECONDS,
    )
    if not result.ok:
        detail = result.stderr.strip() or result.stdout.strip() or result.detail
        if result.returncode is not None:
            raise GoldenError(f"mem-search exited {result.returncode}: {detail[:500]}")
        raise GoldenError(f"mem-search failed ({result.status}): {detail[:500]}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise GoldenError(f"invalid mem-search JSON: {error}") from error
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise GoldenError("mem-search JSON must be an array of objects")
    return payload


def describe(items: list[dict[str, Any]]) -> str:
    if not items:
        return "[]"
    summaries = []
    for item in items:
        content = " ".join(str(item.get("content") or "").split())
        summaries.append(
            f"id={item.get('id')} project={item.get('project')} content={content[:80]!r}"
        )
    return "[" + "; ".join(summaries) + "]"


def evaluate(case: dict[str, Any]) -> dict[str, Any]:
    raw = search(case["query"], case["project"])
    try:
        selected = mem_recall.select_recall_items(case["query"], case["project"], raw)
    except (TypeError, ValueError) as error:
        raise GoldenError(f"invalid mem-search result fields: {error}") from error
    if "expect_substring" in case:
        expected = case["expect_substring"]
        matches = [item for item in selected if expected in str(item.get("content") or "")]
        passed = bool(matches)
        reason = (
            f"found substring {expected!r} in id={matches[0].get('id')}"
            if passed
            else f"missing substring {expected!r}; injected={describe(selected)}"
        )
    elif case.get("expect_none") is True:
        passed = not selected
        reason = "injected set is empty" if passed else f"unexpected hits: {describe(selected)}"
    else:
        forbidden = case["forbid_project"]
        matches = [item for item in selected if item.get("project") == forbidden]
        passed = not matches
        reason = (
            f"no injected item from project {forbidden!r}"
            if passed
            else f"hit forbidden project {forbidden!r}: {describe(matches)}"
        )
    return {
        "id": case["id"],
        "query": case["query"],
        "project": case["project"],
        "note": case["note"],
        "pass": passed,
        "reason": reason,
        "injected": selected,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--min-rate", type=float, default=0.8)
    parser.add_argument("--json", action="store_true", help="emit one JSON result object")
    args = parser.parse_args()
    if not 0 <= args.min_rate <= 1:
        parser.error("--min-rate must be between 0 and 1")
    return args


def main() -> int:
    args = parse_args()
    try:
        cases = load_cases(args.data)
        results = [evaluate(case) for case in cases]
    except GoldenError as error:
        print(f"mem-golden: {error}", file=sys.stderr)
        return 2

    hits = sum(result["pass"] for result in results)
    total = len(results)
    rate = hits / total
    if args.json:
        print(
            json.dumps(
                {
                    "hit": hits,
                    "total": total,
                    "rate": rate,
                    "min_rate": args.min_rate,
                    "pass": rate >= args.min_rate,
                    "results": results,
                },
                ensure_ascii=False,
            )
        )
    else:
        for result in results:
            label = "PASS" if result["pass"] else "FAIL"
            print(f"{label} {result['id']} {result['query']} — {result['reason']}")
        print(f"hit {hits}/{total} = {rate:.1%} (minimum {args.min_rate:.1%})")
    return 0 if rate >= args.min_rate else 1


if __name__ == "__main__":
    raise SystemExit(main())
