"""Exact reviewed slices, not a new whole-file freeze or an allowlist of owners.

Every splice checks the complete candidate fragment, its unique owner and fixed
position. The caller still compares the entire restored AST against 77c5929.
New mutations outside these slices therefore remain visible to that comparison.
"""
import ast
import copy
from pathlib import Path


MEMORY_NAMES = (
    '_system_memory_annotation_candidate',
    '_memory_receipt_verification',
    '_local_memory_annotation_verification',
)


def unique_owner(tree, names):
    node = tree
    for name in names:
        matches = [child for child in node.body
                   if isinstance(child, (ast.FunctionDef, ast.ClassDef)) and child.name == name]
        assert len(matches) == 1, f'changed/duplicate owner: {names}'
        node = matches[0]
    return node


def restore_memory(tree, helper_source, original_tree):
    helper = ast.parse(helper_source)
    imports = [node for node in helper.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    expected_imports = ast.parse('''
from __future__ import annotations
import re
import sqlite3
from typing import Any
from memory_annotation import normalize as normalize_memory_annotation, digest as memory_annotation_digest, verify_receipt as verify_memory_receipt
from .state import SYSTEM_MEMORY_PROFILE, kb_home
from .resource_postconditions import _memory_annotation_postcondition, _verification_digest
''').body
    assert [ast.dump(node) for node in imports] == [ast.dump(node) for node in expected_imports], \
        'memory helper global bindings changed'
    functions = [node for node in helper.body if isinstance(node, ast.FunctionDef)]
    assert tuple(node.name for node in functions) == MEMORY_NAMES, 'memory owner set/order changed'
    allowed = (ast.Import, ast.ImportFrom, ast.FunctionDef)
    assert all(isinstance(node, allowed) or (
        index == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)) for index, node in enumerate(helper.body)), \
        'unreviewed helper module execution'
    for function in functions:
        original = unique_owner(original_tree, (function.name,))
        assert ast.dump(function) == ast.dump(original), f'memory extraction changed: {function.name}'
        assert not any(isinstance(node, ast.FunctionDef) and node.name == function.name
                       for node in tree.body), 'duplicate memory owner'
    anchor = unique_owner(tree, ('_input_digest',))
    index = tree.body.index(anchor)
    assert isinstance(tree.body[index - 1], ast.FunctionDef)
    assert tree.body[index - 1].name == 'contract_from_brief', 'memory extraction anchor changed'
    tree.body[index:index] = functions
    return tree


def splice(owner, after, before):
    """Match complete statement sequences, including unchanged adjacent anchors."""
    expected = ast.parse(after).body
    pattern = [ast.dump(node) for node in expected]
    matches = []
    for parent in ast.walk(owner):
        for _, values in ast.iter_fields(parent):
            if not isinstance(values, list) or not values or not isinstance(values[0], ast.stmt):
                continue
            keys = [ast.dump(node) for node in values]
            matches.extend((values, index) for index in range(len(keys))
                           if keys[index:index + len(pattern)] == pattern)
    assert len(matches) == 1, 'reviewed statement slice changed/duplicated: ' + after[:100]
    values, index = matches[0]
    values[index:index + len(pattern)] = ast.parse(before).body


def branch(owner, test):
    expected = ast.parse(test, mode='eval').body
    matches = [node for node in ast.walk(owner) if isinstance(node, ast.If)
               and ast.dump(node.test) == ast.dump(expected)]
    assert len(matches) == 1, 'reviewed branch changed/duplicated: ' + test
    return matches[0]


