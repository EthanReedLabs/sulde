"""Real installer transaction with synthetic host/candidate evidence.

Not human approval or production/native-Hook acceptance. The shim supplies the
internal context; OS/host observations and staged artifact producer are fixtures.
CAS, journal, rollback and readiness remain real. The home-source race case
alone injects changing observations at the filesystem discovery boundary.
"""
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest import mock

from tests.test_codex_plugin_install import CodexPluginInstallFixture, load_installer, ROOT

SHIM = '''import hashlib,json,os,sys,time
from pathlib import Path
sys.path.insert(0, SOURCE + "/scripts/release")
import install_codex_plugin as m
import legacy_maintenance as maintenance
import candidate_codex_plugin as candidate
real_install=m.install
if os.environ.get("MAINTENANCE_FORBID_MEMORY_WRITE") == "1":
 def forbidden_memory_write(*args,**kwargs):
  raise AssertionError("maintenance called memory reconciliation writer")
 m.reconcile_memory_homes=forbidden_memory_write
def install(**kwargs):
 artifact=kwargs["artifact"].resolve(); kb=kwargs["kb_home"].resolve(); codex=kwargs["codex"]
 descriptor=m.validate_staged_marketplace(artifact,expected_version=m.plugin_version())
 prepared=m.PreparedArtifact(artifact,descriptor,m.tree_digest(artifact/"plugins/sulde"))
 live=m.deployment_cas_snapshot(kb,codex)
 generation=descriptor["delivery_generation"]
 ready={key:{"status":"ready"} for key in ("artifact","isolated_registry","hooks","preexecution_chain","mcp","doctor","scheduler_entrypoint")}
 ready["preexecution_chain"].update(transport="codex-cli-app-server",native_tool="exec_command",executor="unified_exec",positive_executed=True,outside_plan_write_executed=True,destructive_pre_denied=True,marker_absent=True,artifact_generation=generation["generation"],loaded_module_generation="f"*64,proof_id="e"*64,session_id="fixture",started_event_id="fixture",scope_denial_event_id="fixture",native_denial_run_id="fixture")
 ready.update(native_permission_ui={"status":"unobserved","exit_code":78},scheduler_host={"status":"unobserved","exit_code":79})
 identity=m._codex_command_identity(codex)
 receipt=candidate._sealed({"schema":m.CANDIDATE_RECEIPT_SCHEMA,"schema_version":1,"status":"verified",
  "source":{"commit":m.run_command(["git","rev-parse","HEAD"],cwd=m.ROOT).stdout.strip(),"tree":m.run_command(["git","rev-parse","HEAD^{tree}"],cwd=m.ROOT).stdout.strip()},
  "artifact":{"path":str(artifact),"plugin_tree_sha256":prepared.plugin_tree_sha256,**{k:generation[k] for k in ("runtime_tree_sha256","generation","plugin_version","platform")}},
  "codex":{"executable":identity["codex_command"],"executable_sha256":identity["codex_command_sha256"],"version":m.run_command([codex,"--version"]).stdout.strip()},
  "python":m.invoking_environment(),"live_prestate":live,"live_prestate_sha256":hashlib.sha256(m._canonical_json_bytes(live)).hexdigest(),"verifications":ready},"receipt_sha256")
 host={"pid":100,"started":"fixture-host-start","executable":"/fixture/codex"}
 plan={"schema":maintenance.SCHEMA,"operation_id":"a"*32,"created_at":time.time()-1,"expires_at":time.time()+300,
  "kb_home":str(kb),"codex_home":str(m.default_codex_home().resolve()),"codex":str(Path(codex).resolve()),
  "candidate_home":str(artifact.parent),"candidate_id":"fixture","receipt_sha256":receipt["receipt_sha256"],
  "artifact_tree_sha256":prepared.plugin_tree_sha256,"old_state":live,"cache_bindings":m._stable_cache_bindings(sorted(m._canonical_cache_root().iterdir())),
  "cohort":[{**host,"pid":99}],"maintenance_host":host,"source_files":{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in maintenance.source_paths(Path(SOURCE))},
  "user_home":str(Path.home().resolve()),"launcher_home":str(m.launcher_home(kb).resolve()),"launchagents_dir":str(m._launchagents_dir().resolve())}
 rows=[{**host,"parent_pid":1},{"pid":os.getpid(),"parent_pid":100,"started":"fixture-worker-start","executable":"/fixture/python"}]
 kind=os.environ.get("MAINTENANCE_CASE","normal")
 if kind=="home-source-observation-race":
  observations=iter((None,kb.parent/"legacy-source",None))
  m._legacy_home_migration_source=lambda unused: next(observations,None)
  def forbidden_home_write(*args,**kw):
   raise AssertionError("maintenance reached home migration writer")
  m.apply_home_migration=forbidden_home_write
 plan["operation_id"]=os.environ.get("MAINTENANCE_OPERATION_ID", "a"*32)
 if kind=="partial-sources": plan["source_files"].pop(next(iter(plan["source_files"])))
 if kind=="live": rows.append({**host,"pid":99,"parent_pid":1})
 if kind=="expired": plan.update(created_at=time.time()-20,expires_at=time.time()-10)
 if kind=="stale": plan["old_state"]={**live,"marketplace":"/different"}
 late=False
 original_retire=m._publish_retirement_targets
 def retire(*args,**kw):
  nonlocal late
  result=original_retire(*args,**kw); late=True
  return result
 m._publish_retirement_targets=retire
 def inventory():
  return rows+([{**host,"pid":103,"parent_pid":1}] if kind=="late" and late else [])
 maintenance.process_inventory=inventory
 raw=maintenance.canonical(plan); ctx=maintenance.MaintenanceContext(raw,hashlib.sha256(raw).hexdigest())
 original_publish=m._publish_verified_candidate_artifact
 def publish(*args,**kw):
  if kind=="claim-order":
   claim=kb/".install-recovery/maintenance-claims"/(ctx.operation_id+".json")
   if not claim.is_file() or json.loads(claim.read_bytes())!=ctx.claim_record():
    raise RuntimeError("claim missing before candidate publication")
  result=original_publish(*args,**kw)
  if kind=="memory-drift-after-publish":
   m._legacy_memory_database(kb).chmod(0o644)
  return result
 m._publish_verified_candidate_artifact=publish
 # Stage producer is an external fixture, validation/publication remain real.
 m.STAGER=Path(STAGER)
 return real_install(**kwargs,prepared_artifact=prepared,candidate_receipt=receipt,expected_live_state=live,maintenance_context=ctx)
m.install=install
sys.exit(m.main())
'''


