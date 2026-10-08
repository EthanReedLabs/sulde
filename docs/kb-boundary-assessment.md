# KB 系统边界评估(v0.3.1)

> 日期:2026-07-28。对应版本:sulde-cc v0.3.1(KB 检索层 + WP7 运行时加固)。
> 性质:如实划线——能力上限、降级点、失效点、未验证区。M4(Windows)验证与
> 上游修复落地后更新本文档。

## 1. 规模边界

| 维度 | 当前 | 安全上限 | 越界后果与出路 |
|---|---|---|---|
| 语料量 | 275 docs / 1099 chunks | T1.5(numpy 暴力余弦)约 1 万 chunks(向量 <100MB 内存) | 检索变慢 → 换专用向量库,契约不变(contract §0 预留) |
| T1 目录 | INDEX.md 275 行 | 约千条(agent 上下文可容) | 降级为纯人用目录(contract §7) |
| 全量构建 | 47s | 线性增长,万 chunks 约 5 min | 增量构建不受影响(秒级) |
| 反模式编号 | 0179 | append-only 无上限 | 无 |

## 2. 质量边界

- **召回率**:golden set hit@5 = 83%(tests/kb-golden-eval.py 可复跑)。已知失败
  类型是**词汇断层**(如"文字大小"↔"字号 sp/dp")——512 维小模型 + 标题式
  summary 的联合上限。升级路径:179 条 summary 症状式改写(LLM 批量+人审)+
  recall-log 数据调融合权重。
- **阈值未校准**:注入三闸(SCORE_MIN 0.55 / MARGIN 0.10)与判重线(~0.75)均为
  起步值,需约一周真实日志;当前误注/漏注率未知。
- **excerpt 是线索不是依据**:契约靠"必读 source_path 原文"铁律兜底——依赖
  agent 遵守,非机械保证。

## 3. 平台与运行环境边界

| 环境 | 状态 |
|---|---|
| macOS + Claude Code 交互 | ✅ hook 级全验证（Agent 驱动真实宿主 canary 并自动回读；人只处理原生高风险确认） |
| macOS + codex 交互 | ✅ MCP 实调验证(首次需批一次审批) |
| `claude -p` headless | ❌ 插件 hook 不触发(实测稳定复现,与官方文档矛盾)——CI/脚本无自动注入,主动 CLI 不受影响 |
| `codex exec` 非交互 | ⚠️ MCP 工具被审批机制取消(上游 openai/codex#16685/#24135),AGENTS.md CLI 通路兜底 |
| Windows | ❓ 完全未验证(M4):venv 自举/python 命名/hook 执行/jieba 缓存路径 |
| Linux | ❓ 未测,风险低(纯 python 标准栈) |
| 全新机器 bootstrap | ⚠️ 无 HF 缓存时首次下载 ~100MB,国内需 `HF_ENDPOINT`;网络路径未实测 |

## 4. 时效边界

- **知识分发非实时**:沉淀 → merge → 各端 plugin update/git pull → 下个会话
  SessionStart 保鲜重建。端到端延迟 = 人工更新频率。实时通道待 A1 记忆线。
- **会话中途盲区**:会话进行中合入的新知识,本会话不可见(保鲜仅在 SessionStart)。
- **codex 记忆面不可靠**(上游 cognee-integrations#303 未修):codex 会话内容
  进永久图当前 100% 失败(数据滞留 pending 未丢),跨会话召回缺 codex 侧最近内容;
  Claude Code 端记忆正常。

## 5. 架构假设边界(违反假设即失效)

1. **单写者假设**:协调端唯一。多人并行当协调端时判重盲区与编号竞争回归——
   届时需中心化写入服务。
2. **git 能力假设**:贡献者会用 git。扩展到非 git 用户需表单→自动 PR 写入口
   (方案已备,未实施)。
3. **dev 硬拦是纪律+兜底,非铁壁**:硬拦依赖 .sulde-config.yaml role 声明;
   无配置项目仅 advisory;最后防线是 doc_id lint + INDEX 合并冲突(commit 时
   显式失败,而非写入时)。
4. **脱敏最终靠人**:检查表与 lint 不识别语义泄敏,PR 审核者是最终把关。

## 6. 未实施区(设计已备、代码未写)

`kb.related` 图关系(待 A1 + 抽取 PoC)/ kb_shared 入图(同前)/ 跨机 HTTP MCP
(本机 stdio 已通)/ related 候选生成脚本 / codex skill 包装(A-4)/
summary 症状式升级批。

## 7. 置信度总结

- **高置信可用**:macOS 双端交互场景的检索/注入/沉淀全链路。
- **已知降级可接受**:headless、codex 非交互、分发时效。
- **悬空区**:Windows(未碰)、codex 记忆同步(上游 #303)。
