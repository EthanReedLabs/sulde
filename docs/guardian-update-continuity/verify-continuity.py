"""Archive exact wrapper controls/injection and alternating local entry timings.

No real tools or model calls: the external launcher succeeds without executing
the payload. Installer-chain proof is a separate test suite, not this fixture.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidate = Path(__file__).resolve().parents[2]
    relative = Path("integrations/codex/plugins/sulde/scripts")
    roots = {"baseline": args.baseline.resolve(), "candidate": candidate}
    out = args.output / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ-wrapper")
    out.mkdir(parents=True, exist_ok=False)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("SULDE_", "CODEX_", "CLAUDE_"))}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    records = {}
    test = candidate / "tests/test_hook_observer_continuity.py"
    for name, root in roots.items():
        commands = ([sys.executable, "-B", str(test),
                     "ObserverContinuityTests.test_normal_dependencies_read_and_failure_record", "-v"],
                    [sys.executable, "-B", str(test), "-v"])
        records[name] = []
        for index, command in enumerate(commands):
            run = subprocess.run(command, cwd=candidate, env={**env,
                "SULDE_CONTINUITY_TEST_SCRIPTS": str(root / relative)},
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
            log = out / f"{name}-{index}.log"
            log.write_bytes(run.stdout)
            records[name].append({"command": command, "exit": run.returncode,
                                  "log": log.name, "log_sha256": sha(log)})
    assert records["baseline"][0]["exit"] == records["candidate"][0]["exit"] == 0
    assert records["baseline"][1]["exit"] == 1, "old defect must reach failing assertions"
    assert records["candidate"][1]["exit"] == 0

    samples = {"baseline": [], "candidate": []}
    with tempfile.TemporaryDirectory() as temp:
        configs = {}
        for name, root in roots.items():
            fixture = Path(temp) / name
            scripts = fixture / "plugin/scripts"
            shutil.copytree(root / relative, scripts, ignore=shutil.ignore_patterns("__pycache__"))
            bridge = fixture / "sulde/bin/intent-guardian"
            bridge.parent.mkdir(parents=True)
            bridge.write_text("#!/bin/sh\n# sulde-observer-in-process-v1\nexit 0\n", encoding="utf-8")
            bridge.chmod(0o700)
            configs[name] = (["/bin/sh", str(scripts / "run-hook.sh"), "pre-tool-use"],
                             {**env, "SULDE_HOME": str(fixture / "sulde"),
                              "SULDE_KB_HOME": str(fixture / "sulde/data/kb")})
        # Two warm-up pairs excluded; ten AB/BA pairs retained.
        for index in range(12):
            for name in (("baseline", "candidate") if index % 2 == 0 else ("candidate", "baseline")):
                command, configured = configs[name]
                start = time.perf_counter()
                run = subprocess.run(command, input='{"tool_name":"Read"}', env=configured,
                                     capture_output=True, text=True, encoding="utf-8", timeout=10)
                elapsed = (time.perf_counter() - start) * 1000
                assert run.returncode == 0 and not run.stdout.strip(), run.stderr
                if index >= 2:
                    samples[name].append(elapsed)
    metrics = {name: {"median_ms": statistics.median(values), "p95_ms": sorted(values)[-1]}
               for name, values in samples.items()}
    for metric, absolute, percent in (("median_ms", 20, .05), ("p95_ms", 50, .10)):
        assert metrics["candidate"][metric] - metrics["baseline"][metric] <= max(
            absolute, metrics["baseline"][metric] * percent), metrics
    result = {"schema": "sulde-s3c-wrapper-evidence-v1", "records": records,
              "samples_ms": samples, "metrics": metrics,
              "timing_scope": "actual shell wrapper with zero-exit external bridge; not full runtime latency",
              "real_model_calls": 0, "supervision_model_calls": 0,
              "python": sys.version, "test_sha256": sha(test),
              "source_sha256": {name: {file: sha(root / relative / file)
                for file in ("run-hook.sh", "_recovery_defer.py", "_hook_observer.py")}
                for name, root in roots.items()}}
    (out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    manifest = {p.name: sha(p) for p in out.iterdir() if p.is_file()}
    (out / "sha256.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"evidence": str(out), "metrics": metrics}))


if __name__ == "__main__":
    main()
