from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import importlib.util
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

from event_contract import (  # noqa: E402
    EventContractError,
    make_event,
    safe_attributes,
    safe_correlation,
    validate_event,
)
from event_observer import (  # noqa: E402
    EventSource,
    adapt_host_capability,
    adapt_intent,
    adapt_run_event,
    collect_snapshot,
    status_projection,
)
import event_observer as event_observer_module  # noqa: E402
from correction_intervention import (  # noqa: E402
    propose_correction,
    transition_correction,
)
from approval_invariant import ask_approval, decide_approval  # noqa: E402
from intervention import (  # noqa: E402
    archive_store,
    begin_attempt,
    canonical_resource_key,
    event_store_path,
    mark_attempt_unknown,
    projection_path,
    resolve_intervention,
)


NOW = "2026-08-14T10:00:00+08:00"


def write_jsonl(path: Path, *rows: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


class EventContractTests(unittest.TestCase):
    def test_event_id_is_deterministic_and_free_form_target_stays_hashed(self) -> None:
        row = {"at": NOW, "target": "/private/customer/resume.md", "secret": "token-123"}
        keyword = {
            "domain": "intent",
            "event_type": "intent.observation",
            "occurred_at": NOW,
            "phase": "started",
            "outcome": "allow",
            "provider": "codex",
            "actor": "codex",
            "correlation": {"intent_id": "intent-1"},
            "source_kind": "intent-audit",
            "source_name": "kb:intent/demo.events.jsonl",
            "source_line": 1,
            "raw_row": row,
            "attributes": {"target_sha256": "a" * 64, "target_present": True},
        }
        first = make_event(**keyword)
        second = make_event(**keyword)
        self.assertEqual(first["event_id"], second["event_id"])
        rendered = json.dumps(first, ensure_ascii=False)
        self.assertNotIn("/private/customer", rendered)
        self.assertNotIn("token-123", rendered)
        self.assertNotIn("intent-1", rendered)
        self.assertRegex(first["correlation"]["intent_id"], r"^sha256:[0-9a-f]{24}$")
        self.assertEqual(first["occurred_at"], "2026-08-14T02:00:00.000000Z")

    def test_sensitive_attribute_and_absolute_source_are_rejected(self) -> None:
        with self.assertRaises(EventContractError):
            safe_attributes({"prompt": "do not publish"})
        with self.assertRaises(EventContractError):
            safe_attributes({"source_event_id": "raw-provider-id"})
        with self.assertRaises(EventContractError):
            safe_attributes({"free form key": "value"})
        with self.assertRaises(EventContractError):
            make_event(
                domain="intent",
                event_type="intent.observation",
                occurred_at=NOW,
                phase="observed",
                outcome="allow",
                provider="codex",
                actor="codex",
                correlation={},
                source_kind="intent-audit",
                source_name="/Users/private/audit.jsonl",
                source_line=1,
                raw_row={"at": NOW},
            )

    def test_versioned_positive_and_negative_templates_lock_the_boundary(self) -> None:
        templates = ROOT / "templates" / "events"
        positive = json.loads(
            (templates / "positive-observation-event-v1.json").read_text(
                encoding="utf-8"
            )
        )
        negative = json.loads(
            (templates / "negative-observation-event-v1.json").read_text(
                encoding="utf-8"
            )
        )
        validate_event(positive)
        with self.assertRaises(EventContractError):
            validate_event(negative)


class EventObserverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / "kb"
        self.workspace = Path(self.temporary.name) / "workspace"
        self.home.mkdir()
        self.workspace.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_host_capability_observation_joins_read_only_lifecycle_projection(self) -> None:
        row = {
            "schema": "sulde-host-capability-observation-v1",
            "contract_version": 1,
            "at": NOW,
            "provider": "codex",
            "runtime_sha256": "c" * 64,
            "session_id": "private-native-session",
            "workspace_id": "sha256:" + "a" * 24,
            "capability_id": "prompt_control",
            "hook_event": "UserPromptSubmit",
            "source": "live_host_hook",
            "outcome": "observed",
            "event_id": "b" * 64,
        }
        write_jsonl(self.home / "host-capabilities.jsonl", row)

        snapshot = collect_snapshot(self.home)

        self.assertTrue(snapshot["summary"]["contract_healthy"])
        self.assertEqual(snapshot["summary"]["by_domain"], {"lifecycle": 1})
        event = snapshot["events"][0]
        self.assertEqual(event["type"], "lifecycle.host_capability")
        self.assertEqual(event["attributes"]["capability_name"], "prompt_control")
        self.assertEqual(event["provider"], "codex")
        rendered = json.dumps(event, ensure_ascii=False)
        self.assertNotIn("private-native-session", rendered)
        self.assertNotIn('"' + "b" * 64 + '"', rendered)

    def test_managed_run_result_and_disposal_join_execution_projection(self) -> None:
        run_id = "run-" + "a" * 24
        write_jsonl(
            self.workspace / ".codex-agent/task.run.jsonl",
            {
                "schema": "sulde-run-event-v1",
                "at": NOW,
                "run_id": run_id,
                "type": "execution.result",
                "provider": "codex",
                "returncode": 0,
                "stop_reason": "completed",
                "output_present": True,
                "output_sha256": "b" * 64,
            },
            {
                "schema": "sulde-run-event-v1",
                "at": "2026-08-14T10:00:01+08:00",
                "run_id": run_id,
                "type": "execution.disposed",
                "provider": "codex",
                "quiescent": True,
                "tree_scope": "posix-process-group",
                "error_count": 0,
                "errors_sha256": None,
            },
        )

        snapshot = collect_snapshot(self.home, workspaces=[self.workspace])

        self.assertTrue(snapshot["summary"]["contract_healthy"])
        self.assertEqual(snapshot["summary"]["by_domain"], {"execution": 2})
        self.assertEqual(
            [event["outcome"] for event in snapshot["events"]],
            ["completed", "quiescent"],
        )
        self.assertEqual(
            snapshot["events"][0]["correlation"]["run_id"],
            snapshot["events"][1]["correlation"]["run_id"],
        )
        rendered = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn(run_id, rendered)
        self.assertEqual(snapshot["events"][0]["attributes"]["output_sha256"], "b" * 64)

    def test_correction_intervention_projects_state_without_prompt_or_session(self) -> None:
        contract = self.workspace / ".codex-agent/task.intent.json"
        contract.parent.mkdir(parents=True)
        contract.write_text("{}\n", encoding="utf-8")
        item = propose_correction(
            contract,
            intent_id="private-intent",
            intent_revision=4,
            provider="codex",
            session_id="private-session",
            correction="不是这个方向，保留我的表达",
            actor="human",
            source="user_prompt",
        )
        transition_correction(
            contract,
            item["intervention_id"],
            state="applied",
            boundary="pre_tool",
            reason_code="host_reached_pre_tool",
        )

        snapshot = collect_snapshot(self.home, workspaces=[self.workspace])

        self.assertTrue(snapshot["summary"]["contract_healthy"])
        self.assertEqual(snapshot["summary"]["by_domain"], {"intent": 3})
        self.assertEqual(
            [event["outcome"] for event in snapshot["events"]],
            ["proposed", "queued", "applied"],
        )
        self.assertTrue(
            all(
                event["type"] == "intent.correction_intervention"
                for event in snapshot["events"]
            )
        )
        self.assertEqual(
            snapshot["events"][-1]["attributes"]["semantic_acceptance"],
            "unknown",
        )
        rendered = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn("不是这个方向", rendered)
        self.assertNotIn("private-session", rendered)
        self.assertNotIn("private-intent", rendered)

    def test_managed_correction_pause_audit_is_a_redacted_supported_event(self) -> None:
        write_jsonl(
            self.home / "intent/workspaces/demo.events.jsonl",
            {
                "schema": "sulde-correction-pause-v1",
                "at": NOW,
                "intent_id": "private-intent",
                "intent_revision": 3,
                "intervention_ids": ["cor-private-one"],
                "action": "pause_managed_run",
            },
        )

        snapshot = collect_snapshot(self.home)

        self.assertTrue(snapshot["summary"]["contract_healthy"])
        self.assertEqual(snapshot["summary"]["by_type"], {"intent.correction_pause": 1})
        event = snapshot["events"][0]
        self.assertEqual(event["outcome"], "paused")
        self.assertEqual(event["attributes"]["intervention_count"], 1)
        rendered = json.dumps(event, ensure_ascii=False)
        self.assertNotIn("cor-private-one", rendered)
        self.assertNotIn("private-intent", rendered)

    def test_approval_question_and_decision_join_one_private_projection_lane(self) -> None:
        contract = self.workspace / ".codex-agent/task.intent.json"
        contract.parent.mkdir(parents=True, exist_ok=True)
        contract.write_text("{}\n", encoding="utf-8")
        ask_approval(
            contract,
            intent_id="private-intent",
            intent_revision=2,
            kind="event",
            target="private-target",
            provider="codex",
            session_id="private-session",
            source="guardian_pre_action",
        )
        decide_approval(
            contract,
            kind="event",
            target="private-target",
            outcome="approved",
            provider="codex",
            session_id="private-session",
            actor="user-prompt:codex",
            receipt_id="private-receipt",
        )

        snapshot = collect_snapshot(self.home, workspaces=[self.workspace])

        self.assertEqual(snapshot["summary"]["by_domain"], {"approval": 2})
        self.assertEqual(
            [event["outcome"] for event in snapshot["events"]],
            ["asked", "approved"],
        )
        self.assertEqual(
            snapshot["events"][0]["correlation"]["session_id"],
            snapshot["events"][1]["correlation"]["session_id"],
        )
        rendered = json.dumps(snapshot, ensure_ascii=False)
        for private in (
            "private-intent",
            "private-target",
            "private-session",
            "private-receipt",
        ):
            self.assertNotIn(private, rendered)

    def test_typed_approval_observation_events_are_redacted_and_v3_stays_unsupported(self) -> None:
        approvals = self.home / "intent/workspaces/typed.approvals.jsonl"
        write_jsonl(
            approvals,
            {
                "schema": "sulde-approval-pair-event-v2",
                "type": "approval.asked",
                "at": NOW,
                "request_id": "apr-private-one",
                "intent_id_sha256": "a" * 64,
                "intent_revision": 3,
                "kind": "proposal",
                "target_sha256": "b" * 64,
                "provider": "codex",
                "lane_sha256": "c" * 64,
                "source": "codex_permission_request",
                "snapshot": {"session_id": "private-snapshot-session"},
            },
            {
                "schema": "sulde-approval-pair-event-v2",
                "type": "approval.prompt-observed",
                "at": "2026-08-14T10:00:01+08:00",
                "request_id": "apr-private-one",
                "provider": "codex",
                "lane_sha256": "c" * 64,
            },
            {
                "schema": "sulde-approval-pair-event-v2",
                "type": "approval.replaced",
                "at": "2026-08-14T10:00:02+08:00",
                "request_id": "apr-private-one",
                "replacement_request_id": "apr-private-two",
                "replacement_identity": "sha256:private-lineage",
            },
            {
                "schema": "sulde-approval-pair-event-v3",
                "type": "approval.decided",
                "at": "2026-08-14T10:00:03+08:00",
                "request_id": "apr-private-three",
                "typed_receipt": {"secret": "private-future-authority"},
            },
        )

        snapshot = collect_snapshot(self.home)

        self.assertEqual(
            [event["outcome"] for event in snapshot["events"]],
            ["asked", "observed", "replaced"],
        )
        self.assertEqual(snapshot["summary"]["unsupported_rows"], 1)
        rendered = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn("private-snapshot-session", rendered)
        self.assertNotIn("private-future-authority", rendered)

    def test_continuation_event_projects_context_without_raw_authority_or_ids(self) -> None:
        row = {
            "schema": "sulde-continuation-event-v1",
            "at": NOW,
            "action": "loaded",
            "actor": "codex",
            "provider": "codex",
            "session_id": "private-new-thread",
            "source_provider": "codex",
            "source_session_id_present": True,
            "capsule_id": "a" * 64,
            "proposal_digest": "b" * 64,
            "intent_id": "private-intent",
            "intent_revision": 2,
            "context_chars": 1450,
            "authority_transferred": False,
        }
        source = EventSource(
            self.home,
            self.home / "intent/demo.events.jsonl",
            "kb:intent/demo.events.jsonl",
            "intent-audit",
            adapt_intent,
        )

        event = adapt_intent(row, source, 1)

        self.assertEqual(event["domain"], "context")
        self.assertEqual(event["type"], "context.continuation")
        self.assertEqual(event["phase"], "observed")
        self.assertEqual(event["outcome"], "loaded")
        self.assertFalse(event["attributes"]["authority_transferred"])
        rendered = json.dumps(event, ensure_ascii=False)
        self.assertNotIn("private-new-thread", rendered)
        self.assertNotIn("private-intent", rendered)
        self.assertNotIn('"' + "a" * 64 + '"', rendered)

    def seed_sources(self) -> None:
        write_jsonl(
            self.home / "self-repair/approvals.jsonl",
            {
                "slug": "repair-one",
                "decision": "approve",
                "by": "private-operator-name",
                "at": NOW,
                "reason": "private approval rationale",
                "task_type": "implementation",
            },
        )
        write_jsonl(
            self.home / "self-repair/executed.jsonl",
            {
                "slug": "repair-one",
                "status": "success",
                "at": NOW,
                "checks": [{"passed": True, "output": "private build output"}],
                "verify_root": "/private/worktree",
            },
        )
        write_jsonl(
            self.home / "recall-log.jsonl",
            {
                "ts": NOW,
                "cwd": "/private/customer-project",
                "query_head": "private user question",
                "platform": None,
                "top_scores": [0.9],
                "injected": [101, 102],
                "source": "mem",
                "session_id": "session-one",
                "channel": "codex",
                "source_host": "codex",
                "opportunity_id": "a" * 20,
            },
        )
        write_jsonl(
            self.home / "mem-adoption-health.jsonl",
            {
                "ts": NOW,
                "opportunity_id": "a" * 20,
                "status": "classified",
                "session_id": "session-one",
                "event_count": 2,
            },
        )
        write_jsonl(
            self.home / "governance/history.jsonl",
            {
                "period": "2026-08-14",
                "collected_at": NOW,
                "values": {"metric": 1},
            },
        )
        write_jsonl(
            self.home / "sediment-runs/decisions-20260814-100000.jsonl",
            {
                "candidate_line_index": 7,
                "lesson": "private project lesson",
                "context_sha256": "b" * 64,
                "decision": {
                    "action": "merge",
                    "container": "anti-patterns",
                    "doc_id": None,
                    "target_doc_id": "ap-0001",
                    "markdown": "private generated article",
                    "reason": "private routing reason",
                },
                "ts": NOW,
            },
        )
        write_jsonl(
            self.workspace / ".codex-agent/task.intent.events.jsonl",
            {
                "schema": "sulde-guardian-audit-v1",
                "event": {
                    "schema": "sulde-guardian-event-v1",
                    "event_id": "provider-event",
                    "at": NOW,
                    "phase": "started",
                    "provider": "codex",
                    "session_id": "session-one",
                    "kind": "tool",
                    "action": "apply_patch",
                    "capability": "tool:apply_patch",
                    "target": "/private/customer-project/resume.md",
                    "result_target": "",
                    "effect": "local_write",
                    "arguments_digest": "c" * 64,
                    "success": None,
                    "intent_id": "intent-one",
                    "intent_revision": 1,
                    "observation_source": "provider_stream",
                    "parent_skills": [],
                },
                "decision": {
                    "action": "allow",
                    "would_action": "allow",
                    "severity": "info",
                    "verification_required": False,
                },
                "contract": {"intent_id": "intent-one", "revision": 1},
            },
        )
        # Raw provider streams can contain full arguments and are intentionally
        # not declared as observation sources.
        write_jsonl(
            self.workspace / ".codex-agent/task.events.jsonl",
            {"type": "tool_call", "arguments": {"token": "raw-secret"}},
        )

    def test_projection_unifies_domains_and_preserves_cross_domain_ids(self) -> None:
        self.seed_sources()
        before = {
            path: path.read_bytes()
            for path in [
                self.home / "self-repair/approvals.jsonl",
                self.home / "self-repair/executed.jsonl",
                self.home / "recall-log.jsonl",
                self.home / "mem-adoption-health.jsonl",
                self.workspace / ".codex-agent/task.intent.events.jsonl",
            ]
        }
        snapshot = collect_snapshot(self.home, workspaces=[self.workspace])
        self.assertTrue(snapshot["read_only"])
        self.assertTrue(snapshot["summary"]["contract_healthy"])
        self.assertEqual(snapshot["summary"]["events_total"], 7)
        self.assertEqual(
            set(snapshot["summary"]["by_domain"]),
            {"approval", "execution", "governance", "intent", "memory", "sedimentation"},
        )
        task_events = [
            event
            for event in snapshot["events"]
            if event["correlation"].get("task_id")
            == safe_correlation({"task_id": "repair-one"})["task_id"]
        ]
        self.assertEqual(len(task_events), 2)
        self.assertEqual({event["domain"] for event in task_events}, {"approval", "execution"})
        rendered = json.dumps(snapshot, ensure_ascii=False)
        for secret in (
            "private approval rationale",
            "private build output",
            "/private/worktree",
            "/private/customer-project",
            "private user question",
            "private project lesson",
            "private generated article",
            "private routing reason",
            "raw-secret",
            "repair-one",
            "session-one",
            "intent-one",
            "private-operator-name",
        ):
            self.assertNotIn(secret, rendered)
        self.assertNotIn(str(self.home), rendered)
        self.assertNotIn(str(self.workspace), rendered)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_filters_and_limit_apply_after_contract_validation(self) -> None:
        self.seed_sources()
        snapshot = collect_snapshot(
            self.home,
            workspaces=[self.workspace],
            domains=["intent"],
            providers=["codex"],
            correlations={"session_id": "session-one"},
            limit=1,
        )
        self.assertEqual(snapshot["summary"]["events_total"], 1)
        self.assertEqual(snapshot["summary"]["events_returned"], 1)
        self.assertEqual(snapshot["events"][0]["type"], "intent.observation")
        limited = collect_snapshot(self.home, workspaces=[self.workspace], limit=1)
        self.assertEqual(limited["summary"]["events_total"], 7)
        self.assertEqual(limited["summary"]["events_returned"], 1)
        self.assertEqual(len(limited["events"]), 1)

    def test_projection_cache_reuses_exact_prefix_then_replays_only_the_tail(self) -> None:
        source = self.home / "notify-log.jsonl"
        first_row = {
            "ts": NOW,
            "message": "private first notification",
            "cwd": "/private/project-one",
        }
        second_row = {
            "ts": "2026-08-14T10:00:01+08:00",
            "message": "private second notification",
            "cwd": "/private/project-one",
        }
        write_jsonl(source, first_row)

        first = collect_snapshot(self.home)
        second = collect_snapshot(self.home)
        with source.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(second_row, ensure_ascii=False) + "\n")
        tailed = collect_snapshot(self.home)
        rebuilt = collect_snapshot(self.home, use_cache=False)

        self.assertEqual(first["stateVersion"], 3)
        self.assertEqual(first["asOfSeq"], 0)
        self.assertEqual(first["projectionCache"]["status"], "full_rebuild")
        self.assertEqual(second["projectionCache"]["status"], "hit")
        self.assertEqual(tailed["projectionCache"]["status"], "tail_replay")
        self.assertEqual(tailed["projectionCache"]["sourcesTailReplayed"], 1)
        self.assertEqual(tailed["asOfSeq"], 1)
        self.assertEqual(tailed["events"], rebuilt["events"])
        self.assertEqual(tailed["sources"], rebuilt["sources"])
        self.assertEqual(tailed["sourceRevision"], rebuilt["sourceRevision"])
        cache = self.home / "projections/event-observer-v1.json"
        cached_text = cache.read_text(encoding="utf-8")
        for private in (
            "private first notification",
            "private second notification",
            "/private/project-one",
        ):
            self.assertNotIn(private, cached_text)

    def test_projection_cache_does_not_readapt_an_accepted_prefix(self) -> None:
        source = self.home / "notify-log.jsonl"
        write_jsonl(
            source,
            {"ts": NOW, "message": "first", "cwd": "/private/one"},
        )
        original = event_observer_module.adapt_notification
        calls: list[int] = []

        def counting_adapter(row, event_source, line):
            calls.append(line)
            return original(row, event_source, line)

        declared = tuple(
            (relative, kind, counting_adapter if relative == "notify-log.jsonl" else adapter)
            for relative, kind, adapter in event_observer_module._HOME_EXACT_SOURCES
        )
        with mock.patch.object(
            event_observer_module, "_HOME_EXACT_SOURCES", declared
        ):
            collect_snapshot(self.home)
            self.assertEqual(calls, [1])
            calls.clear()
            with source.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "ts": "2026-08-14T10:00:01+08:00",
                            "message": "second",
                            "cwd": "/private/two",
                        }
                    )
                    + "\n"
                )
            collect_snapshot(self.home)

        self.assertEqual(calls, [2])

    def test_projection_cache_discards_rewritten_prefix_without_ghost_events(self) -> None:
        source = self.home / "notify-log.jsonl"
        write_jsonl(
            source,
            {"ts": NOW, "message": "old private event", "cwd": "/old/path"},
        )
        old = collect_snapshot(self.home)
        old_event_id = old["events"][0]["event_id"]
        write_jsonl(
            source,
            {
                "ts": "2026-08-14T10:00:02+08:00",
                "message": "replacement private event",
                "cwd": "/new/path",
            },
        )

        current = collect_snapshot(self.home)

        self.assertEqual(current["projectionCache"]["status"], "full_rebuild")
        self.assertEqual(current["projectionCache"]["entriesDiscarded"], 1)
        self.assertEqual(len(current["events"]), 1)
        self.assertNotEqual(current["events"][0]["event_id"], old_event_id)
        rendered = json.dumps(current, ensure_ascii=False)
        self.assertNotIn("old private event", rendered)
        self.assertNotIn("replacement private event", rendered)

    def test_projection_cache_keeps_last_good_prefix_across_a_torn_tail(self) -> None:
        source = self.home / "notify-log.jsonl"
        write_jsonl(
            source,
            {"ts": NOW, "message": "first private", "cwd": "/private/one"},
        )
        collect_snapshot(self.home)
        accepted_size = source.stat().st_size
        with source.open("ab") as handle:
            handle.write(b'{"ts":')

        torn = collect_snapshot(self.home)

        self.assertFalse(torn["summary"]["contract_healthy"])
        self.assertEqual(torn["summary"]["invalid_rows"], 1)
        self.assertEqual(len(torn["events"]), 1)
        cached = json.loads(
            (self.home / "projections/event-observer-v1.json").read_text()
        )
        entry = next(iter(cached["sources"].values()))
        self.assertEqual(entry["byteOffset"], accepted_size)

        with source.open("ab") as handle:
            handle.write(
                b'"2026-08-14T10:00:03+08:00","message":"second",'
                b'"cwd":"/private/two"}\n'
            )
        healed = collect_snapshot(self.home)
        rebuilt = collect_snapshot(self.home, use_cache=False)

        self.assertTrue(healed["summary"]["contract_healthy"])
        self.assertEqual(healed["projectionCache"]["status"], "tail_replay")
        self.assertEqual(healed["events"], rebuilt["events"])
        self.assertEqual(len(healed["events"]), 2)

    def test_projection_cache_version_or_payload_tamper_falls_back_to_truth(self) -> None:
        source = self.home / "notify-log.jsonl"
        write_jsonl(
            source,
            {"ts": NOW, "message": "authoritative private", "cwd": "/truth"},
        )
        expected = collect_snapshot(self.home, use_cache=False)["events"]
        collect_snapshot(self.home)
        cache = self.home / "projections/event-observer-v1.json"
        payload = json.loads(cache.read_text())
        entry = next(iter(payload["sources"].values()))
        entry["events"][0]["attributes"]["prompt"] = "forged private prompt"
        cache.write_text(json.dumps(payload) + "\n", encoding="utf-8")

        rejected_payload = collect_snapshot(self.home)

        self.assertEqual(rejected_payload["events"], expected)
        self.assertEqual(
            rejected_payload["projectionCache"]["entriesDiscarded"], 1
        )
        self.assertNotIn(
            "forged private prompt",
            json.dumps(rejected_payload, ensure_ascii=False),
        )

        payload = json.loads(cache.read_text())
        payload["stateVersion"] = 1
        cache.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        rejected_version = collect_snapshot(self.home)
        self.assertEqual(
            rejected_version["projectionCache"]["readStatus"],
            "version_mismatch",
        )
        self.assertEqual(rejected_version["events"], expected)

    def test_projection_cache_write_failure_is_fail_soft(self) -> None:
        write_jsonl(
            self.home / "notify-log.jsonl",
            {"ts": NOW, "message": "private", "cwd": "/private"},
        )
        (self.home / "projections").write_text("not a directory\n")

        snapshot = collect_snapshot(self.home)

        self.assertTrue(snapshot["summary"]["contract_healthy"])
        self.assertEqual(len(snapshot["events"]), 1)
        self.assertEqual(
            snapshot["projectionCache"]["writeStatus"], "write_failed"
        )

    def test_concurrent_projection_cache_writers_leave_one_valid_whole_record(self) -> None:
        source = self.home / "notify-log.jsonl"
        write_jsonl(
            source,
            *(
                {
                    "ts": f"2026-08-14T10:00:{index:02d}+08:00",
                    "message": f"private-{index}",
                    "cwd": "/private/concurrent",
                }
                for index in range(20)
            ),
        )

        with ThreadPoolExecutor(max_workers=8) as executor:
            snapshots = list(
                executor.map(lambda _index: collect_snapshot(self.home), range(16))
            )

        event_ids = [
            [event["event_id"] for event in snapshot["events"]]
            for snapshot in snapshots
        ]
        self.assertTrue(all(value == event_ids[0] for value in event_ids))
        cache = json.loads(
            (self.home / "projections/event-observer-v1.json").read_text()
        )
        self.assertEqual(cache["stateVersion"], 3)
        self.assertEqual(cache["asOfSeq"], 19)
        final = collect_snapshot(self.home)
        self.assertEqual(final["projectionCache"]["status"], "hit")
        self.assertEqual(
            [event["event_id"] for event in final["events"]], event_ids[0]
        )

    @unittest.skipIf(os.name == "nt", "symlink creation requires extra Windows privileges")
    def test_projection_cache_never_follows_a_symlink_outside_kb_home(self) -> None:
        outside = Path(self.temporary.name) / "outside-cache"
        outside.mkdir()
        (self.home / "projections").symlink_to(outside, target_is_directory=True)
        write_jsonl(
            self.home / "notify-log.jsonl",
            {"ts": NOW, "message": "private", "cwd": "/private"},
        )

        snapshot = collect_snapshot(self.home)

        self.assertEqual(
            snapshot["projectionCache"]["status"], "unsafe_path_disabled"
        )
        self.assertEqual(snapshot["projectionCache"]["readStatus"], "unsafe_path")
        self.assertEqual(list(outside.iterdir()), [])

    def test_external_effect_interventions_join_the_read_only_intent_projection(self) -> None:
        contract = self.home / "intent/workspaces/one.active.json"
        contract.parent.mkdir(parents=True)
        contract.write_text("{}\n", encoding="utf-8")
        attempt = begin_attempt(
            contract,
            intent_id="intent-private",
            intent_revision=2,
            fingerprint="f" * 64,
            source_event_id="provider-private-id",
            capability="mcp:docs:update_document",
            target="doc://private-resume",
            resource_key=canonical_resource_key(
                "doc://private-resume", kind="uri"
            ),
            effect="external_write",
            provider="codex",
            session_id="private-session",
            idempotency_key="dispatch-private",
        )
        intervention = mark_attempt_unknown(
            contract,
            attempt["attempt_id"],
            reason="private remote error",
        )
        resolve_intervention(
            contract,
            intervention["intervention_id"],
            decision="human_attested_success",
            evidence="private operator evidence",
        )
        snapshot = collect_snapshot(self.home)
        self.assertTrue(snapshot["summary"]["contract_healthy"])
        types = {event["type"] for event in snapshot["events"]}
        self.assertIn("intent.effect_attempt", types)
        self.assertIn("intent.intervention", types)
        self.assertIn("notification.intervention", types)
        rendered = json.dumps(snapshot, ensure_ascii=False)
        for secret in (
            "intent-private",
            "provider-private-id",
            "doc://private-resume",
            "private-session",
            "private remote error",
            "private operator evidence",
            attempt["attempt_id"],
            intervention["intervention_id"],
        ):
            self.assertNotIn(secret, rendered)

    def test_v2_effect_batch_is_observed_without_copying_resource_payloads(self) -> None:
        events = self.home / "intent/workspaces/batch.interventions.jsonl"
        contract_sha256 = "a" * 64
        write_jsonl(
            events,
            {
                "schema": "sulde-intervention-event-v2",
                "type": "effect.batch_prepared",
                "contract_sha256": contract_sha256,
                "at": NOW,
                "batch_id": "private-batch",
                "call_id": "private-call",
                "intent_id": "private-intent",
                "intent_revision": 5,
                "provider": "codex",
                "session_id": "private-session",
                "task_id": "private-task",
                "capability": "tool:typed_batch_write",
                "effect": "external_write",
                "resources": [{"target": "private://resource-one"}],
                "resource_set_sha256": "b" * 64,
                "batch_semantics_sha256": "c" * 64,
            },
            {
                "schema": "sulde-intervention-event-v2",
                "type": "effect.batch_dispatched",
                "contract_sha256": contract_sha256,
                "at": "2026-08-14T10:00:01+08:00",
                "batch_id": "private-batch",
                "call_id": "private-call",
                "prepared_event_id": "private-prepared-event",
                "resource_set_sha256": "b" * 64,
                "batch_semantics_sha256": "c" * 64,
            },
        )

        snapshot = collect_snapshot(self.home)

        self.assertEqual(
            [event["outcome"] for event in snapshot["events"]],
            ["prepared", "dispatched"],
        )
        self.assertTrue(
            all(event["type"] == "intent.effect_batch" for event in snapshot["events"])
        )
        self.assertEqual(snapshot["events"][0]["attributes"]["resource_count"], 1)
        rendered = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn("private://resource-one", rendered)
        self.assertNotIn("private-session", rendered)

    def test_archived_intervention_keeps_the_same_observation_event_identity(self) -> None:
        contract = self.home / "intent/workspaces/one.active.json"
        contract.parent.mkdir(parents=True)
        contract.write_text("{}\n", encoding="utf-8")
        attempt = begin_attempt(
            contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="f" * 64,
            source_event_id="event-one",
            capability="mcp:docs:create_document",
            target="doc://one",
            effect="external_write",
            provider="codex",
            session_id="session-one",
            idempotency_key="dispatch-one",
            verification_kind="existence",
        )
        before = collect_snapshot(self.home)
        archive_store(
            contract,
            self.home / "interventions" / "archive",
            slug="task-one",
        )
        mark_attempt_unknown(
            contract,
            attempt["attempt_id"],
            reason="later rows must select the newest append-only archive",
        )
        archive_store(
            contract,
            self.home / "interventions" / "archive",
            slug="task-one",
        )
        latest_live = collect_snapshot(self.home)
        event_store_path(contract).unlink()
        projection_path(contract).unlink()
        after = collect_snapshot(self.home)
        self.assertTrue(
            set(event["event_id"] for event in before["events"])
            < set(event["event_id"] for event in latest_live["events"])
        )
        self.assertEqual(
            [event["event_id"] for event in latest_live["events"]],
            [event["event_id"] for event in after["events"]],
        )

    def test_unknown_shape_is_visible_and_never_silently_upgraded(self) -> None:
        write_jsonl(
            self.home / "intent/workspaces/demo.events.jsonl",
            {"schema": "future-intent-v9", "at": NOW, "payload": "secret"},
        )
        snapshot = collect_snapshot(self.home)
        self.assertFalse(snapshot["summary"]["contract_healthy"])
        self.assertEqual(snapshot["summary"]["unsupported_rows"], 1)
        self.assertEqual(snapshot["events"], [])
        self.assertNotIn("secret", json.dumps(snapshot, ensure_ascii=False))

    @unittest.skipIf(os.name == "nt", "symlink creation requires extra Windows privileges")
    def test_symlink_source_is_rejected_without_following_it(self) -> None:
        outside = Path(self.temporary.name) / "outside.jsonl"
        write_jsonl(outside, {"ts": NOW, "message": "outside secret", "cwd": "/tmp"})
        target = self.home / "notify-log.jsonl"
        target.symlink_to(outside)
        snapshot = collect_snapshot(self.home)
        self.assertFalse(snapshot["summary"]["contract_healthy"])
        self.assertEqual(snapshot["summary"]["sources_unreadable"], 1)
        self.assertNotIn("outside secret", json.dumps(snapshot, ensure_ascii=False))

    def test_status_projection_is_small_and_has_no_event_rows(self) -> None:
        self.seed_sources()
        status = status_projection(self.home)
        self.assertTrue(status["event_contract_healthy"])
        self.assertEqual(status["event_contract_violations"], 0)
        self.assertGreater(status["event_observations_total"], 0)
        self.assertEqual(status["event_projection_state_version"], 3)
        self.assertGreaterEqual(status["event_projection_as_of_seq"], 0)
        self.assertEqual(status["event_observation_privacy_mode"], "local")
        self.assertTrue(status["event_observation_privacy_healthy"])
        self.assertTrue(status["event_observation_enabled"])
        self.assertFalse(status["event_observation_export_enabled"])
        self.assertNotIn("event_projection_cache", status)
        self.assertNotIn("events", status)
        self.assertNotIn("sources", status)

    def test_cli_verify_returns_one_for_contract_drift(self) -> None:
        path = self.home / "feedback-log.jsonl"
        path.write_text("not-json\n", encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "event-observer.py"),
                "verify",
                "--home",
                str(self.home),
            ],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 1, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["stateVersion"], 3)
        self.assertEqual(payload["asOfSeq"], 0)
        self.assertRegex(payload["sourceRevision"], r"^[0-9a-f]{64}$")
        self.assertIn("status", payload["projectionCache"])
        self.assertEqual(payload["summary"]["invalid_rows"], 1)
        self.assertNotIn("not-json", completed.stdout)

    def test_weekly_governance_consumes_the_zero_tolerance_invariant(self) -> None:
        script = SCRIPT_DIR / "governance-report.py"
        spec = importlib.util.spec_from_file_location("event_governance", script)
        assert spec is not None and spec.loader is not None
        governance = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(governance)
        source_names = (
            "status",
            "fleet",
            "kb_golden",
            "mem_golden",
            "calibrate",
            "recall",
            "mem_adoption",
            "auto_distill",
            "auto_sediment",
            "golden_candidates",
            "graph_audit",
            "kb_aging",
            "kb_dedup",
            "candidates",
            "mem_edges",
            "sync_export",
            "previous_report",
        )
        snapshot = {
            "sources": {
                name: {"status": "available", "data": {}} for name in source_names
            }
        }
        snapshot["sources"]["status"]["data"] = {
            "mem_pending_embedding": 0,
            "event_contract_violations": 2,
            "interventions_open": 1,
            "effect_blocking": 1,
            "intervention_invalid_stores": 0,
        }
        self.assertEqual(
            governance.metric_values(snapshot)["event_contract_violations"], 2
        )
        rule = governance.load_thresholds()["event_contract_violations"]
        self.assertEqual((rule["op"], rule["value"]), ("<=", 0))
        values = governance.metric_values(snapshot)
        self.assertEqual(values["interventions_open"], 1)
        self.assertEqual(values["effect_blocking"], 1)
        self.assertEqual(values["intervention_invalid_stores"], 0)
        thresholds = governance.load_thresholds()
        for name in (
            "interventions_open",
            "effect_blocking",
            "intervention_invalid_stores",
        ):
            self.assertEqual((thresholds[name]["op"], thresholds[name]["value"]), ("<=", 0))


    def test_queue_claim_cannot_override_missing_evidence_or_authority_debt(self) -> None:
        source = self.home / "self-repair" / "pending.json"
        source.parent.mkdir(parents=True)
        source.write_text(
            json.dumps(
                [
                    {
                        "slug": "claim-only",
                        "status": "verified",
                        "closure_status": "verified",
                        "drafted_at": "2026-09-04T00:00:00Z",
                    },
                    {
                        "slug": "authority-open",
                        "status": "verified",
                        "closure_status": "verified",
                        "verification_sha256": "a" * 64,
                        "grant_ids": ["grant-open"],
                        "drafted_at": "2026-09-04T00:00:01Z",
                    },
                ]
            ),
            encoding="utf-8",
        )

        snapshot = collect_snapshot(self.home, use_cache=False)
        events = [
            event for event in snapshot["events"]
            if event["type"] == "lifecycle.self_repair_queue"
        ]
        self.assertEqual([event["outcome"] for event in events], ["inconclusive", "unresolved"])
        self.assertFalse(events[0]["attributes"]["authority_debt"])
        self.assertTrue(events[1]["attributes"]["authority_debt"])

    def test_recent_queue_evolution_life_and_execution_share_versioned_projection(self) -> None:
        pending = self.home / "self-repair/pending.json"
        pending.parent.mkdir(parents=True)
        pending.write_text(
            json.dumps(
                [
                    {
                        "slug": "repair-private",
                        "source": "/Users/private/project/report.md",
                        "status": "resolved",
                        "resolution_evidence": "reviewed evidence",
                        "resolved_at": NOW,
                        "project_id": "private-project",
                        "session_id": "private-session",
                        "task_instance_id": "private-lane",
                    }
                ]
            ),
            encoding="utf-8",
        )
        evolution = self.home / "evolution/registry.json"
        evolution.parent.mkdir()
        evolution.write_text(
            json.dumps(
                {
                    "schema": "sulde-organ-evolution-v1",
                    "generated_at": NOW,
                    "items": [
                        {
                            "id": "private-experiment",
                            "status": "observing",
                            "organ": "self-repair",
                            "metric": "l3.counts.failed",
                            "task_slug": "repair-private",
                            "created_at": NOW,
                            "observations": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        life = self.home / "life/state.json"
        life.parent.mkdir()
        life.write_text(
            json.dumps(
                {
                    "schema": "sulde-life-cycle-v2",
                    "generated_at": NOW,
                    "status": "degraded",
                    "closed_loop": {
                        "dimensions": {
                            "sense": True,
                            "persist": True,
                            "decide": True,
                            "act": False,
                            "verify": False,
                        },
                        "human_gates": {"preserved": False},
                        "identity_resume": {"guarded": False},
                        "overall_ready": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        write_jsonl(
            self.workspace / ".codex-agent/recent.run.jsonl",
            {
                "schema": "sulde-run-event-v1",
                "type": "execution.result",
                "at": NOW,
                "provider": "codex",
                "run_id": "private-run",
                "project_id": "private-project",
                "session_id": "private-session",
                "lane_id": "private-lane",
                "task_instance_id": "private-instance",
                "returncode": 0,
                "stop_reason": "completed",
            },
        )
        before = {
            path: path.read_bytes()
            for path in (pending, evolution, life)
        }

        snapshot = collect_snapshot(
            self.home, workspaces=[self.workspace], use_cache=False
        )

        self.assertEqual(snapshot["summary"]["event_schema"], "sulde-observation-event-v1")
        self.assertTrue(snapshot["summary"]["contract_healthy"])
        self.assertTrue(
            {
                "lifecycle.self_repair_queue",
                "lifecycle.evolution",
                "lifecycle.closed_loop",
                "execution.run",
            }.issubset(snapshot["summary"]["by_type"])
        )
        self.assertEqual(
            next(
                event["outcome"]
                for event in snapshot["events"]
                if event["type"] == "lifecycle.self_repair_queue"
            ),
            "verified",
        )
        rendered = json.dumps(snapshot, ensure_ascii=False)
        for private in (
            "/Users/private", "repair-private", "private-project",
            "private-session", "private-lane", "private-instance", "private-run",
        ):
            self.assertNotIn(private, rendered)
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw)

    def test_historical_violation_is_preserved_but_superseding_projection_settles_it(self) -> None:
        source = self.home / "intent/workspaces/legacy.events.jsonl"
        write_jsonl(
            source,
            {"schema": "future-intent-v99", "at": NOW, "private": "unchanged"},
        )
        original = source.read_bytes()
        first = collect_snapshot(self.home, use_cache=False)
        report = next(
            row for row in first["sources"] if row["kind"] == "intent-audit"
        )
        fingerprint = report["violation_fingerprints"][0]
        self.assertEqual(first["summary"]["contract_violations"], 1)

        write_jsonl(
            self.home / "projections/event-settlements.jsonl",
            {
                "schema": "sulde-observation-settlement-v1",
                "at": "2026-09-04T00:00:00Z",
                "outcome": "superseded",
                "original_category": "unsupported",
                "target_fingerprint": fingerprint,
                "actor": "human",
            },
        )
        settled = collect_snapshot(self.home, use_cache=False)

        self.assertTrue(settled["summary"]["contract_healthy"])
        self.assertEqual(settled["summary"]["unsupported_rows"], 1)
        self.assertEqual(settled["summary"]["historical_contract_violations"], 1)
        self.assertEqual(settled["summary"]["settled_contract_violations"], 1)
        self.assertEqual(settled["summary"]["contract_violations"], 0)
        self.assertEqual(source.read_bytes(), original)
        settlement = next(
            event
            for event in settled["events"]
            if event["type"] == "lifecycle.event_settlement"
        )
        self.assertEqual(settlement["outcome"], "superseded")

    def test_execution_correlation_isolated_by_session_lane_and_formal_continuation(self) -> None:
        rows = []
        for index, session in enumerate(("session-one", "session-two"), 1):
            rows.append(
                {
                    "schema": "sulde-run-event-v1",
                    "type": "execution.started",
                    "at": f"2026-09-04T00:00:0{index}Z",
                    "provider": "codex",
                    "run_id": f"run-{index}",
                    "project_id": "same-project",
                    "session_id": session,
                    "lane_id": f"lane-{index}",
                    "task_instance_id": f"instance-{index}",
                    "continuation_id": f"continuation-{index}",
                    "continuation_kind": "formal" if index == 2 else "informal",
                    "authority_transferred": False,
                }
            )
        write_jsonl(self.workspace / ".codex-agent/isolation.run.jsonl", *rows)

        snapshot = collect_snapshot(
            self.home, workspaces=[self.workspace], use_cache=False
        )
        events = [
            event for event in snapshot["events"] if event["type"] == "execution.run"
        ]

        self.assertEqual(len(events), 2)
        self.assertNotEqual(
            events[0]["correlation"]["session_id"],
            events[1]["correlation"]["session_id"],
        )
        self.assertNotEqual(
            events[0]["correlation"]["lane_id"],
            events[1]["correlation"]["lane_id"],
        )
        self.assertNotIn("continuation_id", events[0]["correlation"])
        self.assertIn("continuation_id", events[1]["correlation"])
        for event in events:
            self.assertNotIn("grant", event["attributes"])
            self.assertNotIn("effect", event["attributes"])


if __name__ == "__main__":
    unittest.main()
