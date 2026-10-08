"""Bounded retrospective producer/maintenance tests; no production homes."""
from __future__ import annotations

from collections import Counter
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest import mock
import contextlib
import io

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/kb"))


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts/kb" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExperiencePrivacyTests(unittest.TestCase):
    def test_future_verified_experience_never_drives_strategy(self):
        module = load("agent-experience")
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            row = module.build_record(task_id="task", run_id="run", project_id="project",
                session_id="session", task_instance_id="instance", problem_type="test_selection",
                symptom="fixture", handling="bounded check", outcome="verified", result="passed",
                source_summary="fixture", occurred_at="2026-10-05T00:00:00Z",
                recommended_tests=["tests.test_agent_experience"])
            module.record(home, row)
            module.record(home, {**row, "experience_id": "b" * 64, "outcome": "unresolved"})
            for ttl in (30 * 86400, None):
                with self.subTest(ttl=ttl):
                    result = module.recall(home, problem_type="test_selection", symptom="fixture",
                        now="2026-10-04T00:00:00+00:00", ttl_seconds=ttl)
                    self.assertEqual(result["strategy"]["source"], "default")
                    self.assertEqual(result["future_verified_excluded"], 1)
                    self.assertEqual(result["unresolved_retained"], 1)

    def test_recall_requires_nonnegative_integer_ttl_and_aware_reference(self):
        module = load("agent-experience")
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            for ttl in (-1, True, 1.5, "30"):
                with self.subTest(ttl=ttl), self.assertRaises(module.ExperienceError):
                    module.recall(home, problem_type="fixture", symptom="fixture", ttl_seconds=ttl)
            for now in ("2026-10-04T00:00:00", "", "not-a-time"):
                with self.subTest(now=now), self.assertRaises(module.ExperienceError):
                    module.recall(home, problem_type="fixture", symptom="fixture", ttl_seconds=30, now=now)
            self.assertEqual(module.recall(home, problem_type="fixture", symptom="fixture",
                ttl_seconds=0, now="2026-10-04T00:00:00Z")["strategy"]["source"], "default")

    def test_optional_fields_cannot_bypass_redaction_on_direct_record(self):
        module = load("agent-experience")
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            row = module.build_record(task_id="task", run_id="run", project_id="project",
                session_id="session", task_instance_id="instance", problem_type="none",
                symptom="no issue observed", handling="none required", outcome="inconclusive",
                result="observed only", source_summary="fixture", occurred_at="2026-10-04T00:00:00Z")
            module.record(home, row)
            for field in ("recommended_tests", "affected_components"):
                for injected in (["password:fixture_secret"], ["/Users/private/customer"], "not-a-list", ["x" * 161]):
                    with self.subTest(field=field, injected=injected):
                        with self.assertRaises(module.ExperienceError):
                            module.record(home, {**row, field: injected, "experience_id":
                                hashlib.sha256(json.dumps([field, injected]).encode()).hexdigest()})


class RunRetrospectiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.module = load("experience_maintenance")
        self.experience = self.module.component("agent-experience")

    def arguments(self, **changes):
        return {"task_id": "task/private-customer", "run_id": "run-one",
                "project_id": "/Users/private/project", "session_id": "secret:session",
                "task_instance_id": "instance-one", "occurred_at": "2026-09-01T00:00:00Z",
                "status": "success", "returncode": 0, "stop_reason": "completed",
                "report_passed": True, "quiescent": True, "findings_count": 0,
                "open_effects": 0, "evidence_sha256": {"terminal": "a" * 64}, **changes}

    def enqueue(self, **changes):
        return self.module.record_run_retrospective(self.home, **self.arguments(**changes))

    def maintain(self, **changes):
        return self.module.maintenance(self.home, apply=True, now="2026-09-01T01:00:00Z", **changes)

    def test_actual_inbox_merge_daily_weekly_and_report(self):
        queued = self.enqueue()
        self.assertEqual(queued["status"], "queued")
        self.assertFalse((self.home / "experience/agent.jsonl").exists())
        self.assertEqual(self.enqueue()["status"], "duplicate")
        self.assertEqual(self.enqueue(run_id="run-failure", status="failed", report_passed=False)["status"], "queued")
        result = self.maintain()
        self.assertEqual(result["status"], "ready", result)
        self.assertEqual(result["merged"], 2)
        rows = self.experience["load_records"](self.home)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["outcome"] for row in rows}, {"inconclusive", "unresolved"})
        self.assertEqual(result["retrospectives"]["daily"][0]["count"], 1)
        self.assertEqual(len(result["retrospectives"]["weekly_candidates"]), 1)
        governance = load("governance-report")
        rendered = governance.retrospective_section({"sources": {"agent_retrospectives": {
            "status": "available", "data": result["retrospectives"]}}})
        self.assertIn("managed_run_failed", rendered)
        self.assertIn("最终一致", rendered)
        serialized = json.dumps(rows) + rendered + json.dumps(result)
        for raw in ("private-customer", "/Users/private", "secret:session"):
            self.assertNotIn(raw, serialized)
        self.assertFalse(self.experience["sedimentation_candidates"](self.home)["candidates"])

    def test_status_matrix_and_provider_zero_never_becomes_verified(self):
        cases = [("success", True, True, 0, "inconclusive"),
                 ("success", False, True, 0, "unresolved"),
                 ("success", True, False, 0, "unresolved"),
                 ("success", True, True, 1, "unresolved"),
                 ("failed", False, True, 0, "unresolved"),
                 ("timeout", False, True, 0, "unresolved"),
                 ("paused", True, True, 0, "unresolved"),
                 ("awaiting_human", True, True, 1, "unresolved")]
        for index, (status, report, quiescent, effects, outcome) in enumerate(cases):
            self.enqueue(run_id=f"run-{index}", status=status, report_passed=report,
                         quiescent=quiescent, open_effects=effects)
        result = self.maintain()
        self.assertEqual(result["merged"], len(cases), result)
        self.assertEqual(Counter(row["outcome"] for row in self.experience["load_records"](self.home)),
                         {"inconclusive": 1, "unresolved": 7})

    def test_hot_path_does_not_read_canonical_history(self):
        with mock.patch.dict(self.experience["record_many"].__globals__, {"load_records": mock.Mock(side_effect=AssertionError("history scan"))}):
            self.assertEqual(self.enqueue()["status"], "queued")
            self.assertEqual(self.enqueue()["status"], "duplicate")

    def test_contradictory_stop_reason_is_not_a_no_issue_observation(self):
        self.enqueue(stop_reason="timeout")
        self.maintain()
        row = self.experience["load_records"](self.home)[0]
        self.assertEqual(row["outcome"], "unresolved")
        self.assertNotEqual(row["problem_type"], "managed_run_no_issue")

    def test_replay_after_merge_is_idempotent_and_changed_terminal_fact_conflicts(self):
        self.enqueue()
        self.maintain()
        before = (self.home / "experience/agent.jsonl").read_bytes()
        self.enqueue()
        self.assertEqual(self.maintain()["merged"], 1)
        self.assertEqual((self.home / "experience/agent.jsonl").read_bytes(), before)
        self.enqueue(occurred_at="2026-09-01T00:00:01Z")
        self.assertEqual(self.maintain()["status"], "degraded")
        self.assertEqual((self.home / "experience/agent.jsonl").read_bytes(), before)
        self.assertEqual(len(list((self.home / "experience/inbox").glob("*.json"))), 1)

    def test_no_run_missing_time_and_write_failure_are_visible_not_raised(self):
        self.assertEqual(self.enqueue(run_id=None)["status"], "non_run")
        self.assertEqual(self.enqueue(occurred_at=None)["status"], "degraded")
        self.assertFalse((self.home / "experience").exists())
        with mock.patch.object(self.module, "write_object", side_effect=OSError("password:fixture_secret")):
            result = self.enqueue()
        self.assertEqual(result["status"], "degraded")
        self.assertFalse(result["task_status_changed"])
        self.assertNotIn("fixture_secret", json.dumps(result))

    def test_merge_readback_failure_never_acknowledges_transport(self):
        self.enqueue()
        with mock.patch.dict(self.experience["record_many"].__globals__, {"_atomic_records": lambda *_: None}):
            result = self.maintain()
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["merged"], 0)
        self.assertEqual(len(list((self.home / "experience/inbox").glob("*.json"))), 1)
        self.assertEqual(self.maintain()["merged"], 1)

    def test_canonical_directory_fsync_failure_retains_replayable_transport(self):
        import os
        import stat
        self.enqueue()
        original = os.fsync
        def fail_directory(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError("fixture canonical directory fsync EIO")
            return original(descriptor)
        with mock.patch.object(os, "fsync", side_effect=fail_directory):
            result = self.maintain()
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["merged"], 0)
        self.assertEqual(len(self.experience["load_records"](self.home)), 1)
        self.assertEqual(len(list((self.home / "experience/inbox").glob("*.json"))), 1)
        self.assertEqual(self.maintain()["merged"], 1)
        self.assertEqual(len(self.experience["load_records"](self.home)), 1)

    def test_crash_after_merge_before_transport_ack_replays_without_duplicate(self):
        self.enqueue()
        original = Path.unlink
        def fail_ack(path, *args, **kwargs):
            if path.parent.name == "inbox" and path.suffix == ".json":
                raise OSError("fixture failed transport acknowledgement")
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, "unlink", fail_ack):
            self.assertEqual(self.maintain()["status"], "degraded")
        self.assertEqual(len(self.experience["load_records"](self.home)), 1)
        self.assertEqual(self.maintain()["merged"], 1)
        self.assertEqual(len(self.experience["load_records"](self.home)), 1)

    def test_unknown_or_private_input_and_symlink_store_are_rejected(self):
        for change in ({"stop_reason": "password:fixture_secret"}, {"evidence_sha256": {"secret": "a"*64}},
                       {"status": "verified"}, {"quiescent": 1}, {"findings_count": -1},
                       {"occurred_at": "2099-01-01T00:00:00Z"}, {"occurred_at": "2026-09-01T00:00:00"}):
            self.assertEqual(self.enqueue(**change)["status"], "degraded")
        self.assertFalse((self.home / "experience").exists())
        outside = self.home / "not-experience"
        outside.mkdir()
        (self.home / "experience").symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.enqueue()["status"], "degraded")
        self.assertEqual(list(outside.iterdir()), [])

    def test_real_fresh_process_entry_then_existing_experience_cli(self):
        code = "import json,sys; from pathlib import Path; from experience_maintenance import record_run_retrospective, maintenance; args=json.load(sys.stdin); print(json.dumps(record_run_retrospective(Path(sys.argv[1]),**args))); print(json.dumps(maintenance(Path(sys.argv[1]),apply=True,now='2026-09-01T01:00:00Z')))"
        result = subprocess.run([sys.executable, "-B", "-c", code, str(self.home)],
            cwd=ROOT / "scripts/kb", input=json.dumps(self.arguments()), text=True,
            capture_output=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([json.loads(line)["status"] for line in result.stdout.splitlines()], ["queued", "ready"])
        readback = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/kb/agent-experience.py"),
            "list", "--home", str(self.home)], text=True, capture_output=True,
            encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(readback.returncode, 0, readback.stderr)
        rows = json.loads(readback.stdout)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "inconclusive")

    def test_existing_weekly_entry_persists_real_projection_when_llm_fails(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        self.enqueue(run_id="weekly-failure", status="failed", occurred_at=now, report_passed=False)
        self.module.maintenance(self.home, apply=True, now=now)
        governance = load("governance-report")
        original = governance.collectors
        def collectors(home, at, **kwargs):
            return {"agent_retrospectives": original(home, at, **kwargs)["agent_retrospectives"]}
        with (mock.patch.object(sys, "argv", ["governance-report.py"]),
              mock.patch.object(governance, "kb_home", return_value=self.home),
              mock.patch.object(governance, "collectors", side_effect=collectors),
              mock.patch.object(governance, "load_thresholds", return_value={}),
              mock.patch.object(governance, "prepare_lights", return_value=[]),
              mock.patch.object(governance, "build_prompt", return_value="fixture"),
              mock.patch.object(governance, "run_llm", side_effect=governance.LLMCommandError("offline fixture")),
              mock.patch.object(governance, "fallback_report", return_value="Weekly report\n"),
              mock.patch.object(governance, "persist_governance_state"),
              mock.patch.object(governance, "notify"),
              contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())):
            self.assertEqual(governance.main(), 0)
        report = next((self.home / "governance").glob("report-*.md")).read_text(encoding="utf-8")
        self.assertIn("managed_run_failed", report)
        self.assertIn("pending_independent_review", report)
        self.assertIn('"execution_authorized": false', report)

    def test_dry_run_reads_without_creating_or_changing_files(self):
        result = self.module.maintenance(self.home, now="2026-09-01T01:00:00Z")
        self.assertEqual(result["status"], "dry_run", result)
        self.assertEqual(list(self.home.iterdir()), [])
        self.enqueue()
        before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in self.home.rglob("*") if path.is_file()}
        self.module.maintenance(self.home, now="2026-09-01T01:00:00Z")
        after = {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in self.home.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_bounded_merge_progress_and_corrupt_inbox_fairness(self):
        for index in range(3):
            self.enqueue(run_id=f"run-{index}")
        first = sorted((self.home / "experience/inbox").glob("*.json"))[0]
        first.write_text("{broken", encoding="utf-8")
        import os
        os.utime(first, (1, 1))
        self.assertEqual(self.maintain(max_batch=1)["merged"], 0)
        self.assertEqual(self.maintain(max_batch=1)["merged"], 1)
        self.assertEqual(self.maintain(max_batch=1)["merged"], 1)
        self.assertTrue(first.exists())
        self.assertEqual(len(self.experience["load_records"](self.home)), 2)
        self.enqueue(run_id="another")
        limited = self.maintain(max_entries=1)
        self.assertFalse(limited["discovery_complete"])
        self.assertEqual(limited["status"], "degraded")

    def test_corrupt_canonical_store_retains_inbox_and_fails_report_source(self):
        self.enqueue()
        target = self.home / "experience/agent.jsonl"
        target.write_text('{"corrupt":true}\n', encoding="utf-8")
        result = self.maintain()
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(len(list((self.home / "experience/inbox").glob("*.json"))), 1)
        self.assertEqual(target.read_text(encoding="utf-8"), '{"corrupt":true}\n')

    def test_real_produced_detail_ttl_quarantine_preserves_authority_and_unresolved(self):
        good = self.enqueue()
        bad = self.enqueue(run_id="unresolved", status="failed", report_passed=False)
        result = self.maintain()
        self.assertEqual(result["status"], "ready", result)
        details = self.home / "experience/derived-details"
        detail_path = next(details.glob("*.detail.json"))
        detail_bytes = detail_path.read_bytes()
        self.assertIn(good["experience_id"], detail_bytes.decode())
        self.assertNotIn(bad["experience_id"], detail_bytes.decode())
        authority = (self.home / "experience/agent.jsonl").read_bytes()
        result = self.module.maintenance(self.home, apply=True, now="2026-10-02T01:00:00Z")
        self.assertEqual(result["retention"]["status"], "verified", result)
        self.assertEqual(result["retention"]["files_checked"], 2)
        self.assertFalse(result["retention"]["deletion_performed"])
        self.assertFalse(detail_path.exists())
        self.assertEqual(next(details.glob(".quarantine/*/*.detail.json")).read_bytes(), detail_bytes)
        self.assertEqual((self.home / "experience/agent.jsonl").read_bytes(), authority)
        self.assertTrue((self.home / "experience/review.json").exists())

    def test_self_repair_retrospective_failure_does_not_change_business_status(self):
        module = load("self-repair")
        row = {"status": "executed", "slug": "fixture"}
        errors = io.StringIO()
        with mock.patch.object(module, "_record_agent_experience", side_effect=ValueError("password:fixture_secret")), contextlib.redirect_stderr(errors):
            module.record_agent_experience(self.home, row, outcome="verified")
        self.assertEqual(row["status"], "executed")
        self.assertIn("degraded", errors.getvalue())
        self.assertNotIn("fixture_secret", errors.getvalue())
        with mock.patch.object(module, "_record_agent_experience", side_effect=ValueError("private")), mock.patch.object(module, "print", side_effect=BrokenPipeError()):
            module.record_agent_experience(self.home, row, outcome="verified")
        self.assertEqual(row["status"], "executed")


if __name__ == "__main__":
    unittest.main()
