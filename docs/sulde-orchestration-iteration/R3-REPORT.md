# R3-REPORT — 编排迭代 R3 五项边界定向返修

- 任务：`sulde-orchestration-iteration-r3` rev 1（R3-TASK.md）
- 被审查 HEAD：`c81520254c8c3f57b37a8612c381975c57c5355e`（树 `1c19675a…`）；基线 dev：`9936c7b`
- R3 候选提交：`14649d5`（R3-01/02）→ `2a05dc0`（R3-03）→ `7d1dafc`（R3-03/04/05 runtime）→
  `a114e58`（R3 回归测试）→ 本文档提交
- 状态：**R3 候选待协调者独立复核**

## 0. 反例固化（reviewed HEAD 上实测失败，证据存 Optimus R3/）

- `counterexample-r3-01-02-head.txt`：A-only 声明 + certify 标志 → coverage=complete、
  reclaimable=1，B 租约仍活跃。
- `counterexample-r3-02b/02c-head.txt`：计划后声明目录消失 → apply 经 lease_guard 静默重建
  空目录并删除目标（含"删除后目标已不存在"回读）。
- `counterexample-r3-04-head.txt`：timeout → --retry → timeout → 同一 --retry 重申 →
  启动数 1/2/3。
- `counterexample-r3-05-head.txt`：失败任务第 2 次重放正确，第 3/4 次退化为
  awaiting_human/task_conclusion_unresolved。
- R3-03：HEAD 无任何 admission fence（协议缺失本身即反例；修复后由围栏生命周期测试覆盖）。
- 以上反例已全部固化为 `tests/test_orchestration_r3.py` 的永久回归（12+3 例）。

## 1. 逐项返修

### R3-01 覆盖证明不得退化为布尔声明 ✅（安全缺口关闭；自动回收能力未交付）

- **根因**：certify 布尔是调用方自签声明，无法与任何权威来源独立核对——本架构不存在
  工作区全局注册表，完整性证明不可构造。
- **最小变更**：删除 `certify_scope_coverage` 参数与 CLI `--apply/--certify-scope-coverage`
  入口；`reclaimable` 恒为 false（原因写明"closed"）；行级 `eligible` 诊断保留。apply 函数
  整体删除——模块与 CLI 所有真实入口同语义拒绝。**明确区分：安全缺口已关闭；自动回收
  能力未交付**（不自称全功能完成）。
- **回归**：B 活跃 + A-only 声明 → 不可回收且目标存活；消失 scope 不可重建、无删除；CLI
  两 flag 均 argparse 拒绝；eligible 随引用释放翻转（诊断有效）。

### R3-02 apply 验证原引用目录、禁止补建空证明 ✅

- **根因**：lease_guard 无条件 mkdir——回收方把"目录消失"抹成"空目录=无引用"。
- **最小变更（R3 followup 更正）**：实际交付的安全改善是**关闭实际回收入口**（apply
  函数与 CLI apply 路径整体删除）——消失目录无从被重建，目标保持存活（回归含回读断言）。
  初版报告曾表述 lease_guard 增加 create 语义分离；该编辑未进入提交，现源码无此接口，
  按实际代码更正（规划器本身严格只读）。
- **回归**：`test_vanished_declared_scope_stays_vanished`、
  `test_vanished_scope_is_never_recreated_and_nothing_is_deleted`。

### R3-03 检查与切换共享有效准入边界 ✅

- **根因**：租约准入不参与 deployment lock——最终复检之后、代际切换之前的窗口无协议保护。
- **最小变更（代际 fencing）**：block 策略下，安装器在**首次生产变更前**原子写入 in-switch
  fence（旧/新代际绑定）；运行时租约准入（生产 codex 路径，installed authority 已加载处）
  读取 fence：携带被替代代际的运行在 fence in-switch 期间**拒绝准入**（无启动、记录失败
  状态）；提交成功/失败回滚/recover_only 均清除 fence——准入即时恢复，不自锁。锁顺序：
  deployment lock（全程）→ fence 为原子标记（无长全局锁）；observe 模式无 fence、只报告
  观测不伪装阻断；兼容并存正例不受阻断。
- **回归**：fence 单元（拒绝被替代代际/放行目标代际/缺失·committed·损坏不阻断）+ 真实
  install 链断言"fence 在变更阶段为 in-switch、失败后清除" + recover_only 清除遗留 fence。

### R3-04 重试操作身份稳定、失败后重复也幂等 ✅

- **问题（已复现）**：同一 `--retry` 重申 → 启动数 1→2→3。
- **根因**：重试没有独立操作身份，"latest attempt +1"由标志位推导。
- **最小变更**：注册表新增 `dispatch.retry` 行：`--retry-op <id>` 首次调用绑定
  (from_attempt, from_run_id) 并开启下一 attempt；**同一操作身份永远解析到它自己的
  attempt**——其自身失败/超时后重复也只回放该结论；第三次尝试必须新的重试操作身份；
  错误 predecessor、同身份异内容 = 冲突；活跃链/已完成链拒绝注册。
