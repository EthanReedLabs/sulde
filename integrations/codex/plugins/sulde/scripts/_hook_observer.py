#!/usr/bin/env python3
"""Bounded Hook telemetry; no Guardian imports, policy or effect settlement.

The wrapper observes only children it starts. Host/pre-wrapper failures require
host results via ingest; absence of such results is an explicit blind spot.
Only schema facts survive. Payload, command, stdout and stderr are never stored.
"""
from __future__ import annotations

from contextlib import closing
# Optional CPython builtin avoids loading OpenSSL merely to hash telemetry IDs.
# Other interpreter layouts use the public stdlib implementation. This is SHA256
# in both cases, never an authorization/signing primitive or a weaker hash.
try:
    from _sha256 import sha256
except ImportError:
    from hashlib import sha256
import json
import os
import re
import sys
import time

VERSION = "hook-observer-v1"
CAPACITY = 2048
TAIL_BYTES = 8192
CATEGORIES = {"normal", "policy_rejection", "script_missing", "internal_exception", "timeout",
              "interpreter_or_executable_unavailable", "nonzero_exit", "unknown"}
BLIND_SPOTS = ["host_events_not_delivered", "observer_or_interpreter_cannot_start", "host_kills_entire_process_tree"]


def digest(value):
    return sha256(str(value).encode("utf-8", "replace")).hexdigest()


def home():
    from pathlib import Path
    return Path(os.environ.get("SULDE_KB_HOME") or Path.home() / ".sulde/data/kb")


def identity(path):
    try:
        with open(path, "rb") as source:
            return sha256(source.read()).hexdigest()
    except OSError:
        return "unknown"


def command_module(command):
    """Identify only a directly named script, never hash an argument as code."""
    from pathlib import Path
    if not command:
        return "unknown"
    first = Path(command[0])
    if first.suffix in {".py", ".sh", ".ps1", ".mjs", ".js"}:
        return identity(first)
    arguments = command[1:]
    if re.fullmatch(r"python(?:3(?:\.\d+)?)?(?:\.exe)?", first.name):
        while arguments and arguments[0] in {"-B", "-I", "-u", "-s", "-E"}:
            arguments = arguments[1:]
    elif first.name not in {"node", "node.exe", "sh", "bash", "zsh", "pwsh", "powershell"}:
        return "unknown"
    return identity(Path(arguments[0])) if arguments and not arguments[0].startswith("-") else "unknown"


def database(root):
    return root / "hook-observer" / "observations.sqlite3"


def record(row, root=None):
    """Bounded, idempotent, short transaction; never retry a business action."""
    import sqlite3
    # A normal write needs no pathlib/package discovery. Public read helpers
    # retain their Path interface; failure and native-import paths load lazily.
    root = root or os.environ.get("SULDE_KB_HOME") or os.path.join(os.path.expanduser("~"), ".sulde/data/kb")
    directory = os.path.join(root, "hook-observer")
    path = os.path.join(directory, "observations.sqlite3")
    try:
        os.makedirs(directory, exist_ok=True, mode=0o700)
        if os.path.islink(path) or os.path.islink(directory):
            raise OSError("unsafe recorder path")
        with closing(sqlite3.connect(path, timeout=0.05)) as conn, conn:
            os.chmod(path, 0o600)
            conn.execute("PRAGMA max_page_count=4096")
            conn.execute("CREATE TABLE IF NOT EXISTS observations (id TEXT PRIMARY KEY, at TEXT NOT NULL, row TEXT NOT NULL)")
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM observations WHERE id=?", (row["id"],)).fetchone():
                return True
            if conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] >= CAPACITY:
                raise OSError("buffer full")
            conn.execute("INSERT INTO observations VALUES (?,?,?)", (row["id"], row["at"], json.dumps(row, sort_keys=True)))
        return True
    except (OSError, sqlite3.Error):
        # The host can observe this even when the entire data root is unwritable.
        print("sulde: hook_observer_delivery_unavailable; action_not_retried", file=sys.stderr)
        return False


def read_rows(root):
    import sqlite3
    path = database(root)
    if not path.exists():
        return {"status": "unobserved", "rows": [], "reason": "no_recorder_database", "blind_spots": BLIND_SPOTS}
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=0.05)) as conn:
            rows = [json.loads(x[0]) for x in conn.execute("SELECT row FROM observations ORDER BY at,id LIMIT ?", (CAPACITY,))]
        return {"status": "saturated" if len(rows) >= CAPACITY else "observed", "rows": rows,
                "blind_spots": BLIND_SPOTS}
    except (OSError, ValueError, sqlite3.Error):
        return {"status": "unavailable", "rows": [], "reason": "recorder_read_failed", "blind_spots": BLIND_SPOTS}


