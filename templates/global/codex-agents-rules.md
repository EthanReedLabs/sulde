## Sulde 宿主独立纪律
Codex 是完整执行宿主；普通任务直接使用当前宿主能力，不得把 Claude Code CLI、
Claude MCP 或 Claude 用户目录中的 skill 当作前置依赖。经人批准的 Sulde L3 任务由
仓库自有 `agent-runtime.py` 在隔离 worktree 中执行并验收；提供方必须显式选择为当前
可用宿主，不可因另一宿主存在而静默切换。`.codex-agent/` 只是历史兼容的任务工件目录名。

## Codex 派单档位纪律
在 Codex 中生成“给 Dev/Agent 发送”、任务签发/返修或继续原任务时，使用 `$dispatch-task`。
默认只给任务内容、路径和验收要求；沿用目标会话当前配置，不输出 `/model`、`/reasoning`、
型号选择前缀或“无需切换”提示，也不因当前模型未知而阻止派单。
只有用户明确要求模型建议时，才使用 `{SULDE_BIN}/model-dispatch --provider codex ...`
的 `--model-advice` 模式；`capability_tier` 仍是任务元数据，不自动触发交互式切换。
若旧 Skill、模板或已安装生成器仍要求模型/推理前缀，以本段的默认任务正文规则为准，
不要为去掉提示而改写已安装缓存。此规则不改变后台受管 Agent 的模型选择策略。
Codex 派单禁止出现其他宿主的型号或控制命令；目标执行宿主不明确时先问，不按本机安装猜测。

## Sulde 知识库(全项目通用)
本机有一个跨项目工程知识库(290+ 篇:反模式/案例研究/平台KB,android/ios/flutter/harmonyos)。
**何时查**:开始实现方案前、调试报错或异常行为时、怀疑踩到已知坑时。用症状描述查询:
```bash
{KB_CLI} search "<症状描述>" -k 5 --json
# 可选: --platform android|ios|flutter|harmonyos  --container anti-patterns
```
命中后**必须读 `source_path` 指向的原文全文**再采纳(仓库根 `{REPO_ROOT}`);
excerpt 不足以作为行动依据。CLI 不可用时降级读该仓库 `knowledge/INDEX.md` 自行匹配。
**沉淀规则(单写者铁律)**:发现值得沉淀的坑/修复/优化,**禁止直接写入该知识库仓库**;
按 `templates/knowledge/problem-card.md` 把结构化 Layer1 问题卡写进当前任务的汇报/handoff
「沉淀候选」段，记录问题语境、证据状态及路由/执行四类正反样本；证据不足标
`inconclusive`。由协调端统一判重入库。

## 记忆系统状态
怀疑记忆/检索异常时先调 MCP 工具 `kb_status` 查健康度;回忆历史决策用
`memory_search`;标注新知识关系用 `memory_annotate`。

## 记忆里程碑标注
任务收尾若确认了新的根因/依赖/结论，先保存在已授权的任务报告中，再按需调用
`memory_annotate`（或 `{KB_CLI} mem-annotate --json`）补充图谱。显式提供
`extracted_by: codex`；每批最多 6 个实体、3 条边，端点均声明，来源可核验。
这是可选增强：失败时保留问题与请求摘要供独立回读，不盲目换入口重写，也不阻止
与记忆结果无关的业务交付。用户明确要求记忆维护时，未验证登记仍是未完成项。
只有确认任务依据已在任务工件中、确实不依赖图谱时，才可在可读提案中声明
`--memory-dependency independent`；不得为了绕过债务而改变依赖声明。
