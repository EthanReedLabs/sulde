"""Diagnostic instrumentation of the preserved C observer; no business actions."""
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(sys.argv[1])
source = subprocess.check_output(["git", "show", "c33d7b9:integrations/codex/plugins/sulde/scripts/_hook_observer.py"], cwd=ROOT).decode()
source = source.replace("import argparse\n", "import time\n_PROFILE_BEGIN = time.perf_counter()\nimport argparse\n", 1)
source = source.replace('VERSION = "hook-observer-v1"', '_PROFILE_IMPORTED = time.perf_counter()\nVERSION = "hook-observer-v1"', 1)
instrumentation = '''
_profile = {"imports_ms": (_PROFILE_IMPORTED - _PROFILE_BEGIN) * 1000, "record_calls": 0}
def _timed(name, function):
    def invoke(*args, **kwargs):
        start = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            _profile[name] = _profile.get(name, 0) + (time.perf_counter() - start) * 1000
            if name == "record_ms":
                _profile["record_calls"] += 1
    return invoke
record = _timed("record_ms", record)
facts = _timed("facts_ms", facts)
subprocess.Popen.__init__ = _timed("popen_ms", subprocess.Popen.__init__)
subprocess.Popen.wait = _timed("wait_inclusive_ms", subprocess.Popen.wait)
time.sleep = _timed("poll_sleep_ms", time.sleep)
try:
    _code = main()
finally:
    _profile["in_process_total_ms"] = (time.perf_counter() - _PROFILE_BEGIN) * 1000
    with open(os.environ["R1_PROFILE_OUTPUT"], "w") as handle:
        json.dump(_profile, handle)
raise SystemExit(_code)
'''
source = source[:source.index('if __name__ == "__main__":')] + instrumentation
base = Path(tempfile.mkdtemp(prefix="life-r1-cost-", dir="/private/tmp"))
script = base / "plugin/scripts/_hook_observer.py"
script.parent.mkdir(parents=True)
script.write_text(source)
target = base / "action.py"
target.write_text("pass\n")
profile = base / "profile.json"
env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "TMPDIR"}}
env.update(HOME=str(base), SULDE_KB_HOME=str(base / "kb"), R1_PROFILE_OUTPUT=str(profile), PYTHONDONTWRITEBYTECODE="1")
rows = []
for index in range(35):
    start = time.perf_counter()
    subprocess.run([sys.executable, "-B", str(script), "--hook", "fixture", "--", sys.executable, "-B", str(target)],
                   input=json.dumps({"tool_use_id": str(index)}), env=env, capture_output=True,
                   text=True, encoding="utf-8", errors="replace", check=True, timeout=5)
    elapsed = (time.perf_counter() - start) * 1000
    row = json.loads(profile.read_text())
    row["wall_ms"] = elapsed
    row["startup_shutdown_and_profile_io_ms"] = elapsed - row["in_process_total_ms"]
    row["other_ms"] = row["in_process_total_ms"] - sum(row[k] for k in ("imports_ms", "popen_ms", "wait_inclusive_ms", "record_ms", "facts_ms"))
    if index >= 5:
        rows.append(row)
summaries = {key: {"median": round(statistics.median(row[key] for row in rows), 3),
                   "p95": round(sorted(row[key] for row in rows)[math.ceil(len(rows)*.95)-1], 3)} for key in rows[0]}
wall = summaries["wall_ms"]["median"]
for key in ("imports_ms", "popen_ms", "wait_inclusive_ms", "record_ms", "facts_ms", "startup_shutdown_and_profile_io_ms", "other_ms"):
    summaries[key]["median_percent_of_instrumented_observer_wall"] = round(summaries[key]["median"] / wall * 100, 2)
result = {"schema": "life-r1-cost-diagnostic-v1", "revision": "c33d7b9", "python": sys.version,
          "n": 30, "warmups": 5, "scope": "instrumented old generic observer with real no-effect Python child; isolated HOME; diagnostic only, not budget measurement",
          "limits": "wait includes useful child execution; poll_sleep is nested inside wait and must not be added again; startup residual includes shutdown/profile I/O; ratios are of measured observer total, not a causal partition of the historical 50 ms increment; full-suite background load present",
          "summaries": summaries, "samples": rows}
Path('/private/tmp/R1-cost-breakdown.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(summaries, indent=2))
