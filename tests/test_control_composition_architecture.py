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
from tests.guardian_u18_ast import restore_memory, reverse_policy, reverse_resources

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


def reviewed_composition_implementation(source):
    """Undo only the two reviewed S1 composition deltas, never whole owners."""
    tree = implementation(source)

    def owner(name):
        matches = [node for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name == name]
        assert len(matches) == 1, f"S1 composition owner changed or duplicated: {name}"
        return matches[0]

    sed_before = ast.parse('''
if name == "sed":
    return bool(len(args) == 2 and args[0] == "-n" and re.fullmatch(r"[0-9,$]*p", args[1]))
''').body[0]
    sed_after = ast.parse(r'''
if name == "sed":
    if len(args) < 2 or args[0] != "-n" or not re.fullmatch(r"(?:[0-9]+|\$)?(?:,(?:[0-9]+|\$))?p", args[1]):
        return False
    files = args[2:]
    if files[:1] == ["--"]:
        files = files[1:]
    else:
        if any(value.startswith("-") for value in files):
            return False
    return all(bool(value) for value in files)
''').body[0]
    filter_owner = owner('_filter_is_proven')
    sed_matches = [node for node in ast.walk(filter_owner) if isinstance(node, ast.If)
                   and ast.dump(node.test) == ast.dump(sed_after.test)]
    assert len(sed_matches) == 1, "S1 sed branch missing or duplicated"
    sed = sed_matches[0]
    assert sed in filter_owner.body, "S1 sed branch moved outside its direct owner body"
    assert ast.dump(sed) == ast.dump(sed_after), "S1 sed operand proof changed"
    filter_owner.body[filter_owner.body.index(sed)] = sed_before

    help_source = '''
if not control or not invocation["runtime_sha256"]:
    reason = "控制入口身份未被证明"
elif trusted_guardian_help(invocation):
    pass
elif control["route"] != "agent":
    reason = "该步骤没有绑定整个组合的原生授权；已有单条审批不能授权后续片段"
elif control["action"] not in READ_ONLY_AGENT_CONTROL_ACTIONS | AUDIT_CONTROL_ACTIONS:
    reason = "该步骤改变任务或授权上下文，后续步骤不能使用变更前的权限快照"
elif control["action"] in {"skill-start", "skill-end"}:
    registration = r._guardian_skill_command(step.command, provider=event["provider"])
    if registration:
        child["composition_registration"] = registration
    elif split_command_template(step.command)[-1] not in {"--help", "-h"}:
        reason = "Skill 登记缺少精确 provider/session/contract 绑定"
'''
    help_after = ast.parse(help_source).body[0]
    help_before = ast.parse(help_source.replace(
        'elif trusted_guardian_help(invocation):\n    pass\n', ''
    )).body[0]
    composition_owner = owner('normalize_composition')
    calls = [node for node in ast.walk(composition_owner) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == 'trusted_guardian_help']
    assert len(calls) == 1, "S1 trusted help proof missing or duplicated"
    gates = [node for node in ast.walk(composition_owner) if isinstance(node, ast.If)
             and isinstance(node.test, ast.Name) and node.test.id == 'invocation']
    assert len(gates) == 1, "S1 invocation gate changed or duplicated"
    gate = gates[0]
    assert len(gate.body) == 1 and ast.dump(gate.body[0]) == ast.dump(help_after), \
        "S1 help proof or surrounding authority chain changed"
    gate.body[0] = help_before
    return tree


