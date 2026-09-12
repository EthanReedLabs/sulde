"""History reconstruction unit fixtures; never represented as live host proof."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/kb"))
import host_capabilities as host
import session_lifecycle_history as history
import session_lifecycle_lineage as lineage
from intent_guardian_parts.session_workspace import _canonical_sha256


class HistoricalLineageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "kb"
        self.intents = self.home / "intent/sessions"
        self.intents.mkdir(parents=True)
        host.provision_provenance_key(self.home)
        self.now = datetime.now(timezone.utc) - timedelta(minutes=5)
        self.mapping = {"provider": "codex", "session_id": "one", "mapping_sha256": "a" * 64}
        self.route = mock.patch("intent_guardian_parts.session_workspace.load_session_workspace", return_value=self.mapping)
        self.route.start()
        self.addCleanup(self.route.stop)
        self.addCleanup(self.temp.cleanup)

    def pair(self, number=0, provider="codex", session="one"):
        source = self.intents / f"source-{number}.active.json"
        anchor = self.intents / f"anchor-{number}.active.json"
        subject = {"schema": "sulde-workspace-cleanup-v1", "provider": provider, "session_id": session,
                   "source_contract": str(source), "source_workspace": f"/fixture/task-{number}",
                   "source_git_common_dir": "/fixture/.git", "source_branch": f"task/{number}",
                   "source_head": "b" * 40, "target_workspace": "/fixture/dev", "target_branch": "dev",
                   "target_head": "b" * 40, "authority_transferred": False, "git_mutation_performed": False}
        release = _canonical_sha256(subject)
        record = {**subject, "release_id": release, "release_subject_sha256": release, "status": "complete",
                  "released_at": self.now.isoformat(), "completed_at": (self.now + timedelta(seconds=2)).isoformat(),
                  "completion_evidence_sha256": _canonical_sha256({"release_id": release,
                      "source_workspace_exists": False, "source_worktree_registered": False, "source_branch_exists": False})}
        source_data = {"schema": "sulde-intent-contract-v1", "workspace_root": subject["source_workspace"], "status": "closed",
                       "workspace_release": {"schema": "sulde-workspace-release-source-v1", "authority_transferred": False,
                           "completion_contract": str(anchor), "provider": provider, "session_id": session,
                           "release_id": release, "released_at": (self.now + timedelta(seconds=1)).isoformat()}}
        anchor_data = {"schema": "sulde-intent-contract-v1", "workspace_root": subject["target_workspace"], "workspace_cleanup": record}
        source.write_text(json.dumps(source_data), encoding="utf-8")
        anchor.write_text(json.dumps(anchor_data), encoding="utf-8")
        return source, anchor

    def recover(self, **kwargs):
        return history.recover_history(self.home, provider="codex", session_id="one", **kwargs)

    def alter(self, path, callback):
        data = json.loads(path.read_text(encoding="utf-8"))
        callback(data)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_completed_release_is_rebuilt_without_source_mutation_and_idempotent(self):
        source, anchor = self.pair()
        before = {path: path.read_bytes() for path in (source, anchor)}
        self.assertEqual(self.recover(dry_run=True)["status"], "planned")
        path = lineage.lineage_path(self.home, "codex", "one")
        self.assertFalse(path.exists())
        first = self.recover()
        self.assertEqual(first["added_edges"], 1, first)
        index_before = path.read_bytes()
        self.assertEqual(self.recover()["added_edges"], 0)
        self.assertEqual(path.read_bytes(), index_before)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        edges = lineage._read(self.home, "codex", "one", host._read_provenance_key(self.home))
        self.assertNotIn("mapping_sha256", edges[0])  # never invent an old mapping
        self.assertFalse(edges[0]["authority_transferred"])

    def test_other_provider_and_session_are_not_borrowed(self):
        self.pair(0, session="two")
        self.pair(1, provider="claude")
        self.assertEqual(self.recover()["added_edges"], 0)

    def test_deleted_worktree_identity_does_not_collapse_to_its_parent_repository(self):
        repository = self.home / "repository"
        (repository / ".git").mkdir(parents=True)
        deleted = str(repository / ".worktrees/deleted-task")
        # The live discovery helper deliberately resolves upward; historical
        # identities must instead retain the exact recorded physical root.
        self.assertEqual(host.workspace_identifier(deleted), host.workspace_identifier(repository))
        self.assertNotEqual(history._recorded_workspace_id(deleted), host.workspace_identifier(repository))
        source, anchor = self.pair()
        self.alter(source, lambda d: d.update(workspace_root=deleted))
        data = json.loads(anchor.read_text())
        record = data["workspace_cleanup"]
        record["source_workspace"] = deleted
        subject = {k: v for k, v in record.items() if k not in {
            "release_id", "release_subject_sha256", "status", "released_at", "completed_at", "completion_evidence_sha256"}}
        record["release_id"] = record["release_subject_sha256"] = _canonical_sha256(subject)
        record["completion_evidence_sha256"] = _canonical_sha256({"release_id": record["release_id"],
            "source_workspace_exists": False, "source_worktree_registered": False, "source_branch_exists": False})
        anchor.write_text(json.dumps(data))
        self.alter(source, lambda d: d["workspace_release"].update(release_id=record["release_id"]))
        result = self.recover(dry_run=True)
        self.assertEqual(result["verified_edges"][0]["source_workspace_id"], history._recorded_workspace_id(deleted), result)

    def test_pending_release_or_allow_alone_is_not_a_committed_transition(self):
        _source, anchor = self.pair()
        self.alter(anchor, lambda d: d["workspace_cleanup"].update(
            status="pending", completed_at="", completion_evidence_sha256=""))
        self.assertEqual(self.recover()["added_edges"], 0)
        self.alter(anchor, lambda d: d.update(runtime={"approval_receipts": [{"action": "handoff-workspace", "outcome": "allow"}]}))
        self.assertEqual(self.recover()["added_edges"], 0)

    def test_invalid_counterparts_and_digest_never_publish(self):
        source, anchor = self.pair()
        original_source, original_anchor = source.read_bytes(), anchor.read_bytes()
        cases = [(source, lambda d: d.update(status="active")),
                 (source, lambda d: d["workspace_release"].update(session_id="two")),
                 (source, lambda d: d["workspace_release"].update(authority_transferred=True)),
                 (source, lambda d: d["workspace_release"].update(completion_contract="/elsewhere")),
                 (anchor, lambda d: d["workspace_cleanup"].update(release_subject_sha256="f" * 64)),
                 (anchor, lambda d: d["workspace_cleanup"].update(completed_at=12)),
                 (anchor, lambda d: d["workspace_cleanup"].update(completed_at=(self.now-timedelta(days=1)).isoformat()))]
        for path, change in cases:
            with self.subTest(path=path.name):
                source.write_bytes(original_source)
                anchor.write_bytes(original_anchor)
                self.alter(path, change)
                self.assertEqual(self.recover()["status"], "inconclusive")
                self.assertFalse(lineage.lineage_path(self.home, "codex", "one").exists())

    def test_missing_and_symlinked_counterpart_fail_closed(self):
        source, _anchor = self.pair()
        raw = source.read_bytes()
        source.unlink()
        self.assertEqual(self.recover()["status"], "inconclusive")
        elsewhere = self.home / "elsewhere"
        elsewhere.write_bytes(raw)
        source.symlink_to(elsewhere)
        self.assertEqual(self.recover()["status"], "inconclusive")
        self.assertEqual(elsewhere.read_bytes(), raw)

    def test_cas_and_lock_contention_keep_previous_projection(self):
        self.pair()
        self.assertEqual(self.recover()["added_edges"], 1)
        path = lineage.lineage_path(self.home, "codex", "one")
        before = path.read_bytes()
        self.pair(1)
        with mock.patch.object(history.Snapshot, "unchanged", return_value=False):
            self.assertEqual(self.recover()["status"], "inconclusive")
        with mock.patch.object(history, "lock_exclusive_nonblocking", side_effect=BlockingIOError):
            self.assertEqual(self.recover()["status"], "inconclusive")
        with mock.patch("intent_guardian_parts.session_workspace.load_session_workspace",
                        side_effect=[self.mapping, {**self.mapping, "mapping_sha256": "c" * 64}]):
            self.assertEqual(self.recover()["status"], "inconclusive")
        self.assertEqual(path.read_bytes(), before)

    def test_inventory_and_file_budgets_fail_without_partial_publish(self):
        self.pair()
        for name, limit in (("MAX_CONTRACTS", 1), ("MAX_FILE_BYTES", 5), ("MAX_TOTAL_BYTES", 5)):
            with self.subTest(name=name), mock.patch.object(history, name, limit):
                self.assertEqual(self.recover()["status"], "inconclusive")
                self.assertFalse(lineage.lineage_path(self.home, "codex", "one").exists())

    def test_concurrent_recovery_is_retryable_and_publishes_each_edge_once(self):
        self.pair()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.recover(), range(2)))
        self.assertTrue(any(row["status"] == "recovered" for row in results), results)
        self.assertEqual(self.recover()["added_edges"], 0)
        self.assertEqual(len(lineage._read(self.home, "codex", "one", host._read_provenance_key(self.home))), 1)

    def test_signed_but_malformed_derived_edge_does_not_supply_continuity(self):
        self.pair()
        self.recover()
        key = host._read_provenance_key(self.home)
        path = lineage.lineage_path(self.home, "codex", "one")
        original = lineage._read(self.home, "codex", "one", key)[0]
        for field, value in (("commit_evidence_sha256", "z" * 64), ("receipt_sha256", True),
                             ("source_workspace_id", {}), ("target_workspace_id", "sha256:bad")):
            with self.subTest(field=field):
                history._atomic_signed(path, {"schema": lineage.SCHEMA, "provider": "codex", "session_id": "one",
                                             "edges": [{**original, field: value}]}, key)
                result = lineage.predecessor_workspaces(self.home, provider="codex", session_id="one",
                    target_workspace_id=original["target_workspace_id"], before=datetime.now(timezone.utc))
                self.assertEqual(result, ({}, "invalid"))
                self.assertEqual(self.recover()["status"], "inconclusive")


if __name__ == "__main__":
    unittest.main()
