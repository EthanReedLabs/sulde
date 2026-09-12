#!/usr/bin/env python3
"""Observe a local Python adapter in its existing process (POSIX only).

No Guardian or database is imported before execution. Native host timeouts
remain the outer boundary; a local alarm allows a final timeout receipt when
Python can handle it. Host kills, os._exit and exec replacement remain blind.
"""
import io
import json
import os
import signal
import sys
import time
try:
    from _sha256 import sha256
except ImportError:
    from hashlib import sha256

sys.dont_write_bytecode = True


class Tee:
    def __init__(self, target, tail):
        self.target, self.tail = target, tail

    def __getattr__(self, name):
        if name == "buffer":
            return Tee(self.target.buffer, self.tail)
        return getattr(self.target, name)

    def write(self, value):
        raw = value.encode("utf-8", "replace") if isinstance(value, str) else value
        self.tail.extend(raw[-8192:])
        del self.tail[:-8192]
        return self.target.write(value)


def main():
    hook, stage, script, *arguments = sys.argv[1:]
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
    original = sys.stdin, sys.stdout, sys.stderr, sys.argv, list(sys.path)
    stdout, stderr = bytearray(), bytearray()
    sys.stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
    sys.stdout, sys.stderr = Tee(sys.stdout, stdout), Tee(sys.stderr, stderr)
    sys.argv = [script, *arguments]
    sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
    class Deadline(BaseException):
        pass
    def expire(_signum, _frame):
        raise Deadline()
    previous = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, 110)
    started = time.monotonic()
    code, kind = 0, None
    module_generation, artifact_generation = "unknown", "unknown"
    manifest = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), ".codex-plugin/generation.json")
    try:
        with open(manifest, "rb") as source:
            artifact_generation = sha256(source.read()).hexdigest()
    except OSError:
        pass
    try:
        # These are owned standalone .py adapters, never packages or zip paths.
        # Avoid run_path's package discovery imports on every ordinary call.
        with open(script, "rb") as source:
            loaded_source = source.read()
        module_generation = sha256(loaded_source).hexdigest()
        code_object = compile(loaded_source, script, "exec")
        exec(code_object, {"__name__": "__main__", "__file__": script,
                           "__package__": None, "__spec__": None, "__cached__": None})
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else 0 if error.code is None else 1
        if not isinstance(error.code, (int, type(None))):
            print(error.code, file=sys.stderr)
    except FileNotFoundError:
        code, kind = (2, "script_missing") if not os.path.isfile(script) else (1, "internal_exception")
    except Deadline:
        code, kind = 124, "timeout"
    except BaseException:
        import traceback
        traceback.print_exc()
        code, kind = 1, "internal_exception"
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        sys.stdin, sys.stdout, sys.stderr, sys.argv, sys.path[:] = original
    # A recording failure must never become a retry or change the adapter code.
    try:
        from _hook_observer import classify, facts, identity, record
        classified, permission = classify(code, stderr, stdout)
        artifact_changed = identity(manifest) != artifact_generation
        row = facts(hook=hook, stage=stage, payload=payload, code=code, kind=kind or classified,
                    permission=permission, module=module_generation,
                    artifact="unknown" if artifact_changed else artifact_generation,
                    duration_ms=round((time.monotonic() - started) * 1000, 2))
        row["module_identity_status"] = "loaded_bytes" if module_generation != "unknown" else "unknown"
        row["module_path_changed"] = identity(script) != module_generation
        if artifact_changed:
            row["artifact_identity_status"] = "changed_during_execution"
        if artifact_generation != "unknown":
            row["artifact_identity_kind"] = "delivery_manifest_sha256"
        record(row)
    except Exception:
        print("sulde: hook_observer_delivery_unavailable; action_not_retried", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
