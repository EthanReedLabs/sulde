---
doc_id: "work-model/skills/dev/README"
container: work-model
platform: none
summary: "Claude Code 团队协作技能模板。"
---

# Team Ops Template

Claude Code 团队协作技能模板。支持并行开发、代码审查、Bug 排查、任务指派、崩溃修复、性能诊断、事后沉淀与 UI 精确还原。

## 使用方式

### 1. 复制到项目

```bash
cp -r team-ops-template/skills/ your-project/.claude/skills/
cp team-ops-template/team-config.example.json your-project/team-config.json
```

### 2. 编辑 team-config.json

填写项目信息、开发者名单、目录结构、文档路径、日志命令。

### 3. 配置 hooks

将 `hooks/hooks.json` 的内容合并到项目的 `.claude/settings.local.json` 的 `hooks` 字段中。

### 4. 配置 git alias

```bash
cd your-project
git config alias.as-a '!git -c user.name="Dev A Name" -c user.email="a@company.com" commit'
git config alias.as-b '!git -c user.name="Dev B Name" -c user.email="b@company.com" commit'
git config alias.as-c '!git -c user.name="Dev C Name" -c user.email="c@company.com" commit'
```

### 5. 开启团队模式

在 `.claude/settings.local.json` 中加入：

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

## 8 个 Skill

| 命令 | 场景 | 模式 |
|------|------|------|
| `/parallel-dev` | 多模块并行开发 | 团队（多队友 + worktree） |
| `/code-review` | 代码审查 | 团队（2 队友，架构 + 性能） |
| `/bug-hunt` | Bug 排查 | 团队（3 队友互相讨论） |
| `/assign` | 指派单人任务 | 单人（自动切分支 + 切身份） |
| `/crash-fix` | 崩溃、无响应与编译错误的四阶段证据诊断 | 单人（Android/iOS 双平台） |
| `/perf-diagnose` | 性能诊断门控:实测数值+截图先于 fix | 单人（Android/iOS 工具链分列） |
| `/postmortem` | 沉淀体系 Dev 侧入口:3 问漏斗→反模式登记 | 单人（handoff 给协调端） |
| `/ui-impl` | pen-truth 逐节点 UI 还原与截图 baseline 验证 | 单人（Android/iOS 双平台） |

## 6 个 Hook

| Hook | 触发时机 | 作用 |
|------|---------|------|
| SessionStart | 新会话启动 | 自动读取 CLAUDE.md |
| UserPromptSubmit | 每次输入指令 | 注入规则提醒 |
| PreToolUse | 执行 git commit | 拦截，强制用 alias |
| PostCompact | 上下文压缩后 | 重新读取 CLAUDE.md |
| TaskCompleted | 队友完成任务 | 自动检查提交规则 |
| TeammateIdle | 队友空闲 | 检查剩余任务 |

## 目录结构

```
team-ops-template/
├── README.md
├── team-config.example.json    ← 项目配置模板
├── skills/
│   ├── parallel-dev.md         ← 并行开发
│   ├── code-review.md          ← 代码审查
│   ├── bug-hunt.md             ← Bug 排查
│   ├── assign.md               ← 任务指派
│   ├── crash-fix.md            ← 崩溃快速修复
│   ├── perf-diagnose.md        ← 性能诊断
│   ├── postmortem.md           ← 修复事后沉淀
│   └── ui-impl.md              ← UI 精确还原
└── hooks/
    └── hooks.json              ← 自动化 hooks
```
