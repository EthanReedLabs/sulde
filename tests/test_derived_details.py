from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/kb/derived-details.py"
spec = importlib.util.spec_from_file_location("derived_details_test", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DerivedDetailsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def add(self, name, **overrides):
        data = b'{"derived_count":1}\n'
        (self.root / (name + ".detail.json")).write_bytes(data)
        meta = {"kind": "derived_detail", "authoritative": False, "issue_status": "closed",
                "effect_status": "settled", "candidate_pending": False, "verified_aggregate": False,
                "sourceVersion": "source-1", "generatorVersion": "generator-1",
                "created_at": (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),
                "sha256": hashlib.sha256(data).hexdigest(), **overrides}
        (self.root / (name + ".meta.json")).write_text(json.dumps(meta), encoding="utf-8")

    def plan(self):
        return module.plan(self.root, source_version="source-1", generator_version="generator-1", ttl_seconds=86400, capacity=2)

    def test_real_cli_dry_run_quarantine_and_separate_readback(self):
        self.add("expired")
        for name, protected in (("log", {"authoritative": True}), ("open", {"issue_status": "open"}),
                                ("experience", {"verified_aggregate": True}), ("candidate", {"candidate_pending": True}),
                                ("effect", {"effect_status": "unknown"}), ("version", {"sourceVersion": "different"})):
            self.add(name, **protected)
        def run(*args):
            result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--root", str(self.root), *args],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        dry = run("--source-version", "source-1", "--generator-version", "generator-1", "--ttl-seconds", "86400")
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
        self.assertEqual(len(dry["candidates"]), 1)
        self.assertEqual(dry["protected"], 6)
        plan_path = self.root / "reviewed-plan.json"
        plan_path.write_text(json.dumps(dry), encoding="utf-8")
        self.assertEqual(run("--quarantine-plan", str(plan_path))["status"], "verified")
        self.assertEqual(run("--readback-plan", str(plan_path))["files_checked"], 2)
        for name, data in before.items():
            if not name.startswith("expired."):
                self.assertEqual((self.root / name).read_bytes(), data)

    def test_drift_and_symlink_are_never_cleaned(self):
        self.add("expired")
        dry = self.plan()
        (self.root / "expired.detail.json").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "drift"):
            module.quarantine(self.root, dry)
        self.assertTrue((self.root / "expired.detail.json").exists())
        os.symlink(self.root / "expired.detail.json", self.root / "linked.detail.json")
        self.add("metadata")
        (self.root / "linked.meta.json").write_bytes((self.root / "metadata.meta.json").read_bytes())
        self.assertEqual(self.plan()["protected"], 2)

    def test_capacity_quarantines_only_oldest_eligible_detail(self):
        for name in ("a", "b", "c"):
            self.add(name, created_at=datetime.now(timezone.utc).isoformat())
        selected = self.plan()
        self.assertEqual([r["file"] for r in selected["candidates"]], ["a.detail.json"])


if __name__ == "__main__":
    unittest.main()
