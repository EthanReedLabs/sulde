"""Compare exact baseline/task classifiers; never execute classified source."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = {
    "literal": "text='abc'; print(text.replace('a','b'))",
    "file_transform": "from pathlib import Path; p=Path('service.py'); s=p.read_text(); s=s.replace('a','b'); p.write_text(s)",
    "keys": "[dict(metric_id=k.replace('_','-')) for k in ('verified_count','retained_bytes')]",
    "opaque": "receiver.replace('a','b')",
    "filesystem": "from pathlib import Path; Path('a').replace('b')",
    "non_string": "print(1)",
}


def worker(root: Path) -> dict:
    sys.path.insert(0, str(root / "scripts/kb"))
    from intent_guardian_parts.resources import _python_source_effect, normalize_hook_event
    result = {}
    for name, source in SAMPLES.items():
        samples = []
        for _ in range(11):
            started = time.perf_counter_ns()
            for _ in range(80):
                _python_source_effect(source, cwd=None)
            samples.append((time.perf_counter_ns() - started) / 80000)
        event_input = {"tool_name": "exec_command", "tool_input": {
            "cmd": shlex.join([sys.executable, "-B", "-c", source])}}
        normalized = []
        for _ in range(5):
            started = time.perf_counter_ns()
            event = normalize_hook_event(event_input, phase="started", provider="codex")
            normalized.append((time.perf_counter_ns() - started) / 1000)
        result[name] = {"classifier_us_median": statistics.median(samples),
                        "classifier_us_max_batch": max(samples),
                        "normalizer_us_median": statistics.median(normalized),
                        "effect": event["effect"],
                        "violation": (event.get("invocation_violation") or {}).get("kind")}
    return result


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        print(json.dumps(worker(Path(sys.argv[2]))))
        return 0
    import run_checks
    results, identities = {}, {}
    for role, root in (("baseline", ROOT.parent / "guardian-v3-dev-merge"), ("task", ROOT)):
        before = run_checks.helpers.source_digest(root)
        results[role] = json.loads(subprocess.check_output(
            [sys.executable, "-B", __file__, "--worker", str(root)],
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), text=True))
        after = run_checks.helpers.source_digest(root)
        if before != after:
            raise RuntimeError("benchmark source changed")
        identities[role] = {"tree_sha256": before, "classifier_files": {
            name: hashlib.sha256((root / "scripts/kb" / name).read_bytes()).hexdigest()
            for name in ("python_data_methods.py", "python_string_flow.py", "intent_guardian_parts/resources.py")
            if (root / "scripts/kb" / name).is_file()}}
    deltas = {name: {field: results["task"][name][field] - results["baseline"][name][field]
                     for field in ("classifier_us_median", "normalizer_us_median")} for name in SAMPLES}
    # Freeze an absolute hot-path budget; percentages mislead at microsecond scale.
    within_budget = all(row["classifier_us_median"] <= 500 and row["normalizer_us_median"] <= 10000
                        for row in deltas.values())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    record = {"schema": "guardian-python-dataflow-benchmark-v1", "at": stamp,
              "source_sha256": identities, "python_identity": run_checks.helpers.inspect_python(Path(sys.executable)),
              "results": results, "deltas_us": deltas, "within_budget": within_budget,
              "budget": {"classifier_added_us": 500, "normalizer_added_us": 10000},
              "sample_sha256": hashlib.sha256(json.dumps(SAMPLES, sort_keys=True).encode()).hexdigest(),
              "scope": "classifier/normalizer microbenchmark; not end-to-end task latency"}
    run_checks.OUT.mkdir(parents=True, exist_ok=True)
    path = run_checks.OUT / (stamp + "-benchmark.json")
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": str(path.relative_to(ROOT)), "results": results,
                      "deltas_us": deltas, "within_budget": within_budget}, indent=2))
    return 0 if within_budget else 1


if __name__ == "__main__":
    raise SystemExit(main())
