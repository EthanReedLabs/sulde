from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "export_community.py"
SPEC = importlib.util.spec_from_file_location("export_community", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
EXPORT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EXPORT
SPEC.loader.exec_module(EXPORT)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ExportCommunityTest(unittest.TestCase):
    def write_manifest(self, root: Path, files: list[dict[str, str]]) -> Path:
        path = root / "manifest.json"
        path.write_text(
            json.dumps({"version": 1, "files": files}, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def test_manifest_rejects_traversal_and_duplicate_destinations(self) -> None:
        with tempfile.TemporaryDirectory(prefix="community-manifest-") as temp:
            root = Path(temp)
            unsafe = self.write_manifest(
                root,
                [
                    {
                        "destination": "../private.txt",
                        "mode": "100644",
                        "policy": "preserve",
                        "sha256": "0" * 64,
                    }
                ],
            )
            with self.assertRaises(EXPORT.ExportError):
                EXPORT.load_manifest(unsafe)

            duplicate = self.write_manifest(
                root,
                [
                    {
                        "destination": "README.md",
                        "mode": "100644",
                        "policy": "preserve",
                        "sha256": "0" * 64,
                    },
                    {
                        "destination": "README.md",
                        "mode": "100644",
                        "policy": "preserve",
                        "sha256": "1" * 64,
                    },
                ],
            )
            with self.assertRaises(EXPORT.ExportError):
                EXPORT.load_manifest(duplicate)

    def test_scan_checks_extensionless_content(self) -> None:
        with tempfile.TemporaryDirectory(prefix="community-scan-") as temp:
            root = Path(temp)
            launcher = root / "launcher"
            launcher.write_text("source=/Users/eric/ClaudePlugin/sulde-cc-pro\n", encoding="utf-8")
            with self.assertRaises(EXPORT.ExportError):
                EXPORT.scan_stage(root)

    def test_copy_and_preserve_are_both_digest_pinned(self) -> None:
        with tempfile.TemporaryDirectory(prefix="community-stage-") as temp:
            root = Path(temp)
            source = root / "source"
            target = root / "target"
            staged = root / "staged"
            source.mkdir()
            target.mkdir()
            (source / "shared.txt").write_text("shared\n", encoding="utf-8")
            (target / "community.txt").write_text("community\n", encoding="utf-8")
            manifest = self.write_manifest(
                root,
                [
                    {
                        "destination": "shared.txt",
                        "source": "shared.txt",
                        "mode": "100644",
                        "policy": "copy",
                        "sha256": digest(source / "shared.txt"),
                    },
                    {
                        "destination": "community.txt",
                        "mode": "100644",
                        "policy": "preserve",
                        "sha256": digest(target / "community.txt"),
                    },
                ],
            )
            entries = EXPORT.load_manifest(manifest)
            EXPORT.stage(entries, source, target, staged)
            self.assertEqual((staged / "shared.txt").read_text(encoding="utf-8"), "shared\n")
            self.assertEqual((staged / "community.txt").read_text(encoding="utf-8"), "community\n")

            (target / "community.txt").write_text("changed\n", encoding="utf-8")
            with self.assertRaises(EXPORT.ExportError):
                EXPORT.stage(entries, source, target, root / "staged-again")

    def test_target_inventory_allows_new_copy_files_but_not_missing_preserve_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="community-inventory-") as temp:
            root = Path(temp)
            target = root / "target"
            target.mkdir()
            entries = [
                EXPORT.Entry(
                    destination=EXPORT.PurePosixPath("new.txt"),
                    mode=0o644,
                    sha256="0" * 64,
                    source=EXPORT.PurePosixPath("new.txt"),
                )
            ]
            EXPORT.verify_target_inventory(entries, target)
            entries.append(
                EXPORT.Entry(
                    destination=EXPORT.PurePosixPath("community.txt"),
                    mode=0o644,
                    sha256="1" * 64,
                    source=None,
                )
            )
            with self.assertRaises(EXPORT.ExportError):
                EXPORT.verify_target_inventory(entries, target)

    def test_checked_in_manifest_pins_every_copy_source(self) -> None:
        entries = EXPORT.load_manifest(REPO / "scripts" / "community-export-manifest.json")
        self.assertGreater(len(entries), 100)
        destinations = {entry.destination.as_posix() for entry in entries}
        self.assertIn("bin/sulde", destinations)
        self.assertIn("template/_project/knowledge/schema.yaml", destinations)
        self.assertNotIn("scripts/kb/agent-runtime.py", destinations)
        for entry in entries:
            if entry.policy == "copy":
                path = EXPORT.within(REPO, entry.source)
                self.assertEqual(EXPORT.sha256_file(path), entry.sha256)

    def test_release_wrapper_has_no_directory_sync_path(self) -> None:
        wrapper = (REPO / "scripts" / "export-community.sh").read_text(encoding="utf-8")
        implementation = (REPO / "scripts" / "export_community.py").read_text(encoding="utf-8")
        self.assertNotIn("rsync", wrapper)
        self.assertNotIn("rsync", implementation)
        self.assertIn("--approve-digest", implementation)
        self.assertIn("public repository must be clean", implementation)


if __name__ == "__main__":
    unittest.main()
