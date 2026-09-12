"""Candidate artifact -> actual Codex CLI -> actual MCP/exec/Hook observations.

Only the response-model endpoint is a deterministic loopback fixture. No test
feeds proof records to Guardian or invokes a Hook as a substitute for the host.
"""
import hashlib
import http.server
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/release"))
import candidate_codex_plugin as candidate
import native_pretool_canary as native


def response_handler(owner):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 8 * 1024 * 1024:
                self.send_error(413)
                return
            request = json.loads(self.rfile.read(size))
            # Only disposable fixture failures are categorized; never retain
            # a prompt, full result or session-start context.
            for entry in request.get("input", []):
                if isinstance(entry, dict) and entry.get("type") == "function_call_output":
                    output = str(entry.get("output", ""))
                    markers = [word for word in ("unsupported", "approval", "denied", "not found", "failed", "invalid", "exit code")
                               if word in output.lower()]
                    if markers:
                        print("NATIVE_FIXTURE_OUTPUT_CATEGORY=" + json.dumps({"call_id": entry.get("call_id"), "markers": markers}), flush=True)
            number = len(owner.calls)
            callback = getattr(owner, "before_calls", {}).pop(number, None)
            if callback:
                try:
                    callback()
                except Exception as error:
                    owner.fixture_error = error
                    self.send_error(422, "native fixture precondition failed")
                    return
            owner.calls.append(self.path)
            if number < len(owner.commands):
                command = owner.commands[number]
                namespace = None
                if isinstance(command, str):
                    name, arguments = "exec_command", {"cmd": command, "workdir": str(owner.workspace), "yield_time_ms": 1000}
                elif "cmd" in command:
                    name, arguments = "exec_command", command
                else:
                    matches = []
                    for tool in request.get("tools", []):
                        if tool.get("type") == "namespace" and "sulde" in tool.get("name", ""):
                            matches.extend((tool["name"], child["name"]) for child in tool.get("tools", [])
                                           if child.get("name") == "memory_annotate")
                        elif str(tool.get("name", "")).endswith("memory_annotate") and "sulde" in str(tool.get("name")):
                            matches.append((None, tool["name"]))
                    if len(matches) != 1:
                        metadata = [{"type": tool.get("type"), "name": tool.get("name"),
                                     "children": [child.get("name") for child in tool.get("tools", [])]}
                                    for tool in request.get("tools", [])]
                        # Tool declarations are fixture metadata, not prompts or tool outputs.
                        print("NATIVE_MEMORY_TOOL_DECLARATIONS=" + json.dumps(metadata), flush=True)
                        self.send_error(422, "candidate memory tool discovery failed")
                        return
                    (namespace, name), arguments = matches[0], command
                item = {"type": "function_call", "name": name, "id": f"fc_{number}",
                        "call_id": f"memory_native_{number}", "arguments": json.dumps(arguments)}
                if namespace:
                    item["namespace"] = namespace
            elif number == len(owner.commands):
                item = {"type": "message", "id": "done", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": "Complete.", "annotations": []}]}
            else:
                self.send_error(429)
                return
            response = {"id": f"resp_{number}", "status": "completed", "output": [item],
                        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}
            events = [{"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
                      {"type": "response.output_item.added", "output_index": 0, "item": item},
                      {"type": "response.output_item.done", "output_index": 0, "item": item},
                      {"type": "response.completed", "response": response}]
            raw = "".join("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n" for event in events).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    return Handler


@unittest.skipIf(os.name == "nt", "Windows native acceptance is Windows-owned")
@unittest.skipUnless(shutil.which("codex"), "actual Codex CLI required")
class NativeMemoryConsistencyTests(unittest.TestCase):
    def test_candidate_native_ten_annotations_and_attribution_denial(self):
        self.run_scenario(drop_post=False)

    def test_candidate_native_missing_post_recovers_without_reexecuting(self):
        self.run_scenario(drop_post=True)

    def run_scenario(self, *, drop_post):
        externally_isolated = bool(os.environ.get("SULDE_ISOLATED_TEST_RUN_ID"))
        with tempfile.TemporaryDirectory(prefix="sulde-memory-consistency-native-") as temporary:
            slot = Path(temporary).resolve()
            installer = candidate.installer
            codex = shutil.which("codex")
            prepared = installer._stage_artifact(slot / "artifact", platform="posix", runner=installer.run_command)
            generation = prepared.descriptor["delivery_generation"]
            env = candidate._candidate_environment(slot, codex, candidate._python_identity(Path(sys.executable)))
            runner = candidate._bound_runner(env)
            with candidate._process_environment(env):
                installed = installer._registry_add(codex, prepared.marketplace, runner,
                    expected_version=generation["plugin_version"])
                kb = Path(env["SULDE_KB_HOME"])
                installer._install_launchers(installed, kb, runner, platform="posix")
                installer._smoke_installed(installed, kb, codex=codex,
                    expected_tree_sha256=prepared.plugin_tree_sha256, runner=runner)
                # Production uses the stable standalone MCP registration too;
                # plugin Hook discovery alone does not register MCP tools.
                runner([codex, "mcp", "add", "sulde_kb", "--env", "SULDE_HOME=" + env["SULDE_HOME"],
                    "--env", "SULDE_KB_HOME=" + env["SULDE_KB_HOME"], "--", str(Path(env["SULDE_HOME"]) / "bin/sulde-kb-mcp")])
                # Fixture authority covers only this local, disposable writer.
                # Guardian remains enabled and independently checks attribution.
                config = Path(env["CODEX_HOME"]) / "config.toml"
                with config.open("a", encoding="utf-8") as output:
                    output.write('\n[mcp_servers.sulde_kb.tools.memory_annotate]\napproval_mode = "approve"\n')
                workspace = slot / "isolated/workspace"
                host = native.NativeCanary(codex, workspace, env,
                    externally_isolated=externally_isolated)
                real_server = http.server.ThreadingHTTPServer
                def model_server(address, _handler):
                    return real_server(address, response_handler(host))
                with mock.patch.object(native.http.server, "ThreadingHTTPServer", side_effect=model_server), host.start():
                    contract, _ = candidate._activate_candidate_enforce_contract(
                        Path(env["SULDE_HOME"]) / "bin/intent-guardian", kb_home=kb, workspace=workspace,
                        session=host.session, environment=env, runner=runner)
                    payload = {"entities": [{"name": "NativeA", "type": "component"}, {"name": "NativeB", "type": "risk"}],
                        "edges": [{"src": "NativeA", "rel": "avoids", "dst": "NativeB"}], "extracted_by": "codex"}
                    if drop_post:
                        inventory = host.rpc("hooks/list", {"cwds": [str(workspace)]})
                        post = [hook for entry in inventory["data"] for hook in entry.get("hooks", [])
                                if hook.get("pluginId") == "sulde@sulde-local" and hook.get("eventName") == "postToolUse"]
                        self.assertEqual(len(post), 1)
                        # Deliberate callback loss in this disposable host only.
                        # Actual PreTool, writer and Stop verifier still execute.
                        host.rpc("config/batchWrite", {"edits": [{"keyPath": "hooks.state." + json.dumps(post[0]["key"]) + ".enabled",
                            "value": False, "mergeStrategy": "replace"}], "filePath": str(config)})
                        inventory = host.rpc("hooks/list", {"cwds": [str(workspace)]})
                        self.assertFalse(next(hook["enabled"] for entry in inventory["data"] for hook in entry.get("hooks", [])
                                              if hook.get("key") == post[0]["key"]))
                        # A running thread retains its compiled Hook settings.
                        # Start another real thread so the missing callback is
                        # an actual delivery gap, not a fabricated audit record.
                        fresh = host.rpc("thread/start", {"cwd": str(workspace), "approvalPolicy": "never",
                            "sandbox": "danger-full-access" if externally_isolated else "workspace-write"})
                        host.session = fresh["thread"]["id"]
                        contract, _ = candidate._activate_candidate_enforce_contract(
                            Path(env["SULDE_HOME"]) / "bin/intent-guardian", kb_home=kb, workspace=workspace,
                            session=host.session, environment=env, runner=runner)
                        host.execute([payload])
                    else:
                        host.execute(["touch " + shlex.quote(str(workspace / "allowed.txt")), *[payload for _ in range(10)], {**payload, "extracted_by": "claude"}])
                    self.assertTrue(drop_post or (workspace / "allowed.txt").is_file(), json.dumps({
                        "commands": [{key: row.get("params", {}).get("item", {}).get(key)
                                      for key in ("type", "status", "exitCode", "aggregatedOutput")}
                                     for row in host.notifications if row.get("method") == "item/completed"],
                        "hooks": [{key: row["params"]["run"].get(key) for key in ("eventName", "status")}
                                  for row in host.notifications if row.get("method") == "hook/completed"],
                    }, default=str)[-12000:])
                    hook_denials = [row["params"]["run"] for row in host.notifications
                        if row.get("method") == "hook/completed" and row["params"]["run"].get("eventName") == "preToolUse"
                        and row["params"]["run"].get("status") == "blocked"]
                    self.assertEqual(len(hook_denials), 0 if drop_post else 1)
                    if not drop_post:
                        self.assertTrue(hook_denials[0]["id"].endswith(":memory_native_11"))
                # Independent reads, not host success strings, establish storage.
                with sqlite3.connect((kb / "memory.db").as_uri() + "?mode=ro", uri=True) as db:
                    self.assertEqual(db.execute("SELECT count(*) FROM mem_edges").fetchone()[0], 1)
                    self.assertEqual(db.execute("SELECT count(*) FROM mem_annotation_receipts").fetchone()[0], 1)
                    self.assertEqual(db.execute("SELECT extracted_by FROM mem_edges").fetchone()[0], "codex")
                active = json.loads(contract.read_text())
                self.assertEqual(active["runtime"]["pending_verifications"], [])
                self.assertEqual(active["runtime"]["open_events"], [])
                if drop_post:
                    self.assertEqual(len(active["runtime"]["verified_effects"]), 1)
                    # Fresh candidate CLI process, two independent recovery
                    # passes: the writer is never called again.
                    for _ in range(2):
                        result = candidate._parse_json_result(runner([
                            str(Path(env["SULDE_HOME"]) / "bin/intent-guardian"), "reconcile-verifications",
                            "--contract", str(contract), "--home", str(kb)], environment=env), label="independent recovery")
                        self.assertEqual(result["reconciled_count"], 0)
                        self.assertEqual(result["pending_verifications"], 0)
                audit = contract.with_suffix(".events.jsonl")
                # Resolve through the candidate's own stable audit layout.
                from intent_guardian_parts.state import audit_path
                audit = audit_path(contract)
                rows = [json.loads(line) for line in audit.read_text().splitlines()]
                actual = [row["event"] for row in rows if isinstance(row.get("event"), dict)
                          and row["event"].get("capability", "").endswith(":memory_annotate")]
                starts = [event for event in actual if event.get("phase") == "started"]
                self.assertEqual(len(starts), 1 if drop_post else 11)
                if drop_post:
                    self.assertFalse([event for event in actual if event.get("phase") == "completed"], "fault injection did not lose PostToolUse")
                    self.assertTrue(any(row.get("schema") == "sulde-guardian-turn-finalize-v1" for row in rows))
                self.assertEqual({event["artifact_generation"] for event in starts}, {generation["generation"]})
                self.assertEqual(len({event["loaded_module_generation"] for event in starts}), 1)
                self.assertTrue(all(event["loaded_module_generation"] for event in starts))
                evidence = {"schema": "guardian-native-memory-v1", "transport": "codex-cli-app-server",
                    "artifact_generation": generation["generation"],
                    "loaded_module_generation": starts[0]["loaded_module_generation"],
                    "annotations": 1 if drop_post else 10, "pretool_attribution_denials": 0 if drop_post else 1,
                    "post_callback_deliberately_lost": drop_post, "fresh_cli_reconciliations": 2 if drop_post else 0,
                    "pending": 0, "audit_sha256": hashlib.sha256(audit.read_bytes()).hexdigest()}
                print("NATIVE_MEMORY_EVIDENCE=" + json.dumps(evidence, sort_keys=True), flush=True)
