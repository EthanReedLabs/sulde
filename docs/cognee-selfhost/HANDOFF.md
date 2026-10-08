# Cognee 自建共享记忆库 — 会话交接文档

> 交接日期:2026-07-27。来源:GYM 目录下的一次 Claude Code 会话。
> 本文档供新会话/新 agent 接手继续实施,按「待办」小节从阶段 0 开始执行。

## 目标

在 EasePi A1(Docker + 1T 盘)上自建 cognee server,让 Mac mini 与 Windows 的
Claude Code / Codex 共享同一份 AI 记忆库。硬性约束:**数据必须自持,不上传任何
第三方托管服务**(已明确排除 Cognee Cloud);LLM API 调用可接受(内容瞬时经过
智谱服务器,不落库)。

## 已完成(Mac mini, 2026-07-23~27)

| 事项 | 状态 |
|---|---|
| Claude Code 装 `cognee-memory@cognee` v1.0.0 + `understand-anything` v2.9.4 | ✅ 已启用,运行正常 |
| Codex 装 `cognee@cognee` v1.1.0 + `understand-anything`,hooks feature 已开 | ✅ |
| cognee LLM 配置:智谱免费 `glm-4.5-flash`(custom provider,OpenAI 兼容端点 `/api/paas/v4`),已实测 200 | ✅ |
| 嵌入:fastembed 本地(all-MiniLM-L6-v2, 384 维),零外发 | ✅ |
| 配置文件独立化:`~/.config/cognee/env.sh`(chmod 600,含真实 GLM key),`~/.zshrc` 只留一行 source | ✅ |
| 部署方案落盘 | ✅ 见同目录 `deploy-plan.md` |

关键路径(均在 Mac 上,含敏感信息,不在本仓库):
- `~/.config/cognee/env.sh` — cognee 全部 LLM/嵌入配置,`COGNEE_GLM_KEY` 存真实 key
- `~/.config/claude/accounts.sh` — Claude 多账号脚本,`CLAUDE_GLM_KEY`(与上面同值,GLM Coding Plan key)
- `~/.cognee-plugin/` — 插件状态、日志、本地记忆数据

## 待办(按序)

1. **阶段 0**:A1 上跑 `uname -m && free -h && df -h`,确认架构/内存/1T 盘挂载点;路由器给 A1 固定 IP
2. **阶段 1**:按 `deploy-plan.md` 在 A1 部署 server(同目录 `docker-compose.yml` 可直接用,填入 GLM key)
3. **阶段 2**:Mac 客户端切远程(`COGNEE_BASE_URL` + 清 key 缓存)
4. **阶段 3**:Windows 清理旧自建网关 + 装官方插件 + 系统环境变量 + 复制 api_key.json
5. **阶段 4**:双机联通验证 + 备份 cron

详细命令全部在 `deploy-plan.md`,本文不重复。

## 重要背景与坑

- **镜像已确认多架构**:`cognee/cognee:latest` 有 amd64+arm64,A1 无需源码构建
- **Windows 现状(未解决,阶段 3 一并处理)**:该机 `claude`/`codex` 被
  `D:\AIProjects\cognee-project-memory`(用户旧自建记忆网关)的 PowerShell profile
  函数劫持(profile 135-138 行 "Cognee project memory managed block"),其
  `memoryctl service start` 重启后报 `service command failed`(exit 78),导致两个
  CLI 全部不可用。临时解法 `Remove-Item Function:\claude, Function:\codex`。
  决策:不修了,直接退役换官方插件。稳定后可删除整个 `D:\AIProjects\cognee-project-memory`
- **GLM key 复用决策**:用户明确选择 cognee 与 Coding Plan 共用同一个 key
  (曾建议分开,用户拍板"就用这个");配置层面已解耦(env.sh 独立),以后换 key 只改一处
- **免费模型实测结论**:`glm-4.5-flash`/`glm-4-flash` 在 `/api/paas/v4` 和
  `/api/coding/paas/v4` 均 200 可用;付费模型(glm-5.2/4.6)仅 coding 端点可用
  (普通端点余额不足)。embedding 接口两端点均 429(Coding Plan 不含),故嵌入必须本地
- **端点变量名风险**:compose 里 `DATA_ROOT_DIRECTORY`/`SYSTEM_ROOT_DIRECTORY`
  及 `/health` 路径未实测,镜像版本差异报错时对照官方 `.env.template` 调整

## 建议新会话使用的技能

- `planning-with-files`(或 /plan-zh):阶段多、跨机器,适合建 task_plan.md 跟踪
- 部署联调时由 Agent 使用已批准的 A1/Windows 连接直接执行并回读；缺少连接能力时报告
  精确 blocker，等待提供连接或交由对应宿主 Agent 续接，不生成命令清单让用户代跑、回贴。

## 本目录文件清单

| 文件 | 用途 |
|---|---|
| `HANDOFF.md` | 本文档 |
| `deploy-plan.md` | 完整部署方案(阶段 0-4 全部命令) |
| `docker-compose.yml` | A1 用,填 key 后即可 `docker compose up -d` |
| `env.sh.example` | Mac/Linux 客户端配置模板(真实文件在 `~/.config/cognee/env.sh`) |
