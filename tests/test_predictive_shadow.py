"""B4 PROTOCOL tests: scenario fixtures over the B1-B3 protocol (fake provider).

Each scenario mirrors a row of plan §7.  SCOPE WITHDRAWN (R1-05): these
fixtures ENCODE their expected answers (the defect and its location are
written into the fixture), so they prove the protocol wiring only —
classification, judgment records, budgets and gates — NOT that a real
agent auto-discovers defects.  Real-behavior evidence lives in
tests/test_r1_behavior_evidence.py and the R1 evidence run.
"""
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
import execution_judgment as ej  # noqa: E402
import impact_prediction as ip  # noqa: E402
import incremental_facts as facts  # noqa: E402

NOW = "2026-09-27T11:00:00+00:00"


class _Repo:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._git("init", "-q")

    def _git(self, *args, check=True):
        result = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", check=False)
        if check and result.returncode != 0:
            raise AssertionError(result.stderr)
        return result

    def commit(self, path: str, content: str, message: str):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self._git("add", path)
        self._git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", message)


class ShadowHarness:
    """One prediction thread + judgment store over one disposable repo."""

    def __init__(self, tmp: Path, task_id: str):
        self.repo = _Repo(tmp / "repo")
        self.prediction_store = tmp / "predictions.jsonl"
        self.judgment_store = tmp / "judgments.jsonl"
        self.task_id = task_id

    def open_prediction(self, expected_paths: list[str], **overrides):
        payload = {
            "kind": "full",
            "task_id": self.task_id, "run_id": "run-shadow", "session_id": "s",
            "project_id": str(self.repo.root),
            "contract_version": "r1",
            "source_identities": {},
            "objective": "scenario",
            "assumptions": [{"text": "baseline holds", "confidence": "medium"}],
            "expected_touch": {"entries": expected_paths},
            "invariants": ["nothing else changes"],
            "impact_bounds": {"lower": "scoped", "upper": "module-wide", "unknown": "callers"},
            "falsification_probe": "collect facts and compare",
            "recovery_path": "git revert",
            **overrides,
        }
        return ip.open_prediction(self.prediction_store, payload, at=NOW, task_id=self.task_id)

    def facts(self, expected_paths: list[str]):
        bundle = facts.collect(self.repo.root, baseline="baseline",
                               expected_paths=expected_paths, source_identities={})
        prediction = ip.load_projection(self.prediction_store)["tasks"][ip.digest(self.task_id)]["current"]
        verdict = facts.classify_against_prediction(bundle, bundle["split"], prediction)
        return bundle, verdict

    def judge(self, trigger: str, verdict: dict, bundle: dict, *, next_action: str,
              prediction_id: str | None = None, **overrides):
        payload = {
            "task_id": self.task_id, "run_id": "run-shadow", "session_id": "s",
            "trigger": trigger,
            "prediction_id": prediction_id or "",
            "key_facts": [f"suggested={verdict['suggested_verdict']}: {verdict['reason']}"],
            "next_action": next_action,
            "evidence_refs": ["facts-bundle"],
            **overrides,
        }
        return ej.record_judgment(self.judgment_store, payload, at=NOW)


