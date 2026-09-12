"""Actual Codex tools/hooks. A local response fixture never transports audit data."""
import hashlib
import http.server
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "integrations/codex/plugins/sulde/scripts"
HEALTH = ROOT / "scripts/kb/life-health.py"


@unittest.skipIf(os.name == "nt", "Native Windows CLI/PowerShell acceptance belongs to Windows")
@unittest.skipUnless(shutil.which("codex"), "native Codex CLI is required")
class NativePostToolDeliveryTests(unittest.TestCase):
    def test_real_tool_fault_automatic_delivery_aggregation_resume_and_isolation(self):
        with tempfile.TemporaryDirectory(prefix="life-r1-posttool-") as temporary:
            base = Path(temporary).resolve()
            workspace, lane = base / "workspace", base / "lane"
            workspace.mkdir()
            home = base / "home"
            codex_home, kb = home / ".codex", home / ".sulde/data/kb"
            codex_home.mkdir(parents=True)
            env = {k: v for k, v in os.environ.items() if k in {"PATH", "TMPDIR", "LANG", "LC_ALL"}}
            env.update(HOME=str(home), CODEX_HOME=str(codex_home), SULDE_HOME=str(home / ".sulde"),
                       SULDE_KB_HOME=str(kb), PYTHONDONTWRITEBYTECODE="1")
            calls, protocol = [], []
            class Handler(http.server.BaseHTTPRequestHandler):
                def log_message(self, *_args):
                    pass

                def do_POST(self):
                    # Deliberately discard prompt and request contents immediately.
                    request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    protocol.append({"tools": [(t.get("type"), t.get("name")) for t in request.get("tools", [])],
                                     "tool_errors": [x.get("output") for x in request.get("input", []) if x.get("type") == "function_call_output"]})
                    calls.append(self.path)
                    number = len(calls)
                    if number % 2:
                        item = {"type": "function_call", "name": "exec_command", "id": f"fc_{number}",
                                "call_id": f"isolated_call_{number}", "arguments": json.dumps({
                                    "cmd": "printf 'once\\n' >> action-count.txt", "yield_time_ms": 1000})}
                    else:
                        item = {"type": "message", "id": f"msg_{number}", "role": "assistant", "status": "completed",
                                "content": [{"type": "output_text", "text": "Fixture complete.", "annotations": []}]}
                    response = {"id": f"resp_{number}", "status": "completed", "output": [item],
                                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}
                    events = [{"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
                              {"type": "response.output_item.added", "output_index": 0, "item": item},
                              {"type": "response.output_item.done", "output_index": 0, "item": item},
                              {"type": "response.completed", "response": response}]
                    body = "".join("event: " + e["type"] + "\ndata: " + json.dumps(e) + "\n\n" for e in events).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            config = ('check_for_update_on_startup = false\nmodel_provider = "isolated"\nmodel = "fixture"\n'
                      '[features]\nhooks = true\n[model_providers.isolated]\nname = "Loopback test fixture"\n'
                      f'base_url = "http://127.0.0.1:{server.server_port}/v1"\nwire_api = "responses"\n'
                      'request_max_retries = 0\nstream_max_retries = 0\n')
            if os.environ.get("SULDE_ISOLATED_TEST_RUN_ID"):
                config = 'sandbox_mode = "danger-full-access"\n' + config
            for cwd in (workspace, lane):
                config += '[projects.' + json.dumps(str(cwd)) + ']\ntrust_level = "trusted"\n'
            config_file = codex_home / "config.toml"
            config_file.write_text(config)
            def command(argv, cwd=workspace, timeout=45):
                result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
                self.assertEqual(result.returncode, 0, result.stdout[-1000:] + result.stderr[-1500:])
                return result
            def hook(command_text):
                return {"type": "command", "command": command_text, "timeout": 5}
            def observed(name, argv):
                return shlex.join([sys.executable, "-B", str(SCRIPTS / "_hook_observer.py"),
                                   "--hook", name, "--stage", "adapter", "--timeout", "3", "--", *argv])
            failed = base / "project-failure.py"
            failed.write_text("raise RuntimeError('isolated fixture failure')\n")
            project = hook(observed("project:r1", [sys.executable, "-B", str(failed)]))
            (workspace / ".codex").mkdir()
            (workspace / ".codex/hooks.json").write_text(json.dumps({"hooks": {"PostToolUse": [
                {"matcher": "Bash", "hooks": [project, project]}]}}))
            # Native Stop invokes the actual background consumer, after delivery.
            # The test never reads events and feeds them into the recorder.
            (codex_home / "hooks.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [hook(
                shlex.join([sys.executable, "-B", str(HEALTH), "--aggregate"]) + " >/dev/null")]}]}}))
            for argv in (["git", "init"], ["git", "add", ".codex"],
                         ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture"]):
                command(argv)
            command(["git", "worktree", "add", "-b", "lane", str(lane)])
            market = base / "market"
            plugins = []
            for name in ("sulde-r1", "third-party-r1"):
                plugin = market / "plugins" / name
                (plugin / ".claude-plugin").mkdir(parents=True)
                (plugin / ".claude-plugin/plugin.json").write_text(json.dumps({"name": name, "version": "1.0.0"}))
                (plugin / "hooks").mkdir()
                if name == "sulde-r1":
                    shutil.copytree(SCRIPTS, plugin / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
                    (plugin / "runtime/hooks").mkdir(parents=True)
                    (plugin / "runtime/scripts/kb").mkdir(parents=True)
                    # Real Sulde adapter + real child Python; only the isolated
                    # runtime target fails, without any Guardian installation.
                    (plugin / "runtime/hooks/post_tool_use.py").write_text("raise RuntimeError('isolated runtime failure')\n")
                    cmd = 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/run-hook.sh" post-tool-use'
                else:
                    (plugin / "hooks/failure.py").write_text("raise SystemExit(1)\n")
                    cmd = observed("third_party:r1", [sys.executable, "-B", str(plugin / "hooks/failure.py")])
                (plugin / "hooks/hooks.json").write_text(json.dumps({"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [hook(cmd)]}]}}))
                plugins.append({"name": name, "source": {"source": "local", "path": "./plugins/" + name},
                                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}})
            (market / ".agents/plugins").mkdir(parents=True)
            (market / ".agents/plugins/marketplace.json").write_text(json.dumps({"name": "life-r1-fixtures", "plugins": plugins}))
            command(["codex", "plugin", "marketplace", "add", str(market), "--json"])
            for plugin in plugins:
                command(["codex", "plugin", "add", plugin["name"] + "@life-r1-fixtures", "--json"])
            config = config_file.read_text()
            host = subprocess.Popen(["codex", "app-server"], cwd=workspace, env=env, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
            def rpc(identifier, method, params):
                host.stdin.write(json.dumps({"id": identifier, "method": method, "params": params}) + "\n")
                host.stdin.flush()
                for line in host.stdout:
                    value = json.loads(line)
                    if value.get("id") == identifier:
                        return value
            try:
                rpc(1, "initialize", {"clientInfo": {"name": "life_r1_inventory", "version": "1"}, "capabilities": {"experimentalApi": True}})
                inventory = rpc(2, "hooks/list", {"cwds": [str(workspace), str(lane)]})
                trusted = set()
                for entry in inventory["result"]["data"]:
                    for h in entry["hooks"]:
                        if h["key"] not in trusted:
                            trusted.add(h["key"])
                            config += '[hooks.state.' + json.dumps(h["key"]) + ']\ntrusted_hash = ' + json.dumps(h["currentHash"]) + '\n'
                config_file.write_text(config)
            finally:
                host.terminate()
                host.wait(timeout=5)
                host.stdin.close()
                host.stdout.close()
            summaries, session = [], None
            for phase, cwd, resume in (("new", workspace, False), ("resume", workspace, True),
                                       ("worktree_switch", lane, True), ("new_isolated_session", workspace, False)):
                argv = ["codex", "-C", str(cwd), "exec"]
                if resume:
                    argv += ["resume", session]
                else:
                    # macOS cannot nest sandbox-exec. The official test runner
                    # already applies OS denial of production writes to children.
                    sandbox = "danger-full-access" if os.environ.get("SULDE_ISOLATED_TEST_RUN_ID") else "workspace-write"
                    argv += ["--sandbox", sandbox]
                argv += ["--json", "Run one isolated fixture action."]
                result = command(argv, cwd=cwd)
                events = [json.loads(line) for line in result.stdout.splitlines()]
                current = next(row["thread_id"] for row in events if row["type"] == "thread.started")
                if resume:
                    self.assertEqual(current, session)
                elif session:
                    self.assertNotEqual(current, session)
                if session is None:
                    session = current
                tool = [e["item"] for e in events if e["type"] == "item.completed" and e.get("item", {}).get("type") == "command_execution"]
                self.assertEqual(len(tool), 1, phase + " " + json.dumps(protocol)[-5000:] + result.stdout[-2000:] + result.stderr[-1000:])
                self.assertEqual(tool[0]["exit_code"], 0)
                status = json.loads(command([sys.executable, "-B", str(HEALTH), "--status"]).stdout)
                self.assertEqual(status["status"], "open", status)
                with sqlite3.connect(f"file:{kb / 'life/problems/ledger.sqlite3'}?mode=ro", uri=True) as db:
                    facts = [json.loads(row[0]) for row in db.execute("SELECT row FROM processed")]
                selected = [row for row in facts if row["session_id"] == hashlib.sha256(current.encode()).hexdigest()
                            and row["workspace_id"] == hashlib.sha256(str(cwd).encode()).hexdigest()]
                failures = [row for row in selected if row["error_category"] != "normal"]
                self.assertEqual({r["source_kind"] for r in failures}, {"sulde", "project", "third_party"}, selected)
                self.assertTrue(all(r["tool_result"] == "success" and r["audit_delivery"] == "recorded" for r in failures))
                self.assertTrue(all(r["permission_decision"] == "unknown" for r in failures))
                summaries.append({"phase": phase, "tool_exit_code": 0, "sources": sorted({r["source_kind"] for r in failures}),
                                  "facts_count": len(facts), "problems": status["problems"]})
            self.assertEqual((workspace / "action-count.txt").read_text().splitlines(), ["once"] * 3)
            self.assertEqual((lane / "action-count.txt").read_text().splitlines(), ["once"])
            self.assertEqual(len(calls), 8)
            # Automatic duplicate invocation and recurrence remain bounded by
            # native call identity: 3 distinct source failures per invocation.
            failures = [row for row in facts if row["error_category"] != "normal"]
            self.assertEqual(len(failures), 12)
            self.assertEqual(sorted(p["occurrences"] for p in status["problems"]), [1, 1, 1, 3, 3, 3])
            evidence = {"schema": "life-r1-native-posttool-v1", "codex": command(["codex", "--version"]).stdout.strip(),
                        "platform": sys.platform, "tool_executions": 4, "external_model_requests": 0,
                        "delivery": "native Hook command -> recorder -> native Stop consumer -> independent CLI/SQLite read",
                        "ingest_calls": 0, "guardian_installed": False, "sessions": summaries,
                        "blind_spots": ["unwrapped foreign Hooks", "Desktop ingress unavailable", "observer pre-start failure"]}
            descriptor, filename = tempfile.mkstemp(prefix="life-r1-native-evidence-", suffix=".json", dir="/private/tmp")
            os.close(descriptor)
            target = Path(filename)
            target.write_text(json.dumps(evidence, indent=2) + "\n")
            print("NATIVE_POSTTOOL_EVIDENCE=" + str(target), flush=True)
