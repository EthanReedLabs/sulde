import subprocess
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "kb-index"))

from common import (  # noqa: E402
    chunks_for,
    create_schema,
    corpus_fingerprint,
    git_tracked_documents,
    parse_document,
    tracked_documents,
)


class TrackedDocumentsTest(unittest.TestCase):
    @staticmethod
    def write(root: Path, relative: Path) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")

    def test_enumerates_packaged_knowledge_without_git_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            included = [
                Path("knowledge/anti-patterns/0001-example.md"),
                Path("knowledge/platform-kb/android/example.md"),
            ]
            excluded = [
                Path("knowledge/INDEX.md"),
                Path("knowledge/platform-kb/README.md"),
                Path("knowledge/unsupported/example.md"),
                Path("knowledge/work-model/example.txt"),
            ]
            for relative in included + excluded:
                self.write(root, relative)

            try:
                documents = tracked_documents(root)
            except subprocess.CalledProcessError as error:
                self.fail(f"packaged knowledge enumeration required Git metadata: {error}")

            self.assertEqual(documents, included)

    def test_enumerates_package_nested_inside_an_enclosing_git_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            enclosing = Path(temp_dir)
            subprocess.run(
                ["git", "init", "-q", str(enclosing)],
                check=True,
                capture_output=True,
            )
            package = enclosing / "plugin-cache"
            included = Path("knowledge/work-model/example.md")
            self.write(package, included)

            self.assertEqual(tracked_documents(package), [included])

    def test_source_checkout_excludes_untracked_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            subprocess.run(
                ["git", "init", "-q", str(root)],
                check=True,
                capture_output=True,
            )
            tracked = Path("knowledge/tech-docs/tracked.md")
            untracked = Path("knowledge/tech-docs/untracked.md")
            self.write(root, tracked)
            self.write(root, untracked)
            subprocess.run(
                ["git", "-C", str(root), "add", tracked.as_posix()],
                check=True,
                capture_output=True,
            )

            self.assertEqual(tracked_documents(root), [tracked])

    def test_source_checkout_does_not_hide_broken_git_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            self.write(root, Path("knowledge/work-model/example.md"))

            with self.assertRaises(subprocess.CalledProcessError) as caught:
                tracked_documents(root)
            self.assertIsNotNone(caught.exception.stderr)
            self.assertIn(b"not a git repository", caught.exception.stderr)

    def test_manifest_wins_without_git_and_ignores_unlisted_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            listed = Path("knowledge/work-model/listed.md")
            unlisted = Path("knowledge/work-model/unlisted.md")
            self.write(root, listed)
            self.write(root, unlisted)
            from corpus_manifest import build_manifest, write_manifest

            write_manifest(root, build_manifest(root, [listed]))
            self.assertEqual(tracked_documents(root), [listed])

    def test_manifest_hash_drives_document_hash_and_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            relative = Path("knowledge/work-model/example.md")
            target = root / relative
            target.parent.mkdir(parents=True)
            target.write_text(
                "---\ndoc_id: x\ncontainer: work-model\nplatform: none\n---\n# X\n",
                encoding="utf-8",
                newline="\r\n",
            )
            from corpus_manifest import build_manifest, write_manifest

            manifest = build_manifest(root, [relative])
            write_manifest(root, manifest)
            self.assertEqual(
                parse_document(root, relative).sha256, manifest.documents[0].sha256
            )
            self.assertEqual(corpus_fingerprint(root), manifest.corpus_sha256)

    def test_v2_chunks_preserve_sample_roles_and_evidence_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            relative = Path("knowledge/work-model/example.md")
            target = root / relative
            target.parent.mkdir(parents=True)
            target.write_text(
                """---
doc_id: work-model/example
container: work-model
platform: none
summary: structured fixture
sedimentation_schema: 2
problem_type: workflow
evidence_status: verified
---
# Structured fixture
## 问题原型
具体任务里出现可观察偏差。
## 根因与证据
已经由测试证据确认根因。
## 适用边界
明确适用与不适用条件。
## 判定样本
### 路由正例
- **输入**：应该召回的输入
- **预期**：apply
- **原因**：命中全部条件
- **来源**：observed
### 路由反例
- **输入**：相似但不应召回
- **预期**：skip
- **原因**：缺少必要条件
- **来源**：constructed
### 执行合格例
- **做法或输出**：完整闭环
- **预期**：pass
- **原因**：证据完整
- **来源**：observed
### 执行失败例
- **做法或输出**：只有形式
- **预期**：fail
- **原因**：没有实质证据
- **来源**：observed
## 正确做法
按完整步骤执行并验证。
## 消费与防复发
进入实际 Skill 和回归测试。
""",
                encoding="utf-8",
            )

            document = parse_document(root, relative)
            chunks = chunks_for(document)

            self.assertEqual(document.problem_type, "workflow")
            self.assertEqual(document.evidence_status, "verified")
            roles = {chunk.role for chunk in chunks}
            self.assertTrue(
                {
                    "problem_context",
                    "route_positive",
                    "route_negative",
                    "outcome_positive",
                    "outcome_negative",
                    "solution",
                    "consumer",
                }.issubset(roles)
            )
            self.assertFalse(
                any(chunk.section == "判定样本" and chunk.role == "general" for chunk in chunks)
            )
            self.assertTrue(all(chunk.evidence_status == "verified" for chunk in chunks))

    def test_schema_migrates_legacy_chunks_with_semantic_columns(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.execute(
            """
            CREATE TABLE chunks (
                chunk_id TEXT PRIMARY KEY,
                doc_id TEXT NOT NULL,
                title TEXT NOT NULL,
                section TEXT NOT NULL,
                container TEXT NOT NULL,
                platform TEXT NOT NULL,
                source_path TEXT NOT NULL,
                text TEXT NOT NULL
            )
            """
        )
        create_schema(connection)
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(chunks)").fetchall()
        }
        connection.execute(
            """
            INSERT INTO chunks(
                chunk_id, doc_id, title, section, container, platform,
                source_path, text
            ) VALUES ('legacy#0000', 'legacy', '旧写入', '', 'tech-docs',
                      'none', 'knowledge/legacy.md', 'legacy body')
            """
        )
        defaults = connection.execute(
            "SELECT role, problem_type, evidence_status FROM chunks"
        ).fetchone()
        connection.close()

        self.assertTrue({"role", "problem_type", "evidence_status"}.issubset(columns))
        self.assertEqual(defaults, ("general", "", ""))


if __name__ == "__main__":
    unittest.main()
