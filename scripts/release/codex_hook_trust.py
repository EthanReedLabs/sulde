"""Exact, human-bound native Hook trust transition; never an auto-trust policy.

The installer supplies a sealed v2 maintenance context. Ordinary Hook inventory
is read-only. Only the six approved user-layer values are edited through Codex's
atomic, version-checked API; recovery never restores the whole configuration.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import time

SCHEMA = "sulde-exact-hook-trust-v1"
PLUGIN = "sulde@sulde-local"
EVENTS = ("preToolUse", "permissionRequest", "postToolUse", "sessionStart", "userPromptSubmit", "stop")
HASH = re.compile(r"sha256:[0-9a-f]{64}")


class TrustError(ValueError):
    pass


class NativeRejected(TrustError):
    """A received RPC error, distinct from an unobserved write outcome."""
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class NativeClient:
    """Short-lived configuration RPC client, no thread/model or bypass flags."""
    def __init__(self, codex, *, environment=None, timeout=20):
        self.timeout = timeout
        self.process = subprocess.Popen([str(codex), "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=environment, bufsize=0)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.selector.register(self.process.stderr, selectors.EVENT_READ)
        self.buffer, self.stderr, self.identifier = bytearray(), bytearray(), 0
        try:
            self.call("initialize", {"clientInfo": {"name": "sulde_exact_hook_trust", "version": "1"}})
            self.send({"method": "initialized", "params": {}})
        except BaseException:
            self.close()
            raise

    def send(self, value):
        raw = (json.dumps(value, separators=(",", ":")) + "\n").encode()
        stream = self.process.stdin
        view = memoryview(raw)
        while view:
            count = stream.write(view)
            if not count:
                raise TrustError("native configuration input closed")
            view = view[count:]
        stream.flush()

    def call(self, method, params):
        self.identifier += 1
        identifier = self.identifier
        self.send({"id": identifier, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            while b"\n" in self.buffer:
                line, _, rest = self.buffer.partition(b"\n")
                self.buffer[:] = rest
                try:
                    reply = json.loads(line)
                except (ValueError, UnicodeError) as error:
                    raise TrustError("malformed native configuration response") from error
                if reply.get("id") == identifier:
                    if "error" in reply:
                        error = reply["error"]
                        raise NativeRejected(f"native {method} rejected: {str(error)[:600]}",
                            error.get("code") if isinstance(error, dict) else None)
                    if not isinstance(reply.get("result"), dict):
                        raise TrustError("native configuration result is malformed")
                    return reply["result"]
                if "id" in reply and "method" in reply:
                    raise TrustError("unexpected host decision request; no automatic reply")
            for key, _ in self.selector.select(.1):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    self.selector.unregister(key.fileobj)
                elif key.fileobj is self.process.stderr:
                    self.stderr[:] = (self.stderr + chunk)[-4096:]
                else:
                    self.buffer.extend(chunk)
                    if len(self.buffer) > 8 * 1024 * 1024:
                        raise TrustError("native configuration response exceeds bound")
            if self.process.poll() is not None and b"\n" not in self.buffer:
                raise TrustError(f"native {method} process ended before response")
        raise TrustError(f"native {method} timed out")

    def close(self):
        self.selector.close()
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
        for stream in (self.process.stdout, self.process.stderr):
            if stream:
                stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def definitions(payload, *, cwd, plugin_root):
    """Canonical native definitions: only source root is relocation-normalized."""
    rows = [r for r in payload.get("data", []) if r.get("cwd") == str(Path(cwd).resolve())]
    if len(rows) != 1 or rows[0].get("errors") != []:
        raise TrustError("native Hook discovery is missing, ambiguous or has errors")
    hooks = [h for h in rows[0].get("hooks", []) if h.get("pluginId") == PLUGIN]
    if len(hooks) != 6 or sorted(h.get("eventName", "") for h in hooks) != sorted(EVENTS):
        raise TrustError("native Sulde Hooks are missing or duplicated")
    result = []
    for hook in hooks:
        if (hook.get("source") != "plugin" or hook.get("handlerType") != "command"
                or hook.get("enabled") is not True or hook.get("isManaged") is not False
                or not HASH.fullmatch(str(hook.get("currentHash", "")))):
            raise TrustError("native Hook is disabled, managed or not a command")
        source = Path(hook.get("sourcePath", ""))
        if not source.is_absolute() or not source.resolve().is_relative_to(Path(plugin_root).resolve()):
            raise TrustError("native Hook source is outside exact candidate")
        row = {key: hook.get(key) for key in ("key", "eventName", "currentHash", "command", "matcher",
            "timeoutSec", "async", "additionalContextLimit")}
        row["source"] = source.resolve().relative_to(Path(plugin_root).resolve()).as_posix()
        result.append(row)
    return sorted(result, key=lambda row: row["key"])


def validate_plan(plan):
    if not isinstance(plan, dict) or set(plan) != {"schema", "config_file", "definitions", "previous", "artifact_tree_sha256"}:
        raise TrustError("exact Hook trust plan fields differ")
    if plan["schema"] != SCHEMA or not re.fullmatch(r"[0-9a-f]{64}", str(plan["artifact_tree_sha256"])):
        raise TrustError("invalid Hook trust plan identity")
    config = Path(plan["config_file"])
    if not config.is_absolute() or config.resolve() != config or config.name != "config.toml":
        raise TrustError("noncanonical user configuration path")
    rows = plan["definitions"]
    if not isinstance(rows, list) or len(rows) != 6 or any(not isinstance(r, dict) for r in rows):
        raise TrustError("exactly six Hook definitions are required")
    if sorted(r.get("eventName", "") for r in rows) != sorted(EVENTS):
        raise TrustError("Hook trust events differ")
    keys = [r.get("key") for r in rows]
    if len(set(keys)) != 6 or any(not isinstance(k, str) or not k.startswith(PLUGIN + ":hooks/hooks.json:") for k in keys):
        raise TrustError("Hook trust keys are ambiguous or foreign")
    if not isinstance(plan["previous"], dict) or set(plan["previous"]) != set(keys):
        raise TrustError("old Hook trust values are incomplete")
    for row in rows:
        if (set(row) != {"key", "eventName", "currentHash", "command", "matcher", "timeoutSec", "async", "additionalContextLimit", "source"}
                or not isinstance(row["command"], str) or not row["command"]
                or row["source"] != "hooks/hooks.json"
                or not HASH.fullmatch(str(row["currentHash"]))
                or not HASH.fullmatch(str(plan["previous"][row["key"]]))):
            raise TrustError("Hook trust definition or previous value is invalid")
    return plan


def read_values(client, plan, *, cwd):
    payload = client.call("config/read", {"includeLayers": True, "cwd": str(Path(cwd).resolve())})
    layers = [r for r in payload.get("layers") or []
        if r.get("name", {}).get("type") == "user"
        and r["name"].get("file") == plan["config_file"]
        and r["name"].get("profile") is None and not r.get("disabledReason")]
    if len(layers) != 1 or not isinstance(layers[0].get("version"), str) or not layers[0]["version"]:
        raise TrustError("exact native user configuration layer/version unavailable")
    layer = layers[0]
    states = layer["config"].get("hooks", {}).get("state", {})
    values = {key: states.get(key, {}).get("trusted_hash") for key in plan["previous"]}
    return {"version": layer["version"], "values": values}


def desired(plan):
    return {row["key"]: row["currentHash"] for row in plan["definitions"]}


def prepare_plan(*, codex, config_file, artifact_tree_sha256, candidate_environment,
                 candidate_root, candidate_cwd, production_cwd, production_environment):
    """Read native facts; preparing a card does not authorize its execution."""
    with NativeClient(codex, environment=candidate_environment) as client:
        payload = client.call("hooks/list", {"cwds": [str(candidate_cwd.resolve())]})
        rows = definitions(payload, cwd=candidate_cwd, plugin_root=candidate_root)
    plan = {"schema": SCHEMA, "config_file": str(config_file.resolve()),
        "artifact_tree_sha256": artifact_tree_sha256, "definitions": rows,
        "previous": {row["key"]: None for row in rows}}
    with NativeClient(codex, environment=production_environment) as client:
        plan["previous"] = read_values(client, plan, cwd=production_cwd)["values"]
    return validate_plan(plan)


def write_values(client, plan, snapshot, values):
    return client.call("config/batchWrite", {
        "filePath": plan["config_file"], "expectedVersion": snapshot["version"], "reloadUserConfig": False,
        "edits": [{"keyPath": "hooks.state." + json.dumps(key) + ".trusted_hash",
                   "mergeStrategy": "replace", "value": value} for key, value in sorted(values.items())]})


def record(transaction, kind, value):
    """Append evidence, no secrets/full user config and no rewriting old facts."""
    raw = (json.dumps({"kind": kind, "transaction_id": transaction.transaction_id,
        "descriptor_sha256": transaction.descriptor_sha256, "value": value}, sort_keys=True) + "\n").encode()
    path = transaction.transaction_root / ("hook-trust-" + kind + "-" + str(time.time_ns()) + ".json")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    from install_transaction_journal import _fsync_directory
    _fsync_directory(path.parent)


def _validate_write_reply(reply, plan):
    if (not isinstance(reply, dict) or reply.get("status") not in {"ok", "okOverridden"}
            or reply.get("filePath") != plan["config_file"]
            or not isinstance(reply.get("version"), str) or not reply["version"]):
        raise TrustError("native Hook trust write acknowledgement is invalid")


def _has_write_ack(transaction, plan):
    """Write intent/current equality is not proof of winning the native CAS."""
    from install_transaction_journal import _read_secure, _validate_metadata
    _validate_metadata(transaction.transaction_root, directory=True)
    paths = list(transaction.transaction_root.glob("hook-trust-write-ack-*.json"))
    if not paths:
        return False
    if len(paths) != 1:
        raise TrustError("Hook trust write acknowledgement is ambiguous")
    try:
        row = json.loads(_read_secure(paths[0]))
        if (not isinstance(row, dict)
                or set(row) != {"kind", "transaction_id", "descriptor_sha256", "value"}
                or row["kind"] != "write-ack"
                or row["transaction_id"] != transaction.transaction_id
                or row["descriptor_sha256"] != transaction.descriptor_sha256):
            raise TrustError("Hook trust write acknowledgement identity differs")
        value = row["value"]
        if (not isinstance(value, dict) or set(value) != {"expected_version", "values", "reply"}
                or not isinstance(value["expected_version"], str) or not value["expected_version"]
                or value["values"] != desired(plan)):
            raise TrustError("Hook trust write acknowledgement request differs")
        _validate_write_reply(value["reply"], plan)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise TrustError("Hook trust write acknowledgement cannot be verified") from error
    return True


def apply(transaction, *, codex, cwd, plugin_root, client_factory=NativeClient):
    plan = validate_plan(transaction.descriptor["expected_postconditions"]["hook_trust"])
    with client_factory(codex) as client:
        observation = client.call("hooks/list", {"cwds": [str(Path(cwd).resolve())]})
        # Retain exact native discovery even when validation rejects it.
        record(transaction, "discovery", {"data": [{**row,
            "hooks": [hook for hook in row.get("hooks", []) if hook.get("pluginId") == PLUGIN]}
            for row in observation.get("data", [])]})
        if definitions(observation, cwd=cwd, plugin_root=plugin_root) != plan["definitions"]:
            raise TrustError("production Hook definition differs from human-reviewed candidate")
        before = read_values(client, plan, cwd=cwd)
        if before["values"] != plan["previous"]:
            raise TrustError("approved Hook trust prestate changed")
        record(transaction, "before", before)
        transaction.append("hook_trust_write_started")
        try:
            reply = write_values(client, plan, before, desired(plan))
            _validate_write_reply(reply, plan)
        except NativeRejected as error:
            record(transaction, "write-outcome", {"outcome": "rejected", "code": error.code})
            raise
        except Exception:
            record(transaction, "write-outcome", {"outcome": "unknown"})
            raise
        # A crash/lost response before this durable receipt leaves ownership
        # unknown. Do not manufacture an acknowledgement from later readback.
        record(transaction, "write-ack", {"expected_version": before["version"],
            "values": desired(plan), "reply": reply})
        record(transaction, "response", reply)
        after = read_values(client, plan, cwd=cwd)
        if after["values"] != desired(plan) or reply.get("status") != "ok":
            raise TrustError("native Hook trust write not independently verified")
        verify(plan, codex=codex, cwd=cwd, plugin_root=plugin_root, client=client)
        record(transaction, "verified", after)
        transaction.append("hook_trust_written")


def verify(plan, *, codex, cwd, plugin_root, client=None):
    validate_plan(plan)
    if client is None:
        with NativeClient(codex) as connection:
            return verify(plan, codex=codex, cwd=cwd, plugin_root=plugin_root, client=connection)
    if read_values(client, plan, cwd=cwd)["values"] != desired(plan):
        raise TrustError("installed Hook trust values differ")
    payload = client.call("hooks/list", {"cwds": [str(Path(cwd).resolve())]})
    if definitions(payload, cwd=cwd, plugin_root=plugin_root) != plan["definitions"]:
        raise TrustError("installed Hook definition identity differs")
    hooks = [h for r in payload["data"] for h in r["hooks"] if h.get("pluginId") == PLUGIN]
    if any(h.get("trustStatus") != "trusted" for h in hooks):
        raise TrustError("native host did not trust exact approved definitions")


def verify_previous(plan, *, codex, cwd, client_factory=NativeClient):
    validate_plan(plan)
    with client_factory(codex) as client:
        if read_values(client, plan, cwd=cwd)["values"] != plan["previous"]:
            raise TrustError("restored Hook trust values differ")


def restore(transaction, *, codex, cwd, client_factory=NativeClient, audit_transaction=None):
    plan = transaction.descriptor["expected_postconditions"].get("hook_trust")
    if plan is None:
        return
    validate_plan(plan)
    audit = audit_transaction if audit_transaction is not None else transaction
    started = any(row["stage"] == "hook_trust_write_started" for row in transaction.read_records())
    with client_factory(codex) as client:
        current = read_values(client, plan, cwd=cwd)
        if current["values"] == plan["previous"]:
            record(audit, "restored-or-unchanged", current)
            return
        if not started or current["values"] != desired(plan) or not _has_write_ack(transaction, plan):
            raise TrustError("Hook trust recovery conflict; retain transaction, no configuration overwrite")
        # Only acknowledged writes still matching their intended values can be
        # compensated; fresh CAS also preserves unrelated concurrent edits.
        record(audit, "restore-before", current)
        reply = write_values(client, plan, current, plan["previous"])
        record(audit, "restore-response", reply)
        after = read_values(client, plan, cwd=cwd)
        if after["values"] != plan["previous"] or reply.get("status") != "ok":
            raise TrustError("Hook trust restoration not independently verified")
        record(audit, "restored", after)
