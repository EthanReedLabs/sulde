# Sulde MCP 0.2.0

**English** | [简体中文](MCP.zh-CN.md)

This is the first public release of Sulde's local MCP server, `sulde-kb`. It uses
newline-delimited JSON-RPC over **stdio** and negotiates MCP **2024-11-05**. Clients
must support that revision; HTTP/SSE hosting is not included. The `mcp-v0.2.0` tag
versions this component independently of the Claude and Codex plugin manifests.

Sulde is independently developed. Source is available for noncommercial use under
[PolyForm Noncommercial 1.0.0](../LICENSE); see the [licensing guide](LICENSING.md).

## Download and install

Download `sulde-mcp-0.2.0.tar.gz` or `sulde-mcp-0.2.0.zip` from the
[GitHub Release](https://github.com/EthanReedLabs/sulde/releases/tag/mcp-v0.2.0).
Both contain the same source tree, including the MCP entry point, shared runtime,
empty knowledge manifest, tests, license notices, and bilingual documentation.
Python packages, models, and personal runtime data are not bundled. `SHA256SUMS`
identifies the archives; `release-manifest.json` records the source commit and
validation scope. Verify your download before extracting it:

```sh
# macOS / Linux: download SHA256SUMS alongside the archive, then compare its digest.
shasum -a 256 sulde-mcp-0.2.0.tar.gz
tar -xzf sulde-mcp-0.2.0.tar.gz
cd sulde-mcp-0.2.0
```

Use Python 3.10+ with SQLite FTS5 support and a data directory dedicated to this
installation. Dependency wheels must be available for your Python/platform.
Run the following from the extracted directory:

```sh
export SULDE_KB_HOME="$HOME/.local/share/sulde-mcp"
python3 -m venv "$SULDE_KB_HOME/venv"
"$SULDE_KB_HOME/venv/bin/python" -m pip install -r tools/kb-mcp/requirements.txt
"$SULDE_KB_HOME/venv/bin/python" -B scripts/kb/kb-index build
"$SULDE_KB_HOME/venv/bin/python" -B scripts/kb/kb-index mem-init
```

For PowerShell, extract the ZIP and use:

```powershell
$env:SULDE_KB_HOME = Join-Path $env:LOCALAPPDATA "SuldeMCP"
py -3 -m venv "$env:SULDE_KB_HOME\venv"
& "$env:SULDE_KB_HOME\venv\Scripts\python.exe" -m pip install -r tools/kb-mcp/requirements.txt
& "$env:SULDE_KB_HOME\venv\Scripts\python.exe" -B scripts/kb/kb-index build
& "$env:SULDE_KB_HOME\venv\Scripts\python.exe" -B scripts/kb/kb-index mem-init
```

These commands create empty local indexes and do not install host hooks, background
schedulers, or global launchers. An empty corpus does not need model weights.
Indexing documents or searching populated memory can download the configured
FastEmbed models; dependencies are downloaded during `pip install`.

## Connect a stdio MCP client

Replace all three absolute paths below with your installation paths. This common
`mcpServers` JSON shape is an example; use your client's documented configuration
format. Launch the server as a subprocess, without a shell wrapper:

```json
{
  "mcpServers": {
    "sulde_kb": {
      "command": "/absolute/data/sulde-mcp/venv/bin/python",
      "args": ["-B", "/absolute/install/sulde-mcp-0.2.0/scripts/kb/kb-mcp"],
      "env": {"SULDE_KB_HOME": "/absolute/data/sulde-mcp"}
    }
  }
}
```

On Windows, use the venv's `Scripts/python.exe` and JSON-escaped Windows paths.
The client performs `initialize`, sends `notifications/initialized`, then uses
`tools/list` and `tools/call`. Closing stdin ends the server. Diagnostics go to
stderr; stdout is reserved for MCP messages. Protocol behavior follows the
[MCP lifecycle](https://modelcontextprotocol.io/specification/2024-11-05/basic/lifecycle)
and [stdio transport](https://modelcontextprotocol.io/specification/2024-11-05/basic/transports).

## Available tools

| Tool | Purpose and prerequisite |
| --- | --- |
| `kb_status` | Read the background health snapshot. Without a snapshot, reports degraded/missing rather than full host readiness. |
| `kb_search` | Search the local knowledge index; requires `kb-index build`. |
| `kb_get` | Read a matching document's original source inside this installation. |
| `kb_related` | Read one-hop frontmatter relationships from the knowledge index. |
| `memory_search` | Search existing local session entries; requires an initialized memory database. |
| `memory_annotate` | **Writes** bounded entities/relationships with `extracted_by`; supplied source entry IDs must exist, while null sources remain unverified. |
| `memory_graph` | Read recorded memory relationships; returned declarations still need source verification. |
| `event_observe` | Read redacted event projections under the configured privacy policy; may maintain a derived cache, without changing authoritative event sources. |

Fresh indexes contain no personal documents or sessions, so searches return no
results. MCP access does not automatically collect a client's chat history.
Session ingestion, background status production, and complete task supervision
need their separately configured Sulde workflows and host adapters.

Example calls after initialization:

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"kb_status","arguments":{}}}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"kb_search","arguments":{"query":"stale cache refresh","top_k":5}}}
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"event_observe","arguments":{"limit":10}}}
```

## Add your own knowledge

The index reads the installation's `knowledge/MANIFEST.json`; copying Markdown
without updating that manifest does not make it searchable. In your own writable
copy, add reviewed documents with the required frontmatter under the supported
knowledge containers. See the [Knowledge Kit](KNOWLEDGE-KIT.md). Refresh the manifest
from the root of that copy, then run `kb-index build` again with the same data root:

```sh
python3 -B - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, "tools/kb-index")
from corpus_manifest import build_manifest, write_manifest
root = Path.cwd()
containers = ("anti-patterns", "platform-kb", "tech-docs", "work-model")
paths = [p.relative_to(root) for c in containers
         for p in (root / "knowledge" / c).rglob("*.md")
         if p.name not in {"INDEX.md", "README.md"}]
write_manifest(root, build_manifest(root, paths))
PY
"$SULDE_KB_HOME/venv/bin/python" -B scripts/kb/kb-index build
```

Case studies live under `knowledge/tech-docs/` with `container: case-studies`.
Keep your data root paired with its source tree so document IDs and source paths
remain valid. Use a fresh data directory when testing another release.

## Release scope

This release exposes knowledge, memory, status, and event tools. Task dispatch,
isolated L3 execution, permission decisions, and acceptance/rework remain framework
CLI and host-adapter capabilities; an MCP connection alone does not provide them.
See the [architecture](../README.md#architecture) and [host contract](dual-runtime-contract.md).

The initial release is validated on macOS arm64 with Python 3.10. Its source and
launcher are portable, but this release does not claim native Windows/Linux
installation or full Claude/Codex supervision acceptance. There is no hosted
service, npm/PyPI publication, or MCP Registry registration in this release.

Each tool sends its result to the connected client. Select a data directory whose
contents may be shared with that client and retain its permission controls for
`memory_annotate`. Private knowledge, memories, credentials, models, production
logs, and receipts are excluded from the release; see the
[public data boundary](PUBLIC-DATA-BOUNDARY.md).
