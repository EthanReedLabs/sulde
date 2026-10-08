"""Local hot-cache normalization measurement; never executes classified commands."""
import json
import os
from pathlib import Path
import shlex
import statistics
import sys
import time

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / "scripts/kb"))
from intent_guardian_parts.resources import normalize_hook_event

commands = {
    "ordinary_read": "rg needle README.md",
    "ordinary_write": "touch marker.txt",
    "help": shlex.join([sys.executable, str(root / "scripts/kb/intent-guardian.py"), "intervention-resolve", "--help"]),
    "datetime": shlex.join([sys.executable, "-B", "-c", 'from datetime import datetime, timezone; print(datetime.fromisoformat("2026-10-04").replace(tzinfo=timezone.utc))']),
    "ssh_probe": "ssh -F /dev/null -o BatchMode=yes -o PermitLocalCommand=no -o StrictHostKeyChecking=yes -o UpdateHostKeys=no reader@192.0.2.10 '/usr/bin/stat -- /srv/app/state'",
    "denied_shape": "ssh reader@server-alias 'rm -rf /srv/app'",
}
results = {}
for name, command in commands.items():
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(root)}
    for _ in range(20):
        normalize_hook_event(payload, phase="started", provider="codex")
    values = []
    for _ in range(150):
        start = time.perf_counter_ns()
        normalize_hook_event(payload, phase="started", provider="codex")
        values.append((time.perf_counter_ns() - start) / 1e6)
    results[name] = {"p50_ms": statistics.median(values), "p95_ms": sorted(values)[142]}
print(json.dumps({"source_root": str(root), "python": sys.version, "samples_per_case": 150,
                  "cache": "20 warmups per case", "measurements": results}, sort_keys=True))
