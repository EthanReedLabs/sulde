"""Record all paired transport timings once; no model or production calls."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    directory = ROOT / ".codex-agent/s3c-stable-evidence" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ-timing")
    directory.mkdir(parents=True, exist_ok=False)
    test = ROOT / "tests/test_codex_stable_hook_entry.py"
    observed = runpy.run_path(str(test))["benchmark"]()
    observed["head"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        encoding="utf-8", errors="replace",
    ).strip()
    observed["test_sha256"] = hashlib.sha256(test.read_bytes()).hexdigest()
    observed["real_model_calls"] = 0
    observed["supervision_model_calls"] = 0
    observed["budget"] = {"median_absolute_ms": 20, "median_fraction": .05,
                          "p95_absolute_ms": 50, "p95_fraction": .10}
    observed["budget_passed"] = all(
        observed["new"][key] - observed["old"][key] <= max(absolute, observed["old"][key] * fraction)
        for key, absolute, fraction in (("median_ms", 20, .05), ("p95_ms", 50, .1))
    )
    target = directory / "timing.json"
    target.write_text(json.dumps(observed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (directory / "sha256.json").write_text(json.dumps({target.name: digest}) + "\n", encoding="utf-8")
    print(json.dumps({"directory": str(directory), "sha256": digest,
                      "old": observed["old"], "new": observed["new"],
                      "budget_passed": observed["budget_passed"]}))
    return 0 if observed["budget_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
