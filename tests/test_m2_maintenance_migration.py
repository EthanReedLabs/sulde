"""Owned-host maintenance rehearsal, NOT a production migration adapter.

The cohort/barrier below belongs only to this fixture's parent. Native unowned
hosts are outside its guarantees. Real CLI registration is exercised; the Sulde
installer's legacy gate is deliberately not bypassed or claimed to have passed.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.test_m1_host_migration import Host, PROBE, EVENTS, candidate


class MaintenanceFixture:
    def __init__(self, case, slot, stack):
        self.case, self.slot, self.stack = case, slot, stack
        self.codex = shutil.which("codex")
        case.assertIsNotNone(self.codex)
        self.env = candidate._candidate_environment(slot, self.codex,
            candidate._python_identity(Path(sys.executable)))
        self.trace = Path(self.env["SULDE_HOME"]) / "m2-trace.jsonl"
        self.env["M1_TRACE"] = str(self.trace)
        self.market = slot / "marketplace"
        self.plugin = self.market / "plugins/sulde"
        for relative in (".agents/plugins", "plugins/sulde/.codex-plugin", "plugins/sulde/hooks"):
            (self.market / relative).mkdir(parents=True)
        (self.market / ".agents/plugins/marketplace.json").write_text(json.dumps({
            "name": "sulde-local", "plugins": [{"name": "sulde", "source": {
                "source": "local", "path": "./plugins/sulde"}, "policy": {
                "installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Productivity"}]}), encoding="utf-8")
        self.stable = Path(self.env["SULDE_HOME"]) / "fixture-stable.py"
        self.stable.write_text(PROBE, encoding="utf-8")
        self.hosts = []
        self.registry_changes = 0

    def save(self, phase, data):
        print("M2_OBSERVATION=" + json.dumps({"case": self.case.id(), "phase": phase,
              "data": data}, sort_keys=True), flush=True)

    def cli(self, *args):
        result = subprocess.run([self.codex, *args], cwd=self.slot, env=self.env,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.save("cli", {"args": args, "rc": result.returncode,
                         "stdout": result.stdout, "stderr": result.stderr})
        self.case.assertEqual(result.returncode, 0, result.stderr)

    def publish(self, version):
        (self.plugin / ".codex-plugin/plugin.json").write_text(json.dumps({
            "name": "sulde", "version": version, "hooks": "./hooks/hooks.json"}), encoding="utf-8")
        (self.plugin / "hooks/probe.py").write_text(PROBE, encoding="utf-8")
        target = '"${PLUGIN_ROOT}/hooks/probe.py"' if version == "0.0.1" else shlex.quote(str(self.stable))
        (self.plugin / "hooks/hooks.json").write_text(json.dumps({"hooks": {
            event: [{"hooks": [{"type": "command", "timeout": 10, "command":
                shlex.quote(sys.executable) + " -B " + target + " " + version + " " + event}]}]
            for event in EVENTS}}), encoding="utf-8")

    def begin(self):
        self.cli("--version")
        self.save("launcher", {"path": str(Path(self.codex).resolve()),
            "sha256": hashlib.sha256(Path(self.codex).resolve().read_bytes()).hexdigest()})
        self.publish("0.0.1")
        self.cli("plugin", "marketplace", "add", str(self.market))
        self.cli("plugin", "add", "sulde@sulde-local")

    def host(self, name, *, trust=True, resume=None):
        workspace = Path(self.env["SULDE_HOME"]).parent / name
        workspace.mkdir(exist_ok=True)
        lifecycle = Host(self.codex, workspace, self.env, externally_isolated=True).start()
        value = self.stack.enter_context(lifecycle)
        if trust:
            value.trust()  # exact synthetic hashes, isolated home only
        if resume is None:
            value.thread()
        else:
            result = value.rpc("thread/resume", {"threadId": resume, "cwd": str(workspace),
                "approvalPolicy": "never", "sandbox": "danger-full-access", "modelProvider": "m1_local"})
            value.session = result["thread"]["id"]
            self.case.assertEqual(value.session, resume)
        self.hosts.append((value, lifecycle))
        return value

    def stop(self, host):
        lifecycle = next(context for value, context in self.hosts if value is host)
        lifecycle.__exit__(None, None, None)
        self.case.assertIsNotNone(host.process.poll())
        self.case.assertTrue(host.process._sulde_fixture_closed)
        self.save("owned-host-stopped", {"pid": host.process.pid, "session": host.session,
            "rc": host.process.returncode, "group_closed": True})

    def switch(self, version):
        live = [host.process.pid for host, _ in self.hosts if host.process.poll() is None]
        self.save("cohort-check", {"live_owned_pids": live, "coverage": "fixture-owned-only",
                                  "global_drain_verified": False})
        if live:
            raise RuntimeError("fixture cohort still active; no registry update")
        self.publish(version)
        self.cli("plugin", "add", "sulde@sulde-local")
        self.registry_changes += 1

    def turn(self, name, host, expected):
        before = len(self.trace.read_text(encoding="utf-8").splitlines()) if self.trace.exists() else 0
        result = host.turn()
        callbacks = [json.loads(line) for line in self.trace.read_text(encoding="utf-8").splitlines()][before:] if self.trace.exists() else []
        self.save(name, {"pid": host.process.pid, "session": host.session,
                        "callbacks": callbacks, "host": result})
        self.case.assertEqual(result["calls"], 2)
        self.case.assertEqual(len(result["items"]), 1)
        self.case.assertEqual(result["items"][0]["params"]["item"]["exitCode"], 0)
        if expected is None:
            self.case.assertEqual(callbacks, [])
            self.case.assertFalse(any(row["method"] == "hook/completed" for row in result["hooks"]))
            self.save("not-ready", {"reason": "no trusted callback despite tool exit 0"})
        else:
            self.case.assertTrue({"UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"}.issubset(
                {row["event"] for row in callbacks}))
            for row in callbacks:
                self.case.assertEqual(row["session"], host.session)
                self.case.assertEqual(row["version"], expected)
                self.case.assertEqual(row["script_sha256"], hashlib.sha256(PROBE.encode()).hexdigest())
                if expected == "0.0.2":
                    self.case.assertEqual(row["script"], str(self.stable))
                else:
                    self.case.assertIn("/0.0.1/hooks/probe.py", row["script"])


@unittest.skipUnless(os.environ.get("SULDE_ISOLATED_TEST_RUN_ID"), "requires official OS-isolated runner")
@unittest.skipIf(os.name == "nt", "POSIX owned-host rehearsal only")
class M2MaintenanceTests(unittest.TestCase):
    def fixture(self, stack):
        slot = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="sulde-m2-"))).resolve()
        value = MaintenanceFixture(self, slot, stack)
        value.begin()
        return value

    def test_normal_maintenance_resumes_two_threads_after_owned_cohort_exit(self):
        with ExitStack() as stack:
            f = self.fixture(stack)
            a, b = f.host("A"), f.host("B")
            f.turn("normal-A", a, "0.0.1")
            f.turn("normal-B", b, "0.0.1")
            f.stop(a)
            with self.assertRaisesRegex(RuntimeError, "cohort still active"):
                f.switch("0.0.2")
            self.assertEqual(f.registry_changes, 0)
            f.turn("surviving-B-unchanged", b, "0.0.1")
            f.stop(b)
            f.switch("0.0.2")
            new_a, new_b = f.host("A", resume=a.session), f.host("B", resume=b.session)
            self.assertNotEqual(a.process.pid, new_a.process.pid)
            self.assertNotEqual(b.process.pid, new_b.process.pid)
            f.turn("resumed-A", new_a, "0.0.2")
            f.turn("resumed-B", new_b, "0.0.2")
            f.save("scope", {"maintenance_cohort_verified": True, "production_migration_verified": False,
                "permission_request_exercised": False, "external_model_calls": 0})

    def test_missing_trust_stays_not_ready_and_cold_rollback_restores_old_hook(self):
        with ExitStack() as stack:
            f = self.fixture(stack)
            old = f.host("A")
            f.turn("normal-before-failure", old, "0.0.1")
            f.stop(old)
            f.switch("0.0.2")
            untrusted = f.host("A", trust=False, resume=old.session)
            f.save("untrusted-inventory", untrusted.rpc("hooks/list", {"cwds": [str(untrusted.workspace)]}))
            f.turn("injected-trust-omission", untrusted, None)
            f.stop(untrusted)
            # Restore via official plugin CLI, not direct cache/registry editing.
            f.switch("0.0.1")
            restored = f.host("A", resume=old.session)
            f.turn("restored-old-thread", restored, "0.0.1")
            f.save("scope", {"fixture_rollback_verified": True, "sulde_transaction_exercised": False,
                "production_migration_verified": False, "external_model_calls": 0})


if __name__ == "__main__":
    unittest.main()
