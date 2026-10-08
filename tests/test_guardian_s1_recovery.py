"""Bounded SSH conflict recovery: normal controls then historical injection."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from unittest import mock

ROOT = Path(os.environ.get("S1_SOURCE_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "scripts/kb"))
import intervention as store

SSH = ("ssh -F /dev/null -o BatchMode=yes -o PermitLocalCommand=no "
       "-o StrictHostKeyChecking=yes -o UpdateHostKeys=no ops@192.0.2.10 ")
COMMAND = SSH + "'/bin/mkdir -p -- /opt/app'"


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="guardian-s1-recovery-")
        self.root = Path(self.temp.name)
        self.path = self.root / "intent.json"
        self.path.write_text("{}")
        self.env = mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(self.root / "kb"),
                                               "SULDE_NOTIFY": "off", "PYTHONDONTWRITEBYTECODE": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def unknown(self, suffix="one", *, abort=True):
        target = "[command:" + hashlib.sha256(suffix.encode()).hexdigest()[:16] + "]"
        a = store.begin_attempt(self.path, intent_id="repair", intent_revision=1,
            fingerprint="a" * 64, source_event_id=suffix, capability="tool:Bash",
            target=target, resource_key=store.canonical_resource_key(target, kind="opaque"),
            resource_context={"schema": "exact", "value": target}, effect="external_write",
            provider="codex", session_id="old", idempotency_key=suffix, verification_kind="unsupported")
        store.mark_attempt_result(self.path, a["attempt_id"], success=True)
        if abort:
            i = store.mark_attempt_unknown(self.path, a["attempt_id"], reason="lost verifier")
            store.resolve_intervention(self.path, i["intervention_id"], decision="abort", evidence="stop retries")
        return store.load_projection(self.path)["attempts"][a["attempt_id"]]

    def event(self):
        # Fixture uses the protocol representation independently of the new
        # producer, so baseline/candidate use identical assertions and inputs.
        target = 'ssh-request-v1:["192.0.2.10","ops",22,"/opt/app"]'
        key = "v2:opaque:" + target
        context = {"schema": "exact", "value": target}
        return {"phase": "started", "kind": "tool", "provider": "codex", "session_id": "current",
                "capability": "tool:Bash", "effect": "external_write", "target": target,
                "effect_resource_key": key, "effect_resource_context": context,
                "arguments_digest": "b" * 64,
                "remote_request": {"target": target, "resource_key": key,
                                   "effect": "external_write", "operation": "mkdir_p"}}

    def test_normal_no_debt_then_old_opaque_must_block_precise_ssh(self):
        event = self.event()
        self.assertIsNone(store.material_event_blocker(self.path, event))
        a = self.unknown()
        blocker = store.material_event_blocker(self.path, event)
        self.assertIsNotNone(blocker)
        self.assertEqual(blocker["attempt_id"], a["attempt_id"])
        self.assertEqual(blocker["match_reason"], "resource_identity_unproved")

    def test_read_probe_does_not_settle_old_effect_or_enable_write(self):
        a = self.unknown()
        before = store.event_store_path(self.path).read_bytes()
        event = self.event()
        self.assertIsNone(store.material_event_blocker(self.path, {**event, "effect": "read"}))
        self.assertIsNotNone(store.material_event_blocker(self.path, event))
        self.assertEqual(store.event_store_path(self.path).read_bytes(), before)
        self.assertEqual(store.load_projection(self.path)["attempts"][a["attempt_id"]]["state"], "unknown")

    def test_runtime_observation_does_not_stale_risk_review(self):
        a = self.unknown()
        event = self.event()
        review = store.effect_risk_review_context(self.path, event)
        self.path.write_text('{"runtime":{"observations":3,"pending_native_question":"fixture"}}')
        self.assertTrue(store.effect_risk_acceptance_matches(self.path,
            {**event, "intent_revision": 1, "task_epoch": "enriched", "fingerprint": "f" * 64,
             "effect_operation_fingerprint": "e" * 64}, review))
        self.assertEqual(store.load_projection(self.path)["attempts"][a["attempt_id"]]["state"], "unknown")

    def test_scope_risk_review_does_not_require_fake_verifier_or_grant(self):
        a = self.unknown()
        event = self.event()
        before = store.event_store_path(self.path).read_bytes()
        review = store.effect_risk_review_context(self.path, event)
        self.assertEqual(review["attempt_id"], a["attempt_id"])
        self.assertFalse(review["effect_verified"])
        self.assertFalse(review["execution_authorized"])
        self.assertTrue(store.effect_risk_acceptance_matches(self.path, event, review))
        self.assertIsNotNone(store.material_event_blocker(self.path, event))
        with self.assertRaisesRegex(store.InterventionError, "verification basis"):
            store.prepare_effect_recovery(self.path, a["attempt_id"],
                expected_binding_sha256=store.effect_recovery_readiness(a)["binding_sha256"])
        self.assertEqual(store.event_store_path(self.path).read_bytes(), before)

    def native_risk_dispatch(self, *, authorize=True):
        import grant_broker as broker
        from decision_kernel import event_binding, observe_grant_prompt
        from intent_guardian import native_decision_context, execute_native_decision
        from intent_guardian_parts.state import default_contract, write_contract, event_fingerprint
        contract = default_contract(intent_id="repair", objective="scoped repair",
            acceptance_criteria=["preserve old effect"], workspace=self.root, mode="enforce",
            confirmed_by="human-readable-proposal-approval")
        write_contract(self.path, contract)
        old = self.unknown()
        event = {**self.event(), "event_id": "new-event", "call_id": "new-call", "action": "Bash"}
        event["fingerprint"] = event_fingerprint(event)
        binding = event_binding(contract, event)
        binding["constraints"]["effect_risk_review"] = store.effect_risk_review_context(self.path, event)
        now = datetime.now(timezone.utc)
        spec = {"schema": broker.PROTOCOL_SCHEMA, **binding, "lane": "fixture-native-risk",
                "readable_card": {"effect": "mkdir exact path despite unknown history"},
                "requested_at": now.isoformat(), "reassess_at": (now + timedelta(minutes=5)).isoformat(),
                "expires_at": (now + timedelta(minutes=20)).isoformat()}
        txid = broker.create_transaction(self.path, spec)["transaction_id"]
        broker.publish_question(self.path, txid)
        tx = broker.transaction(self.path, txid)
        if not authorize:
            return old, event, txid, {"execution_authorized": True, "transaction_id": txid}
        native_decision_context(self.path, kind="grant", decision="allow", target=txid,
            provider="codex", session_id="current")
        observe_grant_prompt(self.path, tx)
        result = execute_native_decision(self.path, kind="grant", decision="allow", target=txid,
            provider="codex", session_id="current")
        self.assertEqual(result["status"], "grant_recorded")
        consumed = broker.consume_allow(self.path, txid, current=binding, now=datetime.now(timezone.utc).isoformat())
        self.assertEqual(consumed["status"], "consumed")
        dispatch = broker.claim_dispatch(self.path, txid, consumer_id=event["event_id"])["dispatch"]
        return old, event, txid, dispatch

    def begin_with_risk(self, event, txid, dispatch, *, key="new-dispatch"):
        return store.begin_attempt(self.path, intent_id="repair", intent_revision=1,
            fingerprint=event["fingerprint"], operation_arguments_digest=event["arguments_digest"],
            source_event_id=event["event_id"], capability=event["capability"],
            target=event["target"], resource_key=event["effect_resource_key"],
            resource_context=event["effect_resource_context"], effect=event["effect"],
            provider=event["provider"], session_id=event["session_id"], idempotency_key=key,
            risk_grant_transaction_id=txid, risk_event=event, risk_dispatch=dispatch)

    def test_native_consumed_risk_dispatch_links_once_and_preserves_old_unknown(self):
        old, event, txid, dispatch = self.native_risk_dispatch()
        before = store.event_store_path(self.path).read_bytes()
        new = self.begin_with_risk(event, txid, dispatch)
        self.assertEqual(new["state"], "dispatched")
        self.assertEqual(new["risk_grant"]["accepted_attempt_id"], old["attempt_id"])
        self.assertNotIn("execution_authorized", json.dumps(new["risk_grant"]))
        self.assertEqual(store.load_projection(self.path)["attempts"][old["attempt_id"]]["state"], "unknown")
        self.assertTrue(store.event_store_path(self.path).read_bytes().startswith(before))
        self.assertEqual(self.begin_with_risk(event, txid, dispatch), new)
        with self.assertRaisesRegex(store.InterventionError, "already linked"):
            self.begin_with_risk(event, txid, dispatch, key="duplicate-new-attempt")
        contract = json.loads(self.path.read_text())
        contract["revision"] += 1
        self.path.write_text(json.dumps(contract))
        self.assertEqual(store.load_projection(self.path)["attempts"][new["attempt_id"]]["state"], "dispatched")

    def test_forged_dispatch_and_wrong_call_never_create_attempt(self):
        _, event, txid, dispatch = self.native_risk_dispatch()
        before = store.event_store_path(self.path).read_bytes()
        forged = {**dispatch, "consumer_id": "forged"}
        for event_value, tx_value, dispatch_value in [(event, "missing-tx", dispatch),
                (event, txid, forged), ({**event, "event_id": "another-call"}, txid, dispatch),
                ({**event, "arguments_digest": "c" * 64}, txid, dispatch)]:
            with self.assertRaises(store.InterventionError):
                self.begin_with_risk(event_value, tx_value, dispatch_value)
        self.assertEqual(store.event_store_path(self.path).read_bytes(), before)

    def test_question_without_native_receipt_is_never_dispatch_authority(self):
        _, event, txid, dispatch = self.native_risk_dispatch(authorize=False)
        before = store.event_store_path(self.path).read_bytes()
        with self.assertRaisesRegex(store.InterventionError, "native consumed dispatch"):
            self.begin_with_risk(event, txid, dispatch)
        self.assertEqual(store.event_store_path(self.path).read_bytes(), before)

    def test_consumed_risk_with_second_blocker_or_contract_drift_fails_closed(self):
        _, event, txid, dispatch = self.native_risk_dispatch()
        contract = json.loads(self.path.read_text())
        self.path.write_text(json.dumps({**contract, "revision": 2}))
        with self.assertRaisesRegex(store.InterventionError, "intent changed"):
            self.begin_with_risk(event, txid, dispatch)
        self.path.write_text(json.dumps(contract))
        self.unknown("second")
        before = store.event_store_path(self.path).read_bytes()
        with self.assertRaisesRegex(store.InterventionError, "snapshot changed"):
            self.begin_with_risk(event, txid, dispatch)
        self.assertEqual(store.event_store_path(self.path).read_bytes(), before)

    def test_replay_rejects_risk_link_or_source_rebinding(self):
        _, event, txid, dispatch = self.native_risk_dispatch()
        self.begin_with_risk(event, txid, dispatch)
        original = [json.loads(row) for row in store.event_store_path(self.path).read_text().splitlines()]
        for name in ("accepted_attempt_id", "review_binding_sha256", "source_event_id"):
            rows = deepcopy(original)
            rows[-1]["risk_grant"][name] = "forged"
            rows[-1].pop("event_id")
            rows[-1]["event_id"] = hashlib.sha256(store._canonical(rows[-1]).encode()).hexdigest()
            with self.assertRaises(store.InterventionError):
                store.replay(self.path, rows)

    def test_offline_risk_archive_without_broker_proof_fails_closed(self):
        _, event, txid, dispatch = self.native_risk_dispatch()
        self.begin_with_risk(event, txid, dispatch)
        before = store.event_store_path(self.path).read_bytes()
        archive = store.archive_store(self.path, self.root / "archives", slug="risk-fixture")
        with self.assertRaisesRegex(store.InterventionError, "contract ledger"):
            store.load_archived_projection(archive)
        self.assertEqual(store.event_store_path(self.path).read_bytes(), before)

    def test_verifying_unsupported_attempt_can_be_reviewed_without_transition(self):
        a = self.unknown(abort=False)
        self.assertEqual(a["state"], "verifying")
        before = store.event_store_path(self.path).read_bytes()
        review = store.effect_risk_review_context(self.path, self.event())
        self.assertEqual(review["attempt_state"], "verifying")
        self.assertEqual(store.load_projection(self.path)["attempts"][a["attempt_id"]]["state"], "verifying")
        self.assertEqual(store.event_store_path(self.path).read_bytes(), before)

    def test_risk_review_rejects_lane_arguments_contract_and_debt_drift(self):
        self.unknown()
        event = self.event()
        review = store.effect_risk_review_context(self.path, event)
        for field, value in [("session_id", "other"), ("provider", "claude"),
                             ("arguments_digest", "c" * 64), ("target", "/other"),
                             ("effect", "destructive"), ("sensitive_input", True)]:
            with self.subTest(field=field):
                self.assertFalse(store.effect_risk_acceptance_matches(self.path, {**event, field: value}, review))
        for changed_contract in [{"revision": 2}, {"acceptance_criteria": ["new scope"]},
                                 {"skills": {"allow": ["new"]}}, {"mcp": {"unknown_effect": "allow"}}]:
            self.path.write_text(json.dumps(changed_contract))
            self.assertFalse(store.effect_risk_acceptance_matches(self.path, event, review))
        self.path.write_text("{}")
        self.unknown("second")
        self.assertFalse(store.effect_risk_acceptance_matches(self.path, event, review))

    def test_literal_identity_not_remote_object_or_alias_proof(self):
        from intent_guardian_parts.remote_identity import ssh_resource_identity
        one = ssh_resource_identity({"host": "192.0.2.10", "user": "ops", "port": 22}, "/opt/app")
        a = store.begin_attempt(self.path, intent_id="repair", intent_revision=1,
            fingerprint="d" * 64, source_event_id="remote", capability="tool:Bash",
            target=one["target"], resource_key=one["resource_key"], resource_context=one["resource_context"],
            effect="external_write", provider="codex", session_id="old", idempotency_key="remote",
            verification_kind="unsupported")
        for host, user, path in [("192.0.2.10", "ops", "/opt/app"),
                                  ("192.0.2.10", "root", "/alias"), ("192.0.2.20", "ops", "/opt/app")]:
            identity = ssh_resource_identity({"host": host, "user": user, "port": 22}, path)
            self.assertEqual(store.settlement_resource_match(a, target=identity["target"],
                resource_key=identity["resource_key"], resource_context=identity["resource_context"]), "unproved")
            self.assertTrue(store.blocker_resource_match(a, target=identity["target"],
                resource_key=identity["resource_key"], resource_context=identity["resource_context"]))
        local = str(self.root / "output")
        self.assertFalse(store.blocker_resource_match(a, target=local,
            resource_key=store.canonical_resource_key(local, kind="path"), resource_base=str(self.root)))

    def test_closed_material_grammar_and_redacted_telemetry(self):
        from intent_guardian_parts.remote_identity import ssh_material_request
        request = ssh_material_request(COMMAND)
        self.assertIsNotNone(request)
        self.assertEqual(request["target"], self.event()["target"])
        self.assertNotIn("192.0.2.10", json.dumps(request["telemetry"]))
        self.assertNotIn("/opt/app", json.dumps(request["telemetry"]))
        for command in [COMMAND.replace("-F /dev/null ", ""),
                        COMMAND.replace("UpdateHostKeys=no", "UpdateHostKeys=yes"),
                        COMMAND.replace("192.0.2.10", "host-alias"),
                        COMMAND.replace("/opt/app", "/"),
                        COMMAND.replace("/opt/app", "/opt/../app"),
                        COMMAND.replace("/bin/mkdir", "mkdir"),
                        COMMAND + " && echo done", COMMAND.replace("mkdir -p", "rm -rf"),
                        COMMAND.replace("-F /dev/null", "-F /dev/null -o ProxyCommand=evil"),
                        COMMAND.replace("/opt/app", "/opt/$APP")]:
            with self.subTest(command=command):
                self.assertIsNone(ssh_material_request(command))

    def test_actual_report_cli_preserves_unsupported_unknown(self):
        a = self.unknown()
        before = store.event_store_path(self.path).read_bytes()
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/kb/intent-guardian.py"),
            "interventions", "--contract", str(self.path)], capture_output=True, text=True,
            encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["attempts"][0]["state"], "unknown")
        self.assertFalse(report["recovery"][a["attempt_id"]]["effect_verified"])
        self.assertEqual(store.event_store_path(self.path).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
