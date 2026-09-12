"""Opt-in reproducible comparison; not another benchmark in every test run."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("CONTINUITY_BASELINE_ROOT"), "explicit baseline required")
class SessionContinuityBenchmarkTests(unittest.TestCase):
    def test_new_tool_events_before_after(self):
        baseline = Path(os.environ["CONTINUITY_BASELINE_ROOT"])
        result = {}
        for busy in (False, True):
            profile = "busy" if busy else "quiet"
            result[profile] = {}
            for name, root in (("before", baseline), ("after", ROOT)):
                command = [sys.executable, "-B", str(ROOT / "scripts/kb/benchmark-session-continuity.py"),
                           "--source-root", str(root), "--observations-only"] + (["--busy"] if busy else [])
                completed = subprocess.run(command, text=True, encoding="utf-8", errors="replace",
                                           capture_output=True, timeout=120)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                result[profile][name] = json.loads(completed.stdout)
        print("CONTINUITY_FRESH_PERFORMANCE=" + json.dumps(result, sort_keys=True), flush=True)
        for profile in result.values():
            before, after = profile["before"]["fresh_observation"], profile["after"]["fresh_observation"]
            self.assertLessEqual(after["median_ms"], max(before["median_ms"] * 1.05, before["median_ms"] + 1))
            self.assertLessEqual(after["p95_ms"], max(before["p95_ms"] * 1.10, before["p95_ms"] + 2))

    def test_same_host_quiet_and_busy_before_after(self):
        baseline = Path(os.environ["CONTINUITY_BASELINE_ROOT"])
        result = {}
        for busy in (False, True):
            profile = "busy" if busy else "quiet"
            result[profile] = {}
            for name, root in (("before", baseline), ("after", ROOT)):
                command = [sys.executable, "-B", str(ROOT / "scripts/kb/benchmark-session-continuity.py"),
                           "--source-root", str(root)] + (["--busy"] if busy else [])
                completed = subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=120)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                result[profile][name] = json.loads(completed.stdout)
        print("CONTINUITY_PERFORMANCE=" + json.dumps(result, sort_keys=True), flush=True)
        # Frozen absolute noise floors prevent sub-ms sampling noise from being
        # turned into percentage claims. All observed deltas are still reported.
        for profile in result.values():
            for operation in ("classification_batch", "deduplicated_observation", "readiness"):
                before, after = profile["before"][operation], profile["after"][operation]
                self.assertLessEqual(after["median_ms"], max(before["median_ms"] * 1.05, before["median_ms"] + 1))
                self.assertLessEqual(after["p95_ms"], max(before["p95_ms"] * 1.10, before["p95_ms"] + 2))
