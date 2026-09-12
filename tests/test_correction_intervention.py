from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "scripts" / "kb"
if str(KB) not in sys.path:
    sys.path.insert(0, str(KB))

from correction_intervention import (  # noqa: E402
    CorrectionInterventionError,
    apply_queued_corrections,
    event_store_path,
    load_projection,
    propose_correction,
    replay,
    transition_correction,
)
from intent_guardian import (  # noqa: E402
    active_contract_path,
    finalize_host_turn,
    load_contract,
    observe_user_prompt,
    process_hook,
    workspace_root,
)


class CorrectionInterventionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        (self.root / ".git").mkdir()
        self.contract = self.root / "intent.json"
        self.contract.write_text("{}\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def propose(self, **overrides: object) -> dict:
        values = {
            "intent_id": "resume-private-intent",
            "intent_revision": 3,
            "provider": "codex",
            "session_id": "native-private-thread",
            "correction": "不是这个方向，保留我的原表达",
            "actor": "human",
            "source": "user_prompt",
        }
        values.update(overrides)
        return propose_correction(self.contract, **values)

    def test_correction_is_durable_private_and_applied_only_at_boundary(self) -> None:
        queued = self.propose(request_id="prompt-17")
        self.assertEqual(queued["state"], "queued")
        raw = event_store_path(self.contract).read_text(encoding="utf-8")
        self.assertNotIn("不是这个方向", raw)
        self.assertNotIn("native-private-thread", raw)
        self.assertNotIn("resume-private-intent", raw)

        applied = apply_queued_corrections(
            self.contract,
            provider="codex",
            session_id="native-private-thread",
            boundary="pre_tool",
            reason_code="host_reached_pre_tool",
        )
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["state"], "applied")
        self.assertEqual(applied[0]["boundary"], "pre_tool")
        self.assertEqual(
            apply_queued_corrections(
                self.contract,
                provider="codex",
                session_id="native-private-thread",
                boundary="turn_stop",
                reason_code="host_turn_reached_stop",
            ),
            [],
        )

    def test_request_id_is_idempotent_but_repeated_human_corrections_are_distinct(self) -> None:
        first = self.propose(request_id="same-host-event")
        duplicate = self.propose(
            request_id="same-host-event",
            correction="different callback payload must not duplicate the host event",
        )
        repeated = self.propose()
        self.assertEqual(first["intervention_id"], duplicate["intervention_id"])
        self.assertNotEqual(first["intervention_id"], repeated["intervention_id"])
        self.assertEqual(load_projection(self.contract)["sequence"], 4)

    def test_terminal_outcomes_and_invalid_authority_are_enforced(self) -> None:
        rejected = self.propose(queue=False)
        rejected = transition_correction(
            self.contract,
            rejected["intervention_id"],
            state="rejected",
            boundary="manual",
            reason_code="human_rejected",
            actor="human",
        )
        self.assertEqual(rejected["state"], "rejected")
        with self.assertRaisesRegex(
            CorrectionInterventionError, "already terminal"
        ):
            transition_correction(
                self.contract,
                rejected["intervention_id"],
                state="applied",
                boundary="pre_tool",
                reason_code="late_apply",
            )
        with self.assertRaisesRegex(
            CorrectionInterventionError, "human correction authority"
        ):
            self.propose(source="agent_monitor")

    def test_missing_supported_host_lane_is_explicitly_unsupported(self) -> None:
        result = self.propose(provider="unknown", session_id="")
        self.assertEqual(result["state"], "unsupported")
        self.assertEqual(result["reason_code"], "missing_supported_host_lane")

    def test_replay_rejects_sequence_gaps_and_cross_contract_rows(self) -> None:
        self.propose()
        rows = [
            json.loads(line)
            for line in event_store_path(self.contract).read_text().splitlines()
        ]
        rows[1]["sequence"] = 7
        with self.assertRaisesRegex(
            CorrectionInterventionError, "not contiguous"
        ):
            replay(self.contract, rows)
        other = self.root / "other.json"
        other.write_text("{}\n")
        with self.assertRaisesRegex(
            CorrectionInterventionError, "another intent contract"
        ):
            replay(other, [rows[0]])


class InteractiveCorrectionJourneyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        (self.root / ".git").mkdir()
        self.home = Path(self.temp.name) / "kb"
        self.environment = mock.patch.dict(
            "os.environ", {"SULDE_KB_HOME": str(self.home)}
        )
        self.environment.start()
        self.payload = {
            "client": "codex",
            "session_id": "thread-correction",
            "cwd": str(self.root),
            "prompt": "先按我的表达修改简历",
            "sulde_observation_source": "live_host_hook",
        }
        observe_user_prompt(self.payload, provider="codex")
        self.contract = active_contract_path(self.home, workspace_root(self.root))

    def tearDown(self) -> None:
        self.environment.stop()
        self.temp.cleanup()

    def test_user_prompt_to_pre_tool_is_one_closed_interactive_journey(self) -> None:
        self.payload["prompt"] = "不是这样，这不是我想要的"
        context = observe_user_prompt(self.payload, provider="codex")
        self.assertIn("CORRECTION_QUEUED", context)
        projection = load_projection(self.contract)
        item = next(iter(projection["interventions"].values()))
        self.assertEqual(item["state"], "queued")

        decision, selected = process_hook(
            {
                "client": "codex",
                "session_id": "thread-correction",
                "cwd": str(self.root),
                "tool_name": "Read",
                "tool_input": {"path": "resume.md"},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(selected, self.contract.resolve())
        self.assertIsNotNone(decision)
        applied = load_projection(self.contract)["interventions"][
            item["intervention_id"]
        ]
        self.assertEqual(applied["state"], "applied")
        self.assertEqual(applied["boundary"], "pre_tool")
        self.assertEqual(load_contract(self.contract)["status"], "active")

    def test_stop_applies_without_claiming_semantic_acceptance(self) -> None:
        self.payload["prompt"] = "又改错了，不要再这样改"
        queued = observe_user_prompt(self.payload, provider="codex")
        self.assertIn("CORRECTION_QUEUED", queued)
        context = finalize_host_turn(
            {
                "client": "codex",
                "session_id": "thread-correction",
                "cwd": str(self.root),
            },
            provider="codex",
        )
        self.assertIn("boundary=turn_stop", context)
        self.assertIn("semantic_acceptance=unknown", context)
        item = next(iter(load_projection(self.contract)["interventions"].values()))
        self.assertEqual(item["state"], "applied")

    def test_other_host_lane_cannot_consume_the_correction(self) -> None:
        self.payload["prompt"] = "不是这个意思，没有理解"
        observe_user_prompt(self.payload, provider="codex")
        finalize_host_turn(
            {
                "client": "claude",
                "session_id": "claude-other",
                "cwd": str(self.root),
            },
            provider="claude",
        )
        item = next(iter(load_projection(self.contract)["interventions"].values()))
        self.assertEqual(item["state"], "queued")

    def test_second_enforce_correction_applies_policy_pause_immediately(self) -> None:
        contract = load_contract(self.contract)
        contract["mode"] = "enforce"
        contract["confirmed_by"] = "human"
        from intent_guardian import write_contract

        write_contract(self.contract, contract)
        self.payload["prompt"] = "不是这样，这不是我想要的"
        observe_user_prompt(self.payload, provider="codex")
        finalize_host_turn(self.payload, provider="codex")
        self.payload["prompt"] = "又改错了，越来越偏"
        context = observe_user_prompt(self.payload, provider="codex")
        self.assertIn("CORRECTION_APPLIED", context)
        self.assertIn("PAUSED", context)
        items = list(load_projection(self.contract)["interventions"].values())
        self.assertEqual([row["state"] for row in items], ["applied", "applied"])
        self.assertEqual(items[-1]["boundary"], "policy_pause")


if __name__ == "__main__":
    unittest.main()
