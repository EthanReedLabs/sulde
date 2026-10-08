"""Bounded relocation store snapshots, using disposable synthetic bytes only."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import tracemalloc
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/kb"))
from intent_guardian_parts import repository_relocation as r
from intent_guardian_parts.decision_types import IntentGuardianError


class RelocationStoreCapacityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def file(self, name, content=b"synthetic\n"):
        path = self.root / name
        path.write_bytes(content)
        path.chmod(0o600)
        return path

    def freeze(self, *paths):
        return r._frozen_store_bytes({"stores": [str(p) for p in paths]})

    def test_large_store_streams_without_increasing_index_limit(self):
        path = self.root / "large.events.jsonl"
        chunk = b'{"synthetic":"' + b'x' * (1024 * 1024 - 17) + b'"}\n'
        digest = hashlib.sha256()
        with path.open("wb") as stream:
            for _ in range(96):
                stream.write(chunk)
                digest.update(chunk)
        path.chmod(0o600)
        tracemalloc.start()
        try:
            result = self.freeze(path)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 8 * 1024**2)
        self.assertEqual(result, [{"path": str(path), "sha256": digest.hexdigest(), "mode": 0o600}])
        with self.assertRaisesRegex(IntentGuardianError, "index.*bounded"):
            r._index_digest(path)

    def test_missing_and_empty_store_keep_manifest_shape(self):
        empty = self.file("empty", b"")
        missing = self.root / "missing"
        self.assertEqual(self.freeze(empty, missing), [
            {"path":str(empty), "sha256":hashlib.sha256(b"").hexdigest(), "mode":0o600},
            {"path":str(missing), "sha256":"", "mode":None}])

    def test_per_file_and_total_limits_are_separate_and_inclusive(self):
        one, two = self.file("one", b"1234"), self.file("two", b"1234")
        with mock.patch.object(r, "MAX_STORE_BYTES", 4), mock.patch.object(r, "MAX_STORE_TOTAL_BYTES", 8):
            self.assertEqual(len(self.freeze(one, two)), 2)
            self.file("one", b"12345")
            with self.assertRaisesRegex(IntentGuardianError, "store.*per-file"):
                self.freeze(one)
        self.file("one", b"1234")
        with mock.patch.object(r, "MAX_STORE_TOTAL_BYTES", 7):
            with self.assertRaisesRegex(IntentGuardianError, "store.*total"):
                self.freeze(one, two)

    def test_symlink_hardlink_directory_and_wrong_owner_are_rejected(self):
        regular = self.file("regular")
        link = self.root / "symlink"
        link.symlink_to(regular)
        for path in (link, self.root):
            with self.subTest(path=path.name), self.assertRaises(IntentGuardianError):
                self.freeze(path)
        hard = self.root / "hard"
        os.link(regular, hard)
        with self.assertRaisesRegex(IntentGuardianError, "link"):
            self.freeze(regular)
        hard.unlink()
        with mock.patch.object(r.os, "getuid", return_value=os.getuid()+1):
            with self.assertRaisesRegex(IntentGuardianError, "owner"):
                self.freeze(regular)

    def test_append_truncate_replace_and_mode_drift_are_rejected(self):
        real_read = os.read
        for mutation in ("append", "truncate", "replace", "mode"):
            path = self.file(mutation, b"abc")
            touched = False
            def read(fd, size):
                nonlocal touched
                chunk = real_read(fd, size)
                if not touched:
                    touched = True
                    if mutation == "append":
                        with path.open("ab") as stream:
                            stream.write(b"changed")
                    elif mutation == "truncate":
                        path.write_bytes(b"")
                    elif mutation == "replace":
                        replacement = self.file("replacement", b"abc")
                        os.replace(replacement, path)
                    else:
                        path.chmod(0o400)
                return chunk
            with self.subTest(mutation=mutation), mock.patch.object(r.os, "read", side_effect=read):
                with self.assertRaisesRegex(IntentGuardianError, "store.*(changed|grew)"):
                    self.freeze(path)


if __name__ == "__main__":
    unittest.main()
