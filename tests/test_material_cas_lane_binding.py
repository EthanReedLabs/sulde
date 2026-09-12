from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts" / "kb"
sys.path.insert(0, str(SCRIPT_DIR))

from intent_guardian import (  # noqa: E402
    GuardianSession,
    IntentGuardianError,
    apply_revision_proposal,
    create_revision_proposal,
    decide_proposal_as_agent,
    default_contract,
    evaluate_event,
    load_contract,
    normalize_hook_event,
    write_contract,
)
from intent_guardian_parts import recovery as guardian_recovery  # noqa: E402
from task_ownership import (  # noqa: E402
    TaskOwnershipError,
    normalize_task_lanes,
    task_lane,
    upsert_task_lane,
)


class MaterialCasLaneBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        (self.root / ".git").mkdir()
        self.contract_path = Path(self.temp.name) / "intent.json"
        contract = default_contract(
            intent_id="t22-material-cas",
            objective="只修改一个明确的本地文件",
            acceptance_criteria=["目标文件通过定向验证"],
            workspace=self.root,
            mode="enforce",
            allowed_paths=["allowed.txt"],
            confirmed_by="human",
        )
        upsert_task_lane(
            contract,
            provider="codex",
            session_id="proposal-owner",
            state="bound",
            source="test-fixture",
        )
        write_contract(self.contract_path, contract)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _proposal(self) -> tuple[Path, str]:
        return create_revision_proposal(
            self.contract_path,
            objective="规范化一个明确的本地文件",
            acceptance_criteria=["定向测试通过", "只修改 allowed.txt"],
            mode="enforce",
            rationale="确定性本地格式修复",
            allowed_paths=["allowed.txt"],
            decision_route="agent",
            intent_kind="deterministic",
            risk="low",
            effects=["local_write"],
            reversibility="reversible",
            cost="none",
            rollback="恢复 allowed.txt",
        )

    def _write_event(
        self,
        *,
        session_id: str,
        phase: str,
        call_id: str,
        success: bool | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "client": "codex",
            "session_id": session_id,
            "call_id": call_id,
            "cwd": str(self.root),
            "tool_name": "Write",
            "tool_input": {
                "file_path": "allowed.txt",
                "content": "bounded\n",
            },
        }
        if success is not None:
            payload["success"] = success
        return normalize_hook_event(payload, phase=phase, provider="codex")

    def test_other_session_denial_and_read_do_not_change_proposal_material_cas(
        self,
    ) -> None:
        proposal, digest = self._proposal()
        before = load_contract(self.contract_path)["runtime"]["material_sequence"]
        session = GuardianSession(self.contract_path, provider="codex")

        denied = session.observe(
            self._write_event(
                session_id="unbound-sibling",
                phase="started",
                call_id="denied-write",
            )
        )
        self.assertEqual(denied.action, "deny")
        read = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "unbound-sibling",
                "call_id": "read-help",
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": "codex --help"},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(session.observe(read).action, "allow")
        current = load_contract(self.contract_path)
        self.assertEqual(current["runtime"]["material_sequence"], before)

        with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": "proposal-owner"}):
            decided = decide_proposal_as_agent(
                self.contract_path,
                digest,
                rationale="跨 lane 的拒绝和读取没有改变实质状态",
                evidence=["material_sequence 未改变"],
                provider="codex",
                session_id="proposal-owner",
            )
        applied = apply_revision_proposal(self.contract_path, proposal)
        lane = task_lane(
            applied,
            provider="codex",
            session_id="proposal-owner",
        )
        self.assertIsNotNone(lane)
        self.assertEqual(lane["state"], "bound")
        self.assertEqual(lane["task_epoch"], applied["task_epoch"])
        self.assertEqual(lane["proposal_digest"], digest)
        self.assertEqual(decided["receipt"]["session_id"], "proposal-owner")

    def test_allowed_material_attempt_advances_once_and_invalidates_proposal(
        self,
    ) -> None:
        _proposal, digest = self._proposal()
        before = load_contract(self.contract_path)["runtime"]["material_sequence"]
        session = GuardianSession(self.contract_path, provider="codex")
        started = self._write_event(
            session_id="proposal-owner",
            phase="started",
            call_id="allowed-write",
        )
        completed = self._write_event(
            session_id="proposal-owner",
            phase="completed",
            call_id="allowed-write",
            success=True,
        )
        self.assertEqual(session.observe(started).action, "allow")
        self.assertEqual(session.observe(completed).action, "allow")
        current = load_contract(self.contract_path)
        self.assertEqual(current["runtime"]["material_sequence"], before + 1)
        receipts_before = list(current["runtime"]["approval_receipts"])
        with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": "proposal-owner"}):
            with self.assertRaisesRegex(
                IntentGuardianError,
                "base material world has changed",
            ):
                decide_proposal_as_agent(
                    self.contract_path,
                    digest,
                    rationale="该决定必须因真实 material drift 被拒绝",
                    evidence=["allowed write 已经启动并完成"],
                    provider="codex",
                    session_id="proposal-owner",
                )
        self.assertEqual(
            load_contract(self.contract_path)["runtime"]["approval_receipts"],
            receipts_before,
        )

    def test_apply_write_failure_cannot_persist_lane_without_revision(self) -> None:
        proposal, digest = self._proposal()
        with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": "proposal-owner"}):
            decide_proposal_as_agent(
                self.contract_path,
                digest,
                rationale="批准严格绑定的本地确定性修复",
                evidence=["provider/session/task epoch/digest 均明确"],
                provider="codex",
                session_id="proposal-owner",
            )
        before = self.contract_path.read_bytes()
        with mock.patch.object(
            guardian_recovery,
            "_write_contract_unlocked",
            side_effect=OSError("injected apply write failure"),
        ):
            with self.assertRaisesRegex(OSError, "injected apply write failure"):
                apply_revision_proposal(self.contract_path, proposal)
        self.assertEqual(self.contract_path.read_bytes(), before)

        current = load_contract(self.contract_path)
        self.assertEqual(current["revision"], 1)
        self.assertEqual(
            task_lane(
                current,
                provider="codex",
                session_id="proposal-owner",
            )["proposal_digest"],
            "",
        )
        applied = apply_revision_proposal(self.contract_path, proposal)
        self.assertEqual(applied["revision"], 2)
        self.assertEqual(
            task_lane(
                applied,
                provider="codex",
                session_id="proposal-owner",
            )["proposal_digest"],
            digest,
        )

    def test_unmatched_allowed_completion_advances_fail_closed_once(self) -> None:
        before = load_contract(self.contract_path)["runtime"]["material_sequence"]
        completed = self._write_event(
            session_id="proposal-owner",
            phase="completed",
            call_id="missing-start",
            success=True,
        )
        decision = GuardianSession(self.contract_path, provider="codex").observe(
            completed
        )
        self.assertEqual(decision.action, "allow")
        self.assertEqual(
            load_contract(self.contract_path)["runtime"]["material_sequence"],
            before + 1,
        )

    def test_codex_cli_missing_or_mismatched_session_fails_before_authority(self) -> None:
        _proposal, digest = self._proposal()
        contract_before = self.contract_path.read_bytes()
        base = [
            sys.executable,
            str(SCRIPT_DIR / "intent-guardian.py"),
            "agent-decide-proposal",
            digest,
            "--contract",
            str(self.contract_path),
            "--provider",
            "codex",
            "--rationale",
            "必须绑定真实宿主会话",
            "--evidence",
            "authority 前置校验",
        ]
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["CODEX_THREAD_ID"] = "actual-codex-session"

        missing = subprocess.run(
            base,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=environment,
        )
        self.assertEqual(missing.returncode, 2)
        self.assertIn("--session-id", missing.stderr)
        self.assertEqual(self.contract_path.read_bytes(), contract_before)

        mismatched = subprocess.run(
            [*base, "--session-id", "different-session"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=environment,
        )
        self.assertEqual(mismatched.returncode, 2)
        self.assertIn("does not match CODEX_THREAD_ID", mismatched.stderr)
        self.assertEqual(self.contract_path.read_bytes(), contract_before)
        self.assertEqual(
            load_contract(self.contract_path)["runtime"]["approval_receipts"],
            [],
        )

    def test_exact_codex_agent_control_path_does_not_create_broad_allow(self) -> None:
        exact = ".codex-agent/guardian-program/task-report.json"
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "proposal-owner",
                "cwd": str(self.root),
                "tool_name": "Write",
                "tool_input": {"file_path": exact, "content": "{}\n"},
            },
            phase="started",
            provider="codex",
        )

        contract = load_contract(self.contract_path)
        contract["constraints"]["allowed_paths"] = [exact]
        self.assertEqual(evaluate_event(contract, event).action, "allow")

        for broad in (".", ".codex-agent", ".codex-agent/**"):
            with self.subTest(broad=broad):
                candidate = json.loads(json.dumps(contract))
                candidate["constraints"]["allowed_paths"] = [broad]
                self.assertEqual(evaluate_event(candidate, event).action, "deny")

        git_event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "proposal-owner",
                "cwd": str(self.root),
                "tool_name": "Write",
                "tool_input": {"file_path": ".git/config", "content": "unsafe"},
            },
            phase="started",
            provider="codex",
        )
        contract["constraints"]["allowed_paths"] = [".git/config"]
        self.assertEqual(evaluate_event(contract, git_event).action, "deny")

        directory = ".codex-agent/guardian-program"
        mkdir_event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "proposal-owner",
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": f"mkdir -p {directory}"},
            },
            phase="started",
            provider="codex",
        )
        contract["constraints"]["allowed_paths"] = [directory]
        self.assertEqual(evaluate_event(contract, mkdir_event).action, "allow")
        contract["constraints"]["allowed_paths"] = [".codex-agent"]
        self.assertEqual(evaluate_event(contract, mkdir_event).action, "deny")

    def test_codex_proposal_cli_forwards_resolved_provider_to_t21_producer(
        self,
    ) -> None:
        tree = ast.parse(
            (SCRIPT_DIR / "intent-guardian.py").read_text(encoding="utf-8")
        )
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "create_revision_proposal"
        ]
        self.assertEqual(len(calls), 2)
        for call in calls:
            provider = next(
                (keyword.value for keyword in call.keywords if keyword.arg == "provider"),
                None,
            )
            self.assertIsInstance(provider, ast.Name)
            self.assertEqual(provider.id, "selected_provider")

    def test_task_lane_reuses_exact_epoch_and_validates_proposal_digest(self) -> None:
        digest = "a" * 64
        contract = {
            "task_epoch": "exact-task-epoch-without-local-truncation",
            "proposal_digest": digest,
            "runtime": {"task_lanes": []},
        }
        row = upsert_task_lane(
            contract,
            provider="codex",
            session_id="thread",
            state="bound",
            source="approved_revision",
        )
        self.assertEqual(row["task_epoch"], contract["task_epoch"])
        self.assertEqual(row["proposal_digest"], digest)
        normalized = normalize_task_lanes(
            contract["runtime"]["task_lanes"],
            default_epoch=contract["task_epoch"],
        )
        self.assertEqual(normalized[0]["task_epoch"], contract["task_epoch"])
        self.assertEqual(normalized[0]["proposal_digest"], digest)

        contract["runtime"]["task_lanes"] = []
        contract["proposal_digest"] = "not-a-digest"
        with self.assertRaisesRegex(TaskOwnershipError, "proposal_digest"):
            upsert_task_lane(
                contract,
                provider="codex",
                session_id="thread",
                state="bound",
                source="approved_revision",
            )


if __name__ == "__main__":
    unittest.main()
