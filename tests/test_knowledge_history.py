from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "kb-index"))
from corpus_manifest import build_manifest, write_manifest  # noqa: E402
from knowledge_history import (  # noqa: E402
    HISTORY_RELATIVE,
    HistoryError,
    build_history,
    canonical_history_sha256,
    load_history,
    render_history,
    write_history,
)


class KnowledgeHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.name", "Fixture"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.repo),
                "config",
                "user.email",
                "fixture@example.test",
            ],
            check=True,
        )
        self.paths = (
            Path("knowledge/anti-patterns/caf\u00e9.md"),
            Path("knowledge/tech-docs/portable.md"),
        )
        for index, relative in enumerate(self.paths):
            target = self.repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                "---\n"
                f'doc_id: "fixture/{index}"\n'
                "container: tech-docs\n"
                "platform: none\n"
                "---\n"
                f"# Fixture {index}\n",
                encoding="utf-8",
            )
        subprocess.run(["git", "-C", str(self.repo), "add", "knowledge"], check=True)
        environment = os.environ.copy()
        environment["GIT_AUTHOR_DATE"] = "2025-01-02T03:04:05+05:30"
        environment["GIT_COMMITTER_DATE"] = "2025-01-02T03:04:05+05:30"
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "fixture"],
            check=True,
            env=environment,
        )
        (self.repo / self.paths[1]).write_text(
            (self.repo / self.paths[1]).read_text(encoding="utf-8")
            + "\nUpdated later.\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "add", self.paths[1].as_posix()],
            check=True,
        )
        environment["GIT_AUTHOR_DATE"] = "2025-02-03T04:05:06-04:00"
        environment["GIT_COMMITTER_DATE"] = "2025-02-03T04:05:06-04:00"
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", "update one"],
            check=True,
            env=environment,
        )
        write_manifest(self.repo, build_manifest(self.repo, self.paths))
        self.history = build_history(self.repo, self.repo)
        write_history(self.repo, self.history)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def packaged_copy(self, name: str) -> Path:
        destination = Path(self.temporary.name) / name
        shutil.copytree(self.repo, destination, ignore=shutil.ignore_patterns(".git"))
        return destination

    def payload(self, root: Path) -> dict[str, object]:
        return json.loads((root / HISTORY_RELATIVE).read_text(encoding="utf-8"))

    def write_payload(
        self,
        root: Path,
        payload: dict[str, object],
        *,
        resign: bool,
    ) -> None:
        if resign:
            payload["history_sha256"] = canonical_history_sha256(payload)
        (root / HISTORY_RELATIVE).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_generation_is_deterministic_and_preserves_timezone(self) -> None:
        with mock.patch(
            "knowledge_history.subprocess.run",
            wraps=subprocess.run,
        ) as run:
            second = build_history(self.repo, self.repo)

        self.assertEqual(run.call_count, 1)
        self.assertEqual(render_history(self.history), render_history(second))
        self.assertEqual(len(self.history.history_sha256), 64)
        self.assertEqual(self.history.document_count, 2)
        timestamps = {
            document.path: document.last_commit_at
            for document in self.history.documents
        }
        self.assertEqual(
            timestamps[self.paths[0].as_posix()],
            "2025-01-02T03:04:05+05:30",
        )
        self.assertEqual(
            timestamps[self.paths[1].as_posix()],
            "2025-02-03T04:05:06-04:00",
        )
        loaded = load_history(self.repo)
        self.assertEqual(loaded, self.history)

    def test_missing_malformed_and_tampered_history_fail_closed(self) -> None:
        missing = self.packaged_copy("missing")
        (missing / HISTORY_RELATIVE).unlink()
        with self.assertRaisesRegex(HistoryError, "cannot read knowledge history"):
            load_history(missing)

        malformed = self.packaged_copy("malformed")
        (malformed / HISTORY_RELATIVE).write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(HistoryError, "cannot read knowledge history"):
            load_history(malformed)

        tampered = self.packaged_copy("tampered")
        payload = self.payload(tampered)
        payload["documents"][0]["last_commit_at"] = "2025-01-03T03:04:05+05:30"
        self.write_payload(tampered, payload, resign=False)
        with self.assertRaisesRegex(HistoryError, "self digest mismatch"):
            load_history(tampered)

    def test_duplicate_incomplete_and_out_of_order_documents_fail_closed(self) -> None:
        duplicate = self.packaged_copy("duplicate")
        payload = self.payload(duplicate)
        payload["documents"].append(dict(payload["documents"][0]))
        payload["document_count"] = len(payload["documents"])
        self.write_payload(duplicate, payload, resign=True)
        with self.assertRaisesRegex(HistoryError, "duplicate or colliding"):
            load_history(duplicate)

        incomplete = self.packaged_copy("incomplete")
        payload = self.payload(incomplete)
        payload["documents"].pop()
        payload["document_count"] = len(payload["documents"])
        self.write_payload(incomplete, payload, resign=True)
        with self.assertRaisesRegex(HistoryError, "do not match corpus manifest"):
            load_history(incomplete)

        unordered = self.packaged_copy("unordered")
        payload = self.payload(unordered)
        payload["documents"].reverse()
        self.write_payload(unordered, payload, resign=True)
        with self.assertRaisesRegex(HistoryError, "sorted by path"):
            load_history(unordered)

    def test_timezone_types_and_nfc_paths_are_strict(self) -> None:
        naive = self.packaged_copy("naive")
        payload = self.payload(naive)
        payload["documents"][0]["last_commit_at"] = "2025-01-02T03:04:05"
        self.write_payload(naive, payload, resign=True)
        with self.assertRaisesRegex(HistoryError, "lacks timezone"):
            load_history(naive)

        wrong_type = self.packaged_copy("wrong-type")
        payload = self.payload(wrong_type)
        payload["document_count"] = True
        self.write_payload(wrong_type, payload, resign=True)
        with self.assertRaisesRegex(HistoryError, "document_count mismatch"):
            load_history(wrong_type)

        nfd = self.packaged_copy("nfd")
        payload = self.payload(nfd)
        payload["documents"][0]["path"] = "knowledge/anti-patterns/cafe\u0301.md"
        self.write_payload(nfd, payload, resign=True)
        with self.assertRaisesRegex(HistoryError, "not NFC-normalized"):
            load_history(nfd)

    def test_corpus_document_hash_and_file_content_mismatches_fail_closed(self) -> None:
        corpus = self.packaged_copy("corpus")
        payload = self.payload(corpus)
        payload["corpus_sha256"] = "0" * 64
        self.write_payload(corpus, payload, resign=True)
        with self.assertRaisesRegex(HistoryError, "does not match corpus manifest"):
            load_history(corpus)

        document_hash = self.packaged_copy("document-hash")
        payload = self.payload(document_hash)
        payload["documents"][0]["sha256"] = "0" * 64
        self.write_payload(document_hash, payload, resign=True)
        with self.assertRaisesRegex(HistoryError, "do not match corpus manifest"):
            load_history(document_hash)

        content = self.packaged_copy("content")
        (content / self.paths[0]).write_text("tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(HistoryError, "sha256 mismatch"):
            load_history(content)


if __name__ == "__main__":
    unittest.main()
