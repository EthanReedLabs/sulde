"""Paired local classifier timing. No model, remote action or production write."""
import ast
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/kb'))
from intent_guardian_parts import resources

BASE = 'ec60b61dbe7c2f83f8ed3d1bb3d9fb0ca885d71a'
raw = subprocess.check_output(['git', 'show', BASE + ':scripts/kb/intent_guardian_parts/resources.py'],
                              cwd=ROOT, text=True, encoding='utf-8', errors='replace')
node = next(n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == '_command_effect')
namespace = dict(vars(resources))
exec(compile(ast.Module(body=[node], type_ignores=[]), '<baseline-classifier>', 'exec'), namespace)
baseline, candidate = namespace['_command_effect'], resources._command_effect
commands = ['cat README.md', 'mkdir output', 'python3 -B -m unittest tests.example', 'git status --short']
samples = {'baseline_ms': [], 'candidate_ms': []}
for function in (baseline, candidate):
    for command in commands:
        function(command, cwd=ROOT)
for round_index in range(7):
    pair = [('baseline_ms', baseline), ('candidate_ms', candidate)]
    for label, function in (pair if round_index % 2 == 0 else list(reversed(pair))):
        start = time.perf_counter()
        for _ in range(30):
            for command in commands:
                function(command, cwd=ROOT)
        samples[label].append((time.perf_counter() - start) * 1000 / (30 * len(commands)))
print(json.dumps({'scope':'local command classifier only; not end-to-end Hook latency',
                  'base': BASE, 'samples': samples,
                  'median_delta_ms': statistics.median(samples['candidate_ms']) - statistics.median(samples['baseline_ms'])}, indent=2))
