import base64
import copy
import hashlib
import json
import shlex
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

import native_agent_broker as broker


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class NativeAgentBrokerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.layout_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.layout_temp.cleanup)
        self.workspace = (Path(self.layout_temp.name).resolve() / "workspace")
        (self.workspace / ".git").mkdir(parents=True)
        (self.workspace / "scripts/kb").mkdir(parents=True)
        (self.workspace / "tests").mkdir()
        self.frozen = {
            "task_id": "T15",
            "base_commit": "2f4593090e13aacdde9fab2f74927d48e77cd85d",
            "task_definition_sha256": sha(b"task definition"),
            "brief_sha256": sha(b"brief"),
            "worktree_canonical_path": str(self.workspace),
            "git_common_dir_canonical_path": str(self.workspace / ".git"),
            "owned_paths": [
                "scripts/kb/native_agent_broker.py",
                "tests/test_native_agent_broker.py",
            ],
            "report_relative_path": ".codex-agent/t15.last.md",
            "model_reasoning_effort": "high",
            "codex_executable": "/opt/codex/bin/codex",
            "codex_version": "codex-cli 0.147.0",
            "codex_executable_sha256": sha(b"codex executable"),
            "broker_generation": 15,
            "broker_sha256": sha(b"immutable broker"),
            "provider_generation": 8,
            "permission_profile_name": "sulde-owned-paths",
            "permission_profile_bytes_sha256": "0" * 64,
            "permission_profile_spec_sha256": sha(b"permission profile spec"),
            "installed_descriptor_sha256": sha(b"installed descriptor"),
            "runtime_generation": "0.2.5+fixture:runtime-tree",
            "runtime_tree_sha256": sha(b"runtime tree"),
            "agent_runtime_sha256": sha(b"agent runtime"),
            "nonce": sha(b"one-shot nonce"),
        }
        self.frozen["permission_profile_bytes_sha256"] = sha(
            broker.permission_profile_bytes(
                self.frozen["owned_paths"], worktree=str(self.workspace)
            )
        )
        self.request = broker.build_request(self.frozen)

    def passing_probe_results(self):
        plan = broker.build_profile_probe_plan(self.request, self.frozen)
        results = []
        for row in plan["probes"]:
            pre_digest = sha((row["probe_id"] + ":pre").encode())
            post_digest = (
                pre_digest
                if row["expected_execution_prevented"]
                else sha((row["probe_id"] + ":post").encode())
            )
            results.append({
                "probe_id": row["probe_id"],
                "operation": row["operation"],
                "pre_exists": row["pre_exists"],
                "post_exists": row["post_exists"],
                "pre_observation_sha256": pre_digest,
                "post_observation_sha256": post_digest,
                "observed_denial": row["expected_execution_prevented"],
                "execution_prevented": row["expected_execution_prevented"],
            })
        return results

    def passing_probe_receipt(self):
        return broker.build_probe_receipt(
            self.request,
            self.frozen,
            self.passing_probe_results(),
            probe_run_id="probe-run-t15-0001",
        )

    def passing_native_observations(self):
        before = {}
        after = {}
        outcomes = {}
        for row in broker._PROBE_MATRIX:
            probe_id, _target_class, operation, pre_exists, post_exists, prevented = row
            pre_digest = sha((probe_id + ":native-pre").encode())
            post_digest = (
                pre_digest
                if prevented
                else sha((probe_id + ":native-post").encode())
            )
            before[probe_id] = (pre_exists, pre_digest)
            after[probe_id] = (post_exists, post_digest)
            outcomes[probe_id] = (
                f"{operation}_permission_denied"
                if prevented
                else f"{operation}_completed"
            )
        return before, after, outcomes

    def passing_launch_plan(self):
        return broker.build_launch_plan(
            self.request, self.passing_probe_receipt(), self.frozen
        )

    def build_provider_receipt(self, **overrides):
        probe_receipt = overrides.pop("probe_receipt", self.passing_probe_receipt())
        launch_plan = overrides.pop(
            "launch_plan",
            broker.build_launch_plan(self.request, probe_receipt, self.frozen),
        )
        kwargs = self.provider_kwargs()
        kwargs.update(overrides)
        return broker.build_provider_receipt(
            self.request, probe_receipt, launch_plan, self.frozen, **kwargs
        )

    def provider_kwargs(self):
        return {
            "started_at": "2026-08-20T10:00:00Z",
            "terminated_at": "2026-08-20T10:00:03Z",
            "provider_pid": 4312,
            "provider_run_id": "run-t15-0001",
            "terminal_status": "succeeded",
            "exit_code": 0,
            "quiescence_confirmed": True,
            "stderr_path": ".codex-agent/logs/t15.stderr",
            "stderr_raw_bytes": b"progress\xffbytes\n",
            "stderr_fsync_completed": True,
            "jsonl_summary": {
                "line_count": 5,
                "valid_json_line_count": 5,
                "terminal_event": "turn.completed",
                "terminal_event_count": 1,
                "sha256": sha(b"jsonl"),
            },
            "output_summary": {
                "present": True,
                "raw_byte_count": 12,
                "sha256": sha(b"output"),
            },
            "report_summary": {
                "present": True,
                "raw_byte_count": 12,
                "sha256": sha(b"output"),
            },
            "observed_denial": False,
            "execution_prevented": False,
        }

    def local_interruption_evidence(self):
        return {
            "schema": "sulde-local-interruption-evidence-v1",
            "run_id": "run-t15-0001",
            "interrupt_reason": "paused",
            "result_stop_reason": "policy_paused",
            "result_returncode": 0,
            "interrupt_event_index": 2,
            "result_event_index": 3,
            "disposed_event_index": 4,
            "quiescent": True,
            "result_before_disposed": True,
            "run_ledger_sha256": sha(b"run ledger"),
        }

    def test_request_round_trip_is_canonical_and_bound(self) -> None:
        self.assertEqual(
            set(self.request),
            {
                "schema",
                "task_id",
                "base_commit",
                "task_definition_sha256",
                "brief_sha256",
                "task_identity_sha256",
                "worktree_canonical_path",
                "git_common_dir_canonical_path",
                "worktree_identity_sha256",
                "owned_paths",
                "owned_paths_sha256",
                "report_relative_path",
                "model_reasoning_effort",
                "codex_executable",
                "codex_version",
                "codex_executable_sha256",
                "codex_identity_sha256",
                "broker_generation",
                "broker_sha256",
                "broker_identity_sha256",
                "provider_generation",
                "permission_profile_name",
                "permission_profile_bytes_sha256",
                "permission_profile_identity_sha256",
                "permission_profile_spec_sha256",
                "installed_descriptor_sha256",
                "runtime_generation",
                "runtime_tree_sha256",
                "agent_runtime_sha256",
                "nonce",
                "coordinator_delivery_projection_sha256",
                "external_authority_required",
                "execution_authorized",
                "request_sha256",
            },
        )
        self.assertEqual(self.request["schema"], "sulde-native-broker-request-v1")
        self.assertEqual(broker.validate_request(self.request, self.frozen), self.request)
        encoded = broker.canonical_json_bytes(self.request)
        self.assertEqual(
            encoded,
            json.dumps(
                self.request,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode(),
        )
        self.assertEqual(broker.load_plain_json(encoded), self.request)

    def test_projection_identity_and_non_authority_flags_bind_every_public_record(self) -> None:
        probe_plan = broker.build_profile_probe_plan(self.request, self.frozen)
        probe_receipt = self.passing_probe_receipt()
        launch_plan = broker.build_launch_plan(
            self.request, probe_receipt, self.frozen
        )
        terminal = self.build_provider_receipt(
            probe_receipt=probe_receipt, launch_plan=launch_plan
        )
        projection = self.request["coordinator_delivery_projection_sha256"]
        for record in (
            self.request,
            probe_plan,
            probe_receipt,
            launch_plan,
            terminal,
        ):
            with self.subTest(schema=record["schema"]):
                self.assertEqual(
                    record["coordinator_delivery_projection_sha256"], projection
                )
                self.assertTrue(record["external_authority_required"])
                self.assertFalse(record["execution_authorized"])

        covered_mutations = {
            "task_id": "T16",
            "base_commit": "3" * 40,
            "task_definition_sha256": sha(b"different task definition"),
            "brief_sha256": sha(b"different brief"),
            "worktree_canonical_path": "/private/tmp/other-worktree",
            "owned_paths": ["scripts/kb/other.py"],
            "report_relative_path": ".codex-agent/t16.last.md",
            "model_reasoning_effort": "medium",
            "codex_executable_sha256": sha(b"different executable bytes"),
            "permission_profile_bytes_sha256": sha(b"different profile bytes"),
            "permission_profile_spec_sha256": sha(b"different profile spec"),
            "installed_descriptor_sha256": sha(b"different installed descriptor"),
            "runtime_generation": "other:runtime-tree",
            "runtime_tree_sha256": sha(b"different runtime tree"),
            "agent_runtime_sha256": sha(b"different agent runtime"),
            "broker_generation": 16,
            "provider_generation": 9,
        }
        for field, value in covered_mutations.items():
            with self.subTest(projection_field=field):
                changed = copy.deepcopy(self.frozen)
                changed[field] = value
                changed_request = broker.build_request(changed)
                self.assertNotEqual(
                    changed_request["coordinator_delivery_projection_sha256"],
                    projection,
                )

        for flag, value in (
            ("external_authority_required", False),
            ("execution_authorized", True),
        ):
            candidate = copy.deepcopy(self.request)
            candidate[flag] = value
            with self.assertRaises(broker.ProtocolError):
                broker.validate_request(candidate, self.frozen)

    def test_request_rejects_unknown_missing_and_non_plain_fields(self) -> None:
        for mutation in ("unknown", "missing"):
            with self.subTest(mutation=mutation):
                candidate = copy.deepcopy(self.request)
                if mutation == "unknown":
                    candidate["argv"] = ["sh", "-c", "true"]
                else:
                    del candidate["brief_sha256"]
                with self.assertRaises(broker.ProtocolError):
                    broker.validate_request(candidate, self.frozen)

        class DictSubclass(dict):
            pass

        class ListSubclass(list):
            pass

        with self.assertRaises(broker.ProtocolError):
            broker.validate_request(DictSubclass(self.request), self.frozen)
        candidate = copy.deepcopy(self.request)
        candidate["owned_paths"] = ListSubclass(candidate["owned_paths"])
        with self.assertRaises(broker.ProtocolError):
            broker.validate_request(candidate, self.frozen)

    def test_request_rejects_bool_as_int_and_coercion(self) -> None:
        for field, value in (("broker_generation", True), ("provider_generation", "8")):
            with self.subTest(field=field):
                frozen = copy.deepcopy(self.frozen)
                frozen[field] = value
                with self.assertRaises(broker.ProtocolError):
                    broker.build_request(frozen)

    def test_request_rejects_authority_bearing_inputs(self) -> None:
        for field, value in (
            ("argv", ["codex", "app-server"]),
            ("shell", "/bin/zsh"),
            ("env", {"X": "Y"}),
            ("cwd", "/tmp"),
            ("profile_path", "/tmp/profile.toml"),
            ("output_path", "/tmp/out"),
            ("sandbox_mode", "workspace-write"),
        ):
            with self.subTest(field=field):
                frozen = copy.deepcopy(self.frozen)
                frozen[field] = value
                with self.assertRaises(broker.ProtocolError):
                    broker.build_request(frozen)

    def test_request_detects_every_frozen_identity_drift(self) -> None:
        mutations = {
            "task_id": "T16",
            "base_commit": "3" * 40,
            "task_definition_sha256": "3" * 64,
            "brief_sha256": "4" * 64,
            "worktree_canonical_path": "/private/tmp/other-worktree",
            "owned_paths": ["scripts/kb/other.py"],
            "report_relative_path": ".codex-agent/other.last.md",
            "model_reasoning_effort": "low",
            "codex_executable": "/opt/codex/bin/codex-new",
            "codex_version": "codex-cli 0.148.0",
            "codex_executable_sha256": "5" * 64,
            "broker_generation": 16,
            "broker_sha256": "6" * 64,
            "provider_generation": 9,
            "permission_profile_name": "wrong-profile",
            "permission_profile_bytes_sha256": "7" * 64,
            "permission_profile_spec_sha256": "9" * 64,
            "installed_descriptor_sha256": "a" * 64,
            "runtime_generation": "other:generation",
            "runtime_tree_sha256": "b" * 64,
            "agent_runtime_sha256": "c" * 64,
            "nonce": "8" * 64,
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                frozen = copy.deepcopy(self.frozen)
                frozen[field] = value
                with self.assertRaisesRegex(broker.ProtocolError, "frozen request"):
                    broker.validate_request(self.request, frozen)

    def test_request_recomputes_derived_identity_and_request_hashes(self) -> None:
        for field in (
            "task_identity_sha256",
            "worktree_identity_sha256",
            "owned_paths_sha256",
            "codex_identity_sha256",
            "broker_identity_sha256",
            "permission_profile_identity_sha256",
            "coordinator_delivery_projection_sha256",
            "request_sha256",
        ):
            with self.subTest(field=field):
                candidate = copy.deepcopy(self.request)
                candidate[field] = "0" * 64
                with self.assertRaises(broker.ProtocolError):
                    broker.validate_request(candidate, self.frozen)

    def test_owned_paths_are_ordered_exact_and_canonical(self) -> None:
        invalid = (
            [],
            ["/absolute.py"],
            [""],
            ["a//b.py"],
            ["a/./b.py"],
            ["a/../b.py"],
            ["a\\b.py"],
            ["a\x00b.py"],
            ["a/*.py"],
            ["a/?.py"],
            ["a/[b].py"],
            [":(glob)a.py"],
            ["a.py", "a.py"],
            ["A.py", "a.py"],
            ["caf\u00e9.py", "cafe\u0301.py"],
            ["stra\u00dfe.py", "STRASSE.py"],
            ["fullwidth\uff0fslash.py"],
            ["fullwidth\uff3cbackslash.py"],
            ["fullwidth\uff0astar.py"],
            ["fullwidth\uff1fquestion.py"],
            ["fullwidth\uff3bclass\uff3d.py"],
            ["control\nname.py"],
            ["bidi\u202ename.py"],
            ["fraction\u2044slash.py"],
        )
        for owned_paths in invalid:
            with self.subTest(owned_paths=owned_paths):
                frozen = copy.deepcopy(self.frozen)
                frozen["owned_paths"] = owned_paths
                with self.assertRaises(broker.ProtocolError):
                    broker.build_request(frozen)

        reversed_frozen = copy.deepcopy(self.frozen)
        reversed_frozen["owned_paths"].reverse()
        reversed_request = broker.build_request(reversed_frozen)
        self.assertNotEqual(
            reversed_request["owned_paths_sha256"], self.request["owned_paths_sha256"]
        )

    def test_absolute_paths_are_lexically_canonical(self) -> None:
        for field, value in (
            ("worktree_canonical_path", "relative/worktree"),
            ("worktree_canonical_path", "/private/tmp/../tmp/worktree"),
            ("codex_executable", "codex"),
            ("codex_executable", "/opt//codex"),
            ("codex_executable", "/opt/\uff43odex"),
            ("worktree_canonical_path", "/private/tmp/control\nworktree"),
            ("worktree_canonical_path", "/private/tmp/division\u2215worktree"),
        ):
            with self.subTest(field=field, value=value):
                frozen = copy.deepcopy(self.frozen)
                frozen[field] = value
                with self.assertRaises(broker.ProtocolError):
                    broker.build_request(frozen)

    def test_diagnostic_stream_targets_do_not_authorize_other_dev_nodes_or_aliases(self) -> None:
        for target in ("/dev/stdout", "/dev/stderr", "/dev/fd/1", "/dev/fd/2"):
            self.assertTrue(broker.is_bounded_diagnostic_stream_target(target))
        for target in (
            "/dev/null",
            "/dev/fd/0",
            "/dev/fd/3",
            "/dev/console",
            "/dev//stdout",
            "/dev/fd/01",
            "/private/dev/stdout",
        ):
            self.assertFalse(broker.is_bounded_diagnostic_stream_target(target))

    def test_native_profile_failure_distinguishes_nested_host_sandbox(self) -> None:
        self.assertEqual(broker.classify_native_profile_failure(0, b""), "none")
        self.assertEqual(
            broker.classify_native_profile_failure(
                1, b"sandbox-exec: sandbox_apply: Operation not permitted\n"
            ),
            "nested_sandbox_interference",
        )
        self.assertEqual(
            broker.classify_native_profile_failure(1, b"invalid profile syntax\n"),
            "native_profile_initialization",
        )

    def test_plain_json_rejects_duplicate_keys_floats_constants_and_subclasses(self) -> None:
        for payload in (
            b'{"a":1,"a":2}',
            b'{"a":1.0}',
            b'{"a":NaN}',
            b'{"a":Infinity}',
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(broker.ProtocolError):
                    broker.load_plain_json(payload)

        class BytesSubclass(bytes):
            pass

        with self.assertRaises(broker.ProtocolError):
            broker.load_plain_json(BytesSubclass(b"{}"))

        cycle = []
        cycle.append(cycle)
        with self.assertRaises(broker.ProtocolError):
            broker.canonical_json_bytes(cycle)
        with self.assertRaises(broker.ProtocolError):
            broker.canonical_json_bytes({"surrogate": "\ud800"})

    def test_magic_objects_are_rejected_without_callbacks(self) -> None:
        calls = []

        class Magic:
            def __iter__(self):
                calls.append("iter")
                return iter(())

            def __str__(self):
                calls.append("str")
                return "magic"

            def __bool__(self):
                calls.append("bool")
                return True

            def __eq__(self, other):
                calls.append("eq")
                return False

        for value in (Magic(), {"nested": Magic()}, [Magic()]):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(broker.ProtocolError):
                    broker.canonical_json_bytes(value)
        frozen = copy.deepcopy(self.frozen)
        frozen["broker_generation"] = Magic()
        with self.assertRaises(broker.ProtocolError):
            broker.build_request(frozen)

        class MagicDict(dict):
            def items(self):
                calls.append("dict.items")
                return super().items()

        class MagicList(list):
            def __iter__(self):
                calls.append("list.iter")
                return super().__iter__()

        class MagicString(str):
            def __str__(self):
                calls.append("string.str")
                return super().__str__()

        class MagicInt(int):
            def __index__(self):
                calls.append("int.index")
                return super().__index__()

        for value in (MagicDict(), MagicList(), MagicString("x"), MagicInt(1)):
            with self.subTest(subclass=type(value).__name__):
                with self.assertRaises(broker.ProtocolError):
                    broker.canonical_json_bytes(value)
        self.assertEqual(calls, [])

    def test_provider_command_is_fixed_codex_exec_template(self) -> None:
        command = broker.build_provider_command(self.request, self.frozen)
        self.assertEqual(
            broker.validate_provider_command(command, self.request, self.frozen),
            command,
        )
        self.assertEqual(command[:2], ["/opt/codex/bin/codex", "exec"])
        self.assertIn(str(self.workspace / ".codex-agent/t15.last.md"), command)
        self.assertIn('model_reasoning_effort="high"', command)
        self.assertIn("danger-full-access", command)
        self.assertIn("--dangerously-bypass-hook-trust", command)
        self.assertIn("features.multi_agent=false", command)
        joined = " ".join(command)
        self.assertNotIn("app-server", joined)
        self.assertEqual(command.count("-s"), 1)
        self.assertNotIn("sandbox_mode", joined)
        hook_config = next(
            value
            for value in command
            if value.startswith("hooks.PreToolUse=")
        )
        self.assertIn("--codex-pre-tool-hook", hook_config)
        self.assertIn('matcher=".*"', hook_config)
        self.assertNotIn('default_permissions=', joined)
        self.assertNotIn("--profile", command)
        self.assertLess(command.index("exec"), command.index("--ignore-user-config"))
        native_profile = broker.render_native_command_profile(
            str(self.workspace), self.frozen["owned_paths"]
        )
        self.assertIn("(deny network*)", native_profile)
        self.assertIn("(deny file-write*)", native_profile)
        for relative in self.frozen["owned_paths"]:
            self.assertIn(
                f'(allow file-write* (literal "{self.workspace / relative}"))',
                native_profile,
            )
        self.assertNotIn(
            f'(allow file-write* (subpath "{self.workspace}"))',
            native_profile,
        )

    def test_pre_tool_hook_rewrites_commands_once_and_denies_other_tools(self) -> None:
        profile_raw = broker.permission_profile_bytes(
            self.frozen["owned_paths"], worktree=str(self.workspace)
        )
        arguments = {
            "profile_base64": base64.b64encode(profile_raw).decode("ascii"),
            "profile_sha256": sha(profile_raw),
            "broker_sha256": sha(Path(broker.__file__).read_bytes()),
            "scratch_path": broker.native_command_scratch_path(str(self.workspace)),
        }
        allowed = broker.codex_pre_tool_hook_decision(
            {"tool_name": "shell", "tool_input": {"command": "printf '%s' '$HOME'"}},
            **arguments,
        )["hookSpecificOutput"]
        self.assertEqual(allowed["permissionDecision"], "allow")
        wrapped = shlex.split(allowed["updatedInput"]["command"])
        self.assertEqual(wrapped.count("/usr/bin/sandbox-exec"), 1)
        self.assertEqual(wrapped[:2], ["/usr/bin/sandbox-exec", "-p"])
        self.assertIn("(deny network*)", wrapped[2])
        self.assertEqual(wrapped[-4:-1], ["/bin/zsh", "-f", "-c"])
        self.assertEqual(wrapped[-1], "printf '%s' '$HOME'")

        denied = broker.codex_pre_tool_hook_decision(
            {"tool_name": "apply_patch", "tool_input": {"patch": "data"}},
            **arguments,
        )["hookSpecificOutput"]
        self.assertEqual(denied["permissionDecision"], "deny")
        self.assertNotIn("updatedInput", denied)

        tampered = broker.codex_pre_tool_hook_decision(
            {"tool_name": "shell", "tool_input": {"command": "true"}},
            **{**arguments, "profile_sha256": sha(b"tampered")},
        )["hookSpecificOutput"]
        self.assertEqual(tampered["permissionDecision"], "deny")

    def test_provider_command_validator_rejects_wrong_order_and_forbidden_modes(self) -> None:
        valid = broker.build_provider_command(self.request, self.frozen)
        bad_commands = (
            [valid[0], "--ignore-user-config", "exec", *valid[2:]],
            [valid[0], "app-server", *valid[2:]],
            ["/usr/bin/sandbox-exec", "-p", "(version 1) (allow default)", *valid],
            [*valid[:-1], "--sandbox", "workspace-write", "-"],
            [*valid[:-1], "-c", "sandbox_mode=workspace-write", "-"],
        )
        for command in bad_commands:
            with self.subTest(command=command):
                with self.assertRaises(broker.ProtocolError):
                    broker.validate_provider_command(command, self.request, self.frozen)

        drifted = copy.deepcopy(self.frozen)
        drifted["permission_profile_bytes_sha256"] = sha(b"caller projection")
        drifted_request = broker.build_request(drifted)
        with self.assertRaisesRegex(broker.ProtocolError, "profile bytes"):
            broker.build_provider_command(drifted_request, drifted)

    def test_renderer_emits_only_lexical_descendants_and_exact_bytes(self) -> None:
        owned = ["scripts/kb/native_agent_broker.py", "tests/test_native_agent_broker.py"]
        arguments = broker.render_permission_profile_arguments(owned)
        profile = arguments[-1]
        self.assertEqual(arguments[:3], [
            "-c", 'default_permissions="sulde-owned-paths"', "-c"
        ])
        self.assertEqual(profile.count('"."="read"'), 1)
        self.assertIn('"scripts/kb/native_agent_broker.py"="write"', profile)
        self.assertIn('"tests/test_native_agent_broker.py"="write"', profile)
        self.assertIn('":tmpdir"="deny"', profile)
        self.assertIn('":slash_tmp"="deny"', profile)
        self.assertIn("network={enabled=false}", profile)
        self.assertNotIn(str(self.workspace), profile)
        native = broker.permission_profile_bytes(
            owned, worktree=str(self.workspace)
        )
        self.assertEqual(
            native,
            broker.render_native_command_profile(
                str(self.workspace), owned
            ).encode("utf-8"),
        )

    def test_git_layout_accepts_full_clone_and_rejects_external_dotdot_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name).resolve()
            full = directory / "full"
            common = full / ".git"
            full.mkdir()
            common.mkdir()
            (full / "owned.py").touch()
            self.assertEqual(
                broker.validate_supported_git_layout(
                    str(full), str(common), owned_paths=["owned.py"]
                ),
                (str(full), str(common)),
            )

            external = directory / "external"
            external.mkdir()
            linked = directory / "linked"
            linked.mkdir()
            (linked / ".git").write_text(
                f"gitdir: {external}\n", encoding="utf-8"
            )
            for worktree, git_common in (
                (str(linked), str(external)),
                (str(full), str(external)),
                (str(full) + "/.", str(common)),
                (str(full), str(full / "child/../.git")),
                (str(full), "/private/arbitrary-git-common"),
            ):
                with self.subTest(worktree=worktree, git_common=git_common):
                    with self.assertRaises(broker.ProtocolError):
                        broker.validate_supported_git_layout(
                            worktree, git_common, owned_paths=["owned.py"]
                        )

            aliased_full = directory / "aliased-full"
            aliased_full.symlink_to(full, target_is_directory=True)
            with self.assertRaisesRegex(broker.UnsupportedGitLayout, "symlink"):
                broker.validate_supported_git_layout(
                    str(aliased_full), str(aliased_full / ".git")
                )

            symlink_root = directory / "symlink-git"
            symlink_root.mkdir()
            (symlink_root / ".git").symlink_to(
                external, target_is_directory=True
            )
            with self.assertRaisesRegex(broker.UnsupportedGitLayout, "symlink"):
                broker.validate_supported_git_layout(
                    str(symlink_root), str(symlink_root / ".git")
                )

            outside = directory / "outside"
            outside.mkdir()
            (full / "owned-alias").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(
                broker.UnsupportedGitLayout, "owned path layout"
            ):
                broker.validate_supported_git_layout(
                    str(full), str(common), owned_paths=["owned-alias/new.py"]
                )

    def test_external_layout_stops_native_probe_before_side_effects(self) -> None:
        frozen = copy.deepcopy(self.frozen)
        frozen["git_common_dir_canonical_path"] = str(
            self.workspace.parent / "external-git"
        )
        request = broker.build_request(frozen)
        with tempfile.TemporaryDirectory() as directory_name:
            evidence = Path(directory_name) / "layout-failure.json"
            with (
                mock.patch.object(broker.tempfile, "mkdtemp") as create_probe,
                self.assertRaisesRegex(
                    broker.UnsupportedGitLayout,
                    "coordinator must create a full clone",
                ),
            ):
                broker.execute_native_profile_probe(
                    request,
                    frozen,
                    evidence_path=str(evidence),
                )
            create_probe.assert_not_called()
            self.assertFalse(evidence.exists())

    def test_profile_probe_plan_is_fixed_complete_and_data_only(self) -> None:
        plan = broker.build_profile_probe_plan(self.request, self.frozen)
        self.assertEqual(plan["schema"], "sulde-native-profile-probe-plan-v2")
        self.assertEqual(
            [row["probe_id"] for row in plan["probes"]],
            [
                "existing_owned_write",
                "new_owned_create",
                "workspace_nonowned",
                "system_tmp",
                "environment_tmpdir",
                "owned_parent_escape",
                "owned_sibling_escape",
                "git_common_write",
                "scope_outside_symlink",
                "scope_outside_pycache",
                "network_socket",
                "nonowned_unlink_file",
                "nonowned_unlink_empty_dir",
                "nonowned_unlink_symlink",
                "git_control_unlink",
                "codex_agent_control_unlink",
                "owned_adjacent_unlink",
                "nonowned_move",
                "nonowned_replace",
            ],
        )
        self.assertEqual(
            [row["expected_execution_prevented"] for row in plan["probes"]],
            [False, False] + [True] * 17,
        )
        self.assertTrue(all(set(row) == {
            "probe_id", "target_class", "operation", "pre_exists", "post_exists", "expected_execution_prevented"
        } for row in plan["probes"]))

    def test_native_probe_stdout_is_one_canonical_exact_cardinality_line(self) -> None:
        _before, _after, outcomes = self.passing_native_observations()
        encoded = broker.canonical_json_bytes(outcomes) + b"\n"
        self.assertEqual(broker._parse_native_probe_stdout(encoded), outcomes)

        missing = dict(outcomes)
        missing.pop("scope_outside_pycache")
        extra = {**outcomes, "unplanned": "unlink_permission_denied"}
        substring = dict(outcomes)
        substring["system_tmp"] = "create_permission_denied:PermissionError"
        wrong_operation = dict(outcomes)
        wrong_operation["nonowned_unlink_file"] = "write_permission_denied"
        for candidate in (
            b"prefix" + encoded,
            encoded + b"\n",
            broker.canonical_json_bytes(missing) + b"\n",
            broker.canonical_json_bytes(extra) + b"\n",
            broker.canonical_json_bytes(substring) + b"\n",
            broker.canonical_json_bytes(wrong_operation) + b"\n",
            b"",
        ):
            with self.subTest(candidate=candidate):
                with self.assertRaises(broker.ProtocolError):
                    broker._parse_native_probe_stdout(candidate)

    def test_native_regular_and_pycache_denials_are_separate_child_observations(self) -> None:
        before, after, outcomes = self.passing_native_observations()
        results = broker._native_probe_results(before, after, outcomes)
        by_id = {row["probe_id"]: row for row in results}
        for probe_id in ("system_tmp", "scope_outside_pycache"):
            self.assertEqual(outcomes[probe_id], "create_permission_denied")
            self.assertFalse(by_id[probe_id]["pre_exists"])
            self.assertFalse(by_id[probe_id]["post_exists"])
            self.assertTrue(by_id[probe_id]["observed_denial"])
            self.assertTrue(by_id[probe_id]["execution_prevented"])
        for probe_id in ("existing_owned_write", "new_owned_create"):
            expected = (
                "write_completed"
                if probe_id == "existing_owned_write"
                else "create_completed"
            )
            self.assertEqual(outcomes[probe_id], expected)
            self.assertFalse(by_id[probe_id]["observed_denial"])
            self.assertFalse(by_id[probe_id]["execution_prevented"])

    def test_destructive_denials_are_operation_specific_and_complete(self) -> None:
        before, after, outcomes = self.passing_native_observations()
        results = broker._native_probe_results(before, after, outcomes)
        by_id = {row["probe_id"]: row for row in results}
        destructive = {
            "nonowned_unlink_file": "unlink",
            "nonowned_unlink_empty_dir": "unlink",
            "nonowned_unlink_symlink": "unlink",
            "git_control_unlink": "unlink",
            "codex_agent_control_unlink": "unlink",
            "owned_adjacent_unlink": "unlink",
            "nonowned_move": "rename",
            "nonowned_replace": "replace",
        }
        for probe_id, operation in destructive.items():
            with self.subTest(probe_id=probe_id):
                self.assertEqual(
                    outcomes[probe_id], f"{operation}_permission_denied"
                )
                self.assertEqual(by_id[probe_id]["operation"], operation)
                self.assertTrue(by_id[probe_id]["pre_exists"])
                self.assertTrue(by_id[probe_id]["post_exists"])
                self.assertTrue(by_id[probe_id]["observed_denial"])
                self.assertTrue(by_id[probe_id]["execution_prevented"])

        missing_unlink_denial = self.passing_probe_results()
        unlink = next(
            row
            for row in missing_unlink_denial
            if row["probe_id"] == "nonowned_unlink_file"
        )
        unlink["observed_denial"] = False
        with self.assertRaisesRegex(
            broker.ProtocolError, "denial observation is missing"
        ):
            broker.build_probe_receipt(
                self.request,
                self.frozen,
                missing_unlink_denial,
                probe_run_id="probe-run-missing-unlink-denial",
            )

    def test_seatbelt_profile_uses_independent_deny_clauses_and_exact_quoting(self) -> None:
        paths = [
            ("literal", Path('/private/tmp/workspace \\ "nonowned"')),
            ("literal", Path("/private/tmp/system-first-write")),
            ("literal", Path("/private/tmp/environment-first-write")),
            ("literal", Path("/private/tmp/symlink-target")),
            ("literal", Path("/private/tmp/pycache")),
            ("subpath", Path("/private/tmp/pycache")),
        ]
        profile = broker._seatbelt_file_write_profile(paths)
        self.assertEqual(profile.count("(deny file-write*"), len(paths))
        self.assertNotIn(
            '(literal "/private/tmp/system-first-write") '
            '(literal "/private/tmp/environment-first-write")',
            profile,
        )
        self.assertIn(
            '(deny file-write* '
            '(literal "/private/tmp/workspace \\\\ \\"nonowned\\""))',
            profile,
        )
        for filter_kind, path in paths[1:]:
            self.assertIn(
                f'(deny file-write* ({filter_kind} "{path}"))',
                profile,
            )

    @unittest.skipUnless(sys.platform == "darwin", "macOS /var alias required")
    def test_seatbelt_profile_canonicalizes_var_aliases_and_missing_child(self) -> None:
        lexical_parent = Path("/var/folders")
        physical_parent = Path("/private/var/folders")
        if (
            not lexical_parent.is_dir()
            or lexical_parent.resolve(strict=True) != physical_parent.resolve(strict=True)
        ):
            self.skipTest("host does not expose /var as the /private/var alias")

        for filter_kind in ("literal", "subpath"):
            with self.subTest(filter_kind=filter_kind, target="existing"):
                self.assertEqual(
                    broker._seatbelt_file_write_profile(
                        [(filter_kind, lexical_parent)]
                    ),
                    broker._seatbelt_file_write_profile(
                        [(filter_kind, physical_parent)]
                    ),
                )

        missing_name = f".sulde-seatbelt-not-created-{id(self):x}"
        lexical_missing = lexical_parent / missing_name
        physical_missing = physical_parent / missing_name
        self.assertFalse(lexical_missing.exists())
        self.assertFalse(physical_missing.exists())
        self.assertEqual(
            broker._seatbelt_file_write_profile([("literal", lexical_missing)]),
            broker._seatbelt_file_write_profile([("literal", physical_missing)]),
        )
        self.assertIn(
            f'(literal "{physical_missing}")',
            broker._seatbelt_file_write_profile([("literal", lexical_missing)]),
        )

    def test_seatbelt_profile_resolves_existing_symlink_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            physical_parent = root / "scope-outside"
            physical_parent.mkdir()
            alias_parent = root / "owned-alias"
            alias_parent.symlink_to(physical_parent, target_is_directory=True)
            missing_target = alias_parent / "not-yet-created"

            profile = broker._seatbelt_file_write_profile(
                [("literal", missing_target), ("subpath", missing_target)]
            )
            canonical_target = physical_parent.resolve(strict=True) / missing_target.name
            self.assertNotIn(str(alias_parent), profile)
            self.assertEqual(profile.count(f'"{canonical_target}"'), 2)

    def test_seatbelt_profile_rejects_noncanonical_paths(self) -> None:
        for path in (
            Path("relative/path"),
            Path("/private/tmp/../tmp/path"),
            Path("/private/tmp/control\npath"),
            "/private//tmp/path",
            "/private/tmp/./path",
        ):
            with self.subTest(path=path):
                with self.assertRaisesRegex(
                    broker.ProtocolError,
                    "native profile path",
                ):
                    broker._seatbelt_file_write_profile([("literal", path)])

    def test_native_probe_rejects_preexisting_first_write_target(self) -> None:
        before, _after, _outcomes = self.passing_native_observations()
        before["system_tmp"] = (True, sha(b"pre-existing regular target"))
        with self.assertRaisesRegex(broker.ProtocolError, "pre-existed unexpectedly"):
            broker._validate_native_probe_preconditions(before)

        before, _after, _outcomes = self.passing_native_observations()
        before["scope_outside_pycache"] = (
            True,
            sha(b"pre-existing pycache target"),
        )
        with self.assertRaisesRegex(broker.ProtocolError, "pre-existed unexpectedly"):
            broker._validate_native_probe_preconditions(before)

    def test_native_probe_rejects_false_success_matrices(self) -> None:
        before, after, outcomes = self.passing_native_observations()
        cases = []

        wrote_without_denial = dict(outcomes)
        wrote_without_denial["system_tmp"] = "create_completed"
        cases.append((before, after, wrote_without_denial))

        denial_but_target_created = dict(after)
        denial_but_target_created["scope_outside_pycache"] = (
            True,
            sha(b"created despite denial label"),
        )
        cases.append((before, denial_but_target_created, outcomes))

        allowed_control_did_not_write = dict(after)
        allowed_control_did_not_write["new_owned_create"] = (
            False,
            before["new_owned_create"][1],
        )
        cases.append((before, allowed_control_did_not_write, outcomes))

        incomplete_before = dict(before)
        incomplete_before.pop("system_tmp")
        cases.append((incomplete_before, after, outcomes))

        extra_after = dict(after)
        extra_after["unplanned"] = (False, sha(b"unplanned"))
        cases.append((before, extra_after, outcomes))

        for candidate_before, candidate_after, candidate_outcomes in cases:
            with self.subTest(after=candidate_after, outcomes=candidate_outcomes):
                with self.assertRaises(broker.ProtocolError):
                    broker._native_probe_results(
                        candidate_before,
                        candidate_after,
                        candidate_outcomes,
                    )

    def test_probe_receipt_requires_all_unique_truthful_results(self) -> None:
        results = self.passing_probe_results()
        receipt = broker.build_probe_receipt(
            self.request,
            self.frozen,
            results,
            probe_run_id="probe-run-t15-0001",
        )
        self.assertEqual(receipt["schema"], "sulde-native-profile-probe-receipt-v2")
        self.assertEqual(
            broker.validate_probe_receipt(receipt, self.request, self.frozen), receipt
        )

        bad_results = (
            results[:-1],
            [*results[:-1], copy.deepcopy(results[0])],
        )
        for rows in bad_results:
            with self.subTest(rows=rows):
                with self.assertRaises(broker.ProtocolError):
                    broker.build_probe_receipt(
                        self.request,
                        self.frozen,
                        rows,
                        probe_run_id="probe-run-t15-0001",
                    )

    def test_probe_run_and_observations_are_bound_and_non_placeholder(self) -> None:
        receipt = self.passing_probe_receipt()
        self.assertRegex(receipt["probe_run_identity_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(receipt["probe_run_id"], "probe-run-t15-0001")

        for mutation in ("missing", "placeholder", "mismatch"):
            with self.subTest(mutation=mutation):
                candidate = copy.deepcopy(receipt)
                if mutation == "missing":
                    del candidate["probes"][0]["pre_observation_sha256"]
                elif mutation == "placeholder":
                    candidate["probes"][0]["post_observation_sha256"] = "0" * 64
                else:
                    candidate["probe_run_identity_sha256"] = sha(b"other probe run")
                with self.assertRaises(broker.ProtocolError):
                    broker.validate_probe_receipt(candidate, self.request, self.frozen)

        for probe_run_id in ("placeholder", "unknown", "none", "todo"):
            with self.subTest(probe_run_id=probe_run_id):
                with self.assertRaises(broker.ProtocolError):
                    broker.build_probe_receipt(
                        self.request,
                        self.frozen,
                        self.passing_probe_results(),
                        probe_run_id=probe_run_id,
                    )

    def test_probe_denial_and_prevention_are_independent_and_observation_derived(self) -> None:
        results = self.passing_probe_results()
        allowed = next(row for row in results if row["probe_id"] == "existing_owned_write")
        allowed["observed_denial"] = True
        allowed["execution_prevented"] = False
        receipt = broker.build_probe_receipt(
            self.request,
            self.frozen,
            results,
            probe_run_id="probe-run-t15-denial-with-write",
        )
        round_tripped = broker.validate_probe_receipt(receipt, self.request, self.frozen)
        allowed_receipt = next(
            row for row in round_tripped["probes"]
            if row["probe_id"] == "existing_owned_write"
        )
        self.assertTrue(allowed_receipt["observed_denial"])
        self.assertFalse(allowed_receipt["execution_prevented"])

        tampered = self.passing_probe_results()
        tampered[0]["post_observation_sha256"] = tampered[0]["pre_observation_sha256"]
        tampered[0]["execution_prevented"] = False
        with self.assertRaisesRegex(broker.ProtocolError, "observation"):
            broker.build_probe_receipt(
                self.request,
                self.frozen,
                tampered,
                probe_run_id="probe-run-t15-tampered",
            )

    def test_launch_plan_rejects_request_profile_generation_cli_and_probe_drift(self) -> None:
        receipt = self.passing_probe_receipt()
        plan = broker.build_launch_plan(self.request, receipt, self.frozen)
        self.assertEqual(plan["command"], broker.build_provider_command(self.request, self.frozen))
        self.assertTrue(plan["external_authority_required"])
        self.assertFalse(plan["execution_authorized"])
        self.assertNotIn("approval", plan)
        self.assertEqual(
            plan["probe_run_identity_sha256"],
            receipt["probe_run_identity_sha256"],
        )
        self.assertEqual(
            broker.validate_launch_plan(plan, self.request, receipt, self.frozen), plan
        )

        mutations = (
            ("request_sha256", "0" * 64),
            ("permission_profile_bytes_sha256", "1" * 64),
            ("broker_generation", 14),
            ("provider_generation", 7),
            ("codex_version", "codex-cli 0.148.0"),
            ("codex_executable_sha256", "2" * 64),
            ("installed_descriptor_sha256", sha(b"rollback descriptor")),
            ("runtime_generation", "rollback:generation"),
            ("runtime_tree_sha256", sha(b"rollback runtime")),
            ("agent_runtime_sha256", sha(b"rollback agent")),
            ("permission_profile_spec_sha256", sha(b"rollback profile spec")),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                candidate = copy.deepcopy(receipt)
                candidate[field] = value
                with self.assertRaises(broker.ProtocolError):
                    broker.build_launch_plan(self.request, candidate, self.frozen)

        candidate = copy.deepcopy(receipt)
        candidate["probes"][2]["execution_prevented"] = False
        with self.assertRaises(broker.ProtocolError):
            broker.build_launch_plan(self.request, candidate, self.frozen)

        candidate_plan = copy.deepcopy(plan)
        candidate_plan["probe_run_identity_sha256"] = sha(b"cross probe")
        with self.assertRaises(broker.ProtocolError):
            broker.validate_launch_plan(
                candidate_plan, self.request, receipt, self.frozen
            )

    def test_stderr_binding_uses_caller_raw_bytes_and_preserves_invalid_utf8(self) -> None:
        raw = b"valid\ninvalid:\xff\xfe\x80"
        binding = broker.build_stderr_binding(
            ".codex-agent/logs/t15.stderr", raw, True
        )
        self.assertEqual(binding["raw_byte_count"], len(raw))
        self.assertEqual(binding["sha256"], sha(raw))
        self.assertEqual(broker.stderr_binding_raw_bytes(binding), raw)
        self.assertTrue(binding["fsync_completed"])

    def test_stderr_binding_rejects_escape_hash_count_and_fsync_drift(self) -> None:
        for path in (
            "/tmp/stderr",
            "../stderr",
            "logs/../../stderr",
            "logs\\stderr",
            "logs//stderr",
            "logs/*.stderr",
            "logs/\uff0estderr",
            "logs/\uff0fstderr",
            "logs/\uff3cstderr",
            "logs/control\nstderr",
            "logs/fraction\u2044stderr",
        ):
            with self.subTest(path=path):
                with self.assertRaises(broker.ProtocolError):
                    broker.build_stderr_binding(path, b"failure", True)

        valid = broker.build_stderr_binding("logs/stderr", b"failure", True)
        for field, value in (
            ("raw_byte_count", 99),
            ("sha256", "0" * 64),
            ("fsync_completed", False),
        ):
            with self.subTest(field=field):
                candidate = copy.deepcopy(valid)
                candidate[field] = value
                with self.assertRaises(broker.ProtocolError):
                    broker.validate_stderr_binding(candidate)

        invalid_base64 = copy.deepcopy(valid)
        invalid_base64["raw_bytes_base64"] = "%%%"
        with self.assertRaises(broker.ProtocolError):
            broker.validate_stderr_binding(invalid_base64)

    def test_protocol_and_stderr_records_have_fixed_byte_bounds(self) -> None:
        maximum = broker.MAX_STDERR_RAW_BYTES
        raw = b"x" * maximum
        binding = broker.build_stderr_binding("logs/bounded.stderr", raw, True)
        self.assertEqual(binding["raw_byte_count"], maximum)
        with self.assertRaisesRegex(broker.ProtocolError, "byte-size bound"):
            broker.build_stderr_binding(
                "logs/oversized.stderr", raw + b"x", True
            )

        oversized_json = b'"' + b"x" * broker.MAX_PROTOCOL_JSON_BYTES + b'"'
        with self.assertRaisesRegex(broker.ProtocolError, "byte-size bound"):
            broker.load_plain_json(oversized_json)
        with self.assertRaisesRegex(broker.ProtocolError, "byte-size bound"):
            broker.canonical_json_bytes(
                {"payload": "x" * broker.MAX_PROTOCOL_JSON_BYTES}
            )

    def test_provider_receipt_is_bound_and_keeps_denial_separate_from_prevention(self) -> None:
        probe_receipt = self.passing_probe_receipt()
        launch_plan = broker.build_launch_plan(self.request, probe_receipt, self.frozen)
        receipt = self.build_provider_receipt(
            probe_receipt=probe_receipt,
            launch_plan=launch_plan,
            observed_denial=True,
            execution_prevented=False,
        )
        self.assertEqual(receipt["schema"], "sulde-native-provider-receipt-v1")
        self.assertTrue(receipt["observed_denial"])
        self.assertFalse(receipt["execution_prevented"])
        self.assertEqual(
            receipt["probe_run_identity_sha256"],
            probe_receipt["probe_run_identity_sha256"],
        )
        self.assertEqual(
            receipt["launch_identity_sha256"],
            launch_plan["launch_identity_sha256"],
        )
        self.assertEqual(
            broker.validate_provider_receipt(
                receipt, self.request, probe_receipt, launch_plan, self.frozen
            ),
            receipt,
        )

    def test_provider_receipt_rejects_binding_and_stderr_drift(self) -> None:
        probe_receipt = self.passing_probe_receipt()
        launch_plan = broker.build_launch_plan(self.request, probe_receipt, self.frozen)
        receipt = self.build_provider_receipt(
            probe_receipt=probe_receipt, launch_plan=launch_plan
        )
        mutations = (
            ("request_sha256", "0" * 64),
            ("permission_profile_name", "other"),
            ("permission_profile_bytes_sha256", "1" * 64),
            ("broker_generation", 99),
            ("broker_sha256", "2" * 64),
            ("provider_generation", 99),
            ("codex_version", "codex-cli 0.148.0"),
            ("installed_descriptor_sha256", sha(b"other descriptor")),
            ("runtime_generation", "rollback:generation"),
            ("runtime_tree_sha256", sha(b"other runtime")),
            ("agent_runtime_sha256", sha(b"other agent runtime")),
            ("permission_profile_spec_sha256", sha(b"other profile spec")),
            ("probe_run_identity_sha256", sha(b"other probe")),
            ("launch_identity_sha256", sha(b"other launch")),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                candidate = copy.deepcopy(receipt)
                candidate[field] = value
                with self.assertRaises(broker.ProtocolError):
                    broker.validate_provider_receipt(
                        candidate,
                        self.request,
                        probe_receipt,
                        launch_plan,
                        self.frozen,
                    )

        for field, value in (
            ("raw_byte_count", 0),
            ("sha256", "3" * 64),
            ("fsync_completed", False),
        ):
            with self.subTest(stderr_field=field):
                candidate = copy.deepcopy(receipt)
                candidate["stderr"][field] = value
                with self.assertRaises(broker.ProtocolError):
                    broker.validate_provider_receipt(
                        candidate,
                        self.request,
                        probe_receipt,
                        launch_plan,
                        self.frozen,
                    )

    def test_terminal_rejects_cross_request_profile_generation_and_launch(self) -> None:
        probe_receipt = self.passing_probe_receipt()
        launch_plan = broker.build_launch_plan(self.request, probe_receipt, self.frozen)
        for field, value in (
            ("nonce", sha(b"cross request nonce")),
            ("permission_profile_bytes_sha256", sha(b"cross profile")),
            ("provider_generation", 9),
        ):
            with self.subTest(field=field):
                other_frozen = copy.deepcopy(self.frozen)
                other_frozen[field] = value
                other_request = broker.build_request(other_frozen)
                with self.assertRaises(broker.ProtocolError):
                    broker.build_provider_receipt(
                        other_request,
                        probe_receipt,
                        launch_plan,
                        other_frozen,
                        **self.provider_kwargs(),
                    )

        other_receipt = broker.build_probe_receipt(
            self.request,
            self.frozen,
            self.passing_probe_results(),
            probe_run_id="probe-run-t15-other",
        )
        with self.assertRaises(broker.ProtocolError):
            broker.build_provider_receipt(
                self.request,
                other_receipt,
                launch_plan,
                self.frozen,
                **self.provider_kwargs(),
            )

    def test_non_success_terminal_receipt_requires_nonempty_fsynced_stderr(self) -> None:
        with self.assertRaisesRegex(broker.ProtocolError, "failed terminal"):
            self.build_provider_receipt(
                terminal_status="failed", exit_code=1, stderr_raw_bytes=b""
            )

        summary = copy.deepcopy(self.provider_kwargs()["jsonl_summary"])
        summary.update({"terminal_event": "none", "terminal_event_count": 0})
        with self.assertRaisesRegex(broker.ProtocolError, "failed terminal"):
            self.build_provider_receipt(
                terminal_status="interrupted",
                termination_domain="local_interruption",
                termination_reason="policy_paused",
                local_interruption_evidence=self.local_interruption_evidence(),
                exit_code=0,
                stderr_raw_bytes=b"",
                jsonl_summary=summary,
            )

    def test_provider_receipt_rejects_unknown_fields_and_bool_pid(self) -> None:
        with self.assertRaises(broker.ProtocolError):
            self.build_provider_receipt(provider_pid=True)

        receipt = self.build_provider_receipt()
        receipt["approval"] = "granted"
        with self.assertRaises(broker.ProtocolError):
            broker.validate_provider_receipt(
                receipt,
                self.request,
                self.passing_probe_receipt(),
                self.passing_launch_plan(),
                self.frozen,
            )

    def test_provider_receipt_rejects_invalid_time_and_does_not_alias_summaries(self) -> None:
        with self.assertRaises(broker.ProtocolError):
            self.build_provider_receipt(started_at="2026-99-20T10:00:00Z")

        kwargs = self.provider_kwargs()
        jsonl = kwargs["jsonl_summary"]
        output = kwargs["output_summary"]
        report = kwargs["report_summary"]
        receipt = self.build_provider_receipt(
            jsonl_summary=jsonl,
            output_summary=output,
            report_summary=report,
        )
        jsonl["line_count"] = 999
        output["raw_byte_count"] = 999
        report["raw_byte_count"] = 999
        self.assertEqual(receipt["jsonl_summary"]["line_count"], 5)
        self.assertEqual(receipt["output_summary"]["raw_byte_count"], 12)
        self.assertEqual(receipt["report_summary"]["raw_byte_count"], 12)

    def test_terminal_status_exit_code_and_single_jsonl_terminal_event_agree(self) -> None:
        cases = (
            ("succeeded", 0, "turn.failed", 1),
            ("failed", 1, "turn.completed", 1),
            ("interrupted", 143, "turn.completed", 1),
            ("succeeded", 0, "turn.completed", 0),
            ("succeeded", 0, "turn.completed", 2),
        )
        for status, code, event, event_count in cases:
            with self.subTest(status=status, event=event, count=event_count):
                summary = copy.deepcopy(self.provider_kwargs()["jsonl_summary"])
                summary["terminal_event"] = event
                summary["terminal_event_count"] = event_count
                with self.assertRaises(broker.ProtocolError):
                    self.build_provider_receipt(
                        terminal_status=status,
                        exit_code=code,
                        stderr_raw_bytes=(b"failure" if code else b"progress"),
                        jsonl_summary=summary,
                    )

        for status, event in (("failed", "turn.failed"),):
            with self.subTest(valid_status=status):
                summary = copy.deepcopy(self.provider_kwargs()["jsonl_summary"])
                summary["terminal_event"] = event
                receipt = self.build_provider_receipt(
                    terminal_status=status,
                    exit_code=1,
                    stderr_raw_bytes=b"failure",
                    jsonl_summary=summary,
                )
                self.assertEqual(receipt["jsonl_summary"]["terminal_event_count"], 1)

    def test_zero_provider_terminal_requires_complete_local_interruption_domain(self) -> None:
        summary = copy.deepcopy(self.provider_kwargs()["jsonl_summary"])
        summary["terminal_event"] = "none"
        summary["terminal_event_count"] = 0
        with self.assertRaisesRegex(broker.ProtocolError, "provider natural"):
            self.build_provider_receipt(jsonl_summary=summary)

        evidence = self.local_interruption_evidence()
        receipt = self.build_provider_receipt(
            terminal_status="interrupted",
            termination_domain="local_interruption",
            termination_reason="policy_paused",
            local_interruption_evidence=evidence,
            exit_code=0,
            stderr_raw_bytes=b"managed local interruption: paused\n",
            jsonl_summary=summary,
        )
        self.assertEqual(receipt["termination_domain"], "local_interruption")
        self.assertEqual(receipt["termination_reason"], "policy_paused")
        self.assertEqual(receipt["jsonl_summary"]["terminal_event_count"], 0)

    def test_local_interruption_reason_authority_is_exact_shared_and_immutable(self) -> None:
        self.assertEqual(
            dict(broker.LOCAL_INTERRUPTION_REASON_AUTHORITY),
            {
                "paused": "policy_paused",
                "correction_intervention": "policy_paused",
                "correction_store_integrity": "policy_paused",
                "awaiting_human": "awaiting_human",
                "external_effect_outcome_unknown": "awaiting_human",
                "timeout": "timeout",
                "monitor_error": "error",
                "unsettled_finalizer": "error",
            },
        )
        self.assertEqual(
            broker.local_interruption_stop_reason("external_effect_outcome_unknown"),
            "awaiting_human",
        )
        for value in ("", " ", "External_Effect_Outcome_Unknown", None, True, 1):
            with self.subTest(value=value):
                self.assertIsNone(broker.local_interruption_stop_reason(value))
        with self.assertRaises(TypeError):
            broker.LOCAL_INTERRUPTION_REASON_AUTHORITY["new"] = "error"

    def test_provider_receipt_rejects_dual_output_report_authority(self) -> None:
        changed = copy.deepcopy(self.provider_kwargs()["report_summary"])
        changed["sha256"] = sha(b"different")
        with self.assertRaisesRegex(broker.ProtocolError, "one byte authority"):
            self.build_provider_receipt(report_summary=changed)

    def test_local_interruption_rejects_missing_result_disposed_first_and_nonquiescence(self) -> None:
        summary = copy.deepcopy(self.provider_kwargs()["jsonl_summary"])
        summary.update({"terminal_event": "none", "terminal_event_count": 0})
        for mutation in (
            "missing-result",
            "disposed-first",
            "not-quiescent",
            "reason-mismatch",
        ):
            evidence = self.local_interruption_evidence()
            if mutation == "missing-result":
                evidence.pop("result_event_index")
            elif mutation == "disposed-first":
                evidence["disposed_event_index"] = 2
            else:
                if mutation == "not-quiescent":
                    evidence["quiescent"] = False
                else:
                    evidence["interrupt_reason"] = "timeout"
            with self.subTest(mutation=mutation), self.assertRaises(broker.ProtocolError):
                self.build_provider_receipt(
                    terminal_status="interrupted",
                    termination_domain="local_interruption",
                    termination_reason="policy_paused",
                    local_interruption_evidence=evidence,
                    exit_code=0,
                    stderr_raw_bytes=b"managed local interruption: paused\n",
                    jsonl_summary=summary,
                )

    def test_success_terminal_round_trips_digest_bound_zero_byte_stderr(self) -> None:
        probe_receipt = self.passing_probe_receipt()
        launch_plan = broker.build_launch_plan(self.request, probe_receipt, self.frozen)
        receipt = self.build_provider_receipt(
            probe_receipt=probe_receipt,
            launch_plan=launch_plan,
            stderr_raw_bytes=b"",
        )
        self.assertEqual(receipt["stderr"]["raw_bytes_base64"], "")
        self.assertEqual(receipt["stderr"]["raw_byte_count"], 0)
        self.assertEqual(receipt["stderr"]["sha256"], sha(b""))
        self.assertEqual(broker.stderr_binding_raw_bytes(receipt["stderr"]), b"")
        self.assertEqual(
            broker.validate_provider_receipt(
                receipt, self.request, probe_receipt, launch_plan, self.frozen
            ),
            receipt,
        )

        for field, value in (
            ("raw_bytes_base64", "AA=="),
            ("raw_bytes_base64", "%%%"),
            ("raw_byte_count", 1),
            ("sha256", sha(b"tampered")),
        ):
            with self.subTest(stderr_field=field, value=value):
                candidate = copy.deepcopy(receipt)
                candidate["stderr"][field] = value
                with self.assertRaises(broker.ProtocolError):
                    broker.validate_provider_receipt(
                        candidate,
                        self.request,
                        probe_receipt,
                        launch_plan,
                        self.frozen,
                    )

    def test_jsonl_terminal_requires_nonempty_physical_and_valid_counts(self) -> None:
        summary = copy.deepcopy(self.provider_kwargs()["jsonl_summary"])
        summary["line_count"] = 0
        summary["valid_json_line_count"] = 0
        with self.assertRaises(broker.ProtocolError):
            self.build_provider_receipt(jsonl_summary=summary)

    def test_jsonl_terminal_count_cannot_exceed_valid_json_count(self) -> None:
        summary = copy.deepcopy(self.provider_kwargs()["jsonl_summary"])
        summary["line_count"] = 1
        summary["valid_json_line_count"] = 0
        with self.assertRaises(broker.ProtocolError):
            self.build_provider_receipt(jsonl_summary=summary)

    def test_jsonl_terminal_count_cannot_exceed_total_line_count(self) -> None:
        summary = copy.deepcopy(self.provider_kwargs()["jsonl_summary"])
        summary["line_count"] = 0
        summary["valid_json_line_count"] = 0
        summary["terminal_event_count"] = 1
        with self.assertRaises(broker.ProtocolError):
            self.build_provider_receipt(jsonl_summary=summary)

    def test_non_json_lines_do_not_supply_the_jsonl_terminal_event(self) -> None:
        invalid = copy.deepcopy(self.provider_kwargs()["jsonl_summary"])
        invalid["line_count"] = 1
        invalid["valid_json_line_count"] = 0
        with self.assertRaises(broker.ProtocolError):
            self.build_provider_receipt(jsonl_summary=invalid)

        valid = copy.deepcopy(self.provider_kwargs()["jsonl_summary"])
        valid["line_count"] = 2
        valid["valid_json_line_count"] = 1
        receipt = self.build_provider_receipt(jsonl_summary=valid)
        self.assertEqual(receipt["jsonl_summary"]["terminal_event_count"], 1)


if __name__ == "__main__":
    unittest.main()
