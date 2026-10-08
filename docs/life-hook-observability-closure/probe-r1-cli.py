"""Native Codex CLI + loopback-only Responses fixture; never transports audit events.

This preliminary probe persists only isolated fixture data under a temporary root.
The fixture emits one benign shell call; native Codex executes the tool and hooks.
"""
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


def main():
    base = Path(tempfile.mkdtemp(prefix="life-r1-native-")).resolve()
    workspace = base / "workspace"
    workspace.mkdir()
    home = base / "home"
    codex_home = home / ".codex"
    codex_home.mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "TMPDIR", "LANG", "LC_ALL"}}
    env.update(HOME=str(home), CODEX_HOME=str(codex_home),
               SULDE_HOME=str(home / ".sulde"), SULDE_KB_HOME=str(home / ".sulde/data/kb"),
               PYTHONDONTWRITEBYTECODE="1")
    requests = []
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append({"path": self.path, "tools": [t.get("name", t.get("type")) for t in request.get("tools", [])]})
            first = len(requests) == 1
            item = ({"type": "function_call", "name": "exec_command", "call_id": "isolated_call_1", "id": "fc_1",
                     "arguments": json.dumps({"cmd": "printf 'once\\n' >> action-count.txt", "yield_time_ms": 1000})}
                    if first else {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                                   "content": [{"type": "output_text", "text": "Fixture complete.", "annotations": []}]})
            events = [{"type": "response.created", "response": {"id": "resp_" + str(len(requests)), "status": "in_progress", "output": []}},
                      {"type": "response.output_item.added", "output_index": 0, "item": item},
                      {"type": "response.output_item.done", "output_index": 0, "item": item},
                      {"type": "response.completed", "response": {"id": "resp_" + str(len(requests)), "status": "completed", "output": [item],
                         "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}}]
            body = "".join("event: " + e["type"] + "\ndata: " + json.dumps(e) + "\n\n" for e in events).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    config = ('check_for_update_on_startup = false\nmodel_provider = "isolated"\nmodel = "fixture"\n'
              '[features]\nhooks = true\n[model_providers.isolated]\nname = "Local fixed test responses"\n'
              f'base_url = "http://127.0.0.1:{server.server_port}/v1"\nwire_api = "responses"\n'
              'request_max_retries = 0\nstream_max_retries = 0\n'
              '[projects.' + json.dumps(str(workspace)) + ']\ntrust_level = "trusted"\n')
    (codex_home / "config.toml").write_text(config)
    script = base / "fixture-hook.py"
    script.write_text("import json, sys\nfrom pathlib import Path\np=json.load(sys.stdin)\n"
                      f"Path({str(base / 'hook-payload.json')!r}).write_text(json.dumps(p))\nraise SystemExit(1)\n")
    (workspace / ".codex").mkdir()
    (workspace / ".codex/hooks.json").write_text(json.dumps({"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": shlex.join([sys.executable, "-B", str(script)]), "timeout": 3}]}]}}))
    for argv in (["git", "init"], ["git", "add", ".codex"],
                 ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture"]):
        subprocess.run(argv, cwd=workspace, env=env, check=True, capture_output=True)
    # Trust the exact definitions reported by this isolated native host.
    host = subprocess.Popen([shutil.which("codex"), "app-server"], cwd=workspace, env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    def rpc(identifier, method, params):
        host.stdin.write(json.dumps({"id": identifier, "method": method, "params": params}) + "\n")
        host.stdin.flush()
        for line in host.stdout:
            value = json.loads(line)
            if value.get("id") == identifier:
                return value
    try:
        rpc(1, "initialize", {"clientInfo": {"name": "life_r1_fixture", "version": "1"}, "capabilities": {"experimentalApi": True}})
        inventory = rpc(2, "hooks/list", {"cwds": [str(workspace)]})
        for entry in inventory["result"]["data"]:
            for hook in entry["hooks"]:
                config += '[hooks.state.' + json.dumps(hook["key"]) + ']\ntrusted_hash = ' + json.dumps(hook["currentHash"]) + '\n'
        (codex_home / "config.toml").write_text(config)
    finally:
        host.terminate()
        host.wait(timeout=5)
        host.stdin.close()
        host.stdout.close()
    try:
        result = subprocess.run([shutil.which("codex"), "exec", "--json", "--sandbox", "workspace-write", "-C", str(workspace),
                                 "Run the single isolated fixture action."], env=env, cwd=workspace,
                                capture_output=True, text=True, timeout=45)
        (base / "cli.stdout.jsonl").write_text(result.stdout)
        (base / "cli.stderr.txt").write_text(result.stderr)
        (base / "requests.json").write_text(json.dumps(requests))
        print(json.dumps({"root": str(base), "exit_code": result.returncode, "requests": requests,
                          "actions": (workspace / "action-count.txt").read_text() if (workspace / "action-count.txt").exists() else None,
                          "hook_payload": json.loads((base / "hook-payload.json").read_text()) if (base / "hook-payload.json").exists() else None,
                          "stderr_tail": result.stderr[-2000:], "stdout_tail": result.stdout[-3000:]}))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
