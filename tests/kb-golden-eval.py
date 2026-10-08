#!/usr/bin/env python3
"""Run the data-file-backed KB golden set against hybrid search."""

from __future__ import annotations

import argparse
import json
import os
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = Path(__file__).with_name("kb-golden.jsonl")
kb_cli = SimpleNamespace(
    **runpy.run_path(str(ROOT / "hooks" / "lib" / "kb_cli.py"))
)


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".claude" / "plugins" / "data" / "sulde-cc" / "kb"


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict) or not isinstance(value.get("query"), str):
            raise ValueError(f"{path}:{number}: query must be a string")
        if not isinstance(value.get("expect"), list) or not value["expect"] or not all(isinstance(item, str) for item in value["expect"]):
            raise ValueError(f"{path}:{number}: expect must be a non-empty string list")
        if not isinstance(value.get("note"), str):
            raise ValueError(f"{path}:{number}: note must be a string")
        cases.append(value)
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--min-rate", type=float, default=0.8)
    args = parser.parse_args()
    if not 0 <= args.min_rate <= 1:
        parser.error("--min-rate must be between 0 and 1")

    cases = load_cases(args.data)
    hits = 0
    misses: list[dict[str, Any]] = []
    baseline_misses: list[dict[str, Any]] = []
    for index, case in enumerate(cases, 1):
        completed = kb_cli.run_cli(
            ROOT,
            kb_home(),
            "search",
            [case["query"], "-k", "5", "--json"],
            timeout=120,
        )
        if not completed.ok:
            detail = (
                completed.stderr.strip()
                or completed.stdout.strip()
                or completed.detail
                or completed.status
            )
            print(detail, file=sys.stderr)
            return completed.returncode or 2
        ids = [row["doc_id"] for row in json.loads(completed.stdout)]
        ok = any(expected in ids for expected in case["expect"])
        hits += int(ok)
        if not ok:
            misses.append(case)
        if "baseline-miss" in case["note"]:
            baseline_misses.append(case)
        print(f"{'✅' if ok else '❌'} {index:02d} {case['query']} → {ids[:5]} [{case['note']}]")

    rate = hits / len(cases) if cases else 0.0
    print(f"\nhit@5: {hits}/{len(cases)} = {rate:.1%} (minimum {args.min_rate:.1%})")
    print(f"misses: {len(misses)}; baseline-miss entries: {len(baseline_misses)}")
    for case in baseline_misses:
        print(f"- baseline-miss: {case['query']} → {case['expect']}")
    return 0 if rate >= args.min_rate else 1


if __name__ == "__main__":
    raise SystemExit(main())
