#!/usr/bin/env python3
"""One benign native-TUI probe. Never sends approval input or installs Sulde."""
import argparse
import hashlib
import http.server
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/release"))
import candidate_codex_plugin as candidate


def save(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def run(slot):
    os.umask(0o077)
    slot.mkdir(mode=0o700)  # Never reuse another run's home or approval state.
    codex = shutil.which("codex")
    if not codex:
        raise RuntimeError("official Codex CLI unavailable")
    environment = candidate._candidate_environment(
        slot, codex, candidate._python_identity(Path(sys.executable)))
    environment["TERM"] = os.environ.get("TERM", "xterm-256color")
    workspace = slot / "isolated/workspace"
    # Stop project/AGENTS/config discovery at the isolated fixture itself.
    subprocess.run(["git", "init", "--quiet", str(workspace)],
                   env=environment, check=True, timeout=10)
    marker = workspace / "benign-marker.json"
    nonce = os.urandom(16).hex()
    body = json.dumps({"probe_only": True, "nonce": nonce}, sort_keys=True)
    # Inline exact bytes: no mutable script reopened after hashing. This probe
    # has no installer, process signalling, provider-generated code or network.
    code = (
        "import os,sys; "
        "fd=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600); "
        "os.write(fd,sys.argv[2].encode()); os.fsync(fd); os.close(fd); "
        "print('BENIGN_MARKER_CREATED')")
    python = str(slot / "isolated/sulde-home/data/kb/venv/bin/python")
    command = shlex.join([python, "-B", "-I", "-c", code, str(marker), body])
    complete = threading.Event()
    calls = []
    record = {"schema": "sulde-interactive-bootstrap-probe-v1", "status": "starting",
              "scope": "isolated-benign-marker-only", "human_receipt": None,
              "command": command, "command_sha256": hashlib.sha256(command.encode()).hexdigest(),
              "codex": str(Path(codex).resolve()),
              "codex_sha256": hashlib.sha256(Path(codex).resolve().read_bytes()).hexdigest(),
              "workspace": str(workspace), "nonce": nonce, "calls": calls,
              "started_at": time.time(), "production_modified": False}
    state = slot / "probe-state.json"
    save(state, record)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size < 4 * 1024 * 1024:
                self.send_error(413)
                return
            request = json.loads(self.rfile.read(size))
            number = len(calls)
            if number > 7:
                self.send_error(429)
                return
            results = [x for x in request.get("input", [])
                if x.get("type") == "function_call_output" and x.get("call_id") == "benign_probe"]
            observation = {"number": number, "path": self.path, "at": time.time(),
                           "input_types": [x.get("type") for x in request.get("input", [])]}
            calls.append(observation)
            if number == 0:
                if "exec_command" not in {x.get("name") for x in request.get("tools", [])}:
                    record["status"] = "unsupported-tool-schema"
                    save(state, record)
                    self.send_error(422)
                    return
                args = {"cmd": command, "workdir": str(workspace), "yield_time_ms": 1000,
                        "sandbox_permissions": "require_escalated",
                        "justification": "仅在本次隔离目录创建一个测试标记；不安装、不修改生产。是否允许一次？"}
                item = {"type": "function_call", "name": "exec_command", "id": "fc_benign_probe",
                        "call_id": "benign_probe", "arguments": json.dumps(args)}
                record["status"] = "native-decision-pending"
            else:
                # Only the fixed tool's returned facts, not prompts or private
                # parent sessions. This is not itself a transferable approval.
                observation["tool_results"] = results
                # Interactive hosts may speculate before the tool finishes.
                # A second provider request is NOT a delivered approval/result.
                if results:
                    record["status"] = "tool-result-observed-awaiting-independent-review"
                item = {"type": "message", "id": "probe_done", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": "隔离验收调用已返回。未执行安装。", "annotations": []}]}
            save(state, record)
            response = {"id": "benign_response_" + str(number), "status": "completed", "output": [item],
                        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}
            events = [{"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
                      {"type": "response.output_item.added", "output_index": 0, "item": item},
                      {"type": "response.output_item.done", "output_index": 0, "item": item},
                      {"type": "response.completed", "response": response}]
            raw = "".join("event: " + row["type"] + "\ndata: " + json.dumps(row) + "\n\n" for row in events).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            self.wfile.flush()
            if results:
                complete.set()

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    argv = [codex, "--no-daemon", "--no-alt-screen", "-C", str(workspace),
            "--sandbox", "read-only", "--ask-for-approval", "on-request",
            "-c", 'approvals_reviewer="user"',
            "-c", 'model_provider="benign_local"', "-c", 'model="fixture"',
            "-c", 'model_providers.benign_local.name="Isolated benign approval probe"',
            "-c", 'model_providers.benign_local.base_url="http://127.0.0.1:' + str(server.server_port) + '/v1"',
            "-c", 'model_providers.benign_local.wire_api="responses"',
            "-c", "model_providers.benign_local.request_max_retries=0",
            "-c", "model_providers.benign_local.stream_max_retries=0",
            "-c", "check_for_update_on_startup=false", "-c", "features.hooks=true",
            "-c", "features.unified_exec=true",
            "仅请求本次隔离测试标记的原生批准，不执行任何安装或生产操作。"]
    record["argv"] = argv
    record["environment_keys"] = sorted(environment)
    save(state, record)
    print("Sulde 隔离审批验收：请在官方 Codex 界面自行选择一次允许或拒绝。")
    print("无付费模型、无生产 Sulde、无正式安装。十分钟未完成则停止本验收。", flush=True)
    process = None
    try:
        # Inherit the real Terminal TTY; never pipe approval input or detach its
        # controlling terminal. Only this Popen object's exact child may stop.
        process = subprocess.Popen(argv, cwd=workspace, env=environment)
        record["owned_pid"] = process.pid
        save(state, record)
        deadline = time.monotonic() + 600
        while process.poll() is None and not complete.wait(0.25) and time.monotonic() < deadline:
            pass
        if complete.is_set():
            time.sleep(3)  # Let the official UI render its final response.
        elif process.poll() is None:
            record["status"] = "timed-out-without-decision-evidence"
        else:
            record["status"] = "host-exited-before-completion"
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        record["host_returncode"] = None if process is None else process.returncode
        record["marker_exists"] = marker.exists()
        record["marker_matches"] = marker.is_file() and marker.read_bytes() == body.encode()
        record["ended_at"] = time.time()
        save(state, record)
        print("\n隔离验收已停止。状态：" + record["status"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slot", type=Path)
    arguments = parser.parse_args()
    allowed = (ROOT / ".codex-agent/s3c-bootstrap-interactive").resolve()
    if arguments.slot.parent.resolve() != allowed or arguments.slot.exists():
        parser.error("slot must be a new direct child of the task-owned interactive probe directory")
    allowed.mkdir(parents=True, exist_ok=True, mode=0o700)
    run(arguments.slot.resolve())
