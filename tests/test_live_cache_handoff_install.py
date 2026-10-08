"""Live handoff through the actual installer; provider/process facts are fixtures.

Set SULDE_TEST_CODEX_EXECUTABLE to exercise the official registry CLI as well.
No model calls, real scheduler changes, or production configuration are used.
"""
import json
import os
from pathlib import Path
import threading
import unittest

from tests.test_codex_plugin_install import CodexPluginInstallFixture, load_installer
from tests import test_legacy_maintenance_install as baseline


class LiveCacheInstallTests(CodexPluginInstallFixture, unittest.TestCase):
    transition = baseline.MaintenanceInstallTests.transition

    def setUp(self):
        self.real_cli = (os.environ.get("SULDE_TEST_CODEX_EXECUTABLE")
                         or os.environ.get("LIVE_HANDOFF_TEST_CODEX"))
        super().setUp()
        old_root, canonical_root = str(self.root), str(self.root.resolve())
        for name, value in tuple(vars(self).items()):
            if isinstance(value, Path):
                setattr(self, name, value.resolve())
        for name, value in tuple(os.environ.items()):
            if value.startswith(old_root):
                os.environ[name] = canonical_root + value[len(old_root):]
        if self.real_cli:
            cli = Path(self.real_cli)
            if not cli.is_absolute() or not cli.is_file():
                self.fail("explicit real CLI path must be an absolute executable")
            print("OFFICIAL_REGISTRY_CLI=" + str(cli), flush=True)
            # Only plugin registry operations use the real CLI. Other fake host
            # capabilities and the sealed receipt remain synthetic, as disclosed.
            source = self.fake.read_text(encoding="utf-8")
            source = source.replace('args = sys.argv[1:]', '''args = sys.argv[1:]
if args and args[0] == "plugin":
 import subprocess
 result=subprocess.run([REAL_CLI,*args],capture_output=True,text=True)
 if result.returncode == 0:
  if args[:3] == ["plugin","marketplace","add"]:
   state["marketplace"]=str(Path(args[3]).resolve())
  elif args[:3] == ["plugin","marketplace","remove"]:
   state["marketplace"]=None
  elif args[:2] == ["plugin","add"]:
   value=json.loads(result.stdout)
   state.update(installed=value["installedPath"],version=value["version"])
  state_path.write_text(json.dumps(state),encoding="utf-8")
 print(result.stdout,end=""); print(result.stderr,end="",file=sys.stderr)
 raise SystemExit(result.returncode)
'''.replace('REAL_CLI', repr(str(cli))))
            self.fake.write_text(source, encoding="utf-8")
        else:
            # Model observed official CLI cache enumeration, not its model API.
            source = self.fake.read_text(encoding="utf-8")
            source = source.replace('args = sys.argv[1:]', '''args = sys.argv[1:]
cache_root=Path(os.environ["CODEX_HOME"])/"plugins/cache/sulde-local/sulde"
cached=sorted(p for p in cache_root.glob("*") if p.is_dir() and not p.is_symlink())
if cached:
 state.update(installed=str(cached[-1]),version=cached[-1].name)
''')
            self.fake.write_text(source, encoding="utf-8")

    def prepare_live(self, *, extra_legacy=True):
        shim, old = baseline.MaintenanceInstallTests.prepare_transition(self, extra_legacy=extra_legacy)
        candidate_version = "0.9.0+live-handoff-test"
        manifest = self.artifact / "plugins/sulde/.codex-plugin/plugin.json"
        value = json.loads(manifest.read_bytes())
        value["version"] = candidate_version
        manifest.write_text(json.dumps(value), encoding="utf-8")
        load_installer()._complete_staged_native_runtime(self.artifact, platform="posix")
        source = shim.read_text(encoding="utf-8")
        source = source.replace('real_install=m.install',
            f'm.plugin_version=lambda *args: {candidate_version!r}\nreal_install=m.install')
        source = source.replace('"schema":maintenance.SCHEMA', '"schema":maintenance.LIVE_SCHEMA')
        source = source.replace('"cohort":[{**host,"pid":99}]', '"cohort":[]')
        source = source.replace('ctx=maintenance.MaintenanceContext(', 'ctx=maintenance.LiveHandoffContext(')
        shim.write_text(source, encoding="utf-8")
        return shim, old

    def observed_transition(self, shim, old, **kwargs):
        cache = self.codex_home / "plugins/cache/sulde-local/sulde" / old["plugin_version"]
        sentinel = cache / ".codex-plugin/plugin.json"
        expected = sentinel.read_bytes()
        observations, stop = [], threading.Event()
        def observe():
            while not stop.is_set():
                try:
                    if sentinel.read_bytes() != expected:
                        observations.append("changed")
                except OSError as error:
                    observations.append(type(error).__name__)
                stop.wait(.0005)
        reader = threading.Thread(target=observe)
        reader.start()
        try:
            result = self.transition(shim, **kwargs)
        finally:
            stop.set()
            reader.join()
        self.assertEqual(observations, [], result.stderr)
        return result

    def test_live_host_install_keeps_old_paths_and_seals_distinct_origin(self):
        shim, old = self.prepare_live()
        result = self.observed_transition(shim, old,
            extra_environment={"MAINTENANCE_CASE": "live"})
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["hook_entry_migration"]["lineage_origin"], "atomic-cache-handoff")
        self.assertFalse(value["operational_ready"])
        self.assertTrue((self.codex_home / "plugins/cache/sulde-local/sulde" / old["plugin_version"]).is_symlink())
        import legacy_maintenance
        deployment = json.loads((self.kb_home / "deployment-generation.json").read_bytes())
        legacy_maintenance.verify_origin(self.kb_home.resolve(), deployment["stable_hook_entry"],
            deployment["maintenance_origin_transaction"])

    def test_process_crash_after_registry_recovers_with_continuous_old_paths(self):
        shim, old = self.prepare_live()
        before = (self.kb_home / "deployment-generation.json").read_bytes()
        result = self.observed_transition(shim, old, failpoint="registry.after_add")
        self.assertEqual(result.returncode, 86, result.stderr)
        recovered = self.observed_transition(shim, old, recover_only=True)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual((self.kb_home / "deployment-generation.json").read_bytes(), before)
        self.assertFalse((self.codex_home / "plugins/cache/sulde-local/sulde" / old["plugin_version"]).is_symlink())
        self.assertFalse((self.kb_home / ".install-recovery/active.json").exists())

    def test_alias_exchange_crash_recovers_before_any_registry_prune(self):
        shim, old = self.prepare_live()
        before = (self.kb_home / "deployment-generation.json").read_bytes()
        result = self.observed_transition(shim, old, failpoint="alias.after_exchange")
        self.assertEqual(result.returncode, 86, result.stderr)
        recovered = self.observed_transition(shim, old, recover_only=True)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual((self.kb_home / "deployment-generation.json").read_bytes(), before)

    def test_preexisting_alias_and_failed_trust_restore_original_targets(self):
        shim, old = self.prepare_live()
        older = self.codex_home / "plugins/cache/sulde-local/sulde/0.0.7"
        original_target = self.codex_home / "plugins/retired/sulde-local/sulde/retained-old"
        original_target.parent.mkdir(parents=True, exist_ok=True)
        older.rename(original_target)
        older.symlink_to(original_target)
        m = load_installer()
        state = m.warm_tree_state(original_target)
        record = original_target.with_name(original_target.name + ".retirement.json")
        record.write_text(json.dumps({"schema": "sulde-retired-codex-cache-v1", "schema_version": 1,
            "alias": str(older), "target": str(original_target), "version": "0.0.7",
            "tree_sha256": state.tree_sha256}), encoding="utf-8")
        result = self.observed_transition(shim, old, hook_trust_status="untrusted")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("atomically restored old generation", result.stderr)
        self.assertTrue(older.is_symlink())
        self.assertEqual(older.resolve(), original_target)
        self.assertEqual(m.warm_tree_state(original_target).tree_sha256, state.tree_sha256)
        self.assertFalse((self.kb_home / ".install-recovery/active.json").exists())


if __name__ == "__main__":
    unittest.main()
