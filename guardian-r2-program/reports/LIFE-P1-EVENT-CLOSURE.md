## 结果
✅ LIFE-P1 事件、自修复与 Agent 经验闭环源码及影响面回归通过：`/usr/bin/env -u SULDE_GUARDIAN_STREAM_OWNER PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -B -m unittest -q tests.test_agent_experience tests.test_self_repair tests.test_organ_evolution tests.test_life_cycle tests.test_test_evidence tests.test_event_observer tests.test_operational_readiness tests.test_agent_runtime.AgentRuntimeTests.test_task_report_verdict_accepts_only_consistent_complete_reports tests.test_agent_runtime.H06HSelfContainedEvidenceTests.test_newer_stronger_same_scope_success_supersedes_structured_diagnostic tests.test_agent_runtime.H06HSelfContainedEvidenceTests.test_task_report_verdict_rejects_duplicate_conflicting_or_unbound_success`，exit 0；Ran 136 tests in 3.601s，OK，覆盖版本化事件投影、队列闭合、身份隔离、回读 readiness、Agent 经验、测试证据、并发幂等与 worker report 证据取代正反例；candidate_sha256=b5b601a4c91fad2c66843e8a9ffee0eca2807c0df903d4b33d738f8a6b016be9；execution_binding_sha256=da9119cc8ee4842ca03886db9d5e67cea70d6f56a4743ff039d24deca008e6a1；environment_sha256=c214f142f5ab65044f923683504b42d69fb36e5c530345f3321cc25299f20f10；command_sha256=a46e641556767089eabb1f57f834e17a0d7e75b09cb2f6caa0625fbe7dce1042；count=136

## 过程
report_contract=sulde-worker-report-v1。实现限定在 16 个 owned 源码/测试文件；candidate_sha256 对按路径排序的“路径 + 内容 SHA-256”规范 JSON 清单求值，不包含本报告及协调端预置的 task definition/brief。

- 统一事件仍采用 `sulde-observation-event-v1`，投影缓存 state version 升至 3；observer 接入 self-repair、evolution、life、Agent experience 与 test evidence。历史 invalid/unsupported 原文不改写，分别保留 historical/open/settled 计数；兼容结算只接受 `inconclusive` 或 `superseded`，不生成伪 success。
- self-repair 队列采用 `sulde-self-repair-queue-v2`：问题指纹与 project/session/task-instance 精确作用域组合聚合，记录首次/最近时间、复发次数、三次重试预算、TTL 与五态投影；最近状态按最近观测时间选择。external/destructive/unknown 及仍有 attempt/grant/verification/intervention 的事实优先保持 `unresolved`。
- 正式 continuation 仅在显式 v1 continuation 已加载且 `authority_transferred=false` 时建立新 binding；新 session/lane 的 attempts 从零开始，不复制 grant、effect debt 或 open event。
- `sulde-life-cycle-v2` 分开投影 sense/persist/decide/act/verify、human gates 与 identity resume；各维度依赖 registry 独立回读一致性，scheduler 局部 ready 不会提升为整体 ready。
- 每个 self-repair 受管终态生成 `sulde-agent-experience-v1` 复盘；无问题的 verified 任务也生成记录。证据仅保留摘要与哈希，不保存隐藏推理、完整 prompt、原始工具输出、密钥或私人绝对路径。verified 经验可影响测试策略，inconclusive 仅作诊断提示，unresolved 继续保留；共享接口只产出沉淀候选。
- `sulde-test-evidence-v2` 保存风险、影响图、命令、范围、baseline、结果、耗时与环境摘要；非零、不完整或非通过结论均不可复用。retention 只产出候选，`deletion_performed=false`。
- worker report 增加 `sulde-worker-diagnostic-v1`、`sulde-worker-diagnostic-supersession-v1` 与投影 v1：只有来源更强、时间更新、scope 相同且完整绑定当前 ✅ 证据的显式记录才可取代旧诊断；跨 scope、同强度、旧时间或绑定不一致均保持当前红态。原报告 SHA-256 与已取代诊断摘要保留在投影中，报告字节不改写。
- 协调端提供的非嵌套宿主扩大命令为 `/usr/bin/env -u SULDE_GUARDIAN_STREAM_OWNER PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -B -m unittest -q tests.test_operational_readiness tests.test_intent_guardian tests.test_supervision_lifecycle_e2e`；可观察结果为 308 tests in 56.949s、18 skipped、进程成功。它是同范围、较新的外层证据，用于取代首轮受管宿主诊断；原 worker events/report 保持不变。
supersession_projection={"schema":"sulde-coordinator-evidence-supersession-v1","scope_sha256":"3dcc99d4368fe3e897492c760a7aecea617e676a77e08150ca52e92b6540dc81","superseding_command_sha256":"51fad3c8f991f5a2247d49697a65b0fa349ca91c61f77f829579be5127b1e03d","superseding_source":"coordinator_non_nested_host","observable_result":"308_tests_56.949s_18_skipped_process_success","original_events_preserved":true,"current_conclusion":"superseded"}
retrospective={"schema":"sulde-task-retrospective-v1","task":"LIFE-P1-EVENT-CLOSURE","run":"managed:l3:life-p1-event-closure-r1","problem_type":"event_closure_and_report_projection","symptom":"lifecycle inputs lacked stable closure and historical diagnostics contaminated current verdicts","handling":"added evidence-bound projections, identity scoping, bounded retry, redacted experience, impact-based test evidence and explicit same-scope supersession","outcome":"verified","result":"scoped implementation and selected regression evidence are consistent","evidence":["candidate_manifest_sha256","execution_binding_sha256","command_sha256","coordinator_supersession_projection"],"source_summary":"redacted managed-task facts only","occurred_at":"2026-09-04T15:33:22Z"}

