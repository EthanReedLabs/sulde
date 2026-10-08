# G0 兼容止血与既有 P0 边界复验

## 范围结论

G0 只修复两个仍可复现的确定性缺陷，并复验已经进入基线的 PermissionRequest
双时钟、worktree 生命周期和 0400/0644 两阶段物化；没有重写生产账本、安装
cache runtime 或改变真实外部写入的 fail-closed 语义。

## 已解决问题

### FG0-001：当前审批 revision 覆盖历史 effect subject revision

- 旧 v4 binding 只有当前审批的 `intent_revision`。历史 attempt 在 revision 3，
  当前原生审批在 revision 13 时，resolved 事件正确保留 revision 3，但 receipt
  producer 错误要求它等于 13。
- 新 v5 binding 保留当前 `intent_revision` 作为审批/CAS 身份，同时密封
  `effect_attempt_id` 与 `effect_subject_intent_revision` 作为被处置对象身份。
- receipt 只接受完全匹配的 v5 subject。v3/v4 历史 binding 保持只读兼容：只有同一
  intervention、intent、lane、decision、actor 的唯一 resolved 事件才可恢复。
- 当前审批 r7 结算历史 subject r3、v4 历史恢复、v3 supersede 均有独立回归。

### FG0-002：read attempt 被错误纳入物化阻断集合

- `blocking_attempts` 原先先检查 `replay_authoritative`，导致迁移后的只读 attempt
  即使已系统 abort，仍可能成为 unrelated local write 的 blocker。
- 现在 `effect == read` 在物化/readiness 阻断投影入口即被排除；attempt、
  intervention 和 append-only 审计历史仍完整保留。
- `external_write`、`destructive` 和 unknown effect 的阻断规则没有放宽。

### FG0-003：根 workspace 路径合同与 repository-local worktree 自锁

- revision 140 的逻辑路径合法，但 Hook 看到的绝对目标带
  `.worktrees/guardian-runtime-control-plane/` 前缀，首次补丁在执行前被拒绝且没有
  产生半成品。
- revision 141 只补充同一 task worktree 内七组等价物化路径；目标、验收、风险和
  禁止项不变。之后代码只在 task branch 写入。
- 补丁工具不继承终端 workdir 的一次误落盘已逐项迁移；根 `main` 工作树恢复 clean，
  task worktree 保留唯一差异。

## 已复验的基线能力

- PermissionRequest：`reassess_at` 与 `expires_at` 独立，五分钟只进入 reassessment，
  不产生 authority；过期后必须新 request。
- Git/worktree：`agent-runtime.py provision/commit/merge` 是受控入口，`.git` 不进入
  普通 owned paths。
- completion evidence：Git 可移植 0644 与运行时 0400 分开建模；完整 digest 预检后
  才执行两阶段 owner-read-only 物化。

## 验证结果

- G0 journal/intervention/readiness/approval：205/205 通过。
- approval timeout、guardian program、agent runtime：147/147 通过。
- 全量首轮：1383 项中 1368 通过、5 skip、10 失败；失败均来自测试入口环境：源码
  `py_compile` 生成 `__pycache__`、系统 Python 缺 `numpy/pyyaml`、当前 sandbox 的
  OS-isolation 探测语义。
- 使用官方 KB venv、Python `-B` 和无 bytecode 隔离副本重跑全部失败覆盖：49/49
  通过、2 skip。没有 G0 产品回归。

后续 G6 必须从 bytecode-free staged tree 使用声明依赖执行，不把“删除当前
`__pycache__`”变成扩大 destructive 权限的隐含前置条件。

## 未做事项

- 未安装、未切换 scheduler、未执行 live canary。
- 未删除当前 worktree 的派生 bytecode；旧 Guardian 正确按 r141 的
  `destructive=deny` 阻断删除。正式验证改用 clean staging，不绕过监督器。
- 未把 observation `event_contract.py` 当成新的 authoritative reducer。

## 沉淀候选

### 候选一：审批事务必须分离 authority revision 与 subject revision

