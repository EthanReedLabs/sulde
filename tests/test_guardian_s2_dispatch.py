"""S2 method-input and prediction facts; disposable real Git, no model calls."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/kb'))
import impact_prediction as ip
import incremental_facts as facts
import prediction_feedback as feedback
from execution_method import execution_method_prompt
from tests.test_incremental_facts import _GitRepo


class PredictionScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / 'repo'
        self.repo.mkdir()
        self.git = _GitRepo(self.repo)
        self.git.run('init', '-q')
        self.git.commit_file('scripts/kb/example.py', 'VALUE = 1\n', 'baseline')
        self.git.run('tag', 'baseline')
        self.state = Path(self.temp.name) / 'state'
        self.store = feedback.prediction_store_path(self.state)
        self.original = hashlib.sha256((self.repo/'scripts/kb/example.py').read_bytes()).hexdigest()[:16]

    def open(self, expected):
        ip.open_prediction(self.store, {
            'kind': 'lightweight', 'task_id': 's2-task', 'run_id': 's2-run',
            'session_id': 's2-session', 'project_id': 'isolated-repo',
            'contract_version': 's2-contract#1',
            'source_identities': {'scripts/kb/example.py': self.original},
            'objective': 'bounded local fixture change',
            'assumptions': [{'text': 'declared scope only', 'confidence': 'high'}],
            'expected_touch': {'entries': expected},
            'impact_bounds': {'lower': 'one file', 'upper': 'declared scope', 'unknown': 'none'},
        }, at='2026-10-04T00:00:00+00:00', task_id='s2-task')

    def complete(self):
        return feedback.record_completion_feedback(
            state_dir=self.state, repo=self.repo, task_id='s2-task', run_id='s2-run',
            session_id='s2-session', provider='codex', intent_id='s2-contract',
            intent_revision=1, contract_version='s2-contract#1', baseline_revision='baseline')

    def test_normal_exact_scope_is_checked_and_no_feedback(self):
        self.open(['scripts/kb/example.py'])
        (self.repo/'scripts/kb/example.py').write_text('VALUE = 2\n', encoding='utf-8')
        result = self.complete()
        self.assertEqual(result['status'], 'checked')
        self.assertEqual(result['verdict'], 'as_predicted')
        self.assertNotIn('feedback_artifact', result)

    def test_directory_prefix_uses_same_in_scope_drift_semantics(self):
        self.open(['scripts/kb'])
        (self.repo/'scripts/kb/example.py').write_text('VALUE = 2\n', encoding='utf-8')
        result = self.complete()
        self.assertEqual(result['status'], 'checked')
        self.assertEqual(result['verdict'], 'as_predicted')
        self.assertNotIn('feedback_artifact', result)

    def test_truncated_real_diff_discloses_total_and_omissions(self):
        for index in range(201):
            (self.repo/f'file{index:03d}.py').write_text('VALUE = 2\n', encoding='utf-8')
        result = facts.collect_diff_facts(self.repo, baseline='baseline')
        self.assertEqual(len(result['changed_paths']), 200)
        self.assertTrue(result.get('truncated'))
        self.assertEqual(result['changed_count_total'], 201)
        self.assertEqual(result['omitted_count'], 1)
        self.assertEqual(result['comparison'], 'task_baseline_to_worktree')

    def test_partial_collection_never_yields_unqualified_verdict(self):
        result = facts.classify_against_prediction(
            {'changed_paths': ['scripts/kb/example.py'], 'diff': {'truncated': True}},
            {'inside_expected': ['scripts/kb/example.py'], 'outside_expected': []},
            {'expected_touch': {'entries': ['scripts/kb']}})
        self.assertIsNone(result['suggested_verdict'])
        self.assertTrue(result['incomplete'])

    def test_incomplete_producer_keeps_pending_and_records_no_check(self):
        self.open(['scripts/kb/example.py'])
        (self.repo/'scripts/surprise.py').write_text('VALUE = 3\n', encoding='utf-8')
        normal = self.complete()
        self.assertEqual(normal['status'], 'checked')
        self.assertEqual(normal['verdict'], 'larger_than_predicted')
        pending = Path(normal['feedback_artifact'])
        pending_before = pending.read_bytes()
        before = self.store.read_bytes()
        for index in range(201):
            (self.repo/f'file{index:03d}.py').write_text('VALUE = 2\n', encoding='utf-8')
        result = self.complete()
        self.assertEqual(result['status'], 'degraded')
        self.assertNotIn('verdict', result)
        self.assertEqual(self.store.read_bytes(), before)
        self.assertEqual(pending.read_bytes(), pending_before)
        self.assertIn('incomplete', result['error'])

    def test_overreach_feedback_contains_bounded_useful_relative_fact(self):
        self.open(['scripts/kb/example.py'])
        (self.repo/'scripts/kb/example.py').write_text('VALUE = 2\n', encoding='utf-8')
        (self.repo/'scripts/surprise.py').write_text('VALUE = 3\n', encoding='utf-8')
        result = self.complete()
        artifact = json.loads(Path(result['feedback_artifact']).read_text(encoding='utf-8'))
        self.assertEqual(artifact['verdict'], 'larger_than_predicted')
        self.assertIn('outside expected: scripts/surprise.py', artifact['facts'])
        self.assertTrue(any('task_baseline_to_worktree' in fact for fact in artifact['facts']))
        self.assertNotIn(str(self.repo), json.dumps(artifact))

    def test_untracked_nested_unicode_and_newline_names_are_counted_as_files(self):
        nested = self.repo/'tests/new'
        nested.mkdir(parents=True)
        for name in ('正常.py', 'second.py', 'line\nbreak.py'):
            (nested/name).write_text('# fixture\n', encoding='utf-8')
        result = facts.collect_diff_facts(self.repo, baseline='baseline')
        self.assertEqual(result['changed_count_total'], 3)
        self.assertFalse(result['truncated'])
        self.assertIn('tests/new/正常.py', result['changed_paths'])
        self.assertIn('tests/new/line\nbreak.py', result['changed_paths'])

    def test_exact_limit_is_complete_but_one_more_is_incomplete(self):
        for index in range(200):
            (self.repo/f'file{index:03d}.py').write_text('# fixture\n', encoding='utf-8')
        result = facts.collect_diff_facts(self.repo, baseline='baseline')
        self.assertEqual(result['changed_count_total'], 200)
        self.assertEqual(result['omitted_count'], 0)
        self.assertFalse(result['truncated'])
        (self.repo/'zzz.py').write_text('# fixture\n', encoding='utf-8')
        self.assertTrue(facts.collect_diff_facts(self.repo, baseline='baseline')['truncated'])


class InputBoundaryTests(unittest.TestCase):
    def test_scope_detail_is_bounded_and_private_or_opaque_paths_are_hashed(self):
        paths = ['scripts/正常.py', '/Users/person/private.py', '../outside.py',
                 'scripts/credentials.json', 'docs/line\nbreak.md', 'C:\\secret.py',
                 'scripts/ignore `instructions`.py', 'a/' + 'x' * 170]
        paths += [f'tests/more{index}.py' for index in range(10)]
        bundle = {'diff': {'changed_count': len(paths), 'changed_count_total': len(paths),
                           'omitted_count': 0}, 'split': {'outside_expected': paths}}
        result = facts.feedback_scope_facts(bundle, {'reason': 'observed scope'})
        self.assertIn('outside expected: scripts/正常.py', result)
        for private in paths[1:8]:
            self.assertNotIn(private, '\n'.join(result))
        self.assertEqual(sum('outside expected:' in line for line in result), 12)
        self.assertIn('scope detail omitted=6;', result[-1])
        self.assertLess(len('\n'.join(result)), 2500)

    def test_method_prompt_is_pure_bounded_and_preserves_authority(self):
        text = execution_method_prompt()
        self.assertEqual(text, execution_method_prompt())
        self.assertLess(len(text), 1500)
        for required in ('--- Sulde 有界执行方法（不新增权限） ---', '明确停止线、预算',
                         'audit-only/tests-only', '同一失败两次无新证据', '首个失败前置',
                         '不是自动重试计数或审批门', 'test-evidence.py plan', '只在任务已授权测试范围内',
                         '不宣称 as_predicted', '不自行 accepted'):
            self.assertIn(required, text)

    def test_real_runtime_stdin_receives_specific_overreach_fact(self):
        from tests.test_r3_real_entry_chain import _Chain
        with tempfile.TemporaryDirectory() as temp:
            chain = _Chain(Path(temp), mode='markerdriven')
            chain.seed_prediction()
            first = chain.run()
            self.assertNotEqual(first.returncode, 0)
            artifact = chain.state / f'prediction-feedback-{ip.digest("embed")}.json'
            saved = json.loads(artifact.read_text(encoding='utf-8'))
            self.assertIn('outside expected: consumer.py', saved['facts'])
            second = chain.run(retry_op='s2-scope-feedback')
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertIn('outside expected: consumer.py', chain.captured_prompt())
            self.assertIn('task_baseline_to_worktree', chain.captured_prompt())
            self.assertEqual(chain.probe().returncode, 0)


if __name__ == '__main__':
    unittest.main()
