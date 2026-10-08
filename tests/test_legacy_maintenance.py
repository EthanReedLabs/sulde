"""Bounded maintenance inputs. Fake OS observations are not human authority."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/release"))
import legacy_maintenance as maintenance
import install_codex_plugin as installer
import candidate_codex_plugin as candidate
from independent_maintenance_host import FixedOperation


def fixture_plan(root):
    host = {"pid": 100, "started": "Tue Oct 6 12:00:00 2026", "executable": "/fixture/codex"}
    return {"schema": maintenance.SCHEMA, "operation_id": "a" * 32,
            "created_at": time.time() - 1, "expires_at": time.time() + 120,
            "kb_home": str(root / "kb"), "codex_home": str(root / "codex"),
            "codex": str(root / "codex-exe"), "candidate_home": str(root / "candidate"),
            "candidate_id": "frozen-one", "receipt_sha256": "b" * 64,
            "artifact_tree_sha256": "c" * 64,
            "old_state": {"plugin": {"path": str(root / "old")}},
            "cache_bindings": [{"path": str(root / "old"), "sha256": "d" * 64}],
            "cohort": [{**host, "pid": 99}], "maintenance_host": host,
            "source_files": {str(root / "worker.py"): "f" * 64},
            "user_home": str(root / "home"), "launcher_home": str(root / "kb"),
            "launchagents_dir": str(root / "launchagents")}


def context(plan):
    raw = maintenance.canonical(plan)
    return maintenance.MaintenanceContext(raw, hashlib.sha256(raw).hexdigest())


@unittest.skipIf(os.name == "nt", "POSIX maintenance boundary")
class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.plan = fixture_plan(self.root)

    def rows(self):
        return [{**self.plan["maintenance_host"], "parent_pid": 1},
                {"pid": os.getpid(), "parent_pid": 100, "started": "now", "executable": "/fixture/python"}]

    def test_normal_cohort_exited_and_owned_worker(self):
        context(self.plan).check_processes(self.rows())

    def test_live_reused_unknown_and_unowned_processes_refuse(self):
        cases = [self.rows() + [{**self.plan["cohort"][0], "parent_pid": 1}],
                 self.rows() + [{**self.plan["cohort"][0], "parent_pid": 1, "started": "reused"}],
                 self.rows() + [{**self.plan["maintenance_host"], "parent_pid": 1, "pid": 102}],
                 [self.rows()[0], {**self.rows()[1], "parent_pid": 1}],
                 [self.rows()[1]], self.rows() + [self.rows()[1]]]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(maintenance.MaintenanceError):
                context(self.plan).check_processes(rows)

    def test_digest_and_schema_fail_closed(self):
        for update in ({"force": True}, {"expires_at": float("nan")},
                       {"operation_id": "../../escape"}, {"candidate_id": "../other"},
                       {"expires_at": time.time() + 7200}, {"cohort": [self.plan["maintenance_host"]]}):
            with self.subTest(update=update), self.assertRaises(maintenance.MaintenanceError):
                context({**self.plan, **update})
        with self.assertRaisesRegex(maintenance.MaintenanceError, "digest"):
            maintenance.MaintenanceContext(maintenance.canonical(self.plan), "0" * 64)

    def test_claim_is_durable_once_and_preserved(self):
        value = context(self.plan)
        kb = self.root / "kb"
        value.claim(kb)
        claim = kb / ".install-recovery/maintenance-claims" / (value.operation_id + ".json")
        before = claim.read_bytes()
        with self.assertRaises(FileExistsError):
            value.claim(kb)
        self.assertEqual(before, claim.read_bytes())
        self.assertEqual(json.loads(before), value.claim_record())

    def test_secure_read_rejects_symlink_and_unsafe_permissions(self):
        file = self.root / "file"
        file.write_text("original", encoding="utf-8")
        alias = self.root / "alias"
        alias.symlink_to(file)
        with self.assertRaises(maintenance.MaintenanceError):
            maintenance.secure_bytes(alias)
        file.chmod(0o666)
        with self.assertRaises(maintenance.MaintenanceError):
            maintenance.secure_bytes(file)
        file.chmod(0o600)
        self.assertEqual(maintenance.secure_bytes(file), b"original")

    def test_plan_access_does_not_mutate_bound_input(self):
        value = context(self.plan)
        value.plan["operation_id"] = "changed"
        self.assertEqual(value.operation_id, "a" * 32)

    def test_consumer_requires_exact_complete_source_catalog(self):
        sources = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in maintenance.source_paths(ROOT)}
        self.assertIn(str(ROOT / "hooks/lib/kb_cli.py"), sources)
        self.assertEqual({path for path in sources if Path(path).parent == ROOT / "hooks/lib"},
                         {str(ROOT / "hooks/lib/kb_cli.py")})
        context({**self.plan, "source_files": sources}).check_sources(ROOT)
        missing = dict(sources)
        missing.pop(next(iter(missing)))
        extra = {**sources, str(self.root / "extra.py"): "e" * 64}
        replaced = {**missing, str(self.root / "replacement.py"): "e" * 64}
        for value in (missing, extra, replaced):
            with self.subTest(keys=len(value)), self.assertRaisesRegex(
                    maintenance.MaintenanceError, "complete executable source catalog"):
                context({**self.plan, "source_files": value}).check_sources(ROOT)

    def test_only_active_legacy_without_stable_lineage_is_migratable(self):
        kb = self.root / "kb"
        kb.mkdir()
        deployment = kb / installer.DEPLOYMENT_GENERATION_NAME
        deployment.write_text("{}", encoding="utf-8")
        plugin = self.root / "installed"
        (plugin / "hooks").mkdir(parents=True)
        hook = plugin / "hooks/hooks.json"
        hook.write_text(json.dumps({"hooks": {"PreToolUse": "${PLUGIN_ROOT}/old"}}), encoding="utf-8")
        # Both actual CLI registry protocols expose the source plugin path;
        # installed Hook bytes live separately at the versioned cache path.
        expected = {"version": "old", "path": str(self.root / "marketplace/plugins/sulde")}
        with mock.patch.object(installer, "_stable_registry_installation", return_value=("old", self.root / "marketplace/plugins/sulde")), \
                mock.patch.object(installer, "_canonical_cache_path", return_value=plugin):
            maintenance.require_legacy_prestate(kb, "fixture", None, expected_plugin=expected)
            for origin in ("fresh-cache-root", "maintenance-window"):
                deployment.write_text(json.dumps({"stable_hook_entry": {"lineage_origin": origin}}), encoding="utf-8")
                with self.assertRaisesRegex(maintenance.MaintenanceError, "first legacy Hook migration"):
                    maintenance.require_legacy_prestate(kb, "fixture", None, expected_plugin=expected)
            deployment.write_text("{}", encoding="utf-8")
            for document in ("{}", (ROOT / "integrations/codex/plugins/sulde/hooks.posix.json").read_text(encoding="utf-8")):
                hook.write_text(document, encoding="utf-8")
                with self.assertRaisesRegex(maintenance.MaintenanceError, "proven legacy active registry"):
                    maintenance.require_legacy_prestate(kb, "fixture", None, expected_plugin=expected)

    def test_expired_or_changed_target_rejects_before_process_or_cas(self):
        for plan in ({**self.plan, "created_at": time.time() - 200, "expires_at": time.time() - 1}, self.plan):
            with mock.patch.object(maintenance, "process_inventory") as processes:
                with self.assertRaises(maintenance.MaintenanceError):
                    context(plan).check(candidate=self.root, kb_home=self.root / "wrong",
                                        codex=self.plan["codex"], runner=installer.run_command)
                processes.assert_not_called()

    def test_worker_target_environment_is_explicit_and_drops_parent_authority(self):
        value = context(self.plan)
        with mock.patch.dict(os.environ, {"SULDE_INTENT_CONTRACT": "sentinel", "CODEX_THREAD_ID": "old",
                                         "SULDE_LAUNCHER_HOME": "/wrong", "OPENAI_API_KEY": "secret"}), \
                mock.patch.object(candidate, "promote") as promote, \
                mock.patch.object(maintenance.MaintenanceContext, "wait_for_cohort"):
            observed = {}
            def run(**kwargs):
                observed.update(os.environ)
                return {"operational_ready": False}
            promote.side_effect = run
            self.assertFalse(candidate.maintenance_promote(value)["operational_ready"])
            self.assertEqual(promote.call_args.kwargs["_maintenance_context"].digest, value.digest)
        for key in ("SULDE_INTENT_CONTRACT", "CODEX_THREAD_ID", "OPENAI_API_KEY"):
            self.assertNotIn(key, observed)
        self.assertEqual(observed["SULDE_LAUNCHER_HOME"], self.plan["launcher_home"])
        self.assertEqual(observed["SULDE_LAUNCHAGENTS_DIR"], self.plan["launchagents_dir"])

    def test_frozen_bundle_runs_held_source_and_rejects_byte_drift(self):
        # Minimal local module graph, no installer or production side effects.
        release = self.root / "scripts/release"
        release.mkdir(parents=True)
        module = release / "legacy_maintenance.py"
        module.write_text("import json\nclass MaintenanceContext:\n def __init__(self,raw,digest): self.plan=json.loads(raw)\n"
            "def operation_context(raw,digest): return MaintenanceContext(raw,digest)\n"
            "def execute_operation(context):\n from candidate_codex_plugin import maintenance_promote\n return maintenance_promote(context)\n",
            encoding="utf-8")
        target = release / "candidate_codex_plugin.py"
        target.write_text("def maintenance_promote(context): return {'held': True}\n", encoding="utf-8")
        helper = self.root / "hooks/lib/kb_cli.py"
        helper.parent.mkdir(parents=True)
        helper.write_text("# Minimal catalog fixture; real helper import covered by reversal entry.\n", encoding="utf-8")
        self.plan["source_files"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (module, target, helper)}
        plan_file = self.root / "plan.json"
        plan_file.write_bytes(maintenance.canonical(self.plan))
        plan_file.chmod(0o600)
        bundle = self.root / "bundle.json"
        prepared = maintenance.prepare_bundle(plan_file, hashlib.sha256(plan_file.read_bytes()).hexdigest(), bundle, root=self.root)
        target.write_text("raise RuntimeError('modified file must never execute')\n", encoding="utf-8")
        argv = [sys.executable, "-B", "-I", "-c", maintenance.BOOTSTRAP, str(bundle), prepared["bundle_sha256"]]
        normal = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        self.assertEqual(normal.returncode, 0, normal.stderr)
        self.assertEqual(json.loads(normal.stdout), {"held": True})
        bundle.write_bytes(bundle.read_bytes() + b" ")
        refused = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("bundle digest differs", refused.stderr)

    def test_fixed_provider_prefetch_never_counts_as_completion(self):
        operation = FixedOperation("fixed-command", "/fixture", "one operation")
        first = operation.response({"input": []})
        self.assertEqual(json.loads(first["arguments"])["cmd"], "fixed-command")
        operation.response({"input": []})
        self.assertFalse(operation.done)
        operation.response({"input": [{"type": "function_call_output", "call_id": "foreign", "output": "exit 0"}]})
        self.assertFalse(operation.done)
        running = operation.response({"input": [{"type": "function_call_output", "call_id": first["call_id"],
                                                   "output": "Process running with session ID 123"}]})
        self.assertEqual(json.loads(running["arguments"])["session_id"], 123)
        self.assertEqual(running["name"], "write_stdin")
        self.assertFalse(operation.done)
        operation.response({"input": [{"type": "function_call_output", "call_id": running["call_id"],
                                        "output": "Process exited with code 0"}]})
        self.assertTrue(operation.done)

    def test_fixed_provider_rejects_process_session_switch(self):
        operation = FixedOperation("fixed", "/fixture", "one")
        first = operation.response({"input": []})
        poll = operation.response({"input": [{"type": "function_call_output", "call_id": first["call_id"],
                                            "output": "Process running with session ID 12"}]})
        with self.assertRaises(maintenance.MaintenanceError):
            operation.response({"input": [{"type": "function_call_output", "call_id": poll["call_id"],
                                           "output": "Process running with session ID 99"}]})


if __name__ == "__main__":
    unittest.main()
