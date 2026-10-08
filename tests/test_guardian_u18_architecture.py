"""Paired normal/mutation proofs for the U18 architectural extraction and freeze."""
import ast
from collections import Counter
import copy
import subprocess
import sys
import unittest

from tests.test_control_composition_architecture import (
    PARTS, ROOT, baseline, implementation, reviewed_implementation,
)
from tests.guardian_u18_ast import MEMORY_NAMES, restore_memory, unique_owner, verify_decision_projection
from intent_guardian_parts import resource_memory, resources, recovery


def source(domain):
    return (PARTS / (domain + '.py')).read_text(encoding='utf-8')


def imports(text):
    result = []
    for node in ast.parse(text).body:
        if isinstance(node, ast.ImportFrom):
            result.extend((node.level, node.module, alias.name, alias.asname) for alias in node.names)
        elif isinstance(node, ast.Import):
            result.extend((0, '', alias.name, alias.asname) for alias in node.names)
    return Counter(result)


class U18ArchitectureTests(unittest.TestCase):
    def assert_frozen(self, domain, text):
        self.assertEqual(ast.dump(implementation(baseline(domain))),
                         ast.dump(reviewed_implementation(text, domain)))

    def test_normal_resource_policy_restore_entire_original_ast(self):
        for domain in ('resources', 'policy'):
            with self.subTest(domain=domain):
                self.assert_frozen(domain, source(domain))

    def test_import_additions_have_exact_provenance_not_only_names(self):
        additions = {
            'resources': '''
from command_template import git_stdin_review_pipeline as _git_stdin_review_pipeline
from .semantic_proofs import proven_datetime_method_calls, ssh_readonly_probe, trusted_guardian_help
from .remote_identity import ssh_material_request, ssh_read_request
from .resource_memory import _system_memory_annotation_candidate, _memory_receipt_verification, _local_memory_annotation_verification
''',
            'policy': '''
from decision_kernel import consumed_grant_decision
from intervention import effect_risk_acceptance_matches, material_blocker_description
''',
        }
        for domain, extra in additions.items():
            with self.subTest(domain=domain):
                self.assertEqual(imports(source(domain)), imports(baseline(domain)) + imports(extra))

    def test_moved_decisions_preserve_all_old_authority_keywords(self):
        text = (ROOT/'scripts/kb/decision_kernel.py').read_text(encoding='utf-8')
        original = implementation(baseline('policy'))
        verify_decision_projection(text, original)
        tree = ast.parse(text)
        helper = unique_owner(tree, ('consumed_grant_decision',))
        helper.body.insert(1, ast.parse('return Decision(dispatch="allow")').body[0])
        with self.assertRaises(AssertionError):
            verify_decision_projection(ast.unparse(tree), original)

    def test_extracted_memory_exports_are_identical_objects_and_globals(self):
        for name in MEMORY_NAMES:
            self.assertIs(getattr(resources, name), getattr(resource_memory, name))
            self.assertIs(getattr(resource_memory, name).__globals__, vars(resource_memory))
        self.assertIs(recovery._memory_receipt_verification, resource_memory._memory_receipt_verification)
        self.assertEqual(resource_memory._memory_receipt_verification('bad-digest'), None)

    def test_memory_body_receipt_and_foreign_identity_mutations_rejected(self):
        original = source('resource_memory')
        cases = (
            ('result = verify_memory_receipt(connection, expected_digest)', 'result = True'),
            ('if tool_input.get("extracted_by") != normalized_provider:', 'if False:'),
            ('if str(edge.get("src") or "").strip() not in entity_names:', 'if False:'),
            ('return _memory_receipt_verification(expected_digest)', 'return {"verified": True}'),
            ('from .state import SYSTEM_MEMORY_PROFILE, kb_home', 'from foreign_state import SYSTEM_MEMORY_PROFILE, kb_home'),
            ('verify_receipt as verify_memory_receipt', 'normalize as verify_memory_receipt'),
        )
        for old, new in cases:
            with self.subTest(mutation=new):
                self.assertEqual(original.count(old), 1)
                with self.assertRaises(AssertionError):
                    restore_memory(implementation(source('resources')), original.replace(old, new),
                                   implementation(baseline('resources')))

    def test_memory_extra_execution_and_duplicate_owner_rejected(self):
        text = source('resource_memory')
        tree = ast.parse(text)
        duplicate = ast.unparse(unique_owner(tree, ('_memory_receipt_verification',)))
        for suffix in ('\nUNREVIEWED = True\n', '\n' + duplicate, '\nfrom foreign import kb_home\n'):
            with self.subTest(suffix=suffix[:60]):
                with self.assertRaises(AssertionError):
                    restore_memory(implementation(source('resources')), text + suffix,
                                   implementation(baseline('resources')))

    def test_risk_check_delete_swap_foreign_identity_and_receipt_mutations(self):
        text = source('policy')
        cases = (
            ('if blocker and isinstance(review, dict):', 'if isinstance(review, dict):'),
            ('if effect_risk_acceptance_matches(self.path, event, review):', 'if True:'),
            ('effect_risk_acceptance_matches(self.path, event, review)', 'effect_risk_acceptance_matches(self.path, foreign_event, review)'),
            ('risk_event=event if risk_grant else None,', 'risk_event=None,'),
            ('risk_dispatch=risk_grant.get("dispatch"),', 'risk_dispatch=None,'),
            ('risk_grant_transaction_id=str(risk_grant.get("transaction_id") or ""),', 'risk_grant_transaction_id="",'),
            ('if not isinstance(risk_grant.get("effect_risk_review"), dict):', 'if False:'),
            ('review = event["human_grant_dispatch"].get("effect_risk_review")', 'return Decision(dispatch="allow")'),
        )
        for old, new in cases:
            with self.subTest(mutation=new):
                self.assertEqual(text.count(old), 1)
                with self.assertRaises(AssertionError):
                    self.assert_frozen('policy', text.replace(old, new))
        tree = ast.parse(text)
        owner = unique_owner(tree, ('GuardianSession', '_observe_locked'))
        gate = next(node for node in ast.walk(owner) if isinstance(node, ast.If)
                    and ast.unparse(node.test) == "isinstance(event.get('human_grant_dispatch'), dict)")
        # Move receipt validation after the decision constructor: same statements,
        # wrong authority ordering. This must not be normalized away.
        gate.body[2], gate.body[4] = gate.body[4], gate.body[2]
        with self.assertRaises(AssertionError):
            self.assert_frozen('policy', ast.unparse(tree))

    def test_remote_help_datetime_and_deploy_mutations_rejected(self):
        text = source('resources')
        cases = (
            ('if trusted_guardian_help(invocation):', 'if "--help" in command:'),
            ('data_calls.update(proven_datetime_method_calls(tree))', 'data_calls.update(ast.walk(tree))'),
            ('remote_request = ssh_material_request(command)', 'remote_request = {"target": "local"}'),
            ('read_request = ssh_read_request(command) if invocation_violation is None else None',
             'read_request = {"effect": "read"}'),
            ('if read_request is not None:', 'if True:'),
            ('if readonly:\n        return "read"', 'if True:\n        return "read"'),
            ('event["effect_resource_base"] = ""', 'event["effect_resource_base"] = str(command_cwd)'),
            ('remote_effect == "unknown" and risks is not None', 'False'),
            ('or executable == "deploy"', 'or executable == "anything"'),
        )
        for old, new in cases:
            with self.subTest(mutation=new):
                self.assertEqual(text.count(old), 1)
                with self.assertRaises(AssertionError):
                    self.assert_frozen('resources', text.replace(old, new))

    def test_unreviewed_tail_early_allow_and_duplicate_owner_never_disappear(self):
        for domain, names in (('policy', ('GuardianSession',)), ('resources', ('_command_effect',))):
            text = source(domain)
            tree = ast.parse(text)
            owner = unique_owner(tree, names)
            duplicate = text + '\n' + ast.unparse(owner)
            changed = copy.deepcopy(tree)
            fn = unique_owner(changed, ('GuardianSession', '_observe_locked') if domain == 'policy' else names)
            fn.body.insert(0, ast.parse('return "allow"').body[0])
            for mutation in (text + '\nUNREVIEWED_TAIL = True\n', duplicate, ast.unparse(changed)):
                with self.subTest(domain=domain, mutation=mutation[-70:]):
                    with self.assertRaises(AssertionError):
                        self.assert_frozen(domain, mutation)

    def test_state_refactor_changes_import_placement_only(self):
        before = subprocess.check_output(
            ['git', 'show', 'ef5e7d6:scripts/kb/intent_guardian_parts/state.py'], cwd=ROOT,
            text=True, encoding='utf-8', errors='replace')
        self.assertEqual(ast.dump(implementation(before)), ast.dump(implementation(source('state'))))
        required = imports('from plugin_creator_dependency import PluginCreatorDependencyError, check_cachebuster_dependency')
        self.assertEqual(imports(source('state')), imports(before) + required)

    def test_real_cli_help_and_fresh_memory_import_orders(self):
        result = subprocess.run([sys.executable, '-B', 'scripts/kb/intent-guardian.py', '--help'], cwd=ROOT,
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('usage:', result.stdout)
        for order in ('resource_memory,state,resources,recovery', 'recovery,resources,state,resource_memory'):
            code = "import importlib; " + '; '.join(
                "importlib.import_module('intent_guardian_parts." + name + "')" for name in order.split(','))
            result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT/'scripts/kb',
                                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
