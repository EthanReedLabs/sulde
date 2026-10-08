# 三项历史原生测试失败：有界诊断

capability_tier: balanced

## 结论与范围

完成本轮诊断，不代表修复或发布验收完成。产品代码与原测试未修改。
从 dev `f5cbf6cde41c35ffb652a360c2f558a66e1c0c4c` 创建
`task/native-failure-diagnosis-20260923`；仅新增诊断脚本、报告和私有证据。
未运行全量、生产任务或付费模型，未合并、推送、正式安装或改变调度配置。
原勘误任务工作树及分支保留。

本轮确认三项失败不是同一个原因：

1. 隔离函数未规范化策略路径。别名路径规则未保护同一真实目录；真实路径规则有效。
2. 组合测试进入真实执行后，登记命令无法访问候选账本锁文件，退出 2。
3. 续接测试中 Guardian 放行后续写入，但执行器对目标 worktree 的 touch 返回 EPERM。
   此复现不是 Guardian 在拒绝之后持续拒绝普通调用。

第 2、3 项共同指向 fixture 布局与原生宿主可写范围不匹配；具体生成的 Seatbelt
条款未捕获，不能断言所有默认临时目录都不可写，也不能把两个错误统一称为锁死。

## 可重复输入

- 源码基线：上述 exact dev；原三份测试摘要记录于每次 `run.json`，各轮一致。
- macOS 26.3；Python 3.10.7；pytest 9.1.1；PyYAML 6.0.3，使用同一解释器。
- 实际 Codex CLI：0.155.1；源码 `codex_cli_contract.py` 审计版本仍为 0.154.0。
  本轮没有升级或降级 CLI；新运行不能冒充历史 0.154.0 的逐字重放或完整版本兼容认证。
- 原生测试使用真实 CLI app-server、unified_exec、候选 Hook、新进程及本地回环模型桩。
  候选安装仅发生在测试自己的临时 CODEX_HOME / Sulde home，不切换生产代际。
- 前三轮通过 `python -B -m pytest` 直接运行原三项，保存完整 stdout/stderr、JUnit XML，
  不使用管道尾部退出码。300 秒上限；实际每轮不足 36 秒。

## 结果矩阵

| 运行 | 外层权限 / 临时根 | 实际结果 | pytest exit | 秒 |
| --- | --- | --- | --- | --- |
| sandbox-default | 当前受限宿主 / 默认临时根 | 2 failed, 1 skipped | 1 | 19.710 |
| host-default | 获批宿主权限 / 默认临时根 | 3 failed | 1 | 35.503 |
| host-relocated | 同等获批权限 / 独立 `/private/tmp` 子目录 | 3 passed | 0 | 35.837 |
| host-continuity-observed | 获批宿主权限 / 默认临时根，仅续接项、失败后观测 | 1 failed | 1 | 17.894 |

第一轮两个失败发生于本机 HTTP 回环服务 bind，原生业务尚未执行；隔离项因外层
Seatbelt 初始化限制而跳过。不能把这一轮作为三项产品故障复现，也不能把 skip 算通过。
后两轮仍保留测试内部的原生宿主隔离，获批外层权限不等于把候选切成全权限运行。
最后一轮只增加异常发生后的观测，不改变命令、审批、断言或策略；单独列出，不混充原始运行。

## D1：隔离策略路径未规范化（verified）

源码位置：`scripts/kb/run-isolated-tests.py:1465`、`:1496`；测试
`tests/test_isolated_test_runner.py:768`。

默认临时根下的完整异常确为 `OS test isolation backend allowed a production write`。
这是测试自建 `production-kb` 中的 `.sulde-isolation-probe-<id>` 曾被创建，随后由
预检移除；不是正式知识库被写入。测试里的另一个 `native-bypass` 尚未进入执行阶段。
第 783 行异常字符串断言失败掩盖了原始异常，但不是唯一问题。

独立探针调用未修改的命令构造器，分别用相同真实目录的 raw / canonical 策略根：

