"""macOS physical relocation integration and portable unsupported-host gates.

The real-Git suite relies on macOS inode/mode identity and RENAME_EXCL, the
explicit v1 execution platform. CI must run it on macOS, never claim its skips
on other hosts as physical migration evidence. Portable rejection tests below
still execute on every CI platform.
"""

from __future__ import annotations

import copy
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))
sys.path.insert(0, str(ROOT / "scripts" / "release"))

from fixture_process_lifecycle import finish_fixture_process_group, start_fixture_process

from intent_guardian_parts import repository_relocation as relocation
from intent_guardian_parts.state import IntentGuardianError
from intent_guardian_parts.state import active_contract_path, default_contract, load_contract, write_contract
from intent_guardian_parts.session_workspace import bind_session_workspace, session_workspace_path


@unittest.skipUnless(os.name == "posix", "fixture process groups require POSIX")
class RepositoryRelocationFixtureLifecycleTests(unittest.TestCase):
    def test_shutdown_reaps_remaining_child_without_touching_other_group(self) -> None:
        with subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                              start_new_session=True) as unrelated:
            try:
                script = ("import subprocess, sys; "
                          "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], "
                          "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
                          "print(child.pid, flush=True)")
                with start_fixture_process([sys.executable, "-c", script],
                                      stdout=subprocess.PIPE, text=True) as owned:
                    try:
                        output, _ = owned.communicate(timeout=5)
                        self.assertEqual(owned.returncode, 0)
                        self.assertEqual(os.getpgid(int(output.strip())), owned.pid)
                    finally:
                        finish_fixture_process_group(owned)
                    with self.assertRaises(ProcessLookupError):
                        os.killpg(owned.pid, 0)
                    self.assertIsNone(unrelated.poll())
            finally:
                unrelated.terminate()
                unrelated.wait(timeout=5)

    def test_shutdown_refuses_callers_process_group(self) -> None:
        from types import SimpleNamespace
        with mock.patch.object(os, "killpg") as send_signal:
            with self.assertRaisesRegex(AssertionError, "non-isolated"):
                finish_fixture_process_group(SimpleNamespace(pid=os.getpgrp()))
            send_signal.assert_not_called()

    def test_shutdown_is_idempotent_and_does_not_signal_a_reused_pid(self) -> None:
        with start_fixture_process([sys.executable, "-c", "pass"]) as owned:
            owned.wait(timeout=5)
            finish_fixture_process_group(owned)
            with mock.patch.object(os, "killpg") as send_signal:
                finish_fixture_process_group(owned)
                send_signal.assert_not_called()

    def test_creation_cannot_join_the_callers_session(self) -> None:
        with mock.patch.object(subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(ValueError, "own session"):
                start_fixture_process([sys.executable, "-c", "pass"], start_new_session=False)
            spawn.assert_not_called()

    def test_canary_restores_other_resources_when_process_cleanup_fails(self) -> None:
        import native_pretool_canary as native
        with tempfile.TemporaryDirectory() as temporary:
            isolated = Path(temporary).resolve() / "isolated"
            codex_home = isolated / "codex"
            codex_home.mkdir(parents=True)
            config = codex_home / "config.toml"
            config.write_bytes(b"# original fixture config\n")
            environment = {"CODEX_HOME": str(codex_home), "SULDE_HOME": str(isolated / "sulde")}
            host = native.NativeCanary("fixture", isolated, environment)
            server = mock.MagicMock(server_port=12345)
            process = mock.MagicMock()
            with mock.patch.object(native.http.server, "ThreadingHTTPServer", return_value=server), \
                    mock.patch.object(native.threading, "Thread"), \
                    mock.patch.object(native, "start_fixture_process", return_value=process), \
                    mock.patch.object(host, "rpc", side_effect=native.NativeCanaryError("startup failed")), \
                    mock.patch.object(native, "finish_fixture_process_group", side_effect=AssertionError("cleanup failed")):
                with self.assertRaisesRegex(AssertionError, "cleanup failed"):
                    with host.start():
                        self.fail("startup cannot succeed")
            self.assertEqual(config.read_bytes(), b"# original fixture config\n")
            process.stdin.close.assert_called_once()
            process.stdout.close.assert_called_once()
            server.shutdown.assert_called_once()
            server.server_close.assert_called_once()


@unittest.skipUnless(os.name == "posix", "descriptor-relative content traversal requires POSIX")
class RepositoryRelocationCapacityTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="sulde-relocation-capacity-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def test_finite_capacity_keeps_original_byte_ceiling(self) -> None:
        self.assertEqual(relocation.MAX_ENTRIES, 500_000)
        self.assertEqual(relocation.MAX_CONTENT_BYTES, 8 * 1024**3)

    def test_exact_entry_boundary_counts_directories_and_symlinks(self) -> None:
        (self.root / "directory").mkdir()
        (self.root / "directory" / "data").write_bytes(b"data")
        (self.root / "link").symlink_to("missing-target")
        with mock.patch.object(relocation, "MAX_ENTRIES", 3):
            content = relocation._content(self.root, [])
            self.assertEqual(content["entries"], 3)
            self.assertEqual(content["bytes"], 4)
        with mock.patch.object(relocation, "MAX_ENTRIES", 2):
            with self.assertRaisesRegex(IntentGuardianError, "entry bound"):
                relocation._content(self.root, [])

    def test_exact_byte_boundary_and_one_byte_over(self) -> None:
        (self.root / "data").write_bytes(b"12345678")
        with mock.patch.object(relocation, "MAX_CONTENT_BYTES", 8):
            self.assertEqual(relocation._content(self.root, [])["bytes"], 8)
            (self.root / "extra").write_bytes(b"9")
            with self.assertRaisesRegex(IntentGuardianError, "byte bound"):
                relocation._content(self.root, [])

    def test_flat_directory_enumeration_stops_before_unbounded_collection(self) -> None:
        # No giant allocation in the fixture: an otherwise unlimited iterator
        # proves that enumeration itself stops at the remaining budget + 1.
        from types import SimpleNamespace
        consumed = []
        def entries():
            for number in range(1_000_000):
                consumed.append(number)
                yield SimpleNamespace(name=f"item-{number}")
        with mock.patch.object(relocation, "MAX_ENTRIES", 2), \
                mock.patch.object(relocation.os, "scandir") as scan, \
                mock.patch.object(relocation.os, "listdir", side_effect=AssertionError("unbounded listdir")), \
                mock.patch.object(relocation.os, "stat") as read_metadata:
            scan.return_value.__enter__.return_value = entries()
            with self.assertRaisesRegex(IntentGuardianError, "entry bound"):
                relocation._content(self.root, [])
            self.assertEqual(consumed, [0, 1, 2])
            read_metadata.assert_not_called()

    def test_only_registered_git_admin_is_excluded_from_budget(self) -> None:
        (self.root / ".git").mkdir()
        (self.root / ".git" / "admin").write_bytes(b"excluded")
        (self.root / "history").mkdir()
        (self.root / "history" / ".git").mkdir()
        history = self.root / "history" / ".git" / "retained"
        history.write_bytes(b"retained")
        with mock.patch.object(relocation, "MAX_ENTRIES", 3):
            before = relocation._content(self.root, [])
            self.assertEqual(before["entries"], 3)
            self.assertEqual(before["bytes"], 8)
            history.write_bytes(b"modified")
            self.assertNotEqual(relocation._content(self.root, [])["sha256"], before["sha256"])
        with mock.patch.object(relocation, "MAX_ENTRIES", 2):
            with self.assertRaisesRegex(IntentGuardianError, "entry bound"):
                relocation._content(self.root, [])

    def test_pending_ancestor_siblings_share_the_discovery_budget(self) -> None:
        (self.root / "a-directory").mkdir()
        (self.root / "z-pending-sibling").touch()
        for number in range(3):
            (self.root / "a-directory" / f"child-{number}").touch()
        # Two names already reserved in the root. The third child exceeds
        # four even though the pending root sibling has not been visited.
        original = relocation.os.stat
        with mock.patch.object(relocation, "MAX_ENTRIES", 4), \
                mock.patch.object(relocation.os, "stat", wraps=original) as read_metadata:
            with self.assertRaisesRegex(IntentGuardianError, "entry bound"):
                relocation._content(self.root, [])
            self.assertEqual([call.args[0] for call in read_metadata.call_args_list], ["a-directory"])

    def test_bounded_enumeration_preserves_existing_digest_order(self) -> None:
        import hashlib
        rows = []
        for name, content in (("z-last", b"last"), ("a-first", b"first")):
            path = self.root / name
            path.write_bytes(content)
            info = path.lstat()
            rows.append({"path": name, "device": info.st_dev, "inode": info.st_ino,
                         "mode": info.st_mode, "size": len(content),
                         "sha256": hashlib.sha256(content).hexdigest()})
        expected = hashlib.sha256()
        for row in sorted(rows, key=lambda item: item["path"]):
            expected.update(bytes.fromhex(relocation._digest(row)))
        self.assertEqual(relocation._content(self.root, []),
                         {"entries": 2, "bytes": 9, "sha256": expected.hexdigest()})

    def test_real_tree_exceeding_legacy_limit_hashes_tail_without_overrides(self) -> None:
        # Actual inodes, real production traversal, no patched capacity or
        # filesystem. Keep data tiny: the regression is cardinality, not I/O GB.
        for number in range(250_001):
            descriptor = os.open(self.root / f"entry-{number:06d}", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        tail = self.root / "entry-250000"
        tail.write_bytes(b"before00")
        tail.chmod(0o400)
        first = relocation._content(self.root, [])
        self.assertEqual(first["entries"], 250_001)
        self.assertEqual(first["bytes"], 8)
        tail.chmod(0o600)
        tail.write_bytes(b"after000")
        tail.chmod(0o400)
        second = relocation._content(self.root, [])
        self.assertEqual((second["entries"], second["bytes"]), (250_001, 8))
        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertEqual(stat.S_IMODE(tail.stat().st_mode), 0o400)


class RepositoryRelocationPlatformTests(unittest.TestCase):
    def test_unsupported_hosts_fail_before_plan_read_or_native_preparation(self) -> None:
        for platform in ("linux", "win32"):
            with self.subTest(platform=platform), mock.patch.object(sys, "platform", platform), \
                    mock.patch.object(relocation, "_read_plan_file") as read, \
                    mock.patch.object(relocation, "_prepare_relocation_execution") as prepare:
                with self.assertRaisesRegex(IntentGuardianError, "verified macOS"):
                    relocation._execute_relocation_filesystem(Path("unused"), "0" * 64,
                                                             provider="codex", session_id="unused")
                with self.assertRaisesRegex(IntentGuardianError, "verified macOS"):
                    relocation.execute_native_relocation(Path("unused"), Path("unused"), "0" * 64,
                                                         decision="execute", provider="codex", session_id="unused")
                read.assert_not_called()
                prepare.assert_not_called()


@unittest.skipUnless(sys.platform == "darwin", "v1 physical relocation is macOS-only; required in macOS CI")
@unittest.skipUnless(shutil.which("codex"), "actual Codex CLI required for installed relocation acceptance")
class InstalledRepositoryRelocationTests(unittest.TestCase):
    def test_installed_native_allow_moves_once_and_leaves_paused_successor(self) -> None:
        self.run_installed_case(deny=False)

    def test_installed_native_deny_does_not_move_or_create_execution_transaction(self) -> None:
        self.run_installed_case(deny=True)

    def run_installed_case(self, *, deny: bool) -> None:
        from tests.test_native_memory_continuation import candidate, ExactApprovalHost, native, response_handler
        with tempfile.TemporaryDirectory(prefix="sulde-relocation-installed-") as temporary:
            slot, codex = Path(temporary).resolve(), shutil.which("codex")
            installer = candidate.installer
            staged = installer._stage_artifact(slot / "artifact", platform="posix", runner=installer.run_command)
            generation = staged.descriptor["delivery_generation"]
            env = candidate._candidate_environment(slot, codex, candidate._python_identity(Path(sys.executable)))
            runner = candidate._bound_runner(env)
            with candidate._process_environment(env):
                installed = installer._registry_add(codex, staged.marketplace, runner,
                                                     expected_version=generation["plugin_version"])
                kb = Path(env["SULDE_KB_HOME"])
                candidate._prepare_isolated_hook_launchers(installed, kb, runner,
                    platform="posix", environment=env)
                installer._smoke_installed(installed, kb, codex=codex,
                                          expected_tree_sha256=staged.plugin_tree_sha256, runner=runner)
                root, destination, stable = (slot / "isolated" / name for name in ("old-repository", "new-repository", "stable-control"))
                root.mkdir()
                stable.mkdir()
                def git(*args):
                    result = runner(["git", "-C", str(root), *args], environment=env, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                git("init", "-b", "dev")
                (root / ".gitignore").write_text(".worktrees/\n")
                (root / "preserved.txt").write_text("preserve fixture data\n")
                (root / "knowledge").mkdir()
                (root / "knowledge/README.md").write_text("fixture source binding\n")
                git("add", ".")
                git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture")
                git("worktree", "add", "-b", "task/fixture", str(root / ".worktrees/task"))
                consumer_path = kb / "auto-sediment-source.json"
                consumer_before = json.dumps({"schema": "sulde-auto-sediment-source-v1",
                    "source_root": str(root / ".worktrees/task"), "git_common_dir": str(root / ".git")}, indent=2) + "\n"
                consumer_path.write_text(consumer_before)
                consumer_path.chmod(0o600)
                (root / "preserved.txt").chmod(0o400)
                guardian = Path(env["SULDE_HOME"]) / "bin/intent-guardian"
                real_popen = subprocess.Popen
                def stable_host(command, *args, **kwargs):
                    if command[0] == codex and command[-1] == "app-server":
                        kwargs["cwd"] = stable
                        kwargs["start_new_session"] = True
                        process = real_popen(command, *args, **kwargs)
                        children.callback(finish_fixture_process_group, process)
                        self.assertEqual(os.getpgid(process.pid), process.pid)
                        return process
                    return real_popen(command, *args, **kwargs)
                host = ExactApprovalHost(codex, root, env, externally_isolated=bool(os.environ.get("SULDE_ISOLATED_TEST_RUN_ID")))
                original_rpc = host.rpc
                def interactive_thread(method, params):
                    if method == "thread/start":
                        params = {**params, "approvalPolicy": "on-request", "sandbox": "workspace-write"}
                    return original_rpc(method, params)
                host.rpc = interactive_thread
                original_server = native.http.server.ThreadingHTTPServer
                def model_server(address, _handler):
                    return original_server(address, response_handler(host))
                with ExitStack() as children, mock.patch.object(subprocess, "Popen", side_effect=stable_host), \
                        mock.patch.object(native.http.server, "ThreadingHTTPServer", side_effect=model_server), host.start():
                    contract, _ = candidate._activate_candidate_enforce_contract(
                        guardian, kb_home=kb, workspace=root, session=host.session, environment=env, runner=runner)
                    control_env = {**env, "CODEX_THREAD_ID": host.session}
                    def control(action, *args):
                        return candidate._parse_json_result(runner([str(guardian), action, *args,
                            "--provider", "codex", "--session-id", host.session, "--home", str(kb)],
                            environment=control_env, timeout=30), label=action)
                    # Establish the exact session mapping through the official
                    # same-repository handoff, not by writing a fixture mapping.
                    source_contract = contract
                    contract, _ = candidate._activate_candidate_enforce_contract(
                        guardian, kb_home=kb, workspace=root / ".worktrees/task", session=host.session,
                        environment=env, runner=runner)
                    handoff = control("prepare-workspace-handoff", str(root / ".worktrees/task"),
                                      "--contract", str(source_contract))
                    self.assertEqual(handoff["status"], "bound", handoff)
                    # Neither the host process nor its running turn may retain
                    # an OS cwd that the approved operation is about to move.
                    host.workspace = stable
                    real_rpc = host.rpc
                    def stable_turn(method, params):
                        if method == "turn/start":
                            params = {**params, "cwd": str(stable)}
                        return real_rpc(method, params)
                    host.rpc = stable_turn
                    checkpoint = {}
                    def prepare_current_card():
                        from approval_invariant import load_projection
                        open_questions = []
                        for p in sorted(kb.glob("intent/*/*.active.json")):
                            for request in load_projection(p)["requests"].values():
                                if request.get("status") == "asked":
                                    open_questions.append({"contract": p.name, "kind": request.get("kind"),
                                        "revision": request.get("intent_revision"), "source": request.get("source")})
                        print("RELOCATION_FIXTURE_OPEN_QUESTIONS=" + json.dumps(open_questions), flush=True)
                        plan = control("prepare-repository-relocation", str(root), str(destination), "--contract", str(contract))
                        preview = control("native-decision-preview", relocation.EXECUTION_KIND, "--decision", "execute",
                                          "--target", plan["plan_id"], "--contract", str(contract))
                        checkpoint.update(plan=plan, source_bytes=contract.read_bytes())
                        host.commands[0] = host.approval_command(preview, decision="decline" if deny else "accept")
                        # Wait for the bounded executor's result. A 1-second
                        # unified-exec yield is a running process, not terminal
                        # evidence; ending the model turn then races Stop.
                        host.commands[0]["yield_time_ms"] = 30000
                    host.before_calls = {0: prepare_current_card}
                    items = host.run_more(["replaced after actual UserPromptSubmit"])
                    self.assertEqual(getattr(host, "approval_count", 0), 1)
                    self.assertIsNone(host.expected_approval)
                    if deny:
                        self.assertTrue(root.exists())
                        self.assertEqual(consumer_path.read_text(), consumer_before)
                        self.assertFalse(destination.exists())
                        self.assertEqual(relocation._read_write_fences(kb), [])
                        from native_decision_journal import load_projection_read_only
                        self.assertEqual(load_projection_read_only(contract)["transactions"], {})
                    else:
                        terminal_path = Path(checkpoint["plan"]["plan_path"]).with_suffix(".terminal.json")
                        self.assertTrue(terminal_path.is_file(), json.dumps(items)[-2500:])
                        terminal = json.loads(terminal_path.read_text())
                        self.assertFalse(root.exists())
                        self.assertEqual(json.loads(consumer_path.read_text()), {
                            "schema": "sulde-auto-sediment-source-v1",
                            "source_root": str(destination / ".worktrees/task"),
                            "git_common_dir": str(destination / ".git")})
                        self.assertEqual(stat.S_IMODE(consumer_path.stat().st_mode), 0o600)
                        self.assertEqual((destination / "preserved.txt").read_text(), "preserve fixture data\n")
                        self.assertEqual(stat.S_IMODE((destination / "preserved.txt").stat().st_mode), 0o400)
                        successor = json.loads(Path(terminal["contract_path"]).read_text())
                        self.assertTrue(successor["confirmation"]["required"])
                        self.assertFalse(successor["permissions"]["local_write"])
                        self.assertEqual(successor["runtime"]["approval_receipts"], [])
                        self.assertEqual(relocation._read_write_fences(kb), [])
                        if os.environ.get("SULDE_ISOLATED_TEST_RUN_ID"):
                            # The repository runner still owns the OS sandbox.
                            # This avoids nested sandbox failures masquerading
                            # as a Guardian denial in the negative canary.
                            prior_rpc = host.rpc
                            def ordinary_tool_turn(method, params):
                                if method == "turn/start":
                                    params = {**params, "sandboxPolicy": {"type": "dangerFullAccess"}}
                                return prior_rpc(method, params)
                            host.rpc = ordinary_tool_turn
                        marker = destination / ".worktrees/task/allowed.txt"
                        first_notification = len(host.notifications)
                        host.run_more(["printf forbidden > " + shlex.quote(str(marker))])
                        self.assertFalse(marker.exists())
                        observed = [row["params"]["run"] for row in host.notifications[first_notification:]
                                    if row.get("method") == "hook/completed"]
                        self.assertTrue(any(row.get("eventName") == "preToolUse" and row.get("status") == "blocked"
                                            for row in observed), observed)
                        host.run_more(["test -f " + shlex.quote(str(destination / "preserved.txt"))])
                        self.assertEqual(host.approval_count, 1)
                    hooks = [row["params"]["run"] for row in host.notifications if row.get("method") == "hook/completed"]
                    self.assertTrue(any(row.get("eventName") == "permissionRequest" for row in hooks))
                    print("NATIVE_RELOCATION_EVIDENCE=" + json.dumps({
                        "transport": "codex-cli-app-server", "executor": "unified_exec",
                        "artifact_generation": generation["generation"], "fixture_choice": "deny" if deny else "allow",
                        "native_approval_count": host.approval_count, "external_model_requests": 0,
                        "physical_move_verified": not deny, "authority_transferred": False,
                        "unreviewed_business_write_denied": not deny,
                        "runtime_outside_moved_root": True, "host_and_turn_cwd_outside_move": True,
                    }, sort_keys=True), flush=True)


@unittest.skipUnless(sys.platform == "darwin", "v1 physical relocation is macOS-only; required in macOS CI")
class RepositoryRelocationEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "old repository"
        self.target = self.base / "new repository"
        self.root.mkdir()
        self.environment = mock.patch.dict(os.environ, {
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.git(self.root, "init", "-b", "main")
        self.git(self.root, "config", "user.email", "fixture@example.invalid")
        self.git(self.root, "config", "user.name", "Relocation Fixture")
        (self.root / "tracked.txt").write_text("base\n")
        (self.root / ".gitignore").write_text("ignored/\n.worktrees/\n")
        self.git(self.root, "add", ".")
        self.git(self.root, "commit", "-m", "fixture")
        self.linked = self.root / ".worktrees" / "task"
        self.git(self.root, "worktree", "add", "-b", "task/fixture", str(self.linked))

    def git(self, root: Path, *args: str) -> bytes:
        return subprocess.run(
            ["git", "-C", str(root), *args], check=True, capture_output=True,
        ).stdout

    def freeze(self) -> dict:
        return relocation.freeze_repository_identity(self.root, self.target)

    def move_and_repair(self) -> None:
        self.root.rename(self.target)
        self.git(self.target, "worktree", "repair", str(self.target / ".worktrees/task"))

    def guardian_fixture(self) -> tuple[Path, Path]:
        home = self.base / "kb-home"
        path = active_contract_path(home, self.root)
        write_contract(path, default_contract(
            intent_id="relocation-fixture", objective="review relocation",
            acceptance_criteria=["do not transfer authority"], workspace=self.root,
            mode="enforce", confirmed_by="fixture",
        ))
        bind_session_workspace(home, provider="codex", session_id="fixture-session", contract_path=path)
        return home, path

    def preflight(self, home: Path) -> dict:
        return relocation.freeze_relocation_preflight(
            home, self.root, self.target, provider="codex", session_id="fixture-session",
        )

    def fence_child(self, home: Path, path: Path, operation: str, payload: dict | None = None) -> subprocess.CompletedProcess:
        # Independent interpreter, actual store APIs and actual OS locks. No
        # production hook injection, real effects, or copied approval receipts.
        script = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from intent_guardian_parts import repository_relocation as r
from intent_guardian_parts.state import load_contract, write_contract, _append_jsonl, audit_path
from intent_guardian_parts.session_workspace import bind_session_workspace
import approval_invariant as a
import intervention as e
import native_decision_journal as n
path, home, op = Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
try:
    if op == "publish":
        result = r._publish_relocation_write_fence(home, json.load(sys.stdin))
    elif op == "read":
        result = {"contract": load_contract(path)["intent_id"],
                  "approval_sequence": a.load_projection(path)["sequence"],
                  "effect_sequence": e.load_projection(path)["sequence"],
                  "native_sequence": n.load_projection_read_only(path)["sequence"]}
    elif op == "contract":
        write_contract(path, load_contract(path))
        result = "written"
    elif op in {"mapping", "new-mapping"}:
        bind_session_workspace(home, provider="codex", session_id=("new-session" if op == "new-mapping" else "fixture-session"), contract_path=path)
        result = "written"
    elif op == "approval":
        c = load_contract(path)
        a.ask_approval(path, intent_id=c["intent_id"], intent_revision=c["revision"], kind="intent-confirmation", target="fixture", source="fixture")
        result = "written"
    elif op == "effect":
        c = load_contract(path)
        e.begin_attempt(path, intent_id=c["intent_id"], intent_revision=c["revision"], fingerprint="c"*64, source_event_id="fixture", capability="mcp:example:write", target="example:item:1", effect="external_write", provider="codex", session_id="fixture-session", idempotency_key="fixture")
        result = "written"
    elif op == "restore-approval":
        a.restore_authoritative_store(path, a.authoritative_store_bytes(path))
        result = "written"
    elif op == "restore-effect":
        e.restore_authoritative_store(path, e.authoritative_store_bytes(path))
        result = "written"
    elif op == "native":
        n.head_proof(path)
        result = "written"
    elif op == "audit":
        _append_jsonl(audit_path(path), {"fixture": True})
        result = "written"
    else:
        raise AssertionError(op)
    print(json.dumps({"ok": True, "result": result}))
except RuntimeError as error:
    print(json.dumps({"ok": False, "error_type": type(error).__name__, "error": str(error)}))
    sys.exit(2)
'''
        return subprocess.run([sys.executable, "-B", "-c", script, str(ROOT / "scripts/kb"),
                               str(path), str(home), operation], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)

    def test_write_fence_survives_publisher_exit_and_preserves_read_only_replay(self) -> None:
        home, path = self.guardian_fixture()
        published = self.fence_child(home, path, "publish", self.preflight(home))
        self.assertEqual(published.returncode, 0, published.stderr + published.stdout)
        value = json.loads(published.stdout)["result"]
        self.assertFalse(value["execution_authorized"])
        before = {p: p.read_bytes() for p in path.parent.glob("*") if p.is_file() and not p.name.startswith(".")}
        for op in ("contract", "mapping", "new-mapping", "approval", "effect", "restore-approval", "restore-effect", "native", "audit"):
            with self.subTest(operation=op):
                result = self.fence_child(home, path, op)
                self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
                self.assertIn("write fenced", result.stdout)
                self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(before, {p: p.read_bytes() for p in path.parent.glob("*") if p.is_file() and not p.name.startswith(".")})
        self.assertFalse(session_workspace_path(home, "codex", "new-session").exists())
        read = self.fence_child(home, path, "read")
        self.assertEqual(read.returncode, 0, read.stderr + read.stdout)
        self.assertTrue(self.root.is_dir())
        self.assertFalse(self.target.exists())

    def test_fence_rejects_new_registry_members_but_not_unrelated_workspace(self) -> None:
        from intent_guardian_parts.state import session_contract_path
        home, path = self.guardian_fixture()
        relocation._publish_relocation_write_fence(home, self.preflight(home))
        for root in (self.root, self.linked, self.target, self.target / ".worktrees/task"):
            candidate = session_contract_path(home, "codex", "new-contract")
            value = load_contract(path)
            value["workspace_root"] = str(root)
            with self.subTest(root=root), self.assertRaisesRegex(IntentGuardianError, "write fenced"):
                write_contract(candidate, value)
            self.assertFalse(candidate.exists())
        unrelated = self.base / "unrelated"
        unrelated.mkdir()
        value = default_contract(intent_id="unrelated", objective="keep independent", acceptance_criteria=["no migration"], workspace=unrelated)
        other = active_contract_path(home, unrelated)
        write_contract(other, value)
        for op in ("contract", "approval", "effect", "read"):
            result = self.fence_child(home, other, op)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_fence_revalidation_is_idempotent_and_rejects_late_registration(self) -> None:
        from intent_guardian_parts.state import session_contract_path
        home, path = self.guardian_fixture()
        frozen = self.preflight(home)
        newcomer = session_contract_path(home, "codex", "late-session")
        write_contract(newcomer, load_contract(path))
        with self.assertRaisesRegex(IntentGuardianError, "world changed"):
            relocation._publish_relocation_write_fence(home, frozen)
        self.assertFalse(relocation._fence_directory(home).exists())
        current = self.preflight(home)
        first = relocation._publish_relocation_write_fence(home, current)
        recorded = Path(first["fence_path"]).stat()
        second = relocation._publish_relocation_write_fence(home, current)
        self.assertEqual(first, second)
        self.assertEqual(recorded.st_ino, Path(second["fence_path"]).stat().st_ino)
        self.assertEqual(stat.S_IMODE(recorded.st_mode), 0o600)

    def test_fence_releases_all_acquired_locks_when_publication_fails(self) -> None:
        home, path = self.guardian_fixture()
        frozen = self.preflight(home)
        with mock.patch.object(relocation, "atomic_write", side_effect=OSError("fixture interruption")):
            with self.assertRaisesRegex(OSError, "fixture interruption"):
                relocation._publish_relocation_write_fence(home, frozen)
        # Every independent writer must be able to reacquire its actual lock.
        for op in ("contract", "mapping", "approval", "effect", "native", "audit"):
            result = self.fence_child(home, path, op)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_fence_publication_holds_each_real_writer_lock(self) -> None:
        home, path = self.guardian_fixture()
        frozen = self.preflight(home)
        actual_write = relocation.atomic_write
        checked = []

        def probe_then_publish(target: Path, content: str) -> None:
            for op in ("contract", "mapping", "approval", "effect", "native", "audit"):
                result = self.fence_child(home, path, op)
                self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
                self.assertIn("lock busy", result.stdout)
                checked.append(op)
            actual_write(target, content)

        with mock.patch.object(relocation, "atomic_write", side_effect=probe_then_publish):
            relocation._publish_relocation_write_fence(home, frozen)
        self.assertEqual(len(checked), 6)

    def test_fence_publisher_waits_for_inflight_registry_publication(self) -> None:
        home, path = self.guardian_fixture()
        frozen = self.preflight(home)
        with relocation.relocation_registration_write(path, workspace=self.root):
            result = self.fence_child(home, path, "publish", frozen)
            self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
            self.assertIn("lock busy", result.stdout)
        self.assertFalse(relocation._fence_directory(home).exists())
        result = self.fence_child(home, path, "publish", frozen)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_fence_reader_rejects_corrupt_or_unsafe_evidence_without_granting_authority(self) -> None:
        home, path = self.guardian_fixture()
        value = relocation._publish_relocation_write_fence(home, self.preflight(home))
        fence = Path(value["fence_path"])
        original = fence.read_bytes()
        fence.chmod(0o644)
        with self.assertRaises(IntentGuardianError):
            write_contract(path, load_contract(path))
        fence.chmod(0o600)
        document = json.loads(original)
        document["stores"] = []
        fence.write_text(json.dumps(document))
        with self.assertRaisesRegex(IntentGuardianError, "fence record is invalid"):
            write_contract(path, load_contract(path))
        self.assertEqual(self.fence_child(home, path, "read").returncode, 0)

    def test_ordinary_store_alias_works_but_cannot_bypass_an_active_fence(self) -> None:
        home, path = self.guardian_fixture()
        alias = self.base / "home-alias"
        alias.symlink_to(home, target_is_directory=True)
        alternate_path = alias / path.relative_to(home)
        write_contract(alternate_path, load_contract(path))
        self.assertEqual(self.fence_child(alias, alternate_path, "contract").returncode, 0)
        relocation._publish_relocation_write_fence(home, self.preflight(home))
        with self.assertRaisesRegex(IntentGuardianError, "write fenced"):
            write_contract(alternate_path, load_contract(path))
        self.assertEqual(self.fence_child(alias, alternate_path, "approval").returncode, 2)
        self.assertEqual(self.fence_child(alias, alternate_path, "read").returncode, 0)

    def test_recovery_inspection_covers_each_git_link_interruption_without_writes(self) -> None:
        snapshot = self.freeze()
        self.assertEqual(relocation.inspect_relocation_filesystem(snapshot)["status"], "source_intact")
        (self.root / "tracked.txt").chmod(0o400)
        snapshot = self.freeze()
        self.root.rename(self.target)
        expected = [row for row in snapshot["git_links"] if row["before"] != row["after"]]
        for completed in range(len(expected) + 1):
            before = {p: p.read_bytes() for p in self.target.rglob("*") if p.is_file()}
            result = relocation.inspect_relocation_filesystem(snapshot)
            self.assertEqual(len(result["links_pending"]), len(expected) - completed)
            self.assertEqual(result["status"], "git_repaired" if completed == len(expected) else "links_pending")
            self.assertFalse(result["execution_authorized"])
            self.assertFalse(result["mutation_performed"])
            self.assertEqual(before, {p: p.read_bytes() for p in self.target.rglob("*") if p.is_file()})
            if completed < len(expected):
                # Simulate precisely one already-approved mechanical write;
                # the production inspector itself never performs this step.
                link = expected[completed]
                (self.target / link["relative_path"]).write_text(link["after"])
        self.assertEqual(stat.S_IMODE((self.target / "tracked.txt").stat().st_mode), 0o400)

    def test_recovery_inspection_rejects_unknown_pointer_and_permission_drift(self) -> None:
        snapshot = self.freeze()
        self.root.rename(self.target)
        pointer = self.target / ".worktrees/task/.git"
        original = pointer.read_bytes()
        pointer.write_text("gitdir: /unknown/repository\n")
        with self.assertRaisesRegex(IntentGuardianError, "neither the frozen"):
            relocation.inspect_relocation_filesystem(snapshot)
        pointer.write_bytes(original)
        pointer.chmod(0o400)
        with self.assertRaisesRegex(IntentGuardianError, "permissions changed"):
            relocation.inspect_relocation_filesystem(snapshot)

    def test_recovery_inspection_rejects_admin_redirect_index_and_registration_drift(self) -> None:
        snapshot = self.freeze()
        self.root.rename(self.target)
        linked = next(row for row in snapshot["worktrees"] if row["relative_path"] != ".")
        admin = self.target / linked["git_dir"]
        index = admin / "index"
        original = index.read_bytes()
        index.write_bytes(original + b"drift")
        with self.assertRaisesRegex(IntentGuardianError, "identity/index/HEAD"):
            relocation.inspect_relocation_filesystem(snapshot)
        index.write_bytes(original)
        unexpected = self.target / ".git/worktrees/unexpected"
        unexpected.mkdir()
        with self.assertRaisesRegex(IntentGuardianError, "registration set changed"):
            relocation.inspect_relocation_filesystem(snapshot)
        unexpected.rmdir()
        backlink = admin / "gitdir"
        saved = self.base / "backlink"
        backlink.rename(saved)
        backlink.symlink_to(saved)
        with self.assertRaisesRegex(IntentGuardianError, "non-symlink"):
            relocation.inspect_relocation_filesystem(snapshot)

    def test_recovery_inspection_rejects_clone_missing_roots_and_recreated_source(self) -> None:
        snapshot = self.freeze()
        stash = self.base / "original-stash"
        self.root.rename(stash)
        with self.assertRaisesRegex(IntentGuardianError, "both roots are missing"):
            relocation.inspect_relocation_filesystem(snapshot)
        self.git(self.base, "clone", str(stash), str(self.target))
        with self.assertRaisesRegex(IntentGuardianError, "physical identity"):
            relocation.inspect_relocation_filesystem(snapshot)
        self.root.mkdir()
        with self.assertRaises(IntentGuardianError):
            relocation.inspect_relocation_filesystem(snapshot)

    def test_recovery_inspection_rejects_legacy_evidence_and_retains_git_permissions(self) -> None:
        snapshot = self.freeze()
        old = copy.deepcopy(snapshot)
        old["schema"] = "sulde-repository-relocation-evidence-v1"
        del old["git_links"]
        old["snapshot_sha256"] = relocation._digest({k: v for k, v in old.items() if k != "snapshot_sha256"})
        with self.assertRaisesRegex(IntentGuardianError, "v2 physical evidence"):
            relocation.inspect_relocation_filesystem(old)
        self.move_and_repair()
        self.assertEqual(relocation.inspect_relocation_filesystem(snapshot)["status"], "git_repaired")

    def test_real_recovery_cli_diagnoses_moved_root_with_fence_and_stale_mapping(self) -> None:
        from intent_guardian_parts.session_workspace import resolve_session_contract
        home, path = self.guardian_fixture()
        prepared = relocation.prepare_relocation_plan(home, path, self.root, self.target,
            provider="codex", session_id="fixture-session")
        relocation._publish_relocation_write_fence(home, self.preflight(home))
        self.root.rename(self.target)
        with self.assertRaisesRegex(IntentGuardianError, "target is unavailable"):
            resolve_session_contract(home, "codex", "fixture-session")
        command = [sys.executable, "-B", str(ROOT / "scripts/kb/intent-guardian.py"),
                   "inspect-repository-relocation", prepared["plan_id"], "--home", str(home),
                   "--provider", "codex", "--session-id", "fixture-session"]
        original = {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}
        observed = subprocess.run(command, cwd=self.base, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        self.assertEqual(observed.returncode, 0, observed.stderr)
        value = json.loads(observed.stdout)
        self.assertEqual(value["status"], "links_pending")
        self.assertFalse(value["execution_authorized"])
        self.assertFalse(value["routing_verified"])
        self.assertEqual(original, {p: p.read_bytes() for p in home.rglob("*") if p.is_file()})
        command[-1] = "different-session"
        refused = subprocess.run(command, cwd=self.base, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("session binding differs", refused.stderr)
        self.assertNotIn("Traceback", refused.stderr)

    def test_relocation_successor_draft_is_deterministic_and_has_no_old_authority(self) -> None:
        from intent_guardian_parts.session_workspace import relocation_review_contract
        home, path = self.guardian_fixture()
        old = load_contract(path)
        old["approved_event_fingerprints"] = ["a" * 64]
        old["runtime"]["approved_proposal_digests"] = ["b" * 64]
        old["runtime"]["future_authority_extension"] = {"allow": True}
        old["future_session_token"] = "synthetic-not-an-authority"
        old["permissions"]["external_write"] = "allow"
        original = copy.deepcopy(old)
        before = {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}
        first = relocation_review_contract(old, self.target, "c" * 64)
        second = relocation_review_contract(old, self.target, "c" * 64)
        self.assertEqual(first, second)
        self.assertEqual(old, original)
        self.assertEqual(first["objective"], old["objective"])
        self.assertEqual(first["constraints"], old["constraints"])
        self.assertEqual(first["acceptance_criteria"], old["acceptance_criteria"])
        self.assertEqual(first["revision"], old["revision"] + 1)
        self.assertNotEqual(first["task_epoch"], old["task_epoch"])
        self.assertEqual(first["status"], "paused")
        self.assertEqual(first["confirmed_by"], "workspace-rebind-pending-intent-review")
        self.assertTrue(first["confirmation"]["required"])
        self.assertTrue(first["runtime"]["pause_requires_revision"])
        self.assertEqual(first["permissions"], {"local_write": False, "external_write": "deny", "destructive": "deny"})
        self.assertEqual(first["continuation"]["grants"], [])
        self.assertEqual(first["approved_event_fingerprints"], [])
        for key in ("approval_receipts", "approved_proposal_digests", "authorized_events", "task_lanes",
                    "open_events", "pending_verifications", "host_observations", "task_continuations"):
            self.assertEqual(first["runtime"][key], [], key)
        self.assertNotIn("future_authority_extension", first["runtime"])
        self.assertNotIn("future_session_token", first)
        self.assertEqual(before, {p: p.read_bytes() for p in home.rglob("*") if p.is_file()})
        self.assertFalse(self.target.exists())

    def test_successor_rebases_only_structured_workspace_locators_without_authority(self) -> None:
        from intent_guardian_parts.session_workspace import relocation_review_contract
        _, path = self.guardian_fixture()
        old = load_contract(path)
        sibling = str(self.root) + "-unrelated/file.txt"
        ambiguous = str(self.root / "../outside.txt")
        old["constraints"].update(
            allowed_paths=[str(self.root), str(self.root / "src/**"), "relative/**", sibling, ambiguous],
            frozen_paths=[str(self.root / "secrets.env")],
            preserve=["historical locator " + str(self.root)],
        )
        original = copy.deepcopy(old)
        new = relocation_review_contract(old, self.target, "c" * 64, rebase_paths=True)
        self.assertEqual(new["constraints"]["allowed_paths"],
                         [str(self.target), str(self.target / "src/**"), "relative/**", sibling, ambiguous])
        self.assertEqual(new["constraints"]["frozen_paths"], [str(self.target / "secrets.env")])
        self.assertEqual(new["constraints"]["preserve"], old["constraints"]["preserve"])
        self.assertEqual(old, original)
        self.assertEqual(new["intent_id"], old["intent_id"])
        self.assertNotEqual(new["task_epoch"], old["task_epoch"])
        self.assertEqual(new["status"], "paused")
        self.assertFalse(new["permissions"]["local_write"])
        self.assertEqual(new["runtime"]["approval_receipts"], [])

    def test_linked_task_rebases_facts_across_the_exact_moved_repository_only(self) -> None:
        from intent_guardian_parts.session_workspace import relocation_review_contract
        old = default_contract(intent_id="linked", objective="linked task", acceptance_criteria=["review"],
                               workspace=self.linked, mode="enforce", confirmed_by="fixture")
        old["constraints"]["allowed_paths"] = [str(self.linked / "src/**"), str(self.root / "shared/**")]
        target = self.target / ".worktrees/task"
        new = relocation_review_contract(old, target, "c" * 64,
            repository_source=self.root, repository_destination=self.target, rebase_paths=True)
        self.assertEqual(new["constraints"]["allowed_paths"], [str(target / "src/**"), str(self.target / "shared/**")])
        self.assertEqual(new["status"], "paused")
        with self.assertRaisesRegex(IntentGuardianError, "differs from repository mapping"):
            relocation_review_contract(old, self.target / "wrong-task", "c" * 64,
                repository_source=self.root, repository_destination=self.target)

    def test_relocation_successor_binding_covers_plan_and_destination(self) -> None:
        from intent_guardian_parts.session_workspace import relocation_review_contract
        _, path = self.guardian_fixture()
        old = load_contract(path)
        one = relocation_review_contract(old, self.target, "a" * 64)
        two = relocation_review_contract(old, self.target, "b" * 64)
        three = relocation_review_contract(old, self.base / "another", "a" * 64)
        self.assertEqual(len({row["repository_relocation"]["binding_sha256"] for row in (one, two, three)}), 3)
        self.assertTrue(all(row["task_epoch"] != old["task_epoch"] for row in (one, two, three)))
        with self.assertRaisesRegex(IntentGuardianError, "exact plan id"):
            relocation_review_contract(old, self.target, "current")

    def native_review(self) -> tuple[Path, Path, dict, dict]:
        from host_capabilities import provision_provenance_key
        from intent_guardian import native_decision_preview
        home, path = self.guardian_fixture()
        patch = mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)})
        patch.start()
        self.addCleanup(patch.stop)
        provision_provenance_key(home)
        plan = relocation.prepare_relocation_plan(
            home, path, self.root, self.target, provider="codex", session_id="fixture-session",
        )
        preview = native_decision_preview(
            path, kind="repository-relocation", decision="approve", target=plan["plan_id"],
            provider="codex", session_id="fixture-session",
        )
        return home, path, plan, preview

    def observe_review(self, path: Path, preview: dict, **overrides) -> dict:
        from intent_guardian import observe_native_permission_request
        payload = {
            "client": "codex", "session_id": "fixture-session", "cwd": str(self.root),
            "intent_contract": str(path), "permission_mode": "default", "tool_name": "Bash",
            "tool_input": {"command": shlex.join(preview["command_argv"]), "description": preview["description"]},
        }
        payload.update(overrides)
        return observe_native_permission_request(payload, provider="codex")

    def execute_review(self, path: Path, plan: dict) -> dict:
        from intent_guardian import execute_native_decision
        return execute_native_decision(
            path, kind="repository-relocation", decision="approve", target=plan["plan_id"],
            provider="codex", session_id="fixture-session",
        )

    def execution_fixture(self, *, outcome: str | None = "allow", observed: bool = True):
        """Synthetic native producer; this is NOT live host approval evidence."""
        from approval_invariant import ask_typed_approval, observe_typed_prompt, decide_typed_approval
        from intent_guardian_parts.approvals import _native_binding_snapshot
        home, path, plan, _ = self.native_review()
        context = relocation.relocation_review_context(home, path, plan["plan_id"], provider="codex",
                                                     session_id="fixture-session", _execution=True)["context"]
        snapshot = _native_binding_snapshot(path, context, "fixture-session")
        request = ask_typed_approval(path, snapshot=snapshot, kind="intent-confirmation",
                                     source="codex_permission_request", intent_id=context["intent_id"])
        if observed:
            observe_typed_prompt(path, request_id=request["request_id"], snapshot=snapshot,
                                 provider="codex", session_id="fixture-session", prompt_shown=True,
                                 decision_owner="human")
        if outcome is not None:
            decide_typed_approval(path, request_id=request["request_id"], receipt_id=request["request_identity"],
                                 outcome=outcome, snapshot=snapshot, current_snapshot=snapshot,
                                 provider="codex", session_id="fixture-session", decision_owner="human",
                                 actor="permission-request:codex")
        return home, path, plan, context

    def prepare_execution(self, home: Path, path: Path, plan: dict) -> dict:
        return relocation._prepare_relocation_execution(home, path, plan["plan_id"], provider="codex",
                                                       session_id="fixture-session")

    def test_preflight_retains_obsolete_display_card_without_treating_it_as_authority(self) -> None:
        from approval_invariant import ask_approval, event_store_path
        home, path = self.guardian_fixture()
        contract = load_contract(path)
        ask_approval(path, intent_id=contract["intent_id"], intent_revision=contract["revision"],
                     kind="intent-confirmation", target="old display", source="intent_confirmation_card")
        with self.assertRaisesRegex(IntentGuardianError, "open approval question"):
            self.preflight(home)
        contract["revision"] += 1
        write_contract(path, contract)
        before = event_store_path(path).read_bytes()
        self.assertEqual(self.preflight(home)["bindings"]["effect_debt_count"], 0)
        self.assertEqual(event_store_path(path).read_bytes(), before)
        # An old request from a different source cannot borrow that exception.
        ask_approval(path, intent_id=contract["intent_id"], intent_revision=contract["revision"] - 1,
                     kind="intent-confirmation", target="other question", source="codex_permission_request")
        with self.assertRaisesRegex(IntentGuardianError, "open approval question"):
            self.preflight(home)

    def test_approval_ttl_boundary_matches_authoritative_projection(self) -> None:
        from approval_invariant import ask_approval, event_store_path, open_requests, summary
        home, path = self.guardian_fixture()
        contract = load_contract(path)
        origin = datetime(2000, 1, 1, tzinfo=timezone.utc)
        with mock.patch("approval_invariant.datetime", wraps=datetime) as clock:
            clock.now.return_value = origin
            ask_approval(path, intent_id=contract["intent_id"], intent_revision=contract["revision"],
                kind="proposal", target="old-proposal", source="codex_permission_request", ttl_seconds=300)
            before = event_store_path(path).read_bytes()
            for elapsed in (299.999999, 300, 301):
                with self.subTest(elapsed=elapsed):
                    clock.now.return_value = origin + timedelta(seconds=elapsed)
                    expected = 1 if elapsed < 300 else 0
                    self.assertEqual(len(open_requests(path)), expected)
                    self.assertEqual(summary(path)["open"], expected)
                    if expected:
                        with self.assertRaisesRegex(IntentGuardianError, "open approval question"):
                            self.preflight(home)
                    else:
                        self.assertFalse(self.preflight(home)["execution_authorized"])
                    self.assertEqual(event_store_path(path).read_bytes(), before)

    def test_typed_reassessment_still_blocks_until_expiry_and_cannot_be_allowed_late(self) -> None:
        from approval_invariant import (ApprovalInvariantError, ask_typed_approval,
            decide_typed_approval, event_store_path, observe_typed_prompt, open_requests, summary)
        home, path = self.guardian_fixture()
        origin = datetime(2000, 1, 1, tzinfo=timezone.utc)
        snapshot = {"card_sha256": "fixture-card", "provider": "codex", "session_id": "fixture-session",
            "lane_sha256": hashlib.sha256(b"codex\0fixture-session").hexdigest(),
            "target_sha256": "fixture-target", "revision": 1,
            "journal_sha256": "fixture-journal", "effect_sha256": "fixture-effect",
            "world_state_sha256": "fixture-world"}
        with mock.patch("approval_invariant.datetime", wraps=datetime) as clock:
            clock.now.return_value = origin
            asked = ask_typed_approval(path, snapshot=snapshot, kind="proposal",
                source="codex_permission_request", ttl_seconds=600, reassess_after_seconds=300)
            observe_typed_prompt(path, request_id=asked["request_id"], snapshot=snapshot,
                provider="codex", session_id="fixture-session", prompt_shown=True, decision_owner="human")
            before = event_store_path(path).read_bytes()
            for seconds in (0, 300, 599, 600):
                with self.subTest(seconds=seconds):
                    clock.now.return_value = origin + timedelta(seconds=seconds)
                    if seconds < 600:
                        self.assertEqual(len(open_requests(path)), 1)
                        with self.assertRaisesRegex(IntentGuardianError, "open approval question"):
                            self.preflight(home)
                    else:
                        self.assertEqual(summary(path)["expired"], 1)
                        self.assertFalse(self.preflight(home)["execution_authorized"])
                        with self.assertRaisesRegex(ApprovalInvariantError, "expired"):
                            decide_typed_approval(path, request_id=asked["request_id"],
                                receipt_id=asked["request_identity"], outcome="allow", snapshot=snapshot,
                                current_snapshot=snapshot, provider="codex", session_id="fixture-session",
                                decision_owner="human", actor="permission-request:codex")
                    self.assertEqual(event_store_path(path).read_bytes(), before)

    def test_expired_question_does_not_hide_unfinished_native_transaction(self) -> None:
        from approval_invariant import ask_approval, open_requests
        home, path = self.guardian_fixture()
        with mock.patch("approval_invariant.datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2000, 1, 1, tzinfo=timezone.utc)
            ask_approval(path, intent_id="relocation-fixture", intent_revision=1,
                kind="proposal", target="old-proposal", source="codex_permission_request", ttl_seconds=300)
        self.assertEqual(open_requests(path), [])
        # Deliberate journal projection fault injection: TTL affects the question,
        # never the independent native transaction gate.
        with mock.patch("native_decision_journal.load_projection_read_only", return_value={
            "transactions": {"fixture": {"stage": "approval_decided"}}}):
            with self.assertRaisesRegex(IntentGuardianError, "unfinished native transaction"):
                self.preflight(home)

    def test_expired_history_cannot_hide_malformed_approval_ledger(self) -> None:
        from approval_invariant import ask_approval, event_store_path
        home, path = self.guardian_fixture()
        with mock.patch("approval_invariant.datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2000, 1, 1, tzinfo=timezone.utc)
            ask_approval(path, intent_id="relocation-fixture", intent_revision=1,
                kind="proposal", target="old-proposal", source="codex_permission_request", ttl_seconds=300)
        ledger = event_store_path(path)
        rows = [json.loads(line) for line in ledger.read_text().splitlines()]
        rows[0]["expires_at"] = "invalid-deadline"
        damaged = "".join(json.dumps(row) + "\n" for row in rows).encode()
        ledger.write_bytes(damaged)  # Isolated fixture corruption, never production history.
        with self.assertRaisesRegex(IntentGuardianError, "cannot verify authoritative ledger"):
            self.preflight(home)
        self.assertEqual(ledger.read_bytes(), damaged)
        self.assertFalse(self.target.exists())

    def test_execution_card_cannot_reuse_data_only_review_allow(self) -> None:
        from native_decision_journal import load_projection_read_only
        home, path, plan, preview = self.native_review()
        self.assertEqual(self.observe_review(path, preview)["action"], "defer")
        self.execute_review(path, plan)
        before = load_projection_read_only(path)
        execution = relocation.relocation_review_context(home, path, plan["plan_id"], provider="codex",
                                                        session_id="fixture-session", _execution=True)
        self.assertIn("移动上述根目录", execution["card"]["本次动作"])
        self.assertNotEqual(execution["bound_card"], preview["decision_card"])
        with self.assertRaisesRegex(IntentGuardianError, "execution-card native Allow"):
            self.prepare_execution(home, path, plan)
        self.assertEqual(load_projection_read_only(path), before)
        self.assertFalse(self.target.exists())

    def test_execution_native_prepare_uses_t12_and_one_t13_transaction(self) -> None:
        from approval_invariant import event_store_path
        from native_decision_journal import load_projection_read_only, journal_path, advance_with_authority, NativeAuthorityReaders
        home, path, plan, _ = self.execution_fixture()
        contract_before = path.read_bytes()
        mapping_before = session_workspace_path(home, "codex", "fixture-session").read_bytes()
        approval_before = event_store_path(path).read_bytes()
        result = self.prepare_execution(home, path, plan)
        self.assertEqual(result["status"], "approval_decided")
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["executor_registered"])
        projection = load_projection_read_only(path)
        self.assertEqual(len(projection["seals"]), 1)
        self.assertEqual(len(projection["transactions"]), 1)
        tx = projection["transactions"][result["transaction_id"]]
        self.assertEqual(tx["binding"]["action"], relocation.EXECUTION_ACTION)
        self.assertEqual(tx["stage_details"]["approval_decided"]["authority_source"], "canonical-t12-approval-jsonl")
        journal_before = journal_path(path).read_bytes()
        self.assertEqual(self.prepare_execution(home, path, plan), result)
        self.assertEqual(journal_path(path).read_bytes(), journal_before)
        self.assertEqual(event_store_path(path).read_bytes(), approval_before)
        self.assertEqual(path.read_bytes(), contract_before)
        self.assertEqual(session_workspace_path(home, "codex", "fixture-session").read_bytes(), mapping_before)
        self.assertEqual(relocation._read_write_fences(home), [])
        self.assertFalse(self.target.exists())
        # No generic journal route can manufacture a physical completion from
        # the approval or from existing contract state.
        pending = advance_with_authority(path, result["transaction_id"], readers=NativeAuthorityReaders(None, None, None, None))
        self.assertEqual(pending["stage"], "approval_decided")
        self.assertFalse(pending["advanced"])

    def test_execution_prepare_recovers_each_persisted_native_boundary_once(self) -> None:
        from approval_invariant import event_store_path
        from native_decision_journal import load_projection_read_only
        home, path, plan, _ = self.execution_fixture()
        before = event_store_path(path).read_bytes()
        for stage in ("sealed", "prepared", "approval_decided"):
            def interrupt(current: str) -> None:
                if current == stage:
                    raise RuntimeError("synthetic boundary " + stage)
            with self.subTest(stage=stage), mock.patch.object(relocation, "_execution_prepare_boundary", side_effect=interrupt):
                with self.assertRaisesRegex(RuntimeError, "synthetic boundary"):
                    self.prepare_execution(home, path, plan)
            self.assertEqual(event_store_path(path).read_bytes(), before)
        result = self.prepare_execution(home, path, plan)
        projection = load_projection_read_only(path)
        self.assertEqual(len(projection["seals"]), 1)
        self.assertEqual(len(projection["transactions"]), 1)
        self.assertEqual(projection["transactions"][result["transaction_id"]]["stage"], "approval_decided")
        self.assertFalse(self.target.exists())

    def test_execution_deny_cannot_create_seal_transaction_or_fence(self) -> None:
        from native_decision_journal import load_projection_read_only
        home, path, plan, _ = self.execution_fixture(outcome="deny")
        before = load_projection_read_only(path)
        with self.assertRaisesRegex(IntentGuardianError, "execution-card native Allow"):
            self.prepare_execution(home, path, plan)
        self.assertEqual(load_projection_read_only(path), before)
        self.assertEqual(relocation._read_write_fences(home), [])

    def test_execution_recovers_after_actual_process_exit_at_each_boundary(self) -> None:
        from approval_invariant import event_store_path
        from native_decision_journal import journal_path, load_projection_read_only
        home, path, plan, _ = self.execution_fixture()
        approval_before = event_store_path(path).read_bytes()
        script = r'''
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from intent_guardian_parts import repository_relocation as r
stage = sys.argv[5]
def stop_at_boundary(current):
    if current == stage:
        os._exit(73)
r._execution_prepare_boundary = stop_at_boundary
result = r._prepare_relocation_execution(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4],
                                         provider="codex", session_id="fixture-session")
print(json.dumps(result))
'''
        command = [sys.executable, "-B", "-c", script, str(ROOT / "scripts/kb"), str(home), str(path), plan["plan_id"]]
        for stage in ("sealed", "prepared", "approval_decided"):
            with self.subTest(stage=stage):
                child = subprocess.run(command + [stage], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)
                self.assertEqual(child.returncode, 73, child.stdout + child.stderr)
                self.assertEqual(event_store_path(path).read_bytes(), approval_before)
                self.assertTrue(self.root.exists())
                self.assertFalse(self.target.exists())
        before = journal_path(path).read_bytes()
        resumed = subprocess.run(command + ["none"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)["status"], "approval_decided")
        self.assertEqual(journal_path(path).read_bytes(), before)
        self.assertEqual(len(load_projection_read_only(path)["transactions"]), 1)

    def test_execution_rejects_wrong_native_actor_before_sealing(self) -> None:
        from approval_invariant import decide_typed_approval, load_projection
        from native_decision_journal import load_projection_read_only
        home, path, plan, _ = self.execution_fixture(outcome=None)
        request = next(iter(load_projection(path)["requests"].values()))
        decide_typed_approval(path, request_id=request["request_id"], receipt_id=request["request_identity"],
                             outcome="allow", snapshot=request["snapshot"], current_snapshot=request["snapshot"],
                             provider="codex", session_id="fixture-session", decision_owner="human", actor="fixture-not-native")
        before = load_projection_read_only(path)
        with self.assertRaises(RuntimeError):
            self.prepare_execution(home, path, plan)
        self.assertEqual(load_projection_read_only(path), before)

    def test_execution_unobserved_request_cannot_enter_transaction(self) -> None:
        from native_decision_journal import load_projection_read_only
        home, path, plan, _ = self.execution_fixture(outcome=None, observed=False)
        before = load_projection_read_only(path)
        with self.assertRaisesRegex(IntentGuardianError, "open approval question"):
            self.prepare_execution(home, path, plan)
        self.assertEqual(load_projection_read_only(path), before)

    def test_execution_material_drift_after_allow_is_not_excused_by_receipt(self) -> None:
        from native_decision_journal import load_projection_read_only
        home, path, plan, _ = self.execution_fixture()
        (self.root / "tracked.txt").write_text("changed after Allow\n")
        before = load_projection_read_only(path)
        with self.assertRaisesRegex(IntentGuardianError, "world changed"):
            self.prepare_execution(home, path, plan)
        self.assertEqual(load_projection_read_only(path), before)

    def test_execution_resume_exemption_does_not_apply_to_review_or_other_transaction(self) -> None:
        from native_decision_journal import load_projection_read_only
        home, path, plan, _ = self.execution_fixture()
        self.prepare_execution(home, path, plan)
        with self.assertRaisesRegex(IntentGuardianError, "unfinished native transaction"):
            relocation.relocation_review_context(home, path, plan["plan_id"], provider="codex", session_id="fixture-session")
        real_projection = load_projection_read_only(path)
        alien = copy.deepcopy(next(iter(real_projection["transactions"].values())))
        alien["binding"]["session_id"] = "other-session"
        real_projection["transactions"]["another"] = alien
        with mock.patch("native_decision_journal.load_projection_read_only", return_value=real_projection):
            with self.assertRaisesRegex(IntentGuardianError, "unfinished native transaction"):
                self.prepare_execution(home, path, plan)

    def test_execution_wrong_session_fails_and_public_preview_has_no_writes(self) -> None:
        from intent_guardian import native_decision_preview
        from native_decision_journal import load_projection_read_only
        home, path, plan, _ = self.execution_fixture()
        before = load_projection_read_only(path)
        with self.assertRaisesRegex(IntentGuardianError, "current lane differs"):
            relocation._prepare_relocation_execution(home, path, plan["plan_id"], provider="codex", session_id="other-session")
        preview = native_decision_preview(path, kind=relocation.EXECUTION_KIND, decision="execute", target=plan["plan_id"],
                                          provider="codex", session_id="fixture-session")
        self.assertIn("按 Allow 执行整仓迁移", preview["description"])
        self.assertEqual(load_projection_read_only(path), before)

    def test_public_native_execution_observes_prompt_and_cli_commits_exactly_once(self) -> None:
        from intent_guardian import native_decision_preview
        from native_decision_journal import load_projection_read_only, journal_path
        from approval_invariant import event_store_path as approval_store
        home, path, plan, _ = self.native_review()
        preview = native_decision_preview(path, kind=relocation.EXECUTION_KIND, decision="execute", target=plan["plan_id"],
                                          provider="codex", session_id="fixture-session")
        observed = self.observe_review(path, preview)
        self.assertEqual(observed["action"], "defer", observed)
        self.assertTrue(self.root.exists())
        self.assertEqual(load_projection_read_only(path)["transactions"], {})
        command = [sys.executable, "-B", str(ROOT / "scripts/kb/intent-guardian.py"), *preview["argv"], "--home", str(home)]
        child = subprocess.run(command, cwd=self.base, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
        result = json.loads(child.stdout)
        self.assertEqual(result["status"], "committed")
        before = (journal_path(path).read_bytes(), approval_store(path).read_bytes())
        repeated = subprocess.run(command, cwd=self.base, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
        self.assertEqual(json.loads(repeated.stdout), result)
        self.assertEqual((journal_path(path).read_bytes(), approval_store(path).read_bytes()), before)

    def test_recovery_hook_is_reachable_after_root_moves_and_rejects_unbound_commands(self) -> None:
        from intent_guardian_parts.audit import process_hook
        from native_decision_journal import journal_path
        home, path, plan, _ = self.execution_fixture()
        def stop(stage):
            if stage == "moved":
                raise RuntimeError("fixture moved")
        with mock.patch.object(relocation, "_relocation_filesystem_boundary", side_effect=stop):
            with self.assertRaisesRegex(RuntimeError, "fixture moved"):
                relocation.execute_repository_relocation(home, plan["plan_id"], provider="codex", session_id="fixture-session")
        command = [sys.executable, str(ROOT / "scripts/kb/intent-guardian.py"), "recover-repository-relocation",
                   plan["plan_id"], "--provider", "codex", "--session-id", "fixture-session"]
        payload = {"client": "codex", "session_id": "fixture-session", "cwd": str(self.root),
                   "intent_contract": str(path), "tool_name": "Bash", "tool_input": {"command": shlex.join(command)}}
        before = journal_path(path).read_bytes()
        decision, selected = process_hook(payload, phase="started", provider="codex")
        self.assertEqual(decision.dispatch, "allow")
        self.assertEqual(decision.reason_code, "repository_relocation_recovery")
        self.assertIsNone(selected)
        self.assertEqual(journal_path(path).read_bytes(), before)
        self.assertIsNone(relocation.route_relocation_recovery(
            {**payload, "tool_name": "mcp__untrusted__write"}, home=home,
            provider="codex", session_id="fixture-session"))
        for altered in (shlex.join(command) + " && echo invalid", shlex.join(command) + " --session-id fixture-session",
                        shlex.join(command[:-1] + ["another-session"]),
                        shlex.join(command) + " --home /some/other/home"):
            bad = {**payload, "tool_input": {"command": altered}}
            decision, _ = process_hook(bad, phase="started", provider="codex")
            self.assertEqual(decision.dispatch, "deny", altered)
        child = subprocess.run(command + ["--home", str(home)], cwd=self.base, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
        self.assertEqual(json.loads(child.stdout)["status"], "committed")
        decision, selected = process_hook(payload, phase="completed", provider="codex")
        self.assertEqual(decision.reason_code, "repository_relocation_recovery")

    def test_recovery_hook_cannot_create_authority_for_a_review_only_plan(self) -> None:
        from intent_guardian_parts.audit import process_hook
        from native_decision_journal import load_projection_read_only
        home, path, plan, _ = self.native_review()
        command = [sys.executable, str(ROOT / "scripts/kb/intent-guardian.py"), "recover-repository-relocation",
                   plan["plan_id"], "--provider", "codex", "--session-id", "fixture-session"]
        payload = {"client": "codex", "session_id": "fixture-session", "cwd": str(self.root),
                   "intent_contract": str(path), "tool_name": "Bash", "tool_input": {"command": shlex.join(command)}}
        decision, _ = process_hook(payload, phase="started", provider="codex")
        self.assertEqual(decision.dispatch, "deny")
        self.assertEqual(load_projection_read_only(path)["transactions"], {})
        self.assertTrue(self.root.exists())

    def physical_execution(self, home: Path, plan: dict) -> dict:
        return relocation._execute_relocation_filesystem(home, plan["plan_id"], provider="codex", session_id="fixture-session")

    def test_complete_relocation_archives_sources_commits_once_and_keeps_new_task_paused(self) -> None:
        from approval_invariant import event_store_path as approval_store
        from native_decision_journal import load_projection_read_only, journal_path
        from intent_guardian_parts.session_workspace import resolve_session_contract
        home, path, plan, _ = self.execution_fixture()
        self.prepare_execution(home, path, plan)
        original = path.read_bytes()
        approvals_before = approval_store(path).read_bytes()
        result = relocation.execute_repository_relocation(home, plan["plan_id"], provider="codex", session_id="fixture-session")
        self.assertEqual(result["status"], "committed")
        self.assertTrue(result["fence_released"])
        self.assertFalse(result["authority_transferred"])
        target = Path(result["contract_path"])
        current = load_contract(target)
        self.assertEqual(current["status"], "paused")
        self.assertTrue(current["confirmation"]["required"])
        self.assertFalse(current["permissions"]["local_write"])
        self.assertEqual(current["runtime"]["approval_receipts"], [])
        self.assertEqual(resolve_session_contract(home, "codex", "fixture-session"), target)
        frozen = json.loads(Path(plan["plan_path"]).read_text())
        archive = relocation._relocation_archive_path(frozen, path)
        self.assertEqual(archive.read_bytes(), original)
        self.assertFalse(path.exists())
        with self.assertRaisesRegex(IntentGuardianError, "historical evidence"):
            load_contract(archive)
        self.assertEqual(approval_store(path).read_bytes(), approvals_before)
        self.assertEqual(relocation._read_write_fences(home), [])
        projection = load_projection_read_only(path)
        self.assertEqual(len(projection["transactions"]), 1)
        self.assertEqual(next(iter(projection["transactions"].values()))["stage"], "committed")
        before = journal_path(path).read_bytes()
        self.assertEqual(relocation.execute_repository_relocation(home, plan["plan_id"], provider="codex", session_id="fixture-session"), result)
        self.assertEqual(journal_path(path).read_bytes(), before)

    def test_store_budget_fails_preflight_before_any_fence_or_move(self) -> None:
        home, path = self.guardian_fixture()
        before = path.read_bytes()
        with mock.patch.object(relocation, "MAX_STORE_TOTAL_BYTES", 1):
            with self.assertRaisesRegex(IntentGuardianError, "stores.*total"):
                self.preflight(home)
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue(self.root.exists())
        self.assertFalse(self.target.exists())
        self.assertEqual(relocation._read_write_fences(home), [])
        self.assertFalse(list((home / "intent/repository-relocations").glob("*.plan.json")))

    def test_large_audit_survives_move_archive_link_interruption_and_recovery(self) -> None:
        from intent_guardian_parts.state import audit_path
        from native_decision_journal import journal_path, load_projection_read_only
        home, path, plan, _ = self.execution_fixture()
        audit = audit_path(path)
        expected = hashlib.sha256(audit.read_bytes() if audit.exists() else b"")
        chunk = (json.dumps({"schema":"synthetic-capacity-observation-v1", "padding":"x" * 1024**2}) + "\n").encode()
        with audit.open("ab") as stream:
            for _ in range(96):
                stream.write(chunk)
                expected.update(chunk)
        audit.chmod(0o600)
        self.prepare_execution(home, path, plan)
        def stop(stage):
            if stage == "archive_linked:" + path.name:
                raise RuntimeError("synthetic archival link interruption")
        with mock.patch.object(relocation, "_relocation_rebind_boundary", side_effect=stop):
            with self.assertRaisesRegex(RuntimeError, "synthetic archival link"):
                relocation.execute_repository_relocation(home, plan["plan_id"], provider="codex", session_id="fixture-session")
        self.assertTrue(self.target.exists())
        self.assertEqual(path.stat().st_nlink, 2)
        result = relocation.execute_repository_relocation(home, plan["plan_id"], provider="codex", session_id="fixture-session")
        self.assertEqual(result["status"], "committed")
        self.assertTrue(result["fence_released"])
        actual = hashlib.sha256()
        with audit.open("rb") as stream:
            for block in iter(lambda: stream.read(1024**2), b""):
                actual.update(block)
        self.assertEqual(actual.hexdigest(), expected.hexdigest())
        before = journal_path(path).read_bytes()
        self.assertEqual(relocation.execute_repository_relocation(home, plan["plan_id"], provider="codex", session_id="fixture-session"), result)
        self.assertEqual(journal_path(path).read_bytes(), before)
        self.assertEqual(len(load_projection_read_only(path)["transactions"]), 1)
        successor = load_contract(Path(result["contract_path"]))
        self.assertEqual(successor["status"], "paused")
        self.assertFalse(successor["permissions"]["local_write"])

    def test_complete_relocation_recovers_process_exit_at_every_rebind_and_commit_boundary(self) -> None:
        from approval_invariant import event_store_path as approval_store
        from native_decision_journal import load_projection_read_only, journal_path
        home, path, plan, _ = self.execution_fixture()
        self.prepare_execution(home, path, plan)
        approval_before = approval_store(path).read_bytes()
        original = path.read_bytes()
        frozen = json.loads(Path(plan["plan_path"]).read_text())
        successor = relocation._relocation_successor_path(frozen["preflight"], path)
        mapping = session_workspace_path(home, "codex", "fixture-session")
        script = r'''
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from intent_guardian_parts import repository_relocation as r
import native_decision_journal as n
def stop(current):
    if current == sys.argv[4]:
        os._exit(73)
r._relocation_rebind_boundary = stop
n._relocation_commit_boundary = stop
print(json.dumps(r.execute_repository_relocation(Path(sys.argv[2]), sys.argv[3],
                                                provider="codex", session_id="fixture-session")))
'''
        command = [sys.executable, "-B", "-c", script, str(ROOT / "scripts/kb"), str(home), plan["plan_id"]]
        boundaries = ["rebind_prepared", "successor_written:" + successor.name,
                      "archive_linked:" + path.name, "source_archived:" + path.name,
                      "mapping_written:" + mapping.name, "rebind_verified",
                      "effect_applied_receipt", "effect_applied", "contract_applied_receipt",
                      "contract_applied", "committed_receipt", "committed", "native_committed",
                      "terminal_recorded", "fence_retired"]
        for boundary in boundaries:
            with self.subTest(boundary=boundary):
                child = subprocess.run(command + [boundary], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
                self.assertEqual(child.returncode, 73, child.stdout + child.stderr)
                self.assertEqual(approval_store(path).read_bytes(), approval_before)
                self.assertEqual(bool(relocation._read_write_fences(home)), boundary != "fence_retired")
                if successor.exists() and boundary != "fence_retired":
                    for writer in ("contract", "approval", "effect", "native"):
                        probe = self.fence_child(home, successor, writer)
                        self.assertEqual(probe.returncode, 2, probe.stdout + probe.stderr)
        before = journal_path(path).read_bytes()
        child = subprocess.run(command + ["none"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
        self.assertEqual(json.loads(child.stdout)["status"], "committed")
        self.assertEqual(journal_path(path).read_bytes(), before)
        self.assertEqual(relocation._relocation_archive_path(frozen, path).read_bytes(), original)
        projection = load_projection_read_only(path)
        self.assertEqual(len(projection["transactions"]), 1)
        self.assertEqual(next(iter(projection["transactions"].values()))["stage"], "committed")

    def test_complete_relocation_recovers_native_append_before_and_after_anchor(self) -> None:
        from native_decision_journal import journal_path, load_projection_read_only
        home, path, plan, _ = self.execution_fixture()
        self.prepare_execution(home, path, plan)
        script = r'''
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from intent_guardian_parts import repository_relocation as r
import native_decision_journal as n
real_write = n._atomic_write_json
def crash(path, value):
    real_write(path, value)
    match = {"pending": n.HEAD_PENDING_SCHEMA, "anchored": n.HEAD_PENDING_ANCHOR_SCHEMA,
             "appended": n.HEAD_ANCHOR_SCHEMA}.get(sys.argv[4])
    if value.get("schema") == match:
        os._exit(73)
n._atomic_write_json = crash
print(json.dumps(r.execute_repository_relocation(Path(sys.argv[2]), sys.argv[3],
                                                provider="codex", session_id="fixture-session")))
'''
        command = [sys.executable, "-B", "-c", script, str(ROOT / "scripts/kb"), str(home), plan["plan_id"]]
        for boundary in ("pending", "anchored", "appended"):
            child = subprocess.run(command + [boundary], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(child.returncode, 73, child.stdout + child.stderr)
            self.assertTrue(relocation._read_write_fences(home))
            with self.assertRaisesRegex(RuntimeError, "pending"):
                load_projection_read_only(path)
        child = subprocess.run(command + ["none"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
        self.assertEqual(json.loads(child.stdout)["status"], "committed")
        rows = [json.loads(line) for line in journal_path(path).read_text().splitlines()]
        for stage in ("effect_applied", "contract_applied", "committed"):
            self.assertEqual(sum(row.get("stage") == stage for row in rows), 1)

    def test_relocation_native_finalizer_keeps_other_writers_fenced_and_resets_on_error(self) -> None:
        import native_decision_journal as journal
        home, path, plan, _ = self.execution_fixture()
        frozen = json.loads(Path(plan["plan_path"]).read_text())
        successor = relocation._relocation_successor_path(frozen["preflight"], path)
        probes = []
        def stop(stage):
            if stage == "effect_applied_receipt":
                self.assertNotIn(successor, journal._RELOCATION_NATIVE_WRITES.get())
                for writer in ("contract", "approval", "effect", "native"):
                    child = self.fence_child(home, successor, writer)
                    self.assertEqual(child.returncode, 2, child.stdout + child.stderr)
                    probes.append(writer)
                raise RuntimeError("fixture finalizer interrupted")
        with mock.patch.object(journal, "_relocation_commit_boundary", side_effect=stop):
            with self.assertRaisesRegex(RuntimeError, "fixture finalizer interrupted"):
                relocation.execute_repository_relocation(home, plan["plan_id"], provider="codex", session_id="fixture-session")
        self.assertEqual(len(probes), 4)
        self.assertEqual(journal._RELOCATION_NATIVE_WRITES.get(), frozenset())
        with self.assertRaisesRegex(RuntimeError, "fenc"):
            journal.head_proof(path)
        result = relocation.execute_repository_relocation(home, plan["plan_id"], provider="codex", session_id="fixture-session")
        self.assertEqual(result["status"], "committed")

    def test_relocation_rejects_changed_successor_and_does_not_release_early(self) -> None:
        from native_decision_journal import journal_path
        home, path, plan, _ = self.execution_fixture()
        def stop(stage):
            if stage == "rebind_verified":
                raise RuntimeError("fixture before native commit")
        with mock.patch.object(relocation, "_relocation_rebind_boundary", side_effect=stop):
            with self.assertRaisesRegex(RuntimeError, "fixture before native commit"):
                relocation.execute_repository_relocation(home, plan["plan_id"], provider="codex", session_id="fixture-session")
        frozen = json.loads(Path(plan["plan_path"]).read_text())
        manifest = relocation._filesystem_manifest(home, frozen)
        recipe = relocation._rebind_recipe(home, frozen, manifest)
        with self.assertRaisesRegex(IntentGuardianError, "before native commitment"):
            relocation._finish_relocation_fence(home, frozen, manifest, recipe)
        successor = Path(recipe["contracts"][0]["target"])
        successor.write_text(successor.read_text() + " ")
        before = journal_path(path).read_bytes()
        with self.assertRaisesRegex(IntentGuardianError, "exact before/after"):
            relocation.execute_repository_relocation(home, plan["plan_id"], provider="codex", session_id="fixture-session")
        self.assertEqual(journal_path(path).read_bytes(), before)
        self.assertTrue(relocation._read_write_fences(home))

    def test_relocation_terminal_readback_does_not_revalidate_or_replay_later_task_work(self) -> None:
        from native_decision_journal import journal_path
        home, path, plan, _ = self.execution_fixture()
        result = relocation.execute_repository_relocation(home, plan["plan_id"], provider="codex", session_id="fixture-session")
        successor = Path(result["contract_path"])
        current = load_contract(successor)
        current["objective"] = "fixture subsequent task, not migration replay"
        current["revision"] += 1
        write_contract(successor, current)
        (self.target / "tracked.txt").write_text("subsequent task content\n")
        before = (successor.read_bytes(), journal_path(path).read_bytes())
        self.assertEqual(relocation.execute_repository_relocation(home, plan["plan_id"], provider="codex", session_id="fixture-session"), result)
        self.assertEqual((successor.read_bytes(), journal_path(path).read_bytes()), before)
        self.assertEqual((self.target / "tracked.txt").read_text(), "subsequent task content\n")

    def test_physical_executor_preserves_dirty_content_permissions_and_history(self) -> None:
        from native_decision_journal import journal_path
        (self.root / "tracked.txt").write_text("staged change\n")
        self.git(self.root, "add", "tracked.txt")
        (self.root / "tracked.txt").write_text("unstaged change\n")
        (self.root / "untracked.txt").write_text("untracked\n")
        (self.root / "ignored").mkdir()
        (self.root / "ignored/private").write_text("fixture, not a credential\n")
        (self.root / "ignored/private").chmod(0o400)
        (self.linked / ".git").chmod(0o400)
        (self.root / ".git/worktrees/task/gitdir").chmod(0o400)
        home, path, plan, _ = self.execution_fixture()
        self.prepare_execution(home, path, plan)
        evidence = json.loads(Path(plan["plan_path"]).read_text())["preflight"]
        fence, _ = relocation._fence_inventory(home, evidence)
        before = relocation._frozen_store_bytes(fence)
        result = self.physical_execution(home, plan)
        self.assertEqual(result["status"], "physical_verified_rebind_pending")
        self.assertTrue(result["fence_active"])
        self.assertFalse(result["routing_verified"])
        self.assertFalse(self.root.exists())
        self.assertTrue(relocation.verify_repository_identity(evidence["repository"], moved=True))
        self.assertEqual(relocation._frozen_store_bytes(fence), before)
        pointer = self.target / ".worktrees/task/.git"
        self.assertEqual(stat.S_IMODE(pointer.stat().st_mode), 0o400)
        self.assertEqual(stat.S_IMODE((self.target / "ignored/private").stat().st_mode), 0o400)
        physical_before = (pointer.stat().st_ino, pointer.stat().st_mtime_ns, journal_path(path).read_bytes())
        self.assertEqual(self.physical_execution(home, plan), result)
        self.assertEqual((pointer.stat().st_ino, pointer.stat().st_mtime_ns, journal_path(path).read_bytes()), physical_before)
        # Normal writes remain inhibited. Physical success is not business
        # permission, a routing commit, or a reason to clear the fence.
        for operation in ("contract", "mapping", "approval", "effect", "native"):
            with self.subTest(operation=operation):
                child = self.fence_child(home, path, operation)
                self.assertEqual(child.returncode, 2, child.stdout + child.stderr)

    def test_physical_executor_recovers_actual_exit_after_every_mutation_boundary(self) -> None:
        from native_decision_journal import journal_path
        home, path, plan, _ = self.execution_fixture()
        self.prepare_execution(home, path, plan)
        journal_before = journal_path(path).read_bytes()
        repo = json.loads(Path(plan["plan_path"]).read_text())["preflight"]["repository"]
        script = r'''
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from intent_guardian_parts import repository_relocation as r
def stop(current):
    if current == sys.argv[4]:
        os._exit(73)
r._relocation_filesystem_boundary = stop
print(json.dumps(r._execute_relocation_filesystem(Path(sys.argv[2]), sys.argv[3],
                                                provider="codex", session_id="fixture-session")))
'''
        command = [sys.executable, "-B", "-c", script, str(ROOT / "scripts/kb"), str(home), plan["plan_id"]]
        boundaries = ["manifest", "fenced", "moved"]
        for row in repo["git_links"]:
            if row["before"] != row["after"]:
                boundaries += ["link_staged:" + row["relative_path"], "link_repaired:" + row["relative_path"]]
        boundaries.append("physical_verified")
        for boundary in boundaries:
            with self.subTest(boundary=boundary):
                child = subprocess.run(command + [boundary], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
                self.assertEqual(child.returncode, 73, child.stdout + child.stderr)
                self.assertEqual(journal_path(path).read_bytes(), journal_before)
        child = subprocess.run(command + ["none"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
        self.assertEqual(json.loads(child.stdout)["filesystem_status"], "git_repaired")
        self.assertFalse(self.root.exists())
        self.assertEqual(journal_path(path).read_bytes(), journal_before)
        self.assertTrue(relocation.verify_repository_identity(repo, moved=True))

    def test_physical_executor_deny_leaves_roots_and_fence_unchanged(self) -> None:
        home, path, plan, _ = self.execution_fixture(outcome="deny")
        with self.assertRaisesRegex(IntentGuardianError, "execution-card native Allow"):
            self.physical_execution(home, plan)
        self.assertEqual(relocation._read_write_fences(home), [])
        self.assertTrue(self.root.exists())
        self.assertFalse(self.target.exists())

    def test_physical_executor_cannot_promote_review_consent_into_a_move(self) -> None:
        home, path, plan, preview = self.native_review()
        self.assertEqual(self.observe_review(path, preview)["action"], "defer")
        self.execute_review(path, plan)
        with self.assertRaisesRegex(IntentGuardianError, "execution-card native Allow"):
            self.physical_execution(home, plan)
        self.assertEqual(relocation._read_write_fences(home), [])
        self.assertTrue(self.root.exists())
        self.assertFalse(self.target.exists())

    def test_physical_executor_does_not_recreate_missing_fence_after_move(self) -> None:
        home, _, plan, _ = self.execution_fixture()
        def stop(stage: str) -> None:
            if stage == "moved":
                raise RuntimeError("synthetic moved interruption")
        with mock.patch.object(relocation, "_relocation_filesystem_boundary", side_effect=stop):
            with self.assertRaisesRegex(RuntimeError, "synthetic moved"):
                self.physical_execution(home, plan)
        fence = relocation._read_write_fences(home)[0]
        marker = relocation._fence_directory(home) / (fence["sha256"] + ".json")
        marker.unlink()  # corruption simulation in a disposable fixture
        pointer = self.target / ".worktrees/task/.git"
        before = pointer.read_bytes()
        with self.assertRaisesRegex(IntentGuardianError, "lost its fence"):
            self.physical_execution(home, plan)
        self.assertFalse(marker.exists())
        self.assertEqual(pointer.read_bytes(), before)

    def test_physical_executor_rejects_unknown_pointer_after_interruption(self) -> None:
        home, _, plan, _ = self.execution_fixture()
        def stop(stage: str) -> None:
            if stage == "moved":
                raise RuntimeError("synthetic moved interruption")
        with mock.patch.object(relocation, "_relocation_filesystem_boundary", side_effect=stop):
            with self.assertRaisesRegex(RuntimeError, "synthetic moved"):
                self.physical_execution(home, plan)
        pointer = self.target / ".worktrees/task/.git"
        pointer.write_text("gitdir: /unexpected-fixture-target\n")
        before = pointer.read_bytes()
        with self.assertRaisesRegex(IntentGuardianError, "neither the frozen"):
            self.physical_execution(home, plan)
        self.assertEqual(pointer.read_bytes(), before)
        self.assertEqual(len(relocation._read_write_fences(home)), 1)

    def test_relocation_rejects_line_separator_in_future_git_pointer_path(self) -> None:
        with self.assertRaisesRegex(IntentGuardianError, "line separators"):
            relocation.freeze_repository_identity(self.root, self.base / "new\nrepository")

    def test_native_exclusive_rename_preserves_python_audit_denial(self) -> None:
        home, _, plan, _ = self.execution_fixture()
        script = r'''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from intent_guardian_parts import repository_relocation as r
def deny(event, args):
    if event == "os.rename" and args[0] == sys.argv[4]:
        raise PermissionError("synthetic audit refusal")
sys.addaudithook(deny)
try:
    r._execute_relocation_filesystem(Path(sys.argv[2]), sys.argv[3], provider="codex", session_id="fixture-session")
except PermissionError as error:
    assert str(error) == "synthetic audit refusal", str(error)
    raise SystemExit(73)
raise SystemExit("native rename bypassed the audit denial")
'''
        child = subprocess.run([sys.executable, "-B", "-c", script, str(ROOT / "scripts/kb"), str(home),
                                plan["plan_id"], str(self.root)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=25)
        self.assertEqual(child.returncode, 73, child.stdout + child.stderr)
        self.assertTrue(self.root.exists())
        self.assertFalse(self.target.exists())

    def test_physical_executor_rejects_store_drift_after_root_move_without_repair(self) -> None:
        home, path, plan, _ = self.execution_fixture()
        def stop(stage: str) -> None:
            if stage == "moved":
                raise RuntimeError("synthetic moved interruption")
        with mock.patch.object(relocation, "_relocation_filesystem_boundary", side_effect=stop):
            with self.assertRaisesRegex(RuntimeError, "synthetic moved"):
                self.physical_execution(home, plan)
        pointer = self.target / ".worktrees/task/.git"
        before = pointer.read_bytes()
        path.write_bytes(path.read_bytes() + b"\n")  # disposable store, not a production repair
        with self.assertRaisesRegex(IntentGuardianError, "store bytes changed"):
            self.physical_execution(home, plan)
        self.assertEqual(pointer.read_bytes(), before)
        self.assertEqual(len(relocation._read_write_fences(home)), 1)

    def test_physical_executor_rejects_late_destination_without_overwriting_it(self) -> None:
        home, _, plan, _ = self.execution_fixture()
        actual = relocation._move_root_exclusive
        def late_destination(snapshot: dict) -> None:
            self.target.mkdir()
            actual(snapshot)
        with mock.patch.object(relocation, "_move_root_exclusive", side_effect=late_destination):
            with self.assertRaisesRegex(IntentGuardianError, "exclusive rename refused"):
                self.physical_execution(home, plan)
        self.assertTrue(self.root.exists())
        self.assertTrue(self.target.exists())
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertEqual(len(relocation._read_write_fences(home)), 1)

    def test_physical_executor_rejects_unsupported_platform_before_native_writes(self) -> None:
        from native_decision_journal import load_projection_read_only
        home, path, plan, _ = self.execution_fixture()
        before = load_projection_read_only(path)
        with mock.patch("sys.platform", "unsupported-host"):
            with self.assertRaisesRegex(IntentGuardianError, "exclusive rename API"):
                self.physical_execution(home, plan)
        self.assertEqual(load_projection_read_only(path), before)
        self.assertEqual(relocation._read_write_fences(home), [])

    def test_physical_executor_keeps_full_lock_set_across_move_and_repair(self) -> None:
        home, _, plan, _ = self.execution_fixture()
        preflight = json.loads(Path(plan["plan_path"]).read_text())["preflight"]
        _, locks = relocation._fence_inventory(home, preflight)
        probed = []
        script = r'''
import fcntl, json, sys
for path in json.loads(sys.argv[1]):
    with open(path, "a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            continue
        raise SystemExit("missing held lock: " + path)
print("all held")
'''
        def probe(stage: str) -> None:
            if stage not in {"fenced", "moved", "physical_verified"}:
                return
            child = subprocess.run([sys.executable, "-B", "-c", script, json.dumps([str(p) for p in locks[:-1]])],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
            self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            probed.append(stage)
        with mock.patch.object(relocation, "_relocation_filesystem_boundary", side_effect=probe):
            self.physical_execution(home, plan)
        self.assertEqual(probed, ["fenced", "moved", "physical_verified"])

    def test_native_plan_prepare_is_immutable_owner_only_and_non_authorizing(self) -> None:
        home, path, plan, preview = self.native_review()
        file = Path(plan["plan_path"])
        before = file.read_bytes()
        again = relocation.prepare_relocation_plan(
            home, path, self.root, self.target, provider="codex", session_id="fixture-session",
        )
        self.assertEqual(plan, again)
        self.assertEqual(file.read_bytes(), before)
        self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
        self.assertFalse(plan["execution_authorized"])
        self.assertIn("仅记录", preview["description"])
        with self.assertRaisesRegex(IntentGuardianError, "no exact current typed native Allow"):
            self.execute_review(path, plan)
        self.assertFalse(relocation._plan_path(home, plan["plan_id"], decision=True).exists())

    def test_native_allow_records_one_decision_without_moving_or_rebinding(self) -> None:
        from approval_invariant import event_store_path, load_projection
        home, path, plan, preview = self.native_review()
        mapping = session_workspace_path(home, "codex", "fixture-session").read_bytes()
        self.assertEqual(self.observe_review(path, preview)["action"], "defer")
        result = self.execute_review(path, plan)
        self.assertEqual(result["status"], "decision_recorded")
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["authority_transferred"])
        before = event_store_path(path).read_bytes()
        self.assertEqual(self.execute_review(path, plan), result)
        self.assertEqual(event_store_path(path).read_bytes(), before)
        requests = list(load_projection(path)["requests"].values())
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["typed_receipt"]["outcome"], "allow")
        files = {str(file.relative_to(home)): file.read_bytes() for file in home.rglob("*") if file.is_file()}
        # Explicit verifier home must not silently consult a different ambient
        # store; evidence is always replayed from the supplied physical home.
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(self.base / "other-home")}):
            verified = relocation.verify_relocation_decision(home, path, plan["plan_id"], provider="codex", session_id="fixture-session")
        self.assertEqual(verified["status"], "verified")
        self.assertFalse(verified["execution_authorized"])
        self.assertEqual(files, {str(file.relative_to(home)): file.read_bytes() for file in home.rglob("*") if file.is_file()})
        self.assertEqual(session_workspace_path(home, "codex", "fixture-session").read_bytes(), mapping)
        self.assertTrue(self.root.is_dir())
        self.assertFalse(self.target.exists())
        self.assertEqual(load_contract(path)["runtime"]["approval_receipts"], [])

    def test_native_deny_and_unobserved_prompt_cannot_record_consent(self) -> None:
        from approval_invariant import decide_typed_approval, load_projection
        home, path, plan, preview = self.native_review()
        with self.assertRaises(IntentGuardianError):
            self.execute_review(path, plan)
        self.assertEqual(self.observe_review(path, preview)["action"], "defer")
        request = next(iter(load_projection(path)["requests"].values()))
        decide_typed_approval(path, request_id=request["request_id"], receipt_id=request["request_identity"],
                             outcome="deny", snapshot=request["snapshot"], current_snapshot=request["snapshot"],
                             provider="codex", session_id="fixture-session", decision_owner="human", actor="permission-request:codex")
        with self.assertRaisesRegex(IntentGuardianError, "no exact current typed native Allow"):
            self.execute_review(path, plan)
        self.assertFalse(relocation._plan_path(home, plan["plan_id"], decision=True).exists())
        self.assertFalse(self.target.exists())

    def test_native_fresh_review_after_deny_keeps_old_decision_immutable(self) -> None:
        from approval_invariant import decide_typed_approval, load_projection
        from intent_guardian import native_decision_preview
        home, path, plan, preview = self.native_review()
        self.assertEqual(self.observe_review(path, preview)["action"], "defer")
        old = next(iter(load_projection(path)["requests"].values()))
        decide_typed_approval(path, request_id=old["request_id"], receipt_id=old["request_identity"],
                             outcome="deny", snapshot=old["snapshot"], current_snapshot=old["snapshot"],
                             provider="codex", session_id="fixture-session", decision_owner="human", actor="permission-request:codex")
        denied = load_projection(path)["requests"][old["request_id"]]
        fresh = relocation.prepare_relocation_plan(home, path, self.root, self.target, provider="codex", session_id="fixture-session")
        self.assertNotEqual(fresh["plan_id"], plan["plan_id"])
        self.assertEqual(json.loads(Path(fresh["plan_path"]).read_text())["denial_predecessor"], plan["plan_id"])
        new_preview = native_decision_preview(path, kind="repository-relocation", decision="approve", target=fresh["plan_id"],
                                             provider="codex", session_id="fixture-session")
        self.assertEqual(self.observe_review(path, new_preview)["action"], "defer")
        self.assertEqual(self.execute_review(path, fresh)["status"], "decision_recorded")
        self.assertEqual(load_projection(path)["requests"][old["request_id"]], denied)
        self.assertEqual(len(load_projection(path)["requests"]), 2)

    def test_native_plan_tamper_and_unsafe_mode_are_rejected(self) -> None:
        home, path, plan, _ = self.native_review()
        file = Path(plan["plan_path"])
        before = file.read_text()
        value = json.loads(before)
        value["preflight"]["repository"]["destination"] = str(self.base / "another-target")
        file.write_text(json.dumps(value))
        with self.assertRaisesRegex(IntentGuardianError, "integrity"):
            relocation.relocation_review_context(home, path, plan["plan_id"], provider="codex", session_id="fixture-session")
        file.write_text(before)
        file.chmod(0o644)
        with self.assertRaisesRegex(IntentGuardianError, "owner-only"):
            relocation.relocation_review_context(home, path, plan["plan_id"], provider="codex", session_id="fixture-session")

    def test_native_review_rejects_wrong_session_or_substituted_description(self) -> None:
        _, path, _, preview = self.native_review()
        self.assertEqual(self.observe_review(path, preview, session_id="other-session")["action"], "deny")
        altered = dict(preview, description="different operation")
        self.assertEqual(self.observe_review(path, altered)["action"], "deny")

    def test_real_cli_prepares_and_previews_data_only_relocation_review(self) -> None:
        home, path, plan, _ = self.native_review()
        command = [sys.executable, "-B", str(ROOT / "scripts/kb/intent-guardian.py"),
                   "prepare-repository-relocation", str(self.root), str(self.target),
                   "--home", str(home), "--contract", str(path), "--provider", "codex", "--session-id", "fixture-session"]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), plan)
        preview = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/kb/intent-guardian.py"),
                                  "native-decision-preview", "repository-relocation", "--decision", "approve",
                                  "--target", plan["plan_id"], "--contract", str(path), "--provider", "codex",
                                  "--session-id", "fixture-session"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertTrue(json.loads(preview.stdout)["requires_native_escalation"])
        self.assertFalse(self.target.exists())

    def test_native_decision_recovers_missing_projection_without_redeciding(self) -> None:
        from approval_invariant import event_store_path, load_projection
        home, path, plan, preview = self.native_review()
        self.assertEqual(self.observe_review(path, preview)["action"], "defer")
        original = relocation.atomic_write

        def fail(path: Path, value: str) -> None:
            if path.name.endswith(".decision.json"):
                raise OSError("synthetic interruption after durable native decision")
            original(path, value)

        with mock.patch.object(relocation, "atomic_write", side_effect=fail):
            with self.assertRaisesRegex(OSError, "synthetic interruption"):
                self.execute_review(path, plan)
        self.assertEqual(next(iter(load_projection(path)["requests"].values()))["typed_receipt"]["outcome"], "allow")
        before = event_store_path(path).read_bytes()
        self.assertEqual(self.execute_review(path, plan)["status"], "decision_recorded")
        self.assertEqual(event_store_path(path).read_bytes(), before)
        self.assertFalse(self.target.exists())

    def test_native_world_drift_and_unrelated_question_remain_blocking(self) -> None:
        from approval_invariant import ask_approval, load_projection
        home, path, plan, preview = self.native_review()
        self.assertEqual(self.observe_review(path, preview)["action"], "defer")
        contract = load_contract(path)
        ask_approval(path, intent_id=contract["intent_id"], intent_revision=contract["revision"],
                     kind="intent-confirmation", target="unrelated", source="fixture", provider="codex",
                     session_id="fixture-session", workspace=self.root)
        with self.assertRaisesRegex(IntentGuardianError, "open approval question"):
            self.execute_review(path, plan)
        self.assertTrue(all(row.get("typed_receipt") is None for row in load_projection(path)["requests"].values()))

    def test_native_changed_content_does_not_create_a_durable_allow(self) -> None:
        from approval_invariant import load_projection
        _, path, plan, preview = self.native_review()
        self.assertEqual(self.observe_review(path, preview)["action"], "defer")
        (self.root / "tracked.txt").write_text("changed after prompt\n")
        with self.assertRaisesRegex(IntentGuardianError, "world changed"):
            self.execute_review(path, plan)
        self.assertIsNone(next(iter(load_projection(path)["requests"].values()))["typed_receipt"])

    def test_native_forged_or_stale_decision_file_is_not_an_authority(self) -> None:
        home, path, plan, preview = self.native_review()
        decision_path = relocation._plan_path(home, plan["plan_id"], decision=True)
        decision_path.write_text(json.dumps({"execution_authorized": True}))
        decision_path.chmod(0o600)
        with self.assertRaisesRegex(IntentGuardianError, "no exact current typed native Allow"):
            relocation.verify_relocation_decision(home, path, plan["plan_id"], provider="codex", session_id="fixture-session")
        self.assertEqual(self.observe_review(path, preview)["action"], "defer")
        with self.assertRaisesRegex(IntentGuardianError, "evidence conflict"):
            self.execute_review(path, plan)
        self.assertEqual(json.loads(decision_path.read_text()), {"execution_authorized": True})

    def test_guardian_preflight_is_read_only_and_requires_exact_current_lane(self) -> None:
        home, path = self.guardian_fixture()
        before = {str(file.relative_to(home)): file.read_bytes() for file in home.rglob("*") if file.is_file()}
        result = self.preflight(home)
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["authority_transferred"])
        self.assertEqual(len(result["bindings"]["contracts"]), 1)
        self.assertEqual(result["bindings"]["contracts"][0]["contract_path"], str(path))
        after = {str(file.relative_to(home)): file.read_bytes() for file in home.rglob("*") if file.is_file()}
        self.assertEqual(before, after)
        with self.assertRaisesRegex(IntentGuardianError, "exact current"):
            relocation.freeze_relocation_preflight(
                home, self.root, self.target, provider="codex", session_id="wrong-session",
            )

    def test_real_cli_preflight_has_no_write_or_approval_side_effect(self) -> None:
        home, _ = self.guardian_fixture()
        before = {str(file.relative_to(home)): file.read_bytes() for file in home.rglob("*") if file.is_file()}
        command = [
            sys.executable, "-B", str(ROOT / "scripts/kb/intent-guardian.py"),
            "repository-relocation-preflight", str(self.root), str(self.target),
            "--home", str(home), "--provider", "codex", "--session-id", "fixture-session",
        ]
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["authority_transferred"])
        after = {str(file.relative_to(home)): file.read_bytes() for file in home.rglob("*") if file.is_file()}
        self.assertEqual(before, after)
        self.target.mkdir()
        failed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(failed.returncode, 2)
        self.assertIn("destination already exists", failed.stderr)
        self.assertNotIn("Traceback", failed.stderr)

    def test_guardian_preflight_rejects_real_unsettled_effect_ledger(self) -> None:
        from intervention import begin_attempt
        home, path = self.guardian_fixture()
        contract = load_contract(path)
        begin_attempt(
            path, intent_id=contract["intent_id"], intent_revision=contract["revision"],
            fingerprint="c" * 64, source_event_id="unfinished-effect", capability="mcp:example:write",
            target="example:item:1", effect="external_write", provider="codex",
            session_id="fixture-session", idempotency_key="unfinished-effect",
        )
        with self.assertRaisesRegex(IntentGuardianError, "settled effect debt"):
            self.preflight(home)

    def test_exact_legacy_diagnostics_do_not_become_migration_authority(self) -> None:
        from tests.test_historical_native_retirement import seed_legacy
        import native_decision_journal as journal
        from approval_invariant import ask_approval
        home, path = self.guardian_fixture()
        seed_legacy(path, self.root)
        ledger = journal.journal_path(path)
        before = ledger.read_bytes()
        self.assertFalse(self.preflight(home)["execution_authorized"])
        self.assertEqual(ledger.read_bytes(), before)
        baseline = journal.load_projection_read_only(path)
        first = next(iter(baseline["transactions"]))
        for change in ({"sealed": True}, {"stage": "approval_decided"},
                       {"external_authority_verified": True}, {"historical_terminal_seen": True}):
            projection = copy.deepcopy(baseline)
            projection["transactions"][first].update(change)
            with self.subTest(change=change), \
                    mock.patch.object(journal, "load_projection_read_only", return_value=projection), \
                    self.assertRaisesRegex(IntentGuardianError, "unfinished native transaction"):
                self.preflight(home)
        contract = load_contract(path)
        ask_approval(path, intent_id=contract["intent_id"], intent_revision=contract["revision"],
            kind="intent-confirmation", target="still-live", source="fixture", provider="codex",
            session_id="fixture-session", workspace=self.root)
        with self.assertRaisesRegex(IntentGuardianError, "open approval question"):
            self.preflight(home)
        self.assertEqual(ledger.read_bytes(), before)

    def test_guardian_preflight_keeps_draft_history_but_rejects_open_approval(self) -> None:
        from approval_invariant import ask_approval
        home, path = self.guardian_fixture()
        contract = load_contract(path)
        contract["runtime"]["pending_proposal_digest"] = "b" * 64
        write_contract(path, contract)
        before = path.read_bytes()
        self.assertFalse(self.preflight(home)["execution_authorized"])
        self.assertEqual(path.read_bytes(), before)
        contract["runtime"]["pending_proposal_digest"] = ""
        write_contract(path, contract)
        ask_approval(
            path, intent_id=contract["intent_id"], intent_revision=contract["revision"],
            kind="intent-confirmation", target="fixture", source="fixture",
            provider="codex", session_id="fixture-session", workspace=self.root,
        )
        with self.assertRaisesRegex(IntentGuardianError, "open approval question"):
            self.preflight(home)

    def test_draft_and_skill_history_are_archived_not_renewed_as_authority(self) -> None:
        original_fixture = self.guardian_fixture
        def history_fixture():
            home, path = original_fixture()
            contract = load_contract(path)
            contract["constraints"]["allowed_paths"] = [str(self.root / "src/**")]
            contract["runtime"].update(pending_proposal_digest="b" * 64,
                active_skills=["historical-skill"],
                active_skill_frames=[{"name": "historical-skill", "provider": "codex", "session_id": "old-session"}])
            write_contract(path, contract)
            return home, path
        with mock.patch.object(self, "guardian_fixture", side_effect=history_fixture):
            home, path, plan, _ = self.execution_fixture()
        self.prepare_execution(home, path, plan)
        original = path.read_bytes()
        result = relocation.execute_repository_relocation(home, plan["plan_id"], provider="codex", session_id="fixture-session")
        self.assertEqual(result["status"], "committed")
        frozen = json.loads(Path(plan["plan_path"]).read_text())
        archive = relocation._relocation_archive_path(frozen, path)
        self.assertEqual(archive.read_bytes(), original)
        self.assertEqual(json.loads(original)["runtime"]["pending_proposal_digest"], "b" * 64)
        current = load_contract(Path(result["contract_path"]))
        self.assertEqual(current["status"], "paused")
        self.assertEqual(current["runtime"]["pending_proposal_digest"], "")
        self.assertEqual(current["runtime"]["active_skills"], [])
        self.assertEqual(current["runtime"]["active_skill_frames"], [])
        self.assertEqual(current["constraints"]["allowed_paths"], [str(self.target / "src/**")])
        self.assertFalse(current["permissions"]["local_write"])
        with self.assertRaisesRegex(IntentGuardianError, "historical evidence"):
            load_contract(archive)

    def test_old_frozen_plan_recovers_original_path_facts_under_new_runtime(self) -> None:
        original_fixture, original_freeze = self.guardian_fixture, relocation.freeze_relocation_preflight
        def legacy_fixture():
            home, path = original_fixture()
            contract = load_contract(path)
            contract["constraints"]["allowed_paths"] = [str(self.root / "src/**")]
            write_contract(path, contract)
            return home, path
        def legacy_freeze(*args, **kwargs):
            value = original_freeze(*args, **kwargs)
            value.pop("path_facts_schema")
            value.pop("consumers")
            value["preflight_sha256"] = relocation._digest({k: v for k, v in value.items() if k != "preflight_sha256"})
            return value
        with mock.patch.object(self, "guardian_fixture", side_effect=legacy_fixture), \
                mock.patch.object(relocation, "freeze_relocation_preflight", side_effect=legacy_freeze):
            home, path, plan, _ = self.execution_fixture()
            relocation._execute_relocation_filesystem(home, plan["plan_id"], provider="codex", session_id="fixture-session")
        # Root already moved using an old frozen plan. New code must neither
        # reinterpret that receipt nor invent the new path-fact policy.
        result = relocation.execute_repository_relocation(home, plan["plan_id"], provider="codex", session_id="fixture-session")
        self.assertEqual(result["status"], "committed")
        current = load_contract(Path(result["contract_path"]))
        self.assertEqual(current["constraints"]["allowed_paths"], [str(self.root / "src/**")])
        self.assertEqual(current["status"], "paused")
        self.assertFalse(current["permissions"]["local_write"])
        with self.assertRaisesRegex(IntentGuardianError, "unsupported relocation path-fact policy"):
            relocation._rebase_path_facts({"path_facts_schema": "unknown-future-policy"})

    def test_cheap_assessment_cannot_substitute_for_frozen_evidence(self) -> None:
        home, _ = self.guardian_fixture()
        before = {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}
        with mock.patch.object(relocation, "_content", side_effect=AssertionError("must not scan content")):
            assessment = relocation.assess_repository_relocation(home, self.root, self.target,
                provider="codex", session_id="fixture-session")
        self.assertEqual(assessment["status"], "ready_for_evidence")
        self.assertFalse(assessment["execution_authorized"])
        self.assertFalse(assessment["content_verified"])
        self.assertNotIn("preflight_sha256", assessment)
        self.assertEqual(before, {p: p.read_bytes() for p in home.rglob("*") if p.is_file()})
        with self.assertRaisesRegex(IntentGuardianError, "intact preflight"):
            relocation._fence_inventory(home, assessment)

    def test_unsettled_operation_fails_before_full_content_scan(self) -> None:
        from intervention import begin_attempt
        home, path = self.guardian_fixture()
        contract = load_contract(path)
        begin_attempt(path, intent_id=contract["intent_id"], intent_revision=contract["revision"],
            fingerprint="c" * 64, source_event_id="unfinished-effect", capability="mcp:example:write",
            target="example:item:1", effect="external_write", provider="codex", session_id="fixture-session",
            idempotency_key="unfinished-effect")
        with mock.patch.object(relocation, "_content", side_effect=AssertionError("expensive scan reached")):
            with self.assertRaisesRegex(IntentGuardianError, "settled effect debt"):
                self.preflight(home)

    def test_assessment_cli_is_read_only_and_does_not_require_release_state(self) -> None:
        home, _ = self.guardian_fixture()
        before = {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/kb/intent-guardian.py"),
            "repository-relocation-preflight", str(self.root), str(self.target), "--assessment-only",
            "--home", str(home), "--provider", "codex", "--session-id", "fixture-session"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["schema"], "sulde-repository-relocation-assessment-v1")
        self.assertEqual(before, {p: p.read_bytes() for p in home.rglob("*") if p.is_file()})

    def test_guardian_preflight_rejects_unfinished_native_transaction(self) -> None:
        home, _ = self.guardian_fixture()
        with mock.patch("native_decision_journal.load_projection_read_only", return_value={
            "transactions": {"fixture": {"stage": "approval_decided"}},
        }):
            with self.assertRaisesRegex(IntentGuardianError, "unfinished native transaction"):
                self.preflight(home)

    def test_unrelated_workspace_and_historical_orphan_are_not_migrated(self) -> None:
        home, _ = self.guardian_fixture()
        for workspace in (self.base / "unrelated", self.root / ".worktrees/removed-old-task"):
            # Create the historical workspace selector before removing it;
            # otherwise workspace_root legitimately finds the live parent Git
            # root and this fixture would overwrite the current contract.
            (workspace / ".git").mkdir(parents=True)
            path = active_contract_path(home, workspace)
            contract = default_contract(
                intent_id="other", objective="unrelated", acceptance_criteria=["preserve"],
                workspace=workspace, mode="enforce", confirmed_by="fixture",
            )
            contract["runtime"]["pending_proposal_digest"] = "a" * 64
            write_contract(path, contract)
            if workspace.is_relative_to(self.root):
                shutil.rmtree(workspace)
        result = self.preflight(home)
        self.assertEqual(len(result["bindings"]["contracts"]), 1)

    def test_host_audit_observation_does_not_change_preflight_material(self) -> None:
        home, path = self.guardian_fixture()
        before = self.preflight(home)
        contract = load_contract(path)
        contract["runtime"]["host_observations"].append({
            "event": "permission_request", "provider": "codex", "session_id": "fixture-session",
            "source": "live_host_hook", "status": "observed", "at": "2026-09-13T00:00:00+00:00",
        })
        write_contract(path, contract)
        self.assertEqual(self.preflight(home), before)

    def test_mapping_tampering_and_binding_drift_are_rejected(self) -> None:
        home, _ = self.guardian_fixture()
        mapping_path = session_workspace_path(home, "codex", "fixture-session")
        value = json.loads(mapping_path.read_text())
        value["session_id"] = "another-session"
        mapping_path.write_text(json.dumps(value))
        with self.assertRaisesRegex(IntentGuardianError, "digest differs"):
            self.preflight(home)

    def test_recovery_home_cannot_move_with_repository(self) -> None:
        with self.assertRaisesRegex(IntentGuardianError, "recovery home must remain outside"):
            self.preflight(self.root / "kb-home")

    def test_freeze_and_recheck_are_read_only_and_non_authorizing(self) -> None:
        git_before = (self.root / ".git/index").read_bytes()
        linked_before = (self.linked / ".git").read_bytes()
        snapshot = self.freeze()
        self.assertEqual(len(snapshot["worktrees"]), 2)
        self.assertFalse(snapshot["authority_transferred"])
        self.assertEqual(self.freeze(), snapshot)
        result = relocation.verify_repository_identity(snapshot)
        self.assertEqual(result["status"], "verified")
        self.assertFalse(result["git_mutation_performed"])
        self.assertEqual((self.root / ".git/index").read_bytes(), git_before)
        self.assertEqual((self.linked / ".git").read_bytes(), linked_before)
        self.assertFalse(self.target.exists())

    def test_whole_root_move_preserves_dirty_staged_untracked_ignored_and_0400(self) -> None:
        (self.root / "tracked.txt").write_text("staged\n")
        self.git(self.root, "add", "tracked.txt")
        (self.root / "tracked.txt").write_text("working\n")
        (self.linked / "draft.txt").write_text("uncommitted\n")
        ignored = self.root / "ignored" / "evidence.bin"
        ignored.parent.mkdir()
        ignored.write_bytes(b"\x00synthetic ignored evidence\xff")
        ignored.chmod(0o400)
        inode = ignored.stat().st_ino
        snapshot = self.freeze()
        self.move_and_repair()
        result = relocation.verify_repository_identity(snapshot, moved=True)
        self.assertEqual(result["status"], "verified")
        self.assertFalse(self.root.exists())
        moved = self.target / "ignored/evidence.bin"
        self.assertEqual(moved.read_bytes(), b"\x00synthetic ignored evidence\xff")
        self.assertEqual(moved.stat().st_ino, inode)
        self.assertEqual(stat.S_IMODE(moved.stat().st_mode), 0o400)
        self.assertEqual((self.target / "tracked.txt").read_text(), "working\n")
        self.assertEqual(self.git(self.target, "show", ":tracked.txt"), b"staged\n")
        self.assertEqual((self.target / ".worktrees/task/draft.txt").read_text(), "uncommitted\n")
        self.assertEqual(relocation.verify_repository_identity(snapshot, moved=True), result)

    def test_move_without_git_link_repair_is_not_verified(self) -> None:
        snapshot = self.freeze()
        self.root.rename(self.target)
        with self.assertRaises(IntentGuardianError):
            relocation.verify_repository_identity(snapshot, moved=True)

    def test_git_0400_materialized_as_0644_is_detected(self) -> None:
        path = self.root / "tracked.txt"
        path.chmod(0o400)
        snapshot = self.freeze()
        self.move_and_repair()
        (self.target / "tracked.txt").chmod(0o644)
        with self.assertRaisesRegex(IntentGuardianError, "permissions changed"):
            relocation.verify_repository_identity(snapshot, moved=True)

    def test_same_head_clone_cannot_impersonate_moved_physical_repository(self) -> None:
        snapshot = self.freeze()
        clone = self.base / "clone"
        self.git(self.base, "clone", "--no-hardlinks", str(self.root), str(clone))
        self.assertEqual(self.git(clone, "rev-parse", "HEAD"), self.git(self.root, "rev-parse", "HEAD"))
        self.root.rename(self.base / "parked")
        clone.rename(self.target)
        with self.assertRaisesRegex(IntentGuardianError, "physical repository identity differs"):
            relocation.verify_repository_identity(snapshot, moved=True)

    def test_same_inode_directory_with_replaced_git_directory_is_rejected(self) -> None:
        snapshot = self.freeze()
        self.move_and_repair()
        original = self.target / ".git"
        replacement = self.base / "replacement.git"
        shutil.copytree(original, replacement)
        original.rename(self.base / "parked.git")
        replacement.rename(original)
        with self.assertRaisesRegex(IntentGuardianError, "physical repository identity differs"):
            relocation.verify_repository_identity(snapshot, moved=True)

    def test_existing_destination_is_rejected(self) -> None:
        self.target.mkdir()
        with self.assertRaisesRegex(IntentGuardianError, "already exists"):
            self.freeze()

    def test_symlink_source_destination_and_parent_are_rejected(self) -> None:
        alias = self.base / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(IntentGuardianError, "non-symlink"):
            relocation.freeze_repository_identity(alias, self.target)
        self.target.symlink_to(self.base / "absent")
        with self.assertRaisesRegex(IntentGuardianError, "non-symlink"):
            self.freeze()
        parent = self.base / "alias-parent"
        parent.symlink_to(self.base, target_is_directory=True)
        with self.assertRaisesRegex(IntentGuardianError, "non-symlink"):
            relocation.freeze_repository_identity(self.root, parent / "another")

    def test_nested_destination_and_linked_source_are_rejected(self) -> None:
        with self.assertRaisesRegex(IntentGuardianError, "overlap"):
            relocation.freeze_repository_identity(self.root, self.root / "nested")
        with self.assertRaises(IntentGuardianError):
            relocation.freeze_repository_identity(self.linked, self.target)

    def test_external_linked_worktree_is_not_silently_omitted(self) -> None:
        self.git(self.root, "worktree", "add", "-b", "task/external", str(self.base / "outside"))
        with self.assertRaisesRegex(IntentGuardianError, "outside the source root"):
            self.freeze()

    def test_locked_or_detached_worktree_is_not_silently_omitted(self) -> None:
        self.git(self.root, "worktree", "lock", str(self.linked))
        with self.assertRaisesRegex(IntentGuardianError, "unlocked attached"):
            self.freeze()
        self.git(self.root, "worktree", "unlock", str(self.linked))
        self.git(self.linked, "checkout", "--detach")
        with self.assertRaisesRegex(IntentGuardianError, "unlocked attached"):
            self.freeze()

    def test_cross_device_destination_is_rejected_before_content_read(self) -> None:
        original = relocation._identity

        def identity(path: Path) -> dict:
            value = original(path)
            if path == self.target.parent:
                value["device"] += 1
            return value

        with mock.patch.object(relocation, "_identity", side_effect=identity):
            with self.assertRaisesRegex(IntentGuardianError, "same filesystem"):
                self.freeze()

    def test_same_size_content_change_with_restored_mtime_is_detected(self) -> None:
        snapshot = self.freeze()
        path = self.root / "tracked.txt"
        before = path.stat()
        path.write_text("edit\n")
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaisesRegex(IntentGuardianError, "candidate drifted"):
            relocation.verify_repository_identity(snapshot)

    def test_ignored_content_is_included_without_echoing_its_value(self) -> None:
        ignored = self.root / "ignored"
        ignored.mkdir()
        path = ignored / "private-fixture"
        path.write_text("synthetic-value-never-output")
        snapshot = self.freeze()
        self.assertNotIn("synthetic-value", str(snapshot))
        path.write_text("changed")
        with self.assertRaisesRegex(IntentGuardianError, "candidate drifted"):
            relocation.verify_repository_identity(snapshot)

    def test_git_environment_cannot_redirect_observation(self) -> None:
        expected = self.freeze()
        with mock.patch.dict(os.environ, {
            "GIT_DIR": str(self.base / "not-a-repository"),
            "GIT_INDEX_FILE": str(self.base / "wrong-index"),
            "GIT_WORK_TREE": str(self.base),
        }):
            self.assertEqual(self.freeze(), expected)

    def test_git_config_drift_and_alternate_objects_are_rejected(self) -> None:
        snapshot = self.freeze()
        self.git(self.root, "config", "remote.fixture.url", "https://example.invalid/another")
        with self.assertRaisesRegex(IntentGuardianError, "candidate drifted"):
            relocation.verify_repository_identity(snapshot)
        alternate = self.root / ".git/objects/info/alternates"
        alternate.write_text(str(self.base / "outside-objects") + "\n")
        with self.assertRaisesRegex(IntentGuardianError, "alternate object"):
            self.freeze()

    def test_path_bound_worktree_config_and_submodule_are_explicitly_unsupported(self) -> None:
        self.git(self.root, "config", "extensions.worktreeConfig", "true")
        with self.assertRaisesRegex(IntentGuardianError, "path-bound worktree configuration"):
            self.freeze()
        self.git(self.root, "config", "--unset", "extensions.worktreeConfig")
        head = self.git(self.root, "rev-parse", "HEAD").decode().strip()
        self.git(self.root, "update-index", "--add", "--cacheinfo", "160000", head, "nested-module")
        with self.assertRaisesRegex(IntentGuardianError, "submodule administration"):
            self.freeze()

    def test_content_symlink_is_preserved_without_reading_external_target(self) -> None:
        outside = self.base / "outside.txt"
        outside.write_text("outside")
        (self.root / "link").symlink_to(outside)
        snapshot = self.freeze()
        outside.write_text("changed outside")
        self.assertEqual(self.freeze(), snapshot)
        self.move_and_repair()
        self.assertEqual(relocation.verify_repository_identity(snapshot, moved=True)["status"], "verified")
        self.assertEqual(os.readlink(self.target / "link"), str(outside))

    def test_snapshot_tampering_does_not_validate(self) -> None:
        snapshot = self.freeze()
        for field, value in (("authority_transferred", True), ("destination", str(self.base / "elsewhere"))):
            with self.subTest(field=field):
                changed = copy.deepcopy(snapshot)
                changed[field] = value
                with self.assertRaisesRegex(IntentGuardianError, "integrity"):
                    relocation.verify_repository_identity(changed)

    def test_special_file_and_evidence_bounds_fail_closed(self) -> None:
        os.mkfifo(self.root / "fifo")
        with self.assertRaisesRegex(IntentGuardianError, "special file"):
            self.freeze()
        (self.root / "fifo").unlink()
        with mock.patch.object(relocation, "MAX_ENTRIES", 1):
            with self.assertRaisesRegex(IntentGuardianError, "entry bound"):
                self.freeze()
        with mock.patch.object(relocation, "MAX_CONTENT_BYTES", 1):
            with self.assertRaisesRegex(IntentGuardianError, "byte bound"):
                self.freeze()

    def test_branch_and_destination_drift_during_snapshot_fail_closed(self) -> None:
        original = relocation._content

        def content(root: Path, worktrees: list) -> dict:
            result = original(root, worktrees)
            self.git(root, "branch", "extra-ref")
            return result

        with mock.patch.object(relocation, "_content", side_effect=content):
            with self.assertRaisesRegex(IntentGuardianError, "Git state changed"):
                self.freeze()

        def destination(root: Path, worktrees: list) -> dict:
            result = original(root, worktrees)
            self.target.mkdir()
            return result

        with mock.patch.object(relocation, "_content", side_effect=destination):
            with self.assertRaisesRegex(IntentGuardianError, "destination changed"):
                self.freeze()


if __name__ == "__main__":
    unittest.main()
