## Sulde 宿主独立纪律
Claude Code 是完整执行宿主；普通任务直接使用当前宿主能力，不得把 Codex CLI、
codex MCP 或 `codex-agent` skill 当作前置依赖。经人批准的 Sulde L3 任务由仓库自有
`agent-runtime.py` 在隔离 worktree 中执行并验收；提供方必须显式选择为当前可用宿主，
不可因另一宿主存在而静默切换。`.codex-agent/` 只是历史兼容的任务工件目录名。

## 记忆里程碑标注(蒸馏第二层)
任务收尾/根因确认/重要决策落定时,趁上下文还热,顺手把本次确认的实体关系落图:
`{KB_CLI} mem-annotate --json '<JSON字符串>'`(或 --file <路径>;
JSON 含 entities、edges 和显式 extracted_by: claude；每批最多 6 个实体、3 条边，端点均声明，宁缺毋滥);
跨项目可复用的教训按 `templates/knowledge/problem-card.md` 追加结构化 Layer1 问题卡到
`{KB_HOME}/distill-candidates.md`(末项标"待 /sediment 处理")，至少记录问题语境、
证据状态和路由/执行四类正反样本；证据不足写 `inconclusive`，不得猜根因。
只在有真结论时做；任务事实先保存在已授权的任务报告中，图谱是可选增强。
重复请求按事务回执确认；类型或来源冲突不能覆盖。失败时保留请求摘要供独立回读，
不盲目换入口重写，不阻断无关业务交付。明确要求记忆维护时，未验证登记仍未完成。
仅在任务工件已保存依据、任务确实不依赖图谱时，才可在可读提案中声明
`--memory-dependency independent`，不得借此绕过相关债务。
