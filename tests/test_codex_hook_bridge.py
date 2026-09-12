from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
KB_SCRIPTS = ROOT / "scripts" / "kb"
CLI_PATH = KB_SCRIPTS / "intent-guardian.py"
PRE_TOOL_ADAPTER = (
    ROOT / "integrations" / "codex" / "plugins" / "sulde" / "scripts" / "pre-tool-use.py"
)
POST_TOOL_ADAPTER = PRE_TOOL_ADAPTER.with_name("post-tool-use.py")


def load_cli_module():
    sys.path.insert(0, str(KB_SCRIPTS))
    spec = importlib.util.spec_from_file_location("test_intent_guardian_cli", CLI_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_pre_tool_adapter():
    scripts = PRE_TOOL_ADAPTER.parent
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location(
        "test_codex_pre_tool_adapter",
        PRE_TOOL_ADAPTER,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_post_tool_adapter():
    scripts = POST_TOOL_ADAPTER.parent
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location(
        "test_codex_post_tool_adapter",
        POST_TOOL_ADAPTER,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CodexHookBridgeTests(unittest.TestCase):
    def test_current_bridge_records_without_observer_child_process(self) -> None:
        adapter = self.root / "observed/scripts/post-tool-use.py"
        adapter.parent.mkdir(parents=True)
        adapter.write_text("print('normal')\n")
        shutil.copy2(ROOT / "integrations/codex/plugins/sulde/scripts/_hook_observer.py", adapter.parent / "_hook_observer.py")
        env = {**os.environ, "SULDE_KB_HOME": str(self.home), "SULDE_BRIDGE_OWNS_OBSERVATION": "1"}
        payload = json.dumps({"hook_event_name": "PostToolUse", "tool_use_id": "bridge-call", "tool_response": "", "session_id": "fixture"}).encode()
        with mock.patch.object(subprocess, "Popen", side_effect=AssertionError("no observer process")):
            completed = self.module._run_codex_adapter_in_process(adapter, environment=env, input_bytes=payload)
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, b"normal\n")
        import sqlite3
        with sqlite3.connect(self.home / "hook-observer/observations.sqlite3") as db:
            row = json.loads(db.execute("SELECT row FROM observations").fetchone()[0])
        self.assertEqual(row["tool_result"], "success")
        self.assertEqual(row["exit_code"], 0)
        self.assertEqual(row["audit_delivery"], "recorded")

    def setUp(self) -> None:
        self.module = load_cli_module()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "kb-home"
        self.adapter = self.root / "adapter.py"
        self.adapter.write_text("# fixture adapter\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _dispatch(self, event: str, payload: bytes, *, completed=None):
        captured: dict[str, object] = {}
        stdout = io.StringIO()
        stderr = io.StringIO()

        def run(adapter, **kwargs):
            captured["adapter"] = adapter
            captured.update(kwargs)
            if completed is not None:
                return completed
            if kwargs.get("input_bytes") == b"not-json":
                return SimpleNamespace(returncode=1, stdout=b"", stderr=b"invalid fixture\n")
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        stdin = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")
        import launcher_contract

        with (
            mock.patch.object(self.module.sys, "stdin", stdin),
            mock.patch.object(self.module.sys, "stdout", stdout),
            mock.patch.object(self.module.sys, "stderr", stderr),
            mock.patch.object(
                launcher_contract,
                "resolve_codex_hook_adapter",
                return_value=self.adapter,
            ),
            mock.patch.object(
                self.module,
                "_run_codex_adapter_in_process",
                side_effect=run,
            ),
        ):
            result = self.module._dispatch_codex_hook(event, self.home)
        captured["bridge_stdout"] = stdout.getvalue()
        captured["bridge_stderr"] = stderr.getvalue()
        return result, captured

    def test_trusted_bridge_injects_exact_short_lived_provenance(self) -> None:
        payload = {
            "session_id": "thread-bridge",
            "cwd": str(ROOT),
            "prompt": "fixture",
        }
        result, captured = self._dispatch(
            "user-prompt-submit",
            json.dumps(payload).encode("utf-8"),
        )
        forwarded = json.loads(bytes(captured["input_bytes"]).decode("utf-8"))

        self.assertEqual(result, 0)
        self.assertEqual(forwarded["client"], "codex")
        self.assertEqual(forwarded["sulde_observation_source"], "live_host_hook")
        proof = forwarded["sulde_host_provenance"]
        self.assertEqual(proof["hook_event"], "UserPromptSubmit")
        self.assertEqual(proof["session_id"], "thread-bridge")
        self.assertTrue(proof["loaded_module_generation"])
        self.assertTrue(proof["artifact_generation"])
        if os.name != "nt":
            mode = (self.home / "runtime" / "host-provenance.key").stat().st_mode
            self.assertEqual(stat.S_IMODE(mode), 0o600)

        from host_capabilities import verify_host_provenance

        verified = verify_host_provenance(
            proof,
            provider="codex",
            hook_event="UserPromptSubmit",
            session_id="thread-bridge",
            workspace=ROOT,
            source="live_host_hook",
            home=self.home,
            loaded_module_generation=proof["loaded_module_generation"],
            artifact_generation=proof["artifact_generation"],
        )
        self.assertEqual(verified["signature"], proof["signature"])

    def test_bridge_binds_observation_to_persisted_session_workspace(self) -> None:
        launch_workspace = self.root / "launch-workspace"
        lane_workspace = self.root / "task-worktree"
        launch_workspace.mkdir()
        lane_workspace.mkdir()
        payload = {
            "sessionId": "thread-handoff",
            "cwd": str(launch_workspace),
            "toolUseId": "handoff-call",
            "toolName": "Read",
        }

        with mock.patch(
            "intent_guardian_parts.session_workspace.load_session_workspace",
            return_value={
                "contract_path": str(lane_workspace / "intent.json"),
                "workspace_root": str(lane_workspace),
            },
        ):
            result, captured = self._dispatch(
                "pre-tool-use",
                json.dumps(payload).encode("utf-8"),
            )

        self.assertEqual(result, 0)
        forwarded = json.loads(captured["input_bytes"])
        self.assertEqual(forwarded["cwd"], str(launch_workspace))
        self.assertEqual(forwarded["sulde_workspace_root"], str(lane_workspace))
        proof = forwarded["sulde_host_provenance"]
        from host_capabilities import workspace_identifier

        self.assertEqual(
            proof["workspace_id"],
            workspace_identifier(lane_workspace),
        )

    def test_invalid_payload_is_forwarded_without_live_claim(self) -> None:
        result, captured = self._dispatch("pre-tool-use", b"not-json")

        self.assertEqual(result, 0)
        self.assertEqual(captured["input_bytes"], b"not-json")
        self.assertEqual(
            json.loads(str(captured["bridge_stdout"]))["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        environment = captured["environment"]
        self.assertEqual(environment["SULDE_HOOK_OBSERVATION_SOURCE"], "unclassified")
        self.assertFalse((self.home / "runtime" / "host-provenance.key").exists())

    def test_post_adapter_nonzero_is_receipted_with_dual_generation_and_returns_zero(self) -> None:
        result, captured = self._dispatch(
            "post-tool-use",
            json.dumps(
                {
                    "sessionId": "post-bridge-session",
                    "cwd": str(ROOT),
                    "toolUseId": "post-bridge-call",
                    "toolName": "Read",
                }
            ).encode("utf-8"),
            completed=SimpleNamespace(
                returncode=17,
                stdout=b"untrusted context",
                stderr=b"adapter failed\n",
            ),
        )

        self.assertEqual(result, 0)
        self.assertEqual(captured["bridge_stdout"], "")
        self.assertIn("degraded_to_native_codex", captured["bridge_stderr"])
        receipts = list((self.home / "runtime" / "hook-failures").glob("*.json"))
        self.assertEqual(len(receipts), 1)
        receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
        self.assertEqual(receipt["hook_event"], "PostToolUse")
        self.assertEqual(receipt["exit_code"], 17)
        self.assertTrue(receipt["loaded_module_generation"])
        self.assertTrue(receipt["artifact_generation"])
        self.assertNotIn("untrusted context", json.dumps(receipt))

    def test_tool_provenance_binds_a_redacted_host_call_id(self) -> None:
        payload = {
            "sessionId": "thread-tool",
            "cwd": str(ROOT),
            "toolUseId": "native-call-secret-shape",
            "toolName": "Read",
        }
        result, captured = self._dispatch(
            "pre-tool-use",
            json.dumps(payload).encode("utf-8"),
        )
        forwarded = json.loads(bytes(captured["input_bytes"]).decode("utf-8"))
        proof = forwarded["sulde_host_provenance"]

        self.assertEqual(result, 0)
        self.assertRegex(proof["call_id_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn("native-call-secret-shape", json.dumps(proof))

        from host_capabilities import HostProvenanceError, verify_host_provenance

        verified = verify_host_provenance(
            proof,
            provider="codex",
            hook_event="PreToolUse",
            session_id="thread-tool",
            workspace=ROOT,
            call_id="native-call-secret-shape",
            source="live_host_hook",
            home=self.home,
        )
        self.assertEqual(verified["call_id_sha256"], proof["call_id_sha256"])
        with self.assertRaisesRegex(HostProvenanceError, "call_id"):
            verify_host_provenance(
                proof,
                provider="codex",
                hook_event="PreToolUse",
                session_id="thread-tool",
                workspace=ROOT,
                call_id="different-call",
                source="live_host_hook",
                home=self.home,
            )

    def test_event_probe_is_read_only_and_does_not_consume_stdin(self) -> None:
        class RefuseRead(io.BytesIO):
            def read(self, *args, **kwargs):
                raise AssertionError("probe consumed Hook stdin")

        stdin = io.TextIOWrapper(RefuseRead(b'{"fixture":true}'), encoding="utf-8")
        stdout = io.StringIO()
        with (
            mock.patch.object(self.module.sys, "stdin", stdin),
            mock.patch.object(self.module.sys, "stdout", stdout),
            mock.patch.object(
                self.module,
                "_resolve_codex_hook",
                return_value=(self.root, self.adapter),
            ),
        ):
            result = self.module._probe_codex_hook("stop", self.home)

        self.assertEqual(result, 0)
        self.assertTrue(json.loads(stdout.getvalue())["healthy"])
        self.assertFalse((self.home / "runtime" / "host-provenance.key").exists())

    def test_bridge_replaces_failed_adapter_output_with_fail_closed_deny(self) -> None:
        stdin = io.TextIOWrapper(
            io.BytesIO(b'{"sessionId":"thread","toolName":"Bash"}'),
            encoding="utf-8",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        deny = b'{"hookSpecificOutput":{"permissionDecision":"deny"}}\n'
        with (
            mock.patch.object(self.module.sys, "stdin", stdin),
            mock.patch.object(self.module.sys, "stdout", stdout),
            mock.patch.object(self.module.sys, "stderr", stderr),
            mock.patch.object(
                self.module,
                "_resolve_codex_hook",
                return_value=(self.root, self.adapter),
            ),
            mock.patch.object(
                self.module,
                "_run_codex_adapter_in_process",
                return_value=SimpleNamespace(
                    returncode=1,
                    stdout=deny,
                    stderr=b"adapter import failed\n",
                ),
            ),
        ):
            result = self.module._dispatch_codex_hook("pre-tool-use", self.home)

        self.assertEqual(result, 0)
        self.assertEqual(
            json.loads(stdout.getvalue())["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        self.assertIn("failed_closed", stderr.getvalue())

    def test_bridge_normalizes_structured_exit_two_policy_deny(self) -> None:
        stdin = io.TextIOWrapper(
            io.BytesIO(b'{"sessionId":"thread","toolName":"Bash"}'),
            encoding="utf-8",
        )
        stdout = io.StringIO()
        deny = (
            b'{"hookSpecificOutput":{"hookEventName":"PreToolUse",'
            b'"permissionDecision":"deny",'
            b'"permissionDecisionReason":"fixture policy"}}\n'
        )
        with (
            mock.patch.object(self.module.sys, "stdin", stdin),
            mock.patch.object(self.module.sys, "stdout", stdout),
            mock.patch.object(
                self.module,
                "_resolve_codex_hook",
                return_value=(self.root, self.adapter),
            ),
            mock.patch.object(
                self.module,
                "_run_codex_adapter_in_process",
                return_value=SimpleNamespace(returncode=2, stdout=deny, stderr=b""),
            ),
        ):
            result = self.module._dispatch_codex_hook("pre-tool-use", self.home)

        self.assertEqual(result, 0)
        self.assertEqual(
            json.loads(stdout.getvalue())["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )

    def test_bridge_fails_closed_for_material_incidental_exit_two(self) -> None:
        for label, event, output in (
            ("empty", "pre-tool-use", b""),
            ("launcher", "pre-tool-use", b"launcher contract failed\n"),
            (
                "allow",
                "pre-tool-use",
                b'{"hookSpecificOutput":{"hookEventName":"PreToolUse",'
                b'"permissionDecision":"allow",'
                b'"permissionDecisionReason":"not a deny"}}\n',
            ),
            (
                "wrong-event",
                "stop",
                b'{"hookSpecificOutput":{"hookEventName":"PreToolUse",'
                b'"permissionDecision":"deny",'
                b'"permissionDecisionReason":"wrong lifecycle"}}\n',
            ),
        ):
            with self.subTest(label=label):
                stdin = io.TextIOWrapper(io.BytesIO(b"{}"), encoding="utf-8")
                stdout = io.StringIO()
                stderr = io.StringIO()
                with (
                    mock.patch.object(self.module.sys, "stdin", stdin),
                    mock.patch.object(self.module.sys, "stdout", stdout),
                    mock.patch.object(self.module.sys, "stderr", stderr),
                    mock.patch.object(
                        self.module,
                        "_resolve_codex_hook",
                        return_value=(self.root, self.adapter),
                    ),
                    mock.patch.object(
                        self.module,
                        "_run_codex_adapter_in_process",
                        return_value=SimpleNamespace(
                            returncode=2,
                            stdout=output,
                            stderr=b"infrastructure exit two\n",
                        ),
                    ),
                ):
                    result = self.module._dispatch_codex_hook(event, self.home)
                self.assertEqual(result, 0)
                if event == "pre-tool-use":
                    self.assertEqual(
                        json.loads(stdout.getvalue())["hookSpecificOutput"]["permissionDecision"],
                        "deny",
                    )
                    self.assertIn("failed_closed", stderr.getvalue())
                else:
                    self.assertEqual(stdout.getvalue(), "")
                    self.assertIn("degraded_to_native_codex", stderr.getvalue())

    def test_bridge_discards_invalid_policy_bytes_for_read_and_plain_git(self) -> None:
        for payload in (
            {"toolName": "Read", "toolInput": {"file_path": "fixture"}},
            {"toolName": "Bash", "toolInput": {"command": "git status --short"}},
        ):
            with self.subTest(payload=payload):
                stdin = io.TextIOWrapper(
                    io.BytesIO(json.dumps(payload).encode("utf-8")),
                    encoding="utf-8",
                )
                stdout = io.StringIO()
                stderr = io.StringIO()
                with (
                    mock.patch.object(self.module.sys, "stdin", stdin),
                    mock.patch.object(self.module.sys, "stdout", stdout),
                    mock.patch.object(self.module.sys, "stderr", stderr),
                    mock.patch.object(
                        self.module,
                        "_resolve_codex_hook",
                        return_value=(self.root, self.adapter),
                    ),
                    mock.patch.object(
                        self.module,
                        "_run_codex_adapter_in_process",
                        return_value=SimpleNamespace(
                            returncode=0,
                            stdout=b"not-a-policy-response\n",
                            stderr=b"adapter warning\n",
                        ),
                    ),
                ):
                    result = self.module._dispatch_codex_hook(
                        "pre-tool-use", self.home
                    )
                self.assertEqual(result, 0)
                self.assertEqual(stdout.getvalue(), "")

    def test_bridge_executes_sealed_adapter_without_python_subprocess(self) -> None:
        stdin = io.TextIOWrapper(io.BytesIO(b"{}"), encoding="utf-8")
        with (
            mock.patch.object(self.module.sys, "stdin", stdin),
            mock.patch.object(
                self.module,
                "_resolve_codex_hook",
                return_value=(self.root, self.adapter),
            ),
            mock.patch.object(
                self.module.subprocess,
                "run",
                side_effect=AssertionError("Python subprocess entered Hook hot path"),
            ),
        ):
            result = self.module._dispatch_codex_hook("stop", self.home)
        self.assertEqual(result, 0)

    @unittest.skipIf(os.name == "nt", "requires a POSIX shell")
    def test_broken_stable_bridge_fails_closed_only_for_pre_tool_use(self) -> None:
        bash = shutil.which("bash")
        self.assertIsNotNone(bash)
        plugin = self.root / "plugin"
        scripts = plugin / "scripts"
        scripts.mkdir(parents=True)
        source = ROOT / "integrations" / "codex" / "plugins" / "sulde" / "scripts"
        for name in ("run-hook.sh", "record-hook-failure.py", "_adapter_common.py"):
            shutil.copy2(source / name, scripts / name)
        runtime_kb = plugin / "runtime" / "scripts" / "kb"
        runtime_kb.mkdir(parents=True)
        shutil.copy2(KB_SCRIPTS / "host_capabilities.py", runtime_kb)
        kb_home = self.root / "broken-kb"
        bridge = kb_home / "bin" / "intent-guardian"
        bridge.parent.mkdir(parents=True)
        bridge.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
        bridge.chmod(0o755)
        environment = os.environ.copy()
        environment.pop("SULDE_HOME", None)
        environment["SULDE_KB_HOME"] = str(kb_home)
        environment.pop("PYTHONDONTWRITEBYTECODE", None)

        for event in ("pre-tool-use", "permission-request", "stop"):
            completed = subprocess.run(
                [str(bash), str(scripts / "run-hook.sh"), event],
                input='{"toolName":"Bash"}',
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=5,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            if event == "pre-tool-use":
                self.assertEqual(
                    json.loads(completed.stdout)["hookSpecificOutput"]["permissionDecision"],
                    "deny",
                )
                self.assertIn("failed_closed", completed.stderr)
            else:
                self.assertEqual(completed.stdout, "")
                self.assertEqual(completed.stderr.count("degraded_to_native_codex"), 1)
        receipts = sorted((kb_home / "runtime" / "hook-failures").glob("*.json"))
        self.assertEqual(len(receipts), 2)
        for receipt in receipts:
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(payload["outcome"], "inconclusive")
            self.assertEqual(payload["effect_claim"], "none")

    def test_posix_bridge_policy_validation_adds_no_python_hot_path(self) -> None:
        source = (
            ROOT
            / "integrations"
            / "codex"
            / "plugins"
            / "sulde"
            / "scripts"
            / "run-hook.sh"
        ).read_text(encoding="utf-8")
        self.assertNotIn('"$PYTHON" -c', source)

    @unittest.skipIf(os.name == "nt", "requires a POSIX shell")
    def test_bridge_dispatch_race_failure_fails_closed_and_policy_deny_survives(self) -> None:
        bash = shutil.which("bash")
        self.assertIsNotNone(bash)
        plugin = self.root / "plugin-dispatch"
        scripts = plugin / "scripts"
        scripts.mkdir(parents=True)
        source = ROOT / "integrations" / "codex" / "plugins" / "sulde" / "scripts"
        shutil.copy2(source / "run-hook.sh", scripts / "run-hook.sh")
        kb_home = self.root / "dispatch-kb"
        bridge = kb_home / "bin" / "intent-guardian"
        bridge.parent.mkdir(parents=True)
        bridge.write_text(
            (
                "#!/bin/sh\n"
                "if [ \"${BRIDGE_EMPTY_SUCCESS:-0}\" = 1 ]; then exit 0; fi\n"
                "if [ \"${BRIDGE_POLICY_DENY:-0}\" = 1 ]; then\n"
                "  echo '{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"fixture policy\"}}'\n"
                "  exit 2\n"
                "fi\n"
                "if [ \"${BRIDGE_INVALID_TWO:-0}\" = 1 ]; then exit 2; fi\n"
                "exit 9\n"
            ),
            encoding="utf-8",
        )
        bridge.chmod(0o755)
        environment = os.environ.copy()
        environment.pop("SULDE_HOME", None)
        environment["SULDE_KB_HOME"] = str(kb_home)

        failed = subprocess.run(
            [str(bash), str(scripts / "run-hook.sh"), "pre-tool-use"],
            input="{}",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=5,
            check=False,
        )
        self.assertEqual(failed.returncode, 0, failed.stderr)
        self.assertEqual(
            json.loads(failed.stdout)["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        self.assertIn("failed_closed", failed.stderr)

        environment["BRIDGE_EMPTY_SUCCESS"] = "1"
        empty_success = subprocess.run(
            [str(bash), str(scripts / "run-hook.sh"), "pre-tool-use"],
            input="{}",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=5,
            check=False,
        )
        self.assertEqual(empty_success.returncode, 0, empty_success.stderr)
        self.assertEqual(empty_success.stdout, "")
        self.assertNotIn("failed_closed", empty_success.stderr)

        environment.pop("BRIDGE_EMPTY_SUCCESS")
        environment["BRIDGE_POLICY_DENY"] = "1"
        denied = subprocess.run(
            [str(bash), str(scripts / "run-hook.sh"), "pre-tool-use"],
            input="{}",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=5,
            check=False,
        )
        self.assertEqual(denied.returncode, 0)
        self.assertEqual(
            json.loads(denied.stdout)["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )

        environment.pop("BRIDGE_POLICY_DENY")
        environment["BRIDGE_INVALID_TWO"] = "1"
        incidental = subprocess.run(
            [str(bash), str(scripts / "run-hook.sh"), "pre-tool-use"],
            input="{}",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=5,
            check=False,
        )
        self.assertEqual(incidental.returncode, 0, incidental.stderr)
        self.assertEqual(
            json.loads(incidental.stdout)["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        self.assertIn("failed_closed", incidental.stderr)

    @unittest.skipIf(os.name == "nt", "requires a POSIX shell")
    def test_staged_local_hook_runs_twice_without_bytecode_environment(self) -> None:
        bash = shutil.which("bash")
        self.assertIsNotNone(bash)
        plugin = self.root / "staged" / "plugins" / "sulde"
        scripts = plugin / "scripts"
        runtime_hooks = plugin / "runtime" / "hooks"
        scripts.mkdir(parents=True)
        runtime_hooks.mkdir(parents=True)
        source_scripts = ROOT / "integrations" / "codex" / "plugins" / "sulde" / "scripts"
        for name in (
            "run-hook.sh",
            "pre-tool-use.py",
            "_adapter_common.py",
            "_recovery_defer.py",
        ):
            shutil.copy2(source_scripts / name, scripts / name)
        (runtime_hooks / "runtime_helper.py").write_text(
            "VALUE = 'two-hooks-green'\n",
            encoding="utf-8",
        )
        (runtime_hooks / "pre_tool_use.py").write_text(
            (
                "import json,os,sys\n"
                "import runtime_helper\n"
                "json.load(sys.stdin)\n"
                "print(runtime_helper.VALUE + ':' + "
                "str(os.environ.get('PYTHONDONTWRITEBYTECODE')), file=sys.stderr)\n"
            ),
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["SULDE_KB_HOME"] = str(self.root / "missing-kb-home")
        environment.pop("PYTHONDONTWRITEBYTECODE", None)

        for index in range(2):
            completed = subprocess.run(
                [str(bash), str(scripts / "run-hook.sh"), "pre-tool-use"],
                input=json.dumps(
                    {
                        "sessionId": "thread-staged",
                        "toolName": "Read",
                        "toolInput": {"file_path": f"fixture-{index}"},
                    }
                ),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=10,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout, "")
            self.assertIn("two-hooks-green:1", completed.stderr)

        runtime = plugin / "runtime"
        self.assertEqual(list(runtime.rglob("*.pyc")), [])
        self.assertEqual(list(runtime.rglob("__pycache__")), [])


class CodexPostToolAdapterResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_post_tool_adapter()
        self.payload = json.dumps(
            {
                "sessionId": "post-session",
                "cwd": str(ROOT),
                "toolUseId": "post-call",
                "toolName": "Read",
                "toolInput": {"file_path": "fixture"},
            }
        )

    def _invoke(self, completed=None, *, error: Exception | None = None):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch.object(self.module.sys, "stdin", io.StringIO(self.payload)),
            mock.patch.object(self.module.sys, "stdout", stdout),
            mock.patch.object(self.module.sys, "stderr", stderr),
            mock.patch.object(
                self.module,
                "run_runtime",
                return_value=completed,
                side_effect=error,
            ),
            mock.patch.object(self.module, "_record_failure") as record_failure,
        ):
            result = self.module.main()
        return result, stdout.getvalue(), stderr.getvalue(), record_failure

    def test_runtime_nonzero_is_recorded_but_never_forwarded_or_returned(self) -> None:
        result, stdout, stderr, record_failure = self._invoke(
            SimpleNamespace(
                returncode=9,
                stdout="untrusted runtime context",
                stderr="runtime traceback\n",
            )
        )

        self.assertEqual(result, 0)
        self.assertEqual(stdout, "")
        self.assertNotIn("untrusted runtime context", stderr)
        self.assertIn("effect outcome remains inconclusive", stderr)
        record_failure.assert_called_once()
        self.assertEqual(record_failure.call_args.kwargs["exit_code"], 9)

    def test_runtime_timeout_is_recorded_and_host_continues(self) -> None:
        result, stdout, stderr, record_failure = self._invoke(
            error=subprocess.TimeoutExpired(["python", "post"], 115)
        )

        self.assertEqual(result, 0)
        self.assertEqual(stdout, "")
        self.assertIn("adapter unavailable", stderr)
        record_failure.assert_called_once()
        self.assertEqual(
            record_failure.call_args.kwargs["error_kind"], "TimeoutExpired"
        )


class CodexPreToolAdapterDegradeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_pre_tool_adapter()
        self.payload = json.dumps(
            {"toolName": "Bash", "toolInput": {"command": "printf fixture"}}
        )

    def _invoke(self, completed=None, *, error: Exception | None = None):
        stdout = io.StringIO()
        stderr = io.StringIO()
        side_effect = error if error is not None else None
        with (
            mock.patch.object(self.module.sys, "stdin", io.StringIO(self.payload)),
            mock.patch.object(self.module.sys, "stdout", stdout),
            mock.patch.object(self.module.sys, "stderr", stderr),
            mock.patch.object(
                self.module,
                "run_runtime",
                return_value=completed,
                side_effect=side_effect,
            ),
        ):
            result = self.module.main()
        return result, stdout.getvalue(), stderr.getvalue()

    def test_runtime_failure_discards_untrusted_output_and_fails_closed(self) -> None:
        deny = json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "fixture policy",
                }
            }
        )
        result, stdout, stderr = self._invoke(
            SimpleNamespace(returncode=1, stdout=deny, stderr="runtime failed\n")
        )
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("failed_closed", stderr)

    def test_timeout_fails_closed_for_material_action(self) -> None:
        result, stdout, stderr = self._invoke(
            error=subprocess.TimeoutExpired(["python", "hook"], 115)
        )
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("failed_closed", stderr)

    def test_runtime_start_failure_fails_closed_for_material_action(self) -> None:
        result, stdout, stderr = self._invoke(error=OSError("runtime missing"))
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("failed_closed", stderr)

    def test_explicit_exit_two_policy_deny_becomes_structured_success(self) -> None:
        deny = json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "fixture policy",
                }
            }
        )
        result, stdout, _stderr = self._invoke(
            SimpleNamespace(returncode=2, stdout=deny, stderr="")
        )
        self.assertEqual(result, 0)
        self.assertEqual(
            json.loads(stdout)["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )

    def test_structured_runtime_deny_uses_codex_json_success_contract(self) -> None:
        deny = json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "fixture policy",
                }
            }
        )
        result, stdout, _stderr = self._invoke(
            SimpleNamespace(returncode=0, stdout=deny, stderr="")
        )
        self.assertEqual(result, 0)
        self.assertEqual(
            json.loads(stdout)["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )

    def test_runtime_exit_zero_empty_is_native_defer(self) -> None:
        result, stdout, stderr = self._invoke(
            SimpleNamespace(returncode=0, stdout="", stderr="")
        )
        self.assertEqual(result, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")

    def test_runtime_exit_zero_rejects_malformed_or_bare_allow(self) -> None:
        bare_allow = json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                }
            }
        )
        for label, output in (("malformed", "not-json\n"), ("bare-allow", bare_allow)):
            with self.subTest(label=label):
                result, stdout, stderr = self._invoke(
                    SimpleNamespace(returncode=0, stdout=output, stderr="")
                )
                self.assertEqual(result, 0)
                self.assertEqual(
                    json.loads(stdout)["hookSpecificOutput"]["permissionDecision"],
                    "deny",
                )
                self.assertIn("failed_closed", stderr)

    def test_permission_request_empty_success_defers_to_native_codex(self) -> None:
        with mock.patch.dict(
            self.module.os.environ,
            {"SULDE_CODEX_HOOK_EVENT": "PermissionRequest"},
        ):
            result, stdout, stderr = self._invoke(
                SimpleNamespace(returncode=0, stdout="", stderr="")
            )
        self.assertEqual(result, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")

    def test_incidental_exit_two_fails_closed_for_material_action(self) -> None:
        for label, output in (
            ("empty", ""),
            ("launcher", "launcher contract failed\n"),
            (
                "allow",
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "allow",
                            "permissionDecisionReason": "not a deny",
                        }
                    }
                ),
            ),
        ):
            with self.subTest(label=label):
                result, stdout, stderr = self._invoke(
                    SimpleNamespace(
                        returncode=2,
                        stdout=output,
                        stderr="infrastructure exit two\n",
                    )
                )
                self.assertEqual(result, 0)
                self.assertEqual(
                    json.loads(stdout)["hookSpecificOutput"]["permissionDecision"],
                    "deny",
                )
                self.assertIn("failed_closed", stderr)

    def test_runtime_failure_keeps_read_and_plain_git_available(self) -> None:
        for payload in (
            {"toolName": "Read", "toolInput": {"file_path": "fixture"}},
            {"toolName": "Bash", "toolInput": {"command": "git status --short"}},
            {
                "toolName": "Bash",
                "toolInput": {"command": "git status && git diff --stat"},
            },
        ):
            with self.subTest(payload=payload):
                self.payload = json.dumps(payload)
                result, stdout, stderr = self._invoke(
                    SimpleNamespace(returncode=1, stdout="", stderr="runtime failed\n")
                )
                self.assertEqual(result, 0)
                self.assertEqual(stdout, "")
                self.assertIn("degraded_to_native_codex", stderr)

    def test_runtime_failure_defers_exact_recovery_to_native_codex(self) -> None:
        launcher_home = Path(
            os.environ.get("SULDE_HOME") or Path.home() / ".sulde"
        ).expanduser()
        contract = launcher_home / "data/kb/intent/workspaces/fixture.active.json"
        skill_path = Path(
            os.environ.get("CODEX_HOME") or Path.home() / ".codex"
        ).expanduser() / "skills/fixture/SKILL.md"
        artifact_uninstaller = (
            launcher_home
            / "artifacts"
            / "fixture"
            / "codex"
            / "plugins"
            / "sulde"
            / "runtime"
            / "scripts"
            / "kb"
            / "install-agents.sh"
        )
        commands = (
            "codex plugin list --json",
            "codex plugin remove sulde@sulde-local --json",
            f"{launcher_home / 'bin' / 'intent-guardian'} doctor --provider codex",
            (
                f"{launcher_home / 'bin' / 'intent-guardian'} doctor "
                f"--workspace {ROOT} --scan --provider codex --session-id fixture"
            ),
            (
                f"{launcher_home / 'bin' / 'intent-guardian'} skill-start "
                f"sulde:intent-guardian --skill-path {skill_path} "
                f"--contract {contract} --provider codex --session-id fixture"
            ),
            (
                f"{launcher_home / 'bin' / 'intent-guardian'} skill-end "
                f"sulde:intent-guardian --skill-path {skill_path} "
                f"--contract {contract} --provider codex --session-id fixture"
            ),
            f"{artifact_uninstaller} --uninstall --provider codex",
        )
        for command in commands:
            with self.subTest(command=command):
                self.payload = json.dumps(
                    {"toolName": "Bash", "toolInput": {"command": command}}
                )
                result, stdout, stderr = self._invoke(error=OSError("runtime missing"))
                self.assertEqual(result, 0)
                self.assertEqual(stdout, "")
                self.assertIn("degraded_to_native_codex", stderr)

    def test_runtime_failure_rejects_recovery_near_misses(self) -> None:
        for command in (
            "codex plugin remove another@sulde-local --json",
            "codex plugin remove sulde@sulde-local --json ; echo bypass",
            "codex plugin list",
            f"{Path.home() / '.sulde/bin/intent-guardian'} doctor --provider claude",
            "/tmp/intent-guardian doctor --provider codex",
            (
                f"{Path.home() / '.sulde/bin/intent-guardian'} skill-start fixture "
                f"--skill-path /tmp/SKILL.md --contract "
                f"{Path.home() / '.sulde/data/kb/intent/workspaces/fixture.active.json'} "
                "--provider codex --session-id fixture"
            ),
            (
                f"{Path.home() / '.sulde/bin/intent-guardian'} skill-start fixture "
                f"--skill-path {Path.home() / '.codex/skills/fixture/SKILL.md'} "
                f"--contract {Path.home() / '.sulde/data/kb/intent/workspaces/fixture.active.json'} "
                "--provider claude --session-id fixture"
            ),
        ):
            with self.subTest(command=command):
                self.payload = json.dumps(
                    {"toolName": "Bash", "toolInput": {"command": command}}
                )
                result, stdout, stderr = self._invoke(error=OSError("runtime missing"))
                self.assertEqual(result, 0)
                self.assertEqual(
                    json.loads(stdout)["hookSpecificOutput"]["permissionDecision"],
                    "deny",
                )
                self.assertIn("failed_closed", stderr)

    def test_static_and_stable_recovery_classifiers_match(self) -> None:
        cli = load_cli_module()
        launcher_home = Path(
            os.environ.get("SULDE_HOME") or Path.home() / ".sulde"
        ).expanduser()
        codex_home = Path(
            os.environ.get("CODEX_HOME") or Path.home() / ".codex"
        ).expanduser()
        home = launcher_home / "data" / "kb"
        commands = (
            "git status --short",
            "codex plugin list --json",
            "codex plugin remove sulde@sulde-local --json",
            f"{launcher_home / 'bin/intent-guardian'} doctor --provider codex",
            (
                f"{launcher_home / 'bin/intent-guardian'} skill-start fixture "
                f"--skill-path {codex_home / 'skills/fixture/SKILL.md'} "
                f"--contract {launcher_home / 'data/kb/intent/workspaces/fixture.active.json'} "
                "--provider codex --session-id fixture"
            ),
            "codex plugin list",
            "codex plugin remove other@sulde-local --json",
            "printf material",
        )
        for command in commands:
            with self.subTest(command=command):
                payload = {
                    "toolName": "Bash",
                    "toolInput": {"command": command},
                }
                raw = json.dumps(payload).encode("utf-8")
                self.assertEqual(
                    self.module._fallback_requires_deny(payload),
                    cli._codex_pre_tool_failure_requires_deny(raw, home),
                )


if __name__ == "__main__":
    unittest.main()