| 传入根 | 无隔离正控 | raw 策略 | canonical 策略 | 原预检 raw / canonical |
| --- | --- | --- | --- | --- |
| `/var/folders/...` | 写入成功 | 写入成功 | 拒写，文件不存在 | 拒绝验收 / 验证拒写 |
| `/tmp/...` | 写入成功 | 写入成功 | 拒写，文件不存在 | 拒绝验收 / 验证拒写 |
| `/private/tmp/...` | 写入成功 | 拒写，文件不存在 | 拒写，文件不存在 | 验证拒写 / 验证拒写 |

9 次直接动作、6 次原预检均在自建临时目录。正控证明解释器可运行、目录本身可写；
canonical 策略证明 OS 隔离有效。因此应归为策略路径身份错误，而非 macOS 安全机制失效。
正式 runner 的 `main():1567` 已对生产根 `.resolve()`；本次不能推出正式入口保护失效。
仍应在公共边界函数内部保障此不变量，不能依赖每个调用方恰好规范化。

对历史勘误的补充：此前仅凭截断尾部，保留原始预检原因 inconclusive 是合理的；
现在新复现证实了临时预检探针写入，不应再简化成“只是错误信息断言”。历史 `/tmp`
对照与此机制相符，但旧日志没有完整异常，不能将新证据伪装成旧执行的直接证据。

## D2：组合登记命令的可写边界（失败层 verified）

`tests/test_native_control_composition.py` 将 workspace 放在 `sulde-home/composition-canary`，
账本在其兄弟路径 `sulde-home/data/kb`。`native_pretool_canary.py:160` 启动 workspace-write
线程；候选 TMPDIR 是另一个隔离子目录。控制状态目录不是初始 workspace 的子目录。

默认根下 `candidate_native_0` 的 skill-start/end 组合实际启动，返回 2：
`cannot enumerate native decision transactions: [Errno 1] Operation not permitted`，
目标为候选 `intent/workspaces/..*.active.native-decisions.jsonl.lock`。
测试因此只有 3 而非 4 个 exit 0，失败在 `test_native_control_composition.py:96`。
同轮后续普通写入成功，不符合“任何被拒绝动作都会锁死后续调用”的描述。

迁到 `/private/tmp` 后原测试通过：4 个安全组合、1 个真实破坏性前置拒绝，短路语义保留，
拒绝后的写入成功。可证明路径布局影响执行权限；不足以声称原生宿主隔离本身有缺陷。

## D3：续接后的目标 worktree 不可写（失败层 verified）

初始 `continuity-canary` 与目标 `continuity-task` 为兄弟目录，目标由 fixture 创建。
本场景回调切换 Guardian 路由及工具工作目录，但不是历史释放场景中那个显式新 turn。
默认根下第一次写入成功；两次负例分别被 PreToolUse 拒绝；之后两次 touch 的 PreToolUse
均 completed，但真实工具回执为：

- `candidate_native_2`：exit 1，`touch: after-composition.txt: Operation not permitted`。
- `candidate_native_4`：exit 1，`touch: after-uncertainty.txt: Operation not permitted`。

最终断言失败于 `test_native_session_continuity.py:256`。不能用这一失败证明 Guardian
残留暂停，也不能仅看 PreToolUse completed 就宣布写入成功。可写根如何继承/变更仍需
在修复中以宿主认可配置和负例证明；本轮没有获取生成的完整 sandbox policy。

迁址后的真实原测试通过：拒绝后写入恢复，worktree handoff 的 authority_transferred=false，
原始观察日志未被改写，否决 proof 的 loaded_module_generation / artifact_generation
均按原测试校验。此结果仅覆盖隔离候选，不替代生产 SessionStart、审批或持续调度验收。

## 下一轮最小修复建议（尚未实施）

1. 在 OS 策略构造边界统一物理路径解析，增加 `/var`、`/tmp`、canonical 及符号链接
   正反例。保持 preflight fail-closed；不得把真实探针写入降为 skip，也不只改错误字符串。
2. 明确原生 fixture 的工作区、账本与目标 worktree 可写根，通过宿主支持的精确配置
   建立隔离权限；区分“控制面 handoff”和“宿主文件权限”。不得放开整个 home、关闭
   沙箱、伪造 externally_isolated 标识或靠 `/tmp` 的宽松默认权限掩盖遗漏。