def reverse_policy(tree, original):
    owner = unique_owner(tree, ('GuardianSession', '_observe_locked'))
    old_owner = unique_owner(original, ('GuardianSession', '_observe_locked'))
    # The whole *small branch body* is checked: receipt check cannot be removed,
    # swapped after dispatch, or changed to accept a foreign identity.
    test = 'isinstance(event.get("human_grant_dispatch"), dict)'
    gate = branch(owner, test)
    old_gate = branch(old_owner, test)
    barrier = '''
try:
    blocker = material_event_blocker(self.path, event)
except (InterventionError, OSError, UnicodeError) as error:
    raise IntentGuardianError(f"cannot prove the external-effect barrier state: {error}") from error
'''
    expected = ast.parse(barrier + '''
review = event["human_grant_dispatch"].get("effect_risk_review")
if blocker and isinstance(review, dict):
    if effect_risk_acceptance_matches(self.path, event, review):
        blocker = None
if blocker:
    event["blocker_match_reason"] = blocker["match_reason"]
decision = consumed_grant_decision(
    event, fingerprint, material_blocker_description(blocker) if blocker else "")
blocker = None
''').body
    assert [ast.dump(n) for n in gate.body] == [ast.dump(n) for n in expected], 'risk receipt/dispatch chain changed'
    gate.body = copy.deepcopy(old_gate.body)
    test = 'not event.get("control_plane") and blocker'
    gate = branch(owner, test)
    old_gate = branch(old_owner, test)
    expected = ast.parse('''
event["blocker_match_reason"] = blocker["match_reason"]
event["blocked_by_attempt_id"] = blocker["attempt_id"]
if blocker.get("intervention_id"):
    event["blocked_by_intervention_id"] = blocker["intervention_id"]
decision = Decision(
    dispatch="deny", would_dispatch="deny", lifecycle="continue", authority="none",
    verification="none", evidence_state="observed", severity="critical",
    reason=(material_blocker_description(blocker) + "；"
            + f"attempt={blocker['attempt_id']} "
            f"intervention={blocker.get('intervention_id') or 'not-opened'}"),
    fingerprint=fingerprint, reason_code="effect_barrier_denied", decision_stage="safety")
''').body
    assert [ast.dump(n) for n in gate.body] == [ast.dump(n) for n in expected], 'blocker denial changed'
    gate.body = copy.deepcopy(old_gate.body)
    tracks = branch(owner, 'tracks_external_effect')
    splice(tracks, '''
call_identity = str(event.get("call_id") or f"sequence:{event['sequence']}")
effect_target = _effect_attempt_target(event)
risk_grant = event.get("human_grant_dispatch") or {}
if not isinstance(risk_grant.get("effect_risk_review"), dict):
    risk_grant = {}
''', '''
call_identity = str(event.get("call_id") or f"sequence:{event['sequence']}")
effect_target = _effect_attempt_target(event)
''')
    calls = [node for node in ast.walk(tracks) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == 'begin_attempt']
    assert len(calls) == 1, 'attempt dispatch changed/duplicated'
    expected = ast.parse('''begin_attempt(
        risk_grant_transaction_id=str(risk_grant.get("transaction_id") or ""),
        risk_event=event if risk_grant else None,
        risk_dispatch=risk_grant.get("dispatch"))''', mode='eval').body.keywords
    assert [ast.dump(n) for n in calls[0].keywords[-3:]] == [ast.dump(n) for n in expected], 'broker receipt binding changed'
    del calls[0].keywords[-3:]
    return tree


def verify_decision_projection(source, original):
    """Moved Decision constructors retain every old keyword except reviewed text."""
    function = unique_owner(ast.parse(source), ('consumed_grant_decision',))
    old_owner = unique_owner(original, ('GuardianSession', '_observe_locked'))
    old_gate = branch(old_owner, 'isinstance(event.get("human_grant_dispatch"), dict)')
    decision = branch(ast.Module(body=old_gate.body, type_ignores=[]), 'blocker')
    deny = copy.deepcopy(decision.body[0].value)
    allow = copy.deepcopy(decision.orelse[0].value)
    reasons = [item for item in deny.keywords if item.arg == 'reason']
    assert len(reasons) == 1
    reasons[0].value = ast.parse('blocker_description + "；一次性授权未被执行"', mode='eval').body
    expected = ast.parse('''
def consumed_grant_decision(event: dict[str, Any], fingerprint: str,
                            blocker_description: str = "") -> Decision:
    if blocker_description:
        return None
    return None
''').body[0]
    expected.body[0].body[0].value = deny
    expected.body[1].value = allow
    if (function.body and isinstance(function.body[0], ast.Expr)
            and isinstance(function.body[0].value, ast.Constant)
            and isinstance(function.body[0].value.value, str)):
        function.body.pop(0)
    assert ast.dump(function) == ast.dump(expected), 'moved Decision projection changed'


