"""Real isolated split-layout refresh, independent proof and debt reconciliation.

Native approval/dispatch history is fixture state. No production state or live
host canary is claimed by these filesystem and ledger tests.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock

import tests.test_launcher_contract as launcher_fixtures

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/kb"))
import launcher_contract as lc
from sulde_paths import launcher_home
from intent_guardian_parts import resource_preflight as preflight


class SplitLauncherRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = launcher_fixtures.LauncherContractTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.base = Path(self.fixture.temp.name).resolve()
        self.runtime = self.fixture.root.resolve()
        for name in ("bootstrap.sh", "launcher_contract.py", "sulde_paths.py"):
            shutil.copy2(ROOT / "scripts/kb" / name, self.runtime / "scripts/kb" / name)
        self.generation = self.fixture.seal_generation()
        self.configure("neutral")

    def configure(self, kind):
        product = self.base / (".sulde" if kind == "neutral" else kind)
        data = product / "data/kb"
        public = product
        if kind == "legacy":
            data = public = self.base / "portable-kb"
        if kind == "explicit":
            data, public = self.base / "other-data", self.base / "other-launchers"
        env = {k: v for k, v in os.environ.items() if not k.startswith("SULDE_")}
        env.update({"SULDE_HOME": str(product), "SULDE_KB_HOME": str(data),
                    "CODEX_HOME": str(self.fixture.codex_home), "PYTHONDONTWRITEBYTECODE": "1"})
        if kind == "explicit": env["SULDE_LAUNCHER_HOME"] = str(public)
        self.environment = env
        self.data, self.public = data, public
        self.data.mkdir(parents=True, exist_ok=True)
        with mock.patch.dict(os.environ, env, clear=True):
            lc.install_launchers(self.data, self.runtime)
            self.assertEqual(launcher_home(self.data), self.public)
        self.manifest = self.public / "bin/.sulde-launchers.json"
        self.runner = self.data / "bin/sulde-scheduled-run"
        self.runner.parent.mkdir(parents=True, exist_ok=True)
        self.runner.write_text("#!/bin/sh\nexit 0\n")
        self.runner.chmod(0o700)
        self.labels = ["com.sulde.isolated-test"]
        common = {"provider": "codex", "runtime_root": str(self.runtime),
                  "runtime_tree_sha256": self.generation.split(":", 1)[1],
                  "generation": self.generation, "operational_ready": True,
                  "scheduler_runner_sha256": lc.sha256_file(self.runner),
                  "scheduler_activation_id": "isolated-activation", "managed_labels": self.labels}
        self.deployment = {**common, "schema": "sulde-installed-deployment-generation-v1",
                           "schema_version": 1, "status": "generation_verified", "platform": "posix",
                           "scheduler_runner": str(self.runner)}
        self.owner = {**common, "schema_version": 2, "status": "active",
                      "installation_status": "generation_verified", "scheduler": "launchd",
                      "source_root": str(self.runtime)}
        self.write_authorities()

    def write_authorities(self):
        for name, payload in (("deployment-generation.json", self.deployment), ("runtime-owner.json", self.owner)):
            path = self.data / name
            path.write_text(json.dumps(payload))
            path.chmod(0o600)

    def refresh(self):
        return subprocess.run(
            ["bash", str(self.runtime / "scripts/kb/bootstrap.sh"), "--launchers-only", "--host", "codex"],
            env=self.environment, cwd=self.base, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=30,
        )

    def candidate(self):
        binding = {"kb_home": str(self.data), "runtime_root": str(self.runtime),
                   "expected_label_count": "1", "expected_labels_sha256": preflight.labels_digest(self.labels)[1]}
        return {"binding": binding, "verification_sha256": "a" * 64}

    def verify(self):
        with mock.patch.dict(os.environ, self.environment, clear=True):
            return preflight.launcher_refresh_verification(self.candidate(), expected_digest="a" * 64)

    def test_real_bootstrap_refresh_and_verifier_in_all_supported_layouts(self):
        for kind in ("neutral", "custom-root", "legacy", "explicit"):
            with self.subTest(layout=kind):
                if kind != "neutral": self.configure(kind)
                self.assertIsNone(self.verify())  # six launchers alone are not effect proof
                refreshed = self.refresh()
                self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
                manifest = json.loads(self.manifest.read_text())
                self.assertEqual(manifest["scheduler_runner"], str(self.runner))
                self.assertEqual(manifest["scheduler_activation_id"], "isolated-activation")
                self.assertEqual(self.verify()["source"], "local_launcher_scheduler_seal_read")
                if self.data != self.public:
                    self.assertFalse((self.data / "bin/.sulde-launchers.json").exists())
                    self.assertFalse((self.public / "bin/sulde-scheduled-run").exists())

    def test_missing_or_mismatched_scheduler_inputs_block_before_refresh(self):
        original_manifest = self.manifest.read_bytes()
        for fault in ("owner-missing", "generation", "runner-digest", "activation", "runner-in-public-bin"):
            with self.subTest(fault=fault):
                saved_owner, saved_deployment = dict(self.owner), dict(self.deployment)
                if fault == "generation": self.owner["generation"] = "other-generation"
                if fault == "runner-digest": self.owner["scheduler_runner_sha256"] = "b" * 64
                if fault == "activation": self.owner["scheduler_activation_id"] = "other-activation"
                if fault == "runner-in-public-bin":
                    lookalike = self.public / "bin/sulde-scheduled-run"
                    shutil.copy2(self.runner, lookalike)
                    self.deployment["scheduler_runner"] = str(lookalike)
                self.write_authorities()
                if fault == "owner-missing": (self.data / "runtime-owner.json").unlink()
                result = self.refresh()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("scheduler seal preflight incomplete", result.stderr)
                self.assertNotIn("refresh complete", result.stdout)
                self.assertEqual(self.manifest.read_bytes(), original_manifest)
                self.assertIsNone(self.verify())
                self.owner, self.deployment = saved_owner, saved_deployment
                self.write_authorities()

    def test_verifier_reads_new_public_manifest_not_old_data_copy_or_claim(self):
        self.assertEqual(self.refresh().returncode, 0)
        good = self.manifest.read_bytes()
        decoy = self.data / "bin/.sulde-launchers.json"
        decoy.write_bytes(good)
        decoy.chmod(0o600)
        current = json.loads(good)
        current.pop("scheduler_runner_sha256")
        self.manifest.write_text(json.dumps(current))
        self.assertIsNone(self.verify())
        self.manifest.write_bytes(good)
        self.assertIsNotNone(self.verify())
        self.runner.write_text("# runner changed after refresh\n")
        self.assertIsNone(self.verify())

    def test_later_host_helper_drift_does_not_hide_real_artifact_damage(self):
        self.assertEqual(self.refresh().returncode, 0)
        self.fixture.validate_script.write_text("# host helper upgraded later\n")
        self.fixture.cachebuster_script.write_text("# host helper upgraded later\n")
        with mock.patch.dict(os.environ, self.environment, clear=True):
            probe = lc.verify_installation(self.data, expected_source_root=self.runtime)
        self.assertFalse(probe["healthy"])
        self.assertEqual(len(probe["issues"]), 2, probe["issues"])
        self.assertIsNotNone(self.verify())
        snapshot = self.public / "bin" / lc.COMMAND_EFFECT_MANIFEST_NAME
        original = snapshot.read_bytes()
        snapshot.write_bytes(original + b"\n")
        self.assertIsNone(self.verify())
        snapshot.write_bytes(original)
        launcher = self.public / "bin" / lc.LAUNCHERS[0].name
        launcher.write_text("# damaged launcher\n")
        self.assertIsNone(self.verify())

    def test_regular_reconciliation_settles_only_proven_existing_debt(self):
        import intent_guardian as guardian
        from intent_guardian_parts import state
        from intervention import begin_attempt, load_projection
        profile_id = "sulde-launcher-refresh-v1"
        profile = state.CONTINUATION_PROFILES[profile_id]
        binding = {**self.candidate()["binding"], "platform": "posix", "plugin_version": "0.1.0",
                   "script_path": str(self.runtime / "scripts/kb/bootstrap.sh"),
                   "script_sha256": lc.sha256_file(self.runtime / "scripts/kb/bootstrap.sh"),
                   "tracked_tree_sha256": "c" * 64, "workspace_root": str(self.base)}
        label = str(profile["label"])
        grant = {"schema": state.CONTINUATION_GRANT_SCHEMA, "grant_id": "",
                 "profile_id": profile_id, "label": label, "acceptance_index": 0,
                 "acceptance_sha256": hashlib.sha256(label.encode()).hexdigest(),
                 **{k: profile[k] for k in ("effect", "capability", "target", "max_uses", "verification_kind", "rollback")},
                 "binding": binding}
        grant["grant_id"] = state._continuation_grant_id(grant)
        candidate = guardian._continuation_candidate_from_grant(grant)
        contract_path = self.base / "isolated-recovery-contract.json"
        contract = guardian.default_contract(intent_id="split-layout-isolated", objective="verify refresh",
                    rationale="isolated regression", acceptance_criteria=[label], workspace=self.base,
                    mode="enforce", confirmed_by="human")
        guardian.write_contract(contract_path, contract)
        resource_key = guardian.canonical_resource_key(grant["target"], kind="opaque")
        attempt_arguments = dict(intent_id=contract["intent_id"], intent_revision=1,
                    fingerprint="d" * 64, source_event_id="isolated-refresh", capability=grant["capability"],
                    target=grant["target"], effect=grant["effect"], provider="codex", session_id="isolated-session",
                    idempotency_key="isolated-refresh", resource_key=resource_key,
                    resource_context={"schema": "exact", "value": grant["target"]},
                    operation_arguments_digest="d" * 64,
                    operation_fingerprint=guardian.effect_operation_fingerprint(provider="codex", capability=grant["capability"],
                        target=grant["target"], resource_key=resource_key, effect=grant["effect"], arguments_digest="d" * 64),
                    verification_kind="content", verification_sha256=candidate["verification_sha256"])
        attempt = begin_attempt(contract_path, **attempt_arguments)
        guardian.mark_attempt_result(contract_path, attempt["attempt_id"], success=True, reason="fixture completed without proof")
        other_target = "host-local:unrelated-resource"
        other_key = guardian.canonical_resource_key(other_target, kind="opaque")
        other_attempt = begin_attempt(contract_path, **{
            **attempt_arguments, "session_id": "other-session",
            "idempotency_key": "other-unproven-write", "source_event_id": "other-write",
            "verification_sha256": "e" * 64, "target": other_target,
            "resource_key": other_key, "resource_context": {"schema": "exact", "value": other_target},
            "operation_fingerprint": guardian.effect_operation_fingerprint(
                provider="codex", capability=grant["capability"], target=other_target,
                resource_key=other_key, effect=grant["effect"], arguments_digest="d" * 64),
        })
        guardian.mark_attempt_result(contract_path, other_attempt["attempt_id"], success=True, reason="other fixture without proof")
        contract = guardian.load_contract(contract_path)
        other_pending = {
            "attempt_id": other_attempt["attempt_id"], "fingerprint": "d" * 64,
            "capability": grant["capability"], "target": other_target,
            "provider": "codex", "session_id": "other-session",
            "verification_kind": "content", "verification_sha256": "e" * 64,
            "outcome_unknown": False,
        }
        contract["runtime"]["pending_verifications"] = [{
            "attempt_id": attempt["attempt_id"], "fingerprint": "d" * 64, "capability": grant["capability"],
            "target": grant["target"], "provider": "codex", "session_id": "isolated-session",
            "created_at": "2026-09-07T00:00:00+00:00", "outcome_unknown": False,
            "verification_kind": "content", "verification_sha256": candidate["verification_sha256"],
            "continuation_grant_id": grant["grant_id"], "continuation_profile_id": profile_id,
            "continuation_grant": grant,
        }, other_pending]
        guardian.write_contract(contract_path, contract)
        other_pending = guardian.load_contract(contract_path)["runtime"]["pending_verifications"][1]
        journal = contract_path.with_name(contract_path.stem + ".interventions.jsonl")
        history = journal.read_bytes()
        with mock.patch.dict(os.environ, self.environment, clear=True):
            self.assertEqual(guardian.reconcile_pending_verifications(contract_path), [])
            self.assertEqual(load_projection(contract_path)["attempts"][attempt["attempt_id"]]["state"], "verifying")
            self.assertEqual(self.refresh().returncode, 0)
            settled = guardian.reconcile_pending_verifications(contract_path)
            self.assertEqual(len(settled), 1)
            self.assertEqual(load_projection(contract_path)["attempts"][attempt["attempt_id"]]["state"], "system_verified")
            self.assertEqual(guardian.load_contract(contract_path)["runtime"]["pending_verifications"], [other_pending])
            self.assertEqual(load_projection(contract_path)["attempts"][other_attempt["attempt_id"]]["state"], "verifying")
            self.assertEqual(guardian.reconcile_pending_verifications(contract_path), [])
        self.assertTrue(journal.read_bytes().startswith(history))


if __name__ == "__main__":
    unittest.main()
