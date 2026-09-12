from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "kb"))
import host_capabilities as host
import host_observation_index as index
import session_lifecycle_lineage as lineage


class HostObservationIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / "kb"
        self.workspace = Path(self.temporary.name) / "project"
        self.workspace.mkdir()
        host.provision_provenance_key(self.home)
        self.now = datetime.now(timezone.utc)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def record(self, hook: str, *, at=None, session="one", call="", runtime="a" * 64):
        moment = at or self.now
        with mock.patch.object(host, "runtime_identity", return_value=runtime):
            proof = host.issue_host_provenance(
                provider="codex", hook_event=hook, session_id=session,
                workspace=self.workspace, call_id=call, home=self.home, now=moment,
                loaded_module_generation=runtime, artifact_generation="artifact:" + runtime,
            )
            return host.record_observation(
                provider="codex", hook_event=hook, session_id=session,
                workspace=self.workspace, call_id=call, home=self.home, now=moment,
                source="live_host_hook", provenance=proof,
            )

    def projection(self, session="one", runtime="a" * 64, now=None):
        return host.readiness_projection(
            self.home, provider="codex", session_id=session,
            workspace=self.workspace, expected_runtime_sha256=runtime,
            now=now or self.now,
        )

    def flood(self):
        with host.observation_path(self.home).open("ab") as handle:
            row = json.dumps({"provider": "codex", "session_id": "unrelated", "padding": "x" * 8192}).encode() + b"\n"
            for _ in range(600):
                handle.write(row)

    def test_lifetime_start_survives_the_global_tail(self):
        start = self.record("SessionStart", at=self.now - timedelta(days=2))
        self.flood()
        result = self.projection()
        self.assertEqual(result["capabilities"]["session_context"]["status"], "live_verified")
        self.assertEqual(result["capabilities"]["session_context"]["last_observed_at"], start["at"])
        self.assertEqual(result["observation_index"]["status"], "catchup_required")

    def test_warm_reader_is_bounded_and_never_writes(self):
        self.record("SessionStart")
        self.record("MCPInitialize", session="")
        path = index.index_path(self.home, "codex", "one")
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        with mock.patch.object(host, "_read_tail", side_effect=AssertionError("global tail replay")), \
             mock.patch.object(index, "publish_index", side_effect=AssertionError("read mutated projection")):
            result = self.projection()
        self.assertLessEqual(result["observation_index"]["scanned_bytes"], index.MAX_INCREMENT_BYTES)
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))

    def test_another_session_cannot_borrow_start_or_prompt(self):
        self.record("SessionStart")
        self.record("UserPromptSubmit")
        other = self.projection("two")
        self.assertEqual(other["capabilities"]["session_context"]["status"], "unobserved")
        self.assertEqual(other["capabilities"]["prompt_control"]["status"], "unobserved")

    def test_append_before_publish_crash_keeps_stop_visible(self):
        self.record("SessionStart", at=self.now - timedelta(minutes=2))
        self.record("UserPromptSubmit", at=self.now - timedelta(minutes=1))
        with mock.patch.object(index, "publish_index", return_value=False):
            self.record("Stop", at=self.now - timedelta(seconds=40))
        self.record("PreToolUse", at=self.now - timedelta(seconds=30), call="call")
        self.record("PostToolUse", at=self.now - timedelta(seconds=20), call="call")
        self.assertNotEqual(self.projection()["capabilities"]["prompt_control"]["status"], "live_verified")

    def test_corrupt_index_cannot_invent_historical_start(self):
        self.record("SessionStart")
        self.flood()
        path = index.index_path(self.home, "codex", "one")
        path.write_text('{"schema":"invented"}', encoding="utf-8")
        before = path.read_bytes()
        result = self.projection()
        self.assertEqual(result["capabilities"]["session_context"]["status"], "unobserved")
        self.assertEqual(result["observation_index"]["status"], "invalid")
        self.assertEqual(path.read_bytes(), before)

    def test_source_removal_does_not_leave_false_green_cache(self):
        self.record("SessionStart")
        host.observation_path(self.home).unlink()
        result = self.projection()
        self.assertEqual(result["capabilities"]["session_context"]["status"], "unobserved")

    def test_uncommitted_mapping_cannot_create_lineage(self):
        self.assertFalse(lineage.record_transition(
            self.home, provider="codex", session_id="one", source_workspace=str(self.workspace),
            mapping={"provider": "codex", "session_id": "one", "mapping_sha256": "a" * 64},
            receipt_id="invented",
        ))
        self.assertFalse(lineage.lineage_path(self.home, "codex", "one").exists())

    def test_maintenance_cli_keeps_original_truth_and_controls_invalid_budget(self):
        self.record("SessionStart")
        original = host.observation_path(self.home).read_bytes()
        command = [sys.executable, "-B", str(Path(__file__).resolve().parents[1] / "scripts/kb/intent-guardian.py"),
                   "rebuild-host-observations", "--provider", "codex", "--session-id", "one"]
        environment = {**os.environ, "SULDE_KB_HOME": str(self.home), "CODEX_THREAD_ID": "one"}
        result = subprocess.run(command, env=environment, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "complete")
        invalid = subprocess.run(command + ["--max-bytes", "-1"], env=environment,
                                 text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=30)
        self.assertEqual(invalid.returncode, 1, invalid.stderr)
        self.assertEqual(json.loads(invalid.stdout)["status"], "inconclusive")
        self.assertEqual(host.observation_path(self.home).read_bytes(), original)

    def test_lock_contention_does_not_stop_observation_or_lose_the_append(self):
        self.record("SessionStart")
        with mock.patch.object(index, "lock_exclusive_nonblocking", side_effect=BlockingIOError):
            prompt = self.record("UserPromptSubmit")
        result = self.projection()
        self.assertEqual(result["capabilities"]["prompt_control"]["last_observed_at"], prompt["at"])

    def test_repeated_delivery_does_not_duplicate_source(self):
        self.record("SessionStart")
        path = host.observation_path(self.home)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        self.record("SessionStart")
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_explicit_rebuild_recovers_a_legacy_start_and_resumes(self):
        with mock.patch.object(index, "publish_index", return_value=False):
            self.record("SessionStart", at=self.now - timedelta(days=2))
        self.flood()
        log = host.observation_path(self.home)
        original = hashlib.sha256(log.read_bytes()).hexdigest()
        self.assertEqual(self.projection()["capabilities"]["session_context"]["status"], "unobserved")
        options = dict(key=host._read_provenance_key(self.home),
                       validate=lambda row: host._valid_observation(row, self.home), max_bytes=1024 * 1024)
        first = index.rebuild_step(self.home, "codex", "one", **options)
        self.assertEqual(first["status"], "in_progress")
        offset = first["offset"]
        for _ in range(8):
            result = index.rebuild_step(self.home, "codex", "one", **options)
            self.assertGreaterEqual(result["offset"], offset)
            offset = result["offset"]
            if result["status"] == "complete":
                break
        self.assertEqual(result["status"], "complete")
        self.assertEqual(self.projection()["capabilities"]["session_context"]["status"], "live_verified")
        self.assertEqual(hashlib.sha256(log.read_bytes()).hexdigest(), original)

    def test_rebuild_rejects_changed_prefix_and_keeps_source(self):
        self.record("SessionStart")
        self.flood()
        options = dict(key=host._read_provenance_key(self.home),
                       validate=lambda row: host._valid_observation(row, self.home), max_bytes=1024)
        index.rebuild_step(self.home, "codex", "one", **options)
        log = host.observation_path(self.home)
        with log.open("r+b") as handle:
            handle.write(b"!")
        altered = log.read_bytes()
        with self.assertRaisesRegex(ValueError, "prefix changed"):
            index.rebuild_step(self.home, "codex", "one", **options)
        self.assertEqual(log.read_bytes(), altered)

    def switch_fixture(self, *, transition_session="one", future=False):
        source_workspace = self.workspace
        self.record("SessionStart", at=self.now - timedelta(hours=1))
        self.record("UserPromptSubmit", at=self.now - timedelta(minutes=1))
        self.workspace = source_workspace.parent / "task-worktree"
        self.workspace.mkdir()
        at = self.now + timedelta(seconds=5) if future else self.now - timedelta(seconds=40)
        mapping = {"provider": "codex", "session_id": transition_session,
                   "workspace_root": str(self.workspace), "bound_at": at.isoformat(),
                   "mapping_sha256": "c" * 64}
        # Unit projection fixture only; actual committed mapping/CLI coverage is
        # in the workspace/native integration tests, not fabricated live proof.
        with mock.patch.object(lineage, "_committed_mapping_matches", return_value=True):
            self.assertTrue(lineage.record_transition(
                self.home, provider="codex", session_id=transition_session,
                source_workspace=str(source_workspace), mapping=mapping, receipt_id="unit-only-receipt",
            ))
        self.record("PreToolUse", at=self.now - timedelta(seconds=30), call="after-handoff", runtime="b" * 64)
        self.record("PostToolUse", at=self.now - timedelta(seconds=20), call="after-handoff", runtime="b" * 64)

    def test_committed_handoff_and_current_roundtrip_carry_only_lifecycle(self):
        self.switch_fixture()
        result = self.projection(runtime="b" * 64)
        self.assertEqual(result["workspace_continuity"]["status"], "verified")
        self.assertEqual(result["capabilities"]["session_context"]["runtime_binding"], "verified_workspace_continuity")
        self.assertEqual(result["capabilities"]["session_context"]["status"], "live_verified")
        self.assertEqual(result["capabilities"]["host_approval"]["status"], "unobserved")
        self.assertFalse(result["workspace_continuity"]["authority_transferred"])

    def test_other_session_handoff_cannot_supply_continuity(self):
        self.switch_fixture(transition_session="two")
        result = self.projection(runtime="b" * 64)
        self.assertNotEqual(result["capabilities"]["session_context"]["status"], "live_verified")

    def test_start_prompt_and_roundtrip_can_each_have_a_different_generation(self):
        self.record("SessionStart", at=self.now - timedelta(days=2), runtime="a" * 64)
        self.record("UserPromptSubmit", at=self.now - timedelta(hours=2), runtime="b" * 64)
        self.record("PreToolUse", at=self.now - timedelta(seconds=30), call="third", runtime="c" * 64)
        self.record("PostToolUse", at=self.now - timedelta(seconds=20), call="third", runtime="c" * 64)
        result = self.projection(runtime="c" * 64)
        for capability in ("session_context", "prompt_control"):
            self.assertEqual(result["capabilities"][capability]["status"], "live_verified")
        self.assertEqual(result["capabilities"]["session_context"]["carried_from_runtime_sha256"], "a" * 64)
        self.assertEqual(result["capabilities"]["prompt_control"]["carried_from_runtime_sha256"], "b" * 64)
        self.assertNotEqual(result["capabilities"]["host_approval"]["status"], "live_verified")

    def test_missing_start_does_not_hide_an_independently_verified_prompt(self):
        self.record("UserPromptSubmit", at=self.now - timedelta(minutes=1))
        self.record("PreToolUse", at=self.now - timedelta(seconds=30), call="next", runtime="b" * 64)
        self.record("PostToolUse", at=self.now - timedelta(seconds=20), call="next", runtime="b" * 64)
        result = self.projection(runtime="b" * 64)
        self.assertEqual(result["capabilities"]["session_context"]["status"], "unobserved")
        self.assertEqual(result["capabilities"]["prompt_control"]["status"], "live_verified")

    def test_stop_in_same_session_other_workspace_ends_prompt(self):
        self.record("SessionStart", at=self.now - timedelta(minutes=4))
        self.record("UserPromptSubmit", at=self.now - timedelta(minutes=3))
        original = self.workspace
        self.workspace = self.workspace.parent / "intermediate"
        self.workspace.mkdir()
        self.record("Stop", at=self.now - timedelta(minutes=2), runtime="b" * 64)
        self.workspace = original
        self.record("PreToolUse", at=self.now - timedelta(seconds=30), call="third", runtime="c" * 64)
        self.record("PostToolUse", at=self.now - timedelta(seconds=20), call="third", runtime="c" * 64)
        result = self.projection(runtime="c" * 64)
        self.assertNotEqual(result["capabilities"]["prompt_control"]["status"], "live_verified")

    def test_future_handoff_cannot_retroactively_validate_a_roundtrip(self):
        self.switch_fixture(future=True)
        result = self.projection(runtime="b" * 64)
        self.assertNotEqual(result["capabilities"]["session_context"]["status"], "live_verified")

    def test_corrupt_lineage_cannot_make_readiness_green(self):
        self.switch_fixture()
        path = lineage.lineage_path(self.home, "codex", "one")
        value = json.loads(path.read_text())
        value["signature"] = "0" * 64
        path.write_text(json.dumps(value))
        result = self.projection(runtime="b" * 64)
        self.assertEqual(result["workspace_continuity"]["status"], "invalid")
        self.assertNotEqual(result["capabilities"]["session_context"]["status"], "live_verified")

    def test_bad_row_types_do_not_crash_the_readonly_projection(self):
        self.record("SessionStart")
        with host.observation_path(self.home).open("ab") as handle:
            handle.write(json.dumps({"provider": "codex", "session_id": "one",
                                     "schema": host.OBSERVATION_SCHEMA, "source": []}).encode() + b"\n")
        result = self.projection()
        self.assertGreater(result["invalid_rows"], 0)

    @unittest.skipIf(os.name == "nt", "POSIX symlink fixture")
    def test_index_symlink_is_never_followed_or_written(self):
        target = self.home / "unrelated"
        target.write_text("unchanged", encoding="utf-8")
        path = index.index_path(self.home, "codex", "one")
        path.parent.mkdir()
        path.symlink_to(target)
        self.record("SessionStart")
        self.assertEqual(target.read_text(encoding="utf-8"), "unchanged")


if __name__ == "__main__":
    unittest.main()
