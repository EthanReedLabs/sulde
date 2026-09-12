#!/usr/bin/env python3
"""Newline-delimited stdio MCP server for the local Sulde knowledge base."""

from __future__ import annotations

import json
import os
import runpy
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "sulde-kb"
SERVER_VERSION = "0.2.0"
CONTAINERS = ["anti-patterns", "platform-kb", "tech-docs", "case-studies", "work-model"]
PLATFORMS = ["android", "ios", "flutter", "harmonyos", "web", "cross", "none"]
SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts" / "kb"
KB_INDEX_DIR = Path(__file__).resolve().parents[1] / "kb-index"
_DIRECT_RUNTIMES: dict[str, SimpleNamespace] = {}
memory_annotation = SimpleNamespace(**runpy.run_path(str(SCRIPT_DIR / "memory_annotation.py")))

host_capabilities = SimpleNamespace(
    **runpy.run_path(str(SCRIPT_DIR / "host_capabilities.py"))
)
record_observation = host_capabilities.record_observation

event_observer = SimpleNamespace(
    **runpy.run_path(str(SCRIPT_DIR / "event_observer.py"))
)
CORRELATION_KEYS = event_observer.CORRELATION_KEYS
DOMAINS = event_observer.DOMAINS
collect_snapshot = event_observer.collect_snapshot

status_snapshot = SimpleNamespace(
    **runpy.run_path(str(SCRIPT_DIR / "sulde_status_snapshot.py"))
)

kb_cli = SimpleNamespace(
    **runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "hooks" / "lib" / "kb_cli.py")
    )
)


def _force_cli_backend() -> bool:
    return os.environ.get("SULDE_MCP_FORCE_CLI", "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _direct_runtime(name: str) -> SimpleNamespace:
    cached = _DIRECT_RUNTIMES.get(name)
    if cached is not None:
        return cached
    if str(KB_INDEX_DIR) not in sys.path:
        sys.path.insert(0, str(KB_INDEX_DIR))
    path = KB_INDEX_DIR / f"{name}.py"
    loaded = SimpleNamespace(**runpy.run_path(str(path)))
    _DIRECT_RUNTIMES[name] = loaded
    return loaded


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "kb_status",
            "description": (
                "读取 Sulde 后台发布的有界健康快照；返回快照年龄和当前就绪摘要。"
                "深度事件、效果债务和调度诊断应显式运行 doctor，不进入 MCP 成功热路径。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": "kb_search",
            "description": (
                "在制定实现方案前、排查报错或异常行为时查询 Sulde 工程知识库。"
                "请用症状式查询词描述现象；命中后再用 kb_get 读取原文全文，"
                "不要只凭摘要采取行动。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "症状式查询词"},
                    "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 50},
                    "container": {"type": "string", "enum": CONTAINERS},
                    "platform": {"type": "string", "enum": PLATFORMS},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "kb_get",
            "description": (
                "按 kb_search 返回的 doc_id 读取知识原文全文。用于在采纳报错排查、"
                "已知坑或实现方案建议前核对完整依据。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "稳定唯一的知识文档 ID"}
                },
                "required": ["doc_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "kb_related",
            "description": "按 frontmatter related 确定性边查询一跳关联知识。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "稳定唯一的知识文档 ID"},
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                },
                "required": ["doc_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "memory_search",
            "description": "检索 sulde 本地原始会话记忆，返回时间、项目、角色、原文和混合分数。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "要召回的历史主题或原文"},
                    "project": {"type": "string", "description": "优先返回的 cwd basename"},
                    "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 50},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "memory_annotate",
            "description": "批量写入 Claude/Codex 已抽取的记忆实体与关系边。",
            "inputSchema": memory_annotation.input_schema(),
        },
        {
            "name": "memory_graph",
            "description": "只读查询记忆关系声明；可显式按来源项目过滤，结果不是默认事实。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "project": {"type": "string", "minLength": 1},
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
                },
                "required": ["entity"],
                "additionalProperties": False,
            },
        },
        {
            "name": "event_observe",
            "description": (
                "只读查询 Sulde 已声明事件源的统一脱敏观察投影。"
                "受 local / approved-export / disabled 隐私策略约束；"
                "不会读取 L3 原始 provider payload，不会修改、迁移或修复任何事实源。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "domains": {
                        "type": "array",
                        "items": {"type": "string", "enum": sorted(DOMAINS)},
                        "uniqueItems": True,
                    },
                    "providers": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["claude", "codex", "import", "system", "unknown"],
                        },
                        "uniqueItems": True,
                    },
                    "correlation": {
                        "type": "object",
                        "properties": {
                            key: {"type": "string", "minLength": 1}
                            for key in sorted(CORRELATION_KEYS)
                        },
                        "additionalProperties": False,
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 200,
                        "default": 50,
                    },
                    "include_events": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
        },
    ]


