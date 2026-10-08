"""One isolated candidate prepare/verify; never promote or install production."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/kb"))


def main():
    isolation = runpy.run_path(str(ROOT / "scripts/kb/run-isolated-tests.py"))
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    identifier = "integration-" + commit[:12] + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate_home = ROOT / ".sulde/data/life-r1-candidates"
    run_root = candidate_home / (identifier + "-evidence")
    run_root.mkdir(parents=True, exist_ok=False, mode=0o700)
    production_kb = isolation["neutral_kb_home"]().resolve()
    inherited = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ}
    environment = isolation["isolated_environment"](run_root / "host", production_kb=production_kb,
                                                    inherited=inherited)
    environment["SULDE_CANDIDATE_PYTHON"] = sys.executable
    isolation["preflight_os_test_isolation"](production_kb, environment)
    codex = shutil.which("codex")
    if not codex:
        raise RuntimeError("Native Codex CLI is required")
    command = [sys.executable, "-B", str(ROOT / "scripts/release/candidate_codex_plugin.py"),
               "--candidate-home", str(candidate_home), "--codex", codex, "--json"]
    evidence = {"schema": "life-r1-integration-candidate-v1", "source_commit": commit,
                "candidate_id": identifier, "production_promotion": False,
                "scope": "official candidate CLI in OS-enforced isolated host/data roots; scheduler dry-run fixture",
                "phases": []}
    for phase, arguments in (("prepare", ["prepare", "--candidate-id", identifier]),
                              ("verify", ["verify", identifier])):
        started = time.monotonic()
        guarded = isolation["os_isolated_test_command"](command + arguments, production_kb)
        completed = subprocess.run(guarded, cwd=ROOT, env=environment, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", timeout=180)
        row = {"phase": phase, "exit_code": completed.returncode,
               "seconds": round(time.monotonic() - started, 3)}
        for stream, content in (("stdout", completed.stdout), ("stderr", completed.stderr)):
            path = run_root / (phase + "." + stream)
            with path.open("x", encoding="utf-8") as output:
                output.write(content)
            path.chmod(0o600)
            row[stream + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        evidence["phases"].append(row)
        print(json.dumps(row), flush=True)
        if completed.returncode:
            print(completed.stderr[-2000:], flush=True)
            break
    evidence["production_write_attempts"] = isolation["process_guard_violations"](environment)
    evidence["passed"] = (len(evidence["phases"]) == 2
                          and all(row["exit_code"] == 0 for row in evidence["phases"])
                          and not evidence["production_write_attempts"])
    report = run_root / "summary.json"
    report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report.chmod(0o600)
    print("CANDIDATE_SUMMARY=" + str(report), flush=True)
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
