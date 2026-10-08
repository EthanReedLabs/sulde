---
assignee: existing-dev-session
branch: task/predictive-verification-recovery-20260928
capability_tier: deep
---

# 验证交付恢复与连续派单规则集成

## 当前执行目标

完成双版本正常对照、持久化真实运行证据、校正过期报告，并纳入已写好的连续派单规则。
一次执行到集中独立复核点，不逐测试交还，不以删除失败脚本或登记缺口代替修复。
本任务不是发布任务；任何此前其他任务的推送/安装授权不得用于本任务。

协调端已创建，无需重复 worktree add：
- worktree：`/Users/eric/ClaudePlugin/sulde-pro/.worktrees/predictive-verification-recovery-20260928`
- 分支：`task/predictive-verification-recovery-20260928`
- 基线：`dev@5a2d951a50cea246d52cbc827e0ef63c0053fd7e`
- 目标执行端：原 Dev 会话。保留上下文，先切工作目录并确认合法任务绑定；不伪造 Guardian 映射。

## 已核实基线

2026-09-28 协调端回读 dev 和原任务工作树均干净，均指向 5a2d951。
该提交新增旧收尾任务文件并删除 `tests/test_r3_normal_pair.py`，没有完成双版本验证。
R3-NORMAL-PAIR-REPORT 仍保留“正常对照成立”，STATUS 未补对应更正。
`git diff af3a614 dev -- scripts/` 为空，当前生产代码与已冻结候选等价。

旧脚本可在 `10e3fd4:tests/test_r3_normal_pair.py` 只读参考，不能原样恢复后声称可用。
已核实可复用的 `tests/test_r3_real_entry_chain.py` 为 4/4 通过；它只证明单版本入口。
知识依据为 `work-model/schema-fixture-migration-and-real-execution`（协调端已全文回读）：
夹具启动失败不是产品缺陷，编译/测试名/零测试发现不能证明实际执行。

## 任务顺序和完整边界

### A. 恢复双版本有效验证

读取同目录 `R3-NORMAL-PAIR-CLOSEOUT-TASK.md`，继续执行其“连续实施与验收”第 1–3 节
及测试成本约束。不是重新设计该任务：保留相同正常对照、身份/消费断言和归档要求。
本文件明确替代旧任务的工作树/分支定位；所有操作仅在本次新 worktree。

被测旧版固定为 `fcd28a4b93f7d63df6b3e0445ea538e48e51c8c3`。
被测候选固定为 `5a2d951a50cea246d52cbc827e0ef63c0053fd7e`，报告其与 af3a614 的源码等价性。
同一驱动、断言、夹具逻辑分别在两个新进程与隔离源码/数据根中运行。
驱动/夹具、配置、模块实际路径与摘要都要留证，不能用当前 shell 的导入替代子进程身份。

连续完成：合规正常控制 → 双版本无反馈/有反馈续接 → 真实消费记录及独立探针断言 →
测试驱动失败负控 → 必要的受影响回归。普通夹具问题在本任务内解决；不得重新恢复
“过一项就停”的执行方式。失败/零执行必须传播非零状态，不能只打印结果或固定 return 0。

此处正常送达链中的首 attempt 预期失败属于夹具准备，不是旧缺陷复现。
本轮不新增 EPIPE 等产品故障注入范围，也不因此宣称既有故障注入已通过。
若实测确需修改生产代码，保留最小反例和精确根因证据，标 blocker；不放宽断言或偷改源码。

### B. 校正状态并保留证据

归档使用 Optimus 新唯一目录：
`/Volumes/Optimus/Sulde/tasks/predictive-execution/R3-normal-pair/<新唯一目录>/`。
旧目录、旧失败和报告保留；临时目录销毁前保存两侧命令、输出、退出码、断言、
必要账本/消费记录、合成 stdin、独立探针输出及摘要清单。清单不含自身并独立回读校验。
挂载或写入权限不可用时准确报告，不静默改用系统盘。

追加更正原 R3-NORMAL-PAIR-REPORT 和 STATUS：单版本 4/4 不等于双版本；
5a2d951 撤除脚本不等于通过；历史 R1/R2 夹具失败不能算缺陷基线；已合入/推送不等于 accepted。
新建 `VERIFICATION-RECOVERY-REPORT.md` 写精确候选、测试身份、结果和证据目录。
未知/未测保持未测，不把历史债务、C 层或多样本列为本轮已完成项。

### C. 纳入已有派单规则，不重做设计

规则源工作树（只读）：
`/Users/eric/ClaudePlugin/sulde-pro/.worktrees/dispatch-continuous-execution`。
先读其 `docs/dispatch-continuous-execution.md`，核对五项文件摘要和 source diff；
协调端已确认这些文件在 f932ca8→5a2d951 没有分支漂移。

