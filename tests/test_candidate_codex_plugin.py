from __future__ import annotations

from contextlib import nullcontext
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "scripts" / "release" / "candidate_codex_plugin.py"
INSTALLER = ROOT / "scripts" / "release" / "install_codex_plugin.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class CandidateDeploymentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="sulde-candidate-tests-")
        self.root = Path(self.temporary.name)
        self.module = load_module(CANDIDATE, f"candidate_test_{id(self)}")
        self.installer = self.module.installer

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_prepare_rejects_unaudited_versions_before_any_candidate_write(self):
        identity = {"codex_command": "/fixture/codex", "codex_command_sha256": "c" * 64}
        for code, output in ((0, "codex-cli 0.153.4\n"),
                             (0, "codex-cli 0.155.0\n"),
                             (0, "wrapper codex-cli 0.154.0\n"),
                             (1, "codex-cli 0.154.0\n")):
            with (
                self.subTest(code=code, output=output),
                mock.patch.object(self.installer, "_codex_command_identity", return_value=identity),
                mock.patch.object(self.installer, "run_command", return_value=
                    self.installer.CommandResult(("codex", "--version"), code, output, "")),
                mock.patch.object(self.module, "_candidate_python") as python_setup,
                mock.patch.object(self.module, "_source_identity") as source_scan,
                mock.patch.object(self.installer, "_stage_artifact") as stage,
                self.assertRaisesRegex(self.module.CandidateError, "exactly codex-cli 0.154.0"),
            ):
                self.module.prepare(candidate_home=self.root / "untouched", codex="/fixture/codex",
                                    platform="posix", candidate_id="rejected")
            python_setup.assert_not_called()
            source_scan.assert_not_called()
            stage.assert_not_called()
            self.assertFalse((self.root / "untouched").exists())

    def test_prepare_rejects_identity_drift_and_accepts_exact_version_gate(self):
        first = {"codex_command": "/fixture/codex", "codex_command_sha256": "c" * 64}
        for changed in (False, True):
            second = {**first, "codex_command_sha256": "d" * 64} if changed else first
            error = "changed during candidate preflight" if changed else "reached Python preflight"
            with (
                self.subTest(changed=changed),
                mock.patch.object(self.installer, "_codex_command_identity", side_effect=[first, second]),
                mock.patch.object(self.installer, "run_command", return_value=
                    self.installer.CommandResult(("codex", "--version"), 0, "codex-cli 0.154.0\n", "")),
                mock.patch.object(self.module, "_candidate_python",
                                  side_effect=self.module.CandidateError("reached Python preflight")) as setup,
                self.assertRaisesRegex(self.module.CandidateError, error),
            ):
                self.module.prepare(candidate_home=self.root / "untouched", codex="/fixture/codex",
                                    platform="posix", candidate_id="probe")
            self.assertEqual(setup.call_count, 0 if changed else 1)
            self.assertFalse((self.root / "untouched").exists())

    def test_verify_rejects_old_version_and_identity_drift_before_environment_setup(self):
        for old_version in (False, True):
            slot = self.root / ("old-version" if old_version else "changed-bytes")
            slot.mkdir()
            state = self.state(slot)
            if old_version:
                state["codex"]["version"] = "codex-cli 0.153.4"
                self.module._write_state(slot, state)
            before = (slot / "state.json").read_bytes()
            with (
                mock.patch.object(self.installer, "_codex_command_identity", return_value={
                    "codex_command": "/opt/codex", "codex_command_sha256": "f" * 64}),
                mock.patch.object(self.module, "_candidate_environment") as environment,
                mock.patch.object(self.installer, "deployment_cas_snapshot") as snapshot,
                self.assertRaisesRegex(self.module.CandidateError,
                    "another audited Codex version" if old_version else "changed after candidate preparation"),
            ):
                self.module.verify(candidate_home=self.root, candidate_id=slot.name)
            environment.assert_not_called()
            snapshot.assert_not_called()
            self.assertEqual((slot / "state.json").read_bytes(), before)

    def test_candidate_environment_discards_parent_authority_and_private_context(self):
        sentinels = {key: 'private-parent-sentinel' for key in (
            'SULDE_INTENT_CONTRACT', 'SULDE_INTENT_ID', 'CODEX_THREAD_ID',
            'CLAUDE_SESSION_ID', 'OPENAI_API_KEY', 'AWS_SECRET_ACCESS_KEY',
            'PYTHONPATH', 'PYTHONHOME', 'CUSTOM_TOKEN', 'HTTP_PROXY')}
        identity = {'executable': sys.executable}
        with mock.patch.dict(os.environ, sentinels), mock.patch.object(
            self.module, '_install_isolated_python', return_value=Path(sys.executable)
        ), mock.patch.object(self.module, 'inspect_python', return_value=identity), mock.patch.object(
            self.module, 'same_runtime', return_value=True
        ):
            env = self.module._candidate_environment(self.root, '/fixture/codex', identity)
        self.assertFalse(set(sentinels) & set(env))
        for key in ('HOME', 'USERPROFILE', 'CODEX_HOME', 'SULDE_HOME', 'SULDE_KB_HOME',
                    'TMPDIR', 'TMP', 'TEMP', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME'):
            self.assertTrue(Path(env[key]).is_relative_to(self.root), key)

    def state(self, slot: Path, *, status: str = "prepared") -> dict[str, object]:
        artifact = slot / "artifact"
        plugin = artifact / "plugins" / "sulde"
        plugin.mkdir(parents=True, exist_ok=True)
        state: dict[str, object] = {
            "schema": self.module.STATE_SCHEMA,
            "schema_version": 1,
            "candidate_id": slot.name,
            "status": status,
            "created_at": "2026-09-01T00:00:00+00:00",
            "updated_at": "2026-09-01T00:00:00+00:00",
            "source": {
                "commit": "a" * 40,
                "tree": "b" * 40,
                "plugin_version": "0.2.5+candidate",
            },
            "platform": "posix",
            "codex": {
                "executable": "/opt/codex",
                "executable_sha256": "c" * 64,
                "version": "codex-cli 0.154.0",
            },
            "python": self.module._python_identity(Path(sys.executable)),
            "artifact": {
                "path": str(artifact.resolve()),
                "plugin_tree_sha256": "d" * 64,
                "runtime_tree_sha256": "e" * 64,
                "generation": "0.2.5+candidate:" + "e" * 64,
                "plugin_version": "0.2.5+candidate",
                "platform": "posix",
            },
            "receipt_sha256": None,
            "promotion_consumed": False,
        }
        return self.module._write_state(slot, state)

    def test_state_digest_rejects_tampering(self) -> None:
        slot = self.root / "candidate-1"
        slot.mkdir()
        self.state(slot)
        state = json.loads((slot / "state.json").read_text(encoding="utf-8"))
        state["status"] = "promoted"
        (slot / "state.json").write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(self.module.CandidateError, "digest differs"):
            self.module.show(candidate_home=self.root, candidate_id=slot.name)

    def test_canonical_bytes_are_the_installer_authority(self) -> None:
        payload = {"unicode": "候选", "nested": {"enabled": True}}

        self.assertEqual(
            self.module._canonical(payload),
            self.installer._canonical_json_bytes(payload),
        )
        self.assertFalse(self.module._canonical(payload).endswith(b"\n"))
        with self.assertRaises(ValueError):
            self.module._canonical({"invalid": float("nan")})

    def test_discard_is_bounded_to_one_verified_slot(self) -> None:
        slot = self.root / "candidate-2"
        slot.mkdir()
        self.state(slot, status="verification_failed")
        sentinel = self.root / "keep.txt"
        sentinel.write_text("keep\n", encoding="utf-8")

        result = self.module.discard(
            candidate_home=self.root, candidate_id=slot.name
        )

        self.assertEqual(result["status"], "discarded")
        self.assertFalse(slot.exists())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep\n")
        for unsafe in ("..", ".", "a/b"):
            with self.assertRaises(self.module.CandidateError):
                self.module.discard(candidate_home=self.root, candidate_id=unsafe)

    def test_discard_accepts_only_a_narrow_unsealed_prepare_orphan(self) -> None:
        safe = self.root / "prepare-orphan"
        (safe / "artifact").mkdir(parents=True)
        result = self.module.discard(
            candidate_home=self.root, candidate_id=safe.name
        )
        self.assertEqual(result["status"], "discarded")

        ambiguous = self.root / "ambiguous-orphan"
        ambiguous.mkdir()
        (ambiguous / "unrelated.txt").write_text("preserve\n", encoding="utf-8")
        with self.assertRaisesRegex(self.module.CandidateError, "ambiguous"):
            self.module.discard(
                candidate_home=self.root, candidate_id=ambiguous.name
            )

    def test_promotion_cas_snapshot_does_not_require_live_process_probe(self) -> None:
        with (
            mock.patch.object(
                self.installer, "current_marketplace_root", return_value=None
            ),
            mock.patch.object(
                self.installer, "current_plugin_installation", return_value=None
            ),
            mock.patch.object(self.installer, "_loaded_sulde_labels") as loaded,
        ):
            snapshot = self.installer.deployment_cas_snapshot(
                self.root / "kb", "codex"
            )
        self.assertEqual(snapshot["schema"], "sulde-codex-promotion-prestate-v1")
        self.assertNotIn("loaded_scheduler_labels", snapshot)
        loaded.assert_not_called()

    def test_isolated_fault_materializes_at_the_expected_production_boundary(self) -> None:
        plugin = self.root / "installed"
        hook = plugin / "scripts/pre-tool-use.py"
        generation = plugin / ".codex-plugin/generation.json"
        mcp = plugin / "runtime/tools/kb-mcp/server.py"
        for path in (hook, generation, mcp):
            path.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("original\n", encoding="utf-8")
        generation.write_text(json.dumps({"generation": "original"}), encoding="utf-8")
        mcp.write_text("server\n", encoding="utf-8")

        self.module._fault_injected_installed_tree(plugin, "hook_invalid_json")
        self.assertIn("not-json", hook.read_text(encoding="utf-8"))
        hook.write_text("original\n", encoding="utf-8")
        self.module._fault_injected_installed_tree(plugin, "decision_null")
        self.assertIn("None", hook.read_text(encoding="utf-8"))
        self.module._fault_injected_installed_tree(plugin, "generation_mismatch")
        self.assertEqual(
            json.loads(generation.read_text(encoding="utf-8"))["generation"],
            "injected-mismatch",
        )
        self.module._fault_injected_installed_tree(plugin, "mcp_missing")
        self.assertFalse(mcp.exists())

    @unittest.skipIf(os.name == "nt", "POSIX scheduler adapter fixture")
    def test_scheduler_failure_adapter_is_nonzero(self) -> None:
        fake = self.root / "launchctl"
        self.module._write_fake_launchctl(fake, fail=True)
        completed = subprocess.run(
            [str(fake), "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(completed.returncode, 91)

    @unittest.skipIf(os.name == "nt", "POSIX isolated interpreter wrapper")
    def test_isolated_python_uses_real_candidate_local_executable(self) -> None:
        target = self.module._install_isolated_python(
            self.root / "kb", Path(sys.executable)
        )
        completed = subprocess.run(
            [str(target), "-c", "import sys; print(sys.executable)"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(target.is_file())
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.read_bytes(), Path(sys.executable).read_bytes())
        self.assertEqual(Path(completed.stdout.strip()).resolve(), target.resolve())

    def test_real_preexecution_activates_enforce_through_candidate_cli(self) -> None:
        commands: list[str] = []
        contract_path = self.root / "contract.active.json"
        proposal_path = self.root / "proposal.json"

        def runner(command, **_kwargs):
            action = str(command[2])
            commands.append(action)
            payload: dict[str, object]
            if action == "prepare-proposal":
                payload = {
                    "decision_route": "agent",
                    "contract_path": str(contract_path),
                    "proposal_path": str(proposal_path),
                    "proposal_digest": "a" * 64,
                }
                stdout = json.dumps(payload)
            elif action == "agent-decide-proposal":
                stdout = json.dumps(
                    {"decision": {"authority": "agent-policy"}}
                )
            elif action == "apply-proposal":
                stdout = "INTENT PROPOSAL: APPLIED revision=2"
            elif action == "show":
                stdout = json.dumps(
                    {
                        "mode": "enforce",
                        "status": "active",
                        "revision": 2,
                        "applied_decision_authority": "agent-policy",
                    }
                )
            else:
                self.fail(f"unexpected action: {action}")
            return self.installer.CommandResult(tuple(command), 0, stdout, "")

        selected, proof = self.module._activate_candidate_enforce_contract(
            self.root / "intent-guardian",
            kb_home=self.root / "kb",
            workspace=self.root / "workspace",
            session="candidate-session",
            environment={"SULDE_HOME": str(self.root)},
            runner=runner,
        )

        self.assertEqual(selected, contract_path)
        self.assertEqual(
            commands,
            [
                "prepare-proposal",
                "agent-decide-proposal",
                "apply-proposal",
                "show",
            ],
        )
        self.assertEqual(proof["status"], "ready")
        self.assertEqual(proof["mode"], "enforce")
        self.assertEqual(proof["decision_authority"], "agent-policy")

    def test_candidate_audit_reader_unwraps_guardian_event_envelope(self) -> None:
        event = {
            "event_id": "event-1",
            "call_id": "call-1",
            "phase": "started",
        }

        self.assertIs(self.module._guardian_audit_event(event), event)
        self.assertIs(
            self.module._guardian_audit_event(
                {"schema": "sulde-guardian-event-v1", "event": event}
            ),
            event,
        )

    def test_verification_failure_records_unchanged_live_state_for_every_fault(self) -> None:
        for fault in sorted(self.module._FAULTS):
            with self.subTest(fault=fault):
                slot = self.root / fault
                slot.mkdir()
                self.state(slot)
                live = {"schema": "sulde-codex-promotion-prestate-v1", "marker": fault}
                with (
                    mock.patch.object(self.installer, "_codex_command_identity", return_value={
                        "codex_command": "/opt/codex", "codex_command_sha256": "c" * 64}),
                    mock.patch.object(self.installer, "_codex_version_preflight", return_value="codex-cli 0.154.0"),
                    mock.patch.object(
                        self.installer,
                        "deployment_cas_snapshot",
                        side_effect=[live, live],
                    ),
                    mock.patch.object(
                        self.installer,
                        "validate_staged_marketplace",
                        side_effect=self.module.CandidateError(f"injected {fault}"),
                    ),
                ):
                    with self.assertRaisesRegex(
                        self.module.CandidateError, "live state preserved"
                    ):
                        self.module.verify(
                            candidate_home=self.root,
                            candidate_id=fault,
                            fault=fault,
                        )
                failed = self.module.show(
                    candidate_home=self.root, candidate_id=fault
                )
                self.assertEqual(failed["status"], "verification_failed")
                self.assertTrue(failed["live_preserved"])
                self.assertEqual(failed["fault_injection"], fault)

    def test_promotion_consumes_receipt_once_and_forwards_exact_cas(self) -> None:
        slot = self.root / "candidate-promote"
        slot.mkdir()
        state = self.state(slot, status="verified")
        live = {"schema": "sulde-codex-promotion-prestate-v1", "generation": "old"}
        verifications = {
            name: {"status": "ready"}
            for name in (
                "artifact",
                "isolated_registry",
                "hooks",
                "preexecution_chain",
                "mcp",
                "doctor",
                "scheduler_entrypoint",
            )
        }
        verifications["native_permission_ui"] = {
            "status": "unobserved",
            "exit_code": 78,
        }
        verifications["scheduler_host"] = {
            "status": "unobserved",
            "exit_code": 79,
        }
        receipt = self.module._sealed(
            {
                "schema": self.module.RECEIPT_SCHEMA,
                "schema_version": 1,
                "status": "verified",
                "candidate_id": slot.name,
                "source": state["source"],
                "artifact": state["artifact"],
                "codex": state["codex"],
                "live_prestate": live,
                "live_prestate_sha256": self.module._digest(live),
                "verifications": verifications,
            },
            "receipt_sha256",
        )
        self.module._atomic_json(slot / "verification-receipt.json", receipt)
        state["receipt_sha256"] = receipt["receipt_sha256"]
        self.module._write_state(slot, state)
        descriptor = {
            "delivery_generation": {
                "runtime_tree_sha256": state["artifact"]["runtime_tree_sha256"]
            }
        }
        with (
            mock.patch.object(
                self.installer, "validate_staged_marketplace", return_value=descriptor
            ),
            mock.patch.object(
                self.installer,
                "tree_digest",
                return_value=state["artifact"]["plugin_tree_sha256"],
            ),
            mock.patch.object(
                self.installer,
                "install",
                return_value={"status": "generation_verified"},
            ) as install,
        ):
            result = self.module.promote(
                candidate_home=self.root,
                candidate_id=slot.name,
                kb_home=self.root / "live-kb",
            )
            self.assertEqual(result["status"], "generation_verified")
            self.assertEqual(
                install.call_args.kwargs["expected_live_state"], live
            )
            self.assertEqual(
                install.call_args.kwargs["candidate_receipt"], receipt
            )
            with self.assertRaisesRegex(
                self.module.CandidateError, "not available"
            ):
                self.module.promote(
                    candidate_home=self.root,
                    candidate_id=slot.name,
                    kb_home=self.root / "live-kb",
                )


class InstallerCandidateBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidate = load_module(CANDIDATE, f"candidate_boundary_test_{id(self)}")
        self.installer = self.candidate.installer
        self.temporary = tempfile.TemporaryDirectory(prefix="sulde-installer-cas-")
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_cas_failure_happens_before_artifact_or_scheduler_preparation(self) -> None:
        subprocess.run([sys.executable, "-B", "-m", "venv", "--without-pip", "--system-site-packages",
                        str(self.root / "kb/venv")], check=True, capture_output=True)
        prepared = self.installer.PreparedArtifact(
            self.root / "artifact", {}, "a" * 64
        )
        with (
            mock.patch.object(
                self.installer,
                "_codex_host_preflight",
                return_value={"status": "ready"},
            ),
            mock.patch.object(
                self.installer, "_deployment_lock", return_value=nullcontext("lock")
            ),
            mock.patch.object(
                self.installer, "load_active_transaction", return_value=None
            ),
            mock.patch.object(
                self.installer,
                "_assert_deployment_cas",
                side_effect=self.installer.InstallError("prestate drifted"),
            ),
            mock.patch.object(self.installer, "_stage_artifact") as stage,
            mock.patch.object(self.installer, "_scheduler_actor_preflight") as actors,
        ):
            with self.assertRaisesRegex(self.installer.InstallError, "prestate drifted"):
                self.installer.install(
                    artifact=self.root / "artifact",
                    kb_home=self.root / "kb",
                    codex="codex",
                    platform="posix",
                    prepared_artifact=prepared,
                    candidate_receipt={"schema": "fixture"},
                    expected_live_state={"schema": "fixture"},
                )
        stage.assert_not_called()
        actors.assert_not_called()

    def test_recover_only_never_stages_when_no_transaction_exists(self) -> None:
        with (
            mock.patch.object(
                self.installer, "_deployment_lock", return_value=nullcontext("lock")
            ),
            mock.patch.object(
                self.installer, "load_active_transaction", return_value=None
            ),
            mock.patch.object(self.installer, "_stage_artifact") as stage,
        ):
            result = self.installer.recover_only(
                kb_home=self.root / "kb", codex="codex"
            )
        self.assertEqual(result["status"], "no_recovery_required")
        stage.assert_not_called()

    def test_candidate_receipt_binds_runtime_python_identity(self) -> None:
        artifact = self.root / "artifact"
        prepared = self.installer.PreparedArtifact(
            artifact,
            {
                "delivery_generation": {
                    "runtime_tree_sha256": "b" * 64,
                    "generation": "0.2.5+candidate:" + "b" * 64,
                    "plugin_version": "0.2.5+candidate",
                    "platform": "posix",
                }
            },
            "a" * 64,
        )
        live = {"schema": "sulde-codex-promotion-prestate-v1"}
        ready = {
            name: {"status": "ready"}
            for name in (
                "artifact",
                "isolated_registry",
                "hooks",
                "preexecution_chain",
                "mcp",
                "doctor",
                "scheduler_entrypoint",
            )
        }
        ready["native_permission_ui"] = {
            "status": "unobserved",
            "exit_code": 78,
        }
        ready["scheduler_host"] = {
            "status": "unobserved",
            "exit_code": 79,
        }
        python_path = Path(sys.executable).resolve()
        ready['preexecution_chain'].update(
            transport='codex-cli-app-server', native_tool='exec_command', executor='unified_exec',
            positive_executed=True, outside_plan_write_executed=True, destructive_pre_denied=True, marker_absent=True,
            artifact_generation='0.2.5+candidate:' + 'b' * 64, loaded_module_generation='f' * 64,
            proof_id='a' * 64, session_id='native-fixture', started_event_id='native-denial',
            scope_denial_event_id='native-scope-denial', native_denial_run_id='host:pre-tool:call')
        receipt = {
            "schema": self.installer.CANDIDATE_RECEIPT_SCHEMA,
            "schema_version": 1,
            "status": "verified",
            "source": {"commit": "c" * 40, "tree": "d" * 40},
            "artifact": {
                "path": str(artifact.resolve()),
                "plugin_tree_sha256": "a" * 64,
                "runtime_tree_sha256": "b" * 64,
                "generation": "0.2.5+candidate:" + "b" * 64,
                "plugin_version": "0.2.5+candidate",
                "platform": "posix",
            },
            "codex": {
                "executable": "/opt/codex",
                "executable_sha256": "e" * 64,
                "version": "codex-cli 0.154.0",
            },
            "python": self.installer.inspect_python(python_path),
            "live_prestate": live,
            "live_prestate_sha256": hashlib.sha256(
                self.installer._canonical_json_bytes(live)
            ).hexdigest(),
            "verifications": ready,
        }

        def seal(value):
            return self.candidate._sealed(value, "receipt_sha256")

        def git_runner(command, **_kwargs):
            value = "d" * 40 if command[-1] == "HEAD^{tree}" else "c" * 40
            return self.installer.CommandResult(tuple(command), 0, value + "\n", "")

        def codex_runner(command, **_kwargs):
            return self.installer.CommandResult(
                tuple(command), 0, "codex-cli 0.154.0\n", ""
            )

        with (
            mock.patch.object(self.installer, "run_command", side_effect=git_runner),
            mock.patch.object(
                self.installer,
                "_codex_command_identity",
                return_value={
                    "codex_command": "/opt/codex",
                    "codex_command_sha256": "e" * 64,
                },
            ),
        ):
            verified = self.installer._validated_candidate_receipt(
                seal(receipt),
                prepared=prepared,
                expected_live_state=live,
                codex="/opt/codex",
                runner=codex_runner,
            )
            self.assertEqual(verified["python"]["executable"], str(python_path))
            for override in ({'transport': 'candidate-stable-cli-new-process'},
                             {'positive_executed': False}, {'scope_denial_event_id': ''},
                             {'loaded_module_generation': 'unknown'}, {'artifact_generation': 'other'}):
                invalid = json.loads(json.dumps(receipt))
                invalid['verifications']['preexecution_chain'].update(override)
                with self.subTest(override=override), self.assertRaisesRegex(
                    self.installer.InstallError, 'native PreToolUse'):
                    self.installer._validated_candidate_receipt(seal(invalid), prepared=prepared,
                        expected_live_state=live, codex='/opt/codex', runner=codex_runner)

            unsigned = dict(receipt)
            legacy_newline = dict(unsigned)
            legacy_newline["receipt_sha256"] = hashlib.sha256(
                self.installer._canonical_json_bytes(unsigned) + b"\n"
            ).hexdigest()
            with self.assertRaisesRegex(
                self.installer.InstallError, "receipt digest differs"
            ):
                self.installer._validated_candidate_receipt(
                    legacy_newline,
                    prepared=prepared,
                    expected_live_state=live,
                    codex="/opt/codex",
                    runner=codex_runner,
                )

            field_drift = seal(receipt)
            field_drift["source"] = {"commit": "f" * 40, "tree": "d" * 40}
            with self.assertRaisesRegex(
                self.installer.InstallError, "receipt digest differs"
            ):
                self.installer._validated_candidate_receipt(
                    field_drift,
                    prepared=prepared,
                    expected_live_state=live,
                    codex="/opt/codex",
                    runner=codex_runner,
                )

            missing_python = dict(receipt)
            missing_python.pop("python")
            with self.assertRaisesRegex(
                self.installer.InstallError, "Python identity is missing"
            ):
                self.installer._validated_candidate_receipt(
                    seal(missing_python),
                    prepared=prepared,
                    expected_live_state=live,
                    codex="/opt/codex",
                    runner=codex_runner,
                )


if __name__ == "__main__":
    unittest.main()
