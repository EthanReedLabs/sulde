from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "kb" / "audit_cursor.py"


def load_module():
    spec = importlib.util.spec_from_file_location("sulde_audit_cursor", MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AuditCursorTests(unittest.TestCase):
    generation = "runtime-generation-a"

    @staticmethod
    def row(sequence: int, generation: str = generation, **extra: object) -> bytes:
        event = {
            "sequence": sequence,
            "runtime_generation": generation,
            **extra,
        }
        return json.dumps({"event": event}, sort_keys=True).encode("utf-8") + b"\n"

    def test_warm_cursor_reads_only_new_bytes_and_persists_cas(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name).resolve(strict=True)
            log = root / "events.jsonl"
            cursor_path = root / "events.cursor.json"
            historical = b"".join(self.row(index) for index in range(1, 1001))
            log.write_bytes(historical)

            initial = module.scan_increment(
                log,
                runtime_generation=self.generation,
                max_bytes=len(historical),
            )
            digest = module.save_cursor(
                cursor_path,
                initial.cursor,
                expected_digest=None,
            )
            with log.open("ab") as handle:
                handle.write(self.row(1001))
            loaded = module.load_cursor(cursor_path)
            warm = module.scan_increment(
                log,
                runtime_generation=self.generation,
                cursor=loaded,
                max_bytes=1024,
            )

            self.assertEqual(warm.bytes_read, len(self.row(1001)))
            self.assertEqual(warm.integrity_bytes_read, len(historical))
            self.assertEqual(len(warm.rows), 1)
            self.assertEqual(warm.cursor.last_sequence, 1001)
            next_digest = module.save_cursor(
                cursor_path,
                warm.cursor,
                expected_digest=digest,
            )
            self.assertEqual(next_digest, module.cursor_digest(warm.cursor))

    def test_truncate_replace_half_line_and_generation_drift_fail_closed(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name).resolve(strict=True)
            log = root / "events.jsonl"
            log.write_bytes(self.row(1))
            checkpoint = module.scan_increment(
                log, runtime_generation=self.generation
            ).cursor

            log.write_bytes(b"")
            with self.assertRaisesRegex(module.AuditCursorError, "truncated"):
                module.scan_increment(
                    log, runtime_generation=self.generation, cursor=checkpoint
                )

            log.unlink()
            log.write_bytes(self.row(1))
            with self.assertRaisesRegex(module.AuditCursorError, "identity changed"):
                module.scan_increment(
                    log, runtime_generation=self.generation, cursor=checkpoint
                )

            fresh = module.scan_increment(
                log, runtime_generation=self.generation
            ).cursor
            with log.open("ab") as handle:
                handle.write(b'{"event":')
            with self.assertRaisesRegex(module.AuditCursorError, "incomplete"):
                module.scan_increment(
                    log, runtime_generation=self.generation, cursor=fresh
                )

            log.write_bytes(self.row(1))
            fresh = module.scan_increment(
                log, runtime_generation=self.generation
            ).cursor
            with self.assertRaisesRegex(module.AuditCursorError, "generation changed"):
                module.scan_increment(
                    log, runtime_generation="runtime-generation-b", cursor=fresh
                )

    def test_checkpoint_row_rewrite_and_sequence_gap_fail_closed(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name).resolve(strict=True)
            log = root / "events.jsonl"
            first = self.row(1)
            log.write_bytes(first)
            checkpoint = module.scan_increment(
                log, runtime_generation=self.generation
            ).cursor
            replacement = self.row(9)
            self.assertEqual(len(first), len(replacement))
            log.write_bytes(replacement)
            with self.assertRaisesRegex(module.AuditCursorError, "segment=0"):
                module.scan_increment(
                    log, runtime_generation=self.generation, cursor=checkpoint
                )

            log.write_bytes(first)
            checkpoint = module.scan_increment(
                log, runtime_generation=self.generation
            ).cursor
            with log.open("ab") as handle:
                handle.write(self.row(3))
            with self.assertRaisesRegex(module.AuditCursorError, "sequence continuity"):
                module.scan_increment(
                    log, runtime_generation=self.generation, cursor=checkpoint
                )

    def test_embedded_hash_discontinuity_is_rejected(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name).resolve(strict=True)
            log = root / "events.jsonl"
            first_raw = self.row(1)
            first_hash = hashlib.sha256(first_raw.rstrip(b"\n")).hexdigest()
            log.write_bytes(first_raw)
            checkpoint = module.scan_increment(
                log, runtime_generation=self.generation
            ).cursor
            self.assertEqual(checkpoint.last_event_hash, first_hash)
            with log.open("ab") as handle:
                handle.write(self.row(2, previous_sha256="f" * 64))
            with self.assertRaisesRegex(module.AuditCursorError, "hash continuity"):
                module.scan_increment(
                    log, runtime_generation=self.generation, cursor=checkpoint
                )

    def test_corrupt_cursor_and_lost_cas_are_rejected(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name).resolve(strict=True)
            log = root / "events.jsonl"
            cursor_path = root / "cursor.json"
            log.write_bytes(self.row(1))
            cursor = module.scan_increment(
                log, runtime_generation=self.generation
            ).cursor
            digest = module.save_cursor(cursor_path, cursor, expected_digest=None)
            cursor_path.write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(module.AuditCursorError, "corrupt"):
                module.load_cursor(cursor_path)

            cursor_path.unlink()
            digest = module.save_cursor(cursor_path, cursor, expected_digest=None)
            winner = module.with_projection(cursor, {"writer": "winner"})
            module.save_cursor(
                cursor_path,
                winner,
                expected_digest=digest,
            )
            loser = module.with_projection(cursor, {"writer": "loser"})
            with self.assertRaises(module.AuditCursorConflict):
                module.save_cursor(
                    cursor_path,
                    loser,
                    expected_digest=digest,
                )

    def test_bounded_recovery_and_symlink_log_are_rejected(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name).resolve(strict=True)
            log = root / "events.jsonl"
            log.write_bytes(self.row(1))
            checkpoint = module.scan_increment(
                log, runtime_generation=self.generation
            ).cursor
            with log.open("ab") as handle:
                handle.write(self.row(2))
            with self.assertRaisesRegex(module.AuditCursorError, "bounded"):
                module.recover_from_checkpoint(
                    log,
                    checkpoint,
                    runtime_generation=self.generation,
                    max_recovery_bytes=1,
                )

            real = root / "real.jsonl"
            real.write_bytes(self.row(1))
            alias = root / "alias.jsonl"
            alias.symlink_to(real)
            with self.assertRaises(module.AuditCursorError):
                module.scan_increment(alias, runtime_generation=self.generation)

    def test_earlier_same_length_rewrite_is_diagnosed_and_bounded_recovery_continues(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name).resolve(strict=True)
            log = root / "events.jsonl"
            original = b"".join(self.row(index) for index in range(1, 5))
            log.write_bytes(original)
            checkpoint = module.scan_increment(
                log,
                runtime_generation=self.generation,
            ).cursor
            first = self.row(1)
            replacement = self.row(9)
            self.assertEqual(len(first), len(replacement))
            with log.open("r+b") as handle:
                handle.write(replacement)
                handle.seek(0, os.SEEK_END)
                handle.write(self.row(5))

            with self.assertRaisesRegex(module.AuditPrefixMismatch, "segment=0"):
                module.scan_increment(
                    log,
                    runtime_generation=self.generation,
                    cursor=checkpoint,
                )
            recovered = module.recover_from_checkpoint(
                log,
                checkpoint,
                runtime_generation=self.generation,
                max_recovery_bytes=1024,
            )
            self.assertTrue(recovered.recovered_from_authority)
            self.assertEqual([row["event"]["sequence"] for row in recovered.rows], [5])
            self.assertTrue(recovered.diagnostics[0].startswith("authoritative-prefix-detached:"))

            with log.open("ab") as handle:
                handle.write(self.row(6))
            warm = module.scan_increment(
                log,
                runtime_generation=self.generation,
                cursor=recovered.cursor,
                max_bytes=1024,
            )
            self.assertEqual([row["event"]["sequence"] for row in warm.rows], [6])

    def test_cursor_storage_rejects_aliases_modes_and_noncanonical_cas_bytes(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name).resolve(strict=True)
            log = root / "events.jsonl"
            log.write_bytes(self.row(1))
            cursor = module.scan_increment(
                log,
                runtime_generation=self.generation,
            ).cursor
            target = root / "cursor.json"
            module.save_cursor(target, cursor, expected_digest=None)

            target.chmod(0o644)
            with self.assertRaisesRegex(module.AuditCursorError, "0600"):
                module.load_cursor(target)
            target.chmod(0o600)
            parsed = json.loads(target.read_text(encoding="utf-8"))
            target.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
            target.chmod(0o600)
            with self.assertRaisesRegex(module.AuditCursorError, "not canonical"):
                module.load_cursor(target)

            target.unlink()
            real = root / "real.cursor"
            module.save_cursor(real, cursor, expected_digest=None)
            target.symlink_to(real)
            with self.assertRaises(module.AuditCursorError):
                module.load_cursor(target)

            alias_parent = root / "cursor-parent-alias"
            real_parent = root / "real-parent"
            real_parent.mkdir()
            alias_parent.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaisesRegex(module.AuditCursorError, "parent must not be a symlink"):
                module.save_cursor(
                    alias_parent / "cursor.json",
                    cursor,
                    expected_digest=None,
                )

    def test_rename_after_cursor_publish_fails_without_displaced_success(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name).resolve(strict=True)
            parent = root / "cursors"
            parent.mkdir()
            log = root / "events.jsonl"
            log.write_bytes(self.row(1))
            cursor = module.scan_increment(
                log,
                runtime_generation=self.generation,
            ).cursor
            target = parent / "cursor.json"
            displaced = root / "cursors-displaced"
            real_rename = module.os.rename

            def publish_then_displace(source, destination, **kwargs):
                real_rename(source, destination, **kwargs)
                real_rename(parent, displaced)
                parent.mkdir()

            with (
                mock.patch.object(module.os, "rename", side_effect=publish_then_displace),
                self.assertRaisesRegex(module.AuditCursorError, "pathname|ancestor"),
            ):
                module.save_cursor(target, cursor, expected_digest=None)

            self.assertFalse(target.exists())
            self.assertTrue((displaced / "cursor.json").is_file())

    def test_load_detects_parent_replacement_after_cursor_read(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name).resolve(strict=True)
            parent = root / "cursors"
            parent.mkdir()
            log = root / "events.jsonl"
            log.write_bytes(self.row(1))
            cursor = module.scan_increment(
                log,
                runtime_generation=self.generation,
            ).cursor
            target = parent / "cursor.json"
            module.save_cursor(target, cursor, expected_digest=None)
            displaced = root / "cursors-displaced"
            real_load = module._load_cursor_at

            def load_then_displace(parent_descriptor, name):
                loaded = real_load(parent_descriptor, name)
                os.rename(parent, displaced)
                parent.mkdir()
                return loaded

            with (
                mock.patch.object(module, "_load_cursor_at", side_effect=load_then_displace),
                self.assertRaisesRegex(module.AuditCursorError, "pathname|ancestor"),
            ):
                module.load_cursor(target)

            self.assertFalse(target.exists())
            self.assertTrue((displaced / "cursor.json").is_file())

    def test_cas_detects_ancestor_replacement_before_target_publish(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name).resolve(strict=True)
            ancestor = root / "authority"
            parent = ancestor / "cursors"
            parent.mkdir(parents=True)
            log = root / "events.jsonl"
            log.write_bytes(self.row(1))
            cursor = module.scan_increment(
                log,
                runtime_generation=self.generation,
            ).cursor
            target = parent / "cursor.json"
            digest = module.save_cursor(target, cursor, expected_digest=None)
            replacement = module.with_projection(cursor, {"revision": "replacement"})
            displaced = root / "authority-displaced"
            real_lock = module._open_private_lock

            def lock_then_replace(parent_descriptor, name):
                locked = real_lock(parent_descriptor, name)
                os.rename(ancestor, displaced)
                parent.mkdir(parents=True)
                return locked

            with (
                mock.patch.object(module, "_open_private_lock", side_effect=lock_then_replace),
                self.assertRaisesRegex(module.AuditCursorError, "pathname|ancestor"),
            ):
                module.save_cursor(
                    target,
                    replacement,
                    expected_digest=digest,
                )

            self.assertFalse(target.exists())
            preserved = module.load_cursor(displaced / "cursors/cursor.json")
            self.assertEqual(module.cursor_digest(preserved), digest)


if __name__ == "__main__":
    unittest.main()
