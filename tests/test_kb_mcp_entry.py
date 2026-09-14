from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import venv


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts" / "kb" / "kb-mcp"
STATUS = ROOT / "scripts" / "kb" / "sulde-status.py"


def create_venv(home: Path) -> Path:
    venv.EnvBuilder(with_pip=False).create(home / "venv")
    return (
        home / "venv" / "Scripts" / "python.exe"
        if os.name == "nt"
        else home / "venv" / "bin" / "python"
    )


def minimal_environment(home: Path) -> dict[str, str]:
    empty_path = home / "empty-path"
    empty_path.mkdir(exist_ok=True)
    environment = {
        "PATH": str(empty_path),
        "PYTHONDONTWRITEBYTECODE": "1",
        "SULDE_KB_HOME": str(home),
    }
    for name in ("SYSTEMROOT", "WINDIR", "USERPROFILE", "HOME", "TEMP", "TMP"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


class KbMcpEntryTests(unittest.TestCase):
    def test_initialize_negotiates_only_the_implemented_protocol(self) -> None:
        server = runpy.run_path(str(ROOT / "tools" / "kb-mcp" / "server.py"))
        for version in ("2024-11-05", "2099-01-01"):
            with self.subTest(version=version):
                response = server["dispatch"]({
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": version},
                })
                self.assertEqual(response["result"]["protocolVersion"], "2024-11-05")
        response = server["dispatch"]({
            "jsonrpc": "2.0", "id": 2, "method": "initialize", "params": ["invalid"],
        })
        self.assertEqual(response["error"]["code"], -32602)

    def test_stdio_remains_utf8_with_an_ascii_parent_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "kb-home"
            home.mkdir()
            python = create_venv(home)
            environment = minimal_environment(home)
            environment["PYTHONIOENCODING"] = "ascii"
            requests = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2024-11-05"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "不存在的工具", "arguments": {}}},
                {"jsonrpc": "2.0", "id": 4, "method": "ping"},
            ]
            completed = subprocess.run(
                [str(python), str(ENTRY)],
                input="".join(json.dumps(row, ensure_ascii=False) + "\n" for row in requests),
                capture_output=True, text=True, encoding="utf-8", env=environment,
                timeout=20, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            responses = [json.loads(line) for line in completed.stdout.splitlines()]
            self.assertEqual([row["id"] for row in responses], [1, 2, 3, 4])
            self.assertEqual(len(responses[1]["result"]["tools"]), 8)
            self.assertIn("不存在的工具", responses[2]["result"]["content"][0]["text"])
            self.assertTrue(responses[2]["result"]["isError"])
            self.assertEqual(responses[3]["result"], {})

    def test_search_uses_persistent_in_process_backend_without_cli_spawn(self) -> None:
        server = runpy.run_path(str(ROOT / "tools" / "kb-mcp" / "server.py"))
        calls: list[tuple[str, int]] = []
        backend = SimpleNamespace(
            search_results=lambda query, **kwargs: calls.append(
                (query, kwargs["limit"])
            ) or [{"doc_id": "fixture"}]
        )
        globals_dict = server["kb_search"].__globals__
        with (
            mock.patch.dict(globals_dict, {"_direct_runtime": lambda _name: backend}),
            mock.patch.object(
                server["kb_cli"],
                "run_cli",
                side_effect=AssertionError("MCP search spawned the CLI backend"),
            ),
        ):
            first = server["kb_search"]({"query": "first", "top_k": 3})
            second = server["kb_search"]({"query": "second", "top_k": 4})
        self.assertEqual(calls, [("first", 3), ("second", 4)])
        self.assertFalse(first.get("isError", False))
        self.assertFalse(second.get("isError", False))

    def test_explicit_force_cli_preserves_recovery_fallback(self) -> None:
        server = runpy.run_path(str(ROOT / "tools" / "kb-mcp" / "server.py"))
        backend = SimpleNamespace(
            search_results=mock.Mock(side_effect=AssertionError("direct backend used"))
        )
        result = SimpleNamespace(
            ok=True,
            stdout='[{"doc_id":"fallback"}]',
            stderr="",
            detail="",
            status="ok",
            returncode=0,
        )
        globals_dict = server["kb_search"].__globals__
        with (
            mock.patch.dict(os.environ, {"SULDE_MCP_FORCE_CLI": "1"}),
            mock.patch.dict(globals_dict, {"_direct_runtime": lambda _name: backend}),
            mock.patch.object(server["kb_cli"], "run_cli", return_value=result) as run_cli,
        ):
            response = server["kb_search"]({"query": "fallback"})
        run_cli.assert_called_once()
        backend.search_results.assert_not_called()
        self.assertEqual(
            json.loads(response["content"][0]["text"])[0]["doc_id"],
            "fallback",
        )

    def test_kb_status_reads_bounded_snapshot_without_deep_subprocess(self) -> None:
        server = runpy.run_path(str(ROOT / "tools" / "kb-mcp" / "server.py"))
        snapshots = runpy.run_path(str(ROOT / "scripts" / "kb" / "sulde_status_snapshot.py"))
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "kb-home"
            self.assertTrue(
                snapshots["write_snapshot"](
                    home,
                    line="sulde \033[31m●\033[0m 交互未就绪:pre_execution_safety_clear",
                    healthy=False,
                )
            )
            with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}), mock.patch.object(
                server["subprocess"], "run", side_effect=AssertionError("deep scan")
            ):
                result = server["kb_status"]({})

        self.assertIsNot(result.get("isError"), True)
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload["schema"], "sulde-kb-status-readiness-v1")
        self.assertEqual(payload["authority"], "bounded_background_status_snapshot")
        self.assertEqual(payload["snapshot_status"], "fresh")
        self.assertEqual(payload["status"], "degraded")
        self.assertFalse(payload["ok"])

    def test_child_processes_use_the_kb_venv_interpreter(self) -> None:
        namespace = runpy.run_path(str(ENTRY))
        home = Path("fixture-kb-home")
        python = home / "venv" / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )

        class ExecCalled(Exception):
            pass

        cases = (
            (["--status"], STATUS, ["--json"], False),
            ([], ROOT / "tools" / "kb-mcp" / "server.py", [], True),
        )
        for arguments, target, target_arguments, unbuffered in cases:
            patches = (
                mock.patch.object(
                    namespace["os"], "execve", side_effect=ExecCalled
                )
                if os.name != "nt"
                else mock.patch.object(
                    namespace["subprocess"],
                    "run",
                    return_value=subprocess.CompletedProcess([], 0),
                )
            )
            with self.subTest(arguments=arguments), mock.patch.dict(
                os.environ, {"SULDE_KB_HOME": str(home)}
            ), mock.patch.object(
                namespace["kb_cli"], "resolve_venv_python", return_value=python
            ), patches as execute:
                if os.name != "nt":
                    with self.assertRaises(ExecCalled):
                        namespace["main"](arguments)
                else:
                    self.assertEqual(namespace["main"](arguments), 0)

            if os.name != "nt":
                executable, command, environment = execute.call_args.args
                self.assertEqual(executable, str(python))
            else:
                command = execute.call_args.args[0]
                environment = execute.call_args.kwargs["env"]
                self.assertIs(execute.call_args.kwargs["check"], False)
            self.assertEqual(command, [str(python), str(target), *target_arguments])
            self.assertEqual(environment.get("PYTHONUNBUFFERED") == "1", unbuffered)

    def test_print_home_preserves_output_and_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "kb-home"
            home.mkdir()
            completed = subprocess.run(
                [sys.executable, str(ENTRY), "--print-home"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=minimal_environment(home),
                timeout=20,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout, f"{home}\n")
            self.assertEqual(completed.stderr, "")

    def test_status_matches_direct_venv_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "kb-home"
            home.mkdir()
            python = create_venv(home)
            environment = minimal_environment(home)

            via_entry = subprocess.run(
                [sys.executable, str(ENTRY), "--status"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=20,
                check=False,
            )
            direct = subprocess.run(
                [str(python), str(STATUS), "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=20,
                check=False,
            )

            self.assertEqual(via_entry.returncode, direct.returncode, via_entry.stderr)
            via_status = json.loads(via_entry.stdout)
            direct_status = json.loads(direct.stdout)
            self.assertIn("checked_at", via_status)
            self.assertIn("checked_at", direct_status)
            via_status.pop("checked_at")
            direct_status.pop("checked_at")
            # Each independent collection has its own timestamp; compare every
            # factual field while checking the observation clock separately.
            via_collected = via_status["health_domains"]["synchronization"].pop("collected_at")
            direct_collected = direct_status["health_domains"]["synchronization"].pop("collected_at")
            self.assertRegex(via_collected, r"^\d{4}-\d{2}-\d{2}T")
            self.assertRegex(direct_collected, r"^\d{4}-\d{2}-\d{2}T")
            self.assertLessEqual(via_collected, direct_collected)
            self.assertEqual(via_status, direct_status)
            self.assertEqual(via_entry.stderr, direct.stderr)

    def test_minimal_environment_completes_initialize_handshake(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "kb-home"
            home.mkdir()
            python = create_venv(home)
            request = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05"},
                },
                separators=(",", ":"),
            )
            completed = subprocess.run(
                [str(python), str(ENTRY)],
                input=request + "\n",
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=minimal_environment(home),
                timeout=20,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            response = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(response["result"]["serverInfo"]["name"], "sulde-kb")

    def test_event_observe_is_read_only_redacted_and_declared(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "kb-home"
            approvals = home / "self-repair" / "approvals.jsonl"
            approvals.parent.mkdir(parents=True)
            approvals.write_text(
                json.dumps(
                    {
                        "slug": "repair-one",
                        "decision": "approve",
                        "by": "human",
                        "at": "2026-08-14T10:00:00+08:00",
                        "reason": "private approval rationale",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            before = approvals.read_bytes()
            python = create_venv(home)
            requests = [
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "event_observe",
                        "arguments": {
                            "domains": ["approval"],
                            "include_events": True,
                            "limit": 10,
                        },
                    },
                },
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "event_observe",
                        "arguments": {"domains": ["approval"]},
                    },
                },
            ]
            completed = subprocess.run(
                [str(python), str(ENTRY)],
                input="".join(json.dumps(request) + "\n" for request in requests),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=minimal_environment(home),
                timeout=20,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            responses = [json.loads(line) for line in completed.stdout.splitlines()]
            names = {tool["name"] for tool in responses[0]["result"]["tools"]}
            self.assertIn("event_observe", names)
            payload = json.loads(responses[1]["result"]["content"][0]["text"])
            self.assertEqual(payload["stateVersion"], 3)
            self.assertEqual(payload["asOfSeq"], 0)
            self.assertRegex(payload["sourceRevision"], r"^[0-9a-f]{64}$")
            self.assertEqual(payload["projectionCache"]["status"], "full_rebuild")
            self.assertEqual(payload["privacy"]["mode"], "local")
            self.assertFalse(payload["privacy"]["portableExportEnabled"])
            self.assertEqual(payload["summary"]["events_total"], 1)
            self.assertEqual(payload["events"][0]["domain"], "approval")
            summary_only = json.loads(responses[2]["result"]["content"][0]["text"])
            self.assertNotIn("events", summary_only)
            self.assertNotIn("sources", summary_only)
            self.assertEqual(summary_only["stateVersion"], 3)
            self.assertEqual(summary_only["projectionCache"]["status"], "hit")
            self.assertNotIn("private approval rationale", completed.stdout)
            self.assertEqual(approvals.read_bytes(), before)

    def test_event_observe_respects_disabled_privacy_without_reading_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "kb-home"
            source = home / "notify-log.jsonl"
            source.parent.mkdir(parents=True)
            source.write_text(
                json.dumps(
                    {
                        "ts": "2026-08-15T10:00:00+08:00",
                        "message": "private disabled message",
                        "cwd": "/private/customer",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            policy = home / "privacy" / "observation-policy.json"
            policy.parent.mkdir(parents=True)
            policy.write_text(
                json.dumps(
                    {
                        "schema": "sulde-observation-privacy-policy-v1",
                        "mode": "disabled",
                        "updatedAt": "2026-08-15T02:00:00Z",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            before = source.read_bytes()
            python = create_venv(home)
            request = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "event_observe",
                        "arguments": {"include_events": True},
                    },
                }
            )
            completed = subprocess.run(
                [str(python), str(ENTRY)],
                input=request + "\n",
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=minimal_environment(home),
                timeout=20,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            response = json.loads(completed.stdout.strip())
            payload = json.loads(response["result"]["content"][0]["text"])
            self.assertEqual(payload["privacy"]["mode"], "disabled")
            self.assertFalse(payload["privacy"]["observationEnabled"])
            self.assertIsNone(payload["summary"]["events_total"])
            self.assertEqual(payload["events"], [])
            self.assertEqual(payload["projectionCache"]["status"], "privacy_disabled")
            self.assertEqual(source.read_bytes(), before)
            self.assertNotIn("private disabled message", completed.stdout)


if __name__ == "__main__":
    unittest.main()
