"""R1-04: the production prediction-feedback consumer."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

import correction_intervention as ci  # noqa: E402
import impact_prediction as ip  # noqa: E402
import prediction_feedback as pf  # noqa: E402

NOW = "2026-09-27T14:00:00+00:00"
TASK = "task/predictive-execution"
RUN = "run-aaaaaaaaaaaaaaaaaaaaaaaa"
SESSION = "session-9"
INTENT = "intent:demo"
REVISION = 3


class PredictionFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state"
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        (self.repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        for args in (["init", "-q"],
                     ["add", "a.py"],
                     ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "base"],
                     ["tag", "baseline"]):
            subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, check=True)
        self.contract = Path(self.tmp.name) / "intent.json"
        self.contract.write_text("{}", encoding="utf-8")
        self.store = pf.prediction_store_path(self.state)

    def tearDown(self):
        self.tmp.cleanup()

    def _open(self, *, expected=None, run_id=RUN):
        return ip.open_prediction(self.store, {
            "kind": "lightweight",
            "task_id": TASK, "run_id": run_id, "session_id": SESSION,
            "project_id": "/repo", "contract_version": "r1-behavior",
            "source_identities": {},
            "objective": "change a.py",
            "assumptions": [{"text": "only a.py", "confidence": "high"}],
            "expected_touch": {"entries": expected or []},
            "impact_bounds": {"lower": "l", "upper": "u", "unknown": "?"},
        }, at=NOW, task_id=TASK)

    def _feedback(self, *, baseline="baseline", contract_version="r1-behavior",
                  session_id=SESSION):
        return pf.record_completion_feedback(
            state_dir=self.state, repo=self.repo, task_id=TASK, run_id=RUN,
            session_id=session_id, provider="codex", intent_id=INTENT,
            intent_revision=REVISION, contract_version=contract_version,
            baseline_revision=baseline,
        )

    def _ledger_rows(self):
        return [json.loads(line)
                for line in self.contract.with_name("intent.corrections.jsonl")
                .read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_missing_store_is_a_clean_skip(self):
        disclosure = self._feedback()
        self.assertEqual(disclosure["status"], "skipped")

    def test_no_thread_for_task_is_a_skip(self):
        self.store.parent.mkdir(parents=True)
        self.store.write_text("", encoding="utf-8")
        self.assertEqual(self._feedback()["status"], "skipped")

    def test_cross_run_prediction_is_rejected(self):
        self._open(expected=["a.py"], run_id="run-bbbbbbbbbbbbbbbbbbbb")
        disclosure = self._feedback()
        self.assertEqual(disclosure["status"], "rejected")
        self.assertIn("another run", disclosure["reason"])

    def test_as_predicted_records_check_without_correction(self):
        self._open(expected=["a.py"])
        (self.repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        disclosure = self._feedback()
        self.assertEqual(disclosure["status"], "checked")
        self.assertEqual(disclosure["verdict"], "as_predicted")
        artifact = self.state / f"prediction-feedback-{ip.digest(TASK)}.json"
        self.assertFalse(artifact.exists())  # as_predicted: no feedback artifact
        entry = ip.load_projection(self.store)["tasks"][ip.digest(TASK)]
        self.assertEqual(len(entry["checks"]), 1)

    def test_larger_verdict_writes_feedback_artifact_once(self):
        self._open(expected=["a.py"])
        (self.repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        (self.repo / "surprise.py").write_text("y = 2\n", encoding="utf-8")
        disclosure = self._feedback()
        self.assertEqual(disclosure["verdict"], "larger_than_predicted")
        self.assertIn("feedback_artifact", disclosure)
        artifact_path = Path(disclosure["feedback_artifact"])
        first = json.loads(artifact_path.read_text(encoding="utf-8"))
        again = self._feedback()
        self.assertTrue(again["feedback"]["deduplicated"])
        # the artifact is unchanged by the deduplicated replay
        self.assertEqual(first, json.loads(artifact_path.read_text(encoding="utf-8")))

    def test_stale_thread_is_skipped_not_revived(self):
        self._open(expected=["a.py"])
        ip.mark_stale(self.store, task_id=TASK, input_changed={"a.py": "f" * 16}, at=NOW)
        disclosure = self._feedback()
        self.assertEqual(disclosure["status"], "stale_skipped")

    def test_degraded_store_discloses_without_raising(self):
        self.store.parent.mkdir(parents=True)
        self.store.write_text("not json\n", encoding="utf-8")
        disclosure = self._feedback()
        self.assertEqual(disclosure["status"], "degraded")
        self.assertIn("corrupt", disclosure["error"])

    def test_feedback_artifact_binds_run_and_verdict(self):
        self._open(expected=["a.py"])
        (self.repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        (self.repo / "surprise.py").write_text("y = 2\n", encoding="utf-8")
        disclosure = self._feedback()
        artifact = json.loads((self.state / f"prediction-feedback-{ip.digest(TASK)}.json")
                              .read_text(encoding="utf-8"))
        self.assertEqual(artifact["verdict"], "larger_than_predicted")
        self.assertEqual(artifact["run_id_sha256"], ip.digest(RUN))
        self.assertEqual(artifact["run_id_sha256"], ip.digest(RUN))

    def _pending_for_later_run(self):
        self._open(expected=["a.py"])
        (self.repo / "surprise.py").write_text("x = 2\n", encoding="utf-8")
        self._feedback()
        path = self.state / f"prediction-feedback-{ip.digest(TASK)}.json"
        pending = json.loads(path.read_text(encoding="utf-8"))
        # Persist an earlier source request; current run creates a different ID.
        pending["request_id"] = "earlier-request"
        path.write_text(json.dumps(pending), encoding="utf-8")
        return path, path.read_bytes()

    def _registry(self, value):
        path = self.state / "prediction-feedback-consumed.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_unconfirmed_pending_survives_new_observation(self):
        path, before = self._pending_for_later_run()
        reg = self._registry({"consumed": {}, "send_unconfirmed": {"earlier-request": {}}, "recovered": {}})
        reg_before = reg.read_bytes()
        disclosure = self._feedback()
        self.assertEqual(disclosure["status"], "checked")
        self.assertEqual(disclosure["feedback"]["disposition"], "preserved_send_unconfirmed")
        self.assertEqual(disclosure["feedback"]["request_id"], "earlier-request")
        self.assertNotEqual(disclosure["feedback"]["deferred_request_id"], "earlier-request")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(reg.read_bytes(), reg_before)
        self.assertEqual(len(ip.load_projection(self.store)["tasks"][ip.digest(TASK)]["checks"]), 2)

    def test_other_request_uncertainty_does_not_block_producer(self):
        path, before = self._pending_for_later_run()
        self._registry({"send_unconfirmed": {"other-request": {}}, "consumed": {}})
        self.assertEqual(self._feedback()["status"], "checked")
        self.assertNotEqual(path.read_bytes(), before)

    def test_different_task_feedback_is_not_globally_blocked(self):
        path, before = self._pending_for_later_run()
        other = self.state / f"prediction-feedback-{ip.digest('other-task')}.json"
        other.write_bytes(before)
        self._registry({"send_unconfirmed": {"unrelated-request": {}}, "consumed": {}})
        self.assertEqual(self._feedback()["status"], "checked")
        self.assertEqual(other.read_bytes(), before)
        self.assertNotEqual(path.read_bytes(), before)

    def test_recovered_request_does_not_stick_producer(self):
        path, before = self._pending_for_later_run()
        self._registry({"send_unconfirmed": {"earlier-request": {}},
                        "recovered": {"earlier-request": {}}, "consumed": {}})
        self.assertEqual(self._feedback()["status"], "checked")
        self.assertNotEqual(path.read_bytes(), before)

    def test_new_prediction_keeps_uncertain_history_but_cannot_consume_it(self):
        path, before = self._pending_for_later_run()
        self._registry({"send_unconfirmed": {"earlier-request": {}}, "consumed": {}})
        ip.revise_prediction(self.store, {"new_evidence": ["new scope"], "revision_reason": "revise"},
                             at=NOW, task_id=TASK)
        self.assertEqual(self._feedback()["feedback"]["disposition"], "preserved_send_unconfirmed")
        self.assertEqual(path.read_bytes(), before)
        pf.mark_feedback_recovered(state_dir=self.state, task_id=TASK,
                                   request_id="earlier-request", decision="retry", at=NOW)
        value, reason = pf.load_pending_feedback(state_dir=self.state, task_id=TASK,
                                                 contract_version="r1-behavior")
        self.assertIsNone(value)
        self.assertIn("predates", reason)

    def test_invalid_registry_keeps_pending_without_raising(self):
        path, before = self._pending_for_later_run()
        for malformed in ([], {"send_unconfirmed": []}, {"recovered": None}, {"consumed": []}):
            with self.subTest(malformed=malformed):
                self._registry(malformed)
                self.assertEqual(self._feedback()["status"], "degraded")
                self.assertEqual(path.read_bytes(), before)
        reg = self.state / "prediction-feedback-consumed.json"
        reg.write_text("{", encoding="utf-8")
        self.assertEqual(self._feedback()["status"], "degraded")
        self.assertEqual(path.read_bytes(), before)

    def test_invalid_pending_identity_is_not_overwritten(self):
        path, _ = self._pending_for_later_run()
        for malformed in ([], {"task_id_sha256": "wrong"},
                          {"task_id_sha256": ip.digest(TASK), "request_id": []}):
            with self.subTest(malformed=malformed):
                path.write_text(json.dumps(malformed), encoding="utf-8")
                before = path.read_bytes()
                self.assertEqual(self._feedback()["status"], "degraded")
                self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()


class IdentityAndFreshnessTests(unittest.TestCase):
    """R2-03: feedback identity, contract freshness and source drift."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state"
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        (self.repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        for args in (["init", "-q"], ["add", "a.py"],
                     ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "base"],
                     ["tag", "baseline"]):
            subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, check=True)
        self.contract = Path(self.tmp.name) / "intent.json"
        self.contract.write_text("{}", encoding="utf-8")
        self.store = pf.prediction_store_path(self.state)

    def tearDown(self):
        self.tmp.cleanup()

    def _open(self, *, run_id=RUN, session_id=SESSION, contract_version="c1",
              source_identities=None):
        return ip.open_prediction(self.store, {
            "kind": "lightweight", "task_id": TASK, "run_id": run_id,
            "session_id": session_id, "project_id": "/repo",
            "contract_version": contract_version,
            "source_identities": source_identities or {},
            "objective": "o",
            "assumptions": [{"text": "a", "confidence": "low"}],
            "expected_touch": {"entries": ["a.py"]},
            "impact_bounds": {"lower": "l", "upper": "u", "unknown": "?"},
        }, at=NOW, task_id=TASK)

    def _feedback(self, *, run_id=RUN, session_id=SESSION, contract_version="c1",
                  baseline="baseline"):
        return pf.record_completion_feedback(
            state_dir=self.state, repo=self.repo, task_id=TASK, run_id=run_id,
            session_id=session_id, provider="codex", intent_id="i",
            intent_revision=REVISION, contract_version=contract_version,
            baseline_revision=baseline)

    def test_same_run_different_session_is_rejected(self):
        self._open()
        disclosure = self._feedback(session_id="someone-else")
        self.assertEqual(disclosure["status"], "rejected")
        self.assertIn("another session", disclosure["reason"])

    def test_contract_version_change_is_rejected(self):
        self._open(contract_version="c1")
        disclosure = self._feedback(contract_version="c2")
        self.assertEqual(disclosure["status"], "rejected")
        self.assertIn("contract", disclosure["reason"])

    def test_bound_source_drift_marks_stale_without_verdict(self):
        import hashlib
        (self.repo / "b.py").write_text("dependent\n", encoding="utf-8")
        digest = hashlib.sha256((self.repo / "b.py").read_bytes()).hexdigest()[:16]
        self._open(source_identities={"b.py": digest})
        (self.repo / "b.py").write_text("changed\n", encoding="utf-8")
        disclosure = self._feedback()
        self.assertEqual(disclosure["status"], "stale_marked")
        entry = ip.load_projection(self.store)["tasks"][ip.digest(TASK)]
        self.assertEqual(entry["current"]["status"], "stale")
        self.assertEqual(entry["checks"], [])  # no verdict on stale basis

    def test_legitimate_same_identity_feedback_passes(self):
        self._open()
        disclosure = self._feedback()
        self.assertEqual(disclosure["status"], "checked")

    def test_new_attempt_explicit_rebind_without_authority(self):
        self._open(run_id="run-old", session_id="s-old")
        ip.close_prediction  # noqa: B018 - presence check only
        rebind = ip.rebind_attempt(self.store, task_id=TASK,
                                   session_id=SESSION, contract_version="c1",
                                   reason="new attempt started", at=NOW,
                                   run_id=RUN)
        self.assertEqual(rebind["type"], "prediction.rebound")
        disclosure = self._feedback()
        self.assertEqual(disclosure["status"], "checked")
        # the rebind event carries identity only — no grants or authority
        self.assertNotIn("grants", json.dumps(rebind))
        # old run/session may no longer consume the rebound thread
        old = pf.record_completion_feedback(
            state_dir=self.state, repo=self.repo, task_id=TASK, run_id="run-old",
            session_id="s-old", provider="codex", intent_id="i",
            intent_revision=REVISION, contract_version="c1",
            baseline_revision="baseline")
        self.assertEqual(old["status"], "rejected")

    def test_unresolvable_baseline_degrades_without_verdict(self):
        self._open()
        disclosure = self._feedback(baseline="task_epoch-not-a-revision")
        self.assertEqual(disclosure["status"], "degraded")
        self.assertIn("not resolvable", disclosure["error"])
        entry = ip.load_projection(self.store)["tasks"][ip.digest(TASK)]
        self.assertEqual(entry["checks"], [])


