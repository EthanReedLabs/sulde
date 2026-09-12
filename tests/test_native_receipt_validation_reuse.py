"""Successful prefix validation reuse must never become authority or stale state."""
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import unittest
from unittest import mock

from tests import test_native_receipt_consistency as regression
from tests import test_native_decision_journal as history_module
from intent_guardian_parts import recovery, state
import native_decision_journal as journal


class NativeReceiptValidationReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print('REPRODUCIBILITY '+json.dumps(dict(python=platform.python_version(),executable=sys.executable,
            test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            journal_sha256=hashlib.sha256(Path(journal.__file__).read_bytes()).hexdigest(),
            recovery_sha256=hashlib.sha256(Path(recovery.__file__).read_bytes()).hexdigest(),
            data='Temporary synthetic formal stores only; no production authority'),sort_keys=True),file=sys.stderr)

    def setUp(self):
        self.f=regression.NativeReceiptConsistencyTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        # Receipt entry points use the canonical path; macOS /var is an alias.
        # Do not weaken the source's no-follow checks to accommodate a fixture.
        self.path=self.f.path.resolve()
        self.h=history_module.NativeDecisionJournalTests()
        self.h.contract=self.path
        self.h.root=self.path.parent
        for i in range(4):
            tx=self.h.transaction('proposal',suffix='reuse-history-'+str(i))
            journal.supersede(self.path,tx['transaction_id'],reason='isolated history; no execution')
        self.rows=[json.loads(x) for x in journal.journal_path(self.path).read_text().splitlines()]
        self.source=history_module.event_store_path(self.path)
        self.present_current()

    def present_current(self):
        preview=regression.fixture_module.native_decision_preview(self.path,kind='proposal',decision='approve',
            target='current',provider='codex',session_id=self.f.session)
        regression.fixture_module.observe_native_permission_request(
            self.f.fixture.native_permission_payload(preview,session_id=self.f.session),provider='codex')

    def add_question(self):
        history_module.ask_approval(self.path,intent_id='isolated-extra-question',intent_revision=1,
            kind='proposal',target='extra-target',provider='codex',session_id='extra-session',
            source='codex_permission_request',card={'question':'isolated later suffix'},workspace=self.h.root,route='human')

    def replay(self): return journal.replay(self.path,self.rows)

    def test_prefix_verifier_call_count_is_bounded_inside_real_receipt_tail(self):
        original=recovery._advance_native_receipt_chain_locked
        observed=[]
        def counted(*a,**kw):
            with mock.patch.object(journal,'verify_request_binding_receipt',wraps=journal.verify_request_binding_receipt) as verifier:
                value=original(*a,**kw)
                observed.append(verifier.call_count)
                return value
        with mock.patch.object(recovery,'_advance_native_receipt_chain_locked',side_effect=counted):
            self.f.execute()
        self.assertEqual(len(observed),1)
        self.assertLessEqual(observed[0],5,'same five immutable request prefixes repeatedly replayed')
        current=[x for x in journal.load_projection(self.path)['transactions'].values() if x['binding']['target']==self.f.digest]
        self.assertEqual([x['stage'] for x in current],['committed'])
        self.assertEqual(len(state.load_contract(self.path)['runtime']['proposal_decisions']),1)

    def test_identical_source_reuses_only_successful_request_validation(self):
        with journal._request_validation_scope(),mock.patch.object(journal,'verify_request_binding_receipt',wraps=journal.verify_request_binding_receipt) as v:
            first=self.replay()
            second=self.replay()
            self.assertEqual(first,second)
            self.assertEqual(v.call_count,4)

    def test_next_call_scope_has_no_inherited_cache(self):
        with mock.patch.object(journal,'verify_request_binding_receipt',wraps=journal.verify_request_binding_receipt) as v:
            with journal._request_validation_scope(): self.replay()
            with journal._request_validation_scope(): self.replay()
            self.assertEqual(v.call_count,8)

    def test_valid_source_append_between_passes_invalidates_and_revalidates(self):
        with journal._request_validation_scope(),mock.patch.object(journal,'verify_request_binding_receipt',wraps=journal.verify_request_binding_receipt) as v:
            self.replay()
            self.add_question()
            self.replay()
            self.assertEqual(v.call_count,8)

    def test_identical_bytes_replaced_inode_requires_revalidation(self):
        with journal._request_validation_scope(),mock.patch.object(journal,'verify_request_binding_receipt',wraps=journal.verify_request_binding_receipt) as v:
            self.replay()
            replacement=self.source.with_suffix('.replacement')
            replacement.write_bytes(self.source.read_bytes())
            replacement.chmod(self.source.stat().st_mode & 0o777)
            old_inode=self.source.stat().st_ino
            os.replace(replacement,self.source)
            self.assertNotEqual(self.source.stat().st_ino,old_inode)
            self.replay()
            self.assertEqual(v.call_count,8)

    def test_source_change_during_pass_fails_and_discards_cache(self):
        original=journal._verify_request_semantics
        calls=[]
        def mutate(*a,**kw):
            value=original(*a,**kw)
            if not calls:
                self.add_question()
            calls.append(True)
            return value
        with journal._request_validation_scope():
            with mock.patch.object(journal,'_verify_request_semantics',side_effect=mutate):
                with self.assertRaisesRegex(journal.NativeDecisionJournalError,'changed during request validation'):
                    self.replay()
            with mock.patch.object(journal,'verify_request_binding_receipt',wraps=journal.verify_request_binding_receipt) as v:
                self.replay()
                self.assertEqual(v.call_count,4)

    def test_same_size_same_mtime_changed_bytes_are_not_cache_hits(self):
        with journal._request_validation_scope():
            self.replay()
            before=self.source.read_bytes()
            metadata=self.source.stat()
            rows=[json.loads(x) for x in before.splitlines()]
            asked=next(x for x in rows if x.get('type')=='approval.asked' and x['request_id']==self.rows[0]['binding']['request_id'])
            old=asked['card_sha256'].encode()
            new=(b'a' if old[:1]!=b'a' else b'b')+old[1:]
            changed=before.replace(old,new,1)
            self.assertNotEqual(changed,before)
            self.assertEqual(len(changed),len(before))
            self.source.write_bytes(changed)
            os.utime(self.source,ns=(metadata.st_atime_ns,metadata.st_mtime_ns))
            with self.assertRaises(journal.NativeDecisionJournalError): self.replay()

    def test_disappeared_source_is_not_served_from_cache(self):
        with journal._request_validation_scope():
            self.replay()
            self.source.unlink()
            with self.assertRaises(journal.NativeDecisionJournalError): self.replay()

    def test_truncated_required_prefix_is_not_served_from_cache(self):
        with journal._request_validation_scope():
            self.replay()
            self.source.write_bytes(self.source.read_bytes().splitlines(keepends=True)[0])
            with self.assertRaises(journal.NativeDecisionJournalError): self.replay()

    def test_symlink_substitution_is_not_served_from_cache(self):
        with journal._request_validation_scope():
            self.replay()
            saved=self.source.with_suffix('.saved')
            self.source.rename(saved)
            self.source.symlink_to(saved)
            with self.assertRaises(journal.NativeDecisionJournalError): self.replay()

    def test_receipt_substitution_still_fails_after_a_cache_hit(self):
        with journal._request_validation_scope():
            self.replay()
            altered=json.loads(json.dumps(self.rows))
            altered[0]['request_receipt']['intent_revision']+=1
            with self.assertRaises(journal.NativeDecisionJournalError): journal.replay(self.path,altered)

    def test_returned_request_cannot_poison_cached_value(self):
        original=journal._verify_request_semantics
        def poison(*a,**kw):
            value=original(*a,**kw)
            value['intent_revision']=-100
            return value
        with journal._request_validation_scope():
            with mock.patch.object(journal,'_verify_request_semantics',side_effect=poison): self.replay()
            self.replay()

    def test_exception_scope_resets_context(self):
        with self.assertRaisesRegex(RuntimeError,'injected exception'):
            with journal._request_validation_scope():
                self.replay()
                raise RuntimeError('injected exception')
        self.assertIsNone(journal._REQUEST_VALIDATIONS.get())
        self.assertIsNone(journal._ACTIVE_REQUEST_VALIDATIONS.get())

    def test_malformed_later_suffix_keeps_existing_immutable_prefix_semantics(self):
        with journal._request_validation_scope():
            self.replay()
            self.source.write_bytes(self.source.read_bytes()+b'not-json-later-tail')
            # The unchanged authority verifier intentionally accepts the exact
            # asked prefix; a later malformed suffix cannot rewrite its history.
            self.replay()


if __name__=='__main__': unittest.main()