## 遇到的问题
- 前轮报告中的宿主边界诊断会被旧 parser 作为整篇文本的当前结论读取；本轮以结构化 supersession 结论引用，不复写可被旧代解释为当前红态的裸诊断。
- 本轮扩展到 AgentRuntime 全类时，两项既有宿主状态语义断言观测到 `policy_paused`，该组合未进入成功缓存；与本次新增解析逻辑直接相关的三项契约正反例及其七个依赖模块已由上方 136 项命令闭合。
- 初轮负例发现“仅声明 `closure_status=verified` 可绕过证据”和“authority debt 未优先覆盖”的假阳性，最终入口已统一收紧。

## 解决方式
- 在 self-repair、observer、evolution 三个入口统一应用“authority debt 优先、verified 必须有可回读证据”，并补充缺证据、open grant/attempt、unknown effect、跨 session/lane、正式 continuation、并发写入和历史 settlement 正反例。
- worker report 先验证当前 ✅ 的 candidate/execution/environment/command/count 绑定，再投影结构化诊断；取代关系必须同时满足更强来源、更新时序和完全一致 scope，且只屏蔽对应结构行参与当前 verdict，原始报告仍以 digest 可追溯。
- 使用 `compile(source, filename, "exec")` 配合 `-B` 与 `PYTHONDONTWRITEBYTECODE=1` 做无缓存语法检查；最终确认源码树未新增 `__pycache__`。
- 报告写入后独立回读检查六个规定标题、✅ 字段、report verdict、owned path 边界与 `git diff --check`。

## 遗留风险与建议
- 协调端提交前仍建议在非嵌套宿主运行完整 `tests.test_agent_runtime`，重点核对两项既有状态语义断言与生产 hook 的一致性；本任务不修改其非 owned 路由。
- 生产中既有 91 条 invalid、46 条 unsupported 与约 43 条队列记录只定义了兼容投影/结算协议，真实迁移、部署后独立回读和调度验收仍由协调端执行。
- 本任务未提交、合并、推送、安装，未操作生产 scheduler/ledger，也未实现 P2 自动删除。

## 沉淀候选
候选：`same-scope-evidence-supersession-for-worker-reports`；证据状态：verified。问题语境：整篇关键字扫描会让旧宿主诊断污染较新的当前结论。正向路由样本：存在版本化旧诊断与来源更强、时间更新、scope 相同、绑定完整的成功证据时，投影为 superseded 并保留原文 digest。反向路由样本：仅凭后文声称完成，或 scope/时序/来源强度/绑定任一不一致时继续判红。正向执行样本：当前 ✅ 先通过五项绑定校验，再建立一对一 supersession。反向执行样本：删除旧记录、改写旧结论或全局忽略敏感词。建议协调端判重后统一入库；本任务未直接写知识库。