def codex_notification(event, workspace):
    """Actual app-server hook/completed schema, without storing output entries.

    Codex 0.153.4 supplies status but no independent exitCode or tool outcome.
    SourcePath identifies the definition, never the executed module/artifact.
    The caller must supply the thread's workspace; a missing mapping stays unknown.
    """
    from datetime import datetime, timezone
    if event.get("method") != "hook/completed":
        raise ValueError("not a completed Hook notification")
    params = event["params"]
    run = params["run"]
    status = run.get("status")
    if status not in {"completed", "failed", "blocked", "stopped"} or not run.get("id") or not params.get("threadId"):
        raise ValueError("invalid terminal Hook notification")
    hook_event = run.get("eventName", "unknown")
    if hook_event not in {"preToolUse", "permissionRequest", "postToolUse", "preCompact", "postCompact", "sessionStart", "sessionEnd", "userPromptSubmit", "subagentStart", "subagentStop", "stop", "interrupt"}:
        hook_event = "unknown"
    payload = {"session_id": params["threadId"], "cwd": workspace or "unknown",
               "call_id": json.dumps([run["id"], params.get("turnId"), run.get("startedAt"), run.get("completedAt")])}
    # Native 0.153.4 emits this exact error entry, but has no exitCode field.
    # Do not infer a zero exit from a completed notification or parse arbitrary text.
    codes = set()
    for entry in run.get("entries", []):
        if isinstance(entry, dict) and entry.get("kind") == "error":
            match = re.fullmatch(r"hook exited with code ([0-9]{1,3})", str(entry.get("text", "")))
            if match and int(match[1]) <= 255:
                codes.add(int(match[1]))
    code = next(iter(codes)) if len(codes) == 1 else None
    row = facts(hook=json.dumps([run.get("sourcePath", "unknown"), hook_event, run.get("displayOrder")]),
                stage="host", payload=payload, code=code,
                kind="nonzero_exit" if code else "normal" if status == "completed" else "unknown", source="codex_appserver_notification")
    row.update(host_status=status, hook_event=hook_event,
               source_kind=run.get("source") if run.get("source") in {"system", "user", "project", "plugin", "sessionFlags"} else "unknown",
               source_definition_id=digest(run.get("sourcePath", "unknown")),
               turn_id=digest(params["turnId"]) if params.get("turnId") else "unknown")
    if not workspace:
        row.update(workspace_id="unknown", lane_id="unknown")
    completed_at = run.get("completedAt")
    if type(completed_at) is int:
        row["at"] = datetime.fromtimestamp(completed_at, timezone.utc).isoformat()
    duration = run.get("durationMs")
    if type(duration) is int and duration >= 0:
        row["duration_ms"] = duration
    return row


def facts(*, hook, stage, payload, code, kind, source="wrapper", invocation=None,
          module="unknown", artifact="unknown", permission="unknown", duration_ms=None):
    session = payload.get("session_id") or os.environ.get("CODEX_THREAD_ID") or "unknown"
    workspace = payload.get("cwd") or payload.get("workspace_root") or os.getcwd()
    call = payload.get("tool_use_id") or payload.get("call_id") or invocation
    if not call:
        import uuid
        call = str(uuid.uuid4())
    # IDs are hashes to prevent arbitrary host strings carrying private content.
    seconds, nanoseconds = divmod(time.time_ns(), 1_000_000_000)
    at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(seconds)) + f".{nanoseconds // 1000:06d}+00:00"
    row = {"schema": VERSION, "source": source, "provider": "codex",
           "session_id": digest(session) if session != "unknown" else "unknown",
           "workspace_id": digest(workspace), "lane_id": digest(str(session) + str(workspace)),
           "hook_id": digest(hook), "phase": stage if stage in {"adapter", "bridge", "runtime", "wrapper", "host"} else "unknown",
           "call_id": digest(call), "at": at,
           "exit_code": code, "error_category": kind,
           "loaded_module_generation": module, "artifact_generation": artifact,
           "permission_decision": permission, "tool_result": "unknown",
           "audit_delivery": "recorded", "authority": "telemetry_only",
           "intent_id": digest(payload.get("intent_id") or os.environ.get("SULDE_INTENT_ID")) if payload.get("intent_id") or os.environ.get("SULDE_INTENT_ID") else "unknown",
           "duration_ms": duration_ms}
    # PostToolUse is the host's successful-tool event. It does not verify the
    # business effect, nor does its presence report the outcome of any Hook.
    if (payload.get("hook_event_name") == "PostToolUse" and payload.get("tool_use_id")
            and "tool_response" in payload):
        row.update(tool_result="success", tool_result_basis="codex_post_tool_use_contract",
                   business_effect="unverified")
    row["hook_event"] = payload.get("hook_event_name") if payload.get("hook_event_name") in {
        "PostToolUse", "PreToolUse", "PermissionRequest", "SessionStart", "Stop"} else "unknown"
    row["source_kind"] = hook.split(":", 1)[0] if hook.split(":", 1)[0] in {
        "sulde", "project", "third_party"} else "unknown"
    row["fingerprint"] = digest(json.dumps([row[k] for k in ("provider", "workspace_id", "hook_id", "phase", "error_category")]))
    row["id"] = digest(json.dumps([row[k] for k in ("session_id", "workspace_id", "hook_id", "phase", "call_id", "exit_code", "error_category", "loaded_module_generation", "artifact_generation")]))
    return row


