from __future__ import annotations

import argparse
from datetime import datetime, timezone
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
SCRIPT = ROOT / "scripts" / "kb" / "self-repair.py"
HEARTBEAT = ROOT / "scripts" / "kb" / "heartbeat.py"
sys.path.insert(0, str(ROOT / "scripts" / "kb"))
from intent_guardian import (  # noqa: E402
    default_contract,
    load_contract,
    resolve_effect_intervention,
    write_contract,
)
from intervention import (  # noqa: E402
    begin_attempt,
    blocking_attempts,
    canonical_resource_key,
    effect_operation_fingerprint,
    load_archived_projection,
    load_projection,
    mark_attempt_unknown,
    readiness_blocking_attempts,
    resolve_intervention,
)


def typed_uri_effect(*, target: str, capability: str, fingerprint: str) -> dict:
    resource_key = canonical_resource_key(target, kind="uri")
    return {
        "resource_key": resource_key,
        "operation_arguments_digest": fingerprint,
        "operation_fingerprint": effect_operation_fingerprint(
            provider="codex",
            capability=capability,
            target=target,
            resource_key=resource_key,
            effect="external_write",
            arguments_digest=fingerprint,
        ),
    }


def load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


VALID_BRIEF = """# WP test task

## 目标
修复被登记的缺陷。

## 范围
涉及路径：scripts/kb/example.py
禁止改动：破坏性操作；knowledge/；阈值实改；未经批准发射委托。

## 已知上下文
先读一手证据。

## 完成标准
1. 测试全绿。

## 体量与熔断
修错三次停止。

**汇报硬性要求：必须五段标题（## 结果／## 过程／## 遇到的问题／## 解决方式／
## 遗留风险与建议），完成标准逐条给出命令、exit code 与输出摘要。**
"""