#### 任务与意图

- **问题类型**：bug-fix
- **任务目标**：让当前原生审批安全关闭旧 revision 的历史 effect debt。
- **用户真实预期**：批准 abort 后只关闭指定历史事务，不重试原操作，也不因合同已演进而永久卡死。
- **触发场景**：append-only effect attempt 早于当前 intent revision。

#### 观测与证据

- **可观察症状**：resolved 已追加，receipt 报 requires one exact source event。
- **期望与实际差异**：对象 revision 正确保留旧值，receipt 却拿当前审批 revision 比较。
- **已确认根因**：一个字段同时承担审批 CAS 身份和历史 subject 身份。
- **已排除假设**：不是用户未 Allow，也不是 resolved 未写入。
- **证据状态**：verified
- **一手证据**：v5 r7/r3 和 v4 cross-revision 回归均通过。
- **正确做法及验证**：密封 current authority 与 exact subject 双身份；恢复时按 subject 匹配且要求唯一来源。

#### 正负样本素材

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 新审批关闭旧 revision attempt 时 receipt CAS mismatch | apply | 同时存在 authority 和 subject 两个时态 | observed |
| 路由反例 | proposal 只审批当前 revision 且无历史对象 | skip | 没有跨时态 subject | constructed |
| 执行合格例 | current revision 保持 CAS，attempt id + subject revision 精确命中唯一 resolved | pass | 两种身份均未丢失 | observed |
| 执行失败例 | 把 resolved revision 改写成当前 revision | fail | 破坏追加历史和对象真相 | constructed |

#### 上浮边界

- **必须删除或泛化**：本机路径、具体 revision、session 与 transaction id。
- **可跨项目复用的内核**：跨版本事务必须把授权时态和被操作对象时态建模为两个字段。
- **建议容器**：anti-patterns
- **候选消费者**：审批状态机、effect ledger、recovery harness、review checklist。

### 候选二：测试入口生成 bytecode 会污染不可变 runtime 验收

#### 任务与意图

- **问题类型**：workflow
- **任务目标**：在不扩大 destructive 权限的前提下完成 clean runtime 验证。
- **用户真实预期**：每轮测试可重复执行，不因测试自己制造的派生物导致后续安装/launcher gate 失败。
- **触发场景**：直接用普通 Python 导入源码树后再验证 bytecode-free artifact。

#### 观测与证据

- **可观察症状**：launcher gate 报源码含 `__pycache__`；删除又被当前合同拒绝。
- **期望与实际差异**：测试应只读源码，却留下会改变 artifact 判定的文件。
- **已确认根因**：测试入口未使用 `-B`，且把可变源码树直接作为 immutable runtime 输入。
- **已排除假设**：不是 launcher digest 算法随机；clean 隔离副本同组 49 项通过。
- **证据状态**：verified
- **一手证据**：全量首轮失败和 clean `-B` 重跑结果。
- **正确做法及验证**：声明解释器依赖，从 bytecode-free staging 以 `-B` 执行；不把事后删除当默认流程。

#### 正负样本素材

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 先 import 源码后 artifact gate 报 pycache | apply | 测试改变了被测输入 | observed |
| 路由反例 | 临时 fixture 内故意生成 pyc 并验证拒绝 | skip | 派生物不进入真实 source root | constructed |
| 执行合格例 | clean staging + 声明 venv + Python `-B`，失败组全部通过 | pass | 被测树在执行前后不产生 bytecode | observed |
| 执行失败例 | 临时放宽 destructive 后 `rm -rf` 再宣称测试可重复 | fail | 把自污染转成额外授权和清理依赖 | observed |

#### 上浮边界

- **必须删除或泛化**：仓库名、临时路径、解释器绝对路径。
- **可跨项目复用的内核**：不可变 runtime 测试必须禁止 import cache，并与依赖环境一起密封。
- **建议容器**：work-model
- **候选消费者**：CI runner、artifact stager、launcher gate、Agent 测试规范。
