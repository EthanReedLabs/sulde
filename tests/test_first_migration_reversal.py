"""Real installer + reversal controller with fake OS/CLI observations.

No production state or human approval. Forward and inverse predicates,
snapshots, journal, fence and registry mutations are real fixture operations.
"""
import json
import os
from pathlib import Path
import unittest
from unittest import mock

from tests import test_legacy_maintenance_install as forward
from tests.test_codex_plugin_install import CodexPluginInstallFixture, ROOT


REVERSE_ENTRY = '''import hashlib,json,os,sys,contextlib,io,subprocess
from pathlib import Path
sys.path.insert(0,SOURCE+"/scripts/release")
import install_codex_plugin as m
import legacy_maintenance as maintenance
import first_migration_reversal as reversal
import candidate_codex_plugin as candidate
# Only external OS/provider observation boundaries are replaced.
host={"pid":100,"started":"fixture-host-start","executable":"/fixture/codex"}
rows=[{**host,"parent_pid":1},{"pid":os.getpid(),"parent_pid":100,"started":"fixture-worker-start","executable":"/fixture/python"}]
maintenance.process_inventory=lambda: rows
old_environment=maintenance.target_environment
def environment(plan):
 result=old_environment(plan)
 result.update({key:value for key,value in os.environ.items() if key.startswith("FAKE_") or key in {"SULDE_TEST_MODE","SULDE_LAUNCHCTL","SULDE_PS","SULDE_INSTALL_FAILPOINT","SULDE_INSTALL_HARD_EXIT"}})
 return result
maintenance.target_environment=environment
kb=Path(os.environ["SULDE_KB_HOME"]).resolve()
plan_file=kb.parent/"reverse-plan.json"
if not plan_file.exists():
 leases=kb.parent/"managed/run-leases"; leases.mkdir(parents=True,exist_ok=True)
 roots={"kb_home":str(kb),"codex_home":str(m.default_codex_home().resolve()),
  "user_home":str(Path.home().resolve()),"launcher_home":str(m.launcher_home(kb).resolve()),
  "launchagents_dir":str(m._launchagents_dir().resolve())}
 draft=kb.parent/"reverse-draft.json"
 # Exercise the shipped CLI parser in this real process; only external
 # OS/CLI observations above are fixtures, not the preparation function.
 sys.argv=["first_migration_reversal.py","prepare","--codex",CODEX,"--leases-dir",str(leases),"--output",str(draft)]
 for key,value in roots.items(): sys.argv.extend(["--"+key.replace("_","-"),value])
 with contextlib.redirect_stdout(io.StringIO()): reversal.main()
 plan=json.loads(draft.read_bytes()); plan["maintenance_host"]=host; plan["cohort"]=[]
 plan_file.write_bytes(maintenance.canonical(plan)); plan_file.chmod(0o600)
plan=json.loads(plan_file.read_bytes())
case=os.environ.get("REVERSAL_CASE")
if case=="expired": plan.update(created_at=1,expires_at=2)
if case=="unknown-caller": rows.append({**host,"pid":101,"parent_pid":1})
if case=="wrong-origin": plan["origin"]["descriptor_sha256"]="0"*64
if case=="missing-scope": plan["lease_scopes"][0]["path"]=str(kb.parent/"missing-leases")
if case=="no-scopes": plan["lease_scopes"]=[]
if case=="source-drift": plan["source_files"][next(iter(plan["source_files"]))]="0"*64
if case=="cas-drift": plan["current_state"]["marketplace"]="/unrelated"
lease=None
if case in {"incompatible-lease","unknown-lease"}:
 from run_concurrency import acquire_run_slot
 lease=acquire_run_slot(kb.parent/case,runtime_generation=("other:"+"1"*64 if case=="incompatible-lease" else None))
 plan["lease_scopes"]=[reversal._bind_scope(lease.path.parent)]
if case=="scope-replaced":
 from run_concurrency import acquire_run_slot
 scope=Path(plan["lease_scopes"][0]["path"])
 lease=acquire_run_slot(scope.parent,runtime_generation="other:"+"1"*64)
 scope.rename(scope.with_name("held-old-scoped-leases")); scope.mkdir()
raw=maintenance.canonical(plan)
context=reversal.ReversalContext(raw,hashlib.sha256(raw).hexdigest())
if os.environ.get("REVERSAL_CLOCK_EXPIRED"):
 reversal.time.time=lambda: plan["expires_at"]+1
if os.environ.get("REVERSAL_PREPARE_ONLY"):
 print(json.dumps({"status":"draft-only"})); sys.exit(0)
if os.environ.get("REVERSAL_RECOVER_ONLY"):
 result=m.recover_only(kb_home=kb,codex=CODEX)
elif os.environ.get("REVERSAL_HELD_BUNDLE"):
 bundle=kb.parent/"reverse-held-bundle.json"
 sealed=maintenance.prepare_bundle(plan_file,hashlib.sha256(plan_file.read_bytes()).hexdigest(),bundle,root=m.ROOT)
 # Execute actual held-source BOOTSTRAP and closed operation dispatch.
 # The import instrumentation replaces ONLY process inventory and fake
 # CLI environment plumbing, the same external boundaries as this fixture.
 injection="""import builtins,os
_original_import=builtins.__import__
def _observe(name,*args,**kwargs):
 module=_original_import(name,*args,**kwargs)
 if name=='legacy_maintenance' and not getattr(module,'_fixture_observed',False):
  module._fixture_observed=True
  host={'pid':100,'started':'fixture-host-start','executable':'/fixture/codex'}
  module.process_inventory=lambda:[{**host,'parent_pid':1},{'pid':os.getpid(),'parent_pid':100,'started':'fixture-worker-start','executable':'/fixture/python'}]
  original=module.target_environment
  def target(plan):
   result=original(plan)
   result.update({k:v for k,v in os.environ.items() if k.startswith('FAKE_') or k in {'SULDE_TEST_MODE','SULDE_LAUNCHCTL','SULDE_PS'}})
   return result
  module.target_environment=target
 return module
builtins.__import__=_observe
"""
 held=subprocess.run([sys.executable,"-B","-I","-c",injection+maintenance.BOOTSTRAP,str(bundle),sealed["bundle_sha256"]],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=120)
 if held.returncode: raise RuntimeError(held.stderr)
 result=json.loads(held.stdout)
else:
 result=reversal.execute(context)
print(json.dumps(result))
'''