@unittest.skipIf(os.name == "nt", "POSIX maintenance transaction")
class MaintenanceInstallTests(CodexPluginInstallFixture, unittest.TestCase):
    def prepare_transition(self, *, extra_legacy=False):
        fake = self.fake.read_text(encoding="utf-8")
        lines = fake.splitlines(keepends=True)
        lines.insert(1, "import sys\nif sys.argv[1:] == ['--version']:\n print('codex-cli 0.160.0'); sys.exit(0)\n")
        self.fake.write_text("".join(lines), encoding="utf-8")
        first = self.run_installer()
        self.assertEqual(first.returncode, 0, first.stderr)
        old = json.loads(first.stdout)
        if extra_legacy:
            older = self.root / "older-artifact"
            shutil.copytree(self.artifact, older)
            manifest = older / "plugins/sulde/.codex-plugin/plugin.json"
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["version"] = "0.0.7"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            load_installer()._complete_staged_native_runtime(older, platform="posix")
            shutil.copytree(older / "plugins/sulde", self.codex_home / "plugins/cache/sulde-local/sulde/0.0.7")
        plugin = self.artifact / "plugins/sulde"
        shutil.copyfile(ROOT / "integrations/codex/plugins/sulde/hooks.posix.json", plugin / "hooks/hooks.json")
        m = load_installer()
        m._complete_staged_native_runtime(self.artifact, platform="posix")
        stage = self.root / "fixture-stage.py"
        stage.write_text("import pathlib,shutil,sys\n"
            f"source=pathlib.Path({str(self.artifact)!r})\n"
            "output=pathlib.Path(sys.argv[sys.argv.index('--output')+1])\n"
            "shutil.copytree(source,output,dirs_exist_ok=True)\n", encoding="utf-8")
        shim = self.root / "maintenance-entry.py"
        shim.write_text(f"SOURCE={str(ROOT)!r}\nSTAGER={str(stage)!r}\n" + SHIM, encoding="utf-8")
        return shim, old

    def transition(self, shim, **kwargs):
        with mock.patch("tests.test_codex_plugin_install.INSTALLER", shim):
            return self.run_installer(prepare_artifact=False, **kwargs)

    def test_real_transaction_migrates_without_fresh_or_ready_claim(self):
        shim, old = self.prepare_transition(extra_legacy=True)
        result = self.transition(shim)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertFalse(value["operational_ready"])
        self.assertEqual(value["hook_entry_migration"]["lineage_origin"], "maintenance-window")
        self.assertEqual(value["hook_entry_migration"]["status"], "legacy_maintenance")
        self.assertEqual(value["previous_plugin_version"], old["plugin_version"])
        m = load_installer()
        deployment = json.loads((self.kb_home / "deployment-generation.json").read_text(encoding="utf-8"))
        import legacy_maintenance
        legacy_maintenance.verify_origin(self.kb_home.resolve(), deployment["stable_hook_entry"], deployment["maintenance_origin_transaction"])
        again = self.transition(shim)
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("already consumed", again.stderr)
        update = self.run_installer()
        self.assertEqual(update.returncode, 0, update.stderr)
        self.assertEqual(json.loads(update.stdout)["hook_entry_migration"]["status"], "stable_update")
        deployment = json.loads((self.kb_home / "deployment-generation.json").read_text(encoding="utf-8"))
        legacy_maintenance.verify_origin(self.kb_home.resolve(), deployment["stable_hook_entry"], deployment["maintenance_origin_transaction"])

    def test_live_cohort_refuses_before_transaction_or_claim(self):
        shim, _ = self.prepare_transition()
        before = (self.kb_home / "deployment-generation.json").read_bytes()
        result = self.transition(shim, extra_environment={"MAINTENANCE_CASE": "live"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cohort still alive", result.stderr)
        self.assertEqual((self.kb_home / "deployment-generation.json").read_bytes(), before)
        self.assertFalse((self.kb_home / ".install-recovery/maintenance-claims").exists())

    def test_claim_precedes_candidate_publication(self):
        shim, _ = self.prepare_transition()
        result = self.transition(shim, extra_environment={"MAINTENANCE_CASE": "claim-order"})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_partial_source_catalog_refuses_before_claim(self):
        shim, _ = self.prepare_transition()
        before = (self.kb_home / "deployment-generation.json").read_bytes()
        result = self.transition(shim, extra_environment={"MAINTENANCE_CASE": "partial-sources"})
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn("complete executable source catalog", result.stderr)
        self.assertEqual((self.kb_home / "deployment-generation.json").read_bytes(), before)
        self.assertFalse((self.kb_home / ".install-recovery/maintenance-claims").exists())

    def test_maintenance_cannot_reclassify_existing_stable_lineage(self):
        shim, _ = self.prepare_transition()
        first = self.transition(shim)
        self.assertEqual(first.returncode, 0, first.stderr)
        before = (self.kb_home / "deployment-generation.json").read_bytes()
        again = self.transition(shim, extra_environment={"MAINTENANCE_OPERATION_ID": "b" * 32})
        self.assertNotEqual(again.returncode, 0, again.stderr)
        self.assertIn("first legacy Hook migration", again.stderr)
        self.assertEqual((self.kb_home / "deployment-generation.json").read_bytes(), before)

    def test_expiry_and_old_cas_drift_refuse_without_consumption(self):
        shim, _ = self.prepare_transition()
        before = (self.kb_home / "deployment-generation.json").read_bytes()
        for case, reason in (("expired", "expired"), ("stale", "prestate drifted")):
            with self.subTest(case=case):
                result = self.transition(shim, extra_environment={"MAINTENANCE_CASE": case})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(reason, result.stderr)
                self.assertEqual((self.kb_home / "deployment-generation.json").read_bytes(), before)
                self.assertFalse((self.kb_home / ".install-recovery/maintenance-claims").exists())

    def test_late_unknown_caller_before_prune_rolls_back(self):
        shim, _ = self.prepare_transition()
        before = (self.kb_home / "deployment-generation.json").read_bytes()
        result = self.transition(shim, extra_environment={"MAINTENANCE_CASE": "late"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown Codex caller", result.stderr)
        self.assertEqual((self.kb_home / "deployment-generation.json").read_bytes(), before)
        self.assertFalse((self.kb_home / ".install-recovery/active.json").exists())

    def test_hard_exit_recovers_original_generation_from_same_journal(self):
        shim, _ = self.prepare_transition()
        old = (self.kb_home / "deployment-generation.json").read_bytes()
        result = self.transition(shim, failpoint="hook_entry.after_publish")
        self.assertEqual(result.returncode, 86, result.stderr)
        active = json.loads((self.kb_home / ".install-recovery/active.json").read_text(encoding="utf-8"))
        self.assertEqual(active["transaction_id"], "a" * 32)
        recovery = self.run_installer(recover_only=True)
        self.assertEqual(recovery.returncode, 0, recovery.stderr)
        self.assertEqual((self.kb_home / "deployment-generation.json").read_bytes(), old)
        self.assertFalse((self.kb_home / "bin/sulde-codex-hook").exists())
        self.assertTrue((self.kb_home / ".install-recovery/maintenance-claims" / ("a" * 32 + ".json")).is_file())

    def test_missing_trust_rolls_back_and_never_reports_ready(self):
        shim, _ = self.prepare_transition()
        before = (self.kb_home / "deployment-generation.json").read_bytes()
        result = self.transition(shim, hook_trust_status="untrusted")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("trusted", result.stderr)
        self.assertEqual((self.kb_home / "deployment-generation.json").read_bytes(), before)

    def test_crash_before_live_mutation_retains_recovery_and_one_use_record(self):
        shim, _ = self.prepare_transition()
        old = (self.kb_home / "deployment-generation.json").read_bytes()
        result = self.transition(shim, failpoint="transaction.after_active")
        self.assertEqual(result.returncode, 86, result.stderr)
        self.assertEqual((self.kb_home / "deployment-generation.json").read_bytes(), old)
        recovery = self.run_installer(recover_only=True)
        self.assertEqual(recovery.returncode, 0, recovery.stderr)
        self.assertEqual((self.kb_home / "deployment-generation.json").read_bytes(), old)
        self.assertTrue((self.kb_home / ".install-recovery/maintenance-claims" / ("a" * 32 + ".json")).is_file())


if __name__ == "__main__":
    unittest.main()
