from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
KB_AGING = ROOT / "scripts" / "kb" / "kb-aging.py"
sys.path.insert(0, str(ROOT / "tools" / "kb-index"))
from corpus_manifest import build_manifest, write_manifest  # noqa: E402
from knowledge_history import build_history, write_history  # noqa: E402


class KBAgingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.repo = base / "fixture-repo"
        self.home = base / "kb-home"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Fixture"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "fixture@example.test"], check=True)

        old = datetime.now(timezone.utc) - timedelta(days=120)
        self.write_document("knowledge/tech-docs/旧零采纳.md", "tech-docs/旧零采纳")
        self.write_document("knowledge/anti-patterns/0001-old-adopted.md", "ap-0001")
        self.commit("old documents", old)

        recent = datetime.now(timezone.utc) - timedelta(days=2)
        self.write_document("knowledge/work-model/recent.md", "work-model/recent")
        self.commit("recent document", recent)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_document(self, relative: str, doc_id: str) -> None:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"---\ndoc_id: {doc_id}\ncontainer: tech-docs\nplatform: none\n---\n# Fixture\n",
            encoding="utf-8",
        )

    def commit(self, message: str, timestamp: datetime) -> None:
        subprocess.run(["git", "-C", str(self.repo), "add", "knowledge"], check=True)
        env = os.environ.copy()
        rendered = timestamp.isoformat()
        env["GIT_AUTHOR_DATE"] = rendered
        env["GIT_COMMITTER_DATE"] = rendered
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", message],
            env=env,
            check=True,
        )

    def run_aging(
        self,
        *arguments: str,
        home: Path | None = None,
        repo: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        selected_home = home or self.home
        env = os.environ.copy()
        env["SULDE_KB_HOME"] = str(selected_home)
        return subprocess.run(
            [
                sys.executable,
                str(KB_AGING),
                "--repo",
                str(repo or self.repo),
                *arguments,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            check=False,
        )

    def packaged_repo(self, name: str) -> Path:
        paths = sorted(
            path.relative_to(self.repo)
            for path in (self.repo / "knowledge").rglob("*.md")
        )
        write_manifest(self.repo, build_manifest(self.repo, paths))
        write_history(self.repo, build_history(self.repo, self.repo))
        packaged = Path(self.temporary.name) / name
        subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import pathlib, shutil, sys; "
                    "source=pathlib.Path(sys.argv[1]); "
                    "destination=pathlib.Path(sys.argv[2]); "
                    "shutil.copytree(source, destination, "
                    "ignore=shutil.ignore_patterns('.git'))"
                ),
                str(self.repo),
                str(packaged),
            ],
            check=True,
        )
        return packaged

    def write_feedback(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": "fixture",
            "doc_id": "ap-0001",
            "event": "read_after_inject",
        }
        (self.home / "feedback-log.jsonl").write_text(
            json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    def test_fixture_reports_zero_adoption_and_stale_lists_with_adjustable_days(self) -> None:
        self.write_feedback()

        result = self.run_aging("--days", "90")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("zero_adoption_aged: 1", result.stdout)
        self.assertIn("stale_unupdated: 2", result.stdout)
        reports = list((self.home / "governance").glob("aging-*.md"))
        self.assertEqual(len(reports), 1)
        report = reports[0].read_text(encoding="utf-8")
        self.assertIn("tech-docs/旧零采纳", report)
        self.assertIn("ap-0001", report)
        zero_section = report.partition("## 零采纳且超龄")[2].partition("## 超龄未更新")[0]
        self.assertNotIn("ap-0001", zero_section)
        self.assertNotIn("work-model/recent", report)

        wider = self.run_aging("--days", "180", "--dry-run")
        self.assertEqual(wider.returncode, 0, wider.stderr)
        self.assertIn("zero_adoption_aged: 0", wider.stdout)
        self.assertIn("stale_unupdated: 0", wider.stdout)

    def test_dry_run_writes_nothing(self) -> None:
        self.write_feedback()

        result = self.run_aging("--dry-run")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("KB AGING RESULT: PASS", result.stdout)
        self.assertIn("details: dry-run (not written)", result.stdout)
        self.assertFalse((self.home / "governance").exists())

    def test_packaged_runtime_uses_validated_history_without_git(self) -> None:
        packaged = self.packaged_repo("packaged")
        self.assertFalse((packaged / ".git").exists())

        result = self.run_aging("--dry-run", repo=packaged)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("KB AGING RESULT: PASS", result.stdout)
        self.assertIn("documents: 3", result.stdout)
        self.assertFalse((self.home / "governance").exists())

    def test_packaged_runtime_rejects_missing_and_tampered_history(self) -> None:
        missing = self.packaged_repo("missing-history")
        (missing / "knowledge" / "HISTORY.json").unlink()
        result = self.run_aging("--dry-run", repo=missing)
        self.assertEqual(result.returncode, 2)
        self.assertIn("packaged knowledge history is invalid", result.stderr)

        tampered = self.packaged_repo("tampered-history")
        history = tampered / "knowledge" / "HISTORY.json"
        payload = json.loads(history.read_text(encoding="utf-8"))
        payload["documents"][0]["last_commit_at"] = "2000-01-01T00:00:00+00:00"
        history.write_text(json.dumps(payload), encoding="utf-8")
        result = self.run_aging("--dry-run", repo=tampered)
        self.assertEqual(result.returncode, 2)
        self.assertIn("packaged knowledge history is invalid", result.stderr)

    def test_missing_or_empty_feedback_degrades_to_file_age(self) -> None:
        for label in ("missing", "empty"):
            with self.subTest(label=label):
                isolated_home = Path(self.temporary.name) / f"{label}-home"
                if label == "empty":
                    isolated_home.mkdir()
                    (isolated_home / "feedback-log.jsonl").write_text("", encoding="utf-8")

                result = self.run_aging(home=isolated_home)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("feedback_signal: insufficient", result.stdout)
                reports = list((isolated_home / "governance").glob("aging-*.md"))
                self.assertEqual(len(reports), 1)
                report = reports[0].read_text(encoding="utf-8")
                self.assertIn("采纳信号不足,仅按文件年龄", report)
                self.assertIn("zero_adoption_aged", result.stdout)


if __name__ == "__main__":
    unittest.main()
