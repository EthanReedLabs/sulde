"""Regression for reviewed SSH operations with multiple unknown effects."""
from tests.test_guardian_s1_grants import RecoveryGrantJourneyTests
from intent_guardian import GuardianSession, load_contract, normalize_hook_event
from decision_kernel import prepare_effect_risk_grant, claim_human_grant, confirmation_reason
import intervention as effects
import hashlib
import json
from copy import deepcopy


class SSHRecoveryScopeTests(RecoveryGrantJourneyTests):
    def inspect_event(self, command):
        base = ("ssh -F /dev/null -i /home/operator/.ssh/id_ed25519 "
                "-o IdentitiesOnly=yes -o BatchMode=yes -o PermitLocalCommand=no "
                "-o StrictHostKeyChecking=yes -o UpdateHostKeys=no "
                "-o ConnectTimeout=10 ops@192.0.2.10 ")
        return normalize_hook_event({"client": "codex", "session_id": "session-one",
            "cwd": str(self.root), "call_id": "inspection", "tool_name": "Bash",
            "tool_input": {"command": base + "'" + command + "'"}},
            phase="started", provider="codex")

    def test_inspection_is_read_and_does_not_settle_unknown(self):
        old = self.debt()
        before = effects.event_store_path(self.path).read_bytes()
        for command in ("/usr/bin/stat /opt/app", "/usr/bin/free -m",
                        "/usr/bin/df -h /opt", "/usr/bin/docker ps --format {{.Names}}"):
            with self.subTest(command=command):
                event = self.inspect_event(command)
                self.assertEqual(event["effect"], "read")
                self.assertIsNone(effects.material_event_blocker(self.path, event))
        self.assertEqual(effects.event_store_path(self.path).read_bytes(), before)
        self.assertEqual(effects.load_projection(self.path)["attempts"][old]["state"], "unknown")

    def test_read_prefix_cannot_hide_material_operation(self):
        for command in ("/usr/bin/stat /opt/app; /bin/mkdir -p /opt/evil",
                        "/usr/bin/docker ps && touch /tmp/evil",
                        "/usr/bin/docker run image", "/usr/bin/stat $(touch /tmp/evil)",
                        "/usr/bin/stat /opt/app /etc/shadow"):
            with self.subTest(command=command):
                self.assertNotEqual(self.inspect_event(command)["effect"], "read")

    def test_private_mkdir_with_identity_file_is_material_not_read(self):
        event = self.inspect_event("/bin/mkdir -p -m 700 -- /opt/app")
        self.assertEqual(event["effect"], "external_write")
        self.assertEqual(event["remote_request"]["operation"], "mkdir_p")
        self.debt("one")
        self.debt("two")
        session = GuardianSession(self.path, provider="codex", session_id="session-one", hot_path=True)
        denied = session.observe(event)
        self.assertEqual(denied.reason_code, "effect_barrier_denied")
        self.assertIsNotNone(prepare_effect_risk_grant(self.path, session.contract, event, denied))

    def test_multiple_debts_can_be_reviewed_without_settling_them(self):
        old = [self.debt('first'), self.debt('second')]
        event = self.remote('review')
        session = GuardianSession(self.path, provider='codex', session_id='session-one', hot_path=True)
        denied = session.observe(event)
        tx = prepare_effect_risk_grant(self.path, session.contract, event, denied)
        self.assertIsNotNone(tx)
        review = tx['spec']['constraints']['effect_risk_review']
        self.assertEqual(set(review['attempt_ids']), set(old))
        self.assertIn('2 unresolved historical effects', review['reason'])
        self.assertIn('2 笔历史未知效果', confirmation_reason(event, tx))
        self.native(tx)
        event = self.remote('execute')
        dispatch = claim_human_grant(self.path, load_contract(self.path), event)
        self.assertIsNotNone(dispatch)
        result = GuardianSession(self.path, provider='codex', session_id='session-one', hot_path=True).observe(
            {**event, 'human_grant_dispatch': dispatch})
        self.assertEqual(result.action, 'allow', result.reason)
        for identity in old:
            self.assertEqual(effects.load_projection(self.path)['attempts'][identity]['state'], 'unknown')
        self.assertIsNone(claim_human_grant(self.path, load_contract(self.path), self.remote('replay')))
        original = [json.loads(row) for row in effects.event_store_path(self.path).read_text().splitlines()]
        index = next(i for i, row in enumerate(original) if row.get('risk_grant'))
        ids = original[index]['risk_grant']['accepted_attempt_ids']
        for altered in (ids[:-1], ids + ['att-forged'], ['att-forged'] + ids[1:], None):
            with self.subTest(altered=altered):
                rows = deepcopy(original)
                if altered is None:
                    rows[index]['risk_grant'].pop('accepted_attempt_ids')
                else:
                    rows[index]['risk_grant']['accepted_attempt_ids'] = altered
                rows[index].pop('event_id')
                rows[index]['event_id'] = hashlib.sha256(effects._canonical(rows[index]).encode()).hexdigest()
                with self.assertRaises(effects.InterventionError):
                    effects.replay(self.path, rows)