def reviewed_implementation(source, domain):
    """Normalize only exact, independently behavior-tested accepted deltas."""
    tree = implementation(source)
    if domain == 'policy':
        tree = reverse_policy(tree, implementation(baseline('policy')))
    else:
        tree = restore_memory(tree, (PARTS/'resource_memory.py').read_text(encoding='utf-8'),
                              implementation(baseline('resources')))
        tree = reverse_resources(tree)
    owner = {"policy": "evaluate_event", "resources": "_command_effect"}[domain]
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == owner]
    assert len(functions) == 1, "reviewed delta owner changed"
    body = functions[0].body
    if domain == "policy":
        expected = ast.parse('''
if (
    contract["runtime"].get("historical_retirement", {}).get("epoch") == contract["task_epoch"]
    and effect in {"local_write", "external_write", "destructive", "unknown"}
):
    violation, severity = "历史执行阶段已终止；旧授权不可复用，须重新确认新阶段", "critical"
    pause, pause_class = True, "historical_retirement"
''').body[0]
        matches = [i for i, n in enumerate(body) if isinstance(n, ast.If)
                   and ast.dump(n.test) == ast.dump(expected.test)]
        assert len(matches) == 1, "historical retirement guard changed or duplicated"
        node = body[matches[0]]
        assert [ast.dump(n) for n in node.body] == [ast.dump(n) for n in expected.body], "retirement outcome changed"
        assert len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If), "original policy chain displaced"
        body[matches[0]] = node.orelse[0]
    else:
        expected = ast.parse('if _git_stdin_review_pipeline(command):\n    return "read"').body[0]
        predecessor = ast.parse('if _git_execution_passthrough(command):\n    return "unknown"').body[0]
        matches = [i for i, n in enumerate(body) if ast.dump(n) == ast.dump(expected)]
        assert len(matches) == 1 and matches[0] > 0, "Git review proof changed or duplicated"
        index = matches[0]
        assert ast.dump(body[index - 1]) == ast.dump(predecessor), "Git authority boundary moved"
        del body[index]
        # Reviewed 2026-09-27 delta (tests/test_intent_guardian_resources.py):
        # a `deploy` keyword only carries external-write weight when the shell
        # parser proves an executable shape. Fold the two statements back into
        # the single pre-delta keyword match so the tree equals BASE.
        old_deploy = ast.parse(
            'if re.search(r"\\b(gh\\s+(?:pr|issue|release)\\s+(?:create|merge|comment)'
            '|curl\\b.*\\s-X\\s*(?:POST|PUT|PATCH|DELETE)|scp\\b|rsync\\b.*:|npm\\s+publish|deploy)\\b", '
            'lowered, re.IGNORECASE):\n    return "external_write"'
        ).body[0]
        narrowed = ast.parse(
            'if re.search(r"\\b(gh\\s+(?:pr|issue|release)\\s+(?:create|merge|comment)'
            '|curl\\b.*\\s-X\\s*(?:POST|PUT|PATCH|DELETE)|scp\\b|rsync\\b.*:|npm\\s+publish)\\b", '
            'lowered, re.IGNORECASE):\n    return "external_write"'
        ).body[0]
        deploy_ifs = [n for n in body if isinstance(n, ast.If)
            and isinstance(n.test, ast.Call)
            and isinstance(n.test.func, ast.Attribute) and n.test.func.attr == 'search'
            and len(n.test.args) == 2 and isinstance(n.test.args[0], ast.Constant)
            and n.test.args[0].value == r"\bdeploy\b"]
        assert len(deploy_ifs) == 1, "deploy narrowing changed or duplicated"
        expected_deploy = ast.parse('''
if re.search(r"\\bdeploy\\b", lowered):
    executable = execution_domains[0][0] if execution_domains else ""
    if (
        not execution_domains
        or executable == "deploy"
        or executable in {"env", "sudo", "doas", "command", "exec", "nohup", "time", "timeout", "xargs", "eval"}
        or (command_tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", command_tokens[0]))
    ):
        return "external_write"
''').body[0]
        assert ast.dump(deploy_ifs[0]) == ast.dump(expected_deploy), "deploy proof body changed"
        deploy_index = body.index(deploy_ifs[0])
        assert deploy_index > 0, "narrowed external-write predecessor missing"
        assert ast.dump(body[deploy_index - 1]) == ast.dump(narrowed), \
            "narrowed external-write predecessor moved"
        body[deploy_index - 1:deploy_index + 1] = [old_deploy]
    return tree


class CompositionArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print('SOURCE_IDENTITIES '+json.dumps({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [PARTS/(n+'.py') for n in ('policy', 'resources', 'control_composition')]}, sort_keys=True))

    def _component_dependencies(self):
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
        return graph, delayed

    def test_full_component_graph_has_no_delayed_imports(self):
        _, delayed = self._component_dependencies()
        self.assertEqual(delayed, [])

    def test_full_component_graph_has_no_cycles(self):
        graph, _ = self._component_dependencies()
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
            ast.dump(reviewed_implementation((PARTS/'policy.py').read_text(), 'policy')))

    def test_composition_implementation_ast_is_unchanged(self):
        before = implementation(baseline('control_composition'))
        after = reviewed_composition_implementation((PARTS/'control_composition.py').read_text())
        self.assertEqual(ast.dump(before), ast.dump(after))

    def test_s1_composition_normalizer_rejects_changed_proofs_and_owners(self):
        source = (PARTS/'control_composition.py').read_text()
        mutations = (
            ('len(args) < 2', 'len(args) < 1'),
            ('files = args[2:]', 'files = args[3:]'),
            ('return all(bool(value) for value in files)', 'return True'),
            ('elif trusted_guardian_help(invocation):', 'elif trusted_guardian_help(child):'),
            ('elif trusted_guardian_help(invocation):\n                pass',
             'elif trusted_guardian_help(invocation):\n                reason = "changed"'),
            ('if not control or not invocation["runtime_sha256"]:', 'if not control:'),
            ('elif control["route"] != "agent":', 'elif control["route"] == "agent":'),
            ('def _filter_is_proven(', 'def renamed_filter('),
            ('def normalize_composition(', 'def renamed_composition('),
        )
        for old, new in mutations:
            with self.subTest(mutation=new):
                self.assertEqual(source.count(old), 1)
                with self.assertRaises(AssertionError):
                    reviewed_composition_implementation(source.replace(old, new))

    def test_s1_composition_normalizer_rejects_duplicate_branches_and_owner(self):
        source = (PARTS/'control_composition.py').read_text()
        for duplicate in ('sed', 'help', 'owner'):
            with self.subTest(duplicate=duplicate):
                tree = ast.parse(source)
                filters = next(node for node in tree.body
                               if isinstance(node, ast.FunctionDef) and node.name == '_filter_is_proven')
                composed = next(node for node in tree.body
                               if isinstance(node, ast.FunctionDef) and node.name == 'normalize_composition')
                if duplicate == 'sed':
                    branch = next(node for node in filters.body if isinstance(node, ast.If)
                                  and ast.dump(node.test) == ast.dump(ast.parse('name == "sed"', mode='eval').body))
                    filters.body.insert(-1, branch)
                elif duplicate == 'help':
                    composed.body.append(ast.parse('if trusted_guardian_help(invocation):\n    pass').body[0])
                else:
                    tree.body.append(filters)
                with self.assertRaises(AssertionError):
                    reviewed_composition_implementation(ast.unparse(tree))

    def test_s1_composition_normalizer_preserves_unrelated_changes(self):
        source = (PARTS/'control_composition.py').read_text()
        expected = ast.dump(implementation(baseline('control_composition')))
        mutations = (
            source + '\nUNREVIEWED_CHANGE = True\n',
            source.replace('if name == "printf":', 'if name == "unexpected":'),
            source.replace('"automatic_retry": False,', '"automatic_retry": True,'),
        )
        for mutated in mutations:
            with self.subTest(mutation=mutated[-120:]):
                self.assertNotEqual(source, mutated)
                self.assertNotEqual(expected, ast.dump(reviewed_composition_implementation(mutated)))

    def test_cycle_check_runs_despite_delayed_import_findings(self):
        graph = {'resources': {'control_composition'}, 'control_composition': {'resources'}}
        with mock.patch.object(self, '_component_dependencies', return_value=(graph, [('state.py', 1)])):
            with self.assertRaises(AssertionError):
                self.test_full_component_graph_has_no_cycles()

    def test_resource_implementation_ast_preserves_accepted_dev_wiring(self):
        before = implementation(baseline('resources'))
        after = reviewed_implementation((PARTS/'resources.py').read_text(), 'resources')
        calls = [n for n in ast.walk(after) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == 'normalize_composition']
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].keywords[-1].arg, 'services')
        self.assertEqual(ast.dump(before), ast.dump(after))

    def test_reviewed_delta_normalizer_rejects_changed_or_duplicate_authority(self):
        cases = (
            ('policy', '"historical_retirement", {}).get("epoch")', '"historical_retirement", {}).get("other_epoch")'),
            ('policy', 'pause, pause_class = True, "historical_retirement"', 'pause, pause_class = False, "historical_retirement"'),
            ('resources', 'if _git_stdin_review_pipeline(command):\n        return "read"', 'if _git_stdin_review_pipeline(command):\n        return "local_write"'),
            ('resources', 'if _git_execution_passthrough(command):\n        return "unknown"', 'if _git_execution_passthrough(command):\n        return "read"'),
        )
        for domain, old, new in cases:
            with self.subTest(domain=domain, mutation=new):
                source = (PARTS / (domain + '.py')).read_text()
                self.assertEqual(source.count(old), 1)
                with self.assertRaises(AssertionError):
                    reviewed_implementation(source.replace(old, new), domain)
        source = (PARTS / 'resources.py').read_text()
        block = '    if _git_stdin_review_pipeline(command):\n        return "read"\n'
        with self.assertRaises(AssertionError):
            reviewed_implementation(source.replace(block, block + block), 'resources')

    def test_reviewed_delta_normalizer_keeps_every_unrelated_change_visible(self):
        for domain in ('policy', 'resources'):
            with self.subTest(domain=domain):
                source = (PARTS / (domain + '.py')).read_text()
                after = reviewed_implementation(source + '\nUNREVIEWED_CHANGE = True\n', domain)
                self.assertNotEqual(ast.dump(implementation(baseline(domain))), ast.dump(after))

    def test_policy_imports_exports_and_line_budget_preserve_accepted_dev(self):
        before = ast.parse(baseline('policy'))
        after = ast.parse((PARTS/'policy.py').read_text())
        def names(tree):
            return {a.asname or a.name.split('.')[0] for n in ast.walk(tree)
                    if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        additions = {'consumed_grant_decision', 'material_blocker_description', 'effect_risk_acceptance_matches'}
        self.assertEqual(names(before) | additions, names(after))
        exact_imports = {
            (n.module, n.level, a.name, a.asname)
            for n in after.body if isinstance(n, ast.ImportFrom)
            for a in n.names if (a.asname or a.name) in additions
        }
        self.assertEqual(exact_imports, {
            ('decision_kernel', 0, 'consumed_grant_decision', None),
            ('intervention', 0, 'material_blocker_description', None),
            ('intervention', 0, 'effect_risk_acceptance_matches', None),
        })
        self.assertLessEqual(len((PARTS/'policy.py').read_text().splitlines()), 3000)
        from_module = __import__('intent_guardian_parts.policy', fromlist=['policy'])
        for path in (ROOT/'scripts/kb/intent_guardian.py', PARTS/'audit.py'):
            for n in ast.walk(ast.parse(path.read_text())):
                if isinstance(n, ast.ImportFrom) and n.module in ('intent_guardian_parts.policy', 'policy'):
                    for name in n.names:
                        self.assertTrue(hasattr(from_module, name.name), name.name)


if __name__ == '__main__':
    unittest.main()
