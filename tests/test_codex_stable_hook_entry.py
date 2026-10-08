from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("codex_hook_entry", ROOT / "scripts/release/codex_hook_entry.py")
ENTRY = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ENTRY)


@unittest.skipIf(os.name == "nt", "POSIX stable transport only")
class StableHookEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "sulde"
        self.plugin = self.root / "cache/plugin"
        (self.plugin / "scripts").mkdir(parents=True)
        for name in ENTRY.FILES:
            shutil.copyfile(ROOT / "integrations/codex/plugins/sulde/scripts" / name, self.plugin / "scripts" / name)
        self.home.mkdir(mode=0o700)
        self.path = self.root / "path"
        self.path.mkdir()
        (self.path / "python3").symlink_to(sys.executable)
        for name in ("bash", "cat", "dirname", "grep"):
            (self.path / name).symlink_to(shutil.which(name))
        self.env = {"PATH": str(self.path), "HOME": str(self.root), "SULDE_HOME": str(self.home), "SULDE_KB_HOME": str(self.home / "data/kb"), "PYTHONDONTWRITEBYTECODE": "1"}

    def publish(self):
        before = ENTRY.describe(self.plugin, self.home)
        self.assertFalse((self.home / "hook-entry").exists())
        descriptor = ENTRY.prepare(self.plugin, self.home)
        self.assertEqual(descriptor, before)
        target = ENTRY.publish(self.home, descriptor)
        self.assertTrue(ENTRY.verify(self.home, descriptor)["healthy"])
        return descriptor, target

    def call(self, target, *, hook="pre-tool-use", write=False, env=None, pass_fds=()):
        payload = {"tool_name": "Write" if write else "Read", "tool_input": {"file_path": "/test/fixture.txt"}, "session_id": "fixture-session", "tool_use_id": "fixture-call"}
        result = subprocess.run([str(target), hook], input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, env=self.env if env is None else env, pass_fds=pass_fds)
        if result.stdout.startswith("sulde-hook-entry-complete-v1:"):
            result.stdout = result.stdout[len("sulde-hook-entry-complete-v1:"):]
        return result

    def test_normal_then_not_yet_started_entry_survives_cache_deletion(self):
        _, target = self.publish()
        normal = self.call(target)
        self.assertEqual(normal.returncode, 0, normal.stderr)
        self.assertEqual(normal.stdout.strip(), "", normal.stderr)
        shutil.rmtree(self.plugin)
        read = self.call(target)
        self.assertEqual(read.returncode, 0, read.stderr)
        self.assertEqual(read.stdout.strip(), "", read.stderr)
        write = self.call(target, write=True)
        self.assertEqual(json.loads(write.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_bad_bundle_denies_pre_and_reports_nonpre_blind_spot(self):
        descriptor, target = self.publish()
        helper = self.home / "hook-entry" / descriptor["bundle_id"] / "scripts/_recovery_defer.py"
        helper.chmod(0o644)
        helper.write_text("raise SystemExit(0)\n", encoding="utf-8")
        for hook in ("pre-tool-use", "post-tool-use"):
            result = self.call(target, hook=hook, write=True)
            self.assertIn("coverage_blind_spot", result.stderr)
            if hook == "pre-tool-use":
                self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
            else:
                self.assertEqual(result.stdout, "")
        self.assertFalse(ENTRY.verify(self.home, descriptor)["healthy"])

    def test_symlink_helper_and_symlink_bundle_are_rejected(self):
        descriptor, target = self.publish()
        bundle = self.home / "hook-entry" / descriptor["bundle_id"]
        helper = bundle / "scripts/_recovery_defer.py"
        original = helper.read_bytes()
        helper.unlink()
        outside = self.root / "outside.py"
        outside.write_bytes(original)
        helper.symlink_to(outside)
        result = self.call(target)
        self.assertIn('"deny"', result.stdout)
        helper.unlink()
        helper.write_bytes(original)
        moved = self.home / "hook-entry/moved"
        bundle.rename(moved)
        bundle.symlink_to(moved, target_is_directory=True)
        self.assertIn('"deny"', self.call(target).stdout)
        self.assertFalse(ENTRY.verify(self.home, descriptor)["healthy"])

    def test_missing_interpreter_is_not_silent_success(self):
        descriptor, target = self.publish()
        copied = self.root / "python-copy"
        shutil.copyfile(Path(sys.executable).resolve(), copied)
        copied.chmod(0o700)
        descriptor["interpreter"]["path"] = str(copied)
        descriptor["interpreter"]["real_path"] = str(copied.resolve())
        descriptor["bootstrap_sha256"] = ENTRY._sha(ENTRY._bootstrap(descriptor))
        ENTRY.publish(self.home, descriptor)
        copied.unlink()
        self.assertIn('"deny"', self.call(target).stdout)
        nonpre = self.call(target, hook="stop")
        self.assertEqual(nonpre.stdout, "")
        self.assertIn("coverage_blind_spot", nonpre.stderr)

    def test_bound_interpreter_does_not_choose_older_python_on_path(self):
        _, target = self.publish()
        result = self.call(target, env={**self.env, "PATH": "/usr/bin:/bin"})
        self.assertEqual(result.stdout.strip(), "", result.stderr)
        self.assertIn("static fallback classified", result.stderr)

    def test_inherited_descriptors_cannot_collide_with_directory_or_helpers(self):
        _, target = self.publish()
        descriptors = [os.open(os.devnull, os.O_RDONLY) for _ in range(14)]
        try:
            result = self.call(target, pass_fds=tuple(descriptors))
            self.assertEqual(result.stdout.strip(), "", result.stderr)
            self.assertIn("static fallback classified", result.stderr)
            self.assertIn('"deny"', self.call(target, write=True, pass_fds=tuple(descriptors)).stdout)
        finally:
            for fd in descriptors:
                os.close(fd)

    def test_descriptor_rejects_path_escape_schema_and_inventory_drift(self):
        descriptor, target = self.publish()
        before = target.read_bytes()
        for changes in ({"bundle_id": "../escape"}, {"bundle_id": "/tmp/escape"}, {"schema": "other"}, {"files": {}}, {"bundle_id": "0" * 64}):
            wrong = {**descriptor, **changes}
            wrong["bootstrap_sha256"] = ENTRY._sha(ENTRY._bootstrap(wrong))
            with self.assertRaises(ValueError):
                ENTRY.publish(self.home, wrong)
            target.write_bytes(ENTRY._bootstrap(wrong))
            self.assertFalse(ENTRY.verify(self.home)["healthy"])
            target.write_bytes(before)

    def test_failed_publication_preserves_previous_pointer(self):
        _, target = self.publish()
        before = target.read_bytes()
        source = self.plugin / "scripts/run-hook.sh"
        source.write_text(source.read_text(encoding="utf-8") + "\n# candidate two\n", encoding="utf-8")
        descriptor = ENTRY.prepare(self.plugin, self.home)
        with mock.patch.object(ENTRY.os, "replace", side_effect=OSError("injected publish failure")):
            with self.assertRaises(OSError):
                ENTRY.publish(self.home, descriptor)
        self.assertEqual(target.read_bytes(), before)
        self.assertTrue(ENTRY.verify(self.home)["healthy"])

    def test_runtime_uses_copied_helpers_after_source_mutation(self):
        descriptor, target = self.publish()
        helper = self.home / "hook-entry" / descriptor["bundle_id"] / "scripts/_recovery_defer.py"
        bridge = self.home / "bin/intent-guardian"
        # The bridge is reached only after loader verification. Mutate the
        # original bundle there: the fallback must still execute copied bytes.
        bridge.write_text("#!/bin/sh\n# sulde-observer-in-process-v1\n/bin/chmod 644 '" + str(helper) + "'\nprintf 'raise SystemExit(0)\\n' > '" + str(helper) + "'\nexit 73\n", encoding="utf-8")
        bridge.chmod(0o700)
        result = self.call(target, write=True)
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny", result.stderr)
        self.assertIn("static fallback classified", result.stderr)

    def test_unrecognized_pin_source_is_rejected(self):
        source = self.plugin / "scripts/run-hook.sh"
        source.write_text(source.read_text(encoding="utf-8").replace("PINNED_OBSERVER=8", "PINNED_OBSERVER=10"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "interface mismatch"):
            ENTRY.describe(self.plugin, self.home)

    def test_bootstrap_drift_and_unexpected_identity_are_rejected(self):
        descriptor, target = self.publish()
        wrong = {**descriptor, "bundle_id": "0" * 64}
        self.assertFalse(ENTRY.verify(self.home, wrong)["healthy"])
        target.write_bytes(target.read_bytes() + b"\n# drift\n")
        self.assertFalse(ENTRY.verify(self.home, descriptor)["healthy"])

    def test_nonzero_shell_never_sends_completion_or_partial_stdout(self):
        source = self.plugin / "scripts/run-hook.sh"
        source.write_text(source.read_text(encoding="utf-8").replace("#!/bin/sh", "#!/bin/sh\nprintf unverified-partial\nexit 17", 1), encoding="utf-8")
        _, target = self.publish()
        result = subprocess.run([str(target), "pre-tool-use"], input="{}", capture_output=True, text=True, encoding="utf-8", errors="replace", env=self.env, timeout=10)
        self.assertNotIn("sulde-hook-entry-complete-v1:", result.stdout)
        self.assertNotIn("unverified-partial", result.stdout)
        self.assertIn('"deny"', result.stdout)

    def test_project_modules_cannot_execute_in_bootstrap_or_pinned_helpers(self):
        _, target = self.publish()
        project = self.root / "business-project"
        project.mkdir()
        marker = project / "untrusted-import-ran"
        for module in ("hashlib", "json"):
            (project / (module + ".py")).write_text(f"open({str(marker)!r}, 'w').write('unexpected')\nraise RuntimeError('untrusted business module')\n", encoding="utf-8")
        result = subprocess.run([str(target), "pre-tool-use"], input='{"tool_name":"Write","tool_input":{"file_path":"fixture"}}', cwd=project, env={**self.env, "PYTHONPATH": str(project)}, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        self.assertFalse(marker.exists(), result.stderr)
        self.assertIn('"deny"', result.stdout)

    def test_new_verifier_accepts_old_sealed_bootstrap_without_rerendering(self):
        # Frozen legacy wire shape, not a claim that this stub executes Hooks.
        # Real old-producer and cross-version installer runs are separate evidence.
        import base64
        descriptor = ENTRY.prepare(self.plugin, self.home)
        descriptor["interpreter"]["path"] = descriptor["interpreter"].pop("real_path")
        core = {key: value for key, value in descriptor.items() if key != "bootstrap_sha256"}
        metadata = base64.b64encode(json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8")).decode("ascii")
        raw = ("#!/bin/sh\n# sulde-stable-entry-v1 " + metadata + "\n# legacy-generator-fixture\nexit 0\n").encode("utf-8")
        descriptor["bootstrap_sha256"] = ENTRY._sha(raw)
        target = ENTRY.snapshot_files(self.home)[0]
        target.parent.mkdir()
        target.write_bytes(raw)
        target.chmod(0o700)
        self.assertEqual(set(descriptor["interpreter"]), {"path", "sha256"})
        self.assertTrue(ENTRY.verify(self.home, descriptor)["healthy"])
        self.assertFalse(ENTRY.verify(self.home)["healthy"])

    def test_sealed_native_recovery_route_survives_broken_bridge(self):
        self._recovery_pair(False)

    def test_sealed_bytecode_recovery_does_not_import_unverified_pyc(self):
        self._recovery_pair(True)

    def _recovery_pair(self, bytecode):
        # Reuse the production recovery fixture, not a second invented grant.
        sys.path.insert(0, str(ROOT / "tests"))
        from test_production_recovery_control import ProductionRecoveryControlTests
        python = str(Path(sys.executable).resolve().parent / "python3")
        with mock.patch.object(sys, "executable", python):
            fixture = ProductionRecoveryControlTests()
            fixture.setUp()
            try:
                marker = fixture.base / "untrusted-bytecode-executed"
                if bytecode:
                    import marshal
                    import struct
                    source = fixture.runtime / "scripts/kb/launcher_contract.py"
                    cache = source.parent / "__pycache__"
                    cache.mkdir()
                    payload = compile(f"open({str(marker)!r}, 'w').write('unexpected')\n", str(source), "exec")
                    metadata = source.stat()
                    binary = importlib.util.MAGIC_NUMBER + struct.pack("<III", 0, int(metadata.st_mtime), metadata.st_size) + marshal.dumps(payload)
                    (cache / ("launcher_contract." + sys.implementation.cache_tag + ".pyc")).write_bytes(binary)
                preview = fixture.prepare("repair_generated_bytecode", "runtime-bytecode") if bytecode else fixture.prepare()
                payload = fixture.payload(preview, event="PreToolUse")
                env = {**fixture.environment, "PATH": str(Path(python).parent) + ":/usr/bin:/bin"}
                if not bytecode:
                    old = subprocess.run(["/bin/sh", str(fixture.runtime.parent / "scripts/run-hook.sh"), "pre-tool-use"], input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=15)
                    self.assertEqual(old.returncode, 0, old.stderr)
                    self.assertEqual(old.stdout, "", old.stderr)
                description = ENTRY.prepare(fixture.runtime.parent, fixture.home, interpreter=Path(python))
                target = ENTRY.publish(fixture.home, description)
                def execute(value):
                    return subprocess.run([str(target), "pre-tool-use"], input=json.dumps(value), capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=15)
                result = execute(payload)
                self.assertEqual(result.stdout.strip(), "sulde-hook-entry-complete-v1:", result.stderr)
                self.assertFalse(marker.exists())
                ordinary = execute({"tool_name": "Write", "tool_input": {"file_path": "ordinary"}})
                self.assertIn('"deny"', ordinary.stdout)
                source = fixture.runtime / "scripts/kb/production_recovery_control.py"
                source.write_bytes(source.read_bytes() + b"\n# drift\n")
                drifted = execute(payload)
                self.assertIn('"deny"', drifted.stdout)
                self.assertIn("verified_recovery_unavailable", drifted.stderr)
                self.assertEqual(fixture.control.lane._payloads("recovery_dispatch_started"), [])
            finally:
                fixture.tearDown()


def benchmark():
    """Opt-in complete registered-command A/B; never a timing-sensitive unit test."""
    case = StableHookEntryTests()
    case.setUp()
    try:
        descriptor, _ = case.publish()
        bridge = case.home / "bin/intent-guardian"
        bridge.write_text("#!/bin/sh\n# sulde-observer-in-process-v1\nexit 0\n", encoding="utf-8")
        bridge.chmod(0o700)
        registration = importlib.util.spec_from_file_location("registration", ROOT / "scripts/release/codex_hook_registration.py")
        module = importlib.util.module_from_spec(registration)
        registration.loader.exec_module(module)
        old = json.loads(subprocess.check_output(["git", "show", "e9d5405:integrations/codex/plugins/sulde/hooks.posix.json"], cwd=ROOT, text=True, encoding="utf-8", errors="replace"))["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        commands = {"old": old, "new": module.stable_hook_command("PreToolUse")}
        env = {**case.env, "PLUGIN_ROOT": str(case.plugin)}
        samples = {"old": [], "new": []}
        for index in range(12):
            for name in (("old", "new") if index % 2 == 0 else ("new", "old")):
                start = time.perf_counter()
                result = subprocess.run(["/bin/sh", "-c", commands[name]], input='{"tool_name":"Read","tool_input":{"file_path":"fixture"}}', capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=10)
                elapsed = (time.perf_counter() - start) * 1000
                if result.returncode or result.stdout.strip():
                    raise AssertionError((name, result.returncode, result.stdout, result.stderr))
                if index >= 2:
                    samples[name].append(elapsed)
        result = {"samples_ms": samples, "python": sys.version, "descriptor": descriptor, "commands": commands, "scope": "registered command + bootstrap + real wrapper + zero-result bridge; no model"}
        for key in ("old", "new"):
            result[key] = {"median_ms": statistics.median(samples[key]), "p95_ms": sorted(samples[key])[-1]}
        return result
    finally:
        case.doCleanups()


if __name__ == "__main__":
    if sys.argv[1:] == ["--benchmark"]:
        print(json.dumps(benchmark(), indent=2))
    else:
        unittest.main()
