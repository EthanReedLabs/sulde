"""Single-operation official Codex TUI transport. Never answers human approval.

Draft/slot are private local artifacts. Production changes only occur if the
person approves the exact frozen worker in the independently isolated host.
"""
import argparse
import hashlib
import http.server
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import candidate_codex_plugin as candidate
from legacy_maintenance import (MaintenanceError, canonical, prepare_bundle,
                                process_identity, process_inventory, secure_bytes)


class FixedOperation:
    """Finite provider: one exact exec, then polls only its observed session."""
    def __init__(self, command, cwd, description):
        self.command, self.cwd, self.description = command, cwd, description
        self.started = False
        self.session = None
        self.done = False
        self.result = None
        self.sequence = 0
        self.pending_call = None

    def response(self, request):
        results = [x for x in request.get("input", [])
                   if x.get("type") == "function_call_output"
                   and self.pending_call is not None and x.get("call_id") == self.pending_call]
        self.sequence += 1
        call = "maintenance_" + str(self.sequence)
        if not self.started:
            self.started = True
            name, args = "exec_command", {"cmd": self.command, "workdir": self.cwd,
                "yield_time_ms": 1000, "sandbox_permissions": "require_escalated",
                "justification": self.description}
        elif results:
            output = str(results[-1].get("output", ""))
            session = re.search(r"Process running with session ID (\d+)", output)
            if session:
                observed = int(session.group(1))
                if self.session is not None and self.session != observed:
                    raise MaintenanceError("native execution session changed")
                self.session = observed
                name, args = "write_stdin", {"session_id": observed, "chars": "", "yield_time_ms": 1000}
            else:
                self.done, self.result = True, output
                name, args = None, None
        else:
            # Prefetch without a result is not a completed operation.
            name, args = None, None
        if name:
            self.pending_call = call
            return {"type": "function_call", "name": name, "id": "fc_" + call,
                    "call_id": call, "arguments": json.dumps(args)}
        return {"type": "message", "id": call, "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": "维护调用状态已记录；是否完成以独立回读为准。", "annotations": []}]}


def run(draft_path, draft_sha256, slot):
    raw = secure_bytes(Path(draft_path))
    if hashlib.sha256(raw).hexdigest() != draft_sha256:
        raise MaintenanceError("maintenance draft changed")
    draft = json.loads(raw)
    if draft.get("maintenance_host") is not None:
        raise MaintenanceError("draft must not borrow another maintenance host identity")
    slot = Path(slot)
    if not slot.is_absolute() or slot.resolve() != slot:
        raise MaintenanceError("isolated host slot must be canonical")
    os.umask(0o077)
    slot.mkdir(mode=0o700)
    codex = draft["codex"]
    environment = candidate._candidate_environment(slot, codex, candidate._python_identity(Path(sys.executable)))
    environment["TERM"] = os.environ.get("TERM", "xterm-256color")
    workspace = slot / "isolated/workspace"
    subprocess.run(["git", "init", "--quiet", str(workspace)], env=environment, check=True, timeout=10)
    process = None
    operation = None
    finished = threading.Event()
    facts = []
    failure = []

    def freeze():
        rows = process_inventory()
        descendants = {process.pid}
        for _ in range(len(rows)):
            descendants.update(row["pid"] for row in rows if row["parent_pid"] in descendants)
        hosts = [row for row in rows if row["pid"] in descendants
                 and Path(row["executable"]).name.lower() == "codex"]
        if len(hosts) != 1:
            raise MaintenanceError("owned native Codex process identity is ambiguous")
        plan = {**draft, "maintenance_host": process_identity(hosts[0])}
        plan_file = slot / "plan.json"
        with plan_file.open("xb") as out:
            out.write(canonical(plan))
            out.flush()
            os.fsync(out.fileno())
        bundle = prepare_bundle(plan_file, hashlib.sha256(canonical(plan)).hexdigest(),
                                slot / "worker-bundle.json", root=Path(__file__).resolve().parents[2])
        facts.append({"stage": "frozen", "operation_id": plan["operation_id"],
                      "bundle_sha256": bundle["bundle_sha256"], "maintenance_host": plan["maintenance_host"]})
        if plan.get("schema") == "sulde-first-migration-reversal-plan-v1":
            description = ("是否一次性撤回 Sulde 当前首次 Hook 迁移？目标 " + plan["kb_home"]
                + "，只恢复绑定的原安装快照与注册；保留审计历史，不终止会话，不允许任意降级。")
        else:
            description = ("是否一次性执行 Sulde 旧 Hook 维护迁移？候选 " + plan["candidate_id"]
                           + "，目标 " + plan["kb_home"]
                           + "。只等待已列明会话退出，不终止会话；失败保留原事务回滚，未验证真人 Hook 前不宣称 ready。")
        return FixedOperation(bundle["command"], str(workspace), description)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            nonlocal operation
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size < 4 * 1024 * 1024 or time.time() >= draft["expires_at"]:
                    raise MaintenanceError("provider input limit or deadline reached")
                request = json.loads(self.rfile.read(size))
                if operation is None:
                    operation = freeze()
                if operation.done:
                    self.send_error(410)
                    return
                item = operation.response(request)
                response = {"id": "maintenance_response", "status": "completed", "output": [item],
                            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}
                events = [{"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
                          {"type": "response.output_item.added", "output_index": 0, "item": item},
                          {"type": "response.output_item.done", "output_index": 0, "item": item},
                          {"type": "response.completed", "response": response}]
                body = "".join("event: " + row["type"] + "\ndata: " + json.dumps(row) + "\n\n" for row in events).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()
                if operation.done:
                    finished.set()
            except Exception as error:
                failure.append(str(error))
                self.send_error(422)
                finished.set()

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    argv = [codex, "--no-daemon", "--no-alt-screen", "-C", str(workspace), "-s", "read-only", "-a", "on-request",
            "-c", 'approvals_reviewer="user"', "-c", 'model_provider="maintenance_local"', "-c", 'model="fixture"',
            "-c", 'model_providers.maintenance_local.name="Sulde exact maintenance"',
            "-c", 'model_providers.maintenance_local.base_url="http://127.0.0.1:' + str(server.server_port) + '/v1"',
            "-c", 'model_providers.maintenance_local.wire_api="responses"',
            "-c", "model_providers.maintenance_local.request_max_retries=0", "-c", "model_providers.maintenance_local.stream_max_retries=0",
            "-c", "check_for_update_on_startup=false", "-c", "features.unified_exec=true",
            "只请求本次冻结维护操作的一次性原生批准；不要选择永久前缀允许。"]
    try:
        process = subprocess.Popen(argv, cwd=workspace, env=environment)
        while process.poll() is None and time.time() < draft["expires_at"] and not finished.wait(0.25):
            pass
        if finished.is_set():
            time.sleep(2)
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
        # Observed result only. No fabricated approval or operational readiness.
        result = {"scope": "independent-native-maintenance", "facts": facts, "errors": failure,
                  "worker_result": operation.result if operation else None,
                  "status": "observed-unverified" if operation and operation.done else "incomplete",
                  "human_receipt": None, "operational_ready": False}
        with (slot / "host-result.json").open("x", encoding="utf-8") as out:
            json.dump(result, out, ensure_ascii=False, indent=2)
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path)
    parser.add_argument("draft_sha256")
    parser.add_argument("slot", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.draft, args.draft_sha256, args.slot), ensure_ascii=False))
