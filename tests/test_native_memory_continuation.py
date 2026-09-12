"""Real native approval transport; exact disposable fixture decisions only.

The harness supplies the simulated human's one-shot answer, not a production
approval. CLI, Pre/Permission/Post Hooks, writer and CAS application are real.
No receipt, event, contract authority or proof is manually injected.
"""
from contextlib import contextmanager
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

from tests.test_native_memory_consistency import candidate, native, response_handler


class ExactApprovalHost(native.NativeCanary):
    expected_approval = None

    def receive(self):
        value = super().receive()
        if "id" not in value or "method" not in value:
            return value
        expected = self.expected_approval
        params = value.get("params", {})
        command = shlex.split(params.get("command", ""))
        matches = command == expected["argv"] if expected else False
        if expected and len(command) == 3 and Path(command[0]).name in {"zsh", "bash", "sh"} and command[1] in {"-c", "-lc"}:
            matches = shlex.split(command[2]) == expected["argv"]
        if not (expected and value["method"] == "item/commandExecution/requestApproval"
                and params.get("threadId") == self.session and matches
                and params.get("reason") == expected["description"]
                and Path(params.get("cwd", "")).resolve() == self.workspace.resolve()):
            raise native.NativeCanaryError("unexpected approval; fixture cannot grant authority: " + json.dumps({
                "method": value.get("method"), "keys": list(params), "command_matches": matches,
                "reason_matches": bool(expected and params.get("reason") == expected["description"])}))
        self.expected_approval = None
        self.approval_count = getattr(self, "approval_count", 0) + 1
        self.send({"id": value["id"], "result": {"decision": expected["decision"]}})
        return self.receive()

    def approval_command(self, preview, *, decision="accept"):
        if self.expected_approval is not None:
            raise native.NativeCanaryError("fixture approval already pending")
        self.expected_approval = {"argv": preview["command_argv"], "description": preview["description"], "decision": decision}
        return {"cmd": shlex.join(preview["command_argv"]), "workdir": str(self.workspace),
                "yield_time_ms": 1000, "sandbox_permissions": "require_escalated",
                "justification": preview["description"]}

    def run_more(self, commands):
        try:
            return self.execute(["already consumed"] * len(self.calls) + commands)
        except native.NativeCanaryError:
            if getattr(self, "fixture_error", None) is not None:
                raise self.fixture_error
            raise


@contextmanager
def model_host(codex, workspace, env, *, externally_isolated):
    host = ExactApprovalHost(codex, workspace, env, externally_isolated=externally_isolated)
    server = http.server.ThreadingHTTPServer
    # Capture the original server before entering either nested fixture.
    factory = getattr(server, "_native_original", server)
    def model_server(address, _handler):
        return factory(address, response_handler(host))
    model_server._native_original = factory
    with mock.patch.object(native.http.server, "ThreadingHTTPServer", model_server), host.start():
        fresh = host.rpc("thread/start", {"cwd": str(workspace), "approvalPolicy": "on-request", "sandbox": "workspace-write"})
        host.session = fresh["thread"]["id"]
        yield host