class SelfRepairTests(unittest.TestCase):
    def test_launch_detached_uses_posix_session_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            process = mock.Mock(pid=123)
            with mock.patch.object(self.module.subprocess, "Popen", return_value=process) as popen:
                launched, _ = self.module.launch_detached(
                    ["provider"], directory, directory / "agent.log"
                )
        self.assertTrue(launched)
        if os.name == "nt":
            self.assertIn("creationflags", popen.call_args.kwargs)
            self.assertNotIn("start_new_session", popen.call_args.kwargs)
        else:
            self.assertTrue(popen.call_args.kwargs["start_new_session"])
            self.assertNotIn("creationflags", popen.call_args.kwargs)

    def test_launch_detached_windows_branch_avoids_posix_only_option(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            process = mock.Mock(pid=456)
            with (
                mock.patch.object(self.module.os, "name", "nt"),
                mock.patch.object(self.module.subprocess, "Popen", return_value=process) as popen,
            ):
                launched, _ = self.module.launch_detached(
                    ["provider"], directory, directory / "agent.log"
                )
        self.assertTrue(launched)
        self.assertIn("creationflags", popen.call_args.kwargs)
        self.assertNotIn("start_new_session", popen.call_args.kwargs)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "kb-home"
        (self.home / "governance").mkdir(parents=True)
        self.module = load_script(SCRIPT, f"self_repair_test_{id(self)}")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_pending(self, rows: list[dict[str, object]]) -> None:
        directory = self.home / "self-repair"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "pending.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")

    def write_approvals(self, *slugs: str) -> None:
        directory = self.home / "self-repair"
        directory.mkdir(parents=True, exist_ok=True)
        content = "".join(
            json.dumps({"slug": slug, "decision": "approve", "by": "human", "at": "2026-08-10T00:00:00Z"}) + "\n"
            for slug in slugs
        )
        (directory / "approvals.jsonl").write_text(content, encoding="utf-8")

    def init_git_project(self) -> Path:
        project = self.root / "project"
        project.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, capture_output=True)
        (project / "tracked.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=project, check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "base"],
            cwd=project,
            check=True,
            capture_output=True,
        )
        return project

    def test_draft_creates_brief_and_pending_entry_with_mock_llm(self) -> None:
        report = self.home / "governance" / "report-20260810.md"
        report.write_text(
            "## 红绿灯表\n\n| mem_adoption_rate | 16.7% | 🔴 |\n\n## 红队质疑\n\n待审提案 P-20：修复展示。\n",
            encoding="utf-8",
        )
        template = self.root / "BRIEF-TEMPLATE.md"
        template.write_text("template", encoding="utf-8")
        args = argparse.Namespace(dry_run=False, llm_cmd="mock-llm")
        with (
            mock.patch.object(self.module, "BRIEF_TEMPLATE", template),
            mock.patch.object(self.module, "run_command_template", return_value=VALID_BRIEF) as llm,
            mock.patch.object(self.module, "notify") as notification,
        ):
            self.assertEqual(self.module.draft(self.home, args), 0)

        rows = json.loads((self.home / "self-repair" / "pending.json").read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "pending")
        self.assertEqual(rows[0]["severity"], "red")
        self.assertTrue(Path(rows[0]["brief_path"]).is_file())
        self.assertEqual(llm.call_count, 1)
        notification.assert_called_once_with("已起草 1 份修复提案待批")

    def test_clean_brief_removes_meta_prefix_and_trailing_question(self) -> None:
        raw = f"""以下是任务书，只起草，未执行任何修复。

---

{VALID_BRIEF.rstrip()}

要我把这份任务书写入指定目录吗？
"""
        cleaned = self.module.clean_brief(raw)
        self.assertEqual(cleaned, VALID_BRIEF)
        self.assertTrue(cleaned.startswith("# WP test task\n"))
        self.assertNotIn("以下是任务书", cleaned)
        self.assertNotIn("要我把", cleaned)

    def test_invalid_cleaned_draft_records_error_without_brief(self) -> None:
        report = self.home / "governance" / "report-20260810.md"
        report.write_text("| mem_adoption_rate | 16.7% | 🔴 |\n", encoding="utf-8")
        template = self.root / "BRIEF-TEMPLATE.md"
        template.write_text("template", encoding="utf-8")
        args = argparse.Namespace(dry_run=False, llm_cmd="mock-llm")
        invalid = "以下是任务书，只起草。\n\n## 目标\n残缺正文。\n\n要我写入吗？\n"

        with (
            mock.patch.object(self.module, "BRIEF_TEMPLATE", template),
            mock.patch.object(self.module, "run_command_template", return_value=invalid),
            mock.patch.object(self.module, "notify") as notification,
        ):
            self.assertEqual(self.module.draft(self.home, args), 1)

        rows = json.loads((self.home / "self-repair" / "pending.json").read_text(encoding="utf-8"))
        self.assertEqual(rows[0]["status"], "draft_error")
        self.assertIn("level-1 heading", rows[0]["failure_reason"])
        self.assertFalse((self.home / "self-repair" / "drafts").exists())
        notification.assert_called_once()

    def test_approve_refuses_automatic_environment(self) -> None:
        self.write_pending([{"slug": "repair-one", "status": "pending"}])
        environment = os.environ.copy()
        environment["SULDE_KB_HOME"] = str(self.home)
        environment["SULDE_SELF_REPAIR_AUTO"] = "heartbeat"
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--approve", "repair-one"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("approval gate refused", completed.stderr)
        rows = json.loads((self.home / "self-repair" / "pending.json").read_text(encoding="utf-8"))
        self.assertEqual(rows[0]["status"], "pending")
        self.assertFalse((self.home / "self-repair" / "approvals.jsonl").exists())

    def test_diagnostic_approval_persists_explicit_task_type(self) -> None:
        self.write_pending([{"slug": "diag-one", "status": "pending"}])
        self.assertEqual(self.module.decide(self.home, "diag-one", "approve", None, "diagnostic"), 0)
        row = json.loads((self.home / "self-repair" / "pending.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(row["task_type"], "diagnostic")

    def test_reviewed_diagnostic_with_evidence_gap_is_not_repair_success(self) -> None:
        worktree = self.root / "worktree"
        report_dir = worktree / ".codex-agent"
        report_dir.mkdir(parents=True)
        report = """## 结果
核心结论成立，但部分逐条归因证据不足。
## 过程
读取一手记录。
## 遇到的问题
部分证据不可得。
## 解决方式
列出观测补强提案。
## 遗留风险与建议
补齐打点后复测。
"""
        (report_dir / "diag-one.last.md").write_text(report, encoding="utf-8")
        self.write_pending([{
            "slug": "diag-one", "status": "failed", "task_type": "diagnostic",
            "worktree": str(worktree),
        }])
        self.assertEqual(
            self.module.record_diagnostic_outcome(
                self.home, "diag-one", "conclusive_with_gaps", "核心结论有证据，逐条归因缺观测",
            ),
            0,
        )
        row = json.loads((self.home / "self-repair" / "pending.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(row["status"], "diagnosed")
        self.assertEqual(row["diagnostic_outcome"], "conclusive_with_gaps")
        self.assertNotEqual(row["status"], "executed")

    def test_implementation_cannot_be_reclassified_as_diagnostic(self) -> None:
        self.write_pending([{"slug": "fix-one", "status": "failed", "task_type": "implementation"}])
        with self.assertRaisesRegex(self.module.SelfRepairError, "not diagnostic"):
            self.module.record_diagnostic_outcome(self.home, "fix-one", "inconclusive", "missing evidence")

    def test_execute_only_processes_approved(self) -> None:
        project = self.root / "project"
        (project / ".codex-agent").mkdir(parents=True)
        approved_brief = self.root / "approved.md"
        approved_brief.write_text(VALID_BRIEF, encoding="utf-8")
        rows = [
            {"slug": "approved-one", "status": "approved", "brief_path": str(approved_brief)},
            {"slug": "unproven-one", "status": "approved", "brief_path": str(approved_brief)},
            {"slug": "pending-one", "status": "pending", "brief_path": str(approved_brief)},
            {"slug": "rejected-one", "status": "rejected", "brief_path": str(approved_brief)},
        ]
        self.write_pending(rows)
        self.write_approvals("approved-one")
        args = argparse.Namespace(effort="high", status_timeout=1, poll_interval=0.01)
        calls: list[tuple[list[str], Path]] = []

        def successful(command: list[str], cwd: Path) -> tuple[bool, str]:
            calls.append((command, cwd))
            return True, "exit=0 PASS"

        def create(_root: Path, worktree: Path, _branch: str) -> None:
            (worktree / ".codex-agent").mkdir(parents=True)

        with (
            mock.patch.object(self.module, "project_root", return_value=project),
            mock.patch.object(self.module, "agent_scripts", return_value=self.root / "agent"),
            mock.patch.object(self.module, "ensure_worktree_available"),
            mock.patch.object(self.module, "create_worktree", side_effect=create),
            mock.patch.object(self.module, "launch_detached", return_value=(True, "pid=1")),
            mock.patch.object(self.module, "command_ok", side_effect=successful),
            mock.patch.object(self.module, "wait_for_status", return_value=("success", "status=success rc=0")),
            mock.patch.object(self.module, "notify"),
        ):
            self.assertEqual(self.module.execute(self.home, args), 0)

        updated = json.loads((self.home / "self-repair" / "pending.json").read_text(encoding="utf-8"))
        self.assertEqual([row["status"] for row in updated], ["executed", "approved", "pending", "rejected"])
        worktree = project / ".worktrees" / "self-repair-approved-one"
        self.assertEqual(updated[0]["worktree"], str(worktree))
        self.assertEqual(updated[0]["branch"], "self-repair/approved-one")
        self.assertEqual(updated[0]["verify_scope"], "worktree")
        self.assertEqual(updated[0]["verify_root"], str(worktree))
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(cwd == worktree for _command, cwd in calls))
        self.assertEqual(calls[0][0][2], "verify")
        self.assertEqual(calls[0][0][3], str(worktree))
        self.assertEqual(calls[2][0][1], str(worktree / "scripts" / "kb" / "mem-golden.py"))
        self.assertRegex(updated[0]["verification_sha256"], r"^[0-9a-f]{64}$")
        closure = self.module.project_queue(updated)
        executed_item = next(
            item for item in closure["items"]
            if "executed" in item["source_statuses"]
        )
        self.assertEqual(executed_item["status"], "verified")
        experiences = [
            json.loads(line)
            for line in (self.home / "experience" / "agent.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(experiences), 1)
        self.assertEqual(experiences[0]["outcome"], "verified")
        self.assertEqual(experiences[0]["problem_type"], "none")
        self.assertNotIn(str(worktree), json.dumps(experiences[0], ensure_ascii=False))

    def test_execute_failure_marks_failed_without_second_attempt(self) -> None:
        project = self.root / "project"
        (project / ".codex-agent").mkdir(parents=True)
        brief = self.root / "failed.md"
        brief.write_text(VALID_BRIEF, encoding="utf-8")
        self.write_pending([{"slug": "failed-one", "status": "approved", "brief_path": str(brief)}])
        self.write_approvals("failed-one")
        args = argparse.Namespace(effort="high", status_timeout=1, poll_interval=0.01)
        outcomes = iter(((True, "exit=0 verify"), (False, "exit=1 pytest failed")))
        command = mock.Mock(side_effect=lambda arguments, cwd: next(outcomes))

        def create(_root: Path, worktree: Path, _branch: str) -> None:
            (worktree / ".codex-agent").mkdir(parents=True)

        with (
            mock.patch.object(self.module, "project_root", return_value=project),
            mock.patch.object(self.module, "agent_scripts", return_value=self.root / "agent"),
            mock.patch.object(self.module, "ensure_worktree_available"),
            mock.patch.object(self.module, "create_worktree", side_effect=create),
            mock.patch.object(self.module, "launch_detached", return_value=(True, "pid=1")),
            mock.patch.object(self.module, "command_ok", command),
            mock.patch.object(self.module, "wait_for_status", return_value=("success", "status=success rc=0")),
            mock.patch.object(self.module, "notify"),
        ):
            self.assertEqual(self.module.execute(self.home, args), 1)

        row = json.loads((self.home / "self-repair" / "pending.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(row["verify_scope"], "worktree")
        self.assertEqual(command.call_count, 2)
        self.assertTrue(Path(row["worktree"]).is_dir())
        failure = json.loads((self.home / "self-repair" / "executed.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(failure["verify_scope"], "worktree")
        experience = json.loads(
            (self.home / "experience" / "agent.jsonl").read_text(encoding="utf-8")
        )
        self.assertEqual(experience["outcome"], "unresolved")
        self.assertEqual(experience["problem_type"], "managed_execution_failure")
        self.assertNotIn("pytest failed", json.dumps(experience["evidence"]))

    def test_guardian_resume_relaunches_and_cannot_read_stale_paused_status(self) -> None:
        project = self.root / "project"
        worktree = project / ".worktrees" / "self-repair-guarded"
        state = worktree / ".codex-agent"
        state.mkdir(parents=True)
        brief = self.root / "guarded.md"
        brief.write_text(VALID_BRIEF, encoding="utf-8")
        stale = state / "guarded.status"
        stale.write_text("status=paused rc=-15\n", encoding="utf-8")
        row = {
            "slug": "guarded",
            "status": "approved",
            "brief_path": str(brief),
            "guardian_resume": True,
        }
        self.write_pending([row])
        args = argparse.Namespace(
            effort="high", guardian_mode="enforce", status_timeout=1, poll_interval=0.01
        )

        def assert_fresh_status(path: Path, _timeout: float, _interval: float) -> tuple[str, str]:
            self.assertEqual(path, stale)
            self.assertFalse(path.exists())
            self.assertTrue((state / "guarded.resume1.status").is_file())
            return "success", "status=success rc=0"

        with (
            mock.patch.object(self.module, "project_root", return_value=project),
            mock.patch.object(self.module, "agent_scripts", return_value=self.root / "agent"),
            mock.patch.object(self.module, "launch_detached", return_value=(True, "pid=2")) as launch,
            mock.patch.object(self.module, "wait_for_status", side_effect=assert_fresh_status),
            mock.patch.object(self.module, "command_ok", return_value=(True, "exit=0 PASS")),
            mock.patch.object(self.module, "notify"),
        ):
            self.assertEqual(self.module.execute_one(self.home, row, args), "success")

        launch.assert_called_once()
        self.assertIn("--guardian-mode", launch.call_args.args[0])

    def test_guardian_resume_targets_the_managed_paused_lane(self) -> None:
        worktree = self.root / "project/.worktrees/self-repair-lane-pause"
        state = worktree / ".codex-agent"
        state.mkdir(parents=True)
        contract_path = state / "lane-pause.intent.json"
        contract = default_contract(
            intent_id="l3:lane-pause",
            objective="resume one managed lane",
            acceptance_criteria=["other lanes remain independent"],
            workspace=worktree,
            mode="enforce",
            confirmed_by="human-l3-approval",
        )
        epoch = contract["task_epoch"]
        contract["status"] = "paused"
        contract["runtime"].update(
            {
                "pause_scope": "lane",
                "pause_reason": "managed correction",
                "pause_class": "semantic",
                "pause_requires_revision": False,
                "pause_revision": 1,
                "task_lanes": [
                    {
                        "provider": "codex",
                        "session_id": "managed:l3:lane-pause",
                        "task_epoch": epoch,
                        "state": "paused",
                        "source": "managed_correction",
                        "pause_reason": "managed correction",
                        "pause_class": "semantic",
                        "pause_requires_revision": False,
                        "pause_revision": 1,
                    }
                ],
            }
        )
        write_contract(contract_path, contract)
        self.write_pending(
            [
                {
                    "slug": "lane-pause",
                    "status": "paused",
                    "worktree": str(worktree),
                }
            ]
        )

        self.assertEqual(
            self.module.resume_guarded(self.home, "lane-pause", "review complete"),
            0,
        )
        resumed = load_contract(contract_path)
        self.assertEqual(resumed["status"], "active")
        self.assertEqual(resumed["task_epoch"], epoch)
        self.assertEqual(resumed["runtime"]["task_lanes"][0]["state"], "bound")
        pending = json.loads(
            (self.home / "self-repair/pending.json").read_text(encoding="utf-8")
        )
        self.assertEqual(pending[0]["status"], "approved")

    def test_unknown_effect_waits_for_human_and_resumes_only_after_adjudication(self) -> None:
        project = self.root / "project"
        worktree = project / ".worktrees" / "self-repair-effect-unknown"
        state = worktree / ".codex-agent"
        state.mkdir(parents=True)
        contract_path = state / "effect-unknown.intent.json"
        write_contract(
            contract_path,
            default_contract(
                intent_id="l3:effect-unknown",
                objective="test durable intervention resume",
                acceptance_criteria=["unknown remains blocked until human adjudication"],
                workspace=worktree,
                mode="enforce",
                confirmed_by="human-l3-approval",
            ),
        )
        attempt = begin_attempt(
            contract_path,
            intent_id="l3:effect-unknown",
            intent_revision=1,
            fingerprint="f" * 64,
            source_event_id="remote-one",
            capability="mcp:docs:update_document",
            target="doc://one",
            effect="external_write",
            provider="codex",
            session_id="managed:l3:effect-unknown",
            task_id="l3:effect-unknown",
            idempotency_key="dispatch-one",
            **typed_uri_effect(
                target="doc://one",
                capability="mcp:docs:update_document",
                fingerprint="f" * 64,
            ),
        )
        intervention = mark_attempt_unknown(
            contract_path,
            attempt["attempt_id"],
            reason="reply was lost after dispatch",
        )
        row = {
            "slug": "effect-unknown",
            "status": "executing",
            "worktree": str(worktree),
            "attempts": 1,
        }
        self.write_pending([row])
        self.assertEqual(
            self.module.mark_awaiting_human(self.home, row, "status=awaiting_human"),
            "awaiting_human",
        )
        with self.assertRaisesRegex(self.module.SelfRepairError, "resolve every intervention"):
            self.module.resume_guarded(self.home, "effect-unknown", "inspect first")
        resolve_effect_intervention(
            contract_path,
            intervention["intervention_id"],
            decision="retry_authorized",
            evidence="remote lookup proves the original write is absent",
        )
        self.assertEqual(
            self.module.resume_guarded(self.home, "effect-unknown", "retry once"),
            0,
        )
        updated = json.loads(
            (self.home / "self-repair/pending.json").read_text(encoding="utf-8")
        )[0]
        self.assertEqual(updated["status"], "approved")
        context = json.loads(Path(updated["resume_context"]).read_text(encoding="utf-8"))
        self.assertEqual(context["interventions"][0]["decision"], "retry_authorized")
        self.assertEqual(context["interventions"][0]["attempt_id"], attempt["attempt_id"])
        self.assertNotIn("target", context["interventions"][0])
        self.assertEqual(context["interventions"][0]["provider"], "codex")
        self.assertEqual(context["interventions"][0]["target_sha256"], attempt["target_sha256"])
        self.assertEqual(
            updated["resume_context_sha256"],
            hashlib.sha256(Path(updated["resume_context"]).read_bytes()).hexdigest(),
        )
        self.assertTrue(updated["intervention_resume"])

    def test_execute_ignores_dirty_main_workspace(self) -> None:
        project = self.init_git_project()
        (project / "tracked.txt").write_text("uncommitted human work\n", encoding="utf-8")
        brief = self.root / "dirty-main.md"
        brief.write_text(VALID_BRIEF, encoding="utf-8")
        self.write_pending([{"slug": "dirty-main", "status": "approved", "brief_path": str(brief)}])
        self.write_approvals("dirty-main")
        args = argparse.Namespace(effort="high", status_timeout=1, poll_interval=0.01, dry_run=False)
        worktree = project / ".worktrees" / "self-repair-dirty-main"

        calls: list[tuple[list[str], Path, str]] = []

        def scoped_command(command: list[str], cwd: Path) -> tuple[bool, str]:
            status = subprocess.run(
                ["git", "status", "--short"],
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).stdout
            output = f"=== 本轮改动 ===\n{status or '（无改动）'}"
            calls.append((command, cwd, output))
            return True, output

        with (
            mock.patch.object(self.module, "project_root", return_value=project),
            mock.patch.object(self.module, "agent_scripts", return_value=self.root / "agent"),
            mock.patch.object(self.module, "launch_detached", return_value=(True, "pid=1")),
            mock.patch.object(self.module, "command_ok", side_effect=scoped_command),
            mock.patch.object(
                self.module,
                "wait_for_status",
                return_value=("success", "status=success rc=0"),
            ) as wait,
            mock.patch.object(self.module, "notify"),
        ):
            self.assertEqual(self.module.execute(self.home, args), 0)

        self.assertTrue(worktree.is_dir())
        self.assertTrue(all(cwd == worktree for _command, cwd, _output in calls))
        verify = calls[0]
        self.assertEqual(verify[0][2], "verify")
        self.assertEqual(verify[0][3], str(worktree))
        self.assertEqual(verify[1], worktree)
        self.assertNotIn("tracked.txt", verify[2])
        wait.assert_called_once_with(worktree / ".codex-agent" / "dirty-main.status", 1, 0.01)
        self.assertEqual((project / "tracked.txt").read_text(encoding="utf-8"), "uncommitted human work\n")
        self.assertEqual((worktree / "tracked.txt").read_text(encoding="utf-8"), "base\n")

    def test_existing_worktree_or_branch_refuses_before_launch(self) -> None:
        project = self.init_git_project()
        brief = self.root / "collision.md"
        brief.write_text(VALID_BRIEF, encoding="utf-8")
        self.write_pending([{"slug": "collision", "status": "approved", "brief_path": str(brief)}])
        self.write_approvals("collision")
        args = argparse.Namespace(effort="high", status_timeout=1, poll_interval=0.01, dry_run=False)
        worktree, branch = self.module.worktree_identity(project, "collision")
        self.module.create_worktree(project, worktree, branch)
        with (
            mock.patch.object(self.module, "project_root", return_value=project),
            mock.patch.object(self.module, "command_ok") as command,
        ):
            with self.assertRaisesRegex(self.module.SelfRepairError, "--cleanup collision"):
                self.module.execute(self.home, args)
        command.assert_not_called()
        row = json.loads((self.home / "self-repair" / "pending.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(row["status"], "approved")

    def test_cleanup_removes_clean_worktree_and_branch(self) -> None:
        project = self.init_git_project()
        worktree, branch = self.module.worktree_identity(project, "clean")
        self.module.create_worktree(project, worktree, branch)
        with mock.patch.object(self.module, "project_root", return_value=project):
            self.assertEqual(self.module.cleanup("clean", False, self.home), 0)
        self.assertFalse(worktree.exists())
        self.assertFalse(self.module.branch_exists(project, branch))

    def test_cleanup_archives_resolved_intervention_truth_before_removal(self) -> None:
        project = self.init_git_project()
        worktree, branch = self.module.worktree_identity(project, "archived")
        self.module.create_worktree(project, worktree, branch)
        contract = worktree / ".codex-agent" / "archived.intent.json"
        contract.parent.mkdir(parents=True)
        contract.write_text("{}\n", encoding="utf-8")
        attempt = begin_attempt(
            contract,
            intent_id="l3:archived",
            intent_revision=1,
            fingerprint="f" * 64,
            source_event_id="event-one",
            capability="mcp:docs:update_document",
            target="doc://one",
            effect="external_write",
            provider="codex",
            session_id="l3:archived",
            task_id="l3:archived",
            idempotency_key="dispatch-one",
            **typed_uri_effect(
                target="doc://one",
                capability="mcp:docs:update_document",
                fingerprint="f" * 64,
            ),
            verification_kind="existence",
        )
        intervention = mark_attempt_unknown(
            contract,
            attempt["attempt_id"],
            reason="completion unavailable",
        )
        resolve_intervention(
            contract,
            intervention["intervention_id"],
            decision="abort",
            evidence="operator abandoned the task without retrying the effect",
        )
        live_projection = load_projection(contract)
        self.assertEqual(
            [row["attempt_id"] for row in blocking_attempts(live_projection)],
            [attempt["attempt_id"]],
        )
        self.assertEqual(readiness_blocking_attempts(live_projection), [])

        with mock.patch.object(self.module, "project_root", return_value=project):
            self.assertEqual(self.module.cleanup("archived", True, self.home), 0)
        manifests = list((self.home / "interventions" / "archive").glob("*/manifest.json"))
        self.assertEqual(len(manifests), 1)
        projection = load_archived_projection(manifests[0])
        self.assertEqual(projection["attempts"][attempt["attempt_id"]]["state"], "unknown")
        self.assertEqual(
            [row["attempt_id"] for row in blocking_attempts(projection)],
            [attempt["attempt_id"]],
        )
        self.assertEqual(readiness_blocking_attempts(projection), [])
        self.assertFalse(worktree.exists())

    def test_cleanup_refuses_unresolved_intervention_even_with_force(self) -> None:
        project = self.init_git_project()
        worktree, branch = self.module.worktree_identity(project, "blocked")
        self.module.create_worktree(project, worktree, branch)
        contract = worktree / ".codex-agent" / "blocked.intent.json"
        contract.parent.mkdir(parents=True)
        contract.write_text("{}\n", encoding="utf-8")
        attempt = begin_attempt(
            contract,
            intent_id="l3:blocked",
            intent_revision=1,
            fingerprint="f" * 64,
            source_event_id="event-one",
            capability="mcp:docs:update_document",
            target="doc://one",
            effect="external_write",
            provider="codex",
            session_id="l3:blocked",
            task_id="l3:blocked",
            idempotency_key="dispatch-one",
            **typed_uri_effect(
                target="doc://one",
                capability="mcp:docs:update_document",
                fingerprint="f" * 64,
            ),
            verification_kind="existence",
        )
        mark_attempt_unknown(contract, attempt["attempt_id"], reason="unknown")
        with mock.patch.object(self.module, "project_root", return_value=project):
            with self.assertRaisesRegex(self.module.SelfRepairError, "truth is unresolved"):
                self.module.cleanup("blocked", True, self.home)
        self.assertTrue(worktree.exists())
        self.assertTrue(self.module.branch_exists(project, branch))

    def test_cleanup_refuses_every_nonterminal_unknown_projection(self) -> None:
        project = self.init_git_project()
        cases = {
            "unhandled": None,
            "open": {"status": "open", "decision": None},
            "acknowledged": {"status": "acknowledged", "decision": None},
            "retry-authorized": {
                "status": "resolved",
                "decision": "retry_authorized",
                "retry_consumed_by": None,
            },
            "reprobe-authorized": {
                "status": "resolved",
                "decision": "reprobe_authorized",
            },
        }
        for state, intervention_state in cases.items():
            with self.subTest(state=state):
                slug = f"blocked-{state}"
                worktree, branch = self.module.worktree_identity(project, slug)
                self.module.create_worktree(project, worktree, branch)
                contract = worktree / ".codex-agent" / f"{slug}.intent.json"
                contract.parent.mkdir(parents=True)
                contract.write_text("{}\n", encoding="utf-8")
                contract.with_name(f"{slug}.intent.interventions.jsonl").write_text(
                    "fixture\n", encoding="utf-8"
                )
                attempt_id = f"attempt-{state}"
                projection = {
                    "attempts": {
                        attempt_id: {
                            "attempt_id": attempt_id,
                            "state": "unknown",
                            "replay_authoritative": True,
                        }
                    },
                    "interventions": {},
                }
                if intervention_state is not None:
                    projection["interventions"][f"intervention-{state}"] = {
                        "attempt_id": attempt_id,
                        **intervention_state,
                    }

                self.assertEqual(
                    [row["attempt_id"] for row in blocking_attempts(projection)],
                    [attempt_id],
                )
                self.assertEqual(
                    [row["attempt_id"] for row in readiness_blocking_attempts(projection)],
                    [attempt_id],
                )
                with (
                    mock.patch.object(self.module, "project_root", return_value=project),
                    mock.patch.object(
                        self.module,
                        "load_intervention_projection",
                        return_value=projection,
                    ),
                    mock.patch.object(self.module, "archive_intervention_store") as archive,
                ):
                    with self.assertRaisesRegex(
                        self.module.SelfRepairError, "truth is unresolved"
                    ):
                        self.module.cleanup(slug, True, self.home)
                archive.assert_not_called()
                self.assertTrue(worktree.exists())
                self.assertTrue(self.module.branch_exists(project, branch))

    def test_cleanup_refuses_unmerged_branch_without_force(self) -> None:
        project = self.init_git_project()
        worktree, branch = self.module.worktree_identity(project, "unmerged")
        self.module.create_worktree(project, worktree, branch)
        (worktree / "repair.txt").write_text("repair\n", encoding="utf-8")
        subprocess.run(["git", "add", "repair.txt"], cwd=worktree, check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "repair"],
            cwd=worktree,
            check=True,
            capture_output=True,
        )
        with mock.patch.object(self.module, "project_root", return_value=project):
            with self.assertRaisesRegex(self.module.SelfRepairError, "not merged into main"):
                self.module.cleanup("unmerged", False, self.home)
            self.assertEqual(self.module.cleanup("unmerged", True, self.home), 0)
        self.assertFalse(worktree.exists())
        self.assertFalse(self.module.branch_exists(project, branch))

    def test_source_has_no_commit_or_push_invocation(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIsNone(__import__("re").search(r"git\s+(?:commit|push)\b", source, __import__("re").IGNORECASE))

    def test_execute_is_not_scheduled_in_plist(self) -> None:
        plist = (ROOT / "templates" / "launchagents" / "com.sulde.self-repair.plist").read_text(encoding="utf-8")
        self.assertNotIn("--execute", plist)

    def test_execute_falls_back_to_unittest_when_pytest_is_unavailable(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"unittest", "discover", "-s", "tests"', source)
        self.assertIn('find_spec("pytest")', source)

    def test_human_can_resolve_failed_entry_with_external_evidence(self) -> None:
        self.write_pending([{"slug": "fixed-elsewhere", "status": "failed"}])
        self.assertEqual(self.module.record_resolution(self.home, "fixed-elsewhere", "commit abc; tests pass"), 0)
        row = json.loads((self.home / "self-repair/pending.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(row["status"], "resolved")
        self.assertEqual(row["resolution_evidence"], "commit abc; tests pass")

    def test_human_can_resolve_approved_entry_completed_on_mainline(self) -> None:
        self.write_pending([{"slug": "approved-mainline", "status": "approved"}])
        self.assertEqual(
            self.module.record_resolution(
                self.home,
                "approved-mainline",
                "commit def merged; acceptance checks pass",
            ),
            0,
        )
        row = json.loads((self.home / "self-repair/pending.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(row["status"], "resolved")
        self.assertEqual(row["resolution_evidence"], "commit def merged; acceptance checks pass")

    def test_heartbeat_invokes_draft_with_automatic_gate_marker(self) -> None:
        heartbeat = load_script(HEARTBEAT, f"heartbeat_test_{id(self)}")
        completed = subprocess.CompletedProcess([], 0, stdout="SELF-REPAIR DRAFT: PASS drafted=0", stderr="")
        with mock.patch.object(heartbeat.subprocess, "run", return_value=completed) as run:
            heartbeat.draft_self_repair("mock llm")
        arguments = run.call_args.args[0]
        environment = run.call_args.kwargs["env"]
        self.assertIn("--draft", arguments)
        self.assertNotIn("--execute", arguments)
        self.assertEqual(environment["SULDE_SELF_REPAIR_AUTO"], "heartbeat")

    def test_heartbeat_refreshes_l2_registry_without_execution_flags(self) -> None:
        heartbeat = load_script(HEARTBEAT, f"heartbeat_l2_registry_test_{id(self)}")
        completed = subprocess.CompletedProcess([], 0, stdout="L2 REGISTRY: READY", stderr="")
        with mock.patch.object(heartbeat.subprocess, "run", return_value=completed) as run:
            heartbeat.refresh_l2_registry()
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[-1], "--refresh")
        self.assertNotIn("--execute", arguments)

    def test_heartbeat_runs_lifecycle_without_execution_flags(self) -> None:
        heartbeat = load_script(HEARTBEAT, f"heartbeat_lifecycle_test_{id(self)}")
        completed = subprocess.CompletedProcess([], 0, stdout="LIFE CYCLE: READY", stderr="")
        with mock.patch.object(heartbeat.subprocess, "run", return_value=completed) as run:
            heartbeat.run_life_cycle()
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[-1], "--run")
        self.assertNotIn("--execute", arguments)


    def test_queue_projection_aggregates_fingerprint_only_inside_exact_scope(self) -> None:
        fingerprint = "a" * 64
        base = {
            "fingerprint": fingerprint,
            "source": "governance:red",
            "status": "pending",
            "project_id": "project-one",
            "session_id": "session-one",
            "task_instance_id": "lane-one",
        }
        rows = [
            {**base, "slug": "first", "drafted_at": "2026-09-01T00:00:00Z"},
            {**base, "slug": "again", "drafted_at": "2026-09-02T00:00:00Z"},
            {
                **base,
                "slug": "other-session",
                "session_id": "session-two",
                "drafted_at": "2026-09-03T00:00:00Z",
            },
        ]

        projection = self.module.project_queue(
            rows, current=datetime(2026, 9, 4, tzinfo=timezone.utc)
        )

        self.assertEqual(projection["schema"], "sulde-self-repair-queue-v2")
        self.assertEqual(projection["total"], 2)
        recurrences = sorted(item["recurrence_count"] for item in projection["items"])
        self.assertEqual(recurrences, [1, 2])
        scopes = {item["scope"]["session_id"] for item in projection["items"]}
        self.assertEqual(scopes, {"session-one", "session-two"})

    def test_queue_latest_state_uses_most_recent_observation_not_first_seen(self) -> None:
        projection = self.module.project_queue(
            [
                {
                    "slug": "recurring",
                    "fingerprint": "f" * 64,
                    "status": "resolved",
                    "resolution_evidence": "read-back verified",
                    "first_seen_at": "2026-09-01T00:00:00Z",
                    "last_seen_at": "2026-09-04T00:00:00Z",
                },
                {
                    "slug": "recurring",
                    "fingerprint": "f" * 64,
                    "status": "pending",
                    "first_seen_at": "2026-09-02T00:00:00Z",
                    "last_seen_at": "2026-09-03T00:00:00Z",
                },
            ],
            current=datetime(2026, 9, 4, tzinfo=timezone.utc),
        )

        item = projection["items"][0]
        self.assertEqual(item["status"], "verified")
        self.assertEqual(item["first_seen_at"], "2026-09-01T00:00:00Z")
        self.assertEqual(item["last_seen_at"], "2026-09-04T00:00:00Z")
        self.assertEqual(item["recurrence_count"], 2)

    def test_queue_expiry_and_retry_never_settle_authority_debt(self) -> None:
        current = datetime(2026, 9, 4, tzinfo=timezone.utc)
        projection = self.module.project_queue(
            [
                {
                    "slug": "old-safe",
                    "source": "one",
                    "status": "pending",
                    "drafted_at": "2026-07-01T00:00:00Z",
                },
                {
                    "slug": "old-unknown",
                    "source": "two",
                    "status": "resolved",
                    "resolution_evidence": "claimed",
                    "effect": "external_write",
                    "pending_verifications": [{"id": "still-open"}],
                    "drafted_at": "2026-07-01T00:00:00Z",
                },
                {
                    "slug": "bounded",
                    "source": "three",
                    "status": "failed",
                    "attempts": 3,
                    "failed_at": "2026-09-03T00:00:00Z",
                },
            ],
            current=current,
        )
        items = {
            tuple(item["source_statuses"]): item for item in projection["items"]
        }
        self.assertEqual(items[("pending",)]["status"], "expired")
        self.assertEqual(items[("resolved",)]["status"], "unresolved")
        self.assertTrue(items[("resolved",)]["authority_debt"])
        self.assertFalse(items[("resolved",)]["retry_allowed"])
        self.assertEqual(items[("failed",)]["retry_remaining"], 0)
        self.assertFalse(items[("failed",)]["retry_allowed"])

    def test_queue_terminal_transition_is_idempotent_and_verified_needs_evidence(self) -> None:
        item = {"status": "inconclusive", "authority_debt": False}
        verified = self.module.transition_queue_item(
            item, "verified", evidence_sha256="b" * 64
        )
        self.assertEqual(verified["status"], "verified")
        self.assertEqual(
            self.module.transition_queue_item(
                verified, "verified", evidence_sha256="b" * 64
            ),
            verified,
        )
        with self.assertRaisesRegex(self.module.SelfRepairError, "immutable"):
            self.module.transition_queue_item(verified, "expired")
        with self.assertRaisesRegex(self.module.SelfRepairError, "requires evidence"):
            self.module.transition_queue_item(item, "verified")
        with self.assertRaisesRegex(self.module.SelfRepairError, "authority debt"):
            self.module.transition_queue_item(
                {"status": "unresolved", "authority_debt": True},
                "verified",
                evidence_sha256="c" * 64,
            )

        projected = self.module.project_queue(
            [{"slug": "claimed", "status": "verified", "closure_status": "verified"}],
            current=datetime(2026, 9, 4, tzinfo=timezone.utc),
        )
        self.assertEqual(projected["items"][0]["status"], "inconclusive")

    def test_only_formal_continuation_creates_fresh_binding_without_authority(self) -> None:
        source = {
            "slug": "same-problem",
            "source": "governance:red",
            "fingerprint": "d" * 64,
            "status": "awaiting_human",
            "grants": [{"secret": "old"}],
            "open_events": [{"id": "old"}],
            "intervention_ids": ["old"],
            "attempts": 2,
        }
        continuation = {
            "schema": "sulde-continuation-event-v1",
            "action": "loaded",
            "session_id": "new-session",
            "capsule_id": "capsule-one",
            "authority_transferred": False,
        }
        bound = self.module.continuation_queue_entry(
            source,
            project_id="project-one",
            session_id="new-session",
            task_instance_id="lane-two",
            continuation=continuation,
            observed_at="2026-09-04T00:00:00Z",
        )
        self.assertEqual(bound["status"], "pending")
        self.assertEqual(bound["attempts"], 0)
        self.assertEqual(bound["session_id"], "new-session")
        for forbidden in (
            "grants", "open_events", "intervention_ids", "pending_verifications"
        ):
            self.assertNotIn(forbidden, bound)
        with self.assertRaisesRegex(self.module.SelfRepairError, "formal"):
            self.module.continuation_queue_entry(
                source,
                project_id="project-one",
                session_id="new-session",
                task_instance_id="lane-two",
                continuation={**continuation, "authority_transferred": True},
            )

    def test_failed_retry_budget_is_bounded(self) -> None:
        self.write_pending(
            [{"slug": "budget", "status": "failed", "attempts": 3}]
        )
        previous = self.module.RETRY_FAILED
        self.module.RETRY_FAILED = True
        try:
            with self.assertRaisesRegex(self.module.SelfRepairError, "budget exhausted"):
                self.module.decide(self.home, "budget", "approve", "retry")
        finally:
            self.module.RETRY_FAILED = previous


if __name__ == "__main__":
    unittest.main()