class PredictiveShadowScenarios(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.harness = ShadowHarness(Path(self.tmp.name), "task/shadow")
        self.harness.repo.commit("scripts/kb/mod.py", "value = 1\n", "baseline")
        self.harness.repo._git("tag", "baseline")

    def tearDown(self):
        self.tmp.cleanup()

    def test_small_change_flips_observe_default_is_flagged_larger(self):
        """Plan §7: 小改动改变 observe 默认行为 → 语义影响按行为,不按行数."""
        self.harness.open_prediction(["scripts/kb/mod.py"])
        self.harness.repo.commit("scripts/kb/mod.py", "value = 0  # default flipped\n", "one-line default flip")
        self.harness.repo.commit("scripts/kb/other.py", "uses value\n", "new consumer appears")
        bundle, verdict = self.harness.facts(["scripts/kb/mod.py"])
        self.assertEqual(verdict["suggested_verdict"], "larger_than_predicted")
        judgment = self.harness.judge("verification_contradicts_prediction", verdict, bundle,
                                      next_action="re-evaluate default flip semantics before delivery")
        self.assertEqual(judgment["trigger"], "verification_contradicts_prediction")

    def test_missing_recovery_entry_is_caught_before_completion(self):
        """Plan §7: 漏掉独立恢复入口 → 完成声明前指出缺口."""
        self.harness.open_prediction(["scripts/kb/mod.py"])
        self.harness.repo.commit("scripts/kb/mod.py",
                                 "value = 2\n# TODO recovery entry missing\n", "missing recovery")
        bundle, verdict = self.harness.facts(["scripts/kb/mod.py"])
        judgment = self.harness.judge("before_expensive_operation", verdict, bundle,
                                      next_action="block delivery: recovery entry missing, add and verify it")
        self.assertIn("recovery", judgment["next_action"])

    def test_extra_consumer_updates_prediction_not_silent_spread(self):
        """Plan §7: 实际多出消费者 → 更新预测与验证范围,不静默扩散."""
        self.harness.open_prediction(["scripts/kb/mod.py"])
        self.harness.repo.commit("scripts/kb/mod.py", "value = 2\n", "expected change")
        self.harness.repo.commit("scripts/kb/consumer.py", "import mod\nprint(mod.value)\n", "extra consumer")
        bundle, verdict = self.harness.facts(["scripts/kb/mod.py"])
        self.assertEqual(verdict["suggested_verdict"], "larger_than_predicted")
        ip.revise_prediction(self.harness.prediction_store,
                             {"new_evidence": ["consumer.py references mod.value"],
                              "revision_reason": "extra consumer surfaced by mechanical scan"},
                             at=NOW, task_id=self.harness.task_id)
        entry = ip.load_projection(self.harness.prediction_store)["tasks"][ip.digest(self.harness.task_id)]
        self.assertEqual(entry["current"]["version"], 2)
        self.assertEqual(entry["current"]["new_evidence"], ["consumer.py references mod.value"])

    def test_clean_low_risk_change_has_no_correction_and_zero_model_reviews(self):
        """Plan §7: 无缺陷低风险改动 → 无额外人工阻断,预算内完成."""
        self.harness.open_prediction(["scripts/kb/mod.py"])
        self.harness.repo.commit("scripts/kb/mod.py", "value = 2\n", "clean change")
        bundle, verdict = self.harness.facts(["scripts/kb/mod.py"])
        self.assertEqual(verdict["suggested_verdict"], "as_predicted")
        judgment = self.harness.judge("after_logical_change_complete", verdict, bundle,
                                      next_action="deliver; no correction needed")
        self.assertFalse(judgment["model_review_used"])
        self.assertEqual(len(ej.load_judgments(self.harness.judgment_store,
                                               task_id=self.harness.task_id)), 1)

    def test_executor_cannot_settle_correction_supervisor_gate(self):
        """Plan §7: 双会话与权限 → 执行者不能自我结算;独立回读才能关闭."""
        contract = Path(self.tmp.name) / "intent.json"
        contract.write_text("{}", encoding="utf-8")
        ci.propose_correction(contract, intent_id="i", intent_revision=1, provider="codex",
                              session_id="s1", correction="fix drift", actor="agent",
                              source="agent_monitor")
        projection = ci.load_projection(contract)
        intervention_id = next(iter(projection["interventions"]))
        ci.transition_correction(contract, intervention_id, state="queued",
                                 boundary="policy_pause", reason_code="queued", actor="system")
        ci.transition_correction(contract, intervention_id, state="applied",
                                 boundary="managed_run_monitor",
                                 reason_code="managed_process_tree_interrupted", actor="system")
        with self.assertRaises(ci.CorrectionInterventionError):
            ci.transition_correction(contract, intervention_id, state="verified",
                                     boundary="manual", reason_code="self_settle",
                                     actor="agent", evidence_sha256="c" * 32)

    def test_degraded_supervisor_discloses_without_faking_verified(self):
        """Plan §7: 监督器故障 → 准确披露降级,不伪造成功."""
        self.harness.open_prediction(["scripts/kb/mod.py"])
        self.harness.repo.commit("scripts/kb/mod.py", "value = 3\n", "change under degraded supervisor")
        # supervisor read-back unavailable: the prediction cannot be verified,
        # so the honest terminal state is an explicit degraded disclosure,
        # never a forged verified/closed.
        entry = ip.load_projection(self.harness.prediction_store)["tasks"][ip.digest(self.harness.task_id)]
        self.assertEqual(entry["current"]["status"], "open")
        judgment = self.harness.judge("before_expensive_operation",
                                      {"suggested_verdict": "as_predicted", "reason": "facts collected"},
                                      {"changed_paths": ["scripts/kb/mod.py"]},
                                      next_action="supervisor unavailable: disclose degraded, keep open")
        self.assertIn("degraded", judgment["next_action"])
        self.assertEqual(entry["checks"], [])  # no verification recorded


if __name__ == "__main__":
    unittest.main()
