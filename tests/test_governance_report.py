from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import copy
import sqlite3
from datetime import datetime, timedelta, timezone
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "kb" / "governance-report.py"
SPEC = importlib.util.spec_from_file_location("governance_report", SCRIPT)
assert SPEC and SPEC.loader
governance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(governance)


GOOD_REPORT = """## 总评

本周治理链路可用，当期 ⚠️ 0 项、⛔ 0 项，真正健康绿灯 1 项。

## 红绿灯表

| 指标 | 值 |
|---|---|
| demo | 1 |

## 行动建议

1. P0：处理红灯。

## 红队质疑

- 固定阈值是否仍能反映近期负载变化？建议提交复核提案。缺源判黄与低于阈值判黄折叠为同色，掩盖了观测能力缺失与质量问题的本质差异，后者更危险。

## 下期关注

- 复核趋势。
"""


def sample_lights(count: int = 2) -> list[dict[str, object]]:
    return [
        {
            "metric": f"metric_{index}",
            "current": index,
            "threshold_value": 10,
            "value": 10,
            "op": ">=",
            "unit": "count",
            "rationale": "test",
            "owner": "test-owner",
            "light": "green" if index else "red",
            "margin_ratio": 0.1,
            "near_edge": False,
            "breached": False,
            "diagnostic": None,
            "degraded": False,
            "trend_state": "无基线",
            "baseline_period_dates": [],
            "near_edge_streak": 0,
            "streak_counting_since": "2026-08-09",
            "missing_escalation_enabled": False,
        }
        for index in range(count)
    ]


def sample_snapshot() -> dict[str, object]:
    previous = f"""# 旧报告

## 总评

不应进入新 prompt。{'全景噪声' * 3_000}

## 红队质疑

- 上期红队内容。{'红队补充' * 1_000}

## 下期关注

- 上期关注内容。{'关注补充' * 1_000}
"""
    return {
        "collected_at": "2026-08-09T10:00:00+08:00",
        "kb_home": "/tmp/test-kb",
        "sources": {
            "previous_report": {
                "status": "available",
                "data": {"path": "/tmp/previous.md", "content": previous},
            }
        },
    }


