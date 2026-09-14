# Sulde MCP 0.2.0

[English](MCP.md) | **简体中文**

这是 Sulde 本地 MCP 服务 `sulde-kb` 的首次公开发布，使用按行分隔的 JSON-RPC，通过
**stdio** 通信，协商 MCP **2024-11-05** 协议。客户端需要支持该版本；本次不提供
HTTP/SSE 服务。`mcp-v0.2.0` 标签独立标识 MCP 组件，与 Claude/Codex 插件版本分开。

Sulde 由个人独立开发，源码按 [PolyForm Noncommercial 1.0.0](../LICENSE) 提供，供非商业
使用；具体范围见[许可说明](LICENSING.zh-CN.md)。

## 下载与安装

从 [GitHub Release](https://github.com/EthanReedLabs/sulde/releases/tag/mcp-v0.2.0)
下载 `sulde-mcp-0.2.0.tar.gz` 或 `sulde-mcp-0.2.0.zip`。两者包含相同源码树，包括 MCP
入口、共享运行时、空知识清单、测试、许可声明和中英文文档；不内置 Python 依赖包、模型
或个人运行数据。`SHA256SUMS` 标识压缩包字节，`release-manifest.json` 记录源码提交与
验证范围。下载后先核对摘要，再解压：

```sh
# macOS / Linux：同时下载 SHA256SUMS，将以下结果与其中的对应行比对。
shasum -a 256 sulde-mcp-0.2.0.tar.gz
tar -xzf sulde-mcp-0.2.0.tar.gz
cd sulde-mcp-0.2.0
```

需要 Python 3.10+、支持 FTS5 的 SQLite，以及当前 Python/平台可用的依赖包。为这次
安装选择独立数据目录，从解压目录执行：

```sh
export SULDE_KB_HOME="$HOME/.local/share/sulde-mcp"
python3 -m venv "$SULDE_KB_HOME/venv"
"$SULDE_KB_HOME/venv/bin/python" -m pip install -r tools/kb-mcp/requirements.txt
"$SULDE_KB_HOME/venv/bin/python" -B scripts/kb/kb-index build
"$SULDE_KB_HOME/venv/bin/python" -B scripts/kb/kb-index mem-init
```

PowerShell 用户解压 ZIP 后执行：

```powershell
$env:SULDE_KB_HOME = Join-Path $env:LOCALAPPDATA "SuldeMCP"
py -3 -m venv "$env:SULDE_KB_HOME\venv"
& "$env:SULDE_KB_HOME\venv\Scripts\python.exe" -m pip install -r tools/kb-mcp/requirements.txt
& "$env:SULDE_KB_HOME\venv\Scripts\python.exe" -B scripts/kb/kb-index build
& "$env:SULDE_KB_HOME\venv\Scripts\python.exe" -B scripts/kb/kb-index mem-init
```

这些命令建立空的本地索引，不安装宿主 Hooks、后台调度器或全局 launcher。空知识库不需要
模型权重；索引文档或搜索已有记忆时可能下载配置的 FastEmbed 模型，Python 依赖在
`pip install` 阶段下载。

## 接入 stdio MCP 客户端

将以下三个绝对路径替换为自己的安装路径。这里展示常见的 `mcpServers` JSON 格式，实际
配置以客户端文档为准。客户端直接启动服务子进程，无需 shell 包装：

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

Windows 使用 venv 下的 `Scripts/python.exe`，并按 JSON 规则转义路径。客户端先发送
`initialize`，再发送 `notifications/initialized`，之后调用 `tools/list` 和 `tools/call`。
关闭 stdin 即结束服务；诊断写入 stderr，stdout 只输出 MCP 消息。协议依据见
[MCP 生命周期](https://modelcontextprotocol.io/specification/2024-11-05/basic/lifecycle)与
[stdio 传输](https://modelcontextprotocol.io/specification/2024-11-05/basic/transports)。

## 可用工具

| 工具 | 用途与前置条件 |
| --- | --- |
| `kb_status` | 读取后台健康快照；没有快照时返回 degraded/missing，不冒充完整宿主已就绪。 |
| `kb_search` | 搜索本地知识索引，需要先执行 `kb-index build`。 |
| `kb_get` | 读取本次安装目录中匹配文档的原文。 |
| `kb_related` | 查询知识索引中由 frontmatter 定义的一跳关系。 |
| `memory_search` | 搜索已有本地会话条目，需要已初始化的记忆数据库。 |
| `memory_annotate` | **写入**有限实体/关系，需声明 `extracted_by`；提供的来源条目 ID 必须存在，空来源保持未验证。 |
| `memory_graph` | 读取记忆关系声明，结果仍需核对来源。 |
| `event_observe` | 按隐私策略读取脱敏事件投影；可能维护派生缓存，不改动权威事件源。 |

全新索引没有个人文档或会话，搜索会返回空结果。MCP 接入不会自动采集客户端聊天历史；
会话导入、后台状态生成和完整任务监督，需要另行配置 Sulde 工作流与宿主适配器。

初始化后的调用示例：

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"kb_status","arguments":{}}}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"kb_search","arguments":{"query":"缓存刷新旧数据覆盖","top_k":5}}}
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"event_observe","arguments":{"limit":10}}}
```

## 添加自己的知识

索引以安装目录中的 `knowledge/MANIFEST.json` 为准，只复制 Markdown 而不更新清单，不会
使文档进入检索。在自己的可写副本中，按[知识工具箱指南](KNOWLEDGE-KIT.md)将带有完整
frontmatter 的已审核文档加入支持的知识容器。在该副本根目录刷新清单，再使用相同数据根
重建索引：

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

案例研究放在 `knowledge/tech-docs/` 下，使用 `container: case-studies`。数据根应与对应的
源码树配对，以保持文档 ID 和来源路径有效；验证另一版本时使用新的数据目录。

## 发布范围

本版通过 MCP 暴露知识、记忆、状态和事件工具。任务派单、隔离 L3 执行、权限决策与验收
返修仍由框架 CLI 和宿主适配器提供，单独连上 MCP 不会获得这些完整能力。参见
[架构](../README.zh-CN.md#架构)与[双宿主契约](dual-runtime-contract.md)。

首版在 macOS arm64、Python 3.10 上验证。源码和 launcher 可跨平台，但本次不声称已通过
原生 Windows/Linux 安装或完整 Claude/Codex 监督验收。本次不提供托管服务，不发布到
npm/PyPI，也不登记 MCP Registry。

工具结果会交给所连接的客户端。请选择允许该客户端读取的数据目录，并保留客户端对
`memory_annotate` 的权限控制。发布物不含私有知识、记忆、凭据、模型、生产日志或回执，
详见[公开数据边界](PUBLIC-DATA-BOUNDARY.md)。
