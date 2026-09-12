import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "kb-index"))

from corpus_manifest import (
    ManifestError,
    build_manifest,
    document_sha256,
    load_manifest,
    write_manifest,
)


class CorpusManifestTest(unittest.TestCase):
    def test_lf_and_crlf_have_the_same_document_hash(self) -> None:
        self.assertEqual(document_sha256(b"a\nb\n"), document_sha256(b"a\r\nb\r\n"))

    def test_manifest_round_trip_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            relative = Path("knowledge/work-model/example.md")
            target = root / relative
            target.parent.mkdir(parents=True)
            target.write_text("---\ndoc_id: example\n---\n# Example\n", encoding="utf-8")
            manifest = build_manifest(root, [relative])
            write_manifest(root, manifest)
            first = (root / "knowledge" / "MANIFEST.json").read_bytes()
            write_manifest(root, manifest)
            self.assertEqual(first, (root / "knowledge" / "MANIFEST.json").read_bytes())
            self.assertEqual(load_manifest(root), manifest)

    def test_rejects_parent_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "knowledge" / "MANIFEST.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "schema_version": 1,
                "documents": [{"path": "knowledge/../secret.md", "sha256": "0" * 64}],
                "document_count": 1,
                "corpus_sha256": "0" * 64,
            }), encoding="utf-8")
            with self.assertRaises(ManifestError):
                load_manifest(root, verify_files=False)

    def test_rejects_casefold_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "knowledge" / "MANIFEST.json"
            path.parent.mkdir(parents=True)
            documents = [
                {"path": "knowledge/work-model/Foo.md", "sha256": "1" * 64},
                {"path": "knowledge/work-model/foo.md", "sha256": "2" * 64},
            ]
            path.write_text(json.dumps({
                "schema_version": 1,
                "documents": documents,
                "document_count": 2,
                "corpus_sha256": "0" * 64,
            }), encoding="utf-8")
            with self.assertRaisesRegex(ManifestError, "collision"):
                load_manifest(root, verify_files=False)

    def test_rejects_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            relative = Path("knowledge/tech-docs/example.md")
            target = root / relative
            target.parent.mkdir(parents=True)
            target.write_text("first\n", encoding="utf-8")
            write_manifest(root, build_manifest(root, [relative]))
            target.write_text("second\n", encoding="utf-8")
            with self.assertRaisesRegex(ManifestError, "sha256 mismatch"):
                load_manifest(root)


if __name__ == "__main__":
    unittest.main()