def reverse_resources(tree):
    owner = unique_owner(tree, ('_guardian_control_command',))
    splice(owner, '''
if invocation is None:
    return None
if trusted_guardian_help(invocation):
    return {**invocation, "action": "--help", "route": "agent", "metadata_query": True}
action = str(invocation["action"])
''', '''
if invocation is None:
    return None
action = str(invocation["action"])
''')
    owner = unique_owner(tree, ('_python_source_effect',))
    splice(owner, '''
data_calls = proven_data_method_calls(tree) if literal_transport else set()
if literal_transport:
    data_calls.update(proven_datetime_method_calls(tree))
effects: list[str] = []
''', '''
data_calls = proven_data_method_calls(tree) if literal_transport else set()
effects: list[str] = []
''')
    ssh = unique_owner(tree, ('_ssh_effect',))
    expected = ast.parse((Path(__file__).with_name('guardian_u18_ssh_slice.txt')).read_text(encoding='utf-8')).body[0]
    assert ast.dump(ssh) == ast.dump(expected), 'reviewed SSH syntax classifier changed'
    index = tree.body.index(ssh)
    assert tree.body[index - 1].name == '_structured_command_effect' and tree.body[index + 1].name == '_command_effect'
    tree.body.remove(ssh)
    owner = unique_owner(tree, ('_command_effect',))
    splice(owner, '''
if not guardian["runtime_sha256"]:
    return "destructive"
if trusted_guardian_help(guardian):
    return "read"
''', '''
if not guardian["runtime_sha256"]:
    return "destructive"
''')
    splice(owner, '''
remote_effect = _ssh_effect(command_tokens)
if remote_effect is not None:
    if risks is not None:
        risks.append("remote_execution")
    if remote_effect == "unknown" and risks is not None:
        risks.append("remote_execution_unresolved")
    return remote_effect
if _is_read_only_command(command):
    return "read"
''', '''
if _is_read_only_command(command):
    return "read"
''')
    owner = unique_owner(tree, ('normalize_hook_event',))
    splice(owner, '''
continuation_candidate: dict[str, Any] | None = None
remote_request: dict[str, Any] | None = None
git_ref: dict[str, Any] | None = None
''', '''
continuation_candidate: dict[str, Any] | None = None
git_ref: dict[str, Any] | None = None
''')
    after = '''
remote_unresolved = "remote_execution_unresolved" in command_risks
remote_execution = "remote_execution" in command_risks
read_request = ssh_read_request(command) if invocation_violation is None else None
if read_request is not None:
    remote_request = read_request
    effect = "read"
    remote_unresolved = False
    uncertainty_kind = ""
if invocation_violation is None and (remote_execution or remote_unresolved) and read_request is None:
    remote_request = ssh_material_request(command)
    if remote_request is not None:
        effect = "external_write"
        remote_execution = True
        remote_unresolved = False
        uncertainty_kind = ""
destructive_risks = [risk for risk in command_risks if risk not in {"remote_execution", "remote_execution_unresolved"}]
if destructive_risks and effect != "destructive" and invocation_violation is None:
    effect = "unknown"
    invocation_violation = {
        "effect": "unknown", "kind": "unresolved-destructive-receiver",
        "reason": "对象类型未能证明；该方法可能改变文件，当前调用需明确目标和风险后再执行",
        "target": "[unresolved-destructive-receiver]", "write_targets": []}
    uncertainty_kind = "unresolved_destructive_receiver"
elif remote_unresolved and effect in {"read", "local_write", "unknown"}:
    effect = "unknown"
    uncertainty_kind = "unresolved_external_write"
trusted_composition = (
    None if git_passthrough or not _has_unquoted_shell_control(command)
    else _trusted_script_command(command, cwd=command_cwd))
'''
    before = '''
if command_risks and effect != "destructive" and invocation_violation is None:
    effect = "unknown"
    invocation_violation = {
        "effect": "unknown", "kind": "unresolved-destructive-receiver",
        "reason": "对象类型未能证明；该方法可能改变文件，当前调用需明确目标和风险后再执行",
        "target": "[unresolved-destructive-receiver]", "write_targets": []}
    uncertainty_kind = "unresolved_destructive_receiver"
trusted_composition = (
    None if git_passthrough or not _has_unquoted_shell_control(command)
    else _trusted_script_command(command, cwd=command_cwd))
'''
    splice(owner, after, before)
    gate = branch(owner, 'invocation_violation is not None')
    expected = ast.parse('''
if remote_request is not None:
    target = remote_request["target"]
elif remote_execution:
    target = "[unresolved-remote-target:" + hashlib.sha256(command.encode("utf-8")).hexdigest()[:16] + "]"
''').body[0]
    assert len(gate.orelse) == 1
    remote = copy.deepcopy(gate.orelse[0])
    assert isinstance(remote, ast.If) and len(remote.orelse) == 1
    assert isinstance(remote.orelse[0], ast.If) and len(remote.orelse[0].orelse) == 1
    tail = remote.orelse[0].orelse
    assert ast.dump(tail[0].test) == ast.dump(ast.parse('effect == "local_write" and write_targets', mode='eval').body)
    remote.orelse[0].orelse = []
    assert ast.dump(remote) == ast.dump(expected), 'remote identity target chain changed'
    gate.orelse = tail
    splice(owner, '''
if supervision_domain != "intent_guardian":
    event["supervision_domain"] = supervision_domain
    event["execution_domain"] = execution_domain
if remote_request is not None:
    event["remote_request"] = remote_request
    event["effect_resource_key"] = remote_request["resource_key"]
    event["effect_resource_context"] = remote_request["resource_context"]
    event["effect_resource_base"] = ""
    event["resource_base"] = ""
if uncertainty_kind:
    event["uncertainty_kind"] = uncertainty_kind
''', '''
if supervision_domain != "intent_guardian":
    event["supervision_domain"] = supervision_domain
    event["execution_domain"] = execution_domain
if uncertainty_kind:
    event["uncertainty_kind"] = uncertainty_kind
''')
    return tree
