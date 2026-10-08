"""Run the public checkout's official candidate CLI in OS-enforced isolation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--production-kb", type=Path, required=True)
    parser.add_argument("--codex", type=Path, required=True)
    args = parser.parse_args()
    checkout = args.checkout.resolve(strict=True)
    output = args.output.absolute()
    evidence_root = ROOT / ".sulde/public-export"
    if not checkout.is_relative_to(evidence_root) or not output.resolve().is_relative_to(evidence_root):
        raise ValueError("checkout and output must be inside this task's evidence root")
    if output.exists():
        raise ValueError("evidence directory already exists")
    output.mkdir(parents=True, mode=0o700)
    production = args.production_kb.resolve(strict=True)
    executable = args.codex.resolve(strict=True)
    cli_digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    isolation = runpy.run_path(str(ROOT / "scripts/kb/run-isolated-tests.py"))
    environment = isolation["isolated_environment"](output / "host", production_kb=production)
    environment["SULDE_CANDIDATE_PYTHON"] = sys.executable
    isolation["preflight_os_test_isolation"](production, environment)
    command = [sys.executable, "-B", str(checkout / "scripts/release/candidate_codex_plugin.py"),
               "--candidate-home", str(output / "candidates"), "--codex", str(executable), "--json"]
    phases = []
    for phase, suffix in (("prepare", ["prepare", "--candidate-id", "r9-public"]),
                          ("verify", ["verify", "r9-public"])):
        started = time.monotonic()
        guarded = isolation["os_isolated_test_command"](command + suffix, production)
        try:
            result = subprocess.run(guarded, cwd=checkout, env=environment, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=180)
        except subprocess.TimeoutExpired as error:
            def text(value):
                return value.decode("utf-8", "replace") if isinstance(value, bytes) else value or ""
            result = subprocess.CompletedProcess(guarded, 124, text(error.stdout), text(error.stderr))
        row = {"phase": phase, "exit_code": result.returncode,
               "seconds": round(time.monotonic() - started, 3)}
        for stream in ("stdout", "stderr"):
            content = getattr(result, stream)
            path = output / (phase + "." + stream)
            path.write_text(content, encoding="utf-8")
            path.chmod(0o600)
            row[stream + "_sha256"] = hashlib.sha256(content.encode()).hexdigest()
        phases.append(row)
        print(json.dumps(row), flush=True)
        if result.returncode:
            print(result.stderr[-2000:], flush=True)
            break
    violations = isolation["process_guard_violations"](environment)
    unchanged = hashlib.sha256(executable.read_bytes()).hexdigest() == cli_digest
    passed = len(phases) == 2 and all(row["exit_code"] == 0 for row in phases) and not violations and unchanged
    summary = {"status": "passed" if passed else "failed", "phases": phases,
               "production_write_violations": len(violations), "cli_unchanged": unchanged,
               "cli_sha256": cli_digest, "production_promotion": False,
               "scope": "official candidate prepare/verify; scheduler dry-run; no native human UI proof"}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
