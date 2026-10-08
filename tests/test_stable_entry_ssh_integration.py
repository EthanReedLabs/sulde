"""Staged stable entry + SSH debt protocol, never SSH or a real human approval."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

from tests import test_guardian_s1_grants as grants

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/release"))
import candidate_codex_plugin as candidate
from codex_hook_registration import stable_hook_command
import intervention as effects
from grant_broker import transaction

SSH = ("ssh -F /dev/null -o BatchMode=yes -o PermitLocalCommand=no "
       "-o StrictHostKeyChecking=yes -o UpdateHostKeys=no ops@192.0.2.10 ")


@unittest.skipIf(os.name == "nt", "POSIX transport; Windows independently owned")
class StableEntrySSHIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = grants.RecoveryGrantJourneyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.env = candidate._candidate_environment(
            (self.fixture.root / "candidate").resolve(), shutil.which("codex") or "codex",
            candidate._python_identity(Path(sys.executable)))
        context = candidate._process_environment(self.env)
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.runner = candidate._bound_runner(self.env)
        prepared = candidate.installer._stage_artifact(
            Path(self.env["CODEX_HOME"]) / "fixture-artifact", platform="posix", runner=self.runner)
        self.plugin = prepared.marketplace / "plugins/sulde"
        self.generation = prepared.descriptor["delivery_generation"]["generation"]
        candidate._prepare_isolated_hook_launchers(self.plugin,
            Path(self.env["SULDE_KB_HOME"]), self.runner, platform="posix", environment=self.env)
        self.assertEqual(self.hook("fixture-normal", "/usr/bin/stat /opt/app").stdout.strip(), "")

    def hook(self, call, remote):
        payload = {"client": "codex", "session_id": "session-one",
                   "cwd": str(self.fixture.root), "call_id": call,
                   "intent_contract": str(self.fixture.path), "tool_name": "Bash",
                   "tool_input": {"command": SSH + "'" + remote + "'"}}
        result = subprocess.run(["/bin/sh", "-c", stable_hook_command("PreToolUse")],
            input=json.dumps(payload), capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=self.env,
            cwd=self.fixture.root, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("static fallback classified", result.stderr, result.stderr)
        return result

    def denied(self, result):
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_read_normal_then_two_debts_exact_once_and_history_unchanged(self):
        self.assertEqual(self.hook("read-normal", "/usr/bin/stat /opt/app").stdout.strip(), "")
        old = {self.fixture.debt("first"), self.fixture.debt("second")}
        before = effects.event_store_path(self.fixture.path).read_bytes()
        self.assertEqual(self.hook("read-with-debt", "/usr/bin/stat /opt/app").stdout.strip(), "")
        self.assertEqual(effects.event_store_path(self.fixture.path).read_bytes(), before)
        self.denied(self.hook("mkdir-denied", "/bin/mkdir -p -- /opt/app"))
        tx = transaction(self.fixture.path, self.fixture.context()["transaction_id"])
        self.assertEqual(set(tx["spec"]["constraints"]["effect_risk_review"]["attempt_ids"]), old)
        self.fixture.native(tx)  # Synthetic isolated protocol receipt, not host UI evidence.
        self.assertEqual(self.hook("mkdir-once", "/bin/mkdir -p -- /opt/app").stdout.strip(), "")
        projection = effects.load_projection(self.fixture.path)
        new = [row for key, row in projection["attempts"].items() if key not in old]
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]["state"], "dispatched")
        self.assertEqual(new[0]["effect"], "external_write")
        self.assertEqual(set(new[0]["risk_grant"]["accepted_attempt_ids"]), old)
        for identity in old:
            self.assertEqual(projection["attempts"][identity]["state"], "unknown")
        self.denied(self.hook("mkdir-replay", "/bin/mkdir -p -- /opt/app"))
        self.assertEqual(len(effects.load_projection(self.fixture.path)["attempts"]), 3)
        print("STABLE_SSH_GENERATION=" + self.generation, flush=True)

    def test_added_debt_invalidates_card_and_compound_read_is_not_read(self):
        self.fixture.debt("first")
        self.fixture.debt("second")
        self.denied(self.hook("mkdir-denied", "/bin/mkdir -p -- /opt/app"))
        tx = transaction(self.fixture.path, self.fixture.context()["transaction_id"])
        self.fixture.native(tx)
        self.fixture.debt("late")
        self.denied(self.hook("mkdir-stale", "/bin/mkdir -p -- /opt/app"))
        self.denied(self.hook("compound", "/usr/bin/stat /opt/app; /bin/mkdir -p /opt/evil"))
        projection = effects.load_projection(self.fixture.path)
        self.assertEqual(len(projection["attempts"]), 3)
        self.assertTrue(all(row["state"] == "unknown" for row in projection["attempts"].values()))


if __name__ == "__main__":
    unittest.main()