@unittest.skipIf(os.name == "nt", "Windows native acceptance is Windows-owned")
@unittest.skipUnless(shutil.which("codex"), "actual Codex CLI required")
class NativeMemoryContinuationTests(unittest.TestCase):
    def test_native_independent_continuation_survives_other_session_memory(self):
        self.run_case(deny=False)

    def test_native_deny_keeps_independent_session_and_source_unchanged(self):
        self.run_case(deny=True)

    def run_case(self, *, deny):
        externally_isolated = bool(os.environ.get("SULDE_ISOLATED_TEST_RUN_ID"))
        with tempfile.TemporaryDirectory(prefix="sulde-memory-consistency-approval-") as temporary:
            slot, codex = Path(temporary).resolve(), shutil.which("codex")
            installer = candidate.installer
            staged = installer._stage_artifact(slot / "artifact", platform="posix", runner=installer.run_command)
            generation = staged.descriptor["delivery_generation"]
            env = candidate._candidate_environment(slot, codex, candidate._python_identity(Path(sys.executable)))
            runner = candidate._bound_runner(env)
            with candidate._process_environment(env):
                installed = installer._registry_add(codex, staged.marketplace, runner, expected_version=generation["plugin_version"])
                kb = Path(env["SULDE_KB_HOME"])
                installer._install_launchers(installed, kb, runner, platform="posix")
                installer._smoke_installed(installed, kb, codex=codex, expected_tree_sha256=staged.plugin_tree_sha256, runner=runner)
                guardian = Path(env["SULDE_HOME"]) / "bin/intent-guardian"
                runner([codex, "mcp", "add", "sulde_kb", "--env", "SULDE_HOME=" + env["SULDE_HOME"],
                        "--env", "SULDE_KB_HOME=" + env["SULDE_KB_HOME"], "--", str(guardian.parent / "sulde-kb-mcp")])
                with (Path(env["CODEX_HOME"]) / "config.toml").open("a", encoding="utf-8") as output:
                    output.write('\n[mcp_servers.sulde_kb.tools.memory_annotate]\napproval_mode = "approve"\n')
                # Two actual hosts share the task/KB, not host configuration.
                # Keep independent plugin registries and loopback providers.
                target_env = {**env, "CODEX_HOME": str(slot / "isolated/codex-target-home")}
                Path(target_env["CODEX_HOME"]).mkdir()
                target_runner = candidate._bound_runner(target_env)
                with candidate._process_environment(target_env):
                    installer._registry_add(codex, staged.marketplace, target_runner, expected_version=generation["plugin_version"])
                workspace = slot / "isolated/workspace"
                with model_host(codex, workspace, env, externally_isolated=externally_isolated) as source:
                    contract, _ = candidate._activate_candidate_enforce_contract(guardian, kb_home=kb,
                        workspace=workspace, session=source.session, environment=env, runner=runner)
                    def control(host, action, *arguments):
                        binding = [str(contract)] if action == "propose-revision" else ["--contract", str(contract)]
                        return candidate._parse_json_result(runner([str(guardian), action, *arguments,
                            *binding, "--provider", "codex", "--session-id", host.session],
                            environment={**env, "CODEX_THREAD_ID": host.session}, timeout=30), label=action)
                    control(source, "propose-revision", "--objective", "Write an isolated report independent of optional memory",
                        "--accept", "report completed without borrowing memory authority", "--allow-path", "allowed.txt",
                        "--mode", "enforce", "--memory-dependency", "independent", "--decision-route", "human",
                        "--intent-kind", "deterministic", "--risk", "low", "--effect", "local_write",
                        "--reversibility", "reversible", "--cost", "none", "--rollback", "discard isolated fixture")
                    first = control(source, "native-decision-preview", "proposal", "--decision", "approve", "--target", "current")
                    source.run_more([source.approval_command(first)])
                    state = json.loads(contract.read_text())
                    self.assertEqual(getattr(source, "approval_count", 0), 1)
                    self.assertEqual(state["constraints"]["memory_dependency"], "independent")
                    self.assertEqual(state["confirmed_by"], "human-readable-proposal-approval")
                    self.assertEqual(state["continuation"]["grants"], [])
                    checkpoint = {}
                    with model_host(codex, workspace, target_env, externally_isolated=externally_isolated) as target:
                        def prepare_then_memory():
                            observed = json.loads(contract.read_text())
                            target_lanes = [row for row in observed["runtime"]["task_lanes"] if row["session_id"] == target.session]
                            session_contracts = [(path, json.loads(path.read_text())) for path in kb.glob("intent/sessions/*.active.json")]
                            owned = [(path, value) for path, value in session_contracts if any(row["session_id"] == target.session
                                     for row in value["runtime"]["task_lanes"])]
                            print("CONTINUATION_DISCOVERY_EVIDENCE=" + json.dumps({
                                "artifact_generation": generation["generation"], "native_proposal_approvals": source.approval_count,
                                "source_memory_dependency": observed["constraints"]["memory_dependency"],
                                "target_lanes_in_source": len(target_lanes), "target_owned_contracts": len(owned),
                                "separate_contract": bool(owned and owned[0][0] != contract),
                                "hooks": [{key: row["params"]["run"].get(key) for key in ("eventName", "status")}
                                    for row in target.notifications if row.get("method") == "hook/completed"]}), flush=True)
                            self.assertEqual(target_lanes, [], "default new-session isolation must remain")
                            self.assertEqual(len(owned), 1)
                            current = owned[0][0]
                            def current_control(action, *arguments):
                                return candidate._parse_json_result(target_runner([str(guardian), action, *arguments,
                                    "--contract", str(current), "--provider", "codex", "--session-id", target.session],
                                    environment={**target_env, "CODEX_THREAD_ID": target.session}, timeout=30), label=action)
                            selected = current_control("prepare-task-continuation", str(contract))
                            self.assertEqual(selected["status"], "review_required")
                            self.assertFalse(selected["authority_transferred"])
                            preview = current_control("native-decision-preview", "task-continuation", "--decision", "approve", "--target", "current")
                            before = json.loads(contract.read_text())
                            source.run_more([{"entities": [{"name": "ContinuationA", "type": "component"},
                                {"name": "ContinuationB", "type": "risk"}], "edges": [
                                {"src": "ContinuationA", "rel": "avoids", "dst": "ContinuationB"}], "extracted_by": "codex"}])
                            after = json.loads(contract.read_text())
                            self.assertEqual(after["runtime"]["material_sequence"], before["runtime"]["material_sequence"] + 1)
                            self.assertEqual(after["runtime"]["memory_material_sequence"], before["runtime"].get("memory_material_sequence", 0) + 1)
                            checkpoint.update({"preview_target": preview["target"], "before": before, "after": after,
                                "current": current, "current_control": current_control})
                            target.commands[0] = target.approval_command(preview, decision="decline" if deny else "accept")
                        target.before_calls = {0: prepare_then_memory}
                        target.run_more(["replaced after actual UserPromptSubmit"])
                        if deny:
                            denied = json.loads(contract.read_text())
                            self.assertFalse(any(row["session_id"] == target.session for row in denied["runtime"]["task_lanes"]))
                            self.assertFalse(json.loads(checkpoint["current"].read_text()).get("task_continuation_transaction"))
                            mappings = [json.loads(path.read_text()) for path in kb.glob("intent/sessions/*.workspace.json")]
                            mapped = next(row for row in mappings if row["session_id"] == target.session)
                            self.assertEqual(mapped["contract_path"], str(checkpoint["current"]))
                            self.assertEqual(target.approval_count, 1)
                            print("NATIVE_CONTINUATION_DENY_EVIDENCE=" + json.dumps({
                                "transport": "codex-cli-app-server", "human_input": "exact one-shot fixture decline",
                                "artifact_generation": generation["generation"], "authority_transferred": False,
                                "source_lane_created": False, "route_unchanged": True}), flush=True)
                            return
                        final = json.loads(contract.read_text())
                        self.assertEqual(getattr(target, "approval_count", 0), 1)
                        continuations = final["runtime"]["task_continuations"]
                        self.assertEqual(len(continuations), 1)
                        self.assertEqual(continuations[0]["target"], checkpoint["preview_target"])
                        self.assertEqual(continuations[0]["session_id"], target.session)
                        self.assertFalse(continuations[0]["authority_transferred"])
                        lane = next(row for row in final["runtime"]["task_lanes"] if row["session_id"] == target.session)
                        self.assertEqual(lane["state"], "bound")
                        self.assertEqual(final["runtime"]["open_events"], [])
                        self.assertEqual(final["runtime"]["pending_verifications"], [])
                        self.assertEqual(final["runtime"]["authorized_events"], [])
                        self.assertTrue(all(row.get("session_id") != target.session for row in final["runtime"]["continuation_uses"]))
                        # Actual post-continuation execution and exact destructive
                        # negative, not a manually injected Guardian event.
                        if externally_isolated:
                            # The repository runner already owns the OS sandbox.
                            # Ordinary commands cannot nest a second macOS sandbox;
                            # native approval above deliberately used workspace-write.
                            original_rpc = target.rpc
                            def isolated_tool_rpc(method, params):
                                if method == "turn/start":
                                    params = {**params, "sandboxPolicy": {"type": "dangerFullAccess"}}
                                return original_rpc(method, params)
                            target.rpc = isolated_tool_rpc
                        marker = workspace / "allowed.txt"
                        target.run_more(["printf continued > " + shlex.quote(str(marker))])
                        from intent_guardian_parts.state import audit_path as source_audit_path
                        observed_rows = [json.loads(line) for line in source_audit_path(contract).read_text().splitlines()]
                        print("CONTINUATION_EXECUTION_DIAGNOSTIC=" + json.dumps({
                            "marker_before_negative": marker.exists(),
                            "lanes": [{k: row.get(k) for k in ("state", "source", "task_epoch", "task_instance_id")}
                                for row in json.loads(contract.read_text())["runtime"]["task_lanes"] if row["session_id"] == target.session],
                            "events": [{"phase": row.get("event", {}).get("phase"), "effect": row.get("event", {}).get("effect"),
                                "call_id": row.get("event", {}).get("call_id"), "decision": row.get("decision", {}).get("action"),
                                "reason_code": row.get("decision", {}).get("reason_code")} for row in observed_rows
                                if row.get("event", {}).get("session_id") == target.session],
                            "hooks": [{k: row["params"]["run"].get(k) for k in ("eventName", "status")}
                                for row in target.notifications if row.get("method") == "hook/completed"]}), flush=True)
                        self.assertEqual(marker.read_text(), "continued")
                        target.run_more(["rm -r -- " + shlex.quote(str(marker))])
                        self.assertEqual(marker.read_text(), "continued")
                        for host, expected_permissions in ((source, 1), (target, 1)):
                            permissions = [row["params"]["run"] for row in host.notifications if row.get("method") == "hook/completed"
                                           and row["params"]["run"].get("eventName") == "permissionRequest"]
                            self.assertEqual(len(permissions), expected_permissions)
                            self.assertTrue(all(row["status"] == "completed" for row in permissions))
                    with sqlite3.connect((kb / "memory.db").as_uri() + "?mode=ro", uri=True) as db:
                        self.assertEqual(db.execute("SELECT count(*) FROM mem_annotation_receipts").fetchone()[0], 1)
                    from intent_guardian_parts.state import audit_path
                    audit = audit_path(contract)
                    events = [json.loads(line).get("event", {}) for line in audit.read_text().splitlines()]
                    memory_starts = [event for event in events if isinstance(event, dict) and event.get("phase") == "started"
                                     and event.get("capability", "").endswith(":memory_annotate")]
                    self.assertEqual(len(memory_starts), 1)
                    self.assertEqual(memory_starts[0]["artifact_generation"], generation["generation"])
                    denials = [json.loads(line) for line in audit.read_text().splitlines()
                        if json.loads(line).get("decision", {}).get("action") == "deny"]
                    self.assertTrue(any(row.get("event", {}).get("session_id") == target.session
                        and row.get("event", {}).get("phase") == "started"
                        and row.get("event", {}).get("artifact_generation") == generation["generation"]
                        and row.get("event", {}).get("loaded_module_generation") == memory_starts[0]["loaded_module_generation"]
                        for row in denials), "real target-session Pre denial must bind both runtime identities")
                    print("NATIVE_MEMORY_CONTINUATION_EVIDENCE=" + json.dumps({
                        "transport": "codex-cli-app-server", "human_input": "exact one-shot fixture accept, not a production click",
                        "artifact_generation": generation["generation"], "loaded_module_generation": memory_starts[0]["loaded_module_generation"],
                        "native_approvals": 2, "other_session_memory_after_preview": 1,
                        "post_continuation_write": "verified", "destructive_marker_preserved": True, "authority_transferred": False,
                        "audit_sha256": hashlib.sha256(audit.read_bytes()).hexdigest()}, sort_keys=True), flush=True)
