from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from decision_kernel import (  # noqa: E402
    claim_human_grant,
    observe_grant_prompt,
    prepare_human_grant,
    record_grant_decision,
)
from grant_broker import transaction as grant_transaction  # noqa: E402
from intent_guardian import (  # noqa: E402
    GuardianSession,
    IntentGuardianError,
    default_contract,
    load_contract,
    normalize_hook_event,
    write_contract,
)
from intent_guardian_parts.completion_recovery import (  # noqa: E402
    _matching_grant_transaction,
    matching_authorized_completion,
    recover_completed_audit_verifications,
)
from intent_guardian_parts.events import _effect_resource_identity  # noqa: E402
from intent_guardian_parts.state import (  # noqa: E402
    _append_jsonl,
    audit_path,
    event_fingerprint,
    now_iso,
)
from intervention import (  # noqa: E402
    load_projection as load_intervention_projection,
    mark_attempt_unknown,
)


class AuthorizedCompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        self.contract_path = Path(self.temp.name) / "intent" / "active.json"
        self.contract_path.parent.mkdir()
        write_contract(
            self.contract_path,
            default_contract(
                intent_id="authorized-completion",
                objective="complete one exact host-local plugin effect",
                rationale="exercise native grant completion pairing",
                acceptance_criteria=["the exact installed generation is independently read"],
                workspace=self.root,
                mode="enforce",
                allowed_paths=["."],
                confirmed_by="human",
            ),
        )

    def event(self, *, phase: str, call_id: str) -> dict:
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "completion-session",
                "call_id": call_id,
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": "candidate-promotion-fixture"},
                "success": True,
            },
            phase=phase,
            provider="codex",
        )
        event.update(
            {
                "capability": "tool:Bash",
                "effect": "external_write",
                "target": "[host-local:codex-plugin]",
                "verification_kind": "content",
                "verification_sha256": "a" * 64,
            }
        )
        if phase == "completed":
            event["independent_verification"] = {
                "capability": "tool:codex_plugin_install_verify",
                "source": "local_codex_install_read",
                "evidence": {"content": ["a" * 64]},
            }
        return event

    def authorized_start(self, *, call_id: str = "allowed-call") -> tuple[dict, str]:
        denied_event = self.event(phase="started", call_id="initial-denial")
        denied = GuardianSession(self.contract_path).observe(denied_event)
        self.assertEqual(denied.action, "deny")
        tx = prepare_human_grant(
            self.contract_path,
            load_contract(self.contract_path),
            denied_event,
            denied,
        )
        self.assertIsNotNone(tx)
        observe_grant_prompt(self.contract_path, tx)
        record_grant_decision(self.contract_path, tx, outcome="allow")

        started = self.event(phase="started", call_id=call_id)
        dispatch = claim_human_grant(
            self.contract_path,
            load_contract(self.contract_path),
            started,
        )
        self.assertIsNotNone(dispatch)
        started["human_grant_dispatch"] = dispatch
        allowed = GuardianSession(self.contract_path).observe(started)
        self.assertEqual(allowed.reason_code, "human_grant_consumed")
        current = load_contract(self.contract_path)
        opened = current["runtime"]["open_events"][-1]
        started.update(
            {
                "event_id": opened["event_id"],
                "fingerprint": opened["fingerprint"],
                "effect_operation_fingerprint": opened["operation_fingerprint"],
                "effect_resource_key": opened["effect_resource_key"],
                "effect_resource_base": opened["effect_resource_base"],
                "effect_resource_context": opened["effect_resource_context"],
                "effect_resource_relation": opened["effect_resource_relation"],
                "intent_id": current["intent_id"],
                "intent_revision": current["revision"],
                "task_epoch": current["task_epoch"],
                "at": opened["started_at"],
            }
        )
        return started, str(tx["transaction_id"])

    def test_exact_completion_settles_effect_and_grant_broker(self) -> None:
        _started, tx_id = self.authorized_start()
        completed = self.event(phase="completed", call_id="allowed-call")
        current = load_contract(self.contract_path)
        key, base, context, relation = _effect_resource_identity(current, completed)
        completed.update(
            {
                "effect_resource_key": key,
                "effect_resource_base": base,
                "effect_resource_context": context,
                "effect_resource_relation": relation,
            }
        )
        completed["fingerprint"] = event_fingerprint(completed)
        completed["task_epoch"] = current["task_epoch"]
        self.assertIsNotNone(
            matching_authorized_completion(
                current["runtime"]["open_events"],
                completed,
                fingerprint=completed["fingerprint"],
            ),
            json.dumps(
                {"open": current["runtime"]["open_events"], "completed": completed},
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        dispatched_attempt = next(
            iter(load_intervention_projection(self.contract_path)["attempts"].values())
        )
        self.assertIsNotNone(
            _matching_grant_transaction(
                self.contract_path,
                dispatched_attempt,
                completed,
            ),
            json.dumps(
                {
                    "attempt": dispatched_attempt,
                    "broker": grant_transaction(self.contract_path, tx_id),
                    "completed": completed,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        decision = GuardianSession(self.contract_path).observe(completed)

        self.assertEqual(decision.action, "allow")
        self.assertEqual(decision.reason_code, "authorized_dispatch_completion")
        current = load_contract(self.contract_path)
        self.assertEqual(current["runtime"]["open_events"], [])
        self.assertEqual(current["runtime"]["pending_verifications"], [])
        attempts = load_intervention_projection(self.contract_path)["attempts"]
        attempt = next(iter(attempts.values()))
        self.assertEqual(attempt["state"], "system_verified")
        broker = grant_transaction(self.contract_path, tx_id)
        self.assertEqual(broker["settlement"]["status"], "succeeded")
        self.assertIsNotNone(broker["effect_receipt"])
        self.assertIsNotNone(broker["verifier_receipt"])

    def test_wrong_call_id_is_not_an_authorized_completion(self) -> None:
        self.authorized_start()
        current = load_contract(self.contract_path)
        completed = self.event(phase="completed", call_id="foreign-call")
        self.assertIsNone(
            matching_authorized_completion(
                current["runtime"]["open_events"],
                completed,
                fingerprint=completed.get("fingerprint", ""),
            )
        )
        with self.assertRaisesRegex(
            IntentGuardianError,
            "same-resource blocker/debt prevents dispatch",
        ):
            GuardianSession(self.contract_path).observe(completed)
        attempt = next(
            iter(load_intervention_projection(self.contract_path)["attempts"].values())
        )
        self.assertEqual(attempt["state"], "dispatched")

    def test_reconciler_uses_exact_audit_evidence_without_replaying_effect(self) -> None:
        started, tx_id = self.authorized_start(call_id="orphan-call")
        completed = deepcopy(started)
        completed.update(
            {
                "phase": "completed",
                "success": True,
                "at": now_iso(),
                "independent_verification": {
                    "capability": "tool:codex_plugin_install_verify",
                    "source": "local_codex_install_read",
                    "evidence": {"content": ["a" * 64]},
                },
            }
        )
        current = load_contract(self.contract_path)
        current["runtime"]["open_events"] = []
        write_contract(self.contract_path, current)
        _append_jsonl(
            audit_path(self.contract_path),
            {
                "schema": "sulde-guardian-event-v1",
                "contract": {
                    "intent_id": current["intent_id"],
                    "revision": current["revision"],
                    "mode": current["mode"],
                    "status": current["status"],
                },
                "decision": {"action": "allow"},
                "event": completed,
            },
        )

        recovered = recover_completed_audit_verifications(self.contract_path)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["grant_broker_status"], "succeeded")
        attempt = next(
            iter(load_intervention_projection(self.contract_path)["attempts"].values())
        )
        self.assertEqual(attempt["state"], "system_verified")
        self.assertEqual(
            grant_transaction(self.contract_path, tx_id)["settlement"]["status"],
            "succeeded",
        )

    def test_reconciler_settles_safe_boundary_unknown_without_replaying_effect(self) -> None:
        started, tx_id = self.authorized_start(call_id="safe-boundary-race")
        completed = deepcopy(started)
        completed.update(
            {
                "phase": "completed",
                "success": True,
                "at": now_iso(),
                "independent_verification": {
                    "capability": "tool:codex_plugin_install_verify",
                    "source": "local_codex_install_read",
                    "evidence": {"content": ["a" * 64]},
                },
            }
        )
        current = load_contract(self.contract_path)
        current["runtime"]["open_events"] = []
        write_contract(self.contract_path, current)
        _append_jsonl(
            audit_path(self.contract_path),
            {
                "schema": "sulde-guardian-event-v1",
                "contract": {
                    "intent_id": current["intent_id"],
                    "revision": current["revision"],
                    "mode": current["mode"],
                    "status": current["status"],
                },
                "decision": {"action": "allow"},
                "event": completed,
            },
        )
        attempt = next(
            iter(load_intervention_projection(self.contract_path)["attempts"].values())
        )
        intervention = mark_attempt_unknown(
            self.contract_path,
            attempt["attempt_id"],
            reason=(
                "safe-boundary recovery found an active effect attempt without "
                "matching contract runtime state"
            ),
        )

        recovered = recover_completed_audit_verifications(self.contract_path)

        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["grant_broker_status"], "succeeded")
        projection = load_intervention_projection(self.contract_path)
        settled = projection["attempts"][attempt["attempt_id"]]
        self.assertEqual(settled["state"], "system_verified")
        self.assertEqual(
            projection["interventions"][intervention["intervention_id"]]["status"],
            "resolved",
        )
        self.assertEqual(
            projection["interventions"][intervention["intervention_id"]]["decision"],
            "system_verified",
        )
        self.assertEqual(
            grant_transaction(self.contract_path, tx_id)["settlement"]["status"],
            "succeeded",
        )

    def test_reconciler_rejects_foreign_verifier(self) -> None:
        started, _tx_id = self.authorized_start(call_id="orphan-call")
        completed = deepcopy(started)
        completed.update(
            {
                "phase": "completed",
                "success": True,
                "at": now_iso(),
                "independent_verification": {
                    "capability": "tool:foreign_verify",
                    "source": "foreign_read",
                    "evidence": {"content": ["a" * 64]},
                },
            }
        )
        current = load_contract(self.contract_path)
        current["runtime"]["open_events"] = []
        write_contract(self.contract_path, current)
        _append_jsonl(
            audit_path(self.contract_path),
            {
                "schema": "sulde-guardian-event-v1",
                "contract": {
                    "intent_id": current["intent_id"],
                    "revision": current["revision"],
                },
                "decision": {"action": "allow"},
                "event": completed,
            },
        )
        self.assertEqual(recover_completed_audit_verifications(self.contract_path), [])
        attempt = next(
            iter(load_intervention_projection(self.contract_path)["attempts"].values())
        )
        self.assertEqual(attempt["state"], "dispatched")


if __name__ == "__main__":
    unittest.main()
