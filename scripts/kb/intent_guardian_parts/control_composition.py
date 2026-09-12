"""Project safe control compositions without granting authority to their tails."""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shlex
from typing import Any, Callable

from shell_composition import CompositionError, literal_shell_plan
from command_template import split_command_template
from .state import READ_ONLY_AGENT_CONTROL_ACTIONS
from .event_identity import bind_host_call_identity


@dataclass(frozen=True)
class CompositionServices:
    """Explicit parser dependencies, never a back-import of the caller module."""
    normalize_hook_event: Callable
    _has_unquoted_shell_control: Callable
    _guardian_invocation: Callable
    _shell_execution_segments: Callable
    _input_digest: Callable
    _contains_sensitive_material: Callable
    _command_execution_cwd: Callable
    _guardian_control_command: Callable
    _guardian_skill_command: Callable
    _strongest_effect: Callable
    _composition_has_destructive_segment: Callable
    _local_target_label: Callable

AUDIT_CONTROL_ACTIONS = frozenset({"skill-start", "skill-end", "reconcile-verifications"})


def _json_filter(source: str) -> bool:
    """Prove a small expression-only stdin JSON formatter, not arbitrary Python."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    def expression(node: ast.AST) -> bool:
        if isinstance(node, ast.Constant):
            return True
        if isinstance(node, (ast.List, ast.Tuple)):
            return all(expression(value) for value in node.elts)
        if isinstance(node, ast.Subscript):
            return expression(node.value) and expression(node.slice)
        if isinstance(node, ast.Attribute):
            return ast.unparse(node) == "sys.stdin"
        if not isinstance(node, ast.Call) or node.keywords:
            return False
        name = ast.unparse(node.func)
        if name in {"print", "json.dumps", "json.loads", "str", "len"}:
            return all(expression(arg) for arg in node.args)
        if name == "json.load":
            return len(node.args) == 1 and ast.unparse(node.args[0]) == "sys.stdin"
        if name == "sys.stdin.read":
            return not node.args
        return bool(isinstance(node.func, ast.Attribute) and node.func.attr == "get"
                    and expression(node.func.value) and all(expression(arg) for arg in node.args))

    return bool(tree.body) and all(
        isinstance(node, ast.Import) and all(item.name in {"json", "sys"} and item.asname is None for item in node.names)
        or isinstance(node, ast.Expr) and expression(node.value)
        for node in tree.body
    )


def _filter_is_proven(command: str, effect: str) -> bool:
    """Do not inherit the broad legacy read-name allowlist for new batches."""
    argv = split_command_template(command)
    name, args = Path(argv[0]).name, argv[1:]
    if name == "printf":
        if args and args[0].startswith("-v"):
            return False
        formats = args[1:] if args and args[0] == "--" else args
        # Shell builtins support %n assignment to a caller-supplied variable.
        # Only prove output conversions; %%n is literal data, not assignment.
        return not formats or "%" not in re.sub(
            r"%%|%[-+ #0'0-9.*]*[diouxXfFeEgGaAcsbq]", "", formats[0],
        )
    if name in {"true", "false", "echo", "pwd"}:
        return True
    if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", name):
        return len(args) == 2 and args[0] == "-c" and _json_filter(args[1])
    if effect != "read":
        return False
    if name in {"cat", "head", "tail", "wc", "stat", "ls", "shasum", "sha256sum", "md5", "realpath", "jq"}:
        return True
    if name in {"rg", "grep"}:
        return not any(arg.startswith(("--pre", "--hostname-bin")) for arg in args)
    if name == "sort":
        return not any(arg.startswith(("--output", "--compress-program"))
                       or (arg.startswith("-") and not arg.startswith("--") and "o" in arg[1:])
                       for arg in args)
    if name == "sed":
        return bool(len(args) == 2 and args[0] == "-n" and re.fullmatch(r"[0-9,$]*p", args[1]))
    return False


def _local_step_is_proven(command: str, event: dict[str, Any]) -> bool:
    """Require complete operand semantics, not one target found in opaque code.

    The legacy classifier may report a known write alongside an unknown call.
    That is not enough to make the whole program an auditable control batch.
    Ordinary standalone tools keep their existing Agent-owned execution policy.
    """
    argv = split_command_template(command)
    name, args = Path(argv[0]).name, argv[1:]
    if name == "rm":
        return bool(event.get("local_file_operations") and not event.get("invocation_violation"))
    options = {
        "touch": {"-a", "-m", "-c", "-h"},
        "mkdir": {"-p"},
        "tee": {"-a", "-i"},
    }
    if name not in options:
        return False
    literal = False
    for arg in args:
        if arg == "--" and not literal:
            literal = True
        elif not literal and arg.startswith("-") and arg not in options[name]:
            return False
    return bool(event.get("write_targets"))


def normalize_composition(
    payload: dict[str, Any], command: str, *, phase: str, provider: str | None,
    services: CompositionServices,
) -> dict[str, Any] | None:
    r = services

    # Ordinary single calls pay no parser, filesystem or journal cost.
    if os.name == "nt" or "intent-guardian" not in command or not r._has_unquoted_shell_control(command):
        return None
    error = ""
    try:
        plan = literal_shell_plan(command)
    except CompositionError as exc:
        # Data mentioning a launcher is not a control invocation.
        if not any(r._guardian_invocation(part) for part in r._shell_execution_segments(command)):
            return None
        plan = ()
        error = str(exc)
    if not error and not any(r._guardian_invocation(step.command) for step in plan):
        return None
    if len(plan) == 1 and not plan[0].redirects and not error:
        return None

    base_payload = {**payload, "tool_name": "Read", "tool_input": {}}
    base_payload.pop("tool_response", None)
    base_payload.pop("response", None)
    event = r.normalize_hook_event(base_payload, phase=phase, provider=provider)
    digest = r._input_digest(payload.get("tool_input") or {"command": command})
    event.update({
        "action": "control-composition", "capability": "tool:control-composition",
        "arguments_digest": digest, "target": "[control-composition]",
        "event_id": hashlib.sha256(f"control-composition\0{digest}".encode()).hexdigest()[:24],
        "control_plane": True, "control_route": "composition",
        "control_action": "composition", "verification_kind": "unsupported",
        "verification_sha256": "", "verification_evidence": {},
        "sensitive_input": r._contains_sensitive_material(payload.get("tool_input") or {}),
    })
    steps: list[dict[str, Any]] = []
    effects: list[str] = []
    targets: list[str] = []
    operations: list[dict[str, Any]] = []
    cwd = r._command_execution_cwd(payload, payload.get("tool_input") or {})
    for number, step in enumerate(plan, 1):
        child_payload = {
            **payload, "tool_name": "Bash",
            "tool_input": {"command": step.command, "workdir": cwd},
            "success": None,
        }
        for key in ("response", "tool_response", "call_id", "tool_use_id", "callId", "toolUseId"):
            child_payload.pop(key, None)
        # Children are possible executions, not fabricated Hook completions.
        child = r.normalize_hook_event(child_payload, phase=phase, provider=provider)
        child["success"] = None
        child["verification_evidence"] = {}
        control = r._guardian_control_command(step.command)
        invocation = r._guardian_invocation(step.command)
        reason = ""
        if invocation:
            if not control or not invocation["runtime_sha256"]:
                reason = "控制入口身份未被证明"
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
        elif child.get("control_plane") or child.get("formal_maintenance") or child.get("continuation_candidate"):
            reason = "该维护步骤的密封调用和独立验证未覆盖整个组合"
        elif child.get("invocation_violation"):
            reason = str(child["invocation_violation"].get("reason") or "步骤目标或调用无法证明")
        elif child.get("supervision_domain") == "execution_passthrough":
            pass
        elif child["effect"] in {"local_write", "destructive"}:
            if not _local_step_is_proven(step.command, child):
                reason = "该写入步骤的全部动作与目标未被证明，不能借控制命令身份放行"
        elif _filter_is_proven(step.command, child["effect"]):
            child["effect"] = "read"
            child.pop("uncertainty_kind", None)
        else:
            reason = "该步骤的效果未被独立证明，或缺少逐步外部效果验证"
        if reason and not error:
            error = f"第 {number} 步：{reason}"
        steps.append({"index": number, "after": step.after, "event": child, "outcome": "not_observed"})
        if child.get("supervision_domain") != "execution_passthrough":
            effects.append(child["effect"])
        targets.extend(child.get("write_targets", []))
        operations.extend(child.get("local_file_operations", []))
        for operator, target in step.redirects:
            if "<" in operator or "&" in operator or target == "/dev/null":
                continue
            redirect_payload = {
                **child_payload, "tool_input": {"command": shlex.join(["touch", "--", target]), "workdir": cwd},
            }
            redirect = r.normalize_hook_event(redirect_payload, phase=phase, provider=provider)
            redirect["success"] = None
            steps.append({"index": number, "after": "redirect", "event": redirect, "outcome": "not_observed"})
            effects.append(redirect["effect"])
            targets.extend(redirect.get("write_targets", []))
    event["composition"] = {
        "schema": "sulde-control-composition-v1", "steps": steps,
        "error": error, "authority_transferred": False,
        "execution_semantics": "original-shell", "step_outcomes": "not_observed",
        "automatic_retry": False,
    }
    event["effect"] = r._strongest_effect(effects or ["read"])
    if error:
        event["effect"] = "destructive" if r._composition_has_destructive_segment(command, cwd=cwd) else "unknown"
    if targets:
        event["write_targets"] = list(dict.fromkeys(targets))
        event["target"] = r._local_target_label(event["write_targets"])
    if operations:
        event["local_file_operations"] = operations
        event["destructive_local_operation"] = True
        event["high_risk_local_operation"] = any(s["event"].get("high_risk_local_operation") for s in steps)
    # Mixed material calls retain ordinary event/effect accounting. Pure
    # audit commands use their own CLI journals, never fake nested Hook facts.
    if event["effect"] != "read" and not error:
        for key in ("control_plane", "control_route", "control_action"):
            event.pop(key, None)
    # The base Read projection and intermediate target are not the final call.
    # Rebind only after all final action/target/digest fields are known.
    bind_host_call_identity(event)
    return event
