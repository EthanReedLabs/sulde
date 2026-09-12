"""Explicit dependencies must preserve the existing control-policy behavior."""
import ast
import dataclasses
import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PARTS = ROOT / 'scripts/kb/intent_guardian_parts'
# The integrated tree must retain dev's accepted memory/host-identity behavior.
BASE = '77c5929d7a69ffada7b205d431db82e24bd4e87c'
sys.path.insert(0, str(ROOT / 'scripts/kb'))
from intent_guardian_parts import control_composition as composition, resources


def baseline(name):
    return subprocess.check_output(['git', 'show', BASE+':scripts/kb/intent_guardian_parts/'+name+'.py'],
        cwd=ROOT, text=True, encoding="utf-8", errors="replace")


class WithoutImports(ast.NodeTransformer):
    def visit_Import(self, node):
        return None

    def visit_ImportFrom(self, node):
        return None


def implementation(source):
    return WithoutImports().visit(ast.parse(source))


class CompositionArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print('SOURCE_IDENTITIES '+json.dumps({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [PARTS/(n+'.py') for n in ('policy', 'resources', 'control_composition')]}, sort_keys=True))

    def test_full_component_graph_has_no_delayed_imports_or_cycles(self):
        graph = {}
        delayed = []
        for path in sorted(PARTS.glob('*.py')):
            tree = ast.parse(path.read_text())
            deps = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    delayed.extend((path.name, child.lineno) for child in ast.walk(node)
                        if isinstance(child, (ast.Import, ast.ImportFrom)))
                if isinstance(node, ast.ImportFrom):
                    if node.level == 1:
                        deps.update([node.module.split('.')[0]] if node.module else [a.name for a in node.names])
                    elif node.module == 'intent_guardian_parts':
                        deps.update(a.name for a in node.names)
                    elif node.module and node.module.startswith('intent_guardian_parts.'):
                        deps.add(node.module.split('.')[1])
                    self.assertNotEqual(node.module, 'intent_guardian', path.name)
                elif isinstance(node, ast.Import):
                    self.assertNotIn('intent_guardian', {a.name for a in node.names}, path.name)
                    deps.update(a.name.split('.')[1] for a in node.names if a.name.startswith('intent_guardian_parts.'))
            graph[path.stem] = deps
        self.assertEqual(delayed, [])
        def visit(node, stack):
            self.assertNotIn(node, stack, ' -> '.join((*stack, node)))
            for child in graph.get(node, set()):
                visit(child, (*stack, node))
        for node in graph:
            visit(node, ())
        self.assertNotIn('resources', graph['control_composition'])
        self.assertIn('control_composition', graph['resources'])

    def test_callbacks_exactly_cover_previous_resource_accesses(self):
        tree = ast.parse(baseline('control_composition'))
        accessed = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                    and isinstance(n.value, ast.Name) and n.value.id == 'r'}
        self.assertEqual({f.name for f in dataclasses.fields(composition.CompositionServices)}, accessed)
        self.assertEqual(len(accessed), 12)

    def test_callback_bundle_is_frozen_and_has_no_defaults(self):
        fields = dataclasses.fields(composition.CompositionServices)
        with self.assertRaises(TypeError):
            composition.CompositionServices()
        bundle = composition.CompositionServices(**{f.name: getattr(resources, f.name) for f in fields})
        with self.assertRaises(dataclasses.FrozenInstanceError):
            bundle.normalize_hook_event = lambda *a, **k: {}

    def test_owner_passes_only_original_named_callbacks(self):
        source = ast.parse((PARTS/'resources.py').read_text())
        constructors = [n for n in ast.walk(source) if isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Name) and n.func.id == 'CompositionServices']
        self.assertEqual(len(constructors), 1)
        call = constructors[0]
        self.assertEqual(call.keywords, [])
        fields = dataclasses.fields(composition.CompositionServices)
        self.assertEqual(len(call.args), len(fields))
        for value, field in zip(call.args, fields):
            self.assertIsInstance(value, ast.Name)
            self.assertEqual(field.name, value.id)
            self.assertTrue(callable(getattr(resources, field.name)))

    def test_ordinary_single_call_never_constructs_composition_bundle(self):
        with mock.patch.object(resources, 'CompositionServices', side_effect=AssertionError('unexpected bundle')):
            event = resources.normalize_hook_event({'tool_name':'Bash', 'tool_input':{'command':'rg needle README.md'},
                'cwd':str(ROOT), 'session_id':'isolated-architecture-test'}, phase='started', provider='codex')
        self.assertNotIn('composition', event)

    def test_fresh_process_import_order_is_independent(self):
        for order in itertools.permutations(('control_composition', 'resources', 'policy')):
            with self.subTest(order=order):
                code = "import sys,importlib; sys.path.insert(0,'scripts/kb'); " + '; '.join(
                    "importlib.import_module('intent_guardian_parts."+name+"')" for name in order)
                result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT,
                    env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'}, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_policy_implementation_ast_is_unchanged(self):
        self.assertEqual(ast.dump(implementation(baseline('policy'))),
            ast.dump(implementation((PARTS/'policy.py').read_text())))

    def test_composition_implementation_ast_is_unchanged(self):
        before = implementation(baseline('control_composition'))
        after = implementation((PARTS/'control_composition.py').read_text())
        self.assertEqual(ast.dump(before), ast.dump(after))

    def test_resource_implementation_ast_preserves_accepted_dev_wiring(self):
        before = implementation(baseline('resources'))
        after = implementation((PARTS/'resources.py').read_text())
        calls = [n for n in ast.walk(after) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == 'normalize_composition']
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].keywords[-1].arg, 'services')
        self.assertEqual(ast.dump(before), ast.dump(after))

    def test_policy_imports_exports_and_line_budget_preserve_accepted_dev(self):
        before = ast.parse(baseline('policy'))
        after = ast.parse((PARTS/'policy.py').read_text())
        def names(tree):
            return {a.asname or a.name.split('.')[0] for n in ast.walk(tree)
                    if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        self.assertEqual(names(before), names(after))
        self.assertLessEqual(len((PARTS/'policy.py').read_text().splitlines()), 3000)
        from_module = __import__('intent_guardian_parts.policy', fromlist=['policy'])
        for path in (ROOT/'scripts/kb/intent_guardian.py', PARTS/'audit.py'):
            for n in ast.walk(ast.parse(path.read_text())):
                if isinstance(n, ast.ImportFrom) and n.module in ('intent_guardian_parts.policy', 'policy'):
                    for name in n.names:
                        self.assertTrue(hasattr(from_module, name.name), name.name)


if __name__ == '__main__':
    unittest.main()
