from __future__ import annotations

import json
import os
import shlex
import stat
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts" / "kb"
sys.path.insert(0, str(SCRIPT_DIR))

from event_observer import collect_snapshot, status_projection  # noqa: E402
from intent_guardian import (  # noqa: E402
    active_contract_path,
    default_contract,
    execute_native_decision,
    native_decision_preview,
    observe_native_permission_request,
    observe_user_prompt,
    write_contract,
)
from observation_privacy import (  # noqa: E402
    ObservationPrivacyError,
    export_approved,
    export_proposal_path,
    load_policy,
    policy_path,
    prepare_export,
    privacy_envelope,
    set_mode,
)
from approval_invariant import decide_approval, summary as approval_summary  # noqa: E402


NOW = "2026-08-15T10:00:00+08:00"


def write_jsonl(path: Path, *rows: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


class ObservationPrivacyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "kb"
        self.workspace = self.root / "workspace"
        self.home.mkdir()
        self.workspace.mkdir()
        self.contract = active_contract_path(self.home, self.workspace)
        write_contract(
            self.contract,
            default_contract(
                intent_id="privacy-export-test",
                objective="审阅并导出统一事件观察快照",
                rationale="只允许脱敏、本地、一次性导出",
                acceptance_criteria=["导出物可解析且不含原始敏感内容"],
                workspace=self.workspace,
                mode="enforce",
                confirmed_by="human",
            ),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def seed_event(self, *, message: str = "private diagnostic text") -> Path:
        path = self.home / "notify-log.jsonl"
        write_jsonl(
            path,
            {
                "ts": NOW,
                "message": message,
                "cwd": str(self.workspace / "private-customer"),
            },
        )
        return path

    def live_decide(self, prompt: str, *, provider: str = "claude") -> str:
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(self.home)}):
            return observe_user_prompt(
                {
                    "client": provider,
                    "session_id": f"{provider}-live-review-session",
                    "cwd": str(self.workspace),
                    "intent_contract": str(self.contract),
                    "prompt": prompt,
                    "sulde_observation_source": "live_host_hook",
                },
                provider=provider,
            )

    def prepare(self, destination: Path) -> tuple[dict, dict]:
        snapshot = collect_snapshot(
            self.home,
            workspaces=[self.workspace],
            include_events=True,
        )
        card = prepare_export(
            self.home,
            self.contract,
            output=destination,
            snapshot=snapshot,
            workspaces=[self.workspace],
        )
        return snapshot, card

    def native_decide_export(self, decision: str, *, session: str) -> dict:
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(self.home)}):
            preview = native_decision_preview(
                self.contract,
                kind="observation-export",
                decision=decision,
                target="current",
                provider="codex",
                session_id=session,
            )
            hook = observe_native_permission_request(
                {
                    "client": "codex",
                    "session_id": session,
                    "cwd": str(self.workspace),
                    "intent_contract": str(self.contract),
                    "permission_mode": "default",
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": shlex.join(preview["command_argv"]),
                        "description": preview["description"],
                    },
                },
                provider="codex",
            )
            self.assertEqual(hook["action"], "defer")
            return execute_native_decision(
                self.contract,
                kind="observation-export",
                decision=decision,
                target=preview["target"],
                provider="codex",
                session_id=session,
            )

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "event-observer.py"),
                *arguments,
                "--home",
                str(self.home),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def test_default_local_policy_is_enabled_but_never_export_authority(self) -> None:
        policy = load_policy(self.home)
        envelope = privacy_envelope(policy)
        self.assertEqual(envelope["mode"], "local")
        self.assertTrue(envelope["observationEnabled"])
        self.assertFalse(envelope["portableExportEnabled"])
        self.assertTrue(envelope["portableExportRequiresLiveApproval"])
        self.assertFalse(envelope["authoritativeLogsAffected"])

        self.seed_event()
        snapshot = collect_snapshot(self.home)
        self.assertEqual(snapshot["privacy"]["mode"], "local")
        self.assertEqual(snapshot["summary"]["events_total"], 1)

    def test_disabled_mode_never_reads_sources_or_writes_projection_cache(self) -> None:
        source = self.seed_event(message="must remain unread")
        before = source.read_bytes()
        collect_snapshot(self.home)
        self.assertTrue((self.home / "projections/event-observer-v1.json").is_file())
        set_mode(self.home, "disabled")

        snapshot = collect_snapshot(self.home)
        status = status_projection(self.home)

        self.assertEqual(snapshot["privacy"]["mode"], "disabled")
        self.assertFalse(snapshot["privacy"]["observationEnabled"])
        self.assertIsNone(snapshot["summary"]["contract_healthy"])
        self.assertIsNone(snapshot["summary"]["events_total"])
        self.assertEqual(snapshot["events"], [])
        self.assertEqual(snapshot["sources"], [])
        self.assertEqual(snapshot["projectionCache"]["status"], "privacy_disabled")
        self.assertFalse((self.home / "projections/event-observer-v1.json").exists())
        self.assertEqual(source.read_bytes(), before)
        self.assertFalse(status["event_observation_enabled"])
        self.assertTrue(status["event_observation_privacy_healthy"])
        self.assertIsNone(status["event_contract_violations"])

        set_mode(self.home, "local")
        restored = collect_snapshot(self.home)
        self.assertEqual(restored["summary"]["events_total"], 1)

    def test_malformed_policy_fails_closed_without_claiming_a_healthy_zero(self) -> None:
        self.seed_event()
        path = policy_path(self.home)
        path.parent.mkdir(parents=True)
        path.write_text('{"schema":"future-policy","mode":"local"}\n', encoding="utf-8")

        snapshot = collect_snapshot(self.home)
        status = status_projection(self.home)

        self.assertFalse(snapshot["privacy"]["policyHealthy"])
        self.assertFalse(snapshot["privacy"]["observationEnabled"])
        self.assertIsNone(snapshot["summary"]["contract_violations"])
        self.assertFalse(status["event_observation_privacy_healthy"])

    @unittest.skipIf(os.name == "nt", "symlink creation requires extra Windows privileges")
    def test_policy_symlink_fails_closed_without_following_external_content(self) -> None:
        outside = self.root / "outside-policy.json"
        outside.write_text(
            json.dumps(
                {
                    "schema": "sulde-observation-privacy-policy-v1",
                    "mode": "local",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        path = policy_path(self.home)
        path.parent.mkdir(parents=True)
        path.symlink_to(outside)

        snapshot = collect_snapshot(self.home)

        self.assertFalse(snapshot["privacy"]["policyHealthy"])
        self.assertFalse(snapshot["privacy"]["observationEnabled"])
        self.assertEqual(outside.read_text(encoding="utf-8").count("\n"), 1)

    def test_local_mode_refuses_to_prepare_a_portable_export(self) -> None:
        self.seed_event()
        snapshot = collect_snapshot(self.home, include_events=True)
        with self.assertRaisesRegex(ObservationPrivacyError, "approved-export"):
            prepare_export(
                self.home,
                self.contract,
                output=self.root / "events.json",
                snapshot=snapshot,
            )

    def test_empty_approved_export_does_not_create_a_proposal_or_output(self) -> None:
        set_mode(self.home, "approved-export")
        destination = self.root / "empty.json"
        snapshot = collect_snapshot(self.home, include_events=True)
        with self.assertRaisesRegex(ObservationPrivacyError, "no matching"):
            prepare_export(
                self.home,
                self.contract,
                output=destination,
                snapshot=snapshot,
            )
        self.assertFalse(destination.exists())
        self.assertEqual(approval_summary(self.contract)["open"], 0)

    def test_live_approval_exports_one_exact_frozen_redacted_cut(self) -> None:
        source = self.seed_event()
        set_mode(self.home, "approved-export")
        destination = self.root / "approved-events.json"

        snapshot, card = self.prepare(destination)

        self.assertFalse(destination.exists())
        self.assertEqual(card["decisionSurface"]["codex"]["type"], "PermissionRequest")
        self.assertFalse(card["decisionSurface"]["codex"]["textAuthority"])
        self.assertIn("已经脱敏", card["contains"])
        self.assertIn("隐藏思维", card["excludes"])
        self.assertFalse(card["dataCut"]["returnedEvents"] == 0)
        proposal = json.loads(
            export_proposal_path(self.home, card["proposalDigest"]).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            proposal["frozenSnapshot"]["sourceRevision"],
            snapshot["sourceRevision"],
        )
        self.assertNotIn("private diagnostic text", json.dumps(proposal, ensure_ascii=False))
        if os.name != "nt":
            self.assertEqual(
                stat.S_IMODE(
                    export_proposal_path(
                        self.home, card["proposalDigest"]
                    ).stat().st_mode
                ),
                0o600,
            )

        # Approval bookkeeping is itself observable and changes current logs.
        # The approved export must still publish the exact pre-approval cut.
        decision = self.native_decide_export(
            "approve", session="exact-frozen-export"
        )
        self.assertEqual(decision["status"], "recorded")
        write_jsonl(
            source,
            {
                "ts": "2026-08-15T10:01:00+08:00",
                "message": "post approval private message",
                "cwd": str(self.workspace),
            },
        )

        result = export_approved(self.home, self.contract, card["proposalDigest"])

        self.assertEqual(result["status"], "completed")
        contract = json.loads(self.contract.read_text(encoding="utf-8"))
        receipt = next(
            row
            for row in contract["runtime"]["approval_receipts"]
            if row["action"] == "approve-observation-export"
        )
        self.assertTrue(receipt["consumed_at"])
        self.assertEqual(receipt["consumed_by"], "observation-export-executor")
        self.assertTrue(destination.is_file())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        exported = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(exported["schema"], "sulde-observation-export-v1")
        self.assertEqual(exported["sourceRevision"], snapshot["sourceRevision"])
        self.assertEqual(len(exported["events"]), card["dataCut"]["returnedEvents"])
        self.assertTrue(exported["privacy"]["oneShotApprovalConsumed"])
        self.assertFalse(exported["privacy"]["networkTransmissionAuthorized"])
        rendered = json.dumps(exported, ensure_ascii=False)
        self.assertNotIn("private diagnostic text", rendered)
        self.assertNotIn("post approval private message", rendered)
        self.assertNotIn(str(self.workspace), rendered)
        with self.assertRaisesRegex(ObservationPrivacyError, "already consumed"):
            export_approved(self.home, self.contract, card["proposalDigest"])

    def test_codex_export_text_is_non_authorizing_and_native_choice_is_live(self) -> None:
        self.seed_event()
        set_mode(self.home, "approved-export")
        destination = self.root / "native-approved-events.json"
        _snapshot, card = self.prepare(destination)

        context = self.live_decide("批准观察导出", provider="codex")
        self.assertIn(
            "NATIVE_DECISION_REQUIRED action=approve-observation-export",
            context,
        )
        with self.assertRaisesRegex(ObservationPrivacyError, "no unique approved"):
            export_approved(self.home, self.contract, card["proposalDigest"])

        result = self.native_decide_export(
            "approve", session="codex-live-review-session"
        )
        self.assertEqual(result["status"], "recorded")
        exported = export_approved(self.home, self.contract, card["proposalDigest"])
        self.assertEqual(exported["status"], "completed")
        contract = json.loads(self.contract.read_text(encoding="utf-8"))
        receipt = next(
            row
            for row in contract["runtime"]["approval_receipts"]
            if row["action"] == "approve-observation-export"
        )
        self.assertEqual(receipt["actor"], "permission-request:codex")
        self.assertEqual(receipt["channel"], "codex-native-permission")

    def test_codex_native_export_rejection_cleans_proposal_without_output(self) -> None:
        self.seed_event()
        set_mode(self.home, "approved-export")
        destination = self.root / "native-rejected-events.json"
        _snapshot, card = self.prepare(destination)

        result = self.native_decide_export("reject", session="codex-native-reject")

        self.assertEqual(result["status"], "recorded")
        with self.assertRaisesRegex(ObservationPrivacyError, "no unique approved"):
            export_approved(self.home, self.contract, card["proposalDigest"])
        self.assertFalse(destination.exists())
        self.assertFalse(
            export_proposal_path(self.home, card["proposalDigest"]).exists()
        )

    def test_rejection_and_unapproved_execution_never_create_output(self) -> None:
        self.seed_event()
        set_mode(self.home, "approved-export")
        destination = self.root / "rejected-events.json"
        _snapshot, card = self.prepare(destination)

        with self.assertRaisesRegex(ObservationPrivacyError, "no unique approved"):
            export_approved(self.home, self.contract, card["proposalDigest"])
        decision = self.native_decide_export(
            "reject", session="rejected-export"
        )
        self.assertEqual(decision["status"], "recorded")
        with self.assertRaisesRegex(ObservationPrivacyError, "no unique approved"):
            export_approved(self.home, self.contract, card["proposalDigest"])
        self.assertFalse(destination.exists())

    def test_forged_direct_decision_without_live_hook_receipt_is_not_authority(self) -> None:
        self.seed_event()
        set_mode(self.home, "approved-export")
        destination = self.root / "forged-events.json"
        _snapshot, card = self.prepare(destination)
        decide_approval(
            self.contract,
            kind="observation-export",
            target=card["proposalDigest"],
            outcome="approved",
            provider="codex",
            session_id="forged-session",
            actor="user-prompt:codex",
            receipt_id="f" * 64,
        )

        with self.assertRaisesRegex(ObservationPrivacyError, "live"):
            export_approved(self.home, self.contract, card["proposalDigest"])
        self.assertFalse(destination.exists())

    def test_destination_race_never_overwrites_and_still_consumes_approval(self) -> None:
        self.seed_event()
        set_mode(self.home, "approved-export")
        destination = self.root / "raced-events.json"
        _snapshot, card = self.prepare(destination)
        self.native_decide_export("approve", session="destination-race")
        destination.write_text("human-owned\n", encoding="utf-8")

        with self.assertRaisesRegex(ObservationPrivacyError, "approval was consumed"):
            export_approved(self.home, self.contract, card["proposalDigest"])

        contract = json.loads(self.contract.read_text(encoding="utf-8"))
        receipt = next(
            row
            for row in contract["runtime"]["approval_receipts"]
            if row["action"] == "approve-observation-export"
        )
        self.assertTrue(receipt["consumed_at"])
        self.assertEqual(destination.read_text(encoding="utf-8"), "human-owned\n")
        self.assertFalse(
            export_proposal_path(self.home, card["proposalDigest"]).exists()
        )
        with self.assertRaisesRegex(ObservationPrivacyError, "already consumed"):
            export_approved(self.home, self.contract, card["proposalDigest"])

    @unittest.skipIf(os.name == "nt", "symlink creation requires extra Windows privileges")
    def test_symlinked_contract_is_not_replaced_when_consuming_receipt(self) -> None:
        self.seed_event()
        set_mode(self.home, "approved-export")
        destination = self.root / "symlink-contract-events.json"
        _snapshot, card = self.prepare(destination)
        self.native_decide_export("approve", session="symlink-contract")
        outside = self.root / "outside-contract.json"
        outside.write_bytes(self.contract.read_bytes())
        before = outside.read_bytes()
        self.contract.unlink()
        self.contract.symlink_to(outside)

        with self.assertRaises(ObservationPrivacyError):
            export_approved(self.home, self.contract, card["proposalDigest"])

        self.assertEqual(outside.read_bytes(), before)
        self.assertFalse(destination.exists())

    def test_non_native_host_stays_pending_and_codex_can_finish_same_export(self) -> None:
        self.seed_event()
        set_mode(self.home, "approved-export")
        destination = self.root / "claude-events.json"
        _snapshot, card = self.prepare(destination)

        context = self.live_decide("批准观察导出", provider="claude")
        self.assertIn("NATIVE_DECISION_REQUIRED", context)
        self.assertIn("decision remains pending", context)
        with self.assertRaisesRegex(ObservationPrivacyError, "no unique approved"):
            export_approved(self.home, self.contract, card["proposalDigest"])

        decision = self.native_decide_export(
            "approve", session="cross-host-native-export"
        )
        result = export_approved(self.home, self.contract, card["proposalDigest"])

        self.assertEqual(decision["status"], "recorded")
        self.assertEqual(result["status"], "completed")
        self.assertTrue(destination.is_file())

    def test_cli_route_closes_mode_prepare_live_approval_and_export(self) -> None:
        self.seed_event()
        configured = self.run_cli(
            "set-privacy", "--mode", "approved-export"
        )
        self.assertEqual(configured.returncode, 0, configured.stderr)
        self.assertEqual(json.loads(configured.stdout)["mode"], "approved-export")
        destination = self.root / "cli-events.json"
        prepared = self.run_cli(
            "prepare-export",
            "--contract",
            str(self.contract),
            "--output",
            str(destination),
            "--workspace",
            str(self.workspace),
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        card = json.loads(prepared.stdout)
        self.assertEqual(
            card["decisionSurface"]["codex"]["type"],
            "PermissionRequest",
        )
        self.native_decide_export("approve", session="cli-export")

        exported = self.run_cli(
            "export",
            "--contract",
            str(self.contract),
            "--proposal",
            card["proposalDigest"],
        )

        self.assertEqual(exported.returncode, 0, exported.stderr)
        self.assertEqual(json.loads(exported.stdout)["status"], "completed")
        self.assertEqual(
            json.loads(destination.read_text(encoding="utf-8"))["schema"],
            "sulde-observation-export-v1",
        )

    def test_cli_verify_reports_disabled_as_unavailable_not_healthy(self) -> None:
        set_mode(self.home, "disabled")
        completed = self.run_cli("verify")
        self.assertEqual(completed.returncode, 3, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["privacy"]["mode"], "disabled")
        self.assertIsNone(payload["summary"]["contract_healthy"])

    def test_only_one_readable_export_question_can_be_open(self) -> None:
        self.seed_event()
        set_mode(self.home, "approved-export")
        self.prepare(self.root / "first.json")
        snapshot = collect_snapshot(self.home, include_events=True)
        with self.assertRaisesRegex(ObservationPrivacyError, "already awaits"):
            prepare_export(
                self.home,
                self.contract,
                output=self.root / "second.json",
                snapshot=snapshot,
            )

    def test_disabling_cancels_open_export_and_purges_only_derived_payloads(self) -> None:
        source = self.seed_event()
        before = source.read_bytes()
        set_mode(self.home, "approved-export")
        _snapshot, card = self.prepare(self.root / "never-exported.json")
        proposal_path = export_proposal_path(self.home, card["proposalDigest"])
        self.assertTrue(proposal_path.is_file())
        self.assertEqual(approval_summary(self.contract)["open"], 1)

        policy = set_mode(self.home, "disabled")

        self.assertEqual(policy["cleanup"]["status"], "completed")
        self.assertGreaterEqual(policy["cleanup"]["derivedFilesRemoved"], 1)
        self.assertEqual(policy["cleanup"]["authoritativeLogsRemoved"], 0)
        self.assertEqual(policy["cleanup"]["externalExportsRemoved"], 0)
        self.assertFalse(proposal_path.exists())
        self.assertEqual(approval_summary(self.contract)["open"], 0)
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
