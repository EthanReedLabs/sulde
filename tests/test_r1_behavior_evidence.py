"""R1-05: behavior-evidence run — the answer is NOT in the execution input.

Scenario: the task input asks for one thing ("expose VALUE from value.py").
The first attempt over-reaches and breaks an existing consumer.  The chain
must catch the over-reach BEFORE delivery via the prediction facts, deliver
the feedback to the agent, and the second attempt must fix it — with the
final proof being an actual execution of the consumer (independent of the
prediction).

Judgment criteria live in THIS test; the task input saved as evidence does
not mention consumers, verdicts or corrections.
"""
from __future__ import annotations

import json
import os
import shutil
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
import prediction_feedback as pf  # noqa: E402

NOW = "2026-09-27T15:00:00+00:00"
TASK = "task/r1-behavior-evidence"
RUN = "run-r1behavior1111111111111"
EVIDENCE_DIR = Path("/Volumes/Optimus/Sulde/tasks/predictive-execution/R1")


def archive_evidence(src_dir: Path, *, dest_root: Path, run_id: str) -> Path:
    """Explicit, unique, overwrite-proof archiving (R2-01).

    Normal tests never call this: they use temp dirs.  Archiving requires an
    explicit destination root, creates a fresh per-run directory, and refuses
    to touch an existing one.
    """
    dest_root.mkdir(parents=True, exist_ok=True)
    run_dir = dest_root / run_id
    if run_dir.exists():
        raise FileExistsError(f"evidence run directory already exists: {run_dir}")
    shutil.copytree(src_dir, run_dir)
    return run_dir


def _run_git(root: Path, *args: str, check: bool = True):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", check=False)
    if check and result.returncode != 0:
        raise AssertionError(result.stderr)
    return result