@unittest.skipIf(os.name == "nt", "POSIX first migration")
class FirstMigrationReversalTests(CodexPluginInstallFixture, unittest.TestCase):
    prepare_transition = forward.MaintenanceInstallTests.prepare_transition
    transition = forward.MaintenanceInstallTests.transition

    def migrated(self):
        shim, old = self.prepare_transition()
        old_deployment = (self.kb_home / "deployment-generation.json").read_bytes()
        result = self.transition(shim)
        self.assertEqual(result.returncode, 0, result.stderr)
        script = self.root / "reverse-entry.py"
        script.write_text(f"SOURCE={str(ROOT)!r}\nCODEX={str(self.fake.resolve())!r}\n" + REVERSE_ENTRY,
                          encoding="utf-8")
        return script, old_deployment

    def reverse(self, script, **kwargs):
        with mock.patch("tests.test_codex_plugin_install.INSTALLER", script):
            return self.run_installer(prepare_artifact=False, initialize_launchctl_state=False, **kwargs)

    def test_normal_committed_inverse_restores_old_and_replay_is_read_only(self):
        script, old = self.migrated()
        origin = self.kb_home / ".install-recovery/transactions" / ("a" * 32)
        before = {path.name: path.read_bytes() for path in origin.iterdir() if path.is_file()}
        result = self.reverse(script, extra_environment={"REVERSAL_HELD_BUNDLE": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "reversed_first_migration")
        self.assertEqual((self.kb_home / "deployment-generation.json").read_bytes(), old)
        self.assertFalse((self.kb_home / ".install-recovery/active.json").exists())
        self.assertFalse((self.kb_home / ".generation-switch-fence.json").exists())
        self.assertEqual(before, {path.name: path.read_bytes() for path in origin.iterdir() if path.is_file()})
        again = self.reverse(script)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(json.loads(again.stdout)["transaction_id"], json.loads(result.stdout)["transaction_id"])
        self.assertEqual((self.kb_home / "deployment-generation.json").read_bytes(), old)

    def test_negative_start_controls_leave_current_installation_unchanged(self):
        script, _ = self.migrated()
        before = (self.kb_home / "deployment-generation.json").read_bytes()
        reasons = {"expired": "expired", "unknown-caller": "unknown Codex", "wrong-origin": "descriptor digest mismatch",
                   "missing-scope": "lease scope unavailable", "no-scopes": "explicit lease scope",
                   "source-drift": "executable source changed", "cas-drift": "prestate drifted",
                   "incompatible-lease": "generational switch blocked", "unknown-lease": "generational switch blocked",
                   "scope-replaced": "lease scope identity drifted"}
        for case, reason in reasons.items():
            with self.subTest(case=case):
                result = self.reverse(script, extra_environment={"REVERSAL_CASE": case})
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(reason, result.stderr)
                self.assertEqual((self.kb_home / "deployment-generation.json").read_bytes(), before)
                self.assertFalse((self.kb_home / ".install-recovery/active.json").exists())
                self.assertFalse((self.kb_home / ".generation-switch-fence.json").exists())

    def crash_resume(self, point):
        script, old = self.migrated()
        result = self.reverse(script, failpoint=point)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        active = self.kb_home / ".install-recovery/active.json"
        self.assertTrue(active.exists(), result.stderr)
        active_before = active.read_bytes()
        before = (self.kb_home / "deployment-generation.json").read_bytes()
        refused = self.run_installer(prepare_artifact=False, initialize_launchctl_state=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("reversal owns recovery", refused.stderr)
        self.assertEqual(active.read_bytes(), active_before)
        self.assertEqual((self.kb_home / "deployment-generation.json").read_bytes(), before)
        if point == "reversal.after_restore":
            fence_path = self.kb_home / ".generation-switch-fence.json"
            fence_bytes = fence_path.read_bytes()
            fence = json.loads(fence_bytes)
            fence["transaction_descriptor_sha256"] = "0" * 64
            fence_path.write_text(json.dumps(fence), encoding="utf-8")
            refused = self.reverse(script, extra_environment={"REVERSAL_RECOVER_ONLY": "1"})
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("foreign or damaged", refused.stderr)
            self.assertEqual(active.read_bytes(), active_before)
            self.assertTrue(fence_path.exists())
            fence_path.write_bytes(fence_bytes)  # undo only the injected corruption
            plan = json.loads((self.kb_home.parent / "reverse-plan.json").read_bytes())
            scope = Path(plan["lease_scopes"][0]["path"])
            preserved = scope.with_name("preserved-scope")
            scope.rename(preserved)
            scope.mkdir()
            refused = self.reverse(script, extra_environment={"REVERSAL_RECOVER_ONLY": "1"})
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("lease scope identity drifted", refused.stderr)
            self.assertEqual(active.read_bytes(), active_before)
            scope.rmdir()
            preserved.rename(scope)  # restore the actual approved directory identity
        result = self.reverse(script, extra_environment={"REVERSAL_RECOVER_ONLY": "1", "REVERSAL_CLOCK_EXPIRED": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "reversed_first_migration")
        self.assertEqual((self.kb_home / "deployment-generation.json").read_bytes(), old)
        self.assertFalse(active.exists())
        self.assertFalse((self.kb_home / ".generation-switch-fence.json").exists())

    def test_crash_after_durable_start_resumes_without_install(self):
        self.crash_resume("reversal.after_active")

    def test_crash_during_restore_resumes(self):
        self.crash_resume("reversal.after_restore")

    def test_crash_after_commit_resumes_cleanup_only(self):
        self.crash_resume("journal.after.committed")

    def test_intervening_stable_update_is_not_a_first_migration_inverse(self):
        script, _ = self.migrated()
        update = self.run_installer(initialize_launchctl_state=False)
        self.assertEqual(update.returncode, 0, update.stderr)
        before = (self.kb_home / "deployment-generation.json").read_bytes()
        result = self.reverse(script)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("eligible legacy destination", result.stderr)
        self.assertEqual((self.kb_home / "deployment-generation.json").read_bytes(), before)
        self.assertFalse((self.kb_home / ".install-recovery/active.json").exists())


if __name__ == "__main__":
    unittest.main()
