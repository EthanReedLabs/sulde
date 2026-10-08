"""Bounded semantic evidence, without authority, execution or remote I/O."""
from __future__ import annotations

import ast
import ipaddress
import re
from typing import Any

from command_template import has_unquoted_shell_control, split_command_template
from .state import AGENT_CONTROL_ACTIONS, HUMAN_CONTROL_ACTIONS, NATIVE_PERMISSION_CONTROL_ACTIONS


def trusted_guardian_help(invocation: dict[str, Any] | None) -> bool:
    """Only the trusted parser's exact help forms are metadata queries."""
    if not invocation or not invocation.get("runtime_sha256") or invocation.get("chained"):
        return False
    args = invocation["tokens"][int(invocation["action_index"]):]
    actions = AGENT_CONTROL_ACTIONS | HUMAN_CONTROL_ACTIONS | NATIVE_PERMISSION_CONTROL_ACTIONS
    return args in (["--help"], ["-h"]) or (
        len(args) == 2 and args[0] in actions and args[1] in {"--help", "-h"}
    )


def proven_datetime_method_calls(tree: ast.Module) -> set[int]:
    """Prove exact datetime values in bounded straight-line module statements.

    Returned IDs include the factories, so consumers need no method-name
    exemption. Unknown calls/control flow invalidate borrowed import facts;
    delayed scopes never borrow these facts. Arguments remain independently
    classified by the caller.
    """
    if not any((isinstance(node, ast.Import) and any(item.name == "datetime" for item in node.names))
               or (isinstance(node, ast.ImportFrom) and node.module == "datetime") for node in tree.body):
        return set()
    for count, _ in enumerate(ast.walk(tree), 1):
        if count > 2048:
            return set()
    facts: dict[str, str] = {}
    proved: set[int] = set()
    intact = True

    def barrier() -> None:
        nonlocal intact
        facts.clear()
        intact = False

    def expression(node: ast.AST, depth: int = 0) -> str:
        if depth > 32:
            barrier()
            return ""
        if isinstance(node, ast.Constant):
            return {str: "str", int: "int", type(None): "none"}.get(type(node.value), "")
        if isinstance(node, ast.Name):
            return facts.get(node.id, "")
        if isinstance(node, ast.Attribute):
            receiver = expression(node.value, depth + 1)
            value = {("module", "datetime"): "factory", ("module", "timezone"): "timezone",
                     ("timezone", "utc"): "tz"}.get((receiver, node.attr), "")
            if value and intact:
                return value
            barrier()
            return ""
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                receiver = expression(node.func.value, depth + 1)
                method = node.func.attr
            else:
                receiver, method = expression(node.func, depth + 1), ""
            arguments = [expression(arg, depth + 1) for arg in node.args]
            keywords = [(item.arg, expression(item.value, depth + 1)) for item in node.keywords]
            result = ""
            if intact and receiver == "factory" and method == "fromisoformat" and arguments == ["str"] and not keywords:
                result = "datetime"
            elif intact and receiver == "datetime" and method == "replace" and not arguments and keywords:
                if all((key == "tzinfo" and kind in {"tz", "none"}) or
                       (key in {"year", "month", "day", "hour", "minute", "second", "microsecond", "fold"} and kind == "int")
                       for key, kind in keywords):
                    result = "datetime"
            elif intact and receiver == "datetime" and method == "isoformat" and not arguments and not keywords:
                result = "str"
            if result:
                proved.add(id(node))
                return result
            if (isinstance(node.func, ast.Name) and node.func.id == "print" and "print" not in facts
                    and intact and not keywords and all(value in {"str", "int", "none", "datetime"} for value in arguments)):
                return "none"
            barrier()
            return ""
        barrier()
        return ""

    for statement in tree.body:
        if isinstance(statement, ast.Import) and intact and all(item.name == "datetime" for item in statement.names):
            for item in statement.names:
                facts[item.asname or item.name] = "module"
        elif (isinstance(statement, ast.ImportFrom) and intact and statement.module == "datetime"
              and not statement.level and all(item.name in {"datetime", "timezone"} for item in statement.names)):
            for item in statement.names:
                facts[item.asname or item.name] = "factory" if item.name == "datetime" else "timezone"
        elif (isinstance(statement, ast.Assign) and len(statement.targets) == 1
              and isinstance(statement.targets[0], ast.Name)):
            value = expression(statement.value)
            facts[statement.targets[0].id] = value
        elif isinstance(statement, ast.Expr):
            expression(statement.value)
        else:
            barrier()
    return proved


def ssh_readonly_probe(tokens: list[str]) -> dict[str, Any] | None:
    """Syntactic read evidence for one config-free explicit-IP SSH probe.

    No lookup/connection or host-key proof is performed. The result cannot
    authorize disclosure, prove a historical endpoint, or settle an attempt.
    """
    if not tokens or tokens[0] not in {"ssh", "/usr/bin/ssh"} or len(tokens) > 24:
        return None
    required = {"BatchMode": "yes", "PermitLocalCommand": "no",
                "StrictHostKeyChecking": "yes", "UpdateHostKeys": "no"}
    seen: dict[str, str] = {}
    port = 22
    index = 1
    config = False
    port_seen = False
    while index < len(tokens) and tokens[index].startswith("-"):
        option = tokens[index]
        if option in {"-n", "-T"}:
            index += 1
            continue
        if option not in {"-F", "-o", "-p"} or index + 1 >= len(tokens):
            return None
        value = tokens[index + 1]
        index += 2
        if option == "-F":
            if config or value != "/dev/null":
                return None
            config = True
        elif option == "-p":
            if port_seen or not re.fullmatch(r"[0-9]{1,5}", value) or not 1 <= int(value) <= 65535:
                return None
            port, port_seen = int(value), True
        else:
            key, separator, setting = value.partition("=")
            if not separator or key in seen or required.get(key) != setting:
                return None
            seen[key] = setting
    if not config or seen != required or len(tokens) != index + 2:
        return None
    account, separator, host = tokens[index].partition("@")
    if not separator or not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_.-]{0,63}", account):
        return None
    try:
        host = str(ipaddress.ip_address(host))
    except ValueError:
        return None
    remote = tokens[index + 1]
    if has_unquoted_shell_control(remote) or any(char in remote for char in "$`\\\n\r*?[]{}~"):
        return None
    try:
        argv = split_command_template(remote, os_name="posix")
    except ValueError:
        return None
    if len(argv) == 3 and argv[:2] == ["/usr/bin/stat", "--"]:
        operation = "stat"
    elif len(argv) == 4 and argv[:3] == ["/bin/ls", "-ld", "--"]:
        operation = "ls"
    else:
        return None
    path = argv[-1]
    if not path.startswith("/") or any(part in {"", ".", ".."} for part in path[1:].split("/")):
        return None
    return {
        "effect": "read", "reason": "bounded_ssh_metadata_probe",
        "evidence": "literal_ip_account_config_disabled_fixed_remote_argv",
        "endpoint": {"host": host, "user": account, "port": port},
        "path": path, "operation": operation,
        "identity_quality": "explicit_literal_unverified_endpoint",
        "limitations": ["no_connection_or_host_key_validation", "remote_read_is_not_disclosure_authority",
                        "not_historical_effect_verification"],
    }
