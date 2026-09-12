from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "scripts" / "kb"
sys.path.insert(0, str(KB))

import grant_broker as broker  # noqa: E402
from native_decision_journal import (  # noqa: E402
    grant_broker_projection,
    pending_grant_broker_transactions,
)
from intent_guardian_parts.approvals import (  # noqa: E402
    evaluate_grant_broker_control_route,
)
from intent_guardian import observe_native_permission_request  # noqa: E402


class Crash(RuntimeError):
    pass


class Magic(dict):
    pass


class GrantBrokerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.contract = self.root / "intent.json"
        self.contract.write_text("{}\n", encoding="utf-8")
        self.serial = 0
        self.specs: dict[str, dict] = {}
        self.dispatches: dict[str, dict] = {}
        self.effect_receipts: dict[str, dict] = {}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def spec(self, suffix: str = "one") -> dict:
        return {
            "schema": broker.PROTOCOL_SCHEMA,
            "provider": "codex",
            "session_id": f"session-{suffix}",
            "task_epoch": "e" * 24,
            "lane": f"lane-{suffix}",
            "subject": {"intent_id": "l3:r2-h02-grant-broker", "revision": 2},
            "capability": {
                "name": "deterministic-local-adapter",
                "risk_class": "external_or_destructive",
                "risk_facts": {
                    "operation": "execute",
                    "local_effect": False,
                    "reversible": False,
                    "external_effect": True,
                    "destructive": False,
                    "integrity_verified": True,
                },
            },
            "effect": {"operation": "publish-fixture", "target": f"fixture-{suffix}"},
            "constraints": {"one_shot": True},
            "world_state": {"revision": 7, "digest": f"world-{suffix}"},
            "verifier": {"kind": "exact-local-readback", "expected": suffix},
            "readable_card": {
                "title": "Publish deterministic fixture",
                "effect": f"fixture-{suffix}",
                "risk": "external write",
            },
            "requested_at": "2026-08-26T01:00:00+00:00",
            "reassess_at": "2026-08-26T01:05:00+00:00",
            "expires_at": "2026-08-26T02:00:00+00:00",
        }

    def current(self, spec: dict, *, drift: bool = False) -> dict:
        value = {
            field: deepcopy(spec[field])
            for field in (
                "provider", "session_id", "task_epoch", "subject", "capability",
                "effect", "constraints", "world_state", "verifier",
            )
        }
        if drift:
            value["world_state"]["revision"] += 1
        return value

    def create(self, suffix: str = "one") -> tuple[dict, str]:
        spec = self.spec(suffix)
        result = broker.create_transaction(self.contract, spec)
        self.specs[result["transaction_id"]] = spec
        return spec, result["transaction_id"]

    def question(self, tx_id: str) -> dict:
        return broker.publish_question(self.contract, tx_id)["question"]

    def observation(self, spec: dict, tx_id: str, question: dict,
                    kind: str = "displayed") -> dict:
        return {
            "schema": broker.OBSERVATION_SCHEMA,
            "transaction_id": tx_id,
            "request_id": question["request_id"],
            "provider": spec["provider"],
            "session_id": spec["session_id"],
            "task_epoch": spec["task_epoch"],
            "kind": kind,
            "observed_at": "2026-08-26T01:01:00+00:00",
            "detail": {"adapter": "deterministic-test"},
        }

    def decision(self, spec: dict, tx_id: str, question: dict,
                 outcome: str = "allow") -> dict:
        return {
            "schema": broker.DECISION_SCHEMA,
            "transaction_id": tx_id,
            "request_id": question["request_id"],
            "receipt_id": f"human-{tx_id}-{outcome}",
            "provider": spec["provider"],
            "session_id": spec["session_id"],
            "task_epoch": spec["task_epoch"],
            "outcome": outcome,
            "decided_at": "2026-08-26T01:02:00+00:00",
            "authority": "human",
            "channel": "native_typed_receipt",
            "question_sha256": question["question_sha256"],
        }

    def effect(self, tx_id: str) -> dict:
        tx = broker.transaction(self.contract, tx_id)
        dispatch = self.dispatches[tx_id]
        receipt = {
            "schema": broker.EFFECT_RECEIPT_SCHEMA,
            "transaction_id": tx_id,
            "dispatch_id": dispatch["dispatch_id"],
            "receipt_id": f"effect-{tx_id}",
            "provider": tx["spec"]["provider"],
            "session_id": tx["spec"]["session_id"],
            "task_epoch": tx["spec"]["task_epoch"],
            "authority_sha256": dispatch["authority_sha256"],
            "status": "succeeded",
            "observed_at": "2026-08-26T01:04:00+00:00",
            "result": {"remote_id": "deterministic-fixture"},
        }
        self.effect_receipts[tx_id] = receipt
        return receipt

    def verifier(self, tx_id: str) -> dict:
        tx = broker.transaction(self.contract, tx_id)
        return {
            "schema": broker.VERIFIER_RECEIPT_SCHEMA,
            "transaction_id": tx_id,
            "effect_receipt_sha256": broker.effect_receipt_identity(
                self.effect_receipts[tx_id]
            ),
            "receipt_id": f"verify-{tx_id}",
            "verifier": deepcopy(self.specs[tx_id]["verifier"]),
            "status": "passed",
            "verified_at": "2026-08-26T01:05:00+00:00",
            "evidence": {"readback": "exact"},
        }

    def prepare(self, through: str, suffix: str) -> tuple[dict, str, dict]:
        order = [
            "question_published", "observation_recorded", "human_decided",
            "grant_consumed", "dispatch_claimed", "effect_receipt_recorded",
            "verifier_receipt_recorded", "settled",
        ]
        spec, tx_id = self.create(suffix)
        question = None
        for stage in order:
            if stage == through:
                break
            question = self.perform(stage, spec, tx_id, question)
        return spec, tx_id, question or broker.transaction(
            self.contract, tx_id
        )["question"]

    def perform(self, stage: str, spec: dict, tx_id: str,
                question: dict | None) -> dict | None:
        if stage == "question_published":
            return self.question(tx_id)
        if question is None:
            question = broker.transaction(self.contract, tx_id)["question"]
        if stage == "observation_recorded":
            broker.record_observation(
                self.contract, self.observation(spec, tx_id, question)
            )
        elif stage == "human_decided":
            broker.record_human_decision(
                self.contract, self.decision(spec, tx_id, question)
            )
        elif stage == "grant_consumed":
            broker.consume_allow(
                self.contract, tx_id, current=self.current(spec),
                now="2026-08-26T01:03:00+00:00",
            )
        elif stage == "dispatch_claimed":
            result = broker.claim_dispatch(
                self.contract, tx_id, consumer_id="worker-a"
            )
            if result["status"] == "claimed":
                self.dispatches[tx_id] = result["dispatch"]
        elif stage == "effect_receipt_recorded":
            broker.record_effect_receipt(self.contract, self.effect(tx_id))
        elif stage == "verifier_receipt_recorded":
            broker.record_verifier_receipt(self.contract, self.verifier(tx_id))
        elif stage == "settled":
            broker.settle(
                self.contract, tx_id, now="2026-08-26T01:06:00+00:00"
            )
        else:
            self.fail(stage)
        return question

    def assert_non_executable_readback(self, value: object) -> None:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
        self.assertNotIn('"execution_authorized":true', encoded)
        self.assertNotIn("sulde-grant-broker-dispatch-intent-v1", encoded)
        self.assertNotIn('"authority_sha256"', encoded)
        self.assertNotIn('"grant_consumption"', encoded)
        self.assertNotIn('"effect":{"operation"', encoded)

    def test_typed_end_to_end_transaction_and_no_second_policy_decision(self) -> None:
        spec, tx_id = self.create()
        question = self.question(tx_id)
        self.assertEqual(
            question["adapter"]["choices"],
            ["allow", "deny", "inspect_diff", "later"],
        )
        self.assertFalse(question["adapter"]["text_response_authoritative"])
        broker.record_observation(
            self.contract, self.observation(spec, tx_id, question)
        )
        broker.record_human_decision(
            self.contract, self.decision(spec, tx_id, question)
        )
        consumed = broker.consume_allow(
            self.contract, tx_id, current=self.current(spec),
            now="2026-08-26T01:03:00+00:00",
        )
        self.assertEqual(consumed["status"], "consumed")
        dispatch = broker.claim_dispatch(
            self.contract, tx_id, consumer_id="worker-a"
        )
        self.dispatches[tx_id] = dispatch["dispatch"]
        self.assertTrue(dispatch["dispatch"]["execution_authorized"])
        self.assertFalse(dispatch["dispatch"]["default_policy_recheck_required"])
        self.assertEqual(
            broker.next_step(
                self.contract, tx_id, now="2026-08-26T01:04:00+00:00"
            )["status"],
            "await_effect_receipt",
        )
        self.assertEqual(
            broker.settle(
                self.contract, tx_id, now="2026-08-26T01:04:00+00:00"
            )["status"],
            "not_ready",
        )
        broker.record_effect_receipt(self.contract, self.effect(tx_id))
        broker.record_verifier_receipt(self.contract, self.verifier(tx_id))
        settled = broker.settle(
            self.contract, tx_id, now="2026-08-26T01:06:00+00:00"
        )
        self.assertEqual(settled["status"], "succeeded")
        self.assertEqual(len(broker.pending(self.contract)), 0)

    def test_observations_timeout_silence_chat_and_magic_text_never_decide(self) -> None:
        spec, tx_id = self.create("observations")
        question = self.question(tx_id)
        for kind in (
            "displayed", "timeout", "silence", "ordinary_chat", "fixed_phrase",
            "copied_digest", "retry", "reprobe", "inspect_diff", "later",
        ):
            broker.record_observation(
                self.contract, self.observation(spec, tx_id, question, kind)
            )
        tx = broker.transaction(self.contract, tx_id)
        self.assertIsNone(tx["decision"])
        step = broker.next_step(
            self.contract, tx_id, now="2026-08-26T01:06:00+00:00"
        )
        self.assertEqual(step["status"], "await_human_decision")
        self.assertTrue(step["reassess_due"])
        expired = broker.settle(
            self.contract, tx_id, now="2026-08-26T02:00:00+00:00"
        )
        self.assertEqual(expired["status"], "expired")

    def test_deny_is_durable_idempotent_and_never_lost(self) -> None:
        spec, tx_id = self.create("deny")
        question = self.question(tx_id)
        broker.record_observation(
            self.contract, self.observation(spec, tx_id, question)
        )
        decision = self.decision(spec, tx_id, question, "deny")
        first = broker.record_human_decision(self.contract, decision)
        second = broker.record_human_decision(self.contract, decision)
        conflict = deepcopy(decision)
        conflict["outcome"] = "allow"
        self.assertEqual(first["status"], "decided")
        self.assertEqual(second["status"], "duplicate")
        self.assertEqual(
            broker.record_human_decision(self.contract, conflict)["status"],
            "conflict",
        )
        self.assertEqual(
            broker.next_step(
                self.contract, tx_id, now="2026-08-26T01:03:00+00:00"
            )["status"],
            "settle_denied",
        )
        self.assertEqual(
            broker.settle(
                self.contract, tx_id, now="2026-08-26T01:03:00+00:00"
            )["status"],
            "denied",
        )

    def test_identity_world_drift_and_exact_json_fail_closed(self) -> None:
        spec, tx_id = self.create("hostile")
        question = self.question(tx_id)
        broker.record_observation(
            self.contract, self.observation(spec, tx_id, question)
        )
        decision = self.decision(spec, tx_id, question)
        for field, value in (
            ("provider", "claude"), ("session_id", "foreign"),
            ("task_epoch", "f" * 24), ("request_id", "gbr-foreign"),
        ):
            changed = deepcopy(decision)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(
                broker.GrantBrokerError
            ):
                broker.record_human_decision(self.contract, changed)
        extra = deepcopy(decision)
        extra["unexpected"] = True
        with self.assertRaises(broker.GrantBrokerError):
            broker.record_human_decision(self.contract, extra)
        with self.assertRaises(broker.GrantBrokerError):
            broker.record_human_decision(self.contract, Magic(decision))
        broker.record_human_decision(self.contract, decision)
        drift = broker.consume_allow(
            self.contract, tx_id, current=self.current(spec, drift=True),
            now="2026-08-26T01:03:00+00:00",
        )
        self.assertEqual(drift["status"], "fresh_decision_required")
        self.assertTrue(drift["world_diff"])

    def test_two_concurrent_consumers_and_dispatchers_have_one_winner(self) -> None:
        spec, tx_id = self.create("race")
        question = self.question(tx_id)
        broker.record_observation(
            self.contract, self.observation(spec, tx_id, question)
        )
        broker.record_human_decision(
            self.contract, self.decision(spec, tx_id, question)
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(
                    broker.consume_allow, self.contract, tx_id,
                    current=self.current(spec),
                    now="2026-08-26T01:03:00+00:00",
                ),
                pool.submit(
                    broker.consume_allow, self.contract, tx_id,
                    current=self.current(spec),
                    now="2026-08-26T01:03:00+00:00",
                ),
            ]
            statuses = sorted(result.result()["status"] for result in futures)
        self.assertEqual(statuses, ["already_consumed", "consumed"])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [
                pool.submit(
                    broker.claim_dispatch, self.contract, tx_id,
                    consumer_id=consumer,
                )
                for consumer in ("worker-a", "worker-b")
            ]
            dispatch_statuses = sorted(item.result()["status"] for item in results)
        self.assertEqual(dispatch_statuses, ["claimed", "lost_race"])

    def test_dispatch_claim_replay_and_all_readbacks_are_non_executable(self) -> None:
        spec, tx_id = self.create("dispatch-replay")
        question = self.question(tx_id)
        broker.record_observation(
            self.contract, self.observation(spec, tx_id, question)
        )
        broker.record_human_decision(
            self.contract, self.decision(spec, tx_id, question)
        )
        consumed = broker.consume_allow(
            self.contract, tx_id, current=self.current(spec),
            now="2026-08-26T01:03:00+00:00",
        )
        self.assertNotIn("authority", consumed)

        first = broker.claim_dispatch(
            self.contract, tx_id, consumer_id="worker-a"
        )
        self.assertEqual(first["status"], "claimed")
        self.assertTrue(first["dispatch"]["execution_authorized"])
        dispatch_id = first["dispatch"]["dispatch_id"]
        same = broker.claim_dispatch(
            self.contract, tx_id, consumer_id="worker-a"
        )
        loser = broker.claim_dispatch(
            self.contract, tx_id, consumer_id="worker-b"
        )
        self.assertEqual(same["status"], "already_claimed")
        self.assertEqual(loser["status"], "lost_race")
        self.assertNotIn("dispatch", same)
        self.assertNotIn("dispatch", loser)
        self.assertEqual(
            same["dispatch_reprobe"]["downstream_idempotency_key"], dispatch_id
        )
        self.assertFalse(same["dispatch_reprobe"]["execution_authorized"])

        step = broker.next_step(
            self.contract, tx_id, now="2026-08-26T01:04:00+00:00"
        )
        self.assertEqual(step["status"], "await_effect_receipt")
        self.assertEqual(step["dispatch_reprobe"]["dispatch_id"], dispatch_id)

        readbacks = [
            same,
            loser,
            step,
            broker.transaction(self.contract, tx_id),
            broker.pending(self.contract),
            broker.load_projection_read_only(self.contract),
            grant_broker_projection(self.contract),
            pending_grant_broker_transactions(self.contract),
        ]
        for readback in readbacks:
            self.assert_non_executable_readback(readback)

        crash_spec, crash_tx = self.create("dispatch-crash")
        crash_question = self.question(crash_tx)
        broker.record_observation(
            self.contract,
            self.observation(crash_spec, crash_tx, crash_question),
        )
        broker.record_human_decision(
            self.contract,
            self.decision(crash_spec, crash_tx, crash_question),
        )
        broker.consume_allow(
            self.contract, crash_tx, current=self.current(crash_spec),
            now="2026-08-26T01:03:00+00:00",
        )

        def fail_after_dispatch(boundary: str) -> None:
            if boundary == "after:dispatch_claimed":
                raise Crash(boundary)

        with mock.patch.object(
            broker, "_failpoint", side_effect=fail_after_dispatch
        ):
            with self.assertRaises(Crash):
                broker.claim_dispatch(
                    self.contract, crash_tx, consumer_id="worker-crash"
                )
        retry = broker.claim_dispatch(
            self.contract, crash_tx, consumer_id="worker-crash"
        )
        self.assertEqual(retry["status"], "already_claimed")
        self.assert_non_executable_readback(retry)

    @unittest.skipUnless(
        sys.platform == "darwin" and Path("/var").is_symlink(),
        "requires the macOS /var canonical alias",
    )
    def test_darwin_var_folders_alias_reuses_one_canonical_transaction(
        self,
    ) -> None:
        system_temp = Path(
            subprocess.check_output(
                ["getconf", "DARWIN_USER_TEMP_DIR"],
                text=True,
                encoding="utf-8",
                errors="replace",
            ).strip()
        )
        self.assertEqual(system_temp.parts[:3], ("/", "var", "folders"))
        self.assertEqual(
            system_temp.resolve(strict=True).parts[:3],
            ("/", "private", "var"),
        )
        temporary = None
        actual_system_alias = True
        try:
            temporary = tempfile.TemporaryDirectory(
                prefix="h02-var-alias-", dir=system_temp
            )
            lexical_root = Path(temporary.name)
        except PermissionError:
            if ".codex-agent/.native-command-scratch" not in os.environ.get(
                "TMPDIR", ""
            ):
                raise
            actual_system_alias = False
            canonical_root = self.root / "private" / "var" / "folders"
            canonical_root.mkdir(parents=True)
            lexical_alias = self.root / "var"
            lexical_alias.symlink_to(
                self.root / "private" / "var", target_is_directory=True
            )
            lexical_root = lexical_alias / "folders" / "h02-var-alias"
            lexical_root.mkdir()
        try:
            lexical_contract = lexical_root / "intent.json"
            lexical_contract.write_text("{}\n", encoding="utf-8")
            canonical_contract = lexical_contract.resolve(strict=True)
            self.assertNotEqual(lexical_contract, canonical_contract)
            if actual_system_alias:
                self.assertEqual(
                    canonical_contract.parts[:3], ("/", "private", "var")
                )
            else:
                self.assertEqual(
                    canonical_contract.parent,
                    lexical_root.resolve(strict=True),
                )

            lexical_ledger = broker.journal_path(lexical_contract)
            canonical_ledger = broker.journal_path(canonical_contract)
            self.assertEqual(lexical_ledger, canonical_ledger)
            self.assertEqual(
                lexical_ledger.with_name(f".{lexical_ledger.name}.lock"),
                canonical_ledger.with_name(f".{canonical_ledger.name}.lock"),
            )

            prior_contract = self.contract
            self.contract = lexical_contract
            try:
                spec = self.spec("darwin-var-alias")
                created = broker.create_transaction(lexical_contract, spec)
                tx_id = created["transaction_id"]
                self.specs[tx_id] = spec
                replayed = broker.create_transaction(canonical_contract, spec)
                self.assertEqual(created["status"], "created")
                self.assertEqual(replayed["status"], "already_created")
                self.assertEqual(replayed["transaction_id"], tx_id)

                question = broker.publish_question(
                    canonical_contract, tx_id
                )["question"]
                broker.record_observation(
                    lexical_contract,
                    self.observation(spec, tx_id, question),
                )
                broker.record_human_decision(
                    canonical_contract,
                    self.decision(spec, tx_id, question),
                )
                broker.consume_allow(
                    lexical_contract,
                    tx_id,
                    current=self.current(spec),
                    now="2026-08-26T01:03:00+00:00",
                )
                claimed = broker.claim_dispatch(
                    canonical_contract, tx_id, consumer_id="worker-alias"
                )
                self.dispatches[tx_id] = claimed["dispatch"]
                broker.record_effect_receipt(
                    lexical_contract, self.effect(tx_id)
                )
                broker.record_verifier_receipt(
                    canonical_contract, self.verifier(tx_id)
                )
                settled = broker.settle(
                    lexical_contract,
                    tx_id,
                    now="2026-08-26T01:06:00+00:00",
                )
            finally:
                self.contract = prior_contract

            self.assertEqual(settled["status"], "succeeded")
            lexical_state = broker.load_projection_read_only(lexical_contract)
            canonical_state = broker.load_projection_read_only(canonical_contract)
            self.assertEqual(lexical_state, canonical_state)
            self.assertEqual(
                lexical_state["transactions"][tx_id]["settlement"]["status"],
                "succeeded",
            )
            events = [
                json.loads(line)["event"]
                for line in canonical_ledger.read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertEqual(events.count("transaction_created"), 1)
            self.assertEqual(events.count("settled"), 1)
        finally:
            if temporary is not None:
                temporary.cleanup()

    def test_no_follow_ledger_and_lock_reject_hostile_files_before_write(
        self,
    ) -> None:
        def contract_for(label: str) -> Path:
            parent = self.root / label
            parent.mkdir()
            contract = parent / "intent.json"
            contract.write_text("{}\n", encoding="utf-8")
            return contract

        for kind in ("ledger", "lock"):
            with self.subTest(attack=f"{kind}-symlink"):
                contract = contract_for(f"{kind}-symlink")
                ledger = broker.journal_path(contract)
                leaf = ledger if kind == "ledger" else ledger.with_name(
                    f".{ledger.name}.lock"
                )
                foreign = contract.parent / "foreign"
                foreign.write_bytes(b"FOREIGN-SYMLINK")
                os.chmod(foreign, 0o600)
                leaf.symlink_to(foreign)
                before = foreign.read_bytes()
                with self.assertRaises(broker.GrantBrokerError):
                    broker.create_transaction(contract, self.spec(f"{kind}-symlink"))
                self.assertEqual(foreign.read_bytes(), before)

        for kind in ("ledger", "lock"):
            with self.subTest(attack=f"{kind}-hardlink"):
                contract = contract_for(f"{kind}-hardlink")
                ledger = broker.journal_path(contract)
                leaf = ledger if kind == "ledger" else ledger.with_name(
                    f".{ledger.name}.lock"
                )
                foreign = contract.parent / "foreign"
                foreign.write_bytes(b"FOREIGN-HARDLINK")
                os.chmod(foreign, 0o600)
                os.link(foreign, leaf)
                before = foreign.read_bytes()
                with self.assertRaisesRegex(
                    broker.GrantBrokerError, "exactly one hard link"
                ):
                    broker.create_transaction(contract, self.spec(f"{kind}-hardlink"))
                self.assertEqual(foreign.read_bytes(), before)

        for kind in ("ledger", "lock"):
            with self.subTest(attack=f"{kind}-nonregular"):
                contract = contract_for(f"{kind}-nonregular")
                ledger = broker.journal_path(contract)
                leaf = ledger if kind == "ledger" else ledger.with_name(
                    f".{ledger.name}.lock"
                )
                leaf.mkdir()
                with self.assertRaises(broker.GrantBrokerError):
                    broker.create_transaction(
                        contract, self.spec(f"{kind}-nonregular")
                    )

        contract = contract_for("broad-mode")
        ledger = broker.journal_path(contract)
        ledger.write_bytes(b"")
        os.chmod(ledger, 0o644)
        with self.assertRaisesRegex(broker.GrantBrokerError, "broader than 0600"):
            broker.create_transaction(contract, self.spec("broad-mode"))

        contract = contract_for("stable-read-drift")
        created = broker.create_transaction(
            contract, self.spec("stable-read-drift")
        )
        ledger = broker.journal_path(contract)
        replacement = contract.parent / "replacement"
        replacement.write_bytes(ledger.read_bytes())
        os.chmod(replacement, 0o600)
        displaced = contract.parent / "displaced"
        read_all = broker._read_all

        def replace_after_read(descriptor: int) -> bytes:
            data = read_all(descriptor)
            ledger.rename(displaced)
            replacement.rename(ledger)
            return data

        with mock.patch.object(
            broker, "_read_all", side_effect=replace_after_read
        ):
            with self.assertRaisesRegex(
                broker.GrantBrokerError, "pathname identity changed"
            ):
                broker.transaction(contract, created["transaction_id"])

        contract = contract_for("read-only-append")
        first = broker.create_transaction(contract, self.spec("read-only-one"))
        self.assertEqual(first["status"], "created")
        ledger = broker.journal_path(contract)
        before = ledger.read_bytes()
        os.chmod(ledger, 0o400)
        try:
            with self.assertRaises(broker.GrantBrokerError):
                broker.create_transaction(contract, self.spec("read-only-two"))
            self.assertEqual(ledger.read_bytes(), before)
        finally:
            os.chmod(ledger, 0o600)

    def test_all_durable_boundaries_recover_before_and_after_crash(self) -> None:
        stages = [
            "question_published", "observation_recorded", "human_decided",
            "grant_consumed", "dispatch_claimed", "effect_receipt_recorded",
            "verifier_receipt_recorded", "settled",
        ]
        for stage in stages:
            for side in ("before", "after"):
                with self.subTest(stage=stage, side=side):
                    suffix = f"{stage}-{side}"
                    spec, tx_id, question = self.prepare(stage, suffix)

                    def fail(boundary: str) -> None:
                        if boundary == f"{side}:{stage}":
                            raise Crash(boundary)

                    with mock.patch.object(broker, "_failpoint", side_effect=fail):
                        with self.assertRaises(Crash):
                            self.perform(stage, spec, tx_id, question)
                    self.perform(stage, spec, tx_id, question)
                    projection = broker.load_projection_read_only(self.contract)
                    events = [
                        line["event"] for line in map(
                            json.loads,
                            broker.journal_path(self.contract).read_text(
                                encoding="utf-8"
                            ).splitlines(),
                        )
                        if line["payload"]["transaction_id"] == tx_id
                    ]
                    self.assertEqual(events.count(stage), 1)
                    tx = projection["transactions"][tx_id]
                    displays = [
                        row for row in tx["observations"]
                        if row["observation"]["kind"] == "displayed"
                    ]
                    self.assertLessEqual(len(displays), 1)

    def test_control_routes_are_narrow_sealed_and_checked_before_policy(self) -> None:
        spec, tx_id = self.create("route")
        self.question(tx_id)
        route = broker.seal_control_route(self.contract, tx_id, kind="question")
        payload = {
            "schema": "sulde-native-grant-broker-control-v1",
            "contract": str(self.contract),
            "route": route,
            "provider": spec["provider"],
            "session_id": spec["session_id"],
            "task_epoch": spec["task_epoch"],
        }
        allowed = evaluate_grant_broker_control_route(payload)
        self.assertEqual(allowed["action"], "allow_control_route")
        self.assertFalse(allowed["ordinary_pretool_policy_required"])
        self.assertEqual(
            observe_native_permission_request(payload)["action"],
            "allow_control_route",
        )
        for mutation in (
            {"destructive": True}, {"session_id": "foreign"},
            {"operation": "delete"}, {"source_event_sha256": "sha256:" + "0" * 64},
        ):
            forged = deepcopy(payload)
            forged["route"].update(mutation)
            self.assertEqual(
                evaluate_grant_broker_control_route(forged)["action"], "deny"
            )
        self.assertEqual(
            evaluate_grant_broker_control_route({"schema": "bad"})["action"],
            "deny",
        )

    def test_tamper_partial_missing_source_and_partial_write_fail_closed(self) -> None:
        _spec, tx_id = self.create("ledger")
        self.question(tx_id)
        path = broker.journal_path(self.contract)
        original = path.read_bytes()
        tampered = original.replace(b'"lane":"lane-ledger"', b'"lane":"lane-forged"')
        path.write_bytes(tampered)
        with self.assertRaisesRegex(broker.GrantBrokerError, "tampered"):
            broker.load_projection_read_only(self.contract)
        path.write_bytes(original + b'{"torn":')
        with self.assertRaisesRegex(broker.GrantBrokerError, "torn trailing record"):
            broker.load_projection_read_only(self.contract)
        path.write_bytes(original)
        first_end = original.index(b"\n") + 1
        path.write_bytes(original[first_end:])
        with self.assertRaises(broker.GrantBrokerError):
            broker.load_projection_read_only(self.contract)

        other = self.root / "partial.json"
        other.write_text("{}\n", encoding="utf-8")
        with mock.patch.object(broker, "_write_all", side_effect=OSError("read-only")):
            with self.assertRaisesRegex(broker.GrantBrokerError, "read-only"):
                broker.create_transaction(other, self.spec("read-only"))
        self.assertEqual(broker.journal_path(other).read_bytes(), b"")

    def test_replacement_and_wrong_effect_receipt_are_bounded(self) -> None:
        _old_spec, old = self.create("old")
        _new_spec, new = self.create("new")
        self.assertEqual(
            broker.replace_transaction(
                self.contract, old, new, now="2026-08-26T01:10:00+00:00"
            )["status"],
            "replaced",
        )
        spec, tx_id, question = self.prepare("effect_receipt_recorded", "receipt")
        receipt = self.effect(tx_id)
        receipt["authority_sha256"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(broker.GrantBrokerError, "authority"):
            broker.record_effect_receipt(self.contract, receipt)
        self.assertEqual(
            broker.next_step(
                self.contract, tx_id, now="2026-08-26T01:05:00+00:00"
            )["status"],
            "await_effect_receipt",
        )


if __name__ == "__main__":
    unittest.main()