def rpc_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def tool_result(value: Any) -> dict[str, Any]:
    return {
        "content": [
            {"type": "text", "text": json.dumps(value, ensure_ascii=False)}
        ]
    }


def tool_error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def run_cli_json(
    tool_name: str,
    subcommand: str,
    arguments: list[str],
    *,
    timeout: float,
    expected_type: type,
    expected_label: str,
) -> tuple[Any, dict[str, Any] | None]:
    result = kb_cli.run_cli(
        repo_root(),
        kb_home(),
        subcommand,
        arguments,
        timeout=timeout,
    )
    if not result.ok:
        detail = (
            result.stderr.strip()
            or result.stdout.strip()
            or result.detail
            or result.status
        )
        if result.returncode is not None:
            return None, tool_error(
                f"{tool_name} backend failed (exit {result.returncode}): {detail}"
            )
        return None, tool_error(f"{tool_name} backend unavailable: {detail}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, tool_error(f"{tool_name} backend returned invalid JSON")
    if not isinstance(payload, expected_type):
        return None, tool_error(
            f"{tool_name} backend returned a non-{expected_label} result"
        )
    return payload, None


def validate_search_arguments(arguments: Any) -> tuple[str, int, str | None, str | None]:
    if not isinstance(arguments, dict):
        raise ValueError("kb_search arguments must be an object")
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("kb_search query must be a non-empty string")
    top_k = arguments.get("top_k", 5)
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 50:
        raise ValueError("kb_search top_k must be an integer between 1 and 50")
    container = arguments.get("container")
    platform = arguments.get("platform")
    if container is not None and container not in CONTAINERS:
        raise ValueError("kb_search container is not a controlled value")
    if platform is not None and platform not in PLATFORMS:
        raise ValueError("kb_search platform is not a controlled value")
    return query.strip(), top_k, container, platform


def kb_search(arguments: Any) -> dict[str, Any]:
    try:
        query, top_k, container, platform = validate_search_arguments(arguments)
    except ValueError as error:
        return tool_error(str(error))
    if not _force_cli_backend():
        try:
            results = _direct_runtime("search").search_results(
                query,
                limit=top_k,
                container=container,
                platform=platform,
            )
            return tool_result(results)
        except Exception as error:
            print(
                f"sulde-kb direct search unavailable; using CLI fallback: {type(error).__name__}",
                file=sys.stderr,
            )
    cli_arguments = [
        query,
        "-k",
        str(top_k),
        "--json",
    ]
    if container:
        cli_arguments.extend(["--container", container])
    if platform:
        cli_arguments.extend(["--platform", platform])
    results, error = run_cli_json(
        "kb_search",
        "search",
        cli_arguments,
        timeout=10,
        expected_type=list,
        expected_label="array",
    )
    if error is not None:
        return error
    return tool_result(results)


def kb_status(arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict) or arguments:
        return tool_error("kb_status takes no arguments")
    snapshot = status_snapshot.read_snapshot(kb_home())
    ready = bool(
        snapshot.get("snapshot_status") == "fresh"
        and snapshot.get("healthy") is True
    )
    return tool_result(
        {
            "schema": "sulde-kb-status-readiness-v1",
            "status": "ready" if ready else "degraded",
            "ok": ready,
            "warn": not ready,
            "authority": "bounded_background_status_snapshot",
            **snapshot,
        }
    )


def kb_get(arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        return tool_error("kb_get arguments must be an object")
    doc_id = arguments.get("doc_id")
    if not isinstance(doc_id, str) or not doc_id.strip():
        return tool_error("kb_get doc_id must be a non-empty string")
    root = repo_root()
    database = kb_home() / "kb.db"
    if not database.is_file():
        return tool_error("KB index database not found; run kb-index build first")
    try:
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT doc_id, title, container, platform, source_path
            FROM chunks WHERE doc_id = ? ORDER BY chunk_id LIMIT 1
            """,
            (doc_id.strip(),),
        ).fetchone()
        connection.close()
    except sqlite3.Error as error:
        return tool_error(f"kb_get database error: {error}")
    if row is None:
        return tool_error(f"kb_get doc_id not found: {doc_id.strip()}")
    try:
        source = (root / row["source_path"]).resolve(strict=True)
        source.relative_to(root.resolve())
        content = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as error:
        return tool_error(f"kb_get source read failed: {error}")
    return tool_result(
        {
            "doc_id": row["doc_id"],
            "container": row["container"],
            "platform": row["platform"],
            "title": row["title"],
            "source_path": row["source_path"],
            "content": content,
        }
    )


def kb_related(arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        return tool_error("kb_related arguments must be an object")
    doc_id = arguments.get("doc_id")
    if not isinstance(doc_id, str) or not doc_id.strip():
        return tool_error("kb_related doc_id must be a non-empty string")
    limit = arguments.get("limit", 10)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        return tool_error("kb_related limit must be an integer between 1 and 50")
    if not _force_cli_backend():
        try:
            return tool_result(
                _direct_runtime("search").related_results(doc_id.strip(), limit)
            )
        except Exception as error:
            print(
                f"sulde-kb direct related unavailable; using CLI fallback: {type(error).__name__}",
                file=sys.stderr,
            )
    results, error = run_cli_json(
        "kb_related",
        "related",
        [
            doc_id.strip(),
            "-k",
            str(limit),
            "--json",
        ],
        timeout=10,
        expected_type=list,
        expected_label="array",
    )
    if error is not None:
        return error
    return tool_result(results)


def memory_search(arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        return tool_error("memory_search arguments must be an object")
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        return tool_error("memory_search query must be a non-empty string")
    project = arguments.get("project")
    if project is not None and (not isinstance(project, str) or not project.strip()):
        return tool_error("memory_search project must be a non-empty string")
    limit = arguments.get("limit", 5)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        return tool_error("memory_search limit must be an integer between 1 and 50")
    if not _force_cli_backend():
        connection = None
        try:
            memory = _direct_runtime("memory")
            connection = memory.connect(ensure_schema=False)
            results = memory.search_memory(
                query.strip(),
                project=project.strip() if project else None,
                limit=limit,
                connection=connection,
                embed_pending_entries=False,
            )
            return tool_result(results)
        except Exception as error:
            print(
                f"sulde-kb direct memory search unavailable; using CLI fallback: {type(error).__name__}",
                file=sys.stderr,
            )
        finally:
            if connection is not None:
                connection.close()
    cli_arguments = [
        query.strip(),
        "-k",
        str(limit),
        "--json",
    ]
    if project:
        cli_arguments.extend(["--project", project.strip()])
    results, error = run_cli_json(
        "memory_search",
        "mem-search",
        cli_arguments,
        timeout=120,
        expected_type=list,
        expected_label="array",
    )
    if error is not None:
        return error
    return tool_result(results)


def memory_annotate(arguments: Any) -> dict[str, Any]:
    try:
        memory_annotation.normalize(arguments, bounded=True)
    except (ValueError, TypeError) as error:
        return tool_error(f"memory_annotation_invalid: {error}")
    if not _force_cli_backend():
        try:
            memory = _direct_runtime("memory")
        except (ImportError, FileNotFoundError) as error:
            # Nothing has entered the writer. A compatibility backend is safe.
            print(
                f"sulde-kb direct memory annotate unavailable; using CLI fallback: {type(error).__name__}",
                file=sys.stderr,
            )
        else:
            connection = None
            try:
                connection = memory.connect()
                return tool_result(memory.annotate_memory(connection, arguments))
            except ValueError as error:
                return tool_error(f"{getattr(error, 'code', 'memory_annotation_invalid')}: {error}")
            except Exception as error:
                # A writer/commit may have been reached. Never repeat the write
                # through another transport; the independent verifier owns recovery.
                return tool_error(f"memory_annotation_unverified: {type(error).__name__}; independent read required")
            finally:
                if connection is not None:
                    connection.close()
    result, error = run_cli_json(
        "memory_annotate",
        "mem-annotate",
        ["--json", json.dumps(arguments, ensure_ascii=False)],
        timeout=10,
        expected_type=dict,
        expected_label="object",
    )
    if error is not None:
        return error
    return tool_result(result)


def memory_graph(arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        return tool_error("memory_graph arguments must be an object")
    entity = arguments.get("entity")
    if not isinstance(entity, str) or not entity.strip():
        return tool_error("memory_graph entity must be a non-empty string")
    project = arguments.get("project")
    if project is not None and (not isinstance(project, str) or not project.strip()):
        return tool_error("memory_graph project must be a non-empty string")
    limit = arguments.get("limit", 10)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        return tool_error("memory_graph limit must be an integer between 1 and 50")
    if not _force_cli_backend():
        connection = None
        try:
            memory = _direct_runtime("memory")
            connection = memory.connect_readonly()
            return tool_result(memory.memory_graph(connection, entity.strip(), limit=limit,
                                                   project=project.strip() if project else None))
        except Exception as error:
            print(
                f"sulde-kb direct memory graph unavailable; using CLI fallback: {type(error).__name__}",
                file=sys.stderr,
            )
        finally:
            if connection is not None:
                connection.close()
    results, error = run_cli_json(
        "memory_graph",
        "mem-graph",
        [
            entity.strip(),
            "-k",
            str(limit),
        ] + (["--project", project.strip()] if project else []),
        timeout=10,
        expected_type=list,
        expected_label="array",
    )
    if error is not None:
        return error
    return tool_result(results)


def event_observe(arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        return tool_error("event_observe arguments must be an object")
    allowed = {"domains", "providers", "correlation", "limit", "include_events"}
    if set(arguments) - allowed:
        return tool_error("event_observe received unknown arguments")
    domains = arguments.get("domains", [])
    providers = arguments.get("providers", [])
    correlation = arguments.get("correlation", {})
    limit = arguments.get("limit", 50)
    include_events = arguments.get("include_events", False)
    if not isinstance(domains, list) or any(domain not in DOMAINS for domain in domains):
        return tool_error("event_observe domains must contain controlled values")
    if not isinstance(providers, list) or any(
        provider not in {"claude", "codex", "import", "system", "unknown"}
        for provider in providers
    ):
        return tool_error("event_observe providers must contain controlled values")
    if not isinstance(correlation, dict) or set(correlation) - CORRELATION_KEYS:
        return tool_error("event_observe correlation contains an unknown key")
    if any(not isinstance(value, str) or not value.strip() for value in correlation.values()):
        return tool_error("event_observe correlation values must be non-empty strings")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        return tool_error("event_observe limit must be an integer between 1 and 200")
    if not isinstance(include_events, bool):
        return tool_error("event_observe include_events must be a boolean")
    try:
        result = collect_snapshot(
            kb_home(),
            domains=domains,
            providers=providers,
            correlations=correlation,
            limit=limit,
            include_events=include_events,
        )
    except (OSError, UnicodeError, ValueError) as error:
        return tool_error(f"event_observe projection failed: {type(error).__name__}")
    if not include_events:
        result = {
            "schema": result["schema"],
            "stateVersion": result["stateVersion"],
            "asOfSeq": result["asOfSeq"],
            "sourceRevision": result["sourceRevision"],
            "generated_at": result["generated_at"],
            "read_only": result["read_only"],
            "authoritative_sources_unchanged": result[
                "authoritative_sources_unchanged"
            ],
            "privacy": result["privacy"],
            "projectionCache": result["projectionCache"],
            "summary": result["summary"],
        }
    return tool_result(result)


def call_tool(params: Any) -> dict[str, Any]:
    if not isinstance(params, dict):
        return tool_error("tools/call params must be an object")
    name = params.get("name")
    arguments = params.get("arguments", {})
    if name == "kb_status":
        return kb_status(arguments)
    if name == "kb_search":
        return kb_search(arguments)
    if name == "kb_get":
        return kb_get(arguments)
    if name == "kb_related":
        return kb_related(arguments)
    if name == "memory_search":
        return memory_search(arguments)
    if name == "memory_annotate":
        return memory_annotate(arguments)
    if name == "memory_graph":
        return memory_graph(arguments)
    if name == "event_observe":
        return event_observe(arguments)
    return tool_error(f"unknown tool: {name}")


def _observe_initialize(message: dict[str, Any]) -> None:
    """Record only a provider-identifiable MCP boundary; never affect RPC."""
    try:
        provider = str(os.environ.get("SULDE_HOST_PROVIDER") or "").strip().lower()
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        client_info = params.get("clientInfo") if isinstance(params.get("clientInfo"), dict) else {}
        client_name = str(client_info.get("name") or "").lower()
        if provider not in {"claude", "codex"}:
            provider = (
                "codex"
                if "codex" in client_name
                else "claude"
                if "claude" in client_name
                else ""
            )
        if provider:
            record_observation(
                provider=provider,
                hook_event="MCPInitialize",
                source=os.environ.get("SULDE_HOOK_OBSERVATION_SOURCE"),
                home=kb_home(),
            )
    except Exception:
        return


def dispatch(message: Any) -> dict[str, Any] | None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        request_id = message.get("id") if isinstance(message, dict) else None
        return rpc_error(request_id, -32600, "Invalid Request")
    if "id" not in message:
        return None
    request_id = message["id"]
    method = message.get("method")
    if method == "initialize":
        _observe_initialize(message)
        client_version = (message.get("params") or {}).get("protocolVersion")
        return rpc_result(
            request_id,
            {
                "protocolVersion": client_version or PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method == "tools/list":
        return rpc_result(request_id, {"tools": tool_definitions()})
    if method == "tools/call":
        return rpc_result(request_id, call_tool(message.get("params")))
    if method == "ping":
        return rpc_result(request_id, {})
    return rpc_error(request_id, -32601, "Method not found")


def write_message(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    for raw_line in sys.stdin:
        if not raw_line.strip():
            continue
        try:
            message = json.loads(raw_line)
        except json.JSONDecodeError:
            write_message(rpc_error(None, -32700, "Parse error"))
            continue
        try:
            response = dispatch(message)
        except Exception as error:  # Protocol loop must survive malformed requests.
            request_id = message.get("id") if isinstance(message, dict) else None
            print(f"sulde-kb internal error: {error}", file=sys.stderr)
            response = rpc_error(request_id, -32603, "Internal error")
        if response is not None:
            write_message(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
