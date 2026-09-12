"""Graph truth and temporary-home production-path integration regressions."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


memory = module("quality_memory", "tools/kb-index/memory.py")
governance = module("quality_governance", "scripts/kb/governance-report.py")


class MemoryGraphQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.database = self.home / "memory.db"
        memory.initialize(self.database)
        self.db = memory.connect(self.database)
        self.addCleanup(self.db.close)

    def add(self, content):
        identifier = memory.add_entry(
            self.db, project="fixture", session_id="quality", source_host="codex",
            role="assistant", content=content, ts="2026-09-04T02:00:00+00:00")
        self.db.commit()
        return identifier

    def edge(self, identifier, src="SyntheticApplication", rel="定位为", dst="示例检索系统", **kwargs):
        return {"src": src, "rel": rel, "dst": dst, "entry_id": identifier, **kwargs}

    def annotate(self, edge):
        return memory.annotate_memory(self.db, {"edges": [edge], "extracted_by": "codex"})

    def test_annotation_preserves_explicit_source_bound_status(self):
        identifier = self.add("SyntheticApplication定位为示例检索系统。当前状态：PLANNED/NOT_READY")
        self.annotate(self.edge(identifier, truth_status="not_ready"))
        self.assertEqual(self.db.execute("SELECT truth_status FROM mem_edges").fetchone()[0], "not_ready")
        before = self.database.read_bytes()
        self.assertEqual(memory.memory_graph(self.db, "SyntheticApplication", current_facts_only=True), [])
        rows = memory.memory_graph(self.db, "SyntheticApplication", current_facts_only=False)
        self.assertEqual(rows[0]["truth_status"], "not_ready")
        self.assertFalse(rows[0]["verified_current"])
        self.assertEqual(self.database.read_bytes(), before)

    def test_current_facts_remain_visible_and_conflicting_reannotation_is_atomic(self):
        identifier = self.add("SyntheticApplication定位为示例检索系统。")
        self.annotate(self.edge(identifier, truth_status="current"))
        self.assertEqual(memory.memory_graph(self.db, "SyntheticApplication", current_facts_only=True)[0]["truth_status"], "current")
        proposed = self.add("计划：SyntheticApplication定位为示例检索系统。")
        with self.assertRaisesRegex(ValueError, "human review"):
            self.annotate(self.edge(proposed))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM mem_edges").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT entry_id FROM mem_edges").fetchone()[0], identifier)

    def test_material_causal_predicate_cannot_be_replaced_with_token_overlap(self):
        identifier = self.add("stale build 导致 iOS walkthrough probe 在没有最新 marker 的旧 app 上运行。")
        self.annotate(self.edge(identifier, "stale build", "导致", "iOS walkthrough probe"))
        self.assertEqual(memory.memory_graph(self.db, "stale build", current_facts_only=True), [])
        row = memory.memory_graph(self.db, "stale build", current_facts_only=False)[0]
        self.assertEqual(row["review_hint"]["predicate_object"], "uncertain")

    def test_modal_variants_and_current_positive_cases(self):
        for state in ("not_ready", "goal", "planned", "counterfactual", "uncertain", "current"):
            with self.subTest(state=state):
                text = "SyntheticApplication 已作为教练系统运行；另一个产品目标是支持视频。"
                identifier = self.add(text + state)
                self.annotate(self.edge(identifier, src=state, truth_status=state))
                row = memory.memory_graph(self.db, state)[0]
                self.assertEqual(row["truth_status"], state)
                self.assertEqual(len(memory.memory_graph(self.db, state, current_facts_only=True)),
                                 int(state == "current"))
                self.assertFalse(row["verified_current"])

    def test_legacy_read_is_readonly_and_migration_preserves_rows(self):
        legacy = self.home / "legacy.db"
        db = sqlite3.connect(legacy)
        db.executescript("""
            CREATE TABLE mem_entries(id INTEGER PRIMARY KEY, project TEXT, session_id TEXT,
                role TEXT, content TEXT, content_hash TEXT, ts TEXT, embedded INTEGER);
            CREATE TABLE mem_edges(id INTEGER PRIMARY KEY, src TEXT, rel TEXT, dst TEXT,
                entry_id INTEGER, extracted_by TEXT, confidence REAL, ts TEXT, UNIQUE(src,rel,dst));
            INSERT INTO mem_entries VALUES(1306,'fixture','s','assistant',
                'SyntheticApplication定位为示例检索系统。PLANNED/NOT_READY','h','2026-09-04T02:00:00Z',0);
            INSERT INTO mem_edges VALUES(1306,'SyntheticApplication','定位为','示例检索系统',1306,'codex',1,'2026-09-04T02:00:00Z');
        """)
        db.close()
        before = legacy.read_bytes()
        readonly = sqlite3.connect(f"file:{legacy}?mode=ro", uri=True)
        readonly.row_factory = sqlite3.Row
        self.assertEqual(len(memory.memory_graph(readonly, "SyntheticApplication")), 1)
        self.assertEqual(memory.memory_graph(readonly, "SyntheticApplication")[0]["truth_basis"], "unverified")
        self.assertEqual(len(memory.memory_graph(readonly, "SyntheticApplication", current_facts_only=False)), 1)
        readonly.close()
        self.assertEqual(before, legacy.read_bytes())
        migrated = memory.connect(legacy)
        memory.create_schema(migrated)
        migrated.commit()
        self.assertEqual(tuple(migrated.execute("SELECT id,src,rel,dst,entry_id,truth_status FROM mem_edges").fetchone()),
                         (1306, "SyntheticApplication", "定位为", "示例检索系统", 1306, "uncertain"))
        migrated.close()

    def test_pending_audit_candidate_is_metadata_without_projection_or_db_mutation(self):
        identifier = self.add("SyntheticApplication定位为示例检索系统。")
        self.annotate(self.edge(identifier, truth_status="current"))
        script = self.home / "audit_llm.py"
        script.write_text(
            'import json,re,sys\n'
            'p=sys.stdin.read(); i=int(re.search(r\'"id":\\s*(\\d+)\',p).group(1))\n'
            'print(json.dumps(dict(edge_id=i,verdict="unsupported",temporal_modal="supported",predicate_object="unsupported",reason="requires human semantic decision")))\n')
        env = {**os.environ, "SULDE_KB_HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"}
        before = self.database.read_bytes()
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/kb/graph-audit.py"),
                                 "--all", "--llm-cmd", f"{sys.executable} -B {script}"],
                                env=env, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(memory.memory_graph(self.db, "SyntheticApplication", current_facts_only=True)), 1)
        row = memory.memory_graph(self.db, "SyntheticApplication", current_facts_only=False)[0]
        self.assertEqual(row["truth_status"], "current")
        self.assertFalse(row["review_candidate"]["applied"])
        self.assertEqual(self.database.read_bytes(), before)
        candidate = next((self.home / "governance/graph-corrections").glob("*.json"))
        candidate.write_text("{}")
        self.assertEqual(len(memory.memory_graph(self.db, "SyntheticApplication", current_facts_only=True)), 1)


    def snapshot(self):
        return dict(self.db.execute(
            "SELECT g.*, e.content FROM mem_edges g LEFT JOIN mem_entries e ON e.id=g.entry_id"
        ).fetchone())

    def decision(self, **changes):
        edge = self.snapshot()
        payload = {
            "schema": "sulde-graph-review-decision-v1",
            "edge": memory.edge_identity(edge), "source_sha256": memory.graph_digest(edge["content"]),
            "decision": "accepted", "truth_status": "unsupported",
            "reviewer": "fixture-human", "reviewed_at": "2026-09-04T03:00:00Z",
        }
        payload.update(changes)
        digest = memory.graph_digest(payload)
        record = {**payload, "decision_sha256": digest}
        audit = module("quality_audit_writer", "scripts/kb/graph-audit.py")
        path = self.home / "governance/graph-decisions" / (digest + ".json")
        audit.write_immutable(path, record)
        self.assertEqual(json.loads(path.read_text()), record)
        return digest, path

    def current(self, *pins):
        return memory.memory_graph(self.db, "SyntheticApplication", current_facts_only=True,
                                   approved_decision_sha256=pins)

    def test_legacy_multi_edge_compatibility_before_and_after_idempotent_migration(self):
        legacy = self.home / "representative-legacy.db"
        db = sqlite3.connect(legacy)
        db.executescript("""
            CREATE TABLE mem_entries(id INTEGER PRIMARY KEY, project TEXT, session_id TEXT,
                role TEXT, content TEXT, content_hash TEXT, ts TEXT, embedded INTEGER);
            CREATE TABLE mem_edges(id INTEGER PRIMARY KEY, src TEXT, rel TEXT, dst TEXT,
                entry_id INTEGER, extracted_by TEXT, confidence REAL, ts TEXT, UNIQUE(src,rel,dst));
        """)
        sources = [
            "Hub uses SQLite for durable storage.", "Hub 通过队列执行任务。",
            "在本次发布中，Hub 已实现缓存。", "Hub 已上线；另一个产品计划增加视频。",
            "此前目标已完成，Hub 现在提供导出。", "Hub 当前可用。如果断网则显示缓存。",
            "Hub 曾经过期，现在已经更新。", "监控确认 Hub 的构建成功。",
            "Hub 为 probe 提供最新 marker。", "Hub定位为示例检索系统。PLANNED/NOT_READY",
            "stale build 导致 iOS walkthrough probe 在没有最新 marker 的旧 app 上运行。",
        ]
        for i, content in enumerate(sources, 1):
            db.execute("INSERT INTO mem_entries VALUES (?, 'fixture','s','assistant',?,?,'2026-09-04T02:00:00Z',0)",
                       (i, content, str(i)))
        triples = [
            ("uses", "SQLite"), ("执行方式", "队列"), ("支持", "缓存"),
            ("状态", "已上线"), ("支持", "导出"), ("离线显示", "缓存"),
            ("状态", "已更新"), ("构建结果", "成功"), ("提供", "最新 marker"),
            ("定位为", "示例检索系统"), ("导致", "iOS walkthrough probe"),
            ("适用于", "所有项目"),
        ]
        for i, (rel, dst) in enumerate(triples, 1):
            db.execute("INSERT INTO mem_edges VALUES (?, 'Hub',?,?,?, 'codex',0.9,'2026-09-04T02:00:00Z')",
                       (i, rel, dst, i if i < 12 else None))
        db.commit()
        originals = db.execute("SELECT * FROM mem_edges ORDER BY id").fetchall()
        db.close()
        before = legacy.read_bytes()
        readonly = sqlite3.connect(f"file:{legacy}?mode=ro", uri=True)
        readonly.row_factory = sqlite3.Row
        old = memory.memory_graph(readonly, "Hub", limit=20)
        readonly.close()
        self.assertEqual(legacy.read_bytes(), before)
        migrated = memory.connect(legacy)
        try:
            memory.create_schema(migrated)
            memory.create_schema(migrated)
            migrated.commit()
            new = memory.memory_graph(migrated, "Hub", limit=20)
            self.assertEqual(new, old)
            self.assertEqual(len(new), 12)
            self.assertEqual(memory.memory_graph(migrated, "Hub", limit=5), new[:5])
            self.assertEqual(len(memory.memory_graph(migrated, "Hub", project="other")), 0)
            self.assertEqual([tuple(row)[:8] for row in migrated.execute("SELECT * FROM mem_edges ORDER BY id")], originals)
            self.assertTrue(all(row["truth_basis"] == "unverified" and not row["verified_current"] for row in new))
            self.assertEqual(memory.memory_graph(migrated, "Hub", limit=20, current_facts_only=True), [])
        finally:
            migrated.close()

    def test_absent_status_is_not_promoted_even_with_literal_current_source(self):
        identifier = self.add("SyntheticApplication定位为示例检索系统。")
        self.annotate(self.edge(identifier))
        row = memory.memory_graph(self.db, "SyntheticApplication")[0]
        self.assertEqual(row["truth_basis"], "unverified")
        self.assertFalse(row["verified_current"])
        self.assertEqual(self.current(), [])

    def test_paraphrase_and_unrelated_modal_words_do_not_suppress_declared_current(self):
        identifier = self.add("SyntheticApplication 已作为教练系统投入使用。其他产品计划支持视频，目标明年上线。")
        self.annotate(self.edge(identifier, truth_status="current"))
        row = self.current()[0]
        self.assertEqual(row["truth_status"], "current")
        self.assertEqual(row["truth_basis"], "source_bound_declaration")
        self.assertEqual(row["review_hint"]["temporal_modal"], "uncertain")

    def test_exact_approved_decision_excludes_current_projection_without_mutation(self):
        identifier = self.add("SyntheticApplication定位为示例检索系统。")
        self.annotate(self.edge(identifier, truth_status="current"))
        pin, path = self.decision()
        before = self.database.read_bytes()
        immutable = path.read_bytes()
        self.assertEqual(len(self.current()), 1)  # A self-declared human is not authority.
        self.assertEqual(self.current(pin), [])
        rows = memory.memory_graph(self.db, "SyntheticApplication", approved_decision_sha256=(pin,))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["truth_basis"], "human_review")
        self.assertEqual(rows[0]["truth_status"], "unsupported")
        self.assertEqual(path.read_bytes(), immutable)
        self.assertEqual(self.database.read_bytes(), before)
        env = {**os.environ, "SULDE_KB_HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"}
        command = [sys.executable, "-B", str(ROOT / "tools/kb-index/memory.py"), "graph", "SyntheticApplication"]
        default = subprocess.run(command, env=env, text=True, capture_output=True,
                                 encoding="utf-8", errors="replace")
        current = subprocess.run(command + ["--current-facts-only", "--review-decision-sha256", pin],
                                 env=env, text=True, capture_output=True,
                                 encoding="utf-8", errors="replace")
        self.assertEqual((default.returncode, current.returncode), (0, 0))
        self.assertEqual(len(json.loads(default.stdout)), 1)
        self.assertEqual(json.loads(current.stdout), [])
        self.assertEqual(self.database.read_bytes(), before)

    def test_forged_and_tampered_decisions_cannot_hide_current(self):
        identifier = self.add("SyntheticApplication定位为示例检索系统。")
        self.annotate(self.edge(identifier, truth_status="current"))
        pin, path = self.decision()
        self.assertEqual(len(self.current()), 1)
        record = json.loads(path.read_text())
        record["reviewer"] = "forged-human"
        path.write_text(json.dumps(record))
        self.assertEqual(len(self.current(pin)), 1)
        payload = {k: v for k, v in record.items() if k != "decision_sha256"}
        forged = memory.graph_digest(payload)
        record["decision_sha256"] = forged
        path.with_name(forged + ".json").write_text(json.dumps(record))
        self.assertEqual(len(self.current(pin)), 1)

    def test_mismatched_identity_source_and_malformed_decisions_have_no_authority(self):
        identifier = self.add("SyntheticApplication定位为示例检索系统。")
        self.annotate(self.edge(identifier, truth_status="current"))
        edge = memory.edge_identity(self.snapshot())
        for changes in (
            {"source_sha256": "0" * 64}, {"edge": {**edge, "id": 1306}},
            {"edge": {**edge, "id": True}}, {"edge": {**edge, "entry_id": 407}},
            {"edge": {**edge, "dst": "different"}}, {"edge": {**edge, "ts": "stale"}},
            {"reviewer": ""}, {"reviewed_at": "2099-01-01T00:00:00Z"},
            {"reviewed_at": "yesterday"}, {"decision": "pending_human_review"},
            {"applied": False}, {"truth_status": ["current"]},
        ):
            with self.subTest(changes=changes):
                pin, _ = self.decision(**changes)
                self.assertEqual(len(self.current(pin)), 1)
        directory = self.home / "governance/graph-decisions"
        (directory / "broken.json").write_text("{broken")
        (directory / "array.json").write_text("[]")
        self.assertEqual(len(self.current()), 1)

    def test_source_change_invalidates_declared_and_human_current_authority(self):
        identifier = self.add("SyntheticApplication定位为示例检索系统。")
        self.annotate(self.edge(identifier))
        pin, _ = self.decision(truth_status="current")
        self.assertTrue(self.current(pin)[0]["verified_current"])
        self.db.execute("UPDATE mem_entries SET content='SyntheticApplication PLANNED/NOT_READY' WHERE id=?", (identifier,))
        self.db.commit()
        row = memory.memory_graph(self.db, "SyntheticApplication", approved_decision_sha256=(pin,))[0]
        self.assertEqual(row["truth_basis"], "unverified")
        self.assertEqual(self.current(pin), [])
        self.assertNotIn("review_decision", row)

    def test_rejected_or_conflicting_approved_decisions_do_not_apply_correction(self):
        identifier = self.add("SyntheticApplication定位为示例检索系统。")
        self.annotate(self.edge(identifier, truth_status="current"))
        rejected, _ = self.decision(decision="rejected")
        self.assertEqual(len(self.current(rejected)), 1)
        accepted, _ = self.decision()
        self.assertEqual(len(self.current(accepted, rejected)), 1)

    def test_old_truth_schema_remains_writable_without_status_invention(self):
        # The rejected candidate's CHECK constraint did not include unverified.
        self.db.execute("ALTER TABLE mem_edges RENAME TO old_edges")
        self.db.execute("""CREATE TABLE mem_edges (
            id INTEGER PRIMARY KEY, src TEXT, rel TEXT, dst TEXT, entry_id INTEGER,
            extracted_by TEXT, confidence REAL, ts TEXT,
            truth_status TEXT NOT NULL DEFAULT 'uncertain'
            CHECK(truth_status IN ('current','goal','planned','not_ready','counterfactual','uncertain','unsupported')),
            UNIQUE(src,rel,dst))""")
        self.db.commit()
        memory.create_schema(self.db)
        identifier = self.add("SyntheticApplication定位为示例检索系统。")
        self.annotate(self.edge(identifier))
        self.assertEqual(memory.memory_graph(self.db, "SyntheticApplication")[0]["truth_basis"], "unverified")
        self.assertEqual(self.current(), [])

    def test_pending_stale_or_malformed_candidates_do_not_override_current(self):
        identifier = self.add("SyntheticApplication定位为示例检索系统。")
        self.annotate(self.edge(identifier, truth_status="current"))
        audit = module("quality_candidate_writer", "scripts/kb/graph-audit.py")
        directory = self.home / "governance/graph-corrections"
        edge = self.snapshot()
        for changes in ({}, {"content": "stale"}, {"id": 407}, {"truth_status": "planned"}):
            candidate = memory.correction_candidate({**edge, **changes}, {"verdict": "unsupported"})
            audit.write_immutable(directory / (candidate["candidate_sha256"] + ".json"), candidate)
            self.assertEqual(len(self.current()), 1)
        self.assertIn("review_candidate", self.current()[0])
        (directory / "broken.json").write_text("{broken")
        self.assertEqual(len(self.current()), 1)

    def test_conflicting_batch_statuses_cannot_silently_drop_modality(self):
        identifier = self.add("SyntheticApplication定位为示例检索系统。PLANNED/NOT_READY")
        with self.assertRaisesRegex(ValueError, "conflicting batch"):
            memory.annotate_memory(self.db, {
                "extracted_by": "codex",
                "entities": [{"name": "SyntheticApplication", "type": "system"}],
                "edges": [self.edge(identifier, truth_status="current"),
                          self.edge(identifier, truth_status="not_ready")],
            })
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM mem_edges").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM mem_entities").fetchone()[0], 0)

    def test_invalid_status_or_missing_lineage_does_not_partially_annotate(self):
        for edge in (self.edge(9999), self.edge(None, truth_status="achieved")):
            with self.assertRaises(ValueError):
                memory.annotate_memory(self.db, {"entities": [{"name": "X", "type": "system"}], "edges": [edge], "extracted_by": "codex"})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM mem_entities").fetchone()[0], 0)

    def test_temporary_home_production_cli_and_governance_parsers(self):
        identifier = self.add("SyntheticApplication定位为示例检索系统。PLANNED/NOT_READY")
        env = {**os.environ, "SULDE_KB_HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"}
        command = [sys.executable, "-B", str(ROOT / "tools/kb-index/memory.py")]
        annotated = subprocess.run(command + ["annotate", "--json", json.dumps({
            "extracted_by": "codex", "edges": [self.edge(identifier, truth_status="not_ready")]
        })], env=env, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace")
        self.assertEqual(annotated.returncode, 0, annotated.stderr)
        before = self.database.read_bytes()
        current = subprocess.run(command + ["graph", "SyntheticApplication", "--current-facts-only"],
                                 env=env, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace")
        self.assertEqual(current.returncode, 0, current.stderr)
        self.assertEqual(json.loads(current.stdout), [])
        review = subprocess.run(command + ["graph", "SyntheticApplication", "--include-noncurrent"],
                                env=env, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
        self.assertEqual(review.returncode, 0, review.stderr)
        self.assertEqual(json.loads(review.stdout)[0]["truth_status"], "not_ready")
        self.assertEqual(before, self.database.read_bytes())
        candidates = self.home / "golden-candidates.jsonl"
        candidates.write_text("".join(json.dumps({
            "id": f"candidate-{i}", "query": "query", "project": "fixture",
            "expect_none": True, "note": "draft"
        }) + "\n" for i in range(24)))
        golden = self.home / "golden.jsonl"
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/kb/golden-review.py"),
                                 "--golden", str(golden), "--json"],
                                env=env, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["pending_review"], 24)
        # Exercise real collectors for graph audit, candidates and L2. External
        # unrelated command collectors are the only mocked boundaries.
        now = datetime.now(timezone.utc) + timedelta(seconds=1)
        with mock.patch.object(governance, "collect_status", return_value={}), \
             mock.patch.object(governance, "collect_fleet", return_value={}), \
             mock.patch.object(governance, "collect_kb_golden", return_value={}), \
             mock.patch.object(governance, "collect_mem_golden", return_value={}):
            snapshot = governance.collect(self.home, now)
        self.assertEqual(snapshot["sources"]["golden_candidates"]["data"]["raw_total"], 24)
        self.assertEqual(snapshot["sources"]["mem_edges"]["status"], "available")
        lights = governance.prepare_lights(snapshot, governance.load_thresholds(), self.home)
        pending = next(row for row in lights if row["metric"] == "golden_candidates_pending")
        self.assertEqual(pending["light"], "red")
        report = governance.fallback_report(snapshot, lights, "fixture: no external LLM")
        self.assertIn("pending_review", report)
        self.assertIn("start_utc", report)
        self.assertIn("knowledge_quality", report)
        governance.persist_governance_state(self.home, snapshot, lights)
        history = json.loads((self.home / "governance/history.jsonl").read_text().splitlines()[-1])
        self.assertIn("denominator", history["l2_observation"])
        self.assertNotIn("l2_coverage_rate", history["values"])


if __name__ == "__main__":
    unittest.main()
