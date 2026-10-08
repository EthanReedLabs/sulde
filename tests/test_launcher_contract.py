from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import venv


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "kb" / "launcher_contract.py"
BOOTSTRAP = ROOT / "scripts" / "kb" / "bootstrap.sh"


def load_module():
    spec = importlib.util.spec_from_file_location("test_launcher_contract_module", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("launcher_contract.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class LauncherContractTests(unittest.TestCase):
    def test_runtime_tree_digest_rejects_git_and_python_bytecode(self) -> None:
        module = load_module()
        digest = module.runtime_tree_digest
        error = module.LauncherContractError
        with tempfile.TemporaryDirectory() as directory_name:
            runtime = Path(directory_name) / "runtime"
            runtime.mkdir()
            (runtime / "main.py").write_text("print('ok')\n", encoding="utf-8")
            self.assertEqual(len(digest(runtime)), 64)
            (runtime / ".git").mkdir()
            with self.assertRaisesRegex(error, "repository metadata"):
                digest(runtime)
            (runtime / ".git").rmdir()
            cache = runtime / "__pycache__"
            cache.mkdir()
            (cache / "main.pyc").write_bytes(b"executable-bytecode")
            with self.assertRaisesRegex(error, "Python bytecode"):
                digest(runtime)

    def setUp(self) -> None:
        self.module = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "runtime"
        self.home = Path(self.temp.name) / "kb-home"
        self.codex_home = Path(self.temp.name) / "codex-home"
        self.validate_script = (
            self.codex_home
            / "skills/.system/plugin-creator/scripts/validate_plugin.py"
        )
        self.cachebuster_script = (
            self.codex_home
            / "skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py"
        )
        for script in (self.validate_script, self.cachebuster_script):
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text(f"# fixture for {script.name}\n", encoding="utf-8")
        self.plugin = Path(self.temp.name) / "workspace" / "plugin"
        manifest = self.plugin / ".codex-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"version":"0.1.0"}\n', encoding="utf-8")
        self.environment = os.environ.copy()
        self.environment["CODEX_HOME"] = str(self.codex_home)
        self.staged_plugin = self.root.parent
        descriptor = self.staged_plugin / ".codex-plugin" / "plugin.json"
        descriptor.parent.mkdir(parents=True)
        descriptor.write_text(
            '{"name":"sulde","version":"0.1.0"}\n',
            encoding="utf-8",
        )
        for relative in self.module.CODEX_HOOK_SURFACE:
            adapter = self.staged_plugin / relative
            if adapter == descriptor:
                continue
            adapter.parent.mkdir(parents=True, exist_ok=True)
            adapter.write_text(f"# fixture for {relative}\n", encoding="utf-8")
        for spec in self.module.LAUNCHERS:
            target = self.root / spec.target_relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"# fixture for {spec.name}\n", encoding="utf-8")
        extra = self.root / "scripts" / "kb" / "shared.py"
        extra.write_text("VALUE = 1\n", encoding="utf-8")
        self.agent_runtime_script = self.root / "scripts" / "kb" / "agent-runtime.py"
        self.agent_runtime_script.write_text(
            "# digest-pinned agent runtime fixture\n", encoding="utf-8"
        )
        for relative in (
            "hooks/lib/kb_cli.py",
            "tools/kb-index/search.py",
            "tools/kb-mcp/server.py",
        ):
            dependency = self.root / relative
            dependency.parent.mkdir(parents=True, exist_ok=True)
            dependency.write_text(f"# fixture for {relative}\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def seal_generation(self) -> str:
        digest = self.module.runtime_tree_digest(self.root)
        generation = f"0.1.0:{digest}"
        descriptor = self.staged_plugin / ".codex-plugin" / "generation.json"
        descriptor.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "schema": "sulde-delivery-generation-v1",
                    "provider": "codex",
                    "plugin_version": "0.1.0",
                    "runtime_tree_sha256": digest,
                    "generation": generation,
                }
            ),
            encoding="utf-8",
        )
        return generation

    def test_install_records_and_verifies_all_six_launchers(self) -> None:
        installed = self.module.install_launchers(self.home, self.root)
        verified = self.module.verify_installation(
            self.home,
            expected_source_root=self.root,
        )

        self.assertEqual(installed["schema"], self.module.SCHEMA)
        self.assertEqual(installed["spec_version"], self.module.SPEC_VERSION)
        self.assertEqual(installed["interpreter"], str(Path(sys.executable).absolute()))
        self.assertEqual(set(installed["launchers"]), {spec.name for spec in self.module.LAUNCHERS})
        self.assertTrue(verified["healthy"], verified["issues"])
        self.assertEqual(verified["issues"], [])
        for spec in self.module.LAUNCHERS:
            launcher = self.home / "bin" / spec.name
            self.assertTrue(launcher.is_file(), spec.name)
            if os.name != "nt":
                self.assertNotEqual(launcher.stat().st_mode & 0o111, 0, spec.name)

    def test_launcher_binds_staged_generation_and_full_runtime_tree(self) -> None:
        notice = self.root / "docs" / "generation-notice.txt"
        notice.parent.mkdir(parents=True)
        notice.write_text("sealed\n", encoding="utf-8")
        digest = self.module.runtime_tree_digest(self.root)
        generation = f"0.1.0:{digest}"
        descriptor = self.staged_plugin / ".codex-plugin" / "generation.json"
        descriptor.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "schema": "sulde-delivery-generation-v1",
                    "provider": "codex",
                    "platform": "posix",
                    "plugin_version": "0.1.0",
                    "runtime_tree_sha256": digest,
                    "generation": generation,
                }
            ),
            encoding="utf-8",
        )
        installed = self.module.install_launchers(self.home, self.root)
        self.assertEqual(installed["generation"], generation)
        probe = subprocess.run(
            [
                sys.executable,
                str(self.home / "bin" / "intent-guardian"),
                "--sulde-launcher-probe",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(json.loads(probe.stdout)["generation"], generation)

        notice.write_text("drifted\n", encoding="utf-8")
        drifted = subprocess.run(
            [
                sys.executable,
                str(self.home / "bin" / "intent-guardian"),
                "--sulde-launcher-probe",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(drifted.returncode, 2)
        self.assertIn("runtime tree digest changed", drifted.stderr)

    def test_launcher_rebinds_to_bootstrapped_venv_interpreter(self) -> None:
        venv.EnvBuilder(with_pip=False).create(self.home / "venv")
        target = self.root / "scripts" / "kb" / "intent-guardian.py"
        target.write_text(
            "import json,sys\nprint(json.dumps({'prefix': sys.prefix}))\n",
            encoding="utf-8",
        )
        installed = self.module.install_launchers(self.home, self.root)
        launcher = self.home / "bin" / "intent-guardian"
        completed = subprocess.run(
            [sys.executable, str(launcher)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            Path(json.loads(completed.stdout)["prefix"]).resolve(),
            (self.home / "venv").resolve(),
        )
        self.assertEqual(
            installed["interpreter"],
            str(self.module.runtime_interpreter(self.home)),
        )
        self.assertEqual(
            Path(installed["interpreter_prefix"]).resolve(),
            (self.home / "venv").resolve(),
        )

    def test_public_launcher_can_bind_neutral_kb_dependency_venv(self) -> None:
        public_home = Path(self.temp.name) / "sulde-home"
        neutral_kb = public_home / "data" / "kb"
        venv.EnvBuilder(with_pip=False).create(neutral_kb / "venv")

        installed = self.module.install_launchers(
            public_home,
            self.root,
            interpreter_home=neutral_kb,
        )

        self.assertEqual(
            Path(installed["interpreter_prefix"]).resolve(),
            (neutral_kb / "venv").resolve(),
        )
        self.assertTrue(
            Path(installed["interpreter"]).resolve().is_relative_to(
                (neutral_kb / "venv").resolve()
            )
        )

    def test_launcher_target_cannot_create_bytecode_without_caller_environment(self) -> None:
        target = self.root / "scripts" / "kb" / "intent-guardian.py"
        target.write_text(
            (
                "import json,os,sys\n"
                "import shared\n"
                "print(json.dumps({'value': shared.VALUE, "
                "'no_bytecode': os.environ.get('PYTHONDONTWRITEBYTECODE'), "
                "'dont_write': sys.dont_write_bytecode}))\n"
            ),
            encoding="utf-8",
        )
        self.module.install_launchers(self.home, self.root)
        environment = os.environ.copy()
        environment.pop("PYTHONDONTWRITEBYTECODE", None)

        for _ in range(2):
            completed = subprocess.run(
                [sys.executable, str(self.home / "bin" / "intent-guardian")],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            output = json.loads(completed.stdout)
            self.assertEqual(output["value"], 1)
            self.assertEqual(output["no_bytecode"], "1")
            self.assertTrue(output["dont_write"])

        self.assertEqual(list(self.root.rglob("*.pyc")), [])
        self.assertEqual(list(self.root.rglob("__pycache__")), [])

    def test_stale_bytecode_artifacts_remain_an_integrity_failure(self) -> None:
        self.module.install_launchers(self.home, self.root)
        cache = self.root / "scripts" / "kb" / "__pycache__"
        cache.mkdir()
        (cache / "stale.cpython-310.pyc").write_bytes(b"stale bytecode fixture")

        verified = self.module.verify_installation(
            self.home,
            expected_source_root=self.root,
        )
        probe = subprocess.run(
            [
                sys.executable,
                str(self.home / "bin" / "intent-guardian"),
                "--sulde-launcher-probe",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        self.assertFalse(verified["healthy"])
        self.assertTrue(
            any("Python bytecode" in issue for issue in verified["issues"]),
            verified["issues"],
        )
        self.assertEqual(probe.returncode, 2)
        self.assertRegex(probe.stderr, r"runtime (?:tree )?digest changed")

    def test_generated_bytecode_repair_restores_exact_sealed_runtime(self) -> None:
        generation = self.seal_generation()
        self.module.install_launchers(self.home, self.root)
        cache = self.root / "scripts" / "kb" / "__pycache__"
        cache.mkdir()
        (cache / "shared.cpython-313.pyc").write_bytes(b"generated bytecode")

        broken = self.module.verify_installation(
            self.home,
            expected_source_root=self.root,
        )
        self.assertFalse(broken["healthy"])
        stale_launcher = subprocess.run(
            [
                sys.executable,
                str(self.home / "bin" / "intent-guardian"),
                "--sulde-launcher-probe",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(stale_launcher.returncode, 2)
        self.assertIn("--repair-generated-bytecode", stale_launcher.stderr)

        repaired = self.module.repair_generated_bytecode(self.root)
        self.assertEqual(repaired["generation"], generation)
        self.assertEqual(repaired["removed_files"], 1)
        self.assertEqual(repaired["removed_directories"], 1)
        self.assertFalse(cache.exists())
        restored = self.module.verify_installation(
            self.home,
            expected_source_root=self.root,
        )
        self.assertTrue(restored["healthy"], restored["issues"])

    def test_launcher_refresh_composes_one_matching_scheduler_seal(self) -> None:
        generation = self.seal_generation()
        self.module.install_launchers(self.home, self.root)
        runner = self.home / "bin" / "sulde-scheduled-run"
        runner.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        runner_sha256 = self.module.sha256_file(runner)
        deployment = {
            "schema": "sulde-installed-deployment-generation-v1",
            "schema_version": 1,
            "status": "generation_verified",
            "operational_ready": True,
            "provider": "codex",
            "platform": "posix",
            "runtime_root": str(self.root.resolve()),
            "runtime_tree_sha256": generation.split(":", 1)[1],
            "generation": generation,
            "scheduler_runner": str(runner.resolve()),
            "scheduler_runner_sha256": runner_sha256,
        }
        owner = {
            "schema_version": 2,
            "status": "active",
            "installation_status": "generation_verified",
            "operational_ready": True,
            "provider": "codex",
            "source_root": str(self.root.resolve()),
            "runtime_root": str(self.root.resolve()),
            "runtime_tree_sha256": generation.split(":", 1)[1],
            "generation": generation,
            "scheduler_runner_sha256": runner_sha256,
            "scheduler": "launchd",
        }
        for path, payload in (
            (self.home / "deployment-generation.json", deployment),
            (self.home / "runtime-owner.json", owner),
        ):
            payload["scheduler_activation_id"] = "matching-activation"
            path.write_text(json.dumps(payload), encoding="utf-8")
            if os.name != "nt":
                path.chmod(0o600)

        refreshed = self.module.install_launchers(self.home, self.root)

        self.assertEqual(refreshed["schema_version"], 1)
        self.assertEqual(refreshed["provider"], "codex")
        self.assertEqual(refreshed["platform"], "posix")
        self.assertEqual(refreshed["scheduler_runner"], str(runner.resolve()))
        self.assertEqual(refreshed["scheduler_runner_sha256"], runner_sha256)
        self.assertEqual(
            json.loads(
                (self.home / "bin" / ".sulde-launchers.json").read_text(
                    encoding="utf-8"
                )
            ),
            refreshed,
        )

        runner.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
        drifted = self.module.install_launchers(self.home, self.root)
        self.assertNotIn("scheduler_runner", drifted)
        self.assertNotIn("scheduler_runner_sha256", drifted)

    def test_launcher_refresh_drops_a_mismatched_scheduler_seal(self) -> None:
        generation = self.seal_generation()
        self.module.install_launchers(self.home, self.root)
        runner = self.home / "bin" / "sulde-scheduled-run"
        runner.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        runner_sha256 = self.module.sha256_file(runner)
        deployment = {
            "schema": "sulde-installed-deployment-generation-v1",
            "schema_version": 1,
            "status": "installed_live_unverified",
            "operational_ready": False,
            "provider": "codex",
            "platform": "posix",
            "runtime_root": str(self.root.resolve()),
            "runtime_tree_sha256": generation.split(":", 1)[1],
            "generation": f"stale:{'0' * 64}",
            "scheduler_runner": str(runner.resolve()),
            "scheduler_runner_sha256": runner_sha256,
        }
        owner = {
            "schema_version": 2,
            "status": "active",
            "installation_status": "installed_degraded",
            "operational_ready": False,
            "provider": "codex",
            "source_root": str(self.root.resolve()),
            "runtime_root": str(self.root.resolve()),
            "runtime_tree_sha256": generation.split(":", 1)[1],
            "generation": generation,
            "scheduler_runner_sha256": runner_sha256,
            "scheduler": "launchd",
        }
        for path, payload in (
            (self.home / "deployment-generation.json", deployment),
            (self.home / "runtime-owner.json", owner),
        ):
            path.write_text(json.dumps(payload), encoding="utf-8")
            if os.name != "nt":
                path.chmod(0o600)

        refreshed = self.module.install_launchers(self.home, self.root)

        self.assertNotIn("scheduler_runner", refreshed)
        self.assertNotIn("scheduler_runner_sha256", refreshed)
        self.assertNotIn("provider", refreshed)
        self.assertNotIn("platform", refreshed)

    def test_generated_bytecode_repair_refuses_non_bytecode_drift(self) -> None:
        self.seal_generation()
        cache = self.root / "scripts" / "kb" / "__pycache__"
        cache.mkdir()
        bytecode = cache / "shared.cpython-313.pyc"
        bytecode.write_bytes(b"generated bytecode")
        (self.root / "scripts" / "kb" / "shared.py").write_text(
            "VALUE = 'drifted'\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            self.module.LauncherContractError,
            "non-bytecode drift",
        ):
            self.module.repair_generated_bytecode(self.root)
        self.assertTrue(bytecode.exists())

    @unittest.skipIf(os.name == "nt", "requires a POSIX shell")
    def test_bytecode_repair_flag_requires_launchers_only(self) -> None:
        bash = shutil.which("bash")
        self.assertIsNotNone(bash)
        environment = os.environ.copy()
        environment["SULDE_KB_HOME"] = str(self.home)
        completed = subprocess.run(
            [
                str(bash),
                str(BOOTSTRAP),
                "--repair-generated-bytecode",
                "--host",
                "codex",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("requires --launchers-only", completed.stderr)

    @unittest.skipIf(os.name == "nt", "POSIX venv interpreter removal semantics")
    def test_missing_pinned_venv_interpreter_is_not_healthy(self) -> None:
        venv.EnvBuilder(with_pip=False).create(self.home / "venv")
        self.module.install_launchers(self.home, self.root)
        interpreter = self.module.runtime_interpreter(self.home)
        interpreter.unlink()

        verified = self.module.verify_installation(
            self.home,
            expected_source_root=self.root,
        )
        probe = subprocess.run(
            [sys.executable, str(self.home / "bin" / "intent-guardian"), "--sulde-launcher-probe"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        self.assertFalse(verified["healthy"])
        self.assertIn("launcher runtime interpreter is missing", verified["issues"])
        self.assertEqual(probe.returncode, 2)
        self.assertIn("runtime interpreter missing", probe.stderr)

    @unittest.skipIf(os.name == "nt", "requires a POSIX shell")
    def test_bootstrap_declares_complete_hook_dependency_closure(self) -> None:
        bash = shutil.which("bash")
        self.assertIsNotNone(bash)
        environment = os.environ.copy()
        environment["SULDE_KB_HOME"] = str(self.home)
        completed = subprocess.run(
            [str(bash), str(BOOTSTRAP), "--dry-run", "--host", "codex"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("pyyaml", completed.stdout.lower())

    def test_codex_hook_bridge_pins_current_adapter_surface(self) -> None:
        installed = self.module.install_launchers(self.home, self.root)
        expected = self.module.codex_hook_surface_digest(self.root)
        self.assertEqual(installed["codex_hook_surface_sha256"], expected)
        self.assertEqual(
            set(installed["codex_hook_file_sha256"]),
            set(self.module.CODEX_HOOK_SURFACE),
        )
        adapter = self.module.resolve_codex_hook_adapter(
            self.home,
            self.root,
            "pre-tool-use",
        )
        self.assertEqual(
            adapter,
            (self.staged_plugin / "scripts" / "pre-tool-use.py").resolve(),
        )

        adapter.write_text("# drifted adapter\n", encoding="utf-8")
        with self.assertRaisesRegex(
            self.module.LauncherContractError,
            "event surface changed",
        ):
            self.module.resolve_codex_hook_adapter(
                self.home,
                self.root,
                "pre-tool-use",
            )
        verified = self.module.verify_installation(
            self.home,
            expected_source_root=self.root,
        )
        self.assertFalse(verified["healthy"])
        self.assertTrue(
            any("hook surface digest" in issue for issue in verified["issues"]),
            verified["issues"],
        )

    def test_codex_hook_bridge_hashes_only_the_selected_event_surface(self) -> None:
        self.module.install_launchers(self.home, self.root)
        unrelated = self.staged_plugin / "scripts" / "post-tool-use.py"
        original = unrelated.read_text(encoding="utf-8")
        unrelated.write_text(original + "\n# unrelated drift\n", encoding="utf-8")

        adapter = self.module.resolve_codex_hook_adapter(
            self.home,
            self.root,
            "pre-tool-use",
        )
        self.assertEqual(adapter.name, "pre-tool-use.py")
        verified = self.module.verify_installation(
            self.home,
            expected_source_root=self.root,
        )
        self.assertFalse(verified["healthy"])
        self.assertTrue(
            any("hook surface digest" in issue for issue in verified["issues"]),
            verified["issues"],
        )

    def test_neutral_kb_hook_uses_product_launcher_manifest(self) -> None:
        neutral_home = Path(self.temp.name) / ".sulde"
        neutral_kb = neutral_home / "data" / "kb"
        stale_bin = neutral_kb / "bin"
        stale_bin.mkdir(parents=True)
        (stale_bin / self.module.MANIFEST_NAME).write_text(
            json.dumps(
                {
                    "schema": self.module.SCHEMA,
                    "spec_version": self.module.SPEC_VERSION,
                    "source_root": "/retired/old/runtime",
                }
            ),
            encoding="utf-8",
        )

        with mock.patch.dict(
            os.environ,
            {"SULDE_HOME": str(neutral_home)},
            clear=False,
        ):
            self.module.install_launchers(
                neutral_home,
                self.root,
                environment=self.environment,
            )
            adapter = self.module.resolve_codex_hook_adapter(
                neutral_kb,
                self.root,
                "pre-tool-use",
            )
            verified = self.module.verify_installation(
                neutral_kb,
                expected_source_root=self.root,
                environment=self.environment,
            )

        self.assertEqual(
            adapter,
            (self.staged_plugin / "scripts" / "pre-tool-use.py").resolve(),
        )
        self.assertTrue(verified["healthy"], verified["issues"])
        self.assertEqual(
            Path(verified["manifest"]).resolve(),
            (neutral_home / "bin" / self.module.MANIFEST_NAME).resolve(),
        )

    def test_changed_runtime_or_launcher_is_stale(self) -> None:
        self.module.install_launchers(self.home, self.root)
        (self.root / "scripts" / "kb" / "shared.py").write_text(
            "VALUE = 2\n", encoding="utf-8"
        )
        runtime_changed = self.module.verify_installation(
            self.home,
            expected_source_root=self.root,
        )
        self.assertFalse(runtime_changed["healthy"])
        self.assertTrue(
            any("runtime digest" in issue for issue in runtime_changed["issues"]),
            runtime_changed["issues"],
        )

        self.module.install_launchers(self.home, self.root)
        launcher = self.home / "bin" / "intent-guardian"
        launcher.write_text(launcher.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
        launcher_changed = self.module.verify_installation(
            self.home,
            expected_source_root=self.root,
        )
        self.assertFalse(launcher_changed["healthy"])
        self.assertIn(
            "launcher file digest mismatch: intent-guardian",
            launcher_changed["issues"],
        )

    def test_command_effect_snapshot_pins_interpreter_script_and_argv(self) -> None:
        installed = self.module.install_launchers(
            self.home,
            self.root,
            environment=self.environment,
        )
        verified = self.module.verify_installation(
            self.home,
            expected_source_root=self.root,
            environment=self.environment,
        )

        self.assertTrue(verified["healthy"], verified["issues"])
        self.assertEqual(verified["command_effects"]["command_count"], 3)
        self.assertEqual(
            installed["command_effects_sha256"],
            self.module.sha256_file(
                self.home / "bin" / self.module.COMMAND_EFFECT_MANIFEST_NAME
            ),
        )
        if os.name != "nt":
            self.assertEqual(
                (self.home / "bin" / self.module.COMMAND_EFFECT_MANIFEST_NAME).stat().st_mode
                & 0o777,
                0o600,
            )

        read = self.module.classify_trusted_script_command(
            [sys.executable, str(self.validate_script), str(self.plugin)],
            kb_home=self.home,
            cwd=self.plugin.parent,
            environment=self.environment,
        )
        self.assertIsNotNone(read)
        self.assertEqual(read["effect"], "read")
        self.assertNotIn("target", read)

        local_write = self.module.classify_trusted_script_command(
            [
                sys.executable,
                str(self.cachebuster_script),
                str(self.plugin),
                "--cachebuster",
                "verified-1",
            ],
            kb_home=self.home,
            cwd=self.plugin.parent,
            environment=self.environment,
        )
        self.assertIsNotNone(local_write)
        self.assertEqual(local_write["effect"], "local_write")
        self.assertEqual(
            Path(local_write["target"]),
            (self.plugin / ".codex-plugin" / "plugin.json").resolve(),
        )

    def test_agent_runtime_git_lifecycle_argv_is_digest_pinned_and_path_exact(self) -> None:
        self.module.install_launchers(
            self.home,
            self.root,
            environment=self.environment,
        )
        repository = Path(self.temp.name) / "repository"
        worktrees = repository / ".worktrees"
        task = worktrees / "task-one"
        dev = worktrees / "dev"
        worktrees.mkdir(parents=True)
        task.mkdir()
        dev.mkdir()
        oid = "a" * 40

        provision = self.module.classify_trusted_script_command(
            [
                sys.executable,
                str(self.agent_runtime_script),
                "provision",
                str(repository),
                str(worktrees / "task-two"),
                "--branch",
                "fix/task-two",
                "--base-ref",
                "dev",
                "--base-commit",
                oid,
            ],
            kb_home=self.home,
            cwd=repository,
            environment=self.environment,
        )
        self.assertIsNotNone(provision)
        self.assertEqual(provision["effect"], "local_write")
        self.assertEqual(
            provision["targets"],
            [str((worktrees / "task-two").resolve(strict=False))],
        )

        commit = self.module.classify_trusted_script_command(
            [
                sys.executable,
                str(self.agent_runtime_script),
                "commit",
                str(task),
                "--expected-head",
                oid,
                "--message",
                "verified task",
                "--path",
                "scripts/one.py",
                "--path",
                "tests/test_one.py",
            ],
            kb_home=self.home,
            cwd=repository,
            environment=self.environment,
        )
        self.assertIsNotNone(commit)
        self.assertEqual(
            commit["targets"],
            sorted(
                [
                    str((task / "scripts/one.py").resolve(strict=False)),
                    str((task / "tests/test_one.py").resolve(strict=False)),
                ]
            ),
        )

        merge = self.module.classify_trusted_script_command(
            [
                sys.executable,
                str(self.agent_runtime_script),
                "merge",
                str(dev),
                "--target-branch",
                "dev",
                "--source-ref",
                "fix/task-one",
                "--expected-target-head",
                oid,
                "--expected-source-head",
                "b" * 40,
                "--path",
                "scripts/one.py",
            ],
            kb_home=self.home,
            cwd=repository,
            environment=self.environment,
        )
        self.assertIsNotNone(merge)
        self.assertEqual(
            merge["targets"],
            [str((dev / "scripts/one.py").resolve(strict=False))],
        )

        unsafe = (
            [
                sys.executable,
                str(self.agent_runtime_script),
                "provision",
                str(repository),
                str(Path(self.temp.name) / "outside"),
                "--branch",
                "fix/outside",
                "--base-ref",
                "dev",
                "--base-commit",
                oid,
            ],
            [
                sys.executable,
                str(self.agent_runtime_script),
                "commit",
                str(task),
                "--expected-head",
                oid,
                "--message",
                "bad scope",
                "--path",
                "../escape.py",
            ],
            [
                sys.executable,
                str(self.agent_runtime_script),
                "merge",
                str(dev),
                "--target-branch",
                "main",
                "--source-ref",
                "fix/task-one",
                "--expected-target-head",
                oid,
                "--expected-source-head",
                "b" * 40,
                "--path",
                "scripts/one.py",
            ],
        )
        for tokens in unsafe:
            with self.subTest(tokens=tokens):
                self.assertIsNone(
                    self.module.classify_trusted_script_command(
                        tokens,
                        kb_home=self.home,
                        cwd=repository,
                        environment=self.environment,
                    )
                )

    def test_command_effect_snapshot_fails_closed_on_digest_path_or_argv_drift(self) -> None:
        self.module.install_launchers(
            self.home,
            self.root,
            environment=self.environment,
        )
        duplicate = Path(self.temp.name) / "other" / self.validate_script.name
        duplicate.parent.mkdir()
        duplicate.write_bytes(self.validate_script.read_bytes())

        cases = (
            [sys.executable, str(duplicate), str(self.plugin)],
            [sys.executable, str(self.validate_script), str(self.plugin), "--extra"],
            [
                sys.executable,
                str(self.cachebuster_script),
                str(self.plugin),
                "--cachebuster",
                "bad/value",
            ],
            ["/bin/echo", str(self.validate_script), str(self.plugin)],
        )
        for tokens in cases:
            self.assertIsNone(
                self.module.classify_trusted_script_command(
                    list(tokens),
                    kb_home=self.home,
                    cwd=self.plugin.parent,
                    environment=self.environment,
                ),
                tokens,
            )

        self.validate_script.write_text("# changed after install\n", encoding="utf-8")
        self.assertIsNone(
            self.module.classify_trusted_script_command(
                [sys.executable, str(self.validate_script), str(self.plugin)],
                kb_home=self.home,
                cwd=self.plugin.parent,
                environment=self.environment,
            )
        )

    def test_command_effect_snapshot_fails_closed_when_manifest_is_tampered(self) -> None:
        self.module.install_launchers(
            self.home,
            self.root,
            environment=self.environment,
        )
        snapshot = self.home / "bin" / self.module.COMMAND_EFFECT_MANIFEST_NAME
        payload = json.loads(snapshot.read_text(encoding="utf-8"))
        payload["commands"][0]["effect"] = "local_write"
        snapshot.write_text(json.dumps(payload), encoding="utf-8")
        if os.name != "nt":
            snapshot.chmod(0o600)

        classified = self.module.classify_trusted_script_command(
            [sys.executable, str(self.validate_script), str(self.plugin)],
            kb_home=self.home,
            cwd=self.plugin.parent,
            environment=self.environment,
        )
        verified = self.module.verify_installation(
            self.home,
            expected_source_root=self.root,
            environment=self.environment,
        )
        self.assertIsNone(classified)
        self.assertFalse(verified["healthy"])
        self.assertTrue(
            any("snapshot digest" in issue for issue in verified["issues"]),
            verified["issues"],
        )

    @unittest.skipIf(os.name == "nt", "POSIX permission and symlink contract")
    def test_command_effect_snapshot_rejects_workspace_location_wide_mode_and_symlink_target(self) -> None:
        self.module.install_launchers(
            self.home,
            self.root,
            environment=self.environment,
        )
        validator_tokens = [sys.executable, str(self.validate_script), str(self.plugin)]
        self.assertIsNone(
            self.module.classify_trusted_script_command(
                validator_tokens,
                kb_home=self.home,
                cwd=Path(self.temp.name),
                environment=self.environment,
            )
        )

        snapshot = self.home / "bin" / self.module.COMMAND_EFFECT_MANIFEST_NAME
        snapshot.chmod(0o644)
        self.assertIsNone(
            self.module.classify_trusted_script_command(
                validator_tokens,
                kb_home=self.home,
                cwd=self.plugin.parent,
                environment=self.environment,
            )
        )
        snapshot.chmod(0o600)

        manifest = self.plugin / ".codex-plugin" / "plugin.json"
        outside = Path(self.temp.name) / "outside-plugin.json"
        outside.write_text(manifest.read_text(encoding="utf-8"), encoding="utf-8")
        manifest.unlink()
        manifest.symlink_to(outside)
        self.assertIsNone(
            self.module.classify_trusted_script_command(
                [sys.executable, str(self.cachebuster_script), str(self.plugin)],
                kb_home=self.home,
                cwd=self.plugin.parent,
                environment=self.environment,
            )
        )

    def test_generated_launcher_fails_closed_after_runtime_change(self) -> None:
        self.module.install_launchers(self.home, self.root)
        launcher = self.home / "bin" / "intent-guardian"
        healthy = subprocess.run(
            [sys.executable, str(launcher), "--sulde-launcher-probe"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(healthy.returncode, 0, healthy.stderr)
        self.assertTrue(json.loads(healthy.stdout)["healthy"])

        (self.root / "scripts" / "kb" / "shared.py").write_text(
            "VALUE = 3\n", encoding="utf-8"
        )
        stale = subprocess.run(
            [sys.executable, str(launcher), "--sulde-launcher-probe"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(stale.returncode, 2)
        self.assertIn("runtime digest changed", stale.stderr)
        self.assertIn("--launchers-only", stale.stderr)
        self.assertNotIn("--repair-generated-bytecode", stale.stderr)

    def test_generated_launcher_matches_nested_runtime_digest_order(self) -> None:
        nested = (
            self.root
            / "scripts"
            / "kb"
            / "intent_guardian_parts"
            / "policy.py"
        )
        nested.parent.mkdir(parents=True)
        nested.write_text("POLICY = 'sealed'\n", encoding="utf-8")

        self.module.install_launchers(
            self.home,
            self.root,
            environment=self.environment,
        )
        installed = self.module.verify_installation(
            self.home,
            expected_source_root=self.root,
            environment=self.environment,
        )
        self.assertTrue(installed["healthy"], installed["issues"])

        launcher = self.home / "bin" / "intent-guardian"
        healthy = subprocess.run(
            [sys.executable, str(launcher), "--sulde-launcher-probe"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self.environment,
            check=False,
        )
        self.assertEqual(healthy.returncode, 0, healthy.stderr)
        self.assertTrue(json.loads(healthy.stdout)["healthy"])

        nested.write_text("POLICY = 'drifted'\n", encoding="utf-8")
        stale = subprocess.run(
            [sys.executable, str(launcher), "--sulde-launcher-probe"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self.environment,
            check=False,
        )
        self.assertEqual(stale.returncode, 2)
        self.assertIn("runtime digest changed", stale.stderr)

    def test_statusline_launcher_preserves_degraded_output_from_nonzero_probe(self) -> None:
        target = self.root / "scripts" / "kb" / "sulde-statusline.py"
        target.write_text(
            "import sys\nprint('sulde 🔴(contract paused)')\nraise SystemExit(1)\n",
            encoding="utf-8",
        )
        self.module.install_launchers(self.home, self.root)
        completed = subprocess.run(
            [sys.executable, str(self.home / "bin" / "sulde-statusline.py")],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "sulde 🔴(contract paused)")

    def test_transitive_mcp_server_change_marks_runtime_stale(self) -> None:
        self.module.install_launchers(self.home, self.root)
        (self.root / "tools" / "kb-mcp" / "server.py").write_text(
            "# damaged server\n", encoding="utf-8"
        )

        verified = self.module.verify_installation(
            self.home,
            expected_source_root=self.root,
        )
        self.assertFalse(verified["healthy"])
        self.assertTrue(
            any("runtime digest" in issue for issue in verified["issues"]),
            verified["issues"],
        )

        launcher = self.home / "bin" / "sulde-kb-mcp"
        probe = subprocess.run(
            [sys.executable, str(launcher), "--sulde-launcher-probe"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(probe.returncode, 2)
        self.assertIn("runtime digest changed", probe.stderr)

    @unittest.skipIf(os.name == "nt", "requires a POSIX shell")
    def test_bootstrap_launchers_only_has_no_venv_or_index_side_effect(self) -> None:
        bash = shutil.which("bash")
        self.assertIsNotNone(bash)
        environment = os.environ.copy()
        environment["SULDE_KB_HOME"] = str(self.home)
        completed = subprocess.run(
            [str(bash), str(BOOTSTRAP), "--launchers-only", "--host", "codex"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("SULDE LAUNCHERS: READY", completed.stdout)
        self.assertFalse((self.home / "venv").exists())
        self.assertFalse((self.home / "kb.db").exists())
        self.assertFalse((self.home / "memory.db").exists())
        verified = self.module.verify_installation(
            self.home,
            expected_source_root=ROOT,
        )
        self.assertTrue(verified["healthy"], verified["issues"])


if __name__ == "__main__":
    unittest.main()
