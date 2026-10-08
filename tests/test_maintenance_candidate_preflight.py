"""Cheap exclusion must not replace exact maintenance authority verification."""
import hashlib
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/kb"))
from intent_guardian_parts import resource_preflight as preflight
from intent_guardian_parts import resources


class MaintenanceCandidatePreflightTests(unittest.TestCase):
    def test_unrelated_commands_never_build_maintenance_bindings(self):
        commands = ("", "rg needle README.md", "touch probe.txt",
                    shlex.join([sys.executable, str(ROOT / "scripts/kb/intent-guardian.py"), "--help"]))
        with mock.patch.object(preflight, "_scheduler_reconcile_binding") as scheduler, \
                mock.patch.object(preflight, "_launcher_refresh_binding") as launcher:
            for command in commands:
                with self.subTest(command=command):
                    self.assertIsNone(preflight.scheduler_reconcile_candidate(command, cwd=ROOT))
                    self.assertIsNone(preflight.launcher_refresh_candidate(command, cwd=ROOT))
            scheduler.assert_not_called()
            launcher.assert_not_called()

    def test_normalization_never_hashes_a_tree_for_unrelated_commands(self):
        commands = ("rg needle README.md", "touch probe.txt",
                    shlex.join([sys.executable, str(ROOT / "scripts/kb/intent-guardian.py"), "--help"]))
        with mock.patch.object(preflight, "_scheduler_reconcile_binding") as scheduler, \
                mock.patch.object(preflight, "_launcher_refresh_binding") as launcher:
            for command, effect in zip(commands, ("read", "local_write", "read")):
                with self.subTest(command=command):
                    event = resources.normalize_hook_event(
                        {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(ROOT)},
                        phase="started", provider="codex")
                    self.assertEqual(event["effect"], effect)
            scheduler.assert_not_called()
            launcher.assert_not_called()

    def test_malformed_near_matches_do_not_compute_bindings(self):
        cases = (
            (preflight.scheduler_reconcile_candidate, "install-agents.sh --help"),
            (preflight.scheduler_reconcile_candidate, "install-agents.sh --runtime-root /x --provider claude --accept-llm-data-egress"),
            (preflight.scheduler_reconcile_candidate, "install-agents.sh --runtime-root /x --provider codex"),
            (preflight.scheduler_reconcile_candidate, "other.sh --runtime-root /x --provider codex --accept-llm-data-egress"),
            (preflight.launcher_refresh_candidate, "bootstrap.sh --host codex --launchers-only"),
            (preflight.launcher_refresh_candidate, "bootstrap.sh --launchers-only --host claude"),
            (preflight.launcher_refresh_candidate, "other.sh --launchers-only --host codex"),
            (preflight.launcher_refresh_candidate, "bootstrap.sh --launchers-only --host codex extra"),
            (preflight.launcher_refresh_candidate, "bootstrap.sh --launchers-only --host codex; touch out"),
            (preflight.launcher_refresh_candidate, "'unterminated"),
        )
        with mock.patch.object(preflight, "_scheduler_reconcile_binding") as scheduler, \
                mock.patch.object(preflight, "_launcher_refresh_binding") as launcher:
            for recognize, command in cases:
                with self.subTest(command=command):
                    self.assertIsNone(recognize(command, cwd=ROOT))
            scheduler.assert_not_called()
            launcher.assert_not_called()

    def test_matching_shape_still_requires_exact_binding_and_fresh_digest(self):
        with tempfile.TemporaryDirectory(prefix="maintenance candidate ") as directory:
            root = Path(directory)
            for name, recognize, binding_name, profile in (
                ("install-agents.sh", preflight.scheduler_reconcile_candidate,
                 "_scheduler_reconcile_binding", "sulde-scheduler-reconcile-v1"),
                ("bootstrap.sh", preflight.launcher_refresh_candidate,
                 "_launcher_refresh_binding", "sulde-launcher-refresh-v1"),
            ):
                with self.subTest(profile=profile):
                    script = root / name
                    script.write_bytes(b"synthetic maintenance bytes\n")
                    binding = {"script_path": str(script), "runtime_root": str(root),
                               "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest()}
                    argv = [str(script)] + (
                        ["--runtime-root", str(root), "--provider", "codex", "--accept-llm-data-egress"]
                        if name == "install-agents.sh" else ["--launchers-only", "--host", "codex"])
                    with mock.patch.object(preflight, binding_name, return_value=binding) as bind:
                        result = recognize(shlex.join(argv), cwd=root)
                        self.assertEqual(result, preflight._candidate(profile, binding))
                        bind.assert_called_once_with(root)
                        wrong = [str(root / "wrong" / name), *argv[1:]]
                        self.assertIsNone(recognize(shlex.join(wrong), cwd=root))
                        if name == "install-agents.sh":
                            wrong_root = [argv[0], argv[1], str(root / "other"), *argv[3:]]
                            self.assertIsNone(recognize(shlex.join(wrong_root), cwd=root))
                        script.write_bytes(b"changed after binding\n")
                        self.assertIsNone(recognize(shlex.join(argv), cwd=root))
                        script.unlink()
                        self.assertIsNone(recognize(shlex.join(argv), cwd=root))
                    with mock.patch.object(preflight, binding_name,
                                           side_effect=preflight.IntentGuardianError("generation drift")):
                        self.assertIsNone(recognize(shlex.join(argv), cwd=root))


if __name__ == "__main__":
    unittest.main()
