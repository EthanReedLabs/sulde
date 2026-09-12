from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts" / "kb"
sys.path.insert(0, str(SCRIPT_DIR))

from approval_invariant import (  # noqa: E402
    LEGACY_EVENT_SCHEMA, ask_approval, ask_typed_approval, decide_approval,
    decide_typed_approval, observe_typed_prompt, event_store_path,
    load_projection as load_approval_projection,
)
from intent_guardian import (  # noqa: E402
    GuardianSession,
    create_revision_proposal,
    default_contract,
    execute_native_decision,
    load_contract,
    native_decision_preview,
    normalize_hook_event,
    observe_native_permission_request,
    write_contract,
)
from intent_guardian_parts import recovery as guardian_recovery  # noqa: E402
from native_decision_journal import load_projection as load_native_projection  # noqa: E402
from task_ownership import upsert_task_lane  # noqa: E402


class P0TransactionIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = mock.patch.dict(
            os.environ,
            {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("SULDE_") and key != "CODEX_THREAD_ID"
            },
            clear=True,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "workspace"
        self.root.mkdir()
        (self.root / ".git").mkdir()
        self.contract = Path(self.temporary.name) / "intent.json"

    def initialize_contract(self, *, owner_session: str = "proposal-owner") -> None:
        contract = default_contract(
            intent_id="p0-transaction-integration",
            objective="验证冻结 P0 事务边界",
            acceptance_criteria=["authority、CAS、lane 与 readiness 契约一致"],
            workspace=self.root,
            mode="enforce",
            allowed_paths=["allowed.txt"],
            confirmed_by="human",
        )
        upsert_task_lane(
            contract,
            provider="codex",
            session_id=owner_session,
            state="bound",
            source="p0-integration-fixture",
        )
        write_contract(self.contract, contract)

    def human_proposal(self) -> tuple[Path, str]:
        return create_revision_proposal(
            self.contract,
            objective="只更新一个明确的本地文件",
            acceptance_criteria=["只修改 allowed.txt"],
            mode="enforce",
            rationale="冻结 P0 集成事务",
            allowed_paths=["allowed.txt"],
            decision_route="human",
            intent_kind="deterministic",
            risk="medium",
            effects=["local_write"],
            reversibility="reversible",
            cost="none",
            rollback="恢复 allowed.txt",
            provider="codex",
        )

    def present_native_proposal(self, digest: str, session_id: str) -> dict:
        preview = native_decision_preview(
            self.contract,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id=session_id,
        )
        return observe_native_permission_request(
            {
                "client": "codex",
                "session_id": session_id,
                "cwd": str(self.root),
                "intent_contract": str(self.contract),
                "permission_mode": "default",
                "tool_name": "Bash",
                "tool_input": {
                    "command": shlex.join(preview["command_argv"]),
                    "description": preview["description"],
                },
            },
            provider="codex",
        )

    def test_synthetic_interleaved_ledger_replays_without_mutating_fixture(self) -> None:
        # Construct from protocol APIs, never from an operator's historical log.
        self.contract.write_text("{}\n", encoding="utf-8")
        session = "synthetic-interleaved-session"
        common = dict(provider="codex", session_id=session)
        def ask_legacy(target):
            return ask_approval(self.contract, intent_id="synthetic-interleaved",
                                intent_revision=1, kind="event", target=target,
                                source="synthetic-fixture", **common)
        ask_legacy("synthetic-before")
        snapshot = {
            "card_sha256": "synthetic-card", "provider": "codex", "session_id": session,
            "lane_sha256": hashlib.sha256(f"codex\0{session}".encode()).hexdigest(),
            "target_sha256": "synthetic-target", "revision": 1,
            "journal_sha256": "synthetic-journal", "effect_sha256": "synthetic-effect",
            "world_state_sha256": "synthetic-world",
        }
        typed_request = ask_typed_approval(
            self.contract, snapshot=snapshot, kind="effect-intervention",
            source="synthetic-fixture", request_id="apr-222222222222222222222222",
        )
        observe_typed_prompt(self.contract, request_id=typed_request["request_id"],
                             snapshot=snapshot, prompt_shown=True, decision_owner="human", **common)
        decide_approval(self.contract, kind="event", target="synthetic-before",
                        outcome="cancelled", actor="synthetic-human", **common)
        decide_typed_approval(
            self.contract, request_id=typed_request["request_id"], receipt_id="synthetic-receipt",
            outcome="allow", snapshot=snapshot, current_snapshot=snapshot,
            decision_owner="human", actor="synthetic-human", **common,
        )
        last = ask_legacy("synthetic-after")
        decide_approval(self.contract, kind="event", target="synthetic-after",
                        outcome="approved", actor="synthetic-human", **common)
        store = event_store_path(self.contract)
        rows = [json.loads(line) for line in store.read_text().splitlines()]
        # Explicitly exercise supported v1 audit rows interleaved after v2 CAS.
        for row in rows:
            if row.get("typed") is not True:
                row["schema"] = LEGACY_EVENT_SCHEMA
        store.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        fixture_before = store.read_bytes()

        projection = load_approval_projection(self.contract)

        self.assertEqual(projection["sequence"], 7)
        self.assertEqual(len(projection["requests"]), 3)
        typed = projection["requests"]["apr-222222222222222222222222"]
        self.assertTrue(typed["typed"])
        self.assertEqual(typed["outcome"], "allow")
        self.assertFalse(typed["execution_authorized"])
        self.assertEqual(
            projection["requests"][last["request_id"]]["outcome"],
            "approved",
        )
        self.assertEqual(store.read_bytes(), fixture_before)

    def test_two_sessions_cannot_cross_bind_or_pollute_material_cas(self) -> None:
        self.initialize_contract()
        _proposal, digest = self.human_proposal()
        self.assertEqual(
            self.present_native_proposal(digest, "proposal-owner")["action"],
            "defer",
        )
        material_before = load_contract(self.contract)["runtime"]["material_sequence"]

        denied_write = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "sibling-session",
                "call_id": "sibling-denied-write",
                "cwd": str(self.root),
                "tool_name": "Write",
                "tool_input": {"file_path": "allowed.txt", "content": "blocked\n"},
            },
            phase="started",
            provider="codex",
        )
        read_help = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "sibling-session",
                "call_id": "sibling-read",
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": "codex --help"},
            },
            phase="started",
            provider="codex",
        )

        def observe(event: dict) -> str:
            return GuardianSession(self.contract, provider="codex").observe(event).action

        with ThreadPoolExecutor(max_workers=2) as executor:
            actions = list(executor.map(observe, (denied_write, read_help)))

        self.assertCountEqual(actions, ["deny", "allow"])
        self.assertEqual(
            load_contract(self.contract)["runtime"]["material_sequence"],
            material_before,
        )
        unbound = execute_native_decision(
            self.contract,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="sibling-session",
        )
        self.assertEqual(unbound["status"], "awaiting_human")
        self.assertFalse(unbound["authority_transferred"])
        self.assertEqual(load_native_projection(self.contract)["transactions"], {})

        applied = execute_native_decision(
            self.contract,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="proposal-owner",
        )
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(load_contract(self.contract)["revision"], 2)
        requests = load_approval_projection(self.contract)["requests"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(next(iter(requests.values()))["outcome"], "allow")

    def test_prepared_crash_recovers_one_typed_request_exactly_once(self) -> None:
        self.initialize_contract(owner_session="crash-owner")
        _proposal, digest = self.human_proposal()
        self.present_native_proposal(digest, "crash-owner")

        with mock.patch.object(
            guardian_recovery,
            "_native_decision_failpoint",
            side_effect=lambda stage: (
                (_ for _ in ()).throw(RuntimeError("injected prepared crash"))
                if stage == "after_prepared"
                else None
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected prepared crash"):
                execute_native_decision(
                    self.contract,
                    kind="proposal",
                    decision="approve",
                    target=digest,
                    provider="codex",
                    session_id="crash-owner",
                )

        before = load_native_projection(self.contract)
        transaction_id, prepared = next(iter(before["transactions"].items()))
        self.assertEqual(prepared["stage"], "prepared")
        requests = load_approval_projection(self.contract)["requests"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(next(iter(requests.values()))["outcome"], "allow")

        GuardianSession(
            self.contract,
            provider="codex",
            session_id="crash-owner",
        )
        recovered = load_native_projection(self.contract)["transactions"][transaction_id]
        self.assertEqual(recovered["stage"], "committed")
        self.assertEqual(load_contract(self.contract)["revision"], 2)
        self.assertEqual(len(load_approval_projection(self.contract)["requests"]), 1)
        replay = execute_native_decision(
            self.contract,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="crash-owner",
        )
        self.assertEqual(replay["status"], "already_decided")
        self.assertEqual(load_contract(self.contract)["revision"], 2)
        self.assertEqual(len(load_native_projection(self.contract)["transactions"]), 1)


if __name__ == "__main__":
    unittest.main()