- **回归**：注册表层 5 例（含失败重试重复不进位、新身份才进位、错误 predecessor 冲突、
  活跃/完成拒绝）+ CLI 层 timeout→--retry→同 --retry 启动数恒 2。

### R3-05 恢复结论持久化、多次回放不破坏原事实 ✅

- **问题（已复现）**：失败任务第 2 次重放正确、第 3 次起退化为 awaiting_human。
- **根因**：恢复 close 未补齐结论；回放覆写 status 文件并把 `run=<id>` 改写为
  `duplicate_of_run=<id>`，对账失去可识别来源。
- **最小变更**：对账 close 携带从原始 status 事实独立求得的结论（run=<id> 精确匹配）；
  回放**不改写**原始 status 文件——重复回执写入独立 append-only
  `{slug}.status.duplicate-replay.log`；真实未知仍为 unknown，不用旧成功猜测另一 run。
- **回归**：失败/超时/成功三类任务，各 4 次提交（含每轮丢弃 closed 行强制走恢复 close）：
  结论恒定、启动数恒 1、原始 status 字节不变、收据逐次留痕。

## 2. 测试与性能

- 新增 `tests/test_orchestration_r3.py` 15 例；修正 phase3/r1/r2 受 API 演进影响的用例。
- 定向全绿：五套件 99 例；受影响链（agent_runtime / codex_plugin_install /
  install_transaction_journal / candidate）157 例全绿。
- **影响矩阵 → 全量必要**（共享状态机/schema 变更）：最终全量结果见 §4。
- **性能（交叠配对 vs R2 head `c815202`；样本存 `R3/paired-ab-perf.txt`）**：
  - 正常成功：base 0.759s vs R3 0.764s（Δ=+5ms）
  - **恢复续接**（缺回执 → 对账 → 终态回放，无重启）：base 0.309s vs R3 0.309s（Δ=0）
  - 均在冻结预算内。R2 head 的 timeout 单次路径不作为恢复性能口径（R3-TASK §5.5）。

## 3. 与 R2 结论的更正关系

- R2-04"✅"收窄：R2 的覆盖证明依赖调用方布尔认证（R3-01 反例可绕过）；R3 改为安全关闭。
- R2-02"✅"收窄：R2 的 --retry 无稳定操作身份（R3-04 反例：失败后重复进位）；R3 改为
  显式重试操作身份。
- R2-01 保持，但恢复 close 的结论持久化缺口（R3-05）在 R3 补齐。
- STATUS.md 已同步；历史报告与中间失败证据保留不覆写。

## 4. 全量回归与披露

- 最终全量（官方入口，所测代码树 `a114e58`）：**2567 例（2453 基线 + 114 新增）**；
  失败恰为 §3 所列 3 项基线既有失败（sandbox-exec error、distill-conflict、encoding-guard
  4 处既有违规），**零新增失败**。上轮 R2 报告的真实宿主 45s 超时在本轮全量中未复现
  （该用例本轮通过），其归因仍维持 inconclusive、不据此改写 R2 记录。
- 代码树未变证明：全量后仅测试文件与文档变化——
  `git diff a114e58 HEAD --stat -- scripts/ tools/` 为空；
  tests/ 仅 `test_orchestration_phase1.py` 的 retry-op 用例对齐（+27/−2）。
- 候选 HEAD：`a632aa5`（树摘要 `git rev-parse a632aa5^{tree}` 可独立回读）。
- 基线既有失败（sandbox-exec、distill-conflict、encoding-guard 4 处）继续逐项保留记录，
  不称全绿；R2 报告的真实宿主 45s 超时结论仍为 inconclusive（本轮未复现亦未归因，
  按 R3-TASK §5.6 保留原失败）。
- 未验收项延续：C 层真实宿主升级/回滚演练、Windows、自动回收能力（本轮安全关闭）。

## 5. 证据与工作树

- Optimus：`/Volumes/Optimus/Sulde/tasks/sulde-orchestration-iteration/R3/`
  （五项反例 HEAD 实测输出、配对 A/B 原始样本、最终全量输出；哈希清单
  `R3-evidence-sha256.txt` 不含自身，摘要见下）。
- 沉淀候选（未写正式知识库）："回收安全依赖覆盖证明可构造性——无权威工作区注册表时，
  共享目标删除应整体关闭而非提供可绕过入口"；"幂等操作身份必须由调用方稳定供给，
  推导自可变状态的标识会随状态进位"。
- 工作树：文档提交后干净；未合并、未推送、未生产安装、未删除真实代际。
