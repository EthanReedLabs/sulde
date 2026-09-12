from __future__ import annotations
from contextlib import closing
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
sys.path.insert(0, str(ROOT / "scripts/kb"))
import life_health
from sulde_paths import sync_repository_path, SuldePathError


def load(name):
    spec = importlib.util.spec_from_file_location("closure_" + name, ROOT / "scripts/kb" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LifeHealthClosureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "kb"
        self.home.mkdir()
        self.env = {**os.environ, "SULDE_HOME": str(self.root), "SULDE_KB_HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"}

    def tearDown(self):
        self.tmp.cleanup()

    def command(self, argv, **kwargs):
        return subprocess.run(argv, env=self.env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40, **kwargs)

    def test_window_increment_total_and_unknown_are_distinct(self):
        heartbeat = load("heartbeat")
        db = self.home / "memory.db"
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute("CREATE TABLE mem_entries(project TEXT, ts TEXT)")
            conn.execute("CREATE TABLE mem_edges(ts TEXT)")
            conn.executemany("INSERT INTO mem_entries VALUES (?,?)", [("one", "2026-01-01"), ("two", "2026-02-01")])
            conn.execute("INSERT INTO mem_edges VALUES ('2026-01-01')")
        result = heartbeat.database_increment(db, "2026-01-15")
        self.assertEqual((result["mem_entries"]["count"], result["total_entries"]), (1, 2))
        self.assertEqual((result["mem_edges"]["count"], result["total_edges"]), (0, 1))
        self.assertIsNone(heartbeat.database_increment(self.home / "missing.db", None)["mem_entries"]["count"])

    def test_real_heartbeat_compresses_once_and_preserves_fixed_self(self):
        heartbeat = load("heartbeat")
        original = (ROOT / "templates/SELF.md").read_text()
        (self.home / "SELF.md").write_text(original)
        counter = self.home / "llm-count"
        stub = self.root / "llm.py"
        stub.write_text("import json,sys\nfrom pathlib import Path\n" +
                        f"p=Path({str(counter)!r}); n=int(p.read_text())+1 if p.exists() else 1; p.write_text(str(n))\n" +
                        f"original={original!r}\n" +
                        "sys.stdin.read()\nprint(json.dumps({'self_md':original+('x'*9000 if n==1 else ''),'observation':'bounded facts'}))\n")
        result = self.command([sys.executable, "-B", str(ROOT / "scripts/kb/heartbeat.py"), "--beat", "--observe-only", "--llm-cmd", f'{sys.executable} {stub}'])
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads((self.home / "heartbeat-state.json").read_text())
        self.assertEqual(counter.read_text(), "2")
        self.assertEqual(state["compression_attempts"], 1)
        self.assertEqual(state["last_mode"], "result", result.stdout)
        self.assertEqual(heartbeat.fixed_self((self.home / "SELF.md").read_text()), heartbeat.fixed_self(original))

    def test_failed_compression_preserves_old_self_without_prompt_leak(self):
        heartbeat = load("heartbeat")
        original = (ROOT / "templates/SELF.md").read_text()
        (self.home / "SELF.md").write_text(original)
        payload = json.dumps({"self_md": original + "x" * 9000, "observation": "facts"})
        sense = ({"memory": {"status": "unavailable", "mem_entries": {"count": None, "projects": {}}, "mem_edges": {"count": None}}, "logs": {}, "governance": {}}, {})
        with mock.patch.object(heartbeat, "sense", return_value=sense), mock.patch.object(heartbeat, "run_llm", return_value=payload) as llm:
            heartbeat.run_beat(self.home, type("Args", (), {"dry_run": False, "observe_only": True, "llm_cmd": "fixture"})())
        self.assertEqual(llm.call_count, 2)
        self.assertEqual((self.home / "SELF.md").read_text(), original)
        failed = self.root / "fail.py"
        failed.write_text("import sys\nsys.stderr.write('PRIVATE_PROMPT_SENTINEL')\nraise SystemExit(1)\n")
        with self.assertRaises(heartbeat.HeartbeatError) as caught:
            heartbeat.run_llm(f"{sys.executable} {failed}", "PRIVATE_PROMPT_SENTINEL")
        self.assertNotIn("PRIVATE_PROMPT_SENTINEL", str(caught.exception))

    def test_real_failure_fix_independent_verify_close_and_reopen(self):
        repo = self.root / "fixture-repo"
        repo.mkdir()
        script = repo / "hook.py"
        script.write_text("raise RuntimeError('fixture fault')\n")
        observer = ROOT / "integrations/codex/plugins/sulde/scripts/_hook_observer.py"
        def execute(call):
            return self.command([sys.executable, "-B", str(observer), "--hook", "fixture", "--stage", "adapter", "--", sys.executable, "-B", str(script)],
                                input=json.dumps({"session_id": "fixture", "cwd": str(repo), "call_id": call}))
        self.assertEqual(execute("initial").returncode, 1)
        discovered = life_health.aggregate(self.home)["problems"][0]
        key = discovered["id"]
        self.assertEqual(discovered["occurrences"], 1)
        self.assertEqual(life_health.aggregate(self.home)["problems"][0]["occurrences"], 1)
        # Real repair commit and a separate regression, not a constructed proof.
        script.write_text("VALUE = 42\n")
        regression = repo / "verify.py"
        regression.write_text("import hook\nassert hook.VALUE == 42\n")
        for args in (["init", "-q"], ["add", "."], ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fix fixture"]):
            result = self.command(["git", "-C", str(repo), *args])
            self.assertEqual(result.returncode, 0, result.stderr)
        commit = self.command(["git", "-C", str(repo), "rev-parse", "HEAD"]).stdout.strip()
        with mock.patch.dict(os.environ, self.env):
            closed = life_health.verify_problem(self.home, key, command=[sys.executable, "-B", "verify.py"], repair_commit=commit, source_root=repo)
        self.assertEqual(closed["status"], "closed")
        script.write_text("raise RuntimeError('fixture fault')\n")
        self.assertEqual(execute("recurrence").returncode, 1)
        reopened = life_health.aggregate(self.home)["problems"][0]
        self.assertEqual((reopened["status"], reopened["occurrences"]), ("open", 2))
        with closing(sqlite3.connect(self.home / "life/problems/ledger.sqlite3")) as conn:
            transitions = [r[0] for r in conn.execute("SELECT transition FROM history ORDER BY seq")]
            self.assertEqual(conn.execute("SELECT count(*) FROM processed").fetchone()[0], 2)
        self.assertEqual(transitions, ["discovered", "closed", "reopened"])

    def test_shared_sync_path_contract_and_queue_plan_are_read_only(self):
        repo = self.home / "mem-sync-repo"
        repo.mkdir()
        config = self.home / "mem-sync.json"
        config.write_text(json.dumps({"repo_path": "mem-sync-repo"}))
        self.assertEqual(sync_repository_path("mem-sync-repo", home=self.home), repo.resolve())
        self.assertEqual(life_health.sync_preflight(self.home)["status"], "local_ready")
        config.write_text(json.dumps({"repo_path": str(self.root / "legacy/mem-sync-repo")}))
        self.assertEqual(life_health.sync_preflight(self.home)["status"], "migration_required")
        with self.assertRaises(SuldePathError):
            sync_repository_path(str(self.root / "legacy/mem-sync-repo"), home=self.home)
        pending = self.home / "self-repair/pending.json"
        pending.parent.mkdir()
        raw = json.dumps([{"id": "one", "source": "same", "status": "pending"}, {"id": "two", "source": "same", "status": "pending"}])
        pending.write_text(raw)
        plan = life_health.queue_plan(self.home)
        self.assertEqual(plan["writes"], 0)
        self.assertEqual(len(plan["queues"]["self-repair/pending.json"]["duplicate_groups"]), 1)
        self.assertEqual(pending.read_text(), raw)

    def test_unavailable_observation_never_closes_problem(self):
        commit = 'a' * 40
        for status in ('unavailable', 'unobserved', 'saturated'):
            with self.subTest(status=status):
                original = {'id': 'fixture', 'status': 'open', 'last_event': 'original',
                            'evidence_status': 'observed'}
                with closing(life_health.connect(self.home)) as conn, conn:
                    conn.execute('INSERT OR REPLACE INTO problems VALUES (?,?)', ('fixture', json.dumps(original)))
                def run(argv, **kwargs):
                    text = commit if argv[-2:] == ['rev-parse', 'HEAD'] else ''
                    return subprocess.CompletedProcess(argv, 0, text, '')
                with mock.patch.object(life_health, 'aggregate', return_value={'observer_status': status}), mock.patch.object(
                    life_health.subprocess, 'run', side_effect=run
                ):
                    row = life_health.verify_problem(self.home, 'fixture', command=['fixture-verifier'],
                                                     repair_commit=commit, source_root=self.root)
                self.assertEqual(row['status'], 'open')
                self.assertNotEqual(row['evidence_status'], 'verified')
                self.assertEqual(row['verification']['status'], 'inconclusive')
                self.assertEqual(row['last_event'], 'original')

    def test_real_unreadable_observer_after_verifier_preserves_open_problem(self):
        recorder = life_health.observer()
        event = recorder.facts(hook='fixture', stage='runtime', payload={'call_id': 'failure'},
                               code=1, kind='nonzero_exit')
        self.assertTrue(recorder.record(event, self.home))
        life_health.aggregate(self.home)
        commit = 'a' * 40
        def run(argv, **kwargs):
            if argv[0] == 'fixture-verifier':
                recorder.database(self.home).write_bytes(b'corrupt fixture observer')
            return subprocess.CompletedProcess(argv, 0, commit if argv[-2:] == ['rev-parse', 'HEAD'] else '', '')
        with mock.patch.object(life_health.subprocess, 'run', side_effect=run):
            row = life_health.verify_problem(self.home, event['fingerprint'], command=['fixture-verifier'],
                                             repair_commit=commit, source_root=self.root)
        self.assertEqual(row['status'], 'open')
        self.assertEqual(row['verification']['status'], 'inconclusive')
        self.assertEqual(row['verification']['observation'], {'before': 'observed', 'after': 'unavailable'})
        self.assertEqual(row['last_event'], event['id'])

    def test_governance_retains_degraded_status_and_source_provenance(self):
        governance = load("governance-report")
        completed = subprocess.CompletedProcess([], 1, '{"ok":false,"missing_sources":["fixture"]}', '')
        with mock.patch.object(governance.subprocess, "run", return_value=completed):
            observed = governance.source(lambda: governance.collect_status(self.home), name="status", scope="fixture")
        self.assertEqual(observed["status"], "available")
        self.assertFalse(observed["data"]["ok"])
        self.assertEqual(observed["source"], "status")
        self.assertTrue(observed["collected_at"])
        missing = governance.source(lambda: (_ for _ in ()).throw(OSError("PRIVATE_PATH")), name="missing")
        self.assertNotIn("PRIVATE_PATH", json.dumps(missing))
        self.assertNotIn("data", missing)


if __name__ == "__main__":
    unittest.main()
