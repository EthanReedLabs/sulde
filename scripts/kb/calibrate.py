#!/usr/bin/env python3
"""Analyze KB recall/adoption logs and suggest a score threshold."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


CURRENT_SCORE_MIN = 0.55
CURRENT_MARGIN = 0.10
MIN_SAMPLES = 20
PROJECT_MIN_SAMPLES = 10
META_PROJECT_MARKER = "sulde-cc"

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hooks" / "lib"))
from recall_log import LOG_FILENAME, classify_recall_source  # noqa: E402


def state_dir() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return records
    for line in lines:
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def parse_ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]


def distribution(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "p50": statistics.median(values) if values else None,
        "p90": percentile(values, 0.9),
        "max": max(values) if values else None,
    }


def selected_at(scores: list[float], threshold: float) -> bool:
    eligible = [score for score in scores if score >= threshold]
    return bool(eligible) and (len(eligible) == 1 or eligible[0] - eligible[1] >= CURRENT_MARGIN)


def project_name(cwd: Any) -> str:
    value = str(cwd or "").strip().rstrip("/\\")
    return value.replace("\\", "/").rsplit("/", 1)[-1] if value else "unknown"


def is_meta_work(cwd: Any) -> bool:
    return META_PROJECT_MARKER in str(cwd or "")


def analyze_rows(rows: list[dict[str, Any]], min_samples: int) -> dict[str, Any]:
    injected_rows = [row for row in rows if row["injected"]]
    adopted_rows = [row for row in injected_rows if row["adopted"]]
    sensitivity: list[dict[str, Any]] = []
    for step in range(40, 81, 5):
        threshold = step / 100
        false_inject = 0
        missed_inject = 0
        selected = 0
        for row in rows:
            counterfactual = selected_at(row["scores"], threshold)
            selected += int(counterfactual)
            was_injected = bool(row["injected"])
            false_inject += int(counterfactual and was_injected and not row["adopted"])
            missed_inject += int(not counterfactual and was_injected and row["adopted"])
        sensitivity.append({
            "threshold": threshold,
            "would_inject": selected,
            "false_inject": false_inject,
            "missed_inject": missed_inject,
        })
    enough = len(injected_rows) >= min_samples
    recommendation: float | None = None
    if enough:
        recommendation = min(
            sensitivity,
            key=lambda row: (
                row["false_inject"] + row["missed_inject"],
                abs(row["threshold"] - CURRENT_SCORE_MIN),
            ),
        )["threshold"]
    return {
        "recall_count": len(rows),
        "injection_count": len(injected_rows),
        "adoption_count": len(adopted_rows),
        "adoption_rate": len(adopted_rows) / len(injected_rows) if injected_rows else 0.0,
        "sensitivity": sensitivity,
        "enough_data": enough,
        "recommendation": recommendation,
    }


def analyze(
    recalls: list[dict[str, Any]],
    feedback: list[dict[str, Any]],
    include_meta: bool = False,
) -> dict[str, Any]:
    feedback_by_doc: dict[str, list[datetime | None]] = {}
    for event in feedback:
        if event.get("event") != "read_after_inject" or not isinstance(event.get("doc_id"), str):
            continue
        feedback_by_doc.setdefault(event["doc_id"], []).append(parse_ts(event.get("ts")))

    rows: list[dict[str, Any]] = []
    for recall in recalls:
        if classify_recall_source(recall) != "kb":
            continue
        raw_scores = recall.get("top_scores")
        scores = [float(value) for value in raw_scores if isinstance(value, (int, float))] if isinstance(raw_scores, list) else []
        injected = [value for value in recall.get("injected", []) if isinstance(value, str)] if isinstance(recall.get("injected"), list) else []
        recall_ts = parse_ts(recall.get("ts"))
        adopted = False
        for doc_id in injected:
            for feedback_ts in feedback_by_doc.get(doc_id, []):
                if recall_ts is None or feedback_ts is None or feedback_ts >= recall_ts:
                    adopted = True
                    break
            if adopted:
                break
        cwd = recall.get("cwd")
        rows.append({
            "scores": scores,
            "injected": injected,
            "adopted": adopted,
            "cwd": cwd,
            "project": project_name(cwd),
            "meta": is_meta_work(cwd),
        })

    injected_rows = [row for row in rows if row["injected"]]
    adopted_rows = [row for row in injected_rows if row["adopted"]]
    unadopted_rows = [row for row in injected_rows if not row["adopted"]]
    noninjected_rows = [row for row in rows if not row["injected"] and row["scores"]]
    adopted_scores = [row["scores"][0] for row in adopted_rows if row["scores"]]
    unadopted_scores = [row["scores"][0] for row in unadopted_rows if row["scores"]]
    noninjected_scores = [row["scores"][0] for row in noninjected_rows]

    project_rows: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        project_rows.setdefault(row["project"], []).append(row)
    projects = {
        name: analyze_rows(bucket, PROJECT_MIN_SAMPLES)
        for name, bucket in sorted(project_rows.items())
    }
    meta_excluded = 0 if include_meta else sum(row["meta"] for row in rows)
    recommendation_rows = [
        row
        for row in rows
        if row["project"] != "unknown" and (include_meta or not row["meta"])
    ]
    recommendation_report = analyze_rows(recommendation_rows, MIN_SAMPLES)
    return {
        "recall_count": len(rows),
        "injection_count": len(injected_rows),
        "adoption_count": len(adopted_rows),
        "adoption_rate": len(adopted_rows) / len(injected_rows) if injected_rows else 0.0,
        "score_distributions": {
            "adopted_injection": distribution(adopted_scores),
            "unadopted_injection": distribution(unadopted_scores),
            "noninjected_top1": distribution(noninjected_scores),
        },
        "current": {"score_min": CURRENT_SCORE_MIN, "margin": CURRENT_MARGIN},
        "sensitivity": recommendation_report["sensitivity"],
        "enough_data": recommendation_report["enough_data"],
        "recommendation": recommendation_report["recommendation"],
        "recommendation_sample_count": recommendation_report["recall_count"],
        "recommendation_injection_count": recommendation_report["injection_count"],
        "meta_excluded_count": meta_excluded,
        "include_meta": include_meta,
        "projects": projects,
    }


def fmt(value: Any) -> str:
    return "-" if value is None else f"{value:.3f}" if isinstance(value, float) else str(value)


def print_report(report: dict[str, Any]) -> None:
    print("KB 检索采纳校准报告")
    print(f"注入次数: {report['injection_count']}")
    print(f"采纳次数: {report['adoption_count']}")
    print(f"采纳率: {report['adoption_rate']:.1%}")
    print("\n分数分布 (count/min/p50/p90/max)")
    for name, values in report["score_distributions"].items():
        print(f"- {name}: " + "/".join(fmt(values[key]) for key in ("count", "min", "p50", "p90", "max")))
    print("\n按项目分层")
    print("project  注入数  采纳数  采纳率  建议阈值")
    for name, values in report["projects"].items():
        suggestion = (
            f"{values['recommendation']:.2f}"
            if values["enough_data"]
            else "样本不足"
        )
        print(
            f"- {name}: {values['injection_count']} / {values['adoption_count']} / "
            f"{values['adoption_rate']:.1%} / {suggestion}"
        )
    if report["include_meta"]:
        print("元工作样本已通过 --include-meta 纳入阈值建议")
    else:
        print(f"元工作样本 {report['meta_excluded_count']} 条已剔除")
    print(
        f"阈值建议样本: {report['recommendation_sample_count']} 条召回 / "
        f"{report['recommendation_injection_count']} 次注入 (unknown 不参与建议)"
    )
    print(f"\n敏感性 (MARGIN={CURRENT_MARGIN:.2f})")
    print("threshold  would_inject  false_inject  missed_inject")
    for row in report["sensitivity"]:
        print(f"{row['threshold']:.2f}       {row['would_inject']:>5}          {row['false_inject']:>5}          {row['missed_inject']:>5}")
    if report["enough_data"]:
        print(f"\n建议 SCORE_MIN={report['recommendation']:.2f}, MARGIN={CURRENT_MARGIN:.2f}")
    else:
        print(f"\n数据不足,继续积累 (至少需要 {MIN_SAMPLES} 次注入)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--home", type=Path, default=state_dir(), help="KB runtime state directory")
    parser.add_argument("--include-meta", action="store_true", help="include sulde-cc meta-work in threshold recommendations")
    args = parser.parse_args()
    report = analyze(
        read_jsonl(args.home / LOG_FILENAME),
        read_jsonl(args.home / "feedback-log.jsonl"),
        include_meta=args.include_meta,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
