from __future__ import annotations

import json
import os
import plistlib
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts" / "kb"
COGNITIVE_ORGANS = (
    "heartbeat.py",
    "auto-distill.py",
    "auto-sediment.py",
    "governance-report.py",
    "golden-expand.py",
    "graph-audit.py",
    "kb-dedup.py",
    "self-repair.py",
)


class DualRuntimeContractTests(unittest.TestCase):
    def test_windows_descriptor_envelopes_reject_wrong_contract_before_digests(self) -> None:
        module = runpy.run_path(str(SCRIPT_DIR / "windows-task.py"))
        validate = module["validate_windows_documents"]
        digest = "a" * 64
        generation = f"1.2.3+fixture:{digest}"
        runtime = {
            "schema": "sulde-delivery-generation-v1",
            "schema_version": 1,
            "provider": "codex",
            "platform": "windows",
            "plugin_version": "1.2.3+fixture",
            "runtime_tree_sha256": digest,
            "generation": generation,
        }
        deployment = {
            "schema": "sulde-installed-deployment-generation-v1",
            "schema_version": 1,
            "provider": "codex",
            "platform": "windows",
            "artifact_platform": "windows",
            "status": "installed_degraded",
            "operational_ready": False,
            "plugin_version": "1.2.3+fixture",
            "plugin_tree_sha256": "b" * 64,
            "runtime_tree_sha256": digest,
            "generation": generation,
            "artifact": "C:/sealed/artifact",
            "installed_plugin": "C:/sealed/plugin",
            "runtime_root": "C:/sealed/plugin/runtime",
            "managed_labels": ["Sulde-Codex-Harvest", "Sulde-Daily-Distill"],
            "scheduler_runner": "C:/kb/bin/sulde-windows-task.py",
            "scheduler_runner_sha256": "c" * 64,
        }
        launcher = {
            "schema": "sulde-launcher-install-v1",
            "schema_version": 1,
            "spec_version": 8,
            "provider": "codex",
            "platform": "windows",
            "generated_at": "2026-08-20T00:00:00+00:00",
            "source_root": deployment["runtime_root"],
            "runtime_sha256": "d" * 64,
            "runtime_tree_sha256": digest,
            "generation": generation,
            "interpreter": "C:/kb/.venv/Scripts/python.exe",
            "interpreter_sha256": "e" * 64,
            "interpreter_prefix": "C:/kb/.venv/Scripts/python.exe",
            "codex_hook_surface_sha256": "f" * 64,
            "command_effects_sha256": "1" * 64,
            "launchers": {},
            "scheduler_runner": deployment["scheduler_runner"],
            "scheduler_runner_sha256": deployment["scheduler_runner_sha256"],
        }
        validate(runtime, deployment, launcher)

        mutations = (
            ("runtime missing schema", runtime, "schema", None),
            ("runtime bool schema", runtime, "schema_version", True),
            ("runtime wrong provider", runtime, "provider", "claude"),
            ("runtime wrong platform", runtime, "platform", "posix"),
            ("runtime unsupported schema", runtime, "schema_version", 2),
            ("runtime truncated generation", runtime, "generation", generation[:-1]),
            ("deployment unknown field", deployment, "unexpected", "self-consistent"),
            ("deployment wrong platform", deployment, "platform", "posix"),
            ("launcher missing provider", launcher, "provider", None),
            ("launcher unsupported spec", launcher, "spec_version", 9),
            ("launcher bool spec", launcher, "spec_version", True),
            ("launcher runner drift", launcher, "scheduler_runner_sha256", "9" * 64),
        )
        for label, original, field, value in mutations:
            with self.subTest(label=label):
                changed = json.loads(json.dumps(original))
                if value is None:
                    changed.pop(field)
                else:
                    changed[field] = value
                documents = [runtime, deployment, launcher]
                documents[{id(runtime): 0, id(deployment): 1, id(launcher): 2}[id(original)]] = changed
                with self.assertRaisesRegex(RuntimeError, "envelope"):
                    validate(*documents)

        wrong = [json.loads(json.dumps(value)) for value in (runtime, deployment, launcher)]
        wrong_digest = "9" * 64
        wrong_generation = f"1.2.3+fixture:{wrong_digest}"
        for document in wrong:
            document["runtime_tree_sha256"] = wrong_digest
            document["generation"] = wrong_generation
        with self.assertRaisesRegex(RuntimeError, "runtime bytes"):
            validate(*wrong, actual_runtime_tree_sha256=digest)

    def test_windows_retired_state_rolls_back_exact_bytes_after_second_registration_failure(self) -> None:
        module = runpy.run_path(str(SCRIPT_DIR / "windows-task.py"))
        snapshot_retired_state = module["snapshot_retired_state"]
        restore_retired_state = module["restore_retired_state"]

        def tree_bytes(root: Path) -> dict[str, tuple[str, bytes | None, int]] | None:
            if not root.exists():
                return None
            captured: dict[str, tuple[str, bytes | None, int]] = {
                ".": ("dir", None, root.stat().st_mode & 0o777)
            }
            for path in sorted(root.rglob("*")):
                relative = path.relative_to(root).as_posix()
                captured[relative] = (
                    (
                        "dir",
                        None,
                        path.stat().st_mode & 0o777,
                    )
                    if path.is_dir()
                    else (
                        "file",
                        path.read_bytes(),
                        path.stat().st_mode & 0o777,
                    )
                )
            return captured

        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            retired = root / ".sulde-retired/windows-tasks"
            retired.mkdir(parents=True)
            (retired / "Sulde-Claude-Harvest.xml").write_bytes(
                b"\xff\xfe<old-generation archive='harvest'/>\r\n"
            )
            (retired / "Sulde-Claude-Harvest.tombstone.json").write_bytes(
                b'{"generation":"old","status":"historical"}\r\n'
            )
            (retired / "operator-evidence").mkdir()
            (retired / "operator-evidence/raw.bin").write_bytes(b"\x00old\xffbytes\r\n")
            retired.chmod(0o700)
            (retired / "operator-evidence/raw.bin").chmod(0o600)
            before_retired = tree_bytes(retired)
            before_tasks = {
                "Sulde-Claude-Distill": b"<Task generation='old'/>\r\n",
                "Sulde-Codex-Harvest": b"<Task generation='old'/>\r\n",
                "Sulde-Daily-Distill": b"<Task generation='old'/>\r\n",
            }
            task_state = dict(before_tasks)
            transaction = root / "transaction/retired-state"

            snapshot_retired_state(retired, transaction)
            try:
                retired_task = "Sulde-Claude-Distill"
                (retired / f"{retired_task}.xml").write_bytes(task_state[retired_task])
                del task_state[retired_task]
                (retired / f"{retired_task}.tombstone.json").write_bytes(
                    b'{"status":"retired","replacement":"immutable-generation-owner"}\n'
                )
                for index, task_name in enumerate(
                    ("Sulde-Codex-Harvest", "Sulde-Daily-Distill")
                ):
                    if index == 1:
                        raise RuntimeError("injected second task registration failure")
                    task_state[task_name] = b"<Task generation='new'/>\n"
            except RuntimeError as error:
                restore_retired_state(retired, transaction)
                task_state = dict(before_tasks)
                self.assertIn("second task registration failure", str(error))

            self.assertEqual(task_state, before_tasks)
            self.assertEqual(tree_bytes(retired), before_retired)

            absent_retired = root / "previously-absent/windows-tasks"
            absent_snapshot = root / "transaction/absent-retired-state"
            snapshot_retired_state(absent_retired, absent_snapshot)
            absent_retired.mkdir(parents=True)
            (absent_retired / "new.tombstone.json").write_bytes(b"new transaction")
            restore_retired_state(absent_retired, absent_snapshot)
            self.assertFalse(absent_retired.exists())

        source = (SCRIPT_DIR / "install-agents.ps1").read_text(encoding="utf-8")
        self.assertIn("Save-RetiredState", source)
        self.assertIn("Restore-RetiredState", source)
        self.assertIn("Set-Acl", source)
        self.assertIn("FAIL CLOSED", source)

    def test_windows_staged_generation_rejects_invalid_versions_and_unsafe_trees(self) -> None:
        module = runpy.run_path(str(SCRIPT_DIR / "windows-task.py"))
        verify = module["verify_staged_runtime"]
        with tempfile.TemporaryDirectory() as directory_name:
            plugin = Path(directory_name) / "plugin"
            runtime = plugin / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "main.py").write_text("print('ok')\n", encoding="utf-8")
            descriptor_dir = plugin / ".codex-plugin"
            descriptor_dir.mkdir()
            descriptor_path = descriptor_dir / "generation.json"
            for invalid in (None, "", 7):
                descriptor_path.write_text(
                    json.dumps(
                        {
                            "schema": "sulde-delivery-generation-v1",
                            "schema_version": 1,
                            "provider": "codex",
                            "platform": "windows",
                            "plugin_version": invalid,
                            "runtime_tree_sha256": "irrelevant",
                            "generation": "irrelevant",
                        }
                    ),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(RuntimeError, "plugin_version"):
                    verify(runtime)

            valid_digest = module["runtime_tree_digest"](runtime)
            descriptor_path.write_text(
                json.dumps(
                    {
                        "schema": "sulde-delivery-generation-v1",
                        "schema_version": 1,
                        "provider": "codex",
                        "platform": "windows",
                        "plugin_version": "1.2.3+fixture",
                        "runtime_tree_sha256": valid_digest,
                        "generation": f"1.2.3+fixture:{valid_digest}",
                    }
                ),
                encoding="utf-8",
            )
            (runtime / ".git").mkdir()
            with self.assertRaisesRegex(RuntimeError, "mutable|repository"):
                verify(runtime)
            (runtime / ".git").rmdir()
            cache = runtime / "__pycache__"
            cache.mkdir()
            (cache / "main.pyc").write_bytes(b"executable-bytecode")
            with self.assertRaisesRegex(RuntimeError, "Python bytecode"):
                verify(runtime)

    def test_windows_desired_state_and_transaction_rollback_are_exact(self) -> None:
        module = runpy.run_path(str(SCRIPT_DIR / "windows-task.py"))
        reconcile = module["reconcile_task_state"]
        desired = {
            "Sulde-Codex-Harvest": {"action": "new-harvest", "generation": "g2"},
            "Sulde-Daily-Distill": {"action": "new-distill", "generation": "g2"},
        }
        previous = {
            "runner": b"runner-g1",
            "owner": {"generation": "g1", "status": "active"},
            "tasks": {
                "Sulde-Codex-Harvest": {"action": "old-harvest", "generation": "g1"},
                "Sulde-Daily-Distill": {"action": "old-distill", "generation": "g1"},
            },
        }
        with self.assertRaisesRegex(RuntimeError, "unknown Sulde task"):
            reconcile(
                {**previous, "tasks": {**previous["tasks"], "Sulde-Unknown": {}}},
                desired,
                fail_after=None,
            )
        with self.assertRaisesRegex(RuntimeError, "injected registration failure") as caught:
            reconcile(previous, desired, fail_after=1)
        self.assertEqual(caught.exception.args[1], previous)
        completed = reconcile(previous, desired, fail_after=None)
        self.assertEqual(completed["owner"]["generation"], "g2")
        self.assertFalse(completed["owner"]["operational_ready"])
        self.assertEqual(completed["tasks"], desired)

    def test_windows_installer_declares_lock_snapshot_inventory_and_readback(self) -> None:
        source = (SCRIPT_DIR / "install-agents.ps1").read_text(encoding="utf-8")
        for marker in (
            ".deployment.lock",
            "Get-ScheduledTask",
            "Export-ScheduledTask",
            "LastTaskResult",
            "runtime_tree_sha256",
            "runner_sha256",
            "Restore-Transaction",
        ):
            self.assertIn(marker, source)
        self.assertIn("unknown Sulde task", source)
        self.assertIn("retired", source.lower())

    def test_windows_scheduler_rejects_noncanonical_actions_before_child_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            runtime = root / "plugin/runtime"
            scripts = runtime / "scripts/kb"
            scripts.mkdir(parents=True)
            child_runs = root / "child-runs.txt"
            (scripts / "codex-harvest.py").write_text(
                "import json, os\n"
                f"with open({str(child_runs)!r}, 'a', encoding='utf-8') as handle:\n"
                "    handle.write('run\\n')\n"
                "print(json.dumps({"
                "'secret_visible': 'LLM_API_KEY' in os.environ, "
                "'generation': os.environ.get('SULDE_RUNTIME_GENERATION'), "
                "'provider': os.environ.get('SULDE_HOST_PROVIDER')}))\n",
                encoding="utf-8",
            )
            (scripts / "auto-distill.py").write_text("print('distill')\n", encoding="utf-8")
            (scripts / "mem-secret-scan.py").write_text(
                "raise SystemExit(0)\n", encoding="utf-8"
            )
            module = runpy.run_path(str(SCRIPT_DIR / "windows-task.py"))
            digest = module["runtime_tree_digest"](runtime)
            generation = f"1.2.3+fixture:{digest}"
            descriptor_dir = runtime.parent / ".codex-plugin"
            descriptor_dir.mkdir()
            (descriptor_dir / "generation.json").write_text(
                json.dumps(
                    {
                        "schema": "sulde-delivery-generation-v1",
                        "schema_version": 1,
                        "provider": "codex",
                        "platform": "windows",
                        "plugin_version": "1.2.3+fixture",
                        "runtime_tree_sha256": digest,
                        "generation": generation,
                    }
                ),
                encoding="utf-8",
            )
            kb_home = root / "kb"
            launcher_bin = kb_home / "bin"
            launcher_bin.mkdir(parents=True)
            stable_runner = launcher_bin / "sulde-windows-task.py"
            shutil.copy2(SCRIPT_DIR / "windows-task.py", stable_runner)
            runner_sha256 = module["sha256_file"](stable_runner)
            provider_executable = root / "Codex.exe"

            def canonical_action(job: str) -> str:
                return (
                    f'"{stable_runner.resolve()}" --kb-home "{kb_home.resolve()}" '
                    f'--runtime-root "{runtime.resolve()}" --generation "{generation}" '
                    f'--runner-sha256 "{runner_sha256}" --provider "codex" '
                    f'--provider-executable "{provider_executable}" {job}'
                )

            deployment = {
                "schema": "sulde-installed-deployment-generation-v1",
                "schema_version": 1,
                "provider": "codex",
                "platform": "windows",
                "artifact_platform": "windows",
                "status": "installed_degraded",
                "operational_ready": False,
                "plugin_version": "1.2.3+fixture",
                "plugin_tree_sha256": "b" * 64,
                "runtime_root": str(runtime.resolve()),
                "runtime_tree_sha256": digest,
                "generation": generation,
                "artifact": str((root / "artifact").resolve()),
                "installed_plugin": str(runtime.parent.resolve()),
                "managed_labels": ["Sulde-Codex-Harvest", "Sulde-Daily-Distill"],
                "scheduler_runner": str(stable_runner.resolve()),
                "scheduler_runner_sha256": runner_sha256,
            }
            owner = {
                "schema_version": 2,
                "status": "active",
                "installation_status": "installed_degraded",
                "operational_ready": False,
                "provider": "codex",
                "executable": str(provider_executable),
                "source_root": str(runtime.resolve()),
                "runtime_root": str(runtime.resolve()),
                "runtime_tree_sha256": digest,
                "generation": generation,
                "scheduler_runner_sha256": runner_sha256,
                "managed_labels": ["Sulde-Codex-Harvest", "Sulde-Daily-Distill"],
                "retired_labels": ["Sulde-Claude-Harvest", "Sulde-Claude-Distill"],
                "task_readback": [
                    {
                        "task_name": name,
                        "action_execute": sys.executable,
                        "action_arguments": canonical_action(
                            "harvest" if name == "Sulde-Codex-Harvest" else "distill"
                        ),
                        "runtime_root": str(runtime.resolve()),
                        "generation": generation,
                        "runner_sha256": runner_sha256,
                        "LastTaskResult": 0,
                    }
                    for name in ("Sulde-Codex-Harvest", "Sulde-Daily-Distill")
                ],
                "scheduler": "windows-task-scheduler",
                "installed_at": "2026-08-20T00:00:00+00:00",
            }
            launcher = {
                "schema": "sulde-launcher-install-v1",
                "schema_version": 1,
                "spec_version": 8,
                "provider": "codex",
                "platform": "windows",
                "generated_at": "2026-08-20T00:00:00+00:00",
                "source_root": str(runtime.resolve()),
                "runtime_sha256": "c" * 64,
                "runtime_tree_sha256": digest,
                "generation": generation,
                "interpreter": sys.executable,
                "interpreter_sha256": "d" * 64,
                "interpreter_prefix": sys.executable,
                "codex_hook_surface_sha256": "e" * 64,
                "command_effects_sha256": "f" * 64,
                "launchers": {},
                "scheduler_runner": str(stable_runner.resolve()),
                "scheduler_runner_sha256": runner_sha256,
            }
            (kb_home / "deployment-generation.json").write_text(
                json.dumps(deployment), encoding="utf-8"
            )
            (kb_home / "runtime-owner.json").write_text(
                json.dumps(owner), encoding="utf-8"
            )
            (launcher_bin / ".sulde-launchers.json").write_text(
                json.dumps(launcher), encoding="utf-8"
            )
            command = [
                sys.executable,
                str(stable_runner),
                "--kb-home",
                str(kb_home),
                "--runtime-root",
                str(runtime),
                "--generation",
                generation,
                "--runner-sha256",
                runner_sha256,
                "--provider",
                "codex",
                "--provider-executable",
                str(provider_executable),
                "harvest",
            ]
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, "LLM_API_KEY": "must-not-reach-child"},
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            child = json.loads(completed.stdout)
            self.assertFalse(child["secret_visible"])
            self.assertEqual(child["generation"], generation)
            self.assertEqual(child["provider"], "codex")
            self.assertEqual(child_runs.read_text(encoding="utf-8"), "run\n")
            self.assertEqual(
                [row["action_arguments"] for row in owner["task_readback"]],
                [canonical_action("harvest"), canonical_action("distill")],
            )

            harvest_action = canonical_action("harvest")
            reordered_action = (
                f'"{stable_runner.resolve()}" --runtime-root "{runtime.resolve()}" '
                f'--kb-home "{kb_home.resolve()}" --generation "{generation}" '
                f'--runner-sha256 "{runner_sha256}" --provider "codex" '
                f'--provider-executable "{provider_executable}" harvest'
            )
            missing_kb_home_action = harvest_action.replace(
                f' --kb-home "{kb_home.resolve()}"', ""
            )
            malicious_decoy = (
                f'--payload "{stable_runner.name} {runtime.resolve()} {generation} '
                f'{runner_sha256}" harvest'
            )
            negative_actions = (
                (
                    "malicious executable plus decoy arguments",
                    "C:/attacker/malware.exe",
                    malicious_decoy,
                ),
                ("wrong executable", "C:/wrong/pythonw.exe", harvest_action),
                (
                    "runner basename",
                    sys.executable,
                    harvest_action.replace(
                        f'"{stable_runner.resolve()}"', f'"{stable_runner.name}"'
                    ),
                ),
                ("leading token", sys.executable, "extra " + harvest_action),
                ("trailing token", sys.executable, harvest_action + " extra"),
                (
                    "duplicate flag",
                    sys.executable,
                    harvest_action.replace(
                        ' --provider "codex"',
                        ' --generation "duplicate" --provider "codex"',
                    ),
                ),
                ("reordered flags", sys.executable, reordered_action),
                ("missing kb-home", sys.executable, missing_kb_home_action),
                (
                    "wrong provider executable",
                    sys.executable,
                    harvest_action.replace(
                        f'"{provider_executable}" harvest',
                        '"C:/attacker/codex.exe" harvest',
                    ),
                ),
                (
                    "job substitution",
                    sys.executable,
                    harvest_action.removesuffix("harvest") + "distill",
                ),
            )
            for label, action_execute, action_arguments in negative_actions:
                with self.subTest(action=label):
                    changed_owner = json.loads(json.dumps(owner))
                    changed_owner["task_readback"][0]["action_execute"] = action_execute
                    changed_owner["task_readback"][0][
                        "action_arguments"
                    ] = action_arguments
                    (kb_home / "runtime-owner.json").write_text(
                        json.dumps(changed_owner), encoding="utf-8"
                    )
                    rejected = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                    )
                    self.assertEqual(rejected.returncode, 2, rejected.stderr)
                    self.assertIn("task action binding drifted", rejected.stderr)
                    self.assertEqual(
                        child_runs.read_text(encoding="utf-8"),
                        "run\n",
                        "scheduled child ran for rejected action",
                    )
            (kb_home / "runtime-owner.json").write_text(
                json.dumps(owner), encoding="utf-8"
            )

            stable_bytes = stable_runner.read_bytes()
            stable_runner.write_bytes(stable_bytes + b"\n# mutable wrapper drift\n")
            wrapper_drift = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(wrapper_drift.returncode, 2)
            self.assertIn("runner digest drifted", wrapper_drift.stderr)
            stable_runner.write_bytes(stable_bytes)

            owner["generation"] = "stale-generation"
            (kb_home / "runtime-owner.json").write_text(
                json.dumps(owner), encoding="utf-8"
            )
            stale = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(stale.returncode, 2)
            self.assertIn("owner envelope generation", stale.stderr)

            owner["generation"] = generation
            owner["task_readback"][0]["action_arguments"] = owner["task_readback"][
                0
            ]["action_arguments"].replace("harvest", "distill")
            (kb_home / "runtime-owner.json").write_text(
                json.dumps(owner), encoding="utf-8"
            )
            action_drift = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(action_drift.returncode, 2)
            self.assertIn("task action binding drifted", action_drift.stderr)

            owner["task_readback"][0]["action_arguments"] = owner["task_readback"][
                0
            ]["action_arguments"].replace("distill", "harvest")
            owner["managed_labels"] = ["Sulde-Codex-Harvest"] * 2
            (kb_home / "runtime-owner.json").write_text(
                json.dumps(owner), encoding="utf-8"
            )
            inventory_drift = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(inventory_drift.returncode, 2)
            self.assertIn("task inventory is invalid", inventory_drift.stderr)

            owner["managed_labels"] = [
                "Sulde-Codex-Harvest",
                "Sulde-Daily-Distill",
            ]
            (kb_home / "runtime-owner.json").write_text(
                json.dumps(owner), encoding="utf-8"
            )
            deployment["unknown"] = "internally-consistent-but-unsupported"
            (kb_home / "deployment-generation.json").write_text(
                json.dumps(deployment), encoding="utf-8"
            )
            unknown_field = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(unknown_field.returncode, 2)
            self.assertIn("deployment envelope fields", unknown_field.stderr)

    def test_every_cognitive_organ_uses_the_runtime_port_by_default(self) -> None:
        for name in COGNITIVE_ORGANS:
            source = (SCRIPT_DIR / name).read_text(encoding="utf-8")
            self.assertNotIn('DEFAULT_LLM_CMD = "claude ', source, name)
            self.assertNotIn('DEFAULT_LLM_CMD = "codex ', source, name)
            self.assertIn('default_llm_command"]()', source, name)

    def test_default_command_keeps_prompt_off_argv(self) -> None:
        helper = runpy.run_path(str(SCRIPT_DIR / "command_template.py"))
        command = helper["default_llm_command"]()
        arguments = helper["split_command_template"](command)
        self.assertEqual(Path(arguments[-2]).name, "llm-runtime.py")
        self.assertEqual(arguments[-1], "{prompt}")

    def test_l3_has_no_external_claude_skill_dependency(self) -> None:
        source = (SCRIPT_DIR / "self-repair.py").read_text(encoding="utf-8")
        self.assertNotIn('Path.home() / ".claude" / "skills"', source)
        self.assertNotIn("launch.sh", source)
        self.assertNotIn("verify.sh", source)
        self.assertIn('"agent-runtime.py"', source)

    def test_global_rules_and_self_do_not_require_the_other_host(self) -> None:
        templates = ROOT / "templates"
        claude = (templates / "global/claude-rules.md").read_text(encoding="utf-8")
        codex = (templates / "global/codex-agents-rules.md").read_text(encoding="utf-8")
        self_template = (templates / "SELF.md").read_text(encoding="utf-8")
        self.assertNotIn("先调用 codex-agent", claude)
        self.assertNotIn("委托给 codex MCP", claude)
        self.assertIn("不得把 Codex CLI", claude)
        self.assertIn("不得把 Claude Code CLI", codex)
        self.assertNotIn("memory-distill/codex-agent", self_template)
        self.assertIn("仓库自有 agent runtime", self_template)

    def test_shared_knowledge_skills_use_host_neutral_runtime_paths(self) -> None:
        for name in ("kb-search", "memory-distill", "sediment"):
            source = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertNotIn("CLAUDE_PLUGIN_ROOT", source, name)
            self.assertNotIn("改道 cognee", source, name)
            self.assertIn("SULDE_HOME", source, name)
            self.assertNotIn(".claude/plugins/data", source, name)

    def test_installers_declare_one_provider_for_mind_and_action(self) -> None:
        mac = (SCRIPT_DIR / "install-agents.sh").read_text(encoding="utf-8")
        windows = (SCRIPT_DIR / "install-agents.ps1").read_text(encoding="utf-8")
        for variable in ("SULDE_HOST_PROVIDER", "SULDE_LLM_PROVIDER", "SULDE_AGENT_PROVIDER"):
            self.assertIn(variable, mac)
        self.assertIn("--provider", mac)
        self.assertIn("--accept-llm-data-egress", mac)
        self.assertIn('LAUNCHER_AUTHORITY="$LAUNCHER_HOME/bin/.sulde-launchers.json"', mac)
        self.assertIn('launcher_manifest = launcher_home / "bin/.sulde-launchers.json"', mac)
        self.assertIn("-Provider", windows)
        self.assertIn("AcceptDailyLlmInvocation", windows)
        self.assertIn("Resolve-LauncherHome", windows)
        self.assertIn("$launcherPath = Join-Path $launcherHome", windows)

    def test_mac_has_only_one_label_namespace_for_coexistence(self) -> None:
        labels: list[str] = []
        for path in (ROOT / "templates" / "launchagents").glob("*.plist"):
            text = path.read_text(encoding="utf-8")
            marker = "<key>Label</key>"
            self.assertEqual(text.count(marker), 1, path.name)
            labels.append(path.name)
        self.assertEqual(len(labels), len(set(labels)))

    @unittest.skipIf(os.name == "nt", "fixture uses a POSIX shell")
    def test_retired_cache_repair_only_writes_tombstone(self) -> None:
        script = ROOT / "scripts/fix-plugin-cache-dirs.sh"
        source = script.read_text(encoding="utf-8")
        self.assertNotIn("ln -s", source)
        self.assertNotIn("readlink", source)
        with tempfile.TemporaryDirectory() as directory_name:
            home = Path(directory_name)
            cache = home / ".codex/plugins/cache/sulde-local/sulde"
            donor = cache / "new"
            donor.mkdir(parents=True)
            (donor / "marker.txt").write_text("new\n", encoding="utf-8")
            legacy = cache / "old"
            legacy.symlink_to(donor, target_is_directory=True)
            before = legacy.readlink()
            environment = {**os.environ, "HOME": str(home)}
            first = subprocess.run(
                [str(script)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=10,
                check=False,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertTrue(legacy.is_symlink())
            self.assertEqual(legacy.readlink(), before)
            tombstone = home / ".sulde/state/codex-cache-repair.retired.json"
            payload = json.loads(tombstone.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "retired")
            self.assertEqual(payload["label"], "com.sulde.codex-cache-repair")
            self.assertEqual(tombstone.stat().st_mode & 0o777, 0o600)
            original = tombstone.read_bytes()
            second = subprocess.run(
                [str(script)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=10,
                check=False,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(tombstone.read_bytes(), original)

    @unittest.skipIf(os.name == "nt", "fixture uses POSIX executable shims")
    def test_mac_scheduler_reconciles_retired_actors_and_fences_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            plugin = root / "installed/plugins/sulde"
            runtime = plugin / "runtime"
            scripts = runtime / "scripts/kb"
            scripts.mkdir(parents=True)
            shutil.copy2(SCRIPT_DIR / "install-agents.sh", scripts / "install-agents.sh")
            for runtime_support in (
                "production_recovery_readiness.py",
                "recovery_lane.py",
                "sulde_paths.py",
                "supervisor_state.py",
            ):
                shutil.copy2(SCRIPT_DIR / runtime_support, scripts / runtime_support)
            shutil.copytree(
                ROOT / "templates/launchagents",
                runtime / "templates/launchagents",
            )
            target_names = {
                "auto-sediment.py",
                "codex-harvest.py",
                "auto-distill.py",
                "golden-expand.py",
                "governance-report.py",
                "graph-audit.py",
                "heartbeat.py",
                "kb-aging.py",
                "kb-dedup.py",
                "life-cycle.py",
                "mem-backup.py",
                "memory-embed-worker.py",
                "mem-sync.py",
                "self-repair.py",
                "sulde-status.py",
            }
            for name in target_names:
                target = scripts / name
                target.write_text(
                    "import json, os, sys\n"
                    "print(json.dumps({'target': __file__, 'argv': sys.argv[1:], "
                    "'secret_visible': 'LLM_API_KEY' in os.environ, "
                    "'kb_home': os.environ.get('SULDE_KB_HOME')}))\n",
                    encoding="utf-8",
                )
            descriptor = plugin / ".codex-plugin/plugin.json"
            descriptor.parent.mkdir(parents=True)
            descriptor.write_text(
                json.dumps({"name": "sulde", "version": "1.2.3+fixture"}),
                encoding="utf-8",
            )

            fake_provider = root / "fake-codex"
            fake_provider.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_provider.chmod(0o755)
            launchctl_log = root / "launchctl.log"
            fake_launchctl = root / "fake-launchctl"
            fake_launchctl.write_text(
                textwrap.dedent(
                    f'''\
                    #!{sys.executable}
                    import json
                    import os
                    from pathlib import Path
                    import plistlib
                    import sys
                    args = sys.argv[1:]
                    state = Path(os.environ["FAKE_LAUNCHCTL_STATE"])
                    try:
                        labels = json.loads(state.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        labels = json.loads(os.environ.get("FAKE_LOADED_LABELS", "[]"))
                    if args == ["list"]:
                        for label in labels:
                            print(f"-\\t0\\t{{label}}")
                    else:
                        log = Path(os.environ["FAKE_LAUNCHCTL_LOG"])
                        with log.open("a", encoding="utf-8") as handle:
                            handle.write(" ".join(args) + "\\n")
                        failure_marker = state.with_name("failure-consumed")
                        if (
                            args
                            and args[0] == os.environ.get("FAKE_FAIL_ACTION")
                            and not failure_marker.exists()
                        ):
                            failure_marker.write_text("consumed", encoding="utf-8")
                            raise SystemExit(9)
                        if len(args) == 2 and args[0] == "remove":
                            labels = [label for label in labels if label != args[1]]
                        elif len(args) == 2 and args[0] in {{"load", "unload"}}:
                            with Path(args[1]).open("rb") as handle:
                                payload = plistlib.load(handle)
                                label = payload["Label"]
                            if args[0] == "load" and label not in labels:
                                labels.append(label)
                                if payload.get("RunAtLoad") is True:
                                    kb_home = Path(os.environ["SULDE_KB_HOME"])
                                    owner = json.loads(
                                        (kb_home / "runtime-owner.json").read_text(encoding="utf-8")
                                    )
                                    deployment = json.loads(
                                        (kb_home / "deployment-generation.json").read_text(encoding="utf-8")
                                    )
                                    with log.open("a", encoding="utf-8") as handle:
                                        handle.write(
                                            "run-at-load-authority "
                                            f"owner={{owner.get('status')}} "
                                            f"deployment={{deployment.get('status')}}\\n"
                                        )
                            elif args[0] == "unload":
                                labels = [item for item in labels if item != label]
                        state.write_text(json.dumps(labels), encoding="utf-8")
                    '''
                ),
                encoding="utf-8",
            )
            fake_launchctl.chmod(0o755)
            launchagents = root / "Library/LaunchAgents"
            launchagents.mkdir(parents=True)
            retired = launchagents / "com.sulde.codex-cache-repair.plist"
            with retired.open("wb") as handle:
                plistlib.dump(
                    {
                        "Label": "com.sulde.codex-cache-repair",
                        "ProgramArguments": ["/bin/false"],
                    },
                    handle,
                )
            kb_home = root / "kb"
            environment = {
                **os.environ,
                "HOME": str(root),
                "TMPDIR": str(root),
                "SULDE_PLATFORM_NAME": "Darwin",
                "SULDE_KB_HOME": str(kb_home),
                "SULDE_LAUNCHAGENTS_DIR": str(launchagents),
                "SULDE_LAUNCHCTL": str(fake_launchctl),
                "SULDE_SCHEDULER_PYTHON": sys.executable,
                "SULDE_CODEX_EXE": str(fake_provider),
                "FAKE_LOADED_LABELS": json.dumps(
                    ["com.sulde.codex-cache-repair"]
                ),
                "FAKE_LAUNCHCTL_LOG": str(launchctl_log),
                "FAKE_LAUNCHCTL_STATE": str(root / "launchctl-state.json"),
            }
            # This case exercises the self-contained legacy/custom KB layout.
            # The isolated suite itself supplies a neutral SULDE_HOME, which
            # must not accidentally change the fixture's deployment authority.
            environment.pop("SULDE_HOME", None)
            (root / "launchctl-state.json").write_text(
                json.dumps(["com.sulde.codex-cache-repair"]),
                encoding="utf-8",
            )
            command = [
                str(scripts / "install-agents.sh"),
                "--provider",
                "codex",
                "--runtime-root",
                str(runtime),
            ]
            dry_run = subprocess.run(
                [*command, "--dry-run"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=30,
                check=False,
            )
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
            self.assertIn(
                f"dry-run: launcher authority={kb_home / 'bin/.sulde-launchers.json'}",
                dry_run.stdout,
            )
            neutral_root = root / ".sulde"
            neutral_kb = neutral_root / "data/kb"
            neutral_dry_run = subprocess.run(
                [*command, "--dry-run"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={
                    **environment,
                    "SULDE_HOME": str(neutral_root),
                    "SULDE_KB_HOME": str(neutral_kb),
                },
                timeout=30,
                check=False,
            )
            self.assertEqual(neutral_dry_run.returncode, 0, neutral_dry_run.stderr)
            self.assertIn(
                f"dry-run: launcher authority={neutral_root / 'bin/.sulde-launchers.json'}",
                neutral_dry_run.stdout,
            )
            match = re.search(r"dry-run: generation=(\S+)", dry_run.stdout)
            self.assertIsNotNone(match, dry_run.stdout)
            generation = match.group(1)
            runtime_digest = generation.split(":", 1)[1]
            claude_environment = {
                **environment,
                "SULDE_CLAUDE_EXE": str(fake_provider),
            }
            claude_without_authority = subprocess.run(
                [
                    str(scripts / "install-agents.sh"),
                    "--provider",
                    "claude",
                    "--runtime-root",
                    str(runtime),
                    "--accept-llm-data-egress",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=claude_environment,
                timeout=10,
                check=False,
            )
            self.assertNotEqual(claude_without_authority.returncode, 0)
            self.assertIn("provider-neutral deployment", claude_without_authority.stderr)
            self.assertFalse((kb_home / "runtime-owner.json").exists())
            self.assertTrue(retired.exists())
            kb_home.mkdir(parents=True, exist_ok=True)
            (kb_home / "deployment-generation.json").write_text(
                json.dumps(
                    {
                        "schema": "sulde-installed-deployment-generation-v1",
                        "schema_version": 1,
                        "status": "installed_degraded",
                        "operational_ready": False,
                        "provider": "codex",
                        "plugin_version": "1.2.3+fixture",
                        "runtime_root": str(runtime.resolve()),
                        "runtime_tree_sha256": runtime_digest,
                        "generation": generation,
                        "managed_labels": sorted(
                            path.stem
                            for path in (runtime / "templates/launchagents").glob(
                                "com.sulde.*.plist"
                            )
                        ),
                    }
                ),
                encoding="utf-8",
            )
            launcher_bin = kb_home / "bin"
            launcher_bin.mkdir()
            (launcher_bin / ".sulde-launchers.json").write_text(
                json.dumps(
                    {
                        "source_root": str(runtime.resolve()),
                        "runtime_tree_sha256": runtime_digest,
                        "generation": generation,
                    }
                ),
                encoding="utf-8",
            )

            installed = subprocess.run(
                [*command, "--accept-llm-data-egress"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=30,
                check=False,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertFalse(retired.exists())
            archived = list(
                (launchagents / ".sulde-retired/archive").glob(
                    "com.sulde.codex-cache-repair.plist"
                )
            )
            self.assertEqual(len(archived), 1)
            self.assertTrue(
                (
                    launchagents
                    / ".sulde-retired/tombstones/com.sulde.codex-cache-repair.json"
                ).is_file()
            )
            calls = launchctl_log.read_text(encoding="utf-8")
            self.assertIn("remove com.sulde.codex-cache-repair", calls)
            self.assertIn("load ", calls)
            self.assertIn(
                "run-at-load-authority owner=activating deployment=installed_live_unverified",
                calls,
            )
            deployment = json.loads(
                (kb_home / "deployment-generation.json").read_text(encoding="utf-8")
            )
            self.assertEqual(deployment["status"], "generation_verified")
            self.assertTrue(deployment["operational_ready"])
            owner_path = kb_home / "runtime-owner.json"
            owner = json.loads(owner_path.read_text(encoding="utf-8"))
            self.assertEqual(owner["schema_version"], 2)
            self.assertEqual(owner["status"], "active")
            self.assertEqual(owner["installation_status"], "generation_verified")
            self.assertTrue(owner["operational_ready"])
            self.assertEqual(owner["generation"], generation)
            self.assertEqual(owner["runtime_root"], str(runtime.resolve()))
            self.assertEqual(owner["runtime_tree_sha256"], runtime_digest)
            self.assertIn(
                "com.sulde.codex-cache-repair", owner["retired_labels"]
            )
            self.assertEqual(len(owner["managed_labels"]), 16)
            self.assertEqual(owner_path.stat().st_mode & 0o777, 0o600)
            recovery_key = kb_home / "control/recovery.key"
            self.assertEqual(len(recovery_key.read_bytes()), 32)
            self.assertEqual(recovery_key.stat().st_mode & 0o777, 0o600)

            repeated = subprocess.run(
                [*command, "--accept-llm-data-egress"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=30,
                check=False,
            )
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            repeated_deployment = json.loads(
                (kb_home / "deployment-generation.json").read_text(encoding="utf-8")
            )
            repeated_owner = json.loads(owner_path.read_text(encoding="utf-8"))
            self.assertEqual(repeated_deployment["status"], "generation_verified")
            self.assertTrue(repeated_deployment["operational_ready"])
            self.assertEqual(repeated_owner["installation_status"], "generation_verified")
            self.assertTrue(repeated_owner["operational_ready"])
            self.assertEqual(repeated_owner["generation"], generation)
            self.assertRegex(
                repeated_owner["scheduler_activation_id"], r"^[0-9a-f]{32}$"
            )
            self.assertEqual(
                repeated_deployment["scheduler_activation_id"],
                repeated_owner["scheduler_activation_id"],
            )
            owner = repeated_owner
            deployment = repeated_deployment

            rendered = launchagents / "com.sulde.daily-distill.plist"
            with rendered.open("rb") as handle:
                payload = plistlib.load(handle)
            arguments = payload["ProgramArguments"]
            self.assertIn(str(runtime.resolve()), arguments)
            self.assertNotIn(str(ROOT.resolve()), arguments)
            fenced_environment = {
                **os.environ,
                **payload["EnvironmentVariables"],
                "LLM_API_KEY": "must-not-reach-scheduled-child",
            }
            self.assertEqual(
                arguments[arguments.index("--activation-id") + 1],
                owner["scheduler_activation_id"],
            )
            owner_bytes = owner_path.read_bytes()
            deployment_path = kb_home / "deployment-generation.json"
            deployment_bytes = deployment_path.read_bytes()
            launcher_path = kb_home / "bin/.sulde-launchers.json"
            launcher_bytes = launcher_path.read_bytes()

            activating_owner = {
                **owner,
                "status": "activating",
                "installation_status": "installed_degraded",
                "operational_ready": False,
            }
            activating_deployment = {
                **deployment,
                "status": "installed_live_unverified",
                "operational_ready": False,
            }
            owner_path.write_text(json.dumps(activating_owner), encoding="utf-8")
            deployment_path.write_text(
                json.dumps(activating_deployment), encoding="utf-8"
            )
            committing = subprocess.Popen(
                arguments,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=fenced_environment,
            )
            try:
                time.sleep(0.2)
                self.assertIsNone(
                    committing.poll(),
                    "same-activation RunAtLoad exited before transaction commit",
                )
                deployment_path.write_bytes(deployment_bytes)
                owner_path.write_bytes(owner_bytes)
                commit_stdout, commit_stderr = committing.communicate(timeout=10)
            finally:
                if committing.poll() is None:
                    committing.kill()
                    committing.communicate()
            self.assertEqual(committing.returncode, 0, commit_stderr)
            committed_payload = json.loads(commit_stdout)
            self.assertEqual(
                committed_payload["target"],
                str((runtime / "scripts/kb/auto-distill.py").resolve()),
            )

            owner_path.write_text(json.dumps(activating_owner), encoding="utf-8")
            deployment_path.write_text(
                json.dumps(activating_deployment), encoding="utf-8"
            )
            rolling_back = subprocess.Popen(
                arguments,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=fenced_environment,
            )
            try:
                time.sleep(0.2)
                self.assertIsNone(
                    rolling_back.poll(),
                    "same-activation RunAtLoad exited before rollback",
                )
                previous_activation = "0" * 32
                rolled_back_owner = {
                    **owner,
                    "scheduler_activation_id": previous_activation,
                }
                rolled_back_deployment = {
                    **deployment,
                    "scheduler_activation_id": previous_activation,
                }
                rolled_back_launcher = json.loads(launcher_bytes)
                rolled_back_launcher["scheduler_activation_id"] = previous_activation
                owner_path.write_text(
                    json.dumps(rolled_back_owner), encoding="utf-8"
                )
                deployment_path.write_text(
                    json.dumps(rolled_back_deployment), encoding="utf-8"
                )
                launcher_path.write_text(
                    json.dumps(rolled_back_launcher), encoding="utf-8"
                )
                rollback_stdout, rollback_stderr = rolling_back.communicate(timeout=10)
            finally:
                if rolling_back.poll() is None:
                    rolling_back.kill()
                    rolling_back.communicate()
                owner_path.write_bytes(owner_bytes)
                deployment_path.write_bytes(deployment_bytes)
                launcher_path.write_bytes(launcher_bytes)
            self.assertNotEqual(rolling_back.returncode, 0, rollback_stdout)
            self.assertIn(
                "stale or inactive runtime generation", rollback_stderr
            )

            owner_path.write_text(json.dumps(activating_owner), encoding="utf-8")
            deployment_path.write_text(
                json.dumps(activating_deployment), encoding="utf-8"
            )
            timeout_arguments = list(arguments)
            runner_argument_index = timeout_arguments.index("--runner-sha256")
            timeout_arguments[runner_argument_index:runner_argument_index] = [
                "--activation-wait-seconds",
                "0.1",
            ]
            timed_out = subprocess.run(
                timeout_arguments,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=fenced_environment,
                timeout=2,
                check=False,
            )
            owner_path.write_bytes(owner_bytes)
            deployment_path.write_bytes(deployment_bytes)
            self.assertNotEqual(timed_out.returncode, 0)
            self.assertIn(
                "activation transaction did not commit", timed_out.stderr
            )

            fenced = subprocess.run(
                arguments,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=fenced_environment,
                timeout=10,
                check=False,
            )
            self.assertEqual(fenced.returncode, 0, fenced.stderr)
            self.assertIn(str(runtime.resolve()), fenced.stdout)
            fenced_payload = json.loads(fenced.stdout)
            self.assertFalse(fenced_payload["secret_visible"])
            self.assertEqual(fenced_payload["kb_home"], str(kb_home.resolve()))

            stable_wrapper = kb_home / "bin/sulde-scheduled-run"
            stable_wrapper_bytes = stable_wrapper.read_bytes()
            stable_wrapper.write_bytes(stable_wrapper_bytes + b"\n# mutable wrapper drift\n")
            wrapper_drift = subprocess.run(
                arguments,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=fenced_environment,
                timeout=10,
                check=False,
            )
            self.assertNotEqual(wrapper_drift.returncode, 0)
            self.assertIn("runtime tree digest drifted", wrapper_drift.stderr)
            stable_wrapper.write_bytes(stable_wrapper_bytes)

            unknown_label = "com.sulde.codex-cache-repair-v2"
            unknown_plist = launchagents / f"{unknown_label}.plist"
            with unknown_plist.open("wb") as handle:
                plistlib.dump(
                    {"Label": unknown_label, "ProgramArguments": ["/bin/false"]},
                    handle,
                )
            launchctl_state = Path(environment["FAKE_LAUNCHCTL_STATE"])
            loaded = json.loads(launchctl_state.read_text(encoding="utf-8"))
            launchctl_state.write_text(
                json.dumps([*loaded, unknown_label]), encoding="utf-8"
            )
            unknown = subprocess.run(
                [*command, "--accept-llm-data-egress"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=10,
                check=False,
            )
            self.assertNotEqual(unknown.returncode, 0)
            self.assertIn("unknown Sulde actor", unknown.stderr)
            self.assertTrue(unknown_plist.is_file())
            unknown_plist.unlink()
            launchctl_state.write_text(json.dumps(loaded), encoding="utf-8")

            unexpected_runtime_file = runtime / "unexpected-runtime-drift.txt"
            unexpected_runtime_file.write_text("drift\n", encoding="utf-8")
            drifted = subprocess.run(
                arguments,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=fenced_environment,
                timeout=10,
                check=False,
            )
            self.assertNotEqual(drifted.returncode, 0)
            self.assertIn("runtime tree digest drifted", drifted.stderr)
            unexpected_runtime_file.unlink()

            owner["generation"] = "stale-generation"
            owner_path.write_text(json.dumps(owner), encoding="utf-8")
            stale = subprocess.run(
                arguments,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn("stale or inactive runtime generation", stale.stderr)

            owner["generation"] = generation
            owner_path.write_text(json.dumps(owner), encoding="utf-8")
            previous_files = {
                path: path.read_bytes()
                for path in (
                    owner_path,
                    kb_home / "bin/sulde-scheduled-run",
                    kb_home / "deployment-generation.json",
                    kb_home / "bin/.sulde-launchers.json",
                    rendered,
                )
            }
            failing_environment = {**environment, "FAKE_FAIL_ACTION": "load"}
            failed_reload = subprocess.run(
                [*command, "--accept-llm-data-egress"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=failing_environment,
                timeout=10,
                check=False,
            )
            self.assertNotEqual(failed_reload.returncode, 0)
            for path, expected_bytes in previous_files.items():
                self.assertEqual(path.read_bytes(), expected_bytes, path)
            rolled_back_owner = json.loads(owner_path.read_text(encoding="utf-8"))
            self.assertEqual(rolled_back_owner["status"], "active")
            self.assertEqual(rolled_back_owner["generation"], generation)
            self.assertEqual(
                set(json.loads(launchctl_state.read_text(encoding="utf-8"))),
                set(owner["managed_labels"]),
            )

            valid_deployment_bytes = (
                kb_home / "deployment-generation.json"
            ).read_bytes()
            invalid_deployment = json.loads(valid_deployment_bytes)
            invalid_deployment["status"] = "active"
            (kb_home / "deployment-generation.json").write_text(
                json.dumps(invalid_deployment),
                encoding="utf-8",
            )
            invalid_prestate_bytes = (
                kb_home / "deployment-generation.json"
            ).read_bytes()
            rejected_transition = subprocess.run(
                [*command, "--accept-llm-data-egress"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=10,
                check=False,
            )
            self.assertNotEqual(rejected_transition.returncode, 0)
            self.assertIn(
                "deployment transition rejected prestate",
                rejected_transition.stderr,
            )
            self.assertEqual(
                (kb_home / "deployment-generation.json").read_bytes(),
                invalid_prestate_bytes,
            )
            self.assertEqual(
                json.loads(owner_path.read_text(encoding="utf-8"))["status"],
                "active",
            )
            self.assertEqual(
                set(json.loads(launchctl_state.read_text(encoding="utf-8"))),
                set(owner["managed_labels"]),
            )
            (kb_home / "deployment-generation.json").write_bytes(
                valid_deployment_bytes
            )

            deployment_lock = kb_home / ".deployment.lock"
            deployment_lock.mkdir()
            (deployment_lock / "owner.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "pid": os.getpid(),
                        "token": "live-installer-fixture",
                    }
                ),
                encoding="utf-8",
            )
            concurrent = subprocess.run(
                [*command, "--accept-llm-data-egress"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=10,
                check=False,
            )
            self.assertNotEqual(concurrent.returncode, 0)
            self.assertIn(
                "another plugin or scheduler deployment owns",
                concurrent.stderr,
            )
            (deployment_lock / "owner.json").unlink()
            deployment_lock.rmdir()
            uninstalled = subprocess.run(
                [*command, "--uninstall"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=10,
                check=False,
            )
            self.assertEqual(uninstalled.returncode, 0, uninstalled.stderr)
            self.assertFalse(
                owner_path.exists(),
                f"stdout={uninstalled.stdout}\nstderr={uninstalled.stderr}",
            )
            self.assertFalse((kb_home / "bin/sulde-scheduled-run").exists())
            self.assertEqual(list(launchagents.glob("com.sulde.*.plist")), [])

    def test_status_reads_bom_runtime_owner_and_checks_executable(self) -> None:
        status = runpy.run_path(str(SCRIPT_DIR / "sulde-status.py"))
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            executable = directory / "codex"
            executable.write_text("fixture\n", encoding="utf-8")
            owner = directory / "runtime-owner.json"
            owner.write_text(
                json.dumps(
                    {
                        "provider": "codex",
                        "executable": str(executable),
                        "scheduler": "fixture",
                    }
                ),
                encoding="utf-8-sig",
            )
            result = status["read_runtime_owner"](owner)
        self.assertEqual(result["runtime_provider"], "codex")
        self.assertEqual(result["runtime_scheduler"], "fixture")
        self.assertTrue(result["runtime_available"])

    def test_scheduler_health_includes_missing_failed_and_retired_actor_truth(self) -> None:
        status = runpy.run_path(str(SCRIPT_DIR / "sulde-status.py"))
        owner = {
            "runtime_owner_status": "active",
            "runtime_available": True,
            "runtime_scheduler": "launchd",
            "runtime_managed_labels": [
                "com.sulde.daily-distill",
                "com.sulde.mem-sync-export",
                "com.sulde.heartbeat",
            ],
            "runtime_retired_labels": ["com.sulde.codex-cache-repair"],
        }
        projection = status["scheduler_health_projection"](
            owner,
            platform_name="darwin",
            launchctl_list_output=(
                "-\t1\tcom.sulde.daily-distill\n"
                "321\t-\tcom.sulde.heartbeat\n"
                "-\t0\tcom.sulde.codex-cache-repair\n"
            ),
        )
        self.assertEqual(projection["status"], "degraded")
        self.assertEqual(
            projection["missing_labels"], ["com.sulde.mem-sync-export"]
        )
        self.assertEqual(
            projection["failed_labels"], {"com.sulde.daily-distill": "1"}
        )
        self.assertEqual(
            projection["retired_loaded_labels"], ["com.sulde.codex-cache-repair"]
        )


if __name__ == "__main__":
    unittest.main()
