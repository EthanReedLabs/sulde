"""Paired controls and externally injected historical-debt boundaries."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/kb'))
import intervention as store
from intent_guardian import normalize_hook_event
from intent_guardian_parts.approvals import _effect_intervention_card


class EffectRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sulde-effect-recovery-')
        self.root = Path(self.temp.name)
        self.path = self.root / 'intent.json'
        self.path.write_text('{}', encoding='utf-8')
        self.env = mock.patch.dict(os.environ, {'SULDE_KB_HOME': str(self.root / 'kb'),
                                              'SULDE_NOTIFY': 'off', 'PYTHONDONTWRITEBYTECODE': '1'})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def attempt(self, kind='existence', target='https://example.test/doc'):
        return store.begin_attempt(self.path, intent_id='repair', intent_revision=1,
            fingerprint='a'*64, source_event_id='original-write', capability='mcp:docs:update_document',
            target=target, resource_key=store.canonical_resource_key(target, kind='uri'),
            effect='external_write', provider='codex', session_id='old-session',
            idempotency_key='one-write', verification_kind=kind)

    def unknown(self, kind='existence'):
        a = self.attempt(kind)
        store.mark_attempt_result(self.path, a['attempt_id'], success=True)
        i = store.mark_attempt_unknown(self.path, a['attempt_id'], reason='lost verification')
        return store.load_projection(self.path)['attempts'][a['attempt_id']], i

    def event(self, command):
        return normalize_hook_event({'tool_name':'Bash','tool_input':{'command':command},
            'cwd':str(self.root),'session_id':'next-session'}, phase='started', provider='codex')

    def rebind(self, a, expected_content='c'*64):
        key = a['resource_key']
        arguments = 'b' * 64
        return store.resolve_attempt_target(self.path, a['attempt_id'], target=a['target'],
            resource_key=key, verification_kind='content', verification_sha256=expected_content,
            operation_arguments_digest=arguments,
            operation_fingerprint=store.effect_operation_fingerprint(provider='codex',
                capability=a['capability'], target=a['target'], resource_key=key,
                effect='external_write', arguments_digest=arguments),
            expected_target_sha256=a['target_sha256'], expected_resource_sha256=a['resource_sha256'],
            expected_operation_fingerprint=a['operation_fingerprint'])

    def prepare(self, a):
        return store.prepare_effect_recovery(self.path, a['attempt_id'],
            expected_binding_sha256=store.effect_recovery_readiness(a)['binding_sha256'])

    def test_aborted_recovery_requires_new_evidence_then_authorization(self):
        a, i = self.unknown()
        store.resolve_intervention(self.path, i['intervention_id'], decision='abort', evidence='stop')
        with self.assertRaisesRegex(store.InterventionError, 'new bound evidence'):
            self.prepare(a)
        before = store.event_store_path(self.path).read_bytes()
        a = self.rebind(a)
        recovery = self.prepare(a)
        self.assertEqual(recovery['recovery_of'], i['intervention_id'])
        self.assertEqual(recovery['status'], 'open')
        self.assertIsNone(recovery['decision'])
        self.assertIsNone(recovery.get('takeover_session_id'))
        after = store.event_store_path(self.path).read_bytes()
        self.assertTrue(after.startswith(before))
        self.assertEqual(self.prepare(a), recovery)
        self.assertEqual(store.event_store_path(self.path).read_bytes(), after)
        projection = store.load_projection(self.path)
        self.assertEqual(projection['attempts'][a['attempt_id']]['state'], 'unknown')
        self.assertEqual(len(store.blocking_attempts(projection)), 1)
        # The prepared card does not allow a new session to verify until approved.
        kwargs = dict(provider='codex', session_id='new-session',
            capability='mcp:docs:read_document', target=a['target'], resource_key=a['resource_key'],
            explicit_attempt_id=a['attempt_id'], verification_event_id='independent-read',
            evidence={'content':['c'*64]})
        self.assertEqual(store.verify_from_read(self.path, **kwargs), [])
        store.resolve_intervention(self.path, recovery['intervention_id'],
            decision='reprobe_authorized', evidence='approve independent read',
            takeover_provider='codex', takeover_session_id='new-session')
        self.assertEqual(len(store.verify_from_read(self.path, **kwargs)), 1)
        projection = store.load_projection(self.path)
        self.assertEqual(projection['attempts'][a['attempt_id']]['state'], 'system_verified')
        self.assertEqual(projection['interventions'][i['intervention_id']]['decision'], 'abort')

    def test_unsupported_recovery_and_stale_binding_never_append(self):
        a, i = self.unknown('unsupported')
        store.resolve_intervention(self.path, i['intervention_id'], decision='abort', evidence='stop')
        before = store.event_store_path(self.path).read_bytes()
        with self.assertRaisesRegex(store.InterventionError, 'verification basis'):
            self.prepare(a)
        with self.assertRaisesRegex(store.InterventionError, 'CAS'):
            store.prepare_effect_recovery(self.path, a['attempt_id'], expected_binding_sha256='0'*64)
        self.assertEqual(before, store.event_store_path(self.path).read_bytes())

    def test_recovery_does_not_reuse_previous_round_takeover(self):
        a, i = self.unknown()
        store.resolve_intervention(self.path, i['intervention_id'], decision='reprobe_authorized',
            evidence='old approval', takeover_provider='codex', takeover_session_id='old-takeover')
        next_i = store.mark_attempt_unknown(self.path, a['attempt_id'], reason='probe unavailable')
        store.resolve_intervention(self.path, next_i['intervention_id'], decision='abort', evidence='stop')
        a = self.rebind(a)
        self.prepare(a)
        self.assertEqual(store.verify_from_read(self.path, provider='codex', session_id='old-takeover',
            capability='mcp:docs:read_document', target=a['target'], resource_key=a['resource_key'],
            explicit_attempt_id=a['attempt_id'], verification_event_id='read-old-round',
            evidence={'content':['c'*64]}), [])

    def test_rebind_history_and_recycled_evidence_do_not_reopen_abort(self):
        a, i = self.unknown()
        a = self.rebind(a)
        store.resolve_intervention(self.path, i['intervention_id'], decision='abort', evidence='stop')
        for _ in range(2):
            a = self.rebind(a)
            with self.assertRaisesRegex(store.InterventionError, 'new bound evidence'):
                self.prepare(a)
        a = self.rebind(a, 'd'*64)
        next_i = self.prepare(a)
        store.resolve_intervention(self.path, next_i['intervention_id'], decision='abort', evidence='stop again')
        a = self.rebind(a, 'c'*64)
        with self.assertRaisesRegex(store.InterventionError, 'new bound evidence'):
            self.prepare(a)

    def test_recovery_projection_failure_replays_once_and_rejects_forged_opening(self):
        a, i = self.unknown()
        store.resolve_intervention(self.path, i['intervention_id'], decision='abort', evidence='stop')
        a = self.rebind(a)
        # Durable append succeeds but derived projection publication fails.
        with mock.patch.object(store, '_atomic_json', side_effect=OSError('injected projection failure')):
            with self.assertRaisesRegex(OSError, 'injected'):
                self.prepare(a)
        before = store.event_store_path(self.path).read_bytes()
        recovered = self.prepare(a)
        self.assertEqual(recovered['status'], 'open')
        self.assertEqual(store.event_store_path(self.path).read_bytes(), before)
        rows = [json.loads(line) for line in before.splitlines()]
        rows[-1]['recovery_of'] = 'int-forged'
        rows[-1].pop('event_id')
        rows[-1]['event_id'] = hashlib.sha256(store._canonical(rows[-1]).encode()).hexdigest()
        with self.assertRaisesRegex(store.InterventionError, 'predecessor or binding'):
            store.replay(self.path, rows)

    def test_legacy_unsupported_reprobe_history_still_replays(self):
        a, i = self.unknown('unsupported')
        # A pre-feature persisted event, not a new authorization request.
        store._mutate(self.path, lambda projection: ([{
            'type':'intent.intervention_resolved','intervention_id':i['intervention_id'],
            'attempt_id':a['attempt_id'],'decision':'reprobe_authorized','evidence':'historical',
            'actor':'human-cli'}], None))
        projection = store.load_projection(self.path)
        self.assertEqual(projection['interventions'][i['intervention_id']]['decision'], 'reprobe_authorized')
        self.assertEqual(projection['attempts'][a['attempt_id']]['state'], 'unknown')

    def test_recovery_cli_entry_and_concurrent_idempotency(self):
        a, i = self.unknown()
        store.resolve_intervention(self.path, i['intervention_id'], decision='abort', evidence='stop')
        a = self.rebind(a)
        argv = [sys.executable, '-B', str(ROOT/'scripts/kb/intent-guardian.py'),
            'prepare-effect-recovery', a['attempt_id'], '--contract', str(self.path),
            '--expected-binding-sha256', store.effect_recovery_readiness(a)['binding_sha256']]
        processes = [subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(3)]
        rows = []
        for process in processes:
            out, err = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, err.decode())
            rows.append(json.loads(out))
        self.assertEqual(len({row['intervention_id'] for row in rows}), 1)
        self.assertEqual(len(store.load_projection(self.path)['interventions']), 2)

    def test_ssh_shapes_do_not_use_remote_literals_as_local_writes(self):
        for command, effect in [
            ("ssh -p2222 -oBatchMode=yes host 'mkdir /opt/app'", 'external_write'),
            ("ssh -- host 'rm -rf /opt/app'", 'destructive'),
            ("ssh host 'rg \"mkdir /opt/app\" notes'", 'unknown'),
            ("ssh host 'cat /opt/app'", 'unknown'),
            ("ssh host", 'unknown'),
            ("ssh -z host 'mkdir /opt/app'", 'unknown'),
            ("ssh host 'mkdir /opt/app' && cat README.md", 'external_write'),
            ("env MODE=test ssh host 'test -e /opt/app && mkdir /opt/app'", 'external_write'),
            ("sudo -n -u root ssh host 'test -e /opt/app && mkdir /opt/app'", 'external_write'),
            ("command ssh host 'mkdir /opt/app'", 'external_write'),
            ("timeout 5 ssh host 'rm -rf /opt/app'", 'destructive'),
        ]:
            with self.subTest(command=command):
                event = self.event(command)
                self.assertEqual(event['effect'], effect)
                if effect == 'unknown':
                    self.assertEqual(event['uncertainty_kind'], 'unresolved_external_write')
                self.assertTrue(event['target'].startswith('[unresolved-remote-target:'))

    def test_normal_local_mkdir_and_remote_mutation_pair(self):
        self.assertEqual(self.event('mkdir output')['effect'], 'local_write')
        remote = self.event("ssh -i /tmp/test-key -o BatchMode=yes ops@192.0.2.10 'test ! -e /opt/app && mkdir -m 700 /opt/app'")
        self.assertEqual(remote['effect'], 'external_write')
        self.assertNotEqual(remote.get('uncertainty_kind'), 'unresolved_local_write')
        self.assertFalse(remote.get('write_targets'))
        self.assertTrue(remote['target'].startswith('[unresolved-remote-target:'))

    def test_normal_read_and_remote_destructive_are_not_weakened(self):
        self.assertEqual(self.event('cat README.md')['effect'], 'read')
        self.assertEqual(self.event("ssh ops@192.0.2.10 'rm -rf /opt/app'")['effect'], 'destructive')

    def test_unsupported_reprobe_rejected_without_append(self):
        a, i = self.unknown('unsupported')
        before = store.event_store_path(self.path).read_bytes()
        with self.assertRaisesRegex(store.InterventionError, 'verification|reprobe'):
            store.resolve_intervention(self.path, i['intervention_id'], decision='reprobe_authorized', evidence='try again')
        self.assertEqual(before, store.event_store_path(self.path).read_bytes())
        card = _effect_intervention_card(i, a)
        self.assertNotIn('只重新检查当前外部效果', card['可处理的事项'])

    def test_normal_supported_reprobe_still_works(self):
        a, i = self.unknown()
        r = store.resolve_intervention(self.path, i['intervention_id'], decision='reprobe_authorized', evidence='read independently')
        self.assertEqual(r['decision'], 'reprobe_authorized')
        self.assertEqual(store.load_projection(self.path)['attempts'][a['attempt_id']]['state'], 'unknown')

    def test_unresolved_blocker_is_not_claimed_same(self):
        a, i = self.unknown()
        store.resolve_intervention(self.path, i['intervention_id'], decision='abort', evidence='abandon')
        blocker = store.material_event_blocker(self.path, {'phase':'started','effect':'unknown',
            'uncertainty_kind':'unresolved_local_write','target':'[unresolved-command-target]'})
        self.assertEqual(blocker['attempt_id'], a['attempt_id'])
        self.assertEqual(blocker.get('match_reason'), 'resource_identity_unproved')
        self.assertEqual(store.readiness_blocking_attempts(store.load_projection(self.path)), [])

    def test_same_resource_and_explicit_dependency_stay_blocked(self):
        a, _ = self.unknown()
        event = {'phase':'started','effect':'external_write','target':a['target'],
            'effect_resource_key':a['resource_key']}
        self.assertIsNotNone(store.material_event_blocker(self.path, event))
        event['target'] = 'https://other.test/doc'
        event['effect_resource_key'] = store.canonical_resource_key(event['target'], kind='uri')
        self.assertIsNone(store.material_event_blocker(self.path, event))
        event['depends_on_attempt_id'] = a['attempt_id']
        self.assertIsNotNone(store.material_event_blocker(self.path, event))

    def test_local_typed_path_not_blocked_by_unrelated_remote_debt(self):
        self.unknown()
        event = {'phase':'started','kind':'tool','effect':'local_write','target':str(self.root/'output'),
            'resource_base':str(self.root)}
        self.assertIsNone(store.material_event_blocker(self.path, event))

    def test_distinct_ssh_command_hashes_do_not_prove_distinct_resources(self):
        target = '[command:' + 'd'*16 + ']'
        a = store.begin_attempt(self.path, intent_id='repair', intent_revision=1,
            fingerprint='e'*64, source_event_id='old-ssh', capability='tool:Bash',
            target=target, resource_key=store.canonical_resource_key(target, kind='opaque'),
            resource_context={'schema':'exact','value':target},
            effect='external_write', provider='codex', session_id='old-session',
            idempotency_key='old-ssh', verification_kind='unsupported')
        i = store.mark_attempt_unknown(self.path, a['attempt_id'], reason='remote result unknown')
        store.resolve_intervention(self.path, i['intervention_id'], decision='abort', evidence='stop')
        for command in ["ssh host-alias 'mkdir /opt/app'", "ssh 192.0.2.20 'echo hi > /opt/app'"]:
            blocker = store.material_event_blocker(self.path, self.event(command))
            self.assertEqual(blocker['attempt_id'], a['attempt_id'])
            self.assertEqual(blocker['match_reason'], 'resource_identity_unproved')

    def test_native_preview_and_real_hook_entry(self):
        # Reuse the standard isolated contract/environment fixture. No model,
        # remote command execution or production approval takes place here.
        from tests.test_intent_guardian import IntentGuardianTests
        from intent_guardian import native_decision_preview, IntentGuardianError
        fixture = IntentGuardianTests('runTest')
        fixture.setUp()
        saved_path = self.path
        try:
            fixture.contract()
            self.path = fixture.contract_path
            a, i = self.unknown('unsupported')
            before = store.event_store_path(self.path).read_bytes()
            with self.assertRaisesRegex(IntentGuardianError, 'verification basis'):
                native_decision_preview(self.path, kind='effect-intervention',
                    decision='reprobe_authorized', target=i['intervention_id'],
                    provider='codex', session_id='reviewer')
            abort = native_decision_preview(self.path, kind='effect-intervention',
                decision='abort', target=i['intervention_id'], provider='codex', session_id='reviewer')
            self.assertFalse(abort['authority_transferred'])
            self.assertEqual(before, store.event_store_path(self.path).read_bytes())
            payload = {'client':'claude','session_id':'entry-check','cwd':str(fixture.root),
                'tool_name':'Bash','tool_input':{'command':"ssh host 'mkdir /opt/app'"}}
            denied = fixture.run_hook(ROOT/'hooks/pre_tool_use.py', payload)
            self.assertEqual(denied.returncode, 0, denied.stderr)
            output = json.loads(denied.stdout)['hookSpecificOutput']
            self.assertEqual(output['permissionDecision'], 'deny')
            self.assertIn('资源身份尚未证明', output['permissionDecisionReason'])
            # Paired read is not blocked by the unknown historical remote effect.
            read = fixture.run_hook(ROOT/'hooks/pre_tool_use.py',
                {**payload, 'tool_name':'Read', 'tool_input':{'file_path':str(fixture.root/'resume.md')}})
            self.assertEqual(read.returncode, 0, read.stderr)
            self.assertEqual(read.stdout.strip(), '')
        finally:
            self.path = saved_path
            fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
