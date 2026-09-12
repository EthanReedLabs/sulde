from __future__ import annotations

import unittest

from scripts.kb.local_file_operations import (
    LocalFileOperationError,
    has_destructive_operation,
    operation_targets,
    parse_apply_patch_operations,
)


class LocalFileOperationTests(unittest.TestCase):
    def test_mixed_patch_preserves_typed_targets_and_commas(self) -> None:
        operations = parse_apply_patch_operations(
            "*** Begin Patch\n"
            "*** Add File: added.md\n"
            "+new\n"
            "*** Update File: notes,2026.md\n"
            "@@\n-old\n+new\n"
            "*** Delete File: obsolete.md\n"
            "*** End Patch"
        )

        self.assertEqual(
            [item.as_dict() for item in operations],
            [
                {"operation": "add", "path": "added.md"},
                {"operation": "update", "path": "notes,2026.md"},
                {"operation": "delete", "path": "obsolete.md"},
            ],
        )
        self.assertEqual(
            operation_targets(operations),
            ("added.md", "notes,2026.md", "obsolete.md"),
        )
        self.assertTrue(has_destructive_operation(operations))

    def test_move_checks_both_source_and_destination(self) -> None:
        operations = parse_apply_patch_operations(
            "*** Begin Patch\n"
            "*** Update File: old.md\n"
            "*** Move to: archive/new.md\n"
            "@@\n-old\n+new\n"
            "*** End Patch"
        )

        self.assertEqual(
            [item.as_dict() for item in operations],
            [
                {"operation": "move_from", "path": "old.md"},
                {"operation": "move_to", "path": "archive/new.md"},
            ],
        )
        self.assertTrue(has_destructive_operation(operations))

    def test_ordinary_updates_are_not_destructive(self) -> None:
        operations = parse_apply_patch_operations(
            "*** Begin Patch\n"
            "*** Update File: resume.md\n"
            "@@\n-old\n+new\n"
            "*** End Patch"
        )
        self.assertFalse(has_destructive_operation(operations))

    def test_orphan_move_and_unresolved_envelope_fail_closed(self) -> None:
        with self.assertRaises(LocalFileOperationError):
            parse_apply_patch_operations(
                "*** Begin Patch\n*** Move to: destination.md\n*** End Patch"
            )
        with self.assertRaises(LocalFileOperationError):
            parse_apply_patch_operations("not an apply_patch envelope")


if __name__ == "__main__":
    unittest.main()
