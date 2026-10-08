"""Real host approval protocol in an isolated home; never human authority.

The client replies below are synthetic test decisions. This is not a production
bootstrap implementation and does not transfer a parent Guardian receipt.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
import time
import unittest

from tests.test_m1_host_migration import Host, candidate


# Test-only bounded worker. No shell, installer, signals or production paths.
WORKER = '''import hashlib, json, os, pathlib, sys, time
plan_path = pathlib.Path(sys.argv[1])
raw = plan_path.read_bytes()
if hashlib.sha256(raw).hexdigest() != sys.argv[2]:
    raise SystemExit(65)
plan = json.loads(raw)
root = plan_path.parent.resolve()
if plan["deadline"] < time.time() or plan["schema"] != "fixture-maintenance-v1":
    raise SystemExit(65)
current = root / "current.json"
if hashlib.sha256(current.read_bytes()).hexdigest() != plan["old_sha256"]:
    raise SystemExit(65)
fd = os.open(root / "effect.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as output:
    json.dump({"fixture_only": True, "nonce": plan["nonce"], "plan_sha256": sys.argv[2]}, output)
    output.flush()
    os.fsync(output.fileno())
print("fixture-effect-once")
'''


@unittest.skipUnless(os.environ.get("SULDE_ISOLATED_TEST_RUN_ID"), "requires official OS-isolated runner")
@unittest.skipIf(os.name == "nt", "POSIX bootstrap protocol only")
class MaintenanceBootstrapHostTests(unittest.TestCase):
    def assert_command(self, host, rendered):
        # The native request shows the actual shell argv, not the raw tool cmd.
        # Keep exact inner bytes; never compare by substring or drop extra args.
        argv = shlex.split(rendered)
        self.assertEqual(len(argv), 3)
        self.assertIn(argv[0], ("/bin/zsh", "/bin/bash", "/bin/sh"))
        self.assertEqual(argv[1], "-lc")
        self.assertEqual(argv[2], host.tool_arguments["cmd"])

    def observe(self, phase, data):
        print("BOOTSTRAP_OBSERVATION=" + json.dumps({"case": self.id(), "phase": phase,
            "data": data, "authority": "fixture-decision-not-human"}, sort_keys=True), flush=True)

    def fixture(self, stack):
        slot = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="sulde-bootstrap-"))).resolve()
        codex = shutil.which("codex")
        self.assertIsNotNone(codex)
        env = candidate._candidate_environment(slot, codex, candidate._python_identity(Path(sys.executable)))
        workspace = Path(env["CODEX_HOME"]).parent / "workspace"
        # No copied auth, rules, plugin config, contract or parent session.
        for key in ("CODEX_THREAD_ID", "SULDE_INTENT_CONTRACT", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            self.assertNotIn(key, env)
        current = workspace / "current.json"
        current.write_text('{"generation":"fixture-old"}', encoding="utf-8")
        plan = workspace / "plan.json"
        plan.write_text(json.dumps({"schema": "fixture-maintenance-v1", "nonce": slot.name,
            "deadline": time.time() + 120, "old_sha256": hashlib.sha256(current.read_bytes()).hexdigest()}),
            encoding="utf-8")
        worker = workspace / "worker.py"
        worker.write_text(WORKER, encoding="utf-8")
        plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
        # The executable command embeds the worker digest as well as plan digest.
        # An approval preview alone does not hash script bytes.
        check = ('import hashlib, pathlib, runpy, sys; p=pathlib.Path(sys.argv[1]); '
                 'assert hashlib.sha256(p.read_bytes()).hexdigest()==sys.argv.pop(2); '
                 'sys.argv=sys.argv[1:]; runpy.run_path(str(p), run_name="__main__")')
        argv = [sys.executable, "-B", "-I", "-c", check, str(worker),
                hashlib.sha256(worker.read_bytes()).hexdigest(), str(plan), plan_sha]
        command = shlex.join(argv)
        host = stack.enter_context(Host(codex, workspace, env, externally_isolated=True).start())
        inventory = host.rpc("hooks/list", {"cwds": [str(workspace)]})
        self.assertEqual([h for row in inventory.get("data", []) for h in row.get("hooks", [])], [])
        started = host.rpc("thread/start", {"cwd": str(workspace),
            "approvalPolicy": "on-request", "sandbox": "read-only"})
        host.session = started["thread"]["id"]
        self.assertEqual(started["approvalPolicy"], "on-request")
        self.assertEqual(started["sandbox"]["type"], "readOnly")
        host.tool_arguments = {"cmd": command, "workdir": str(workspace), "yield_time_ms": 1000,
            "sandbox_permissions": "require_escalated",
            "justification": "Isolated fixture only: execute this digest-bound worker once."}
        self.observe("host", {"pid": host.process.pid, "session": host.session,
            "codex": str(Path(codex).resolve()), "codex_sha256": hashlib.sha256(Path(codex).resolve().read_bytes()).hexdigest(),
            "approvalPolicy": started["approvalPolicy"], "sandbox": started["sandbox"],
            "hooks": inventory, "command": command, "plan_sha256": plan_sha,
            "worker_sha256": hashlib.sha256(worker.read_bytes()).hexdigest()})
        return host, workspace, plan

    def pending(self, host, workspace):
        host.calls.clear()
        host.notifications.clear()
        host.deadline = time.monotonic() + 35
        result = host.rpc("turn/start", {"threadId": host.session,
            "input": [{"type": "text", "text": "Execute only the isolated maintenance fixture."}]})
        turn_id = result["turn"]["id"]
        while True:
            row = host.receive()
            if "id" in row and "method" in row:
                self.assertEqual(row["method"], "item/commandExecution/requestApproval", row)
                params = row["params"]
                self.assertEqual(params["threadId"], host.session)
                self.assertEqual(params["turnId"], turn_id)
                self.assertEqual(params["cwd"], str(workspace))
                self.assert_command(host, params["command"])
                self.assertFalse((workspace / "effect.json").exists())
                self.observe("pending-no-effect", row)
                return row
            self.assertNotEqual(row.get("method"), "turn/completed", row)

    def finish(self, host, request, decision):
        self.assertIn(decision, ("accept", "decline"))
        host.send({"id": request["id"], "result": {"decision": decision}})
        self.observe("fixture-reply", {"request_id": request["id"], "decision": decision,
            "human_receipt": False, "persistent_permission": False})
        while True:
            row = host.receive()
            self.assertFalse("id" in row and "method" in row, row)
            if row.get("method") == "turn/completed":
                self.assertEqual(row["params"]["turn"]["status"], "completed", row)
                break
        items = [row["params"]["item"] for row in host.notifications
                 if row.get("method") == "item/completed"
                 and row.get("params", {}).get("item", {}).get("type") == "commandExecution"]
        self.assertEqual(len(items), 1)
        self.assertEqual(len(host.calls), 2)
        self.observe("completion", {"items": items, "calls": len(host.calls)})
        return items[0]

    def test_allow_then_repeat_requires_another_decision(self):
        with ExitStack() as stack:
            host, workspace, plan = self.fixture(stack)
            request = self.pending(host, workspace)
            item = self.finish(host, request, "accept")
            self.assertEqual(item["exitCode"], 0)
            marker = workspace / "effect.json"
            original = marker.read_bytes()
            self.assertEqual(json.loads(original)["plan_sha256"], hashlib.sha256(plan.read_bytes()).hexdigest())
            # Separate turn, same exact command: accepting once must not become
            # acceptForSession/prefix authority. Remove no evidence to test this.
            host.calls.clear()
            host.notifications.clear()
            host.deadline = time.monotonic() + 35
            host.rpc("turn/start", {"threadId": host.session,
                "input": [{"type": "text", "text": "Repeat the exact isolated fixture request."}]})
            while True:
                row = host.receive()
                if "id" in row and "method" in row:
                    self.assertEqual(row["method"], "item/commandExecution/requestApproval", row)
                    self.assert_command(host, row["params"]["command"])
                    self.assertNotEqual(row["id"], request["id"])
                    break
                self.assertNotEqual(row.get("method"), "turn/completed", row)
            repeated = self.finish(host, row, "decline")
            self.assertEqual(repeated["status"], "declined")
            self.assertEqual(marker.read_bytes(), original)

    def test_deny_has_no_effect(self):
        with ExitStack() as stack:
            host, workspace, _ = self.fixture(stack)
            request = self.pending(host, workspace)
            item = self.finish(host, request, "decline")
            self.assertEqual(item["status"], "declined")
            self.assertFalse((workspace / "effect.json").exists())

    def test_plan_drift_after_prompt_is_rejected_by_worker(self):
        with ExitStack() as stack:
            host, workspace, plan = self.fixture(stack)
            request = self.pending(host, workspace)
            plan.write_bytes(plan.read_bytes() + b" ")
            item = self.finish(host, request, "accept")
            self.assertEqual(item["exitCode"], 65)
            self.assertFalse((workspace / "effect.json").exists())

    def test_disconnect_while_pending_does_not_execute(self):
        with ExitStack() as stack:
            host, workspace, _ = self.fixture(stack)
            self.pending(host, workspace)
            # Exercise only this fixture-owned process group, never user hosts.
            from fixture_process_lifecycle import finish_fixture_process_group
            finish_fixture_process_group(host.process)
            self.assertIsNotNone(host.process.poll())
            self.assertFalse((workspace / "effect.json").exists())
            self.observe("pending-disconnect", {"returncode": host.process.returncode, "effect": False})


if __name__ == "__main__":
    unittest.main()
