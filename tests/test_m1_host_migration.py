"""Opt-in host-mechanism experiment: synthetic hooks, no production migration."""
from contextlib import ExitStack, contextmanager
import hashlib
import http.server
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/release"))
import candidate_codex_plugin as candidate
from native_pretool_canary import NativeCanary
from fixture_process_lifecycle import start_fixture_process, finish_fixture_process_group

EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PermissionRequest", "PostToolUse", "Stop")
PROBE = '''import hashlib, json, os, sys, time
payload = json.load(sys.stdin)
row = {"version": sys.argv[1], "event": sys.argv[2], "pid": os.getpid(),
       "session": payload.get("session_id"), "call": payload.get("tool_use_id", payload.get("call_id")),
       "script": __file__, "script_sha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(),
       "monotonic_ns": time.monotonic_ns()}
fd = os.open(os.environ["M1_TRACE"], os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
os.write(fd, (json.dumps(row) + "\\n").encode()); os.close(fd)
print("{}")
'''


class Host(NativeCanary):
    """Reuse the existing strict RPC reader; own only a local fixture process."""
    @contextmanager
    def start(self):
        owner = self
        self.deadline = time.monotonic() + 120
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size < 4 * 1024 * 1024:
                    self.send_error(413)
                    return
                request = json.loads(self.rfile.read(size))
                number = len(owner.calls)
                owner.calls.append(self.path)
                if number == 0:
                    if "exec_command" not in {row.get("name") for row in request.get("tools", [])}:
                        self.send_error(422)
                        return
                    item = {"type": "function_call", "name": "exec_command", "id": "fc_m1",
                            "call_id": "m1_fixture", "arguments": json.dumps(getattr(owner, "tool_arguments", {
                                "cmd": "printf m1", "workdir": str(owner.workspace), "yield_time_ms": 1000}))}
                elif number == 1:
                    item = {"type": "message", "id": "m1_done", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": "M1 complete.", "annotations": []}]}
                else:
                    self.send_error(429)
                    return
                response = {"id": "m1_response_" + str(number), "status": "completed", "output": [item],
                            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}
                events = [{"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
                          {"type": "response.output_item.added", "output_index": 0, "item": item},
                          {"type": "response.output_item.done", "output_index": 0, "item": item},
                          {"type": "response.completed", "response": response}]
                raw = "".join("event: " + e["type"] + "\ndata: " + json.dumps(e) + "\n\n" for e in events).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        argv = [self.codex, "-c", 'model_provider="m1_local"', "-c", 'model="fixture"',
                "-c", 'model_providers.m1_local.name="M1 local fixture"',
                "-c", 'model_providers.m1_local.base_url="http://127.0.0.1:' + str(server.server_port) + '/v1"',
                "-c", 'model_providers.m1_local.wire_api="responses"',
                "-c", "model_providers.m1_local.request_max_retries=0",
                "-c", "model_providers.m1_local.stream_max_retries=0",
                "-c", "check_for_update_on_startup=false", "-c", "features.hooks=true",
                "-c", "features.unified_exec=true", "app-server", "--stdio"]
        errors = self.workspace / "host-stderr.log"
        with errors.open("wb") as error_output:
            try:
                self.process = start_fixture_process(argv, cwd=self.workspace, env=self.environment,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=error_output,
                    text=True, encoding="utf-8", errors="replace")
                def read():
                    try:
                        for line in self.process.stdout:
                            self.messages.put(json.loads(line), timeout=1)
                    finally:
                        self.messages.put(None, timeout=1)
                threading.Thread(target=read, daemon=True).start()
                self.rpc("initialize", {"clientInfo": {"name": "m1_local", "version": "1"},
                                        "capabilities": {"experimentalApi": True}})
                self.send({"method": "initialized", "params": {}})
                yield self
            finally:
                if self.process is not None:
                    finish_fixture_process_group(self.process)
                    self.process.stdin.close()
                    self.process.stdout.close()
                server.shutdown()
                server.server_close()
                worker.join(timeout=2)
                print("M1_HOST_STDERR=" + json.dumps({"workspace": self.workspace.name,
                    "text": errors.read_text(encoding="utf-8", errors="replace")[-12000:]}), flush=True)

    def trust(self):
        inventory = self.rpc("hooks/list", {"cwds": [str(self.workspace)]})
        hooks = [h for row in inventory.get("data", []) for h in row.get("hooks", [])
                 if h.get("pluginId") == "sulde@sulde-local"]
        if len(hooks) != 6:
            raise AssertionError("six fixture hooks not discovered: " + json.dumps(inventory))
        edits = [{"keyPath": "hooks.state." + json.dumps(h["key"]) + ".trusted_hash",
                  "value": h["currentHash"], "mergeStrategy": "replace"} for h in hooks]
        edits.append({"keyPath": "projects." + json.dumps(str(self.workspace)) + ".trust_level",
                      "value": "trusted", "mergeStrategy": "replace"})
        self.rpc("config/batchWrite", {"edits": edits})
        return hooks

    def thread(self):
        # The official outer runner supplies OS isolation, not this experiment.
        result = self.rpc("thread/start", {"cwd": str(self.workspace), "approvalPolicy": "never",
                                           "sandbox": "danger-full-access"})
        self.session = result["thread"]["id"]
        return self.session

    def turn(self):
        self.calls.clear()
        self.notifications.clear()
        self.deadline = time.monotonic() + 45
        self.execute(["printf m1"])
        return {"calls": len(self.calls), "hooks": [row for row in self.notifications
            if row.get("method") in {"hook/started", "hook/completed"}],
            "items": [row for row in self.notifications if row.get("method") == "item/completed"
                      and row.get("params", {}).get("item", {}).get("type") == "commandExecution"]}


@unittest.skipUnless(os.environ.get("SULDE_ISOLATED_TEST_RUN_ID"), "requires official OS-isolated runner")
@unittest.skipIf(os.name == "nt", "POSIX host feasibility only")
class M1HostMigrationTests(unittest.TestCase):
    def test_capture_two_old_callers_and_boundary_caller(self):
        with tempfile.TemporaryDirectory(prefix="sulde-m1-") as temporary, ExitStack() as stack:
            slot = Path(temporary).resolve()
            codex = shutil.which("codex")
            self.assertIsNotNone(codex)
            env = candidate._candidate_environment(slot, codex, candidate._python_identity(Path(sys.executable)))
            trace = Path(env["SULDE_HOME"]) / "m1-trace.jsonl"
            env["M1_TRACE"] = str(trace)
            marketplace = slot / "marketplace"
            plugin = marketplace / "plugins/sulde"
            for relative in (".agents/plugins", "plugins/sulde/.codex-plugin", "plugins/sulde/hooks"):
                (marketplace / relative).mkdir(parents=True)
            (marketplace / ".agents/plugins/marketplace.json").write_text(json.dumps({
                "name": "sulde-local", "plugins": [{"name": "sulde", "source": {"source": "local", "path": "./plugins/sulde"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Productivity"}]}), encoding="utf-8")
            stable = Path(env["SULDE_HOME"]) / "fixture-stable.py"
            stable.write_text(PROBE, encoding="utf-8")
            history = []

            def save(kind, data):
                history.append({"kind": kind, "data": data})
                print("M1_OBSERVATION=" + json.dumps(history[-1], sort_keys=True), flush=True)

            def publish(version, outside):
                (plugin / ".codex-plugin/plugin.json").write_text(json.dumps({
                    "name": "sulde", "version": version, "description": "M1 synthetic host fixture",
                    "hooks": "./hooks/hooks.json"}), encoding="utf-8")
                (plugin / "hooks/probe.py").write_text(PROBE, encoding="utf-8")
                target = shlex.quote(str(stable)) if outside else '"${PLUGIN_ROOT}/hooks/probe.py"'
                document = {"hooks": {event: [{"hooks": [{"type": "command", "timeout": 10,
                    "command": shlex.quote(sys.executable) + " -B " + target + " " + version + " " + event}]}]
                    for event in EVENTS}}
                (plugin / "hooks/hooks.json").write_text(json.dumps(document), encoding="utf-8")

            def cli(*argv):
                result = subprocess.run([codex, *argv], env=env, cwd=slot, capture_output=True,
                    text=True, encoding="utf-8", errors="replace", timeout=30)
                save("cli", {"argv": list(argv), "rc": result.returncode,
                             "stdout": result.stdout, "stderr": result.stderr})
                self.assertEqual(result.returncode, 0, result.stderr)
                return result

            def host(name):
                workspace = Path(env["SULDE_HOME"]).parent / name
                workspace.mkdir()
                value = stack.enter_context(Host(codex, workspace, env, externally_isolated=True).start())
                save(name + "-trust", value.trust())
                value.thread()
                return value

            def run(name, value, *, normal=False):
                before = len(trace.read_text(encoding="utf-8").splitlines()) if trace.exists() else 0
                result = value.turn()
                rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()][before:] if trace.exists() else []
                save(name, {"session": value.session, "host_pid": value.process.pid,
                            "callbacks": rows, "host": result})
                self.assertEqual(result["calls"], 2)
                if normal:
                    self.assertTrue(any(row["event"] == "PreToolUse" and row["version"] == "0.0.1" for row in rows))
                    self.assertTrue(any(row["event"] == "PostToolUse" for row in rows))
                    self.assertTrue(result["items"])
                    self.assertTrue(all(row["session"] == value.session for row in rows))
                    self.assertTrue(all(row["params"]["item"]["exitCode"] == 0 for row in result["items"]))
                save(name + "-summary", {
                    "session": value.session, "host_pid": value.process.pid,
                    "callbacks": [[row["event"], row["version"]] for row in rows],
                    "hook_results": [row["params"] for row in result["hooks"] if row["method"] == "hook/completed"],
                    "command_exit_codes": [row["params"]["item"]["exitCode"] for row in result["items"]]})

            cli("--version")
            save("executable", {"path": str(Path(codex).resolve()),
                "sha256": hashlib.sha256(Path(codex).resolve().read_bytes()).hexdigest()})
            publish("0.0.1", False)
            cli("plugin", "marketplace", "add", str(marketplace))
            cli("plugin", "add", "sulde@sulde-local")
            a, b = host("old-A"), host("old-B")
            run("normal-A", a, normal=True)
            run("normal-B", b, normal=True)
            old = Path(env["CODEX_HOME"]) / "plugins/cache/sulde-local/sulde/0.0.1"
            self.assertTrue(old.is_dir())
            publish("0.0.2", True)
            cli("plugin", "add", "sulde@sulde-local")
            save("registry-boundary", {"old_cache_exists": old.exists()})
            c = host("boundary-C")  # after registry update, before any explicit old-host reload
            run("boundary-new-C", c)
            run("after-registry-A", a)
            run("after-registry-B", b)
            save("reconcile-A", a.rpc("plugin/reconcile", {"reason": "isolated M1 fixture"}))
            run("after-reconcile-A", a)
            run("untouched-peer-B", b)
            for name, value in (("A", a), ("B", b)):
                save("reload-" + name, value.rpc("config/batchWrite", {
                    "edits": [{"keyPath": "check_for_update_on_startup", "value": False, "mergeStrategy": "replace"}],
                    "reloadUserConfig": True}))
                run("after-reload-" + name, value)
                if name == "A":
                    run("peer-B-after-A-reload", b)
            save("scope", {"external_model_requests": 0, "fixture_only": True,
                "production_migration_proven": False, "boundary": "post-registry/pre-explicit-old-reload",
                "all_processes_distinct": len({a.process.pid, b.process.pid, c.process.pid}) == 3})


if __name__ == "__main__":
    unittest.main()
