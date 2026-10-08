"""Same production assertions can run against SULDE_S1_SOURCE_ROOT baseline."""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import sys
import unittest

ROOT = Path(os.environ.get("SULDE_S1_SOURCE_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/kb"))
from tests import test_intent_guardian as fixtures
import intent_guardian as guardian
from intent_guardian_parts import resources
from intent_guardian_parts.resource_preflight import codex_plugin_read_only_maintenance_command


class GuardianS1SemanticsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.IntentGuardianTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root, self.path = self.fixture.root, self.fixture.contract_path
        contract = self.fixture.contract()
        guardian._upsert_task_lane_locked(contract, provider="codex", session_id="s1-semantics", state="bound", source="test")
        guardian.write_contract(self.path, contract)
        self.launcher = shlex.join([sys.executable, str(ROOT / "scripts/kb/intent-guardian.py")])

    def event(self, command, phase="started", **extra):
        return guardian.normalize_hook_event({
            "client": "codex", "session_id": "s1-semantics", "cwd": str(self.root),
            "tool_name": "Bash", "tool_input": {"command": command},
            "call_id": "s1-call", **extra,
        }, phase=phase, provider="codex")

    def observe(self, command, phase="started", **extra):
        return guardian.GuardianSession(self.path).observe(self.event(command, phase, **extra))

    def python(self, source):
        return shlex.join([sys.executable, "-B", "-c", source])

    def ssh(self, remote="/usr/bin/stat -- /srv/app/state", *extra):
        return shlex.join(["ssh", "-F", "/dev/null", "-o", "BatchMode=yes", "-o", "PermitLocalCommand=no",
                           "-o", "StrictHostKeyChecking=yes", "-o", "UpdateHostKeys=no", *extra,
                           "reader@192.0.2.10", remote])

    def test_valid_normal_controls(self):
        for command in (self.launcher + " --help", self.launcher + " --help | sed -n '1,2p'",
                        self.python('print("value".replace("v", "V"))')):
            with self.subTest(command=command):
                self.assertEqual(self.event(command)["effect"], "read")
                decision = self.observe(command)
                self.assertEqual(decision.action, "allow", decision.reason)
        self.assertEqual(resources._command_effect(self.ssh("rm -rf /srv/app/state")), "destructive")

    def test_guardian_human_command_help_is_metadata_at_real_entry(self):
        command = self.launcher + " intervention-resolve --help"
        pre = self.event(command)
        self.assertEqual(pre["effect"], "read")
        self.assertEqual(pre["control_route"], "agent")
        self.assertEqual(pre["control_action"], "--help")
        decision = self.observe(command)
        self.assertEqual(decision.action, "allow", decision.reason)
        completed = subprocess.run(shlex.split(command), cwd=self.root, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("usage:", completed.stdout)
        post = self.observe(command, "completed", success=True)
        self.assertEqual(post.action, "allow", post.reason)

    def test_help_compound_and_business_arguments_keep_boundaries(self):
        for command in (self.launcher + " intervention-resolve event --decision abort --help",
                        self.launcher + " intervention-resolve --HELP",
                        self.launcher + " intervention-resolve -- --help",
                        "./untrusted/intent-guardian intervention-resolve --help"):
            with self.subTest(command=command):
                control = resources._guardian_control_command(command)
                self.assertFalse(control and control.get("metadata_query"))
        self.assertEqual(self.event(self.launcher + " intervention-resolve --help ; rm -rf /") ["effect"], "destructive")
        self.assertNotEqual(self.event(self.launcher + " intervention-resolve --help > help.txt")["effect"], "read")
        decision = self.observe(self.launcher + " intervention-resolve --help ; opaque-writer")
        self.assertEqual(decision.action, "deny")

    def test_maintenance_help_exact_real_parser(self):
        for script, arguments in (("candidate_codex_plugin.py", ["promote", "--help"]),
                                  ("install_codex_plugin.py", ["--help"])):
            command = shlex.join([sys.executable, "-B", str(ROOT / "scripts/release" / script), *arguments])
            with self.subTest(script=script):
                self.assertTrue(codex_plugin_read_only_maintenance_command(command, cwd=ROOT))
                event = self.event(command, cwd=str(ROOT))
                self.assertEqual(event["effect"], "read")
                self.assertFalse(event.get("invocation_violation"))
                decision = guardian.GuardianSession(self.path).observe(event)
                self.assertEqual(decision.action, "allow", decision.reason)
                completed = subprocess.run(shlex.split(command), cwd=ROOT, capture_output=True, text=True,
                                           encoding="utf-8", errors="replace",
                                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=30)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("usage:", completed.stdout)
                post = self.observe(command, "completed", cwd=str(ROOT), success=True)
                self.assertEqual(post.action, "allow", post.reason)

    def test_maintenance_extra_arguments_and_copies_are_not_metadata(self):
        script = ROOT / "scripts/release/candidate_codex_plugin.py"
        for args in (["promote", "slot", "--help"], ["--codex", "--help", "promote", "slot"],
                     ["promote", "--HELP"], ["promote", "--", "--help"]):
            self.assertFalse(codex_plugin_read_only_maintenance_command(shlex.join([sys.executable, str(script), *args]), cwd=ROOT))
        copy = self.root / "candidate_codex_plugin.py"
        copy.write_text("print('untrusted')\n")
        self.assertFalse(codex_plugin_read_only_maintenance_command(shlex.join([sys.executable, str(copy), "promote", "--help"]), cwd=ROOT))

    def test_sed_file_operands_are_proved_inside_control_composition(self):
        source = self.root / "input.txt"
        source.write_text("one\ntwo\nthree\n")
        for operands in (shlex.quote(str(source)), "-- " + shlex.quote(str(source))):
            command = self.launcher + " --help ; sed -n '1,2p' " + operands
            event = self.event(command)
            self.assertEqual(event["effect"], "read", event.get("composition"))
            self.assertFalse(event["composition"]["error"])
            self.assertEqual(self.observe(command).action, "allow")
        command = self.launcher + " --help ; sed -n '1,2p' " + shlex.quote(str(source))
        completed = subprocess.run(command, shell=True, cwd=self.root, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(completed.stdout.endswith("one\ntwo\n"))
        self.assertEqual(self.observe(command, "completed", success=True).action, "allow")
        for tail in ("sed -n '1w output' input.txt", "sed -n p -e 'w output' input.txt", "sed -n p -i input.txt"):
            self.assertEqual(self.observe(self.launcher + " --help ; " + tail).action, "deny")

    def test_datetime_receiver_and_factory_proofs(self):
        for source in (
            'from datetime import datetime, timezone; print(datetime.fromisoformat("2026-10-04").replace(tzinfo=timezone.utc))',
            'import datetime as d; value=d.datetime.fromisoformat("2026-10-04"); print(value.replace(tzinfo=d.timezone.utc).isoformat())',
            'from datetime import datetime as D; value=D.fromisoformat("2026-10-04"); print(value.replace(year=2025))',
        ):
            command = self.python(source)
            event = self.event(command)
            self.assertEqual(event["effect"], "read", event.get("invocation_violation"))
            self.assertFalse(event.get("invocation_violation"))
            decision = self.observe(command)
            self.assertEqual(decision.action, "allow", decision.reason)
            result = subprocess.run(shlex.split(command), capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.observe(command, "completed", success=True).action, "allow")

    def test_datetime_proof_does_not_hide_unknown_or_file_mutation(self):
        for source in (
            'from pathlib import Path; Path("a").replace("b")',
            'from datetime import datetime; datetime=opaque(); datetime.fromisoformat("2026-10-04").replace(year=2025)',
            'from datetime import datetime; value=datetime.fromisoformat("2026-10-04"); opaque(); value.replace(year=2025)',
            'from datetime import datetime; value=datetime.fromisoformat("2026-10-04"); value.replace(tzinfo=opaque())',
            'from datetime import datetime; datetime.fromisoformat=opaque; datetime.fromisoformat("2026-10-04").replace(year=2025)',
            'from datetime import datetime\ndef later():\n return datetime.fromisoformat("2026-10-04").replace(year=2025)',
        ):
            with self.subTest(source=source):
                self.assertNotEqual(self.event(self.python(source))["effect"], "read")

    def test_config_free_ssh_probe_is_remote_read_with_limits(self):
        for remote in ("/usr/bin/stat -- /srv/app/state", "/bin/ls -ld -- /srv/app"):
            command = self.ssh(remote)
            risks = []
            self.assertEqual(resources._command_effect(command, risks=risks), "read")
            self.assertIn("remote_execution", risks)
            self.assertNotIn("remote_execution_unresolved", risks)
            self.assertEqual(self.event(command)["effect"], "read")

    def test_ssh_opaque_config_dynamic_and_write_shapes_stay_blocked(self):
        for command in (
            self.ssh("/usr/bin/stat -- /srv/app", "-o", "ProxyCommand=touch marker"),
            self.ssh().replace("-F /dev/null", "-F config"),
            self.ssh().replace("UpdateHostKeys=no", "UpdateHostKeys=yes"),
            self.ssh().replace("reader@192.0.2.10", "reader@server-alias"),
            self.ssh().replace("reader@192.0.2.10", "192.0.2.10"),
            self.ssh("/usr/bin/stat -- /srv/../secret"), self.ssh("cat /etc/private"),
            self.ssh("/usr/bin/stat -- $TARGET"), self.ssh("/usr/bin/stat -- /srv/a ; touch /srv/b"),
            self.ssh("deploy /srv/app"), self.ssh("rm -rf /srv/app"),
            "sudo " + self.ssh(), self.ssh("/bin/ls -ld -- /srv/app", "-A"),
        ):
            with self.subTest(command=command):
                self.assertNotEqual(resources._command_effect(command), "read")


if __name__ == "__main__":
    unittest.main()
