from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/kb/guardian_policy_review.py"


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class GuardianPolicyReviewTests(unittest.TestCase):
    def setUp(self):
        self.module = load(SCRIPT)
        self.experience = load(ROOT / "scripts/kb/agent-experience.py")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def feedback(self, **overrides):
        args = dict(rule_id="guardian.control", rule_version="3", reason_code="human_required",
                    scope_digest=digest("private-target"), event_digest=digest("event-one"),
                    occurred_at="2026-10-04T08:00:00Z")
        args.update(overrides)
        return self.module.build_feedback(**args)

    def evidence(self, expected="allow", **overrides):
        args = dict(kind="regression_test", outcome="passed", expected_decision=expected,
                    observed_decision="deny", source_sha256=digest("test-output"),
                    fingerprint=self.feedback()["policy_dispute"]["fingerprint"])
        args.update(overrides)
        return args

    def test_normal_feedback_is_persisted_in_existing_experience_store(self):
        row = self.feedback()
        self.module.record_feedback(self.home, row)
        self.module.record_feedback(self.home, row)
        records = self.experience.load_records(self.home)
        self.assertEqual(records, [row])
        self.assertEqual(row["outcome"], "inconclusive")
        self.assertEqual(row["policy_dispute"]["disposition"], "unconfirmed")

    def test_classification_requires_bound_evidence_not_denial_or_claim(self):
        for expected, classification in (("allow", "false_denial"), ("deny", "valid_protection")):
            row = self.feedback(assessment=self.evidence(expected))
            self.assertEqual(row["policy_dispute"]["disposition"], classification)
            self.assertEqual(row["outcome"], "inconclusive")
        for evidence in (None, self.evidence(outcome="unknown"),
                         self.evidence(fingerprint=digest("other-rule")),
                         self.evidence(observed_decision="unknown")):
            self.assertEqual(self.feedback(assessment=evidence)["policy_dispute"]["disposition"], "unconfirmed")

    def test_stable_fingerprint_covers_rule_version_scope_reason(self):
        original = self.feedback()["policy_dispute"]["fingerprint"]
        self.assertEqual(original, self.feedback(event_digest=digest("different"))["policy_dispute"]["fingerprint"])
        for field, value in (("rule_id", "guardian.other"), ("rule_version", "4"),
                             ("scope_digest", digest("other")), ("reason_code", "effect_unknown")):
            self.assertNotEqual(original, self.feedback(**{field: value})["policy_dispute"]["fingerprint"])

    def test_unknown_never_becomes_verified_or_execution_authority(self):
        row = self.feedback(assessment=self.evidence())
        for mutation in ({"outcome": "verified"}, {"policy_dispute": {**row["policy_dispute"], "allow": True}},
                         {"policy_dispute": {**row["policy_dispute"], "disposition": "valid_protection"}}):
            with self.assertRaises(ValueError):
                self.experience.record(self.home, {**row, **mutation})
        self.module.record_feedback(self.home, row)
        recalled = self.experience.recall(self.home, problem_type="guardian_policy_dispute", symptom="denial")
        self.assertEqual(recalled["strategy"]["source"], "default")
        self.assertEqual(self.experience.sedimentation_candidates(self.home)["candidates"], [])
        stripped = {key: value for key, value in row.items() if key != "policy_dispute"}
        stripped["outcome"] = "verified"
        with self.assertRaises(ValueError):
            self.experience.record(self.home, stripped)

    def test_daily_dedup_weekly_recurrence_and_conflicting_evidence(self):
        rows = [self.feedback(), self.feedback(assessment=self.evidence()),
                self.feedback(event_digest=digest("event-two"), occurred_at="2026-10-03T08:00:00Z"),
                self.feedback(event_digest=digest("old"), occurred_at="2026-09-01T08:00:00Z"),
                self.feedback(event_digest=digest("future"), occurred_at="2026-10-05T08:00:00Z")]
        for row in rows:
            self.module.record_feedback(self.home, row)
        result = self.module.project(self.home, now="2026-10-04T12:00:00Z")
        candidate = result["weekly_candidates"][0]
        self.assertEqual(candidate["recurrence"], 2)
        self.assertEqual(candidate["disposition"], "false_denial")
        self.assertEqual(candidate["source_evidence_sha256"], [digest("test-output")])
        self.assertEqual([day["recurrence"] for day in result["daily"]], [1, 1])
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["production_policy_changed"])
        self.module.record_feedback(self.home, self.feedback(assessment=self.evidence("deny")))
        conflict = self.module.project(self.home, now="2026-10-04T12:00:00Z")["weekly_candidates"][0]
        self.assertEqual(conflict["disposition"], "unconfirmed")
        self.assertTrue(conflict["conflicting_evidence"])

    def test_privacy_and_unrecognized_fields_rejected(self):
        private = "ssh user@secret-host 'password=secret /private/customer'"
        for args in ({"rule_id": private}, {"reason_code": private}, {"scope_digest": private},
                     {"assessment": {**self.evidence(), "raw_command": private}}):
            with self.assertRaises(ValueError):
                self.feedback(**args)
        row = self.feedback(scope_digest=digest(private), event_digest=digest(private), assessment=self.evidence())
        self.assertNotIn(private, json.dumps(row))
        self.assertNotIn("private-target", json.dumps(row))
        for field in ("symptom", "handling", "result", "source_summary", "recommended_tests"):
            poisoned = {**row, field: [private] if field == "recommended_tests" else private}
            with self.assertRaises(ValueError):
                self.module.record_feedback(self.home, poisoned)

    def test_replayed_event_on_next_day_does_not_create_a_new_occurrence(self):
        self.module.record_feedback(self.home, self.feedback(occurred_at="2026-10-03T08:00:00Z"))
        self.module.record_feedback(self.home, self.feedback(assessment=self.evidence()))
        result = self.module.project(self.home, now="2026-10-04T12:00:00Z")
        self.assertEqual(len(result["daily"]), 1)
        self.assertEqual(result["daily"][0]["day"], "2026-10-03")
        self.assertEqual(result["weekly_candidates"][0]["recurrence"], 1)

    def test_unknown_and_repeated_denials_remain_unconfirmed(self):
        for index in range(12):
            self.module.record_feedback(self.home, self.feedback(event_digest=digest(str(index))))
        result = self.module.project(self.home, now="2026-10-04T12:00:00Z")
        self.assertEqual(result["weekly_candidates"][0]["recurrence"], 12)
        self.assertEqual(result["weekly_candidates"][0]["disposition"], "unconfirmed")
        self.assertEqual(result["weekly_candidates"][0]["suggested_disposition"], "collect_evidence")

    def test_actual_cli_ingests_and_reviews_without_policy_mutation(self):
        payload = self.home / "feedback.json"
        payload.write_text(json.dumps(self.feedback()), encoding="utf-8")
        for action in ("record", "project"):
            command = [sys.executable, "-B", str(SCRIPT), action, "--home", str(self.home)]
            command += ["--input", str(payload)] if action == "record" else ["--now", "2026-10-04T12:00:00Z"]
            result = subprocess.run(command, text=True, capture_output=True,
                                    encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(json.loads(result.stdout)["execution_authorized"])
        self.assertEqual(sorted(str(path.relative_to(self.home)) for path in self.home.rglob("*") if path.is_file()),
                         ["experience/agent.jsonl", "experience/agent.lock", "feedback.json"])

    def test_governance_existing_consumer_reads_projection_and_keeps_failure_visible(self):
        governance = load(ROOT / "scripts/kb/governance-report.py")
        self.module.record_feedback(self.home, self.feedback())
        from datetime import datetime, timezone
        collector = governance.collectors(self.home, datetime(2026, 10, 4, 12, tzinfo=timezone.utc))["guardian_policy_review"]
        source = governance.source(collector)
        self.assertEqual(source["status"], "available")
        self.assertEqual(source["data"]["weekly_candidates"][0]["disposition"], "unconfirmed")
        text = governance.policy_review_section({"sources": {"guardian_policy_review": source}})
        self.assertIn("unconfirmed", text)
        self.assertIn("不授予执行权限", text)
        (self.home / "experience/agent.jsonl").write_text('{"broken":true}\n')
        broken = governance.source(collector)
        self.assertEqual(broken["status"], "unavailable")
        self.assertIn("unavailable", governance.policy_review_section({"sources": {"guardian_policy_review": broken}}))

    def test_existing_weekly_report_persists_candidates_when_optional_model_fails(self):
        governance = load(ROOT / "scripts/kb/governance-report.py")
        self.produce_denial()
        original_collectors = governance.collectors
        def isolated_collectors(home, now, **kwargs):
            return {"guardian_policy_review": original_collectors(home, now, **kwargs)["guardian_policy_review"]}
        with (mock.patch.object(sys, "argv", ["governance-report.py"]),
              mock.patch.object(governance, "kb_home", return_value=self.home),
              mock.patch.object(governance, "collectors", side_effect=isolated_collectors),
              mock.patch.object(governance, "load_thresholds", return_value={}),
              mock.patch.object(governance, "prepare_lights", return_value=[]),
              mock.patch.object(governance, "build_prompt", return_value="fixture"),
              mock.patch.object(governance, "run_llm", side_effect=governance.LLMCommandError("offline fixture")),
              mock.patch.object(governance, "fallback_report", return_value="Weekly report\n"),
              mock.patch.object(governance, "persist_governance_state"),
              mock.patch.object(governance, "notify")):
            self.assertEqual(governance.main(), 0)
        reports = list((self.home / "governance").glob("report-*.md"))
        self.assertEqual(len(reports), 1)
        report = reports[0].read_text()
        self.assertIn("unconfirmed", report)
        records = self.experience.load_records(self.home)
        self.assertEqual(len(records), 1)
        self.assertIn(records[0]["policy_dispute"]["fingerprint"], report)
        self.assertIn('"execution_authorized": false', report)
        self.assertIn('"recorded": 1', report)

    def produce_denial(self, call_id="first", workspace_name="project"):
        sys.path.insert(0, str(ROOT / "scripts/kb"))
        from intent_guardian import (GuardianSession, active_contract_path, audit_path,
                                     default_contract, normalize_hook_event, write_contract)
        workspace = self.home / workspace_name
        workspace.mkdir(exist_ok=True)
        contract = default_contract(intent_id="policy-review-producer", objective="Review local draft",
                                    rationale="Keep scope local", acceptance_criteria=["local only"],
                                    workspace=workspace, mode="enforce", allowed_paths=["draft.md"],
                                    confirmed_by="human")
        contract_path = active_contract_path(self.home, workspace)
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(self.home)}):
            if not contract_path.exists():
                write_contract(contract_path, contract)
            event = normalize_hook_event({"tool_name": "mcp__docs__update_document",
                                          "tool_use_id": call_id,
                                          "tool_input": {"uri": "doc://private-customer", "content": "password=never-retain"}},
                                         phase="started", provider="codex")
            decision = GuardianSession(contract_path).observe(event)
        self.assertEqual(decision.dispatch, "deny")
        path = audit_path(contract_path)
        row = json.loads(path.read_text().splitlines()[-1])
        self.assertEqual(row["schema"], "sulde-guardian-event-v1")
        self.assertIn("at", row["event"])
        return path, row

    def test_actual_producer_to_maintenance_to_experience_to_weekly_report(self):
        path, raw = self.produce_denial()
        governance = load(ROOT / "scripts/kb/governance-report.py")
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        before = path.read_bytes()
        data = governance.collectors(self.home, now, ingest_policy_feedback=True)["guardian_policy_review"]()
        self.assertEqual(data["ingestion"]["status"], "ready")
        self.assertEqual(data["ingestion"]["recorded"], 1)
        records = self.experience.load_records(self.home)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["policy_dispute"]["disposition"], "unconfirmed")
        self.assertEqual(records[0]["policy_dispute"]["reason_code"], raw["decision"]["reason_code"])
        report = governance.policy_review_section({"sources": {"guardian_policy_review": {"status": "available", "data": data}}})
        self.assertIn(records[0]["policy_dispute"]["fingerprint"], report)
        for private in ("private-customer", "never-retain", str(self.home)):
            self.assertNotIn(private, json.dumps(records) + report)
        second = governance.collect_policy_review(self.home, now, ingest=True)
        self.assertEqual(second["ingestion"]["recorded"], 0)
        self.assertEqual(len(self.experience.load_records(self.home)), 1)
        self.assertEqual(path.read_bytes(), before)
        self.produce_denial(call_id="second")
        third = governance.collect_policy_review(self.home, now, ingest=True)
        self.assertEqual(third["ingestion"]["recorded"], 1)
        self.assertEqual(len(self.experience.load_records(self.home)), 2)

    def test_cursor_loss_replay_deduplicates_and_corruption_does_not_advance(self):
        path, _row = self.produce_denial()
        first = self.module.ingest_audits(self.home)
        self.assertEqual(first["recorded"], 1)
        cursor = next((self.home / "governance/policy-review-cursors").glob("*.json"))
        cursor.unlink()
        self.module.ingest_audits(self.home)
        self.assertEqual(len(self.experience.load_records(self.home)), 1)
        checkpoint = cursor.read_bytes()
        with path.open("a") as stream:
            stream.write('{"incomplete":')
        degraded = self.module.ingest_audits(self.home)
        self.assertEqual(degraded["status"], "degraded")
        self.assertEqual(cursor.read_bytes(), checkpoint)
        self.assertEqual(len(self.experience.load_records(self.home)), 1)

    def test_oversized_and_row_caps_report_backlog_without_false_empty_success(self):
        path, _row = self.produce_denial()
        limited = self.module.ingest_audits(self.home, max_source_bytes=32)
        self.assertEqual(limited["status"], "degraded")
        self.assertEqual(limited["recorded"], 0)
        self.assertEqual(limited["diagnostics"][0]["reason"], "source_byte_limit")
        self.assertEqual(list((self.home / "governance/policy-review-cursors").glob("*.json")), [])
        self.assertEqual(len(list((self.home / "governance/policy-review-cursors").glob("*.checked"))), 1)
        self.produce_denial(call_id="second")
        limited = self.module.ingest_audits(self.home, max_rows=1)
        self.assertEqual(limited["status"], "degraded")
        self.assertEqual(limited["diagnostics"][0]["reason"], "row_limit")
        self.assertEqual(self.experience.load_records(self.home), [])

    def test_readonly_collection_never_ingests_and_invalid_code_degrades(self):
        path, row = self.produce_denial()
        governance = load(ROOT / "scripts/kb/governance-report.py")
        from datetime import datetime, timezone
        data = governance.collect_policy_review(self.home, datetime.now(timezone.utc))
        self.assertEqual(data["ingestion"]["status"], "not_requested")
        self.assertEqual(self.experience.load_records(self.home), [])
        row["decision"]["reason_code"] = "curl https://private-host password=never-retain"
        path.write_text(json.dumps(row) + "\n")
        data = governance.collect_policy_review(self.home, datetime.now(timezone.utc), ingest=True)
        self.assertEqual(data["ingestion"]["status"], "degraded")
        self.assertEqual(self.experience.load_records(self.home), [])
        self.assertNotIn("never-retain", json.dumps(data))
        self.assertEqual(list((self.home / "governance/policy-review-cursors").glob("*.json")), [])

    def test_file_cap_rotates_across_two_real_audits_and_empty_checks(self):
        self.produce_denial(workspace_name="project-one")
        self.produce_denial(call_id="second", workspace_name="project-two")
        first = self.module.ingest_audits(self.home, max_files=1)
        second = self.module.ingest_audits(self.home, max_files=1)
        self.assertEqual(first["sources_checked"], 1)
        self.assertEqual(second["sources_checked"], 1)
        self.assertEqual(len(self.experience.load_records(self.home)), 2)
        # Warm empty checks must keep rotating instead of monopolizing a slot.
        self.module.ingest_audits(self.home, max_files=1)
        self.module.ingest_audits(self.home, max_files=1)
        self.produce_denial(call_id="third", workspace_name="project-two")
        for _ in range(2):
            self.module.ingest_audits(self.home, max_files=1)
        self.assertEqual(len(self.experience.load_records(self.home)), 3)

    def test_invalid_source_cannot_monopolize_one_file_budget(self):
        paths = [self.produce_denial(workspace_name="project-one")[0],
                 self.produce_denial(call_id="second", workspace_name="project-two")[0]]
        invalid = sorted(paths)[0]
        invalid.write_text('{"broken":')
        first = self.module.ingest_audits(self.home, max_files=1)
        second = self.module.ingest_audits(self.home, max_files=1)
        self.assertEqual(first["recorded"], 0)
        self.assertEqual(first["status"], "degraded")
        self.assertEqual(second["recorded"], 1)
        self.assertEqual(len(self.experience.load_records(self.home)), 1)

    def test_discovery_limit_exposes_partial_coverage(self):
        self.produce_denial(workspace_name="project-one")
        self.produce_denial(call_id="second", workspace_name="project-two")
        result = self.module.ingest_audits(self.home, max_entries=1)
        self.assertEqual(result["status"], "degraded")
        self.assertFalse(result["discovery_complete"])
        self.assertEqual(result["automatic_coverage"], "partial")
        self.assertLess(result["sources_checked"], 2)
        governance = load(ROOT / "scripts/kb/governance-report.py")
        data = self.module.project(self.home)
        data["ingestion"] = result
        report = governance.policy_review_section({"sources": {"guardian_policy_review": {"status": "available", "data": data}}})
        self.assertIn("目录发现未完成（discovery_complete=false）", report)
        self.assertIn("不宣称全量覆盖", report)

    def test_oversized_source_cannot_monopolize_one_file_budget(self):
        paths = [self.produce_denial(workspace_name="project-one")[0],
                 self.produce_denial(call_id="second", workspace_name="project-two")[0]]
        oversized = sorted(paths)[0]
        row = json.loads(oversized.read_text())
        row["fixture_padding"] = "x" * 10000
        oversized.write_text(json.dumps(row) + "\n")
        first = self.module.ingest_audits(self.home, max_files=1, max_source_bytes=4096)
        second = self.module.ingest_audits(self.home, max_files=1, max_source_bytes=4096)
        self.assertEqual(first["recorded"], 0)
        self.assertIn("source_byte_limit", {item["reason"] for item in first["diagnostics"]})
        self.assertEqual(second["recorded"], 1)
        self.assertEqual(len(self.experience.load_records(self.home)), 1)
        self.assertEqual(len(list((self.home / "governance/policy-review-cursors").glob("*.json"))), 1)

    def test_manual_cleartext_labels_cannot_leak_credentials_through_any_consumer(self):
        from datetime import datetime, timezone
        governance = load(ROOT / "scripts/kb/governance-report.py")
        private = "password:fixture_secret"
        for field in ("rule_id", "rule_version", "reason_code"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.feedback(**{field: private})
                forged = self.feedback()
                forged["policy_dispute"][field] = private
                forged["policy_dispute"]["fingerprint"] = self.module.fingerprint(forged["policy_dispute"])
                with self.assertRaises(ValueError):
                    self.module.record_feedback(self.home, forged)
                input_path = self.home / "forged.json"
                input_path.write_text(json.dumps(forged))
                result = subprocess.run([sys.executable, "-B", str(SCRIPT), "record", "--home", str(self.home), "--input", str(input_path)], text=True, capture_output=True,
                                        encoding="utf-8", errors="replace")
                self.assertEqual(result.returncode, 2)
                self.assertNotIn(private, result.stdout + result.stderr)
                # Inject a historical malformed record to test read-side boundaries.
                store = self.home / "experience/agent.jsonl"
                store.parent.mkdir(exist_ok=True)
                store.write_text(json.dumps(forged) + "\n")
                with self.assertRaises(ValueError):
                    self.module.project(self.home)
                source = governance.source(lambda: governance.collect_policy_review(self.home, datetime.now(timezone.utc)))
                self.assertEqual(source["status"], "unavailable")
                report = governance.policy_review_section({"sources": {"guardian_policy_review": source}})
                self.assertNotIn(private, json.dumps(source) + report)
                self.assertIn("unavailable", report)


if __name__ == "__main__":
    unittest.main()
