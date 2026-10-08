#!/usr/bin/env python3
"""Read-only corpus acceptance through Codex's installed stdio MCP route.

Starts a new actual server process; it does not reconnect this conversation's
existing MCP process and does not call server functions directly.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    expected_version = sys.argv[1]
    root = Path(__file__).resolve().parents[2]
    projection = subprocess.run(
        ["codex", "mcp", "get", "sulde_kb", "--json"],
        capture_output=True, text=True, check=True, timeout=30,
    )
    route = json.loads(projection.stdout)
    transport = route["transport"]
    assert route["enabled"] is True and transport["type"] == "stdio"
    installed = Path(transport["cwd"]).resolve()
    assert installed.name == expected_version
    assert json.loads((installed / ".codex-plugin/plugin.json").read_text())["version"] == expected_version
    command = [transport["command"], *transport.get("args", [])]
    environment = os.environ.copy()
    environment.update(transport.get("env") or {})
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    cases = [json.loads(line) for line in (Path(__file__).parent / "paraphrases.jsonl").read_text().splitlines()]
    cases = [case for case in cases if case["expected"] == "apply"]
    assert len(cases) == 8 and len({case["expected_doc_id"] for case in cases}) == 8
    requests = [dict(jsonrpc="2.0", id=1, method="initialize", params={
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "sulde-corpus-acceptance", "version": "1"},
    }), dict(jsonrpc="2.0", method="notifications/initialized")]
    for index, case in enumerate(cases):
        requests.extend([
            dict(jsonrpc="2.0", id=2 + index * 2, method="tools/call", params={
                "name": "kb_search", "arguments": {"query": case["query"], "top_k": 3}}),
            dict(jsonrpc="2.0", id=3 + index * 2, method="tools/call", params={
                "name": "kb_get", "arguments": {"doc_id": case["expected_doc_id"]}}),
        ])
    started = time.monotonic()
    run = subprocess.run(command, cwd=installed, env=environment,
                         input="".join(json.dumps(row, ensure_ascii=False) + "\n" for row in requests),
                         capture_output=True, text=True, timeout=120, check=True)
    responses = [json.loads(line) for line in run.stdout.splitlines() if line.strip()]
    by_id = {row["id"]: row for row in responses if "id" in row}
    assert len(by_id) == 17 and len(responses) == 17
    assert by_id[1]["result"]["serverInfo"]["name"] == "sulde-kb"

    def value(identifier):
        row = by_id[identifier]
        assert "error" not in row, row
        result = row["result"]
        assert not result.get("isError"), result
        return json.loads(result["content"][0]["text"])

    verified = []
    for index, case in enumerate(cases):
        hits = value(2 + index * 2)
        doc = value(3 + index * 2)
        ids = [hit["doc_id"] for hit in hits]
        expected = case["expected_doc_id"]
        assert expected in ids, (expected, ids)
        assert doc["doc_id"] == expected
        relative = Path(doc["source_path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        source = (root / relative).read_bytes()
        runtime = (installed / "runtime" / relative).read_bytes()
        returned = doc["content"].encode("utf-8")
        assert source == runtime == returned, expected
        verified.append(dict(doc_id=expected, rank=ids.index(expected) + 1,
                             source_path=relative.as_posix(), content_sha256=sha(returned),
                             source_runtime_mcp_bytes_equal=True))
    generation = json.loads((installed / ".codex-plugin/generation.json").read_text())
    print(json.dumps(dict(schema="sulde-installed-corpus-mcp-acceptance-v1", status="passed",
                         route_source="codex mcp get sulde_kb --json", transport="stdio",
                         server_process="fresh", existing_conversation_reconnected=False,
                         plugin_version=expected_version, generation=generation["generation"],
                         requests=17, search_passed=8, get_passed=8, documents=verified,
                         stderr_sha256=sha(run.stderr.encode()),
                         elapsed_seconds=round(time.monotonic() - started, 3)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