3. 失败证据常态保留：真实工具退出码、具体路径、Hook verdict、前后文件状态；禁止
   只留最后五行。预检结构化地区分 backend 不可用、规则未生效和执行权限不足。
4. scoped 验收：隔离 runner 相关单元测试 + 上述路径矩阵 + 两项真实宿主测试，覆盖默认
   与迁址目录；同时验证未声明兄弟路径仍被拒绝。小范围修复不直接重跑全部 2400+ 项。
   若改变公共权限/状态机或发布审计 CLI 契约，再按影响范围扩充验收。
5. 保留 0.154.0 / 0.155.1 审计版本差异为独立发布条件；不能只改版本常量宣称兼容。

## 私有证据与复用

完整日志、JUnit、环境/输入摘要及 failure-only 工具观测保存于当前任务的
`.sulde/native-failure-diagnosis/`；该目录有本地 `.gitignore`，不进入源码提交或公开导出。
原始日志可能含私人路径，公开共享须先脱敏。临时测试副本由测试回收，证据不自动删除。

| 证据 | SHA-256 |
| --- | --- |
| sandbox-default/run.json | f2990e2e84438f745b4a54b1a503e616205e59624ce83771afdbb3eaacacb1e6 |
| host-default/run.json | 77f73736828d143b84a59eb07c11ec83f91c3d66b46ce8b9c7671da7df9c6249 |
| host-relocated/run.json | 3ec247825f254e87d2d8676507815b7b1ef86f566cd7aa0b463fe3565cffb5f9 |
| host-continuity-observed/run.json | 1c997070dc4850fc35313436e5260b4f3a1bcd16d5c024032c6e5f4d121c45fa |
| host-continuity-observed/native-failure.json | 0c0d5fd91bff2bbe57398d30ffadf17da3f01eaf8ef942a80914c4a9beecccd8 |
| path-boundary/evidence.json | a1d2d55c49d9b8d4edad2252127c050d89c93c1babbad3a5d4fd15954f4dc905 |

每份 run.json 还包含 pytest.log 摘要。脚本：`run-native-failure-diagnosis.py`、
`native_failure_evidence.py`、`probe-native-path-boundary.py`。observer 只收集自建 fixture
失败时的命令结果和 Hook 通知，不记录隐藏推理、宿主环境全文或真实业务 prompt。
运行需当前宿主授权，并使用新的 run_id；不得覆盖已有证据。

## 沉淀候选

- 语境：拒绝之后写入失败，测试尾部被误读为 Guardian 自锁或 OS 隔离失效。
- 证据状态：路径规则缺陷与实际失败层 verified；历史逐次原因及具体宿主条款 inconclusive。
- 处理：同版本、同解释器的目录对照；原异常完整保留；无隔离正控 + canonical 负控。
- 结果：区分策略路径身份、Hook 决策和执行器写权限，未假报修复或生产 ready。
- 路由正例：Hook 已放行但工具 EPERM，应排查实际可写根。
- 路由反例：PreToolUse 明确拒绝且工具未启动，不能归因于文件系统执行权限。
- 执行合格例：相同物理目录 raw 规则可写、canonical 规则拒写，并记录实际文件存在性。
- 执行失败例：仅将 TMPDIR 迁到宽松目录后称产品已修复，或把预检探针与另一目标混为一谈。
- 来源：本报告的 exact source、四轮 run.json 和独立路径矩阵；入库前去除私人路径及标识。

依据 dispatch-task 保持宿主当前配置；intent-guardian 限定本轮为诊断且不修改产品；
kb-search 的 ap-0201 / ap-0252 要求将沙箱噪声、解释器输入与实际判决分开验证。
本轮另遇一次混合只读/控制命令组合被拒绝，拆为独立只读调用后继续；未据此扩大修复范围。

## 交付检查

三个诊断脚本 AST 解析通过；四轮日志摘要与 run.json 一致，JUnit 的失败/跳过计数已独立
回读；三份原测试摘要跨轮一致。main/dev 工作树仍干净。四个新增交付文件尚未提交，
无产品源码差异。证据是本机私有留存，不把任务文档完成称为发布闭环。
