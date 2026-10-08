#!/usr/bin/env python3
"""Mechanical incremental fact collection for predictive execution (B2).

This module only COLLECTS facts: incremental worktree diffs against a
baseline, drift of the source identities bound into a prediction, and bounded
symbol-reference scans.  It never interprets: classification against a
prediction is returned as a mechanical suggestion, and the agent owns the
semantic judgment (which is recorded separately, see execution_judgment.py).

All collection is local, read-only and bounded; there is no repository-wide
scan and no model call.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

MAX_REFERENCES_PER_SYMBOL = 50
MAX_CHANGED_PATHS = 200


class FactError(ValueError):
    pass


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, check=False,
    )
    if result.returncode != 0:
        raise FactError(f"git {' '.join(args[:3])} failed: {result.stderr.strip()[:200]}")
    return result.stdout


def collect_diff_facts(repo: Path, *, baseline: str) -> dict[str, Any]:
    """Incremental worktree facts versus a revision: changed paths, split by
    whether they appear in the prediction's expected touch set."""
    if not baseline.strip():
        raise FactError("baseline revision is required")
    # NUL framing preserves quoted, Unicode and newline-containing filenames;
    # ls-files expands untracked directories instead of counting a directory as
    # one changed file. These Git commands return the complete name lists.
    changed = set(_git(repo, "diff", "--name-only", "-z", baseline).split("\0"))
    changed.update(_git(repo, "ls-files", "--others", "--exclude-standard", "-z").split("\0"))
    changed.discard("")
    total = len(changed)
    ordered = sorted(changed)[:MAX_CHANGED_PATHS]
    return {"baseline": baseline, "changed_paths": ordered, "changed_count": len(ordered),
            "changed_count_total": total, "omitted_count": total - len(ordered),
            "truncated": total > len(ordered), "comparison": "task_baseline_to_worktree"}


def match_entry(path: str, expected: str) -> bool:
    """Exact path or directory/module-prefix match."""
    return path == expected or path.startswith(expected.rstrip("/") + "/") or path.startswith(expected.rstrip("/") + ".")


def split_by_expected(changed_paths: list[str], expected_paths: list[str]) -> dict[str, list[str]]:
    """Mechanical split only.  Expected entries may be exact paths or path
    prefixes (directory or module prefixes); semantic judgment stays with the
    agent."""

    expected_paths = [e for e in (item.strip() for item in expected_paths) if e]
    inside = [p for p in changed_paths if any(match_entry(p, e) for e in expected_paths)]
    outside = [p for p in changed_paths if p not in inside]
    return {"inside_expected": inside, "outside_expected": outside}


def source_identity_drift(repo: Path, source_identities: dict[str, str]) -> dict[str, Any]:
    """Compare prediction-bound content digests with current file contents."""
    drift = {}
    for path, expected in sorted(source_identities.items()):
        file = repo / path
        if not file.is_file():
            actual = "missing"
        else:
            actual = hashlib.sha256(file.read_bytes()).hexdigest()[:16]
        if actual != expected:
            drift[path] = {"expected": expected, "actual": actual}
    return {"drifted": drift, "drift_count": len(drift)}


def symbol_references(repo: Path, symbols: list[str], *, path_prefix: str = "scripts") -> dict[str, Any]:
    """Bounded textual reference scan.  Occurrences are candidates, not proof
    of semantic dependency; the agent decides relevance."""
    if not symbols or not all(symbol.strip() for symbol in symbols):
        raise FactError("symbols must be non-empty strings")
    references: dict[str, list[str]] = {}
    for symbol in symbols:
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", "--include=*.md", "-m", "1",
             "--", symbol, str(repo / path_prefix)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, check=False,
        )
        hits = []
        for line in result.stdout.splitlines():
            if not line:
                continue
            rel = line.split(":", 1)[0]
            try:
                rel = str(Path(rel).relative_to(repo))
            except ValueError:
                pass
            hits.append(rel)
            if len(hits) >= MAX_REFERENCES_PER_SYMBOL:
                break
        references[symbol] = sorted(set(hits))
    return {"references": references,
            "truncated": any(len(v) >= MAX_REFERENCES_PER_SYMBOL for v in references.values())}


