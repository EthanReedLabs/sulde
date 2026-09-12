"""Fixed-budget single-call regression against the task's immutable dev base."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASE = "086f49bd372c21ef0c63613b1682d803c0047eec"


class CompositionPerformanceTests(unittest.TestCase):
    def test_single_call_budget_against_base(self):
        # The baseline module source is evaluated in a fresh process, with the
        # unchanged sibling dependencies of this task. No worktree or installed
        # module is replaced. This measures normalization, not whole-Agent time.
        source = r'''
import json, pathlib, statistics, subprocess, sys, time
sys.path.insert(0, str(pathlib.Path.cwd() / 'scripts/kb'))
from intent_guardian_parts import resources
if sys.argv[1] == 'base':
    raw = subprocess.check_output(['git','show',sys.argv[2]+':scripts/kb/intent_guardian_parts/resources.py'], text=True, encoding='utf-8', errors='strict')
    exec(compile(raw, resources.__file__, 'exec'), resources.__dict__)
commands = {'read': 'rg needle README.md', 'local_write': 'touch probe.txt',
            'single_control': sys.executable + ' ' + str(pathlib.Path.cwd() / 'scripts/kb/intent-guardian.py') + ' --help'}
result = {}
for label, command in commands.items():
    payload = {'tool_name':'Bash','tool_input':{'command':command},'cwd':str(pathlib.Path.cwd())}
    for _ in range(10): resources.normalize_hook_event(payload, phase='started', provider='codex')
    samples=[]
    for _ in range(150):
        start=time.perf_counter_ns()
        resources.normalize_hook_event(payload, phase='started', provider='codex')
        samples.append((time.perf_counter_ns()-start)/1e6)
    result[label]={'median_ms':statistics.median(samples),'p95_ms':sorted(samples)[142]}
    print(json.dumps({'variant':sys.argv[1], 'case':label, **result[label]}), file=sys.stderr, flush=True)
print(json.dumps(result))
'''
        results = {}
        for variant in ("base", "candidate"):
            completed = subprocess.run([sys.executable, "-B", "-c", source, variant, BASE],
                cwd=ROOT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                # This is a wall-clock guard for both the old and new source,
                # not the per-call performance budget asserted below. Trusted
                # control normalization also verifies the runtime identity.
                text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=180)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            results[variant] = json.loads(completed.stdout)
        print("COMPOSITION_PERFORMANCE=" + json.dumps({"base": BASE, "samples_per_case": 150,
            "scope": "single-call normalization; unchanged sibling dependencies", "measurements": results}, sort_keys=True))
        for label in results["base"]:
            baseline, candidate = results["base"][label], results["candidate"][label]
            self.assertLessEqual(candidate["median_ms"] - baseline["median_ms"], max(1, baseline["median_ms"] * .05))
            self.assertLessEqual(candidate["p95_ms"] - baseline["p95_ms"], max(2, baseline["p95_ms"] * .10))
