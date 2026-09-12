"""Frozen memory/Guardian consistency regressions; all state is disposable."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import runpy
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/kb"))
import memory_annotation as annotation
from intent_guardian_parts.resources import normalize_hook_event, _local_memory_annotation_verification, _memory_receipt_verification

memory = runpy.run_path(str(ROOT / "tools/kb-index/memory.py"))
server = runpy.run_path(str(ROOT / "tools/kb-mcp/server.py"))
import tests.test_intent_guardian as fixtures
from intent_guardian import GuardianSession, load_contract, write_contract, create_revision_proposal
from intent_guardian_parts import policy, approvals, memory_scope, state, recovery
from intent_guardian_parts.events import _completion_open_event_index


def request():
    return {"entities": [{"name": "A", "type": "component"}, {"name": "B", "type": "risk"}],
            "edges": [{"src": "A", "rel": "avoids", "dst": "B", "confidence": 0.9}],
            "extracted_by": "codex"}


class MemoryConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        memory["initialize"](self.home / "memory.db")
        self.db = memory["connect"](self.home / "memory.db")
        self.addCleanup(self.db.close)

    def test_identical_retry_is_explicit_and_receipt_verifies(self):
        first = memory["annotate_memory"](self.db, request())
        second = memory["annotate_memory"](self.db, request())
        self.assertEqual(first["status"], "created")
        self.assertEqual(second["status"], "already_present")
        self.assertEqual(second["inserted"], 0)
        self.assertTrue(second["replayed"])
        self.assertEqual(self.db.execute("SELECT count(*) FROM mem_annotation_receipts").fetchone()[0], 1)
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(self.home)}):
            proof = _local_memory_annotation_verification(request(), expected_digest=first["request_sha256"])
        self.assertEqual(proof["source"], "local_memory_db_read")

    def test_other_host_preserves_original_provenance(self):
        first = memory["annotate_memory"](self.db, request())
        other = {**request(), "extracted_by": "claude"}
        second = memory["annotate_memory"](self.db, other)
        self.assertEqual(second["status"], "already_present")
        self.assertNotEqual(first["request_sha256"], second["request_sha256"])
        self.assertEqual(self.db.execute("SELECT extracted_by FROM mem_edges").fetchone()[0], "codex")
        self.assertIsNotNone(annotation.verify_receipt(self.db, second["request_sha256"]))

    def test_conflicts_rollback_the_whole_batch(self):
        memory["annotate_memory"](self.db, request())
        before = self.db.total_changes
        for changed in ("entity_type", "confidence"):
            value = copy.deepcopy(request())
            value["entities"].insert(0, {"name": "NEW", "type": "task"})
            if changed == "entity_type":
                value["entities"][1]["type"] = "project"
            else:
                value["edges"][0]["confidence"] = 1.0
            with self.assertRaisesRegex(ValueError, "conflict"):
                memory["annotate_memory"](self.db, value)
            self.assertIsNone(self.db.execute("SELECT 1 FROM mem_entities WHERE name='NEW'").fetchone())
            self.assertEqual(self.db.execute("SELECT count(*) FROM mem_annotation_receipts").fetchone()[0], 1)
        self.assertGreaterEqual(self.db.total_changes, before)

    def test_missing_provider_never_defaults_to_claude(self):
        value = request()
        del value["extracted_by"]
        with self.assertRaisesRegex(ValueError, "extracted_by"):
            memory["annotate_memory"](self.db, value)
        definition = next(row for row in server["tool_definitions"]() if row["name"] == "memory_annotate")
        self.assertIn("extracted_by", definition["inputSchema"]["required"])
        self.assertNotIn("default", definition["inputSchema"]["properties"]["extracted_by"])

    def test_confidence_and_input_bounds_are_shared(self):
        for confidence in (True, -0.1, 1.1, float("nan"), float("inf")):
            value = request()
            value["edges"][0]["confidence"] = confidence
            with self.assertRaises(ValueError):
                annotation.normalize(value, bounded=True)
            with self.assertRaises(ValueError):
                memory["annotate_memory"](self.db, value)

    def test_existing_caller_transaction_is_not_committed_or_rolled_back(self):
        self.db.execute("INSERT INTO mem_entities VALUES ('unrelated','task','now')")
        with self.assertRaisesRegex(ValueError, "idle"):
            memory["annotate_memory"](self.db, request())
        self.assertTrue(self.db.in_transaction)
        self.assertIsNotNone(self.db.execute("SELECT 1 FROM mem_entities WHERE name='unrelated'").fetchone())
        self.db.rollback()

    def test_tampered_rows_or_receipt_do_not_verify(self):
        result = memory["annotate_memory"](self.db, request())
        with self.db:
            self.db.execute("UPDATE mem_edges SET confidence=1.0")
        self.assertIsNone(annotation.verify_receipt(self.db, result["request_sha256"]))

    def test_graph_reader_cannot_create_or_write_a_database(self):
        missing = self.home / "missing.db"
        with self.assertRaises(sqlite3.OperationalError):
            memory["connect_readonly"](missing)
        self.assertFalse(missing.exists())
        with memory["connect_readonly"](self.home / "memory.db") as reader:
            self.assertEqual(memory["memory_graph"](reader, "A", project="other"), [])
            with self.assertRaises(sqlite3.OperationalError):
                reader.execute("CREATE TABLE unexpected(value)")
        reader.close()

    def test_real_database_lock_is_unverified_then_recovers_without_a_write(self):
        result = memory["annotate_memory"](self.db, request())
        self.db.execute("BEGIN EXCLUSIVE")
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(self.home)}):
            try:
                self.assertIsNone(_memory_receipt_verification(result["request_sha256"]))
            finally:
                self.db.rollback()
            before = self.db.total_changes
            self.assertIsNotNone(_memory_receipt_verification(result["request_sha256"]))
            self.assertEqual(self.db.total_changes, before)

    def test_mcp_graph_project_is_forwarded_without_a_schema_write(self):
        class Backend:
            def connect_readonly(inner):
                return memory["connect_readonly"](self.home / "memory.db")
            def memory_graph(inner, connection, entity, **kwargs):
                self.assertEqual(kwargs["project"], "one")
                self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)
                return []
        with mock.patch.dict(server["memory_graph"].__globals__, {"_direct_runtime": lambda _: Backend()}):
            self.assertNotIn("isError", server["memory_graph"]({"entity": "A", "project": "one"}))

    def test_mcp_business_failure_never_falls_back(self):
        class Backend:
            def connect(self):
                return sqlite3.connect(":memory:")
            def annotate_memory(self, connection, payload):
                raise ValueError("conflicting assertion")
        target = server["memory_annotate"].__globals__
        with mock.patch.dict(target, {"_direct_runtime": lambda _: Backend()}), \
                mock.patch.object(server["kb_cli"], "run_cli", side_effect=AssertionError("unsafe write retry")):
            result = server["memory_annotate"](request())
        self.assertTrue(result["isError"])
        self.assertIn("conflicting assertion", result["content"][0]["text"])

    def test_pre_post_digest_covers_confidence_and_provider(self):
        payload = {"tool_name": "mcp__sulde_kb__memory_annotate", "tool_input": request(),
                   "client": "codex", "session_id": "test", "call_id": "one"}
        event = normalize_hook_event(payload, phase="started", provider="codex")
        self.assertEqual(event["effect"], "local_write")
        self.assertEqual(event["memory_verification"]["request_sha256"], event["verification_sha256"])
        changed = copy.deepcopy(payload)
        changed["tool_input"]["edges"][0]["confidence"] = 1.0
        self.assertNotEqual(event["verification_sha256"], normalize_hook_event(changed, phase="started", provider="codex")["verification_sha256"])

    def test_concurrent_identical_writers_commit_one_receipt(self):
        def write(_):
            db = memory["connect"](self.home / "memory.db")
            try:
                return memory["annotate_memory"](db, request())["status"]
            finally:
                db.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(write, range(8)))
        self.assertEqual(results.count("created"), 1)
        self.assertEqual(results.count("already_present"), 7)
        self.assertEqual(self.db.execute("SELECT count(*) FROM mem_annotation_receipts").fetchone()[0], 1)

    def test_automatic_recall_is_source_bound_project_scoped_and_labelled(self):
        entry = memory["add_entry"](self.db, project="one", session_id="s", source_host="codex",
            role="assistant", content="A currently avoids B in this isolated example.", ts="2026-09-09T00:00:00Z")
        self.db.commit()
        value = request()
        value["edges"][0].update(entry_id=entry, truth_status="current")
        memory["annotate_memory"](self.db, value)
        reader = memory["memory_associations"]
        before = self.db.total_changes
        self.assertIn("未经人工核实", reader(self.db, entry, "one")[0])
        self.assertEqual(reader(self.db, entry, "two"), [])
        self.assertEqual(self.db.total_changes, before)
        for status in ("planned", "not_ready", "uncertain"):
            with self.db:
                self.db.execute("UPDATE mem_edges SET truth_status=?", (status,))
            self.assertEqual(reader(self.db, entry, "one"), [])
        with self.db:
            self.db.execute("UPDATE mem_edges SET truth_status='current',truth_source_sha256='stale'")
        self.assertEqual(reader(self.db, entry, "one"), [])
        with self.db:
            self.db.execute("UPDATE mem_edges SET entry_id=NULL")
        self.assertEqual(reader(self.db, entry, "one"), [])


class GuardianMemoryLifecycleTests(unittest.TestCase):
    setUp = fixtures.IntentGuardianTests.setUp
    tearDown = fixtures.IntentGuardianTests.tearDown
    contract = fixtures.IntentGuardianTests.contract

    def event(self, call="one", phase="started", value=None, session="thread"):
        return normalize_hook_event({"client": "codex", "session_id": session, "call_id": call,
            "tool_name": "mcp__sulde_kb__memory_annotate", "tool_input": value or request(), "success": True},
            phase=phase, provider="codex")

    def store(self):
        path = Path(os.environ["SULDE_KB_HOME"]) / "memory.db"
        path.parent.mkdir(exist_ok=True)
        memory["initialize"](path)
        db = memory["connect"](path)
        self.addCleanup(db.close)
        return db

    def test_lost_post_busy_db_restart_and_idempotent_reconciliation(self):
        self.contract()
        db = self.store()
        session = GuardianSession(self.contract_path, provider="codex", session_id="thread")
        self.assertEqual(session.observe(self.event()).action, "allow")
        memory["annotate_memory"](db, request())
        # Stop owns the unknown transition; this is not a fabricated Post.
        with mock.patch.object(recovery, "_memory_receipt_verification", return_value=None):
            policy._finalize_lane(self.contract_path, host="codex", session_id="thread")
        row = load_contract(self.contract_path)["runtime"]["pending_verifications"][0]
        self.assertEqual(row["memory_verification"]["schema"], annotation.SCHEMA)
        with mock.patch.object(recovery, "_memory_receipt_verification", return_value=None):
            self.assertEqual(recovery.reconcile_pending_verifications(self.contract_path), [])
        self.assertEqual(len(load_contract(self.contract_path)["runtime"]["pending_verifications"]), 1)
        self.assertEqual(len(recovery.reconcile_pending_verifications(self.contract_path)), 1)
        self.assertEqual(recovery.reconcile_pending_verifications(self.contract_path), [])
        self.assertEqual(load_contract(self.contract_path)["runtime"]["pending_verifications"], [])
        attempts = fixtures.load_intervention_projection(self.contract_path)["attempts"]
        self.assertEqual(len(attempts), 1)
        self.assertEqual(next(iter(attempts.values()))["state"], "system_verified")

    def test_ten_calls_and_duplicate_callbacks_do_not_exhaust_authority(self):
        self.contract()
        db = self.store()
        session = GuardianSession(self.contract_path, provider="codex", session_id="thread")
        for index in range(10):
            started = self.event(str(index))
            self.assertEqual(session.observe(started).action, "allow")
            material = load_contract(self.contract_path)["runtime"]["material_sequence"]
            self.assertEqual(session.observe(started).action, "allow")
            self.assertEqual(load_contract(self.contract_path)["runtime"]["material_sequence"], material)
            memory["annotate_memory"](db, request())
            completed = self.event(str(index), "completed")
            session.observe(completed)
            session.observe(completed)
        runtime = load_contract(self.contract_path)["runtime"]
        self.assertEqual(runtime["open_events"], [])
        self.assertEqual(runtime["pending_verifications"], [])
        self.assertEqual(runtime["material_sequence"], 10)
        self.assertEqual(runtime["memory_material_sequence"], 10)
        self.assertEqual(memory_scope.sequence(runtime, scoped=True), 0)
        self.assertEqual(len(fixtures.load_intervention_projection(self.contract_path)["attempts"]), 10)
        self.assertEqual(session.observe(self.event("9")).action, "deny")

    def test_pairing_never_consumes_equal_arguments_other_call_session_or_epoch(self):
        event = self.event("two", "completed")
        event["task_epoch"] = "epoch"
        opened = {**self.event("one"), "task_epoch": "epoch", "fingerprint": "same"}
        self.assertIsNone(_completion_open_event_index([opened], event, fingerprint="same"))
        for change in ({"call_id": "two", "session_id": "other"}, {"call_id": "two", "task_epoch": "old"}):
            self.assertIsNone(_completion_open_event_index([{**opened, **change}], event, fingerprint="same"))
        correct = {**opened, "call_id": "two"}
        self.assertIsNone(_completion_open_event_index([correct, correct], event, fingerprint="same"))
        self.assertEqual(_completion_open_event_index([opened, correct], event, fingerprint="same"), 1)

    def test_unsettled_state_over_100_survives_normalization(self):
        contract = self.contract()
        row = self.event()
        contract["runtime"]["open_events"] = [{**row, "event_id": str(i)} for i in range(151)]
        contract["runtime"]["pending_verifications"] = [{"attempt_id": str(i)} for i in range(151)]
        normalized = state.validate_contract(contract)
        self.assertEqual(len(normalized["runtime"]["open_events"]), 151)
        self.assertEqual(len(normalized["runtime"]["pending_verifications"]), 151)
        for field in ("open_events", "pending_verifications"):
            invalid = copy.deepcopy(contract)
            invalid["runtime"][field] = [None]
            with self.assertRaises(state.IntentGuardianError):
                state.validate_contract(invalid)

    def test_persist_keeps_older_protected_continuation_uses(self):
        self.contract()
        monitor = GuardianSession(self.contract_path, provider="codex", session_id="thread")
        monitor.observe(self.event())
        current = load_contract(self.contract_path)
        opened = current["runtime"]["open_events"][0]
        use = current["runtime"]["continuation_uses"][0]
        current["runtime"]["open_events"] = [{**opened, "fingerprint": f"{i:064x}"} for i in range(151)]
        current["runtime"]["continuation_uses"] = [{**use, "fingerprint": f"{i:064x}"} for i in range(151)]
        write_contract(self.contract_path, current)
        read = normalize_hook_event({"client": "codex", "session_id": "thread", "tool_name": "Read",
                                     "tool_input": {"path": str(self.root / "README.md")}}, phase="started", provider="codex")
        GuardianSession(self.contract_path).observe(read)
        self.assertEqual(len(load_contract(self.contract_path)["runtime"]["continuation_uses"]), 151)

    def test_only_explicit_independent_proposal_ignores_memory_sequence(self):
        self.contract()
        for dependency in ("dependent", "independent"):
            path, digest = create_revision_proposal(self.contract_path, objective="Update report wording",
                acceptance_criteria=["Report text updated"], mode="enforce", allowed_paths=["report.md"],
                effects=["local_write"], memory_dependency=dependency, provider="codex", session_id="thread")
            current = load_contract(self.contract_path)
            event = self.event()
            decision = policy.Decision(dispatch="allow", would_dispatch="allow", lifecycle="continue", authority="task",
                verification="none", evidence_state="observed", severity="low", reason="unit sequence input", fingerprint="a" * 64)
            policy._advance_material_sequence_for_allowed_event(current["runtime"], event, decision, matched_started_event=False)
            if dependency == "dependent":
                with self.assertRaisesRegex(state.IntentGuardianError, "material world"):
                    approvals._validate_proposal_for_approval(self.contract_path, current, digest)
            else:
                self.assertEqual(approvals._validate_proposal_for_approval(self.contract_path, current, digest), path)
                ordinary = {**event, "capability": "tool:apply_patch", "memory_verification": None}
                policy._advance_material_sequence_for_allowed_event(current["runtime"], ordinary, decision, matched_started_event=False)
                with self.assertRaisesRegex(state.IntentGuardianError, "material world"):
                    approvals._validate_proposal_for_approval(self.contract_path, current, digest)

    def test_memory_scope_is_not_an_unknown_external_or_control_exemption(self):
        current = self.contract()
        proposal = copy.deepcopy(current)
        proposal["constraints"]["memory_dependency"] = "independent"
        proposal["decision"] = {"effects": ["local_write"]}
        row = self.event()
        row["attempt_id"] = "attempt"
        attempts = {"attempt": copy.deepcopy(row)}
        current["runtime"]["pending_verifications"] = [row]
        self.assertEqual(memory_scope.blocking_pending(current, proposal, attempts=attempts), [])
        self.assertEqual(len(memory_scope.blocking_pending(current, proposal)), 1)
        for changes in ({"effect": "external_write"}, {"effect": "destructive"}, {"effect": "unknown"},
                        {"control_plane": True}, {"memory_verification": None}, {"verification_sha256": "bad"},
                        {"continuation_grant_id": "another"}, {"provider": []}):
            current["runtime"]["pending_verifications"] = [{**row, **changes}]
            self.assertEqual(len(memory_scope.blocking_pending(current, proposal, attempts=attempts)), 1)

    def test_independent_proposal_does_not_clear_open_memory_audit(self):
        self.contract()
        self.assertEqual(GuardianSession(self.contract_path).observe(self.event()).action, "allow")
        common = dict(objective="Update report", acceptance_criteria=["Report updated"], mode="enforce",
            allowed_paths=["report.md"], effects=["local_write"], provider="codex", session_id="thread")
        with self.assertRaisesRegex(state.IntentGuardianError, "still open"):
            create_revision_proposal(self.contract_path, **common)
        path, _ = create_revision_proposal(self.contract_path, memory_dependency="independent", **common)
        self.assertTrue(path.is_file())
        self.assertEqual(len(load_contract(self.contract_path)["runtime"]["open_events"]), 1)

    def test_continuation_projection_requires_authoritative_memory_identity(self):
        row = {**self.event(), "event_id": "event", "attempt_id": "attempt"}
        attempts = {"attempt": {**row, "source_event_id": "event"}}
        self.assertTrue(memory_scope.proven_memory_row(row, attempts))
        use = {key: value for key, value in row.items() if key != "attempt_id"}
        self.assertTrue(memory_scope.proven_memory_row(use, attempts))
        for corrupt in ({}, {"attempt": {**attempts["attempt"], "effect": "external_write"}},
                        {"attempt": attempts["attempt"], "duplicate": attempts["attempt"]}):
            self.assertFalse(memory_scope.proven_memory_row(use, corrupt))

    def test_older_writer_total_increments_still_invalidate_scoped_world(self):
        runtime = {"material_sequence": 10, "memory_material_sequence": 4}
        self.assertEqual(memory_scope.sequence(runtime, scoped=True), 6)
        runtime["material_sequence"] += 1  # old writer has no memory-domain field
        self.assertEqual(memory_scope.sequence(runtime, scoped=True), 7)

    def test_provider_file_change_fanout_retains_one_host_call_identity(self):
        self.contract()
        monitor = GuardianSession(self.contract_path, provider="codex", session_id="thread")
        item = {"type": "file_change", "id": "files", "changes": [
            {"path": str(self.root / "a.txt")}, {"path": str(self.root / "b.txt")}], "status": "completed"}
        for phase in ("started", "completed"):
            events = fixtures.normalize_provider_events({"type": "item." + phase, "item": item}, provider="codex")
            for event in events:
                self.assertEqual(monitor.observe(event).action, "allow")
            self.assertEqual(len(load_contract(self.contract_path)["runtime"]["open_events"]), 2 if phase == "started" else 0)

    def test_malformed_receipt_is_not_a_hook_exception_or_success(self):
        self.contract()
        db = self.store()
        result = memory["annotate_memory"](db, request())
        with db:
            db.execute("UPDATE mem_annotation_receipts SET result_json='[]'")
        self.assertIsNone(annotation.verify_receipt(db, result["request_sha256"]))
