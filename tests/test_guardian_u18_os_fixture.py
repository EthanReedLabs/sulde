"""Nested Seatbelt diagnostics are unavailable evidence, never a passed denial."""
import os
import sys
import unittest
from unittest import mock

from tests import test_isolated_test_runner as fixture


@unittest.skipUnless(sys.platform == "darwin", "Seatbelt fixture is macOS-specific")
class NativeFixtureDiagnosticTests(unittest.TestCase):
    def run_fixture(self, message, required=False):
        module = fixture.load_module()
        case = fixture.IsolatedTestRunnerTests(
            "test_real_os_boundary_denies_alias_and_symlink_targets"
        )
        with mock.patch.object(fixture, "load_module", return_value=module), \
                mock.patch.object(module, "preflight_os_test_isolation",
                                  side_effect=RuntimeError(message)), \
                mock.patch.dict(os.environ, {
                    "SULDE_REQUIRE_NATIVE_OS_EVIDENCE": "1" if required else "0"
                }):
            case.test_real_os_boundary_denies_alias_and_symlink_targets()

    def test_known_nested_diagnostics_are_skipped_not_passed(self):
        for operation in ("sandbox_init", "sandbox_apply"):
            with self.subTest(operation=operation):
                message = (
                    "OS test isolation backend did not prove write denial: "
                    f"sandbox-exec: {operation}: Operation not permitted"
                )
                with self.assertRaises(unittest.SkipTest):
                    self.run_fixture(message)

    def test_required_native_evidence_never_skips(self):
        for operation in ("sandbox_init", "sandbox_apply"):
            with self.subTest(operation=operation):
                message = (
                    "OS test isolation backend did not prove write denial: "
                    f"sandbox-exec: {operation}: Operation not permitted"
                )
                try:
                    with self.assertRaisesRegex(RuntimeError, operation):
                        self.run_fixture(message, required=True)
                except unittest.SkipTest:
                    self.fail("mandatory native evidence was incorrectly skipped")

    def test_escape_or_other_error_cannot_be_misreported_as_unavailable(self):
        for message in (
            "OS test isolation backend allowed a production write",
            "OS test isolation backend did not prove write denial",
            "OS test isolation backend did not prove write denial: PermissionError",
            "OS test isolation backend allowed a production write: "
            "sandbox_init: Operation not permitted",
        ):
            with self.subTest(message=message):
                try:
                    with self.assertRaises(RuntimeError):
                        self.run_fixture(message)
                except unittest.SkipTest:
                    self.fail("an unexpected failure was incorrectly skipped")
