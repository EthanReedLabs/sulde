#!/usr/bin/env python3
"""Same-process warm-path samples; run each source root in a fresh worker."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import statistics
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=80)
    parser.add_argument("--busy", action="store_true")
    parser.add_argument("--observations-only", action="store_true")
    args = parser.parse_args()
    def source_version():
        return {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.source_root, text=True, encoding="utf-8", errors="replace").strip(),
                "diff_sha256": __import__("hashlib").sha256(subprocess.check_output(
                    ["git", "diff", "--no-ext-diff", "--binary", "HEAD"], cwd=args.source_root)).hexdigest()}
    version = source_version()
    sys.path.insert(0, str(args.source_root.resolve() / "scripts/kb"))
    import host_capabilities as host
    from intent_guardian_parts.resources import normalize_hook_event

    def sample(operation):
        for _ in range(5):
            operation()
        values = []
        for _ in range(args.samples):
            started = time.perf_counter_ns()
            operation()
            values.append((time.perf_counter_ns() - started) / 1_000_000)
        return {"median_ms": statistics.median(values),
                "p95_ms": sorted(values)[int(.95 * (len(values) - 1))], "samples": len(values)}

    with tempfile.TemporaryDirectory(prefix="sulde-continuity-benchmark-") as temporary:
        workspace = Path(temporary) / "workspace"
        workspace.mkdir()
        home = Path(temporary) / "kb"
        host.provision_provenance_key(home)
        now = datetime.now(timezone.utc)
        if args.busy:
            with host.observation_path(home).open("wb") as output:
                row = json.dumps({"provider": "codex", "session_id": "unrelated", "padding": "x" * 8192}).encode() + b"\n"
                for _ in range(6000):
                    output.write(row)
        runtime = host.runtime_identity("codex")

        def record(hook, call=""):
            provenance = host.issue_host_provenance(
                provider="codex", hook_event=hook, session_id="benchmark", workspace=workspace,
                call_id=call, home=home, now=now, loaded_module_generation=runtime,
                artifact_generation="fixture:" + runtime,
            )
            return host.record_observation(provider="codex", hook_event=hook, session_id="benchmark",
                workspace=workspace, call_id=call, home=home, now=now,
                source="live_host_hook", provenance=provenance)

        for hook in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"):
            record(hook, "call" if hook.endswith("ToolUse") else "")
        # The provider index is also warm, avoiding a misleading cold-start
        # comparison in a benchmark explicitly intended for ordinary hot paths.
        host.record_observation(provider="codex", hook_event="MCPInitialize", home=home, now=now)
        if args.observations_only:
            sequence = 0
            def fresh_event():
                nonlocal sequence
                sequence += 1
                record("PreToolUse", "fresh-" + str(sequence))
            result = {"profile": "busy_47MiB" if args.busy else "quiet",
                      "fresh_observation": sample(fresh_event),
                      "distinct_call_ids": sequence, "cold_start_included": False,
                      "source_version": version}
            if source_version() != version:
                raise RuntimeError("benchmark source changed during sampling")
            print(json.dumps(result, sort_keys=True))
            return 0
        sources = ["rg -n pattern README.md", "touch ordinary.txt", "git status --short",
                   "python3 -c " + shlex.quote("text='before'; print(text.replace('before', 'after'))")]
        result = {"profile": "busy_47MiB" if args.busy else "quiet", "cold_start_included": False,
                  "source_log_bytes": host.observation_path(home).stat().st_size,
                  "classification_batch": sample(lambda: [normalize_hook_event(
                      {"tool_name": "exec_command", "tool_input": {"cmd": command}},
                      phase="started", provider="codex") for command in sources]),
                  "deduplicated_observation": sample(lambda: record("PreToolUse", "call")),
                  "readiness": sample(lambda: host.readiness_projection(home, provider="codex",
                      session_id="benchmark", workspace=workspace, expected_runtime_sha256=runtime, now=now))}
        if source_version() != version:
            raise RuntimeError("benchmark source changed during sampling")
        result["source_version"] = version
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