def classify_against_prediction(facts: dict[str, Any], split: dict[str, Any],
                                prediction: dict[str, Any]) -> dict[str, Any]:
    """Mechanical verdict SUGGESTION.  larger: changes outside the expected
    touch set; smaller: expected entries with no change; divergent: bound
    source identities drifted; as_predicted otherwise.  The agent may accept
    or override with reasons via a judgment record."""
    if (facts.get("diff") or {}).get("truncated") or facts.get("truncated"):
        return {"suggested_verdict": None, "incomplete": True,
                "reason": "incomplete changed-path collection; no prediction verdict recorded"}
    expected_entries = list((prediction.get("expected_touch") or {}).values())
    expected_flat = [item for group in expected_entries if isinstance(group, list) for item in group]
    expected_flat += [item for item in expected_entries if isinstance(item, str)]
    touched = facts.get("changed_paths") or []
    split = split or split_by_expected(touched, expected_flat)
    untouched_expected = [
        entry for entry in expected_flat
        if not any(match_entry(path, entry) for path in touched)
    ]
    drift = facts.get("source_identity_drift") or {}
    expected_paths = set(facts.get("expected_paths") or [])
    relevant_drift = {path: row for path, row in (drift.get("drifted") or {}).items()
                      if not any(match_entry(path, entry) for entry in expected_paths)}
    if relevant_drift:
        return {"suggested_verdict": "divergent",
                "reason": (f"{len(relevant_drift)} bound source identity(ies) outside the "
                           "expected touch changed; prediction marked stale")}
    if split.get("outside_expected"):
        return {"suggested_verdict": "larger_than_predicted",
                "reason": f"{len(split['outside_expected'])} changed path(s) outside expected touch"}
    if untouched_expected:
        # R1-03: fewer touched expectations is a FACT for the agent to judge
        # (reasonable simplification vs missed consumer) — never an automatic
        # defect or a human gate.
        return {"suggested_verdict": "smaller_than_predicted",
                "untouched_expected": untouched_expected,
                "reason": (f"{len(untouched_expected)} expected entr"
                           "y(ies) untouched; judge simplification vs omission")}
    return {"suggested_verdict": "as_predicted",
            "untouched_expected": [],
            "reason": "changes confined to the expected touch set"}


def _feedback_path_label(path: str) -> str:
    """Only bounded canonical relative labels; sensitive/opaque names are hashes."""
    parts = path.split("/")
    unsafe = (
        not path or len(path) > 160 or "\\" in path or ":" in path
        or any(part in {"", ".", ".."} for part in parts)
        or any(not (char.isalnum() or char in "/._-") for char in path)
        or any(unicodedata.category(char).startswith("C") for char in path)
        or re.search(r"(?i)(secret|credential|password|passwd|token|private|id_rsa|id_ed25519|\.env|\.pem|\.key|api[_-]?key)", path)
    )
    if unsafe:
        return "[path-sha256:" + hashlib.sha256(path.encode("utf-8", errors="replace")).hexdigest()[:24] + "]"
    return path


def feedback_scope_facts(bundle: dict[str, Any], verdict: dict[str, Any]) -> list[str]:
    """Bounded observed scope, not permission or a semantic dependency judgment."""
    diff = bundle.get("diff") or {}
    result = [str(verdict["reason"]),
              "comparison=task_baseline_to_worktree (not per-attempt delta)",
              f"changed_observed={diff.get('changed_count', 'unknown')} "
              f"changed_total={diff.get('changed_count_total', 'unknown')} "
              f"collection_omitted={diff.get('omitted_count', 'unknown')}"]
    entries = [("outside expected", path) for path in
               (bundle.get("split") or {}).get("outside_expected", [])]
    entries += [("untouched expected", path) for path in verdict.get("untouched_expected", [])]
    result.extend(f"{kind}: {_feedback_path_label(path)}" for kind, path in entries[:12])
    if len(entries) > 12:
        result.append(f"scope detail omitted={len(entries) - 12}; inspect authorized local diff")
    return result


def collect(repo: Path, *, baseline: str, expected_paths: list[str],
            source_identities: dict[str, str], symbols: list[str] | None = None) -> dict[str, Any]:
    """One-shot mechanical fact bundle (diff + drift + optional references)."""
    diff_facts = collect_diff_facts(repo, baseline=baseline)
    split = split_by_expected(diff_facts["changed_paths"], expected_paths)
    bundle: dict[str, Any] = {
        "changed_paths": diff_facts["changed_paths"],
        "diff": diff_facts,
        "split": split,
        "expected_paths": list(expected_paths),
        "source_identity_drift": source_identity_drift(repo, source_identities),
    }
    if symbols:
        bundle["symbol_references"] = symbol_references(repo, symbols)
    return bundle


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--expected", action="append", default=[])
    parser.add_argument("--sources", type=Path, default=None,
                        help="JSON file mapping paths to content digests")
    parser.add_argument("--symbols", default="", help="comma-separated symbols")
    args = parser.parse_args(argv)
    sources = json.loads(args.sources.read_text(encoding="utf-8")) if args.sources else {}
    symbols = [s for s in args.symbols.split(",") if s.strip()]
    bundle = collect(args.repo, baseline=args.baseline, expected_paths=args.expected,
                     source_identities=sources, symbols=symbols)
    print(json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    main()