def classify(code, stderr, stdout, timeout=False):
    if timeout:
        return "timeout", "unknown"
    try:
        decision = json.loads(stdout).get("hookSpecificOutput", {}).get("permissionDecision")
    except (ValueError, AttributeError):
        decision = None
    if decision == "deny":
        return "policy_rejection", "deny"
    if code == 0:
        return "normal", "unknown"
    if b"No such file" in stderr or b"can't open file" in stderr or b"MODULE_NOT_FOUND" in stderr:
        return "script_missing", "unknown"
    if b"Traceback" in stderr:
        return "internal_exception", "unknown"
    return "nonzero_exit", "unknown"


def observe_adapter(adapter, raw, code, stdout, stderr):
    """Called inside the verified bridge process; recording is never authority."""
    try:
        payload = json.loads(raw or b"{}")
        if not isinstance(payload, dict):
            payload = {}
        kind, permission = classify(code, stderr[-TAIL_BYTES:], stdout[-TAIL_BYTES:])
        row = facts(hook="sulde:" + adapter.stem, stage="adapter", payload=payload,
                    code=code, kind=kind, permission=permission, module=identity(adapter),
                    artifact=identity(adapter.parent.parent / ".codex-plugin/generation.json"))
        record(row)
    except Exception:
        print("sulde: hook_observer_delivery_unavailable; action_not_retried", file=sys.stderr)


