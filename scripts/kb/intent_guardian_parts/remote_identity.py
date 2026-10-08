"""Literal SSH request identity, deliberately distinct from endpoint proof.

No connection, config lookup, filesystem lookup, authority or effect evidence is
created here. Remote path aliases cannot be resolved on the local machine.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from typing import Any
from command_template import split_command_template

PREFIX = "ssh-request-v1:"


def ssh_resource_identity(endpoint: dict[str, Any], path: str) -> dict[str, Any]:
    """Bind account/address/port/scope without claiming a verified endpoint."""
    if not isinstance(endpoint, dict) or set(endpoint) != {"host", "user", "port"}:
        raise ValueError("SSH identity requires exactly host, user and port")
    host = str(ipaddress.ip_address(endpoint["host"]))
    user = endpoint["user"]
    port = endpoint["port"]
    if not isinstance(user, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}", user):
        raise ValueError("SSH identity requires a literal account")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("SSH identity requires a literal port")
    if (not isinstance(path, str) or not path.startswith("/")
            or not re.fullmatch(r"/[A-Za-z0-9_./-]*", path)
            or (path != "/" and any(part in {"", ".", ".."} for part in path[1:].split("/")))):
        raise ValueError("SSH identity requires one unambiguous absolute path")
    value = json.dumps([host, user, port, path], separators=(",", ":"), ensure_ascii=True)
    target = PREFIX + value
    digest = hashlib.sha256(target.encode()).hexdigest()
    return {
        "target": target,
        "resource_key": "v2:opaque:" + target,
        "resource_context": {"schema": "exact", "value": target},
        "identity_quality": "explicit_literal_unverified_endpoint",
        "evidence": "literal account, IP, port and absolute path; SSH config excluded by caller",
        "limitations": ["no host-key or connection verification", "remote path aliases unresolved",
                        "request identity is not historical effect evidence"],
        "telemetry": {"domain": "ssh", "identity_sha256": digest,
                      "identity_quality": "explicit_literal_unverified_endpoint"},
    }


def is_ssh_request_key(key: str) -> bool:
    return str(key).startswith("v2:opaque:" + PREFIX)


def validate_ssh_identity(target: str, resource_key: str) -> bool:
    """Accept only canonical literal request bindings, never caller quality tags."""
    if not str(target).startswith(PREFIX):
        return False
    try:
        host, user, port, path = json.loads(target[len(PREFIX):])
        identity = ssh_resource_identity({"host": host, "user": user, "port": port}, path)
        return identity["target"] == target and identity["resource_key"] == resource_key
    except (ValueError, TypeError, KeyError):
        return False


def ssh_material_request(command: str) -> dict[str, Any] | None:
    return _ssh_request(command, read_only=False)


def ssh_read_request(command: str) -> dict[str, Any] | None:
    return _ssh_request(command, read_only=True)


def _read_scope(words: list[str]) -> str | None:
    """Closed argv grammar: no shells, substitutions, output files or mutations."""
    if not words:
        return None
    binary, args = words[0], words[1:]
    if binary == "/usr/bin/stat" and len(args) == 1:
        if all(re.fullmatch(r"/[A-Za-z0-9_./-]+", arg) and ".." not in arg.split("/") for arg in args):
            return args[0]
    if binary == "/usr/bin/free" and args in ([], ["-m"], ["-h"]):
        return "/"
    if binary == "/usr/bin/df" and len(args) == 2 and args[0] == "-h":
        if re.fullmatch(r"/[A-Za-z0-9_./-]*", args[1]) and ".." not in args[1].split("/"):
            return args[1]
    if binary == "/usr/bin/docker" and args and args[0] == "ps":
        tail = args[1:]
        if tail in ([], ["-a"], ["--no-trunc"]):
            return "/"
        if (len(tail) == 2 and tail[0] == "--format"
                and re.fullmatch(r"[A-Za-z0-9 .{}:_/-]{1,256}", tail[1])):
            return "/"
    return None


def _ssh_request(command: str, *, read_only: bool) -> dict[str, Any] | None:
    """Recognize exactly one bounded mkdir request; never execute SSH.

    This is a scope binding, not a claim that mkdir is reversible or authorized.
    SSH config and optional side effects are excluded with a closed grammar.
    """
    if not isinstance(command, str) or any(c in command for c in "\n\r`$;&|<>"):
        return None
    try:
        words = split_command_template(command, os_name="posix")
    except ValueError:
        return None
    if not words or words.pop(0) not in {"ssh", "/usr/bin/ssh"}:
        return None
    required = {"BatchMode=yes", "PermitLocalCommand=no", "StrictHostKeyChecking=yes", "UpdateHostKeys=no"}
    options: set[str] = set()
    port, config = 22, False
    seen_port = False
    seen_identity = False
    while words and words[0].startswith("-"):
        option = words.pop(0)
        if option in {"-n", "-T"}:
            if option in options:
                return None
            options.add(option)
        elif option == "-F" and not config and words and words.pop(0) == "/dev/null":
            config = True
        elif option == "-p" and not seen_port and words and re.fullmatch(r"[0-9]{1,5}", words[0]):
            port, seen_port = int(words.pop(0)), True
        elif option == "-i" and not seen_identity and words:
            identity_file = words.pop(0)
            if not re.fullmatch(r"/[A-Za-z0-9_./-]+", identity_file) or ".." in identity_file.split("/"):
                return None
            seen_identity = True
        elif option == "-o" and words and words[0] == "IdentitiesOnly=yes" and words[0] not in options:
            options.add(words.pop(0))
        elif (option == "-o" and words and re.fullmatch(r"ConnectTimeout=[1-9][0-9]?", words[0])
              and not any(value.startswith("ConnectTimeout=") for value in options)):
            options.add(words.pop(0))
        elif option == "-o" and words and words[0] in required and words[0] not in options:
            options.add(words.pop(0))
        else:
            return None
    if not config or not required.issubset(options) or len(words) != 2:
        return None
    destination, remote = words
    if destination.count("@") != 1:
        return None
    user, host = destination.split("@")
    try:
        remote_words = split_command_template(remote, os_name="posix")
        if read_only:
            scope = _read_scope(remote_words)
            if scope is None:
                return None
        else:
            mode_form = len(remote_words) == 6 and remote_words[1:5] == ["-p", "-m", "700", "--"]
            simple_form = len(remote_words) == 4 and remote_words[1:3] == ["-p", "--"]
            if (not (mode_form or simple_form) or remote_words[0] not in {"/bin/mkdir", "/usr/bin/mkdir"}
                    or remote_words[-1] == "/"):
                return None
            scope = remote_words[-1]
        identity = ssh_resource_identity({"host": host, "user": user, "port": port}, scope)
    except (ValueError, TypeError):
        return None
    if read_only:
        return {**identity, "effect": "read", "operation": "inspection",
                "reason": "closed read-only argv with SSH optional writes and configuration excluded"}
    return {**identity, "effect": "external_write", "operation": "mkdir_p",
            "reason": "one literal mkdir -p scope with SSH config and optional writes excluded"}