class R1BehaviorEvidenceTests(unittest.TestCase):
    def test_overreach_caught_before_delivery_and_fixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            repo = tmp / "repo"
            repo.mkdir()
            # baseline: consumer.py actually executes and exits 0
            (repo / "consumer.py").write_text("import value\nprint('ok', value.VALUE)\n",
                                              encoding="utf-8")
            (repo / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
            _run_git(repo, "init", "-q")
            _run_git(repo, "add", ".")
            _run_git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
                     "commit", "-m", "baseline")
            _run_git(repo, "tag", "baseline")

            # execution input (saved as evidence): no answers inside
            task_input = ("Task: expose VALUE = 2 from value.py. "
                          "Deliverable: the module exports VALUE. "
                          "Work only inside this repository.")
            (tmp / "task-input.txt").write_text(task_input, encoding="utf-8")

            # baseline behavior check passes
            probe = subprocess.run([sys.executable, "-B", str(repo / "consumer.py")],
                                   capture_output=True, text=True, check=False,
                                   encoding="utf-8", errors="replace",
                                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            self.assertEqual(probe.returncode, 0, probe.stderr)

            state = tmp / "state"
            store = pf.prediction_store_path(state)
            contract = tmp / "intent.json"
            contract.write_text("{}", encoding="utf-8")
            opened = ip.open_prediction(store, {
                "kind": "lightweight",
                "task_id": TASK, "run_id": RUN, "session_id": "s-r1",
                "project_id": str(repo), "contract_version": "r1-behavior",
                "source_identities": {},
                "objective": "expose VALUE from value.py",
                "assumptions": [{"text": "no other module is affected", "confidence": "high"}],
                "expected_touch": {"entries": ["value.py"]},
                "impact_bounds": {"lower": "one constant", "upper": "importers of value",
                                  "unknown": "none recorded"},
            }, at=NOW, task_id=TASK)

            def collect():
                bundle = facts.collect(repo, baseline="baseline",
                                       expected_paths=["value.py"], source_identities={})
                prediction = ip.load_projection(store)["tasks"][ip.digest(TASK)]["current"]
                verdict = facts.classify_against_prediction(bundle, bundle["split"], prediction)
                return bundle, verdict

            # --- attempt 1: the agent over-reaches (breaks consumer.py) ---
            (repo / "value.py").write_text("VALUE = 2\n", encoding="utf-8")
            (repo / "consumer.py").write_text("import value\nprint('ok', value.TYPO)\n",
                                              encoding="utf-8")
            feedback1 = pf.record_completion_feedback(
                state_dir=state, repo=repo, task_id=TASK, run_id=RUN,
                session_id="s-r1", provider="codex", intent_id="i", intent_revision=1,
                contract_version="r1-behavior", baseline_revision="baseline")
            self.assertEqual(feedback1["verdict"], "larger_than_predicted")
            # R2-04: feedback rides the artifact the launcher composes the
            # next attempt brief from
            self.assertIn("feedback_artifact", feedback1)
            self.assertEqual(feedback1["feedback"]["verdict"], "larger_than_predicted")
            artifact = json.loads(Path(feedback1["feedback_artifact"]).read_text(encoding="utf-8"))
            self.assertEqual(artifact["verdict"], "larger_than_predicted")
            self.assertIn("outside expected touch", " ".join(artifact["facts"]))

            # attempt 1 must NOT be delivered: the correction is queued, the
            # prediction is open, and the broken consumer proves it
            broken = subprocess.run([sys.executable, "-B", str(repo / "consumer.py")],
                                    capture_output=True, text=True, check=False,
                                    encoding="utf-8", errors="replace",
                                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            self.assertNotEqual(broken.returncode, 0)

            # --- attempt 2: the agent receives the feedback and changes action ---
            ci.apply_queued_corrections(contract, provider="codex", session_id="s-r1",
                                        boundary="managed_run_monitor",
                                        reason_code="feedback_delivered")
            (repo / "consumer.py").write_text("import value\nprint('ok', value.VALUE)\n",
                                              encoding="utf-8")
            feedback2 = pf.record_completion_feedback(
                state_dir=state, repo=repo, task_id=TASK, run_id=RUN,
                session_id="s-r1", provider="codex", intent_id="i", intent_revision=1,
                contract_version="r1-behavior", baseline_revision="baseline")
            # after the fix the touch set is back inside the prediction
            self.assertEqual(feedback2["verdict"], "as_predicted")
            # the agent records a reasoned judgment closing the feedback loop
            ej.record_judgment(tmp / "judgments.jsonl", {
                "task_id": TASK, "run_id": RUN, "session_id": "s-r1",
                "trigger": "verification_contradicts_prediction",
                "key_facts": ["consumer.py import fixed after feedback"],
                "next_action": "keep consumer.py; deliver",
                "evidence_refs": ["consumer.py executes with exit 0"],
            }, at=NOW)

            # --- independent verification: actual behavior, not the prediction ---
            final = subprocess.run([sys.executable, "-B", str(repo / "consumer.py")],
                                   capture_output=True, text=True, check=False,
                                   encoding="utf-8", errors="replace",
                                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            self.assertEqual(final.returncode, 0, final.stderr)

            self.assertIn("ok 2", final.stdout)
            # and the delivered feedback is settled by the supervisor, not the agent
            # supervisor's own settlement ledger (independent of the run):
            # the feedback artifact binds the problem, the rerun binds the result
            summary = "independent rerun: consumer executes, exit 0, output 'ok 2'"
            proposed = ci.propose_correction(contract, intent_id="i", intent_revision=1,
                                  provider="codex", session_id="s-r1",
                                  correction="supervisor settlement for " + artifact["request_id"],
                                  actor="agent", source="agent_monitor",
                                  request_id="settle-" + artifact["request_id"])
            fid = proposed["intervention_id"]
            ci.transition_correction(contract, fid, state="queued", boundary="manual",
                                     reason_code="delivered_to_agent_session", actor="system")
            ci.transition_correction(contract, fid, state="applied", boundary="manual",
                                     reason_code="feedback_delivered_via_session_continuation",
                                     actor="system")
            ci.transition_correction(contract, fid, state="acknowledged", boundary="turn_stop",
                                     reason_code="executor_applied_feedback", actor="agent")
            ci.transition_correction(contract, fid, state="verified", boundary="manual",
                                     reason_code="independent_behavior_verified",
                                     actor="system", verification_summary=summary,
                                     evidence_sha256=ci._verification_evidence_digest(fid, summary))

            # R2-01: artifacts stay in the test's temp dir; formal archiving
            # is an explicit, separate step (see archive_evidence).
            out_dir = tmp / "evidence"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "task-input.txt").write_text(task_input, encoding="utf-8")
            (out_dir / "ledger.jsonl").write_text(
                store.read_text(encoding="utf-8"), encoding="utf-8")
            (out_dir / "corrections.jsonl").write_text(
                contract.with_name("intent.corrections.jsonl")
                .read_text(encoding="utf-8"), encoding="utf-8")
            (out_dir / "final-behavior.json").write_text(json.dumps({
                "exit_code": final.returncode, "stdout": final.stdout.strip(),
                "verdicts": [feedback1["verdict"], feedback2["verdict"]],
            }, indent=1), encoding="utf-8")


class ArchiveIsolationTests(unittest.TestCase):
    def test_normal_run_never_touches_existing_evidence_even_when_mounted(self):
        """R2-01 反例证明:外接盘挂载时,普通测试不改写历史证据。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            mounted_root = tmp / "Optimus-R1"
            mounted_root.mkdir()
            historical = mounted_root / "20260927T130000-archived-run"
            historical.mkdir()
            (historical / "final-behavior.json").write_text('{"archived": true}',
                                                            encoding="utf-8")
            before = sorted(p.name for p in historical.iterdir())
            # a normal run produces its artifacts in a TEMP dir and never calls
            # the archive function against the mounted root
            normal_run_artifacts = tmp / "temp-evidence"
            normal_run_artifacts.mkdir()
            (normal_run_artifacts / "final-behavior.json").write_text('{"exit_code": 0}',
                                                                      encoding="utf-8")
            self.assertEqual(sorted(p.name for p in historical.iterdir()), before)
            self.assertEqual(before, ["final-behavior.json"])
            # the archive function itself refuses to overwrite an existing run
            with self.assertRaises(FileExistsError):
                archive_evidence(normal_run_artifacts, dest_root=mounted_root,
                                 run_id="20260927T130000-archived-run")


if __name__ == "__main__":
    unittest.main()
