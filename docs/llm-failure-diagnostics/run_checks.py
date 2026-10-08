"""Offline scoped test runner; fixed commands, no product process/model calls."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

task = Path(__file__).resolve().parents[2]
pilot = task.parent / "orca-sulde-diagnostics-pilot"
runtime = pilot / ".pilot-runtime"
python = "/Users/eric/.sulde/data/kb/venv/bin/python"
report_dir = Path(__file__).resolve().parent
run = Path(tempfile.mkdtemp(prefix="fix-checks-", dir=runtime))
profile = report_dir / "offline.sb"
sandbox = ["/usr/bin/sandbox-exec"]
for key, value in {"TASK": task, "PILOT": pilot, "RUNTIME": runtime,
                   "USERROOT": "/Users/eric", "VENV": "/Users/eric/.sulde/data/kb/venv",
                   "PYTHONROOT": "/Users/eric/.pyenv/versions/3.10.7"}.items():
    sandbox += ["-D", f"{key}={value}"]
sandbox += ["-f", str(profile)]
env = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": str(run)}
files = ["test_llm_diagnostics.py", "test_distill_conflict_resilience.py", "test_self_repair.py",
         "test_auto_distill_windows.py", "test_command_template_split.py",
         "test_scheduler_entrypoints.py"]
rows = []
for name in files:
    start = time.monotonic()
    argv = [python, "-B", "-m", "unittest", "discover", "-s", "tests", "-p", name, "-q"]
    result = subprocess.run(sandbox + argv, env=env, cwd=task, capture_output=True, text=True, timeout=120)
    combined = result.stdout + result.stderr
    count = re.search(r"Ran (\d+) tests?", combined)
    skipped = re.search(r"skipped=(\d+)", combined)
    row = {"test": name, "exit_code": result.returncode, "tests": int(count[1]) if count else None,
           "skipped": int(skipped[1]) if skipped else 0, "seconds": round(time.monotonic()-start, 3),
           "output_sha256": hashlib.sha256(combined.encode()).hexdigest(), "argv": argv[1:]}
    rows.append(row)
    print(json.dumps(row), flush=True)
    if result.returncode:
        # Only failure diagnostics, not successful synthetic execution logs.
        print(result.stderr[-8000:].replace(str(task), "<task>").replace(str(pilot), "<pilot>"), flush=True)
evidence = run / "independent.json"
argv = [python, "-B", str(pilot / "docs/orca-sulde-diagnostics-pilot/verify_diagnostics.py"),
        "--source", str(task), "--scratch-root", str(runtime), "--report", str(evidence)]
result = subprocess.run(sandbox + argv, env=env, cwd=task, capture_output=True, text=True, timeout=30)
independent = json.loads(evidence.read_text()) if evidence.exists() else {"runner_failed": True}
print(json.dumps({"independent_exit": result.returncode, "summary": result.stdout.strip()}), flush=True)
if result.returncode:
    print(result.stderr[-4000:].replace(str(task), "<task>").replace(str(pilot), "<pilot>"), flush=True)
paths = [task / "scripts/kb" / n for n in ("llm_diagnostics.py", "auto-distill.py", "self-repair.py")]
paths += [task / "tests" / n for n in files]
paths += [profile, Path(__file__)]
hashes = {str(p.relative_to(task)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
report = {"schema": "llm-diagnostic-scoped-checks-v1", "model_calls": 0, "network": "denied",
          "source_base_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=task, text=True).strip(),
          "source_and_test_sha256": hashes, "unit_results": rows,
          "independent_exit": result.returncode, "independent": independent}
path = report_dir / (run.name + ".json")
with path.open("x") as output:
    json.dump(report, output, indent=2)
    output.write("\n")
os.chmod(path, 0o600)
print(json.dumps({"report": path.name}), flush=True)
raise SystemExit(0 if result.returncode == 0 and all(row["exit_code"] == 0 for row in rows) else 1)