if __name__ == "__main__":
    unittest.main()


class ContractVersionTests(unittest.TestCase):
    """R3-01: 缺失版本不得默认跳过校验。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state"
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        (self.repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        for args in (["init", "-q"], ["add", "a.py"],
                     ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "base"],
                     ["tag", "baseline"]):
            subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, check=True)
        self.contract = Path(self.tmp.name) / "intent.json"
        self.contract.write_text("{}", encoding="utf-8")
        self.store = pf.prediction_store_path(self.state)

    def tearDown(self):
        self.tmp.cleanup()

    def _open(self, contract_version):
        return ip.open_prediction(self.store, {
            "kind": "lightweight", "task_id": TASK, "run_id": RUN,
            "session_id": SESSION, "project_id": "/repo",
            "contract_version": contract_version,
            "source_identities": {}, "objective": "o",
            "assumptions": [{"text": "a", "confidence": "low"}],
            "expected_touch": {"entries": ["a.py"]},
            "impact_bounds": {"lower": "l", "upper": "u", "unknown": "?"},
        }, at=NOW, task_id=TASK)

    def _feedback(self, contract_version):
        return pf.record_completion_feedback(
            state_dir=self.state, repo=self.repo, task_id=TASK, run_id=RUN,
            session_id=SESSION, provider="codex", intent_id="i",
            intent_revision=REVISION, contract_version=contract_version,
            baseline_revision="baseline")

    def test_same_version_passes(self):
        self._open("intent-i#7")
        disclosure = self._feedback("intent-i#7")
        self.assertEqual(disclosure["status"], "checked")

    def test_old_version_is_rejected(self):
        self._open("intent-i#7")
        disclosure = self._feedback("intent-i#6")
        self.assertEqual(disclosure["status"], "rejected")

    def test_missing_producer_version_degrades_not_skips(self):
        self._open("intent-i#7")
        disclosure = self._feedback("")
        self.assertEqual(disclosure["status"], "degraded")
        self.assertIn("version", disclosure["error"])
        entry = ip.load_projection(self.store)["tasks"][ip.digest(TASK)]
        self.assertEqual(entry["checks"], [])


class DriftScopeTests(unittest.TestCase):
    """R3-02: 预计范围内的内容变化进入对照;范围外依据漂移才 stale。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state"
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        (self.repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        (self.repo / "basis.py").write_text("base = 1\n", encoding="utf-8")
        for args in (["init", "-q"], ["add", "."],
                     ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "base"],
                     ["tag", "baseline"]):
            subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, check=True)
        self.contract = Path(self.tmp.name) / "intent.json"
        self.contract.write_text("{}", encoding="utf-8")
        self.store = pf.prediction_store_path(self.state)
        import hashlib
        self.digests = {
            "a.py": hashlib.sha256((self.repo / "a.py").read_bytes()).hexdigest()[:16],
            "basis.py": hashlib.sha256((self.repo / "basis.py").read_bytes()).hexdigest()[:16],
        }
        self._open()

    def tearDown(self):
        self.tmp.cleanup()

    def _open(self):
        return ip.open_prediction(self.store, {
            "kind": "lightweight", "task_id": TASK, "run_id": RUN,
            "session_id": SESSION, "project_id": "/repo",
            "contract_version": "c1",
            # 绑定依据:范围内 a.py + 范围外依据 basis.py
            "source_identities": dict(self.digests),
            "objective": "o",
            "assumptions": [{"text": "a", "confidence": "low"}],
            "expected_touch": {"entries": ["a.py"]},
            "impact_bounds": {"lower": "l", "upper": "u", "unknown": "?"},
        }, at=NOW, task_id=TASK)

    def _feedback(self):
        return pf.record_completion_feedback(
            state_dir=self.state, repo=self.repo, task_id=TASK, run_id=RUN,
            session_id=SESSION, provider="codex", intent_id="i",
            intent_revision=REVISION, contract_version="c1",
            baseline_revision="baseline")

    def _checks(self):
        entry = ip.load_projection(self.store)["tasks"][ip.digest(TASK)]
        return entry["checks"], entry["current"]["status"]

    def test_normal_in_scope_change_gets_checked_not_stale(self):
        (self.repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        disclosure = self._feedback()
        self.assertEqual(disclosure["status"], "checked")
        checks, status = self._checks()
        self.assertEqual(len(checks), 1)
        self.assertEqual(status, "open")  # 摘要变化不等于依据失效

    def test_out_of_scope_basis_drift_marks_stale(self):
        (self.repo / "basis.py").write_text("base = 2\n", encoding="utf-8")
        disclosure = self._feedback()
        self.assertEqual(disclosure["status"], "stale_marked")
        checks, status = self._checks()
        self.assertEqual(checks, [])
        self.assertEqual(status, "stale")

    def test_both_in_scope_and_out_of_scope_stale_wins(self):
        (self.repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        (self.repo / "basis.py").write_text("base = 3\n", encoding="utf-8")
        disclosure = self._feedback()
        self.assertEqual(disclosure["status"], "stale_marked")
        checks, status = self._checks()
        self.assertEqual(checks, [])
        self.assertEqual(status, "stale")


class FeedbackConsumptionTests(unittest.TestCase):
    """R3-followup 一: 正式反馈消费的绑定校验。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state"
        self.store = pf.prediction_store_path(self.state)
        self._open("intent-i#7", run_id="run-gen", session_id="s-gen")
        self._write_artifact(request_id="req-feedback-1")

    def tearDown(self):
        self.tmp.cleanup()

    def _open(self, contract_version, run_id, session_id):
        return ip.open_prediction(self.store, {
            "kind": "lightweight", "task_id": TASK, "run_id": run_id,
            "session_id": session_id, "project_id": "/repo",
            "contract_version": contract_version,
            "source_identities": {}, "objective": "o",
            "assumptions": [{"text": "a", "confidence": "low"}],
            "expected_touch": {"entries": ["a.py"]},
            "impact_bounds": {"lower": "l", "upper": "u", "unknown": "?"},
        }, at=NOW, task_id=TASK)

    def _write_artifact(self, request_id, prediction_version=1,
                        task_id=TASK):
        projection = ip.load_projection(self.store)
        entry = projection["tasks"].get(ip.digest(task_id)) or {}
        current = entry.get("current") or {}
        artifact = {
            "schema": "sulde-prediction-feedback-v1",
            "request_id": request_id,
            "task_id_sha256": ip.digest(task_id),
            "run_id_sha256": ip.digest("run-gen"),
            "prediction_id": current.get("prediction_id") or "pred-demo",
            "prediction_version": prediction_version,
            "verdict": "larger_than_predicted",
            "facts": ["fact"],
            "evidence": ["e"],
            "created_at": NOW,
        }
        path = self.state / f"prediction-feedback-{ip.digest(task_id)}.json"
        path.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
        return artifact

    def _consume(self, *, contract_version="intent-i#7", run_id="run-consume",
                 session_id="s-consume"):
        feedback, reason = pf.load_pending_feedback(
            state_dir=self.state, task_id=TASK, contract_version=contract_version)
        if feedback is not None:
            pf.confirm_feedback_consumed(
                state_dir=self.state, task_id=TASK, request_id=feedback["request_id"],
                consuming_run_id=run_id, consuming_session_id=session_id)
        return feedback, reason

    def test_valid_delivery_consumes_and_registers(self):
        feedback, reason = self._consume()
        self.assertIsNotNone(feedback)
        self.assertEqual(reason, "delivered")
        registry = json.loads((self.state / "prediction-feedback-consumed.json")
                              .read_text(encoding="utf-8"))
        self.assertIn("req-feedback-1", registry["consumed"])
        artifact = self.state / f"prediction-feedback-{ip.digest(TASK)}.json"
        self.assertFalse(artifact.exists())  # 已消费,不再重复投递
        feedback2, reason2 = self._consume()
        self.assertIsNone(feedback2)
        self.assertEqual(reason2, "no pending feedback artifact")  # 已消费即不在待投递位

    def test_wrong_task_feedback_not_consumed(self):
        other = self._write_artifact(request_id="req-other", task_id="task/other")
        feedback, reason = self._consume()
        # 消费入口只处理本任务的工件:本任务反馈正常消费,错任务工件原样保留
        self.assertIsNotNone(feedback)
        other_after = self.state / f"prediction-feedback-{ip.digest('task/other')}.json"
        self.assertTrue(other_after.exists())
        self.assertEqual(json.loads(other_after.read_text(encoding="utf-8")), other)
        registry = json.loads((self.state / "prediction-feedback-consumed.json")
                              .read_text(encoding="utf-8"))
        self.assertNotIn("req-other", registry["consumed"])

    def test_feedback_predating_revision_not_consumed(self):
        ip.revise_prediction(self.store, {"new_evidence": ["e"],
                                          "revision_reason": "r"},
                             at=NOW, task_id=TASK)
        feedback, reason = self._consume()
        self.assertIsNone(feedback)
        self.assertIn("predates the current prediction revision", reason)

    def test_contract_mismatch_not_consumed(self):
        feedback, reason = self._consume(contract_version="intent-i#6")
        self.assertIsNone(feedback)
        self.assertIn("contract version does not match", reason)


class ConsumptionTimingTests(unittest.TestCase):
    """R3-closeout 二:消费时序、恢复与降级(可控故障点,无真实模型)。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state"
        self.store = pf.prediction_store_path(self.state)
        self.contract = Path(self.tmp.name) / "intent.json"
        self.contract.write_text("{}", encoding="utf-8")
        # 预测线程(task identity = T-fixture)
        ip.open_prediction(self.store, {
            "kind": "lightweight", "task_id": "T-fixture", "run_id": "run-gen",
            "session_id": "s-gen", "project_id": "/p",
            "contract_version": "c1", "source_identities": {},
            "objective": "o", "assumptions": [{"text": "a", "confidence": "low"}],
            "expected_touch": {"entries": ["a.py"]},
            "impact_bounds": {"lower": "l", "upper": "u", "unknown": "?"},
        }, at=NOW, task_id="T-fixture")

    def tearDown(self):
        self.tmp.cleanup()

    def _propose(self, request_id="req-1"):
        proposed = ci.propose_correction(
            self.contract, intent_id="i", intent_revision=1, provider="codex",
            session_id="s-gen", correction="fix drift", actor="agent",
            source="agent_monitor", request_id=request_id, queue=False)
        return proposed["intervention_id"]

    def _write_artifact(self):
        projection = ip.load_projection(self.store)
        current = projection["tasks"][ip.digest("T-fixture")]["current"]
        artifact = self.state / f"prediction-feedback-{ip.digest('T-fixture')}.json"
        artifact.write_text(json.dumps({
            "schema": "sulde-prediction-feedback-v1",
            "request_id": "req-1", "task_id_sha256": ip.digest("T-fixture"),
            "run_id_sha256": ip.digest("run-gen"),
            "prediction_id": current["prediction_id"],
            "prediction_version": current["version"],
            "verdict": "larger_than_predicted",
            "facts": ["f"], "evidence": ["e"], "created_at": NOW,
        }, ensure_ascii=False), encoding="utf-8")
        return artifact

    def test_1_launch_failure_keeps_artifact_recoverable(self):
        """场景 1:启动失败(未 spawn/未发送)→ 工件保留,可恢复。"""
        self._propose()
        # 模拟:预检通过但进程从未启动 → 无 confirm、无 registry、工件在
        artifact = self._write_artifact()
        self.assertTrue(artifact.exists())
        registry = self.state / "prediction-feedback-consumed.json"
        self.assertFalse(registry.exists())  # 未登记 consumed → 可恢复
        feedback, reason = pf.load_pending_feedback(
            state_dir=self.state, task_id="T-fixture", contract_version="c1")
        self.assertIsNotNone(feedback)  # 恢复:仍可投递

    def test_2_registry_written_artifact_cleanup_interrupted_no_double_delivery(self):
        """场景 3:registry 已落盘、工件未清理时中断 → 恢复不重复消费。"""
        fid = self._propose()
        ci.transition_correction(self.contract, fid, state="queued",
                                 boundary="managed_run_monitor",
                                 reason_code="delivered", actor="system")
        ci.transition_correction(self.contract, fid, state="applied",
                                 boundary="managed_run_monitor",
                                 reason_code="feedback_delivered_via_managed_boundary",
                                 actor="system")
        # 模拟中断:confirm 已写 registry,工件未删
        artifact = self._write_artifact()
        self.assertTrue(artifact.exists())
        pf.confirm_feedback_consumed(
            state_dir=self.state, task_id="T-fixture",
            request_id="req-1", consuming_run_id="run-x",
            consuming_session_id="s-x")
        # 恢复:load 读 registry → 不重复消费;残留工件按精确 request 清理
        feedback, reason = pf.load_pending_feedback(
            state_dir=self.state, task_id="T-fixture", contract_version="c1")
        self.assertIsNone(feedback)
        self.assertIn("no pending feedback artifact", reason)
        self.assertFalse(artifact.exists())  # 残留已按身份清理

    def test_3_consumed_request_reappearing_is_recognized(self):
        """场景 4:已消费 request 再次出现(重放工件)→ 识别为已消费。"""
        pf.confirm_feedback_consumed(
            state_dir=self.state, task_id="T-fixture", request_id="req-seen",
            consuming_run_id="run-x", consuming_session_id="s-x")
        # 重放工件(同 request)再次出现
        artifact = self.state / f"prediction-feedback-{ip.digest('T-fixture')}.json"
        artifact.write_text(json.dumps({
            "schema": "sulde-prediction-feedback-v1",
            "request_id": "req-seen", "task_id_sha256": ip.digest("T-fixture"),
            "run_id_sha256": ip.digest("run-old"), "verdict": "larger_than_predicted",
            "facts": ["f"], "evidence": ["e"], "prediction_id": "pred-x",
            "prediction_version": 1, "created_at": NOW,
        }, ensure_ascii=False), encoding="utf-8")
        feedback, reason = pf.load_pending_feedback(
            state_dir=self.state, task_id="T-fixture", contract_version="c1")
        self.assertIsNone(feedback)
        # registry 中 request 记录未被二次确认破坏
        registry = json.loads((self.state / "prediction-feedback-consumed.json")
                              .read_text(encoding="utf-8"))
        self.assertIn("req-seen", registry["consumed"])

    def test_4_different_request_not_removed_by_old_confirmation(self):
        """场景 5:不同请求的工件不被旧消费确认误删。"""
        pf.confirm_feedback_consumed(
            state_dir=self.state, task_id="T-fixture", request_id="req-old",
            consuming_run_id="run-x", consuming_session_id="s-x")
        artifact = self.state / f"prediction-feedback-{ip.digest('T-fixture')}.json"
        artifact.write_text("{}", encoding="utf-8")
        feedback, reason = pf.load_pending_feedback(
            state_dir=self.state, task_id="T-fixture", contract_version="c1")
        # load 因 registry 无该请求 → 正常走 verdict 流(此处无 verdict 数据则
        # 走 checked/异常),但工件不会被旧确认删除
        self.assertTrue(artifact.exists())

    def test_5_wrong_contract_and_self_source_not_in_input(self):
        """场景 6:错合同 / 非法来源 attempt 不进入执行输入。"""
        self._propose()
        # 错合同(attempt 合同 ≠ 绑定合同)
        import impact_prediction as ipmod
        ipmod.rebind_attempt(self.store, task_id="T-fixture", session_id="s-new",
                             contract_version="c2-different",
                             reason="continuation under new contract",
                             at=NOW, run_id="run-new")
        self._write_artifact()
        feedback, reason = pf.load_pending_feedback(
            state_dir=self.state, task_id="T-fixture", contract_version="c2-different")
        self.assertIsNone(feedback)
        self.assertIn("contract version does not match", reason)

    def test_6_no_prediction_task_creates_no_files(self):
        """场景 7:未启用预测的任务零新建文件。"""
        state = Path(self.tmp.name) / "state-plain"
        state.mkdir(parents=True)
        pf.rebind_open_prediction(state_dir=state, task_id="t",
                                  session_id="s", contract_version="c",
                                  reason="attempt", run_id="run-1")
        feedback, reason = pf.load_pending_feedback(
            state_dir=state, task_id="t", contract_version="c1")
        self.assertIsNone(feedback)
        self.assertEqual(list(state.iterdir()), [])  # 零新建
