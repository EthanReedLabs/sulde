#!/usr/bin/env python3
"""Read-only fresh-process MCP acceptance through the installed Codex route."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    version, expected_generation = sys.argv[1:]
    route = json.loads(subprocess.run(
        ["codex", "mcp", "get", "sulde_kb", "--json"],
        capture_output=True, text=True, check=True, timeout=30,
    ).stdout)
    transport = route["transport"]
    assert route["enabled"] is True and transport["type"] == "stdio"
    installed = Path(transport["cwd"]).resolve()
    assert installed.name == version
    assert json.loads((installed / ".codex-plugin/plugin.json").read_text())["version"] == version
    generation = json.loads((installed / ".codex-plugin/generation.json").read_text())["generation"]
    assert generation == expected_generation
    environment = os.environ.copy()
    environment.update(transport.get("env") or {})
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    requests = [
        dict(jsonrpc="2.0", id=1, method="initialize", params={
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "sulde-cli01551-release-acceptance", "version": "1"}}),
        dict(jsonrpc="2.0", method="notifications/initialized"),
        dict(jsonrpc="2.0", id=2, method="tools/list", params={}),
        dict(jsonrpc="2.0", id=3, method="tools/call", params={"name": "kb_status", "arguments": {}}),
    ]
    started = time.monotonic()
    run = subprocess.run(
        [transport["command"], *transport.get("args", [])], cwd=installed, env=environment,
        input="".join(json.dumps(row) + "\n" for row in requests),
        capture_output=True, text=True, timeout=60, check=True,
    )
    rows = [json.loads(line) for line in run.stdout.splitlines() if line.strip()]
    responses = [row for row in rows if "id" in row]
    by_id = {row["id"]: row for row in responses}
    assert len(responses) == 3 and set(by_id) == {1, 2, 3}
    assert all("error" not in row for row in responses)
    assert by_id[1]["result"]["serverInfo"]["name"] == "sulde-kb"
    names = [tool["name"] for tool in by_id[2]["result"]["tools"]]
    assert "kb_status" in names
    result = by_id[3]["result"]
    assert not result.get("isError")
    status = json.loads(result["content"][0]["text"])
    print(json.dumps(dict(
        schema="sulde-cli01551-installed-mcp-readback-v1", status="transport_passed",
        generation=generation, plugin_version=version, tool_count=len(names),
        requests=3, fresh_process=True, existing_conversation_reconnected=False,
        kb_status=status, stdout_sha256=hashlib.sha256(run.stdout.encode()).hexdigest(),
        stderr_sha256=hashlib.sha256(run.stderr.encode()).hexdigest(),
        elapsed_seconds=round(time.monotonic() - started, 3),
    ), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