def run(args):
    from pathlib import Path
    import signal
    import subprocess
    import threading
    start = time.monotonic()
    # Forward the payload unchanged; only small metadata is interpreted.
    raw = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        print("sulde: hook_observer_payload_limit", file=sys.stderr)
        return 65
    try:
        payload = json.loads(raw or b"{}")
        if not isinstance(payload, dict):
            payload = {}
    except ValueError:
        payload = {}
    tails = {"stdout": bytearray(), "stderr": bytearray()}
    def forward(pipe, target, name):
        while True:
            chunk = pipe.read(4096)
            if not chunk:
                break
            tails[name].extend(chunk)
            del tails[name][:-TAIL_BYTES]
            try:
                target.write(chunk)
                target.flush()
            except (BrokenPipeError, OSError):
                pass
        pipe.close()
    timed_out = False
    module_before = command_module(args.command)
    artifact = Path(__file__).resolve().parents[1] / ".codex-plugin/generation.json"
    artifact_before = identity(artifact)
    try:
        process = subprocess.Popen(args.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=os.name != "nt")
        threads = [threading.Thread(target=forward, args=(getattr(process, name), getattr(sys, name).buffer, name), daemon=True) for name in tails]
        for thread in threads:
            thread.start()
        def feed():
            try:
                process.stdin.write(raw)
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        feeder = threading.Thread(target=feed, daemon=True)
        feeder.start()
        def expire():
            nonlocal timed_out
            if process.poll() is None:
                timed_out = True
                try:
                    if os.name == "nt":
                        process.kill()
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        timer = threading.Timer(args.timeout, expire)
        timer.daemon = True
        timer.start()
        try:
            code = process.wait()
        finally:
            timer.cancel()
            timer.join()
        if timed_out:
            code = 124
        for thread in threads:
            thread.join(timeout=1)
        kind, permission = classify(code, tails["stderr"], tails["stdout"], timed_out)
    except OSError:
        code, kind, permission = 127, "interpreter_or_executable_unavailable", "unknown"
    module = args.module
    if module == "unknown":
        module = module_before
    module_changed = command_module(args.command) != module_before
    if module_changed:
        module = "unknown"
    row = facts(hook=args.hook, stage=args.stage, payload=payload, code=code, kind=kind,
                module="unknown" if kind == "interpreter_or_executable_unavailable" else module,
                artifact=args.artifact, permission=permission,
                duration_ms=round((time.monotonic() - start) * 1000, 2))
    row["module_identity_status"] = "changed_during_execution" if module_changed else "stable_path_snapshot"
    artifact_changed = identity(artifact) != artifact_before
    if artifact_changed:
        row["artifact_generation"] = "unknown"
        row["artifact_identity_status"] = "changed_during_execution"
    if args.artifact == "unknown" and artifact_before != "unknown" and not artifact_changed and kind != "interpreter_or_executable_unavailable":
        # Content identity of a present delivery manifest; never hash its pathname.
        row["artifact_generation"] = artifact_before
        row["artifact_identity_kind"] = "delivery_manifest_sha256"
        row["id"] = digest(row["id"] + row["artifact_generation"])
    record(row)
    return code if code >= 0 else 128 - code


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hook", default="unknown")
    parser.add_argument("--stage", default="wrapper")
    parser.add_argument("--module", default="unknown")
    parser.add_argument("--artifact", default="unknown")
    parser.add_argument("--timeout", type=float, default=110)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--record-shell-exit", type=int)
    parser.add_argument("--category", choices=sorted(CATEGORIES), default="nonzero_exit")
    parser.add_argument("--ingest-host-result", action="store_true",
                        help="consume one normalized host result on stdin; never execute or settle an effect")
    parser.add_argument("--ingest-codex-notification", action="store_true")
    parser.add_argument("--workspace", default=None, help="workspace mapped by the app-server client")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.record_shell_exit is not None:
        try:
            raw = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024 or not 0 <= args.record_shell_exit <= 255:
                raise ValueError("invalid shell completion")
            payload = json.loads(raw or b"{}")
            if not isinstance(payload, dict):
                payload = {}
            row = facts(hook=args.hook, stage="bridge", payload=payload, code=args.record_shell_exit,
                        kind=args.category, permission="deny" if args.category == "policy_rejection" else "unknown")
            return 0 if record(row) else 74
        except (ValueError, TypeError):
            print("sulde: invalid_shell_hook_result", file=sys.stderr)
            return 65
    if args.ingest_codex_notification:
        try:
            raw = sys.stdin.buffer.read(65537)
            if len(raw) > 65536 or args.command or args.ingest_host_result:
                raise ValueError("invalid notification")
            row = codex_notification(json.loads(raw), args.workspace)
            return 0 if record(row) else 74
        except (ValueError, AttributeError, TypeError, KeyError, OverflowError, OSError):
            print("sulde: invalid_codex_hook_notification", file=sys.stderr)
            return 65
    if args.ingest_host_result:
        try:
            raw = sys.stdin.buffer.read(65537)
            if len(raw) > 65536 or args.command:
                raise ValueError("invalid host result")
            event = json.loads(raw)
            if event.get("schema") != "sulde-normalized-host-hook-result-v1":
                raise ValueError("unknown host schema")
            code = event.get("exit_code")
            if code is not None and type(code) is not int:
                raise ValueError("invalid exit code")
            def generation(name):
                value = event.get(name, "unknown")
                return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else "unknown"
            row = facts(hook=event.get("hook_id", "unknown"), stage="host", payload=event, code=code,
                        kind=event.get("error_category") if event.get("error_category") in CATEGORIES else "unknown",
                        source="host_result_import", module=generation("loaded_module_generation"),
                        artifact=generation("artifact_generation"),
                        permission=event.get("permission_decision") if event.get("permission_decision") in {"allow", "deny"} else "unknown")
            return 0 if record(row) else 74
        except (ValueError, AttributeError, TypeError):
            print("sulde: invalid_normalized_host_result", file=sys.stderr)
            return 65
    if args.status:
        result = read_rows(home())
        result["count"] = len(result.pop("rows"))
        print(json.dumps(result))
        return 0
    if args.command[:1] == ["--"]:
        args.command.pop(0)
    if not args.command or not 0 < args.timeout <= 110:
        parser.error("command and timeout in (0,110] required")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
