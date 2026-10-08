"""Actual installer + native registry/config/Hook discovery, isolated homes only.

Scheduler, process ownership and approval receipt are fixtures. The production
trust callback, CAS, install journal, rollback and native API are NOT mocked.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from tests.test_live_cache_handoff_install import LiveCacheInstallTests
from tests.test_codex_hook_trust import trust
from tests import test_first_migration_reversal as inverse


@unittest.skipUnless(os.environ.get("LIVE_HANDOFF_TEST_CODEX"), "requires explicit official CLI")
class LiveTrustInstallTests(LiveCacheInstallTests):

    def prepare_trust(self, *, include_trust=True):
        shim, old = self.prepare_live(extra_legacy=False)
        # The historical fixture mutates one staging directory for both
        # versions. Freeze a real old marketplace before binding rollback:
        # unlike the fake CLI, native plugin add actually reads its manifest.
        old_market = self.root / "frozen-old-market"
        old_cache = self.codex_home / "plugins/cache/sulde-local/sulde" / old["plugin_version"]
        shutil.copytree(old_cache, old_market / "plugins/sulde")
        (old_market / ".agents/plugins").mkdir(parents=True)
        shutil.copyfile(self.artifact / ".agents/plugins/marketplace.json",
                        old_market / ".agents/plugins/marketplace.json")
        for args in (["plugin","marketplace","remove","sulde-local"],
                     ["plugin","marketplace","add",str(old_market)]):
            result = subprocess.run([self.real_cli,*args],cwd=self.root,env=os.environ.copy(),
                capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        state["marketplace"] = str(old_market)
        self.state.write_text(json.dumps(state),encoding="utf-8")
        # Initial fixture install intentionally models legacy defaults. From
        # this point all Hook/config requests go to the actual native binary.
        source = self.fake.read_text(encoding="utf-8")
        source = source.replace('args = sys.argv[1:]',
            'args = sys.argv[1:]\nif args[:1] == ["app-server"]:\n os.execv(' + repr(self.real_cli) + ', [' + repr(self.real_cli) + ', *args])')
        self.fake.write_text(source, encoding="utf-8")
        cwd = self.root
        with trust.NativeClient(self.real_cli) as client:
            payload = client.call("hooks/list", {"cwds":[str(cwd)]})
            hooks = [h for r in payload["data"] for h in r["hooks"] if h.get("pluginId")==trust.PLUGIN]
            self.assertEqual(len(hooks), 6)
            previous = {h["key"]: h["currentHash"] for h in hooks}
            partial = {"config_file":str(self.codex_home/"config.toml"), "previous":previous}
            before = trust.read_values(client, partial, cwd=cwd)
            trust.write_values(client, partial, before, previous)
        self.previous_trust = previous
        candidate_home = self.root / "native-candidate-home"
        candidate_home.mkdir()
        env = dict(os.environ, CODEX_HOME=str(candidate_home))
        for args in (["plugin","marketplace","add",str(self.artifact)],
                     ["plugin","add",trust.PLUGIN,"--json"]):
            result = subprocess.run([self.real_cli,*args],env=env,cwd=cwd,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
        installed = Path(json.loads(result.stdout)["installedPath"])
        with trust.NativeClient(self.real_cli, environment=env) as client:
            payload = client.call("hooks/list",{"cwds":[str(cwd)]})
            rows = trust.definitions(payload,cwd=cwd,plugin_root=installed)
        if include_trust:
            source = shim.read_text(encoding="utf-8")
            source = source.replace('"schema":maintenance.LIVE_SCHEMA', '"schema":maintenance.TRUST_SCHEMA')
            source = source.replace('ctx=maintenance.LiveHandoffContext(', 'ctx=maintenance.TrustedLiveHandoffContext(')
            assignment = ('plan["hook_trust"]={"schema":"sulde-exact-hook-trust-v1",'
                '"config_file":str(m.default_codex_home()/"config.toml"),'
                '"artifact_tree_sha256":prepared.plugin_tree_sha256,'
                '"definitions":'+repr(rows)+',"previous":'+repr(previous)+'}\n ')
            source = source.replace('raw=maintenance.canonical(plan);',assignment+'raw=maintenance.canonical(plan);')
            shim.write_text(source,encoding="utf-8")
        return shim, old

    def test_normal_v2_install_trusts_exact_native_hooks(self):
        shim, old = self.prepare_trust()
        result = self.observed_transition(shim,old)
        self.assertEqual(result.returncode,0,result.stderr)
        result = json.loads(result.stdout)
        self.assertFalse(result["operational_ready"], "fixture is not live production acceptance")
        with trust.NativeClient(self.real_cli) as client:
            data = client.call("hooks/list",{"cwds":[str(self.root)]})
            self.assertTrue(all(h["trustStatus"]=="trusted" for r in data["data"] for h in r["hooks"]))

    def test_unchanged_v1_missing_trust_refuses_and_preserves_details(self):
        shim, old = self.prepare_trust(include_trust=False)
        result = self.observed_transition(shim,old)
        self.assertNotEqual(result.returncode,0)
        self.assertIn("atomically restored old generation",result.stderr)
        evidence = list((self.kb_home/".install-recovery/transactions").glob("*/hook-trust-readiness-failure-*.json"))
        self.assertEqual(len(evidence),1)
        value = json.loads(evidence[0].read_text(encoding="utf-8"))["value"]
        self.assertEqual(value["status"],"review_required")
        self.assertEqual(len(value["unrunnable_events"]),6)

    def test_crash_after_trust_write_recovery_restores_native_values(self):
        shim, old = self.prepare_trust()
        result = self.observed_transition(shim,old,failpoint="journal.after.hook_trust_written")
        self.assertEqual(result.returncode,86,result.stderr)
        result = self.observed_transition(shim,old,recover_only=True)
        self.assertEqual(result.returncode,0,result.stderr)
        with trust.NativeClient(self.real_cli) as client:
            plan={"config_file":str(self.codex_home/"config.toml"),"previous":self.previous_trust}
            self.assertEqual(trust.read_values(client,plan,cwd=self.root)["values"],self.previous_trust)
        self.assertFalse((self.kb_home/".install-recovery/active.json").exists())

    def test_separately_authorized_inverse_restores_trust_via_native_api(self):
        shim, old = self.prepare_trust()
        result = self.observed_transition(shim,old)
        self.assertEqual(result.returncode,0,result.stderr)
        # The inverse requires a drained owned cohort. It is not a claim of
        # same-session postcommit live downgrade. OS facts alone are fixtures.
        from tests.test_codex_plugin_install import ROOT
        script = self.root / "reverse-entry.py"
        entry = inverse.REVERSE_ENTRY.replace("import install_codex_plugin as m",
            "import install_codex_plugin as m\nm.plugin_version=lambda *args: '0.9.0+live-handoff-test'")
        script.write_text(f"SOURCE={str(ROOT)!r}\nCODEX={str(self.fake.resolve())!r}\n" + entry,
                          encoding="utf-8")
        result = inverse.FirstMigrationReversalTests.reverse(self,script)
        self.assertEqual(result.returncode,0,result.stderr)
        with trust.NativeClient(self.real_cli) as client:
            plan={"config_file":str(self.codex_home/"config.toml"),"previous":self.previous_trust}
            self.assertEqual(trust.read_values(client,plan,cwd=self.root)["values"],self.previous_trust)


if __name__ == "__main__":
    unittest.main()