仅把下列既有变更应用到本次工作树，保留源工作树原状，不切换其分支、不提交其文件：
- skills/dispatch-task/SKILL.md
- skills/coordinator/writing-task-md/SKILL.md
- skills/dev/assign/SKILL.md
- spec/task-authoring.md
- template/_project/docs-hub/00_shared-rules/task-brief.md.template
- docs/dispatch-continuous-execution.md（复制历史记录后追加本次集成身份与结果）

规则摘要：授权内连续完成、两次无新证据换诊断方法、区分旧缺陷/候选修复/无效测试、
按影响选测试、集中独立复核、相邻问题不自动扩范围、明确停止线和权限仍生效。
不是新 Guardian 门禁，不改运行时/审批/任务 parser，不改安装缓存。
如源摘要变化先核实差异归属，不覆盖。此集成不依赖 A 必须通过：A 遇真实阻塞时，
仍可完成已授权的 B/C 并分别报告，禁止用 C 完成掩盖 A 阻塞。

验证：派单相关 28 项回归（test_model_dispatch_contract、test_runtime_provider）和 Skill 结构检查。
优先使用已验证含 PyYAML 的解释器；官方 validator 对 assign 的既有 user-invocable 拒绝
分开记录，不能删除跨宿主元数据凑绿。输入等价的历史证据可复用并列明，不默认全量。
规则实际长任务行为未验证，不把文档/结构检查升级为生产效果证明。

## 允许范围、停止线与交付

允许写本 worktree 的专用双版本测试/必要辅助文件、上述报告/STATUS、C 列出的六项。
不删除既有回归；不改 scripts/、生产合同、账本、源码分类器、模型配置。
未授权：合并 dev/main、push、安装、cachebuster、历史债务处理、真实模型调用、资源删除。
最终提交仅在本任务分支；功能与规则变更分组提交，报告给出完整复核入口。

模型调用预算 0；不跑全量。每次运行有合理进程超时。
同一失败两次无新证据就改诊断方法，不盲重跑/加时/扩大 prompt。
换方法仍无安全进展、缺权限/外部条件或用户停止时，保存检查点并准确交还 blocker。
上下文续接从检查点继续，不重新生成已完成证据。普通失败或阶段通过无需再次派单。

全部本轮项通过：`candidate-awaiting-independent-review`，不能自行 accepted。
存在未过项：`incomplete`，列出已完成与阻塞，不使用“所有可执行工作均完成”概括。
交还后由协调端独立复核再决定合入；本任务文件不授权后续发布动作。

## 协调端复核补充：继续当前 A/B/C，不新建轮次（2026-09-28）

复核 HEAD：`ffc5f7283a875bdf5ebf30a08441178658c7ff3d`，复核前工作树干净。
独立执行 `python3 -B -m unittest tests.test_r3_dual_version_normal -v`，
1.709 秒，old/new 两个子例都在 brief 读取前置失败；这是夹具错误，不是产品缺陷反例。

1. 当前测试只创建 `.codex-agent` 和 fake-provider，再传入 `embed.md` 路径，
   **没有创建 embed.md**。纠正“夹具已创建 brief，但提取树找不到 control root”的归因。
   `agent-runtime.py:read_brief_authority` 已支持该目录内的 local_reuse；不需要改生产解析。
   复用 `test_r3_real_entry_chain.py:_Chain.__init__` 的 brief 写入、0400 权限和状态目录隔离，
   不只补文件后就结束。理解现有读取链属于本任务诊断范围，不是扩大生产修改授权。
2. 当前测试也没有调用 open_prediction/seed_prediction，没有执行正式反馈续接；
   `_check_prediction` 未被调用，不能证明 checked/as_predicted。
   继续完成 A 原定的两条完整正常控制路径、exact-request 消费断言和独立探针，
   复用既有可运行夹具与合规报告；检查真实返回码和任务结论，不仅搜索 DONE 文本。
3. 先更正 B 的错误根因说明；运行前置修好后，连续完成双版本运行和原定证据归档。
   原日志保留，不能把相同错误泛化为“两版本不存在其他差异”。
4. C 的派单规则仍未纳入本分支；按原六文件清单继续完成，与 A 的诊断相互独立。
   即使 A 遇真实外部阻塞，也要完成仍可安全执行的 B/C，再按项报告。

这四点是原验收要求的定位补充，不增加功能、权限、模型调用或测试范围。
本补充由协调端修改，属于预期任务文件差异；Dev 保留并随本任务提交。
直到原交付清单完成或有经过实际排查的停止条件才集中交还，不能在补齐 brief 后再次停工。