class GovernanceReportTest(unittest.TestCase):
    def test_mem_adoption_groups_entries_by_opportunity_and_requires_full_coverage(self) -> None:
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            now = datetime.now(timezone.utc)
            adoption = root / "adoption.jsonl"
            recall = root / "recall.jsonl"
            recalls = []
            for key in ("one", "two", "missing"):
                cwd = f"/tmp/{key}"
                timestamp = now.isoformat()
                opportunity_id = hashlib.sha256(
                    f"claude\0{key}\0{cwd}\0{timestamp}".encode("utf-8")
                ).hexdigest()[:20]
                recalls.append({
                    "ts": timestamp,
                    "cwd": cwd,
                    "query_head": key,
                    "platform": None,
                    "top_scores": [0.9],
                    "injected": [1],
                    "source": "mem",
                    "session_id": key,
                    "channel": "claude",
                    "opportunity_id": opportunity_id,
                })
            opportunity_ids = [row["opportunity_id"] for row in recalls]
            adoption.write_text("\n".join([
                json.dumps({"ts": now.isoformat(), "opportunity_id": opportunity_ids[0], "entry_id": 1, "verdict": "adopted"}),
                json.dumps({"ts": now.isoformat(), "opportunity_id": opportunity_ids[0], "entry_id": 2, "verdict": "ignored"}),
                json.dumps({"ts": now.isoformat(), "opportunity_id": opportunity_ids[1], "entry_id": 3, "verdict": "ignored"}),
            ]) + "\n", encoding="utf-8")
            recall.write_text(
                "\n".join(json.dumps(row) for row in recalls) + "\n",
                encoding="utf-8",
            )
            result = governance.collect_mem_adoption(adoption, now, recall)
            self.assertEqual(result["samples_7d"], 2)
            self.assertEqual(result["adopted_7d"], 1)
            self.assertEqual(result["eligible_opportunities_7d"], 3)
            self.assertAlmostEqual(result["observation_coverage"], 2 / 3)
            self.assertEqual(result["rate"], "insufficient")

    def test_golden_candidates_source_available_and_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "golden-candidates.jsonl"
            path.write_text('{"id":"one"}\n{"id":"two"}\n', encoding="utf-8")
            self.assertEqual(governance.collect_golden_candidates(path)["pending"], 0)
            self.assertEqual(governance.collect_golden_candidates(path)["revision_required"], 2)
            path.unlink()
            self.assertEqual(governance.source(lambda: governance.collect_golden_candidates(path))["status"], governance.UNAVAILABLE)

    def test_graph_audit_source_available_and_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_dir = Path(temp_dir)
            (report_dir / "graph-audit-2026-08-10.md").write_text("- unsupported：4\n", encoding="utf-8")
            collect = lambda: governance.collect_latest_report(report_dir, "graph-audit-*.md", "unsupported", "unsupported")
            self.assertEqual(collect()["unsupported"], 4)
            (report_dir / "graph-audit-2026-08-10.md").unlink()
            self.assertEqual(governance.source(collect)["status"], governance.UNAVAILABLE)

    def test_kb_aging_source_available_and_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_dir = Path(temp_dir)
            (report_dir / "aging-2026-08-10.md").write_text("- 零采纳且超龄：9\n", encoding="utf-8")
            collect = lambda: governance.collect_latest_report(report_dir, "aging-*.md", "零采纳且超龄", "stale")
            self.assertEqual(collect()["stale"], 9)
            (report_dir / "aging-2026-08-10.md").unlink()
            self.assertEqual(governance.source(collect)["status"], governance.UNAVAILABLE)

    def test_kb_dedup_source_available_and_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_dir = Path(temp_dir)
            (report_dir / "dedup-2026-08-10.md").write_text("- 候选簇：3\n", encoding="utf-8")
            collect = lambda: governance.collect_latest_report(report_dir, "dedup-*.md", "候选簇", "clusters")
            self.assertEqual(collect()["clusters"], 3)
            (report_dir / "dedup-2026-08-10.md").unlink()
            self.assertEqual(governance.source(collect)["status"], governance.UNAVAILABLE)

    def run_main(self, llm_side_effect: object, timeout: float = 321) -> tuple[str, str, mock.Mock]:
        lights = sample_lights()
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = (
                mock.Mock(side_effect=llm_side_effect)
                if isinstance(llm_side_effect, BaseException)
                else mock.Mock(return_value=llm_side_effect)
            )
            args = argparse.Namespace(
                llm_cmd="fake-llm",
                llm_timeout=timeout,
                dry_run=False,
                collect_only=False,
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(governance, "parse_args", return_value=args),
                mock.patch.object(governance, "kb_home", return_value=Path(temp_dir)),
                mock.patch.object(governance, "load_thresholds", return_value={}),
                mock.patch.object(governance, "collect", return_value=sample_snapshot()),
                mock.patch.object(governance, "prepare_lights", return_value=lights),
                mock.patch.object(governance, "persist_governance_state"),
                mock.patch.object(governance, "notify"),
                mock.patch.object(governance.subprocess, "run", completed),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(governance.main(), 0)
            reports = list((Path(temp_dir) / "governance").glob("report-*.md"))
            self.assertEqual(len(reports), 1)
            report = reports[0].read_text(encoding="utf-8")
        return report, stderr.getvalue(), completed

    def test_timeout_is_labeled_and_machine_report_is_written(self) -> None:
        report, log, run = self.run_main(subprocess.TimeoutExpired(cmd="fake-llm", timeout=321))

        self.assertIn("仅机器红绿灯", report)
        self.assertIn("LLM 超时", report)
        self.assertNotIn("格式不合格", report)
        self.assertIn("category=timeout", log)
        self.assertEqual([call.kwargs["timeout"] for call in run.call_args_list], [321, 321])

    def test_invalid_format_is_labeled(self) -> None:
        response = subprocess.CompletedProcess(["fake-llm"], 0, stdout="not a report", stderr="")
        report, log, _ = self.run_main(response)

        self.assertIn("LLM 格式不合格", report)
        self.assertNotIn("LLM 超时", report)
        self.assertIn("category=format", log)

    def test_valid_report_writes_all_five_sections(self) -> None:
        response = subprocess.CompletedProcess(["fake-llm"], 0, stdout=GOOD_REPORT, stderr="")
        report, log, run = self.run_main(response)

        for heading in governance.REQUIRED_HEADINGS:
            self.assertIn(f"## {heading}", report)
        self.assertTrue(governance.valid_report(report))
        self.assertNotIn("仅机器红绿灯", report)
        self.assertEqual(log, "")
        self.assertEqual(run.call_count, 1)

    def test_command_failure_has_its_own_category(self) -> None:
        response = subprocess.CompletedProcess(["fake-llm"], 7, stdout="", stderr="boom")
        report, log, _ = self.run_main(response)

        self.assertIn("LLM 命令失败", report)
        self.assertIn("category=command", log)
        self.assertNotIn("格式不合格", report)

    def test_realistic_prompt_is_compact_and_keeps_red_team_clause(self) -> None:
        prompt = governance.build_prompt(sample_snapshot(), sample_lights(25), retry=True)

        self.assertLess(len(prompt), 8_000)
        self.assertIn("红队职责条款：必须提出≥1 条对现行阈值/规则/机制本身的质疑，不许全盘认可；质疑不得擅自改阈值，只能形成待审提案。", prompt)
        self.assertIn("上期红队内容", prompt)
        self.assertIn("上期关注内容", prompt)
        self.assertNotIn("不应进入新 prompt", prompt)
        self.assertNotIn('"collected_at"', prompt)
        self.assertIn("贴边告警、缺源诊断/连续升级、相对退化检测", prompt)
        self.assertIn("当期 ⚠️ 0 项、⛔ 0 项", prompt)
        self.assertIn("真正健康绿灯 24 项", prompt)
        self.assertIn("P-12 至 P-17", prompt)
        self.assertIn("升级暂缓:计数起点待人工回填", prompt)
        self.assertIn(governance.DECISION_TRACE, prompt)

    def test_margin_ratio_at_edge_wide_and_upper_bound(self) -> None:
        self.assertEqual(governance.threshold_margin_ratio(10, 10, ">="), 0)
        self.assertAlmostEqual(governance.threshold_margin_ratio(15, 10, ">="), 0.5)
        self.assertAlmostEqual(governance.threshold_margin_ratio(95, 100, "<="), 0.05)
        snapshot = self.metric_snapshot()
        with mock.patch.object(governance, "metric_values", return_value={"metric": 10}):
            self.assertTrue(governance.prejudge(snapshot, {"metric": self.rule(10, ">=")})[0]["near_edge"])
        with mock.patch.object(governance, "metric_values", return_value={"metric": 15}):
            self.assertFalse(governance.prejudge(snapshot, {"metric": self.rule(10, ">=")})[0]["near_edge"])

    def test_absolute_margin_trial_requires_relative_and_absolute_nearness(self) -> None:
        rule = {**self.rule(300_000, "<="), "absolute_margin": 2_000}
        snapshot = self.metric_snapshot()
        with mock.patch.object(governance, "metric_values", return_value={"metric": 297_000}):
            row = governance.prejudge(snapshot, {"metric": rule})[0]
            self.assertAlmostEqual(row["margin_ratio"], 0.01)
            self.assertFalse(row["near_edge"])
        with mock.patch.object(governance, "metric_values", return_value={"metric": 299_000}):
            self.assertTrue(governance.prejudge(snapshot, {"metric": rule})[0]["near_edge"])

    @staticmethod
    def rule(value: float, op: str = ">=") -> dict[str, object]:
        return {"value": value, "op": op, "unit": "count", "rationale": "test", "owner": "test", "observation": {"source": "status", "field": "test", "bucket": "runtime_health"}}

    @staticmethod
    def metric_snapshot() -> dict[str, object]:
        sources = {name: {"status": "available", "data": {}} for name in governance.METRIC_SOURCES.values()}
        return {"sources": sources}

    def test_missing_diagnostics_distinguish_no_source_and_small_sample(self) -> None:
        snapshot = {
            "sources": {
                "mem_adoption": {
                    "status": "available",
                    "data": {"samples_7d": 4, "required_minimum": 10, "upstream_present": True},
                }
            }
        }
        small = governance.unavailable_diagnostic(snapshot, "mem_adoption_rate", "insufficient")
        snapshot["sources"]["mem_adoption"]["data"]["upstream_present"] = False
        missing = governance.unavailable_diagnostic(snapshot, "mem_adoption_rate", "insufficient")
        # P-16 新增 collected_at/sample_denominator 字段:核心四项用包含式断言,
        # 避免每加一个诊断字段就要改断言(全等比较是脆断源)
        for key, expected in (("reason", "insufficient_sample"), ("sample_count", 4),
                              ("required_minimum", 10), ("upstream_present", True)):
            self.assertEqual(small[key], expected)
        self.assertIn("collected_at", small)
        self.assertIn("sample_denominator", small)
        self.assertEqual(missing["reason"], "no_source")
        self.assertIn("样本不足(4/10)", governance.display_diagnostic(small))
        self.assertIn("数据源断链/null(取不到)", governance.display_diagnostic(missing))

    def test_missing_streak_declares_start_and_escalation_is_paused(self) -> None:
        row = {"metric": "metric", "light": "yellow", "diagnostic": governance.missing_diagnostic("no_source", 0, 1, False)}
        previous: dict[str, object] = {}
        for period in ("2026-08-02", "2026-08-09", "2026-08-16"):
            current = [dict(row)]
            governance.apply_missing_streaks(current, previous, period, 3)
            previous = {
                "metric": {
                    "count": current[0]["missing_streak"],
                    "last_period": period,
                    "missing": True,
                    "counting_since": current[0]["streak_counting_since"],
                }
            }
        self.assertEqual(current[0]["missing_streak"], 3)
        self.assertEqual(current[0]["streak_counting_since"], "2026-08-02")
        self.assertEqual(current[0]["light"], "yellow")
        self.assertFalse(current[0]["missing_escalation_enabled"])
        rerun = [dict(row)]
        governance.apply_missing_streaks(rerun, previous, "2026-08-16", 3)
        self.assertEqual(rerun[0]["missing_streak"], 3)
        self.assertEqual(rerun[0]["light"], "yellow")
        enabled = [dict(row)]
        governance.apply_missing_streaks(enabled, previous, "2026-08-16", 3, escalation_enabled=True)
        self.assertEqual(enabled[0]["light"], "red")

    def test_near_edge_streak_is_continuous_and_idempotent(self) -> None:
        previous: dict[str, object] = {}
        row = {"metric": "metric", "near_edge": True}
        for period in ("2026-08-02", "2026-08-09"):
            current = [dict(row)]
            governance.apply_near_edge_streaks(current, previous, period)
            previous = {
                "metric": {
                    "near_edge_count": current[0]["near_edge_streak"],
                    "near_edge": True,
                    "last_period": period,
                }
            }
        self.assertEqual(governance.display_margin({"margin_ratio": 0.01, "near_edge": True, "near_edge_streak": 2}), "1.00% ⚠️×2⁺")
        rerun = [dict(row)]
        governance.apply_near_edge_streaks(rerun, previous, "2026-08-09")
        self.assertEqual(rerun[0]["near_edge_streak"], 2)

    def test_degradation_uses_recent_history_without_changing_light(self) -> None:
        history = [{"period": f"2026-07-{index:02d}", "values": {"coverage": 0.8}} for index in range(1, 7)]
        lights = [{"metric": "coverage", "current": 0.6, "op": ">=", "light": "green", "degraded": False}]
        governance.apply_degradation(lights, history, "2026-08-09", 0.2)
        self.assertTrue(lights[0]["degraded"])
        self.assertEqual(lights[0]["light"], "green")
        self.assertEqual(lights[0]["trend_state"], "↓退化")

    def test_trend_states_and_detector_proof(self) -> None:
        history = [{"period": "2026-08-02", "values": {"steady": 10.0, "down": 10.0}}]
        lights = [
            {
                "metric": metric,
                "current": current,
                "threshold_value": 0,
                "op": ">=",
                "unit": "count",
                "owner": "test",
                "light": "green",
                "margin_ratio": 0.1,
                "near_edge": False,
            }
            for metric, current in (("new", 1.0), ("steady", 10.0), ("down", 5.0))
        ]
        governance.apply_degradation(lights, history, "2026-08-09", 0.2)
        self.assertEqual([row["trend_state"] for row in lights], ["无基线", "未见退化", "↓退化"])
        self.assertEqual(
            governance.detector_proof(lights),
            "检测器自证：本期比对了 2 项指标；基线期数 1；基线最早日期 2026-08-02；未比对项清单及原因：new(历史基线不足)",
        )
        table = governance.machine_table(lights)
        self.assertIn("| 余量 | 诊断 | 趋势 | 灯色 |", table)
        self.assertIn("| steady | 10.0 |", table)
        self.assertIn("| 未见退化（10.0→10.0，变化 +0.00%） |", table)

    def test_valid_report_requires_warning_count_in_summary(self) -> None:
        self.assertTrue(governance.valid_report(GOOD_REPORT))
        self.assertFalse(governance.valid_report(GOOD_REPORT.replace("，当期 ⚠️ 0 项、⛔ 0 项", "")))
        self.assertFalse(governance.valid_report(GOOD_REPORT.replace("，真正健康绿灯 1 项", "")))

    def test_p20_green_display_tiers_are_exclusive_and_yellow_is_excluded(self) -> None:
        base = {
            "current": 10,
            "threshold_value": 10,
            "value": 10,
            "op": ">=",
            "unit": "count",
            "rationale": "test",
            "owner": "test-owner",
            "margin_ratio": 0.1,
            "breached": False,
            "diagnostic": None,
            "trend_state": "未见退化",
        }
        lights = [
            {**base, "metric": "healthy", "light": "green", "near_edge": False},
            {**base, "metric": "edge", "light": "green", "near_edge": True},
            {**base, "metric": "degraded", "light": "green", "near_edge": False, "trend_state": "↓退化"},
            {**base, "metric": "edge_degraded", "light": "green", "near_edge": True, "trend_state": "↓退化"},
            {**base, "metric": "missing", "light": "yellow", "near_edge": False, "trend_state": "↓退化"},
        ]

        self.assertEqual(
            [governance.green_display_tier(row) for row in lights],
            ["余量充裕", "踩线", "高位退化", "踩线", None],
        )
        self.assertEqual(
            [governance.display_light(row) for row in lights],
            ["🟢[余量充裕]", "🟢[踩线]", "🟢[高位退化]", "🟢[踩线]", "🟡"],
        )
        self.assertEqual(governance.healthy_green_count(lights), 1)
        summary = governance.compact_lights(lights)
        self.assertEqual(summary.count("🟢[踩线]"), 2)
        self.assertEqual(summary.count("🟢[高位退化]"), 1)
        self.assertNotIn("🟡[", summary)

        prompt = governance.build_prompt(sample_snapshot(), lights)
        self.assertIn("真正健康绿灯 1 项", prompt)

    def test_prompt_requires_no_capacity_when_warning_share_is_high(self) -> None:
        lights = sample_lights(4)
        for row in lights[:2]:
            row["near_edge"] = True
            row["near_edge_streak"] = 1
        prompt = governance.build_prompt(sample_snapshot(), lights)
        self.assertIn("当期 ⚠️ 2 项、⛔ 0 项", prompt)
        self.assertIn("合格但无余量", prompt)

    def test_p12_buckets_breached_and_near_edge_separately(self) -> None:
        snapshot = self.metric_snapshot()
        with mock.patch.object(governance, "metric_values", return_value={"broken": 0, "edging": 10.2}):
            rows = governance.prejudge(
                snapshot,
                {"broken": self.rule(10), "edging": self.rule(10)},
            )
        governance.apply_near_edge_streaks(rows, {}, "2026-08-10")
        governance.apply_breach_streaks(rows, {}, "2026-08-10")
        self.assertEqual(rows[0]["margin_ratio"], -1.0)
        self.assertTrue(rows[0]["breached"])
        self.assertFalse(rows[0]["near_edge"])
        self.assertFalse(rows[1]["breached"])
        self.assertTrue(rows[1]["near_edge"])
        self.assertEqual(governance.warning_count(rows), 1)
        self.assertEqual(governance.breach_count(rows), 1)
        prompt = governance.build_prompt(sample_snapshot(), rows)
        self.assertIn("当期 ⚠️ 1 项、⛔ 1 项", prompt)

    def test_p13_all_continuous_counters_declare_three_fields_and_lower_bound(self) -> None:
        row = {
            "metric": "metric",
            "near_edge": True,
            "breached": False,
            "diagnostic": governance.missing_diagnostic("no_source", 0, 1, False),
            "light": "yellow",
        }
        rows = [row]
        governance.apply_missing_streaks(rows, {}, "2026-08-10", 3)
        governance.apply_near_edge_streaks(rows, {}, "2026-08-10")
        governance.apply_breach_streaks(rows, {}, "2026-08-10")
        proof = governance.counter_contract_summary(rows)
        for field in ("计数起点日期", "起点是否已回填", "回填前/后双值"):
            self.assertEqual(proof.count(field), 3)
        self.assertIn("⚠️×1⁺", governance.display_margin({**row, "margin_ratio": 0.02}))
        self.assertIn("缺源×1⁺", governance.display_diagnostic(row["diagnostic"], row["missing_streak"]))
        broken = {**row, "near_edge": False, "breached": True, "margin_ratio": -1.0}
        governance.apply_breach_streaks([broken], {}, "2026-08-10")
        self.assertIn("⛔已破 1⁺ 期", governance.display_margin(broken))

    def test_p14_trend_renamed_and_includes_magnitude(self) -> None:
        lights = [{"metric": "age", "current": 10.0, "op": "<=", "unit": "seconds", "light": "green"}]
        governance.apply_degradation(lights, [{"period": "2026-08-03", "values": {"age": 100.0}}], "2026-08-10", 0.2)
        self.assertEqual(lights[0]["trend_state"], "未见退化")
        rendered = governance.display_trend(lights[0])
        self.assertIn("100.0→10.0", rendered)
        self.assertIn("变化 -90.00%", rendered)

    def test_p16_null_zero_and_self_proof_conflict(self) -> None:
        snapshot = {
            "collected_at": "2026-08-10T12:00:00+08:00",
            "sources": {"mem_adoption": {"status": "available", "data": {"samples_7d": 20, "required_minimum": 10}}},
        }
        null_diag = governance.unavailable_diagnostic(snapshot, "mem_adoption_rate", None)
        zero_diag = governance.unavailable_diagnostic(snapshot, "mem_adoption_rate", 0)
        self.assertIn("null(取不到)", governance.display_diagnostic(null_diag))
        zero_text = governance.display_diagnostic(zero_diag)
        self.assertIn("0(取到零)", zero_text)
        self.assertIn("采集 2026-08-10T12:00:00+08:00", zero_text)
        self.assertIn("样本分母 20", zero_text)
        rows = [{"metric": "mem_adoption_rate", "light": "red", "diagnostic": zero_diag}]
        previous = {"mem_adoption_rate": {"count": 2, "missing": True, "last_period": "2026-08-03"}}
        governance.apply_missing_streaks(rows, previous, "2026-08-10", 3)
        self.assertTrue(rows[0]["self_proof_conflict"])
        self.assertIn("自证冲突", governance.display_diagnostic(zero_diag, conflict=True))

    def test_p17_detector_proof_lists_uncompared_reason_and_blindness(self) -> None:
        lights = [
            {
                "metric": "missing_metric",
                "trend_state": "无基线",
                "baseline_period_dates": [],
                "trend_uncompared_reason": "缺源",
                "trend_permanently_blind": True,
            }
        ]
        proof = governance.detector_proof(lights)
        self.assertIn("未比对项清单及原因", proof)
        self.assertIn("missing_metric(缺源，趋势永久失明)", proof)

    def test_state_persistence_replaces_same_period(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            snapshot = {"collected_at": "2026-08-09T10:00:00+08:00"}
            lights = [
                {
                    "metric": "metric",
                    "current": 1.0,
                    "diagnostic": None,
                    "missing_streak": 0,
                    "streak_counting_since": "2026-08-09",
                    "near_edge_streak": 1,
                    "near_edge": True,
                }
            ]
            governance.persist_governance_state(home, snapshot, lights)
            lights[0]["current"] = 2.0
            governance.persist_governance_state(home, snapshot, lights)
            rows = [json.loads(line) for line in (home / "governance" / "history.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["values"]["metric"], 2.0)
            state = json.loads((home / "governance" / "streaks.json").read_text())
            self.assertEqual(state["metrics"]["metric"]["counting_since"], "2026-08-09")
            self.assertEqual(state["metrics"]["metric"]["near_edge_count"], 1)

    def make_coverage(self, home, l2=11, l3=34):
        path = home / "memory.db"
        now = datetime(2026, 9, 5, 12).astimezone()
        normal = datetime(2026, 9, 4, 12).astimezone().astimezone(timezone.utc).isoformat()
        scheduled = datetime(2026, 9, 4, 9, 31).astimezone().astimezone(timezone.utc).isoformat()
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE mem_edges(id INTEGER PRIMARY KEY, ts TEXT)")
            db.executemany("INSERT INTO mem_edges VALUES (?,?)",
                           [(i + 1, normal if i < l2 else scheduled) for i in range(l2 + l3)])
        return path, now

    def test_l2_absolute_window_baseline_and_honest_red(self):
        with tempfile.TemporaryDirectory() as temp:
            path, now = self.make_coverage(Path(temp))
            first = governance.collect_edges(path, now)
            self.assertEqual((first["numerator"], first["denominator"]), (11, 45))
            self.assertAlmostEqual(first["l2_coverage_rate"], 11 / 45)
            self.assertEqual(first["discontinuity"]["state"], "unknown")
            self.assertFalse(first["reusable_success_evidence"])
            current = governance.collect_edges(path, now + timedelta(seconds=1), first)
            self.assertEqual(current["discontinuity"]["state"], "continuous")
            self.assertEqual(current["baseline"]["denominator"], 45)
            self.assertEqual(current["baseline"]["provenance"]["observation_sha256"], first["observation_sha256"])
            self.assertEqual(current["window"]["bounds"], "[start,end)")
            self.assertTrue(current["window"]["start_utc"].endswith("+00:00"))
            snapshot = {"collected_at": now.isoformat(), "sources": {
                "mem_edges": {"status": "available", "data": current}}}
            rule = governance.load_thresholds()["l2_coverage_rate"]
            row = governance.prejudge(snapshot, {"l2_coverage_rate": rule})[0]
            self.assertEqual(row["light"], "red")

    def test_l2_denominator_discontinuity_cannot_turn_green_or_reuse_history(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            path, now = self.make_coverage(home)
            baseline = governance.collect_edges(path, now)
            with sqlite3.connect(path) as db:
                db.execute("DELETE FROM mem_edges WHERE id > 11")
            current = governance.collect_edges(path, now + timedelta(seconds=1), baseline)
            self.assertEqual(current["discontinuity"]["state"], "discontinuous")
            self.assertEqual(current["denominator"], 11)
            self.assertEqual(current["l2_coverage_rate"], 1)
            self.assertFalse(current["reusable_success_evidence"])
            snapshot = {"collected_at": now.isoformat(), "sources": {
                "mem_edges": {"status": "available", "data": current}}}
            rule = governance.load_thresholds()["l2_coverage_rate"]
            lights = governance.prejudge(snapshot, {"l2_coverage_rate": rule})
            self.assertEqual(lights[0]["light"], "yellow")
            governance.persist_governance_state(home, snapshot, lights)
            history = governance.read_history(home / "governance/history.jsonl")
            self.assertNotIn("l2_coverage_rate", history[-1]["values"])
            self.assertEqual(history[-1]["l2_observation"]["discontinuity"]["state"], "discontinuous")

    def test_l2_future_offsets_bad_dates_empty_and_absent_denominator(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            path, now = self.make_coverage(home, 0, 0)
            empty = governance.collect_edges(path, now)
            self.assertIsNone(empty["l2_coverage_rate"])
            self.assertEqual(empty["evidence_status"], "inconclusive")
            cutoff = now - timedelta(days=7)
            with sqlite3.connect(path) as db:
                db.executemany("INSERT INTO mem_edges VALUES (?,?)", [
                    (1, cutoff.isoformat()), (2, now.isoformat()),
                    (3, (now + timedelta(days=1)).isoformat()),
                    (4, (cutoff - timedelta(microseconds=1)).isoformat()),
                ])
            self.assertEqual(governance.collect_edges(path, now)["denominator"], 1)
            with sqlite3.connect(path) as db:
                db.execute("INSERT INTO mem_edges VALUES(5, 'bad date')")
            broken = governance.collect_edges(path, now)
            self.assertIsNone(broken["denominator"])
            self.assertIsNone(broken["l2_coverage_rate"])
            self.assertFalse(broken["reusable_success_evidence"])
            absent = governance.source(lambda: governance.collect_edges(home / "absent.db", now))
            self.assertEqual(absent["status"], "unavailable")
            self.assertFalse((home / "absent.db").exists())

    def test_l2_legacy_or_tampered_baseline_is_inconclusive(self):
        with tempfile.TemporaryDirectory() as temp:
            path, now = self.make_coverage(Path(temp))
            first = governance.collect_edges(path, now)
            first["denominator"] = 999
            result = governance.collect_edges(path, now, first)
            self.assertEqual(result["baseline"]["status"], "inconclusive")
            self.assertFalse(result["reusable_success_evidence"])
            result = governance.collect_edges(path, now, {"l2_coverage_rate": 0.9})
            self.assertEqual(result["discontinuity"]["state"], "unknown")
            snapshot = {"collected_at": now.isoformat(), "sources": {
                "mem_edges": {"status": "available", "data": {"l2_coverage_rate": 0.9}}}}
            lights = governance.prejudge(snapshot, {"l2_coverage_rate": governance.load_thresholds()["l2_coverage_rate"]})
            self.assertIsNone(lights[0]["current"])
            self.assertEqual(lights[0]["light"], "yellow")

    def test_governance_mapping_is_consumed_and_validated(self):
        registry = governance.load_thresholds()
        self.assertEqual(governance.METRIC_SOURCES,
                         {key: rule["observation"]["source"] for key, rule in registry.items()})
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "thresholds.json"
            for field, invalid in (("bucket", "green"), ("source", "unknown"), ("field", None)):
                broken = copy.deepcopy(registry)
                broken["golden_candidates_pending"]["observation"][field] = invalid
                path.write_text(json.dumps(broken))
                with self.assertRaises(governance.GovernanceError):
                    governance.load_thresholds(path)
        snapshot = {"sources": {"golden_candidates": {"status": "available", "data": {
            "pending_review": 24, "pending": 3, "raw_total": 100}}}}
        rule = registry["golden_candidates_pending"]
        row = governance.prejudge(snapshot, {"golden_candidates_pending": rule})[0]
        self.assertEqual((row["current"], row["light"], row["bucket"]), (24, "red", "knowledge_quality"))
        broken = copy.deepcopy(rule)
        broken["observation"]["field"] = "typo"
        with self.assertRaises(governance.GovernanceError):
            governance.metric_values(snapshot, {"golden_candidates_pending": broken})

    def test_golden_parser_rejects_malformed_rows_without_turning_missing_into_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "golden-candidates.jsonl"
            for content in ('{"id":"x"}\nnot-json\n', '[]\n',
                            '{"id":"x","schema":"sulde-golden-candidate-v2","stage":"pending_review","extra":1}\n'):
                path.write_text(content)
                self.assertEqual(governance.source(lambda: governance.collect_golden_candidates(path))["status"], "unavailable")


    def test_existing_threshold_values_match_git_head(self) -> None:
        head = json.loads(
            subprocess.run(
                ["git", "show", "HEAD:scripts/kb/thresholds.json"],
                cwd=SCRIPT.parents[2],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            ).stdout
        )
        current = json.loads(governance.THRESHOLDS_PATH.read_text(encoding="utf-8"))
        self.assertEqual({key: value["value"] for key, value in head.items()}, {key: current[key]["value"] for key in head})


if __name__ == "__main__":
    unittest.main()
