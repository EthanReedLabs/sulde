import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KB_INDEX = ROOT / "tools" / "kb-index"
sys.path.insert(0, str(KB_INDEX))

from corpus_manifest import build_manifest, write_manifest  # noqa: E402


def load_module(name: str, relative: Path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {relative}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FingerprintConsumerTest(unittest.TestCase):
    def test_consumers_return_manifest_fingerprint_and_reject_changed_document(self) -> None:
        freshness = load_module("test_kb_freshness", Path("hooks/lib/kb_freshness.py"))
        status = load_module("test_sulde_status", Path("scripts/kb/sulde-status.py"))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            relative = Path("knowledge/work-model/example.md")
            target = root / relative
            target.parent.mkdir(parents=True)
            target.write_text("fixture\n", encoding="utf-8")
            expected = build_manifest(root, [relative])
            write_manifest(root, expected)

            self.assertEqual(
                freshness._corpus_fingerprint(root), expected.corpus_sha256
            )
            self.assertEqual(status.current_fingerprint(root), expected.corpus_sha256)

            target.write_text("changed\n", encoding="utf-8")
            self.assertIsNone(freshness._corpus_fingerprint(root))
            self.assertIsNone(status.current_fingerprint(root))


if __name__ == "__main__":
    unittest.main()
