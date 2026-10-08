/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06I-R2-interruption-authority.json

# H06I-R2 — 闭合 interruption authority 与 worker report 终态协议

## Authority

- exact base：`10ad8d876d74fe5c4dea8e3b1cc27e178078bdc2`。
- provider：Codex deep/high；不得调用或依赖 Claude。
- 范围冻结权威：`guardian-r2-program/SCOPE-FREEZE.json`。先校验该文件，再执行本任务；它只允许 `H06I-R2-interruption-authority` 与 `H06J-r2-final-acceptance` 两个未来 task identity，各一次正式 managed candidate。禁止创建 R3、H06K 或其他返修任务，禁止扩大 owned paths。
- 只允许修改 task definition 中五个 exact paths；禁止 commit、install、scheduler、production intent/KB、push、merge、dev/main 与网络副作用。
- 从 fresh exact base 独立实现。H06I 与 H06I-R1 的候选均不可复制、提升或改写；它们只提供冻结红证据和复审结论。
- 文件修改必须使用原生 `apply_patch`。禁止 heredoc、重定向写文件、`perl -i`、`sed -i`、Python 写文件或依赖未授权临时文件的 shell 原地编辑。
- 正式 managed candidate 失败时立即停止并保存证据；不得自动新建 successor、扩大路径或发起第二次正式 candidate。只有用户显式解冻并先提交 append-only freeze amendment 才能改变该边界。

## Required knowledge and frozen evidence

- 受管临时 authority 已知不含 kb-index venv。不要再次调用该已知不可用入口；按仓库降级规则直接阅读全文 `/Users/eric/.codex/plugins/cache/sulde-local/sulde/0.2.5+codex.20260826044342/runtime/knowledge/anti-patterns/0224-verification-environment-differs-from-runtime.md`，不得只读索引 excerpt。
- H06H run ledger SHA-256：`8f32a901dc01221376b13cae56ed328e4729d21dac91f5ac29b25b363f63b67a`；events SHA-256：`cec437d7a1d35307c90f2ceb9d333de7e556fa685c559010221e39e48fc6a62e`；stderr SHA-256：`b38d2df3d6d0624e798a39de46f6b72ef8ebce83bc023ee6c3593b22d1ce61d3`。
- H06I events/report/status SHA-256：`a3400d5c1f94328e27f864d1d54e01d12fe3814c4cc63f27ed66edc583d6767e`、`efcddc15305963b127c6c39fe51d9df23dc9254e4e42446de65a4ae5d750b124`、`0a00a0f757775f6bd3ce58e067b99b2176d399d25fad50a2c5fa59ddf8930f55`。
- H06I-R1 events/report/status SHA-256：`442ace1c96749773a1dfa079ed13ac46f7e95180c85e3d97e6c979b60f405b77`、`ba02c7f368c0c592fb5d8137ebfac17734336c2024b99032ef20357caf2afd48`、`34bf68592fd8b58d38c00fb6c28a2710d97606f3a3b4e412f0bb6b1bb3ec3f0e`。
- `FR2-H06H-002`、`FR2-H06I-001..004` 与 `FR2-H06I-R1-001..006` 的精确历史状态、返回码和错误文本已在统一 controller ledger 中保存。worker report 只做 content-addressed 引用，不重复这些控制事实。
- finding 语义不得重排：`H06I-002` 是 H06H events/stderr 绑定缺失，`H06I-003` 是完整命令/item 链缺失，`H06I-004` 是未实际进入测试体却声明已验证；`H06I-R1-001` 是报告历史上下文误触发，`002` 是 final message 与 durable report 权威分裂，`003` 是 finding 映射错误，`004` 是三种生命周期角色混写，`005` 是派单路径与投影路径不一致，`006` 是乱序反例仍含重复项。

## Implementation

1. 让 runtime 与 broker 消费一个共享、不可变、精确的 local interruption reason authority；runtime 不保留第二张 map。未知 reason、非字符串、大小写/空白/前后缀变化全部 fail closed。
2. `external_effect_outcome_unknown` 唯一映射为 `awaiting_human`。保留事件唯一数量、matching run_id、严格顺序、严格 int returncode、disposed quiescent、reason/stop equality 和 ledger digest 约束。
3. 新增真实 H06H 字节绑定的 runtime parser → production broker receipt build/validate roundtrip，不设置 `SULDE_TEST_MODE`。两侧 failure matrix 覆盖 missing、duplicate、reordered、reason drift、unknown/non-string reason、字符串或 bool returncode、非 quiescent disposal；乱序必须使用唯一 index 的真实乱序，例如 `[3,2,4]` 或 `[2,4,3]`，不得同时混入 duplicate。
4. managed terminal 用例断言 provider、interrupt、result、disposed、intervention identity 与 external attempt 各一次；human decision、retry、reprobe、effect replay 与 `post_terminal` 均不存在。
5. 不修改 production exact profile。需要 `TemporaryDirectory(dir=ROOT)` 的完整模块与 managed fixture 由协调器在 candidate 终止后于独立测试 scratch 执行。

## Worker verification

- worker 只运行本 profile 内可完成的 focused tests、AST、diff、scope/control hash 与 report-verdict preflight；全部命令必须真实成功。
- focused 至少包含 runtime H06H authority/failure matrix 与 broker boundary tests。需要仓库临时 fixture 的 roundtrip/managed test 只添加断言，不在 worker 报告中声称已执行。
- effective diff 精确五个 owned paths；两份 host control projections 不属于候选，`.git`、`.codex-agent`、`.pyc` 不得进入候选。
- 派单前由协调器把 task/brief 投影到 fresh clone 内同名 `guardian-r2-program/...` 路径；模型前缀的任务路径必须真实存在，不得改写成另一个目录名。

## Report protocol

- 报告 `guardian-r2-program/reports/H06I-R2-interruption-authority.md` 必须且只出现一次 `## 结果`、`## 过程`、`## 遇到的问题`、`## 解决方式`、`## 遗留风险与建议`。
- 每条 `✅ 完成检查：` 只能记录当前 worker 本轮真实成功的命令，并带 `exit 0` 与可观察输出。
- strict worker verifier 会把报告任意位置的历史非零返回码或 incomplete-state 词当成当前候选失败。故精确历史数值/终态只保留在 controller ledger；报告以 SHA-256 和 finding ID 引用，不复述数字或这些状态词。这不是删除历史，controller append-only 事件仍是唯一权威。报告正文不得出现非成功返回码，也不得出现 `partial` 或 `blocked`。
- 报告不得宣称 coordinator full-module、production roundtrip 或 managed fixture 已验证；只能说“断言已添加，等待协调器验证”。
- 写完报告后，必须用当前 `scripts/kb/agent-runtime.py` 的 `report_contract_for_brief` 与 `task_report_verdict` 读取实际 brief/report 并得到 `passed=true`、空 failures；把该真实成功命令作为一条 `✅ 完成检查` 后再次运行并确认仍通过。
- durable report 与 worker 最终回复必须逐字节相同；不得在最终回复前后增加解释。协调器将同时计算两者 SHA-256，并要求 receipt 绑定同一摘要。
- 最终报告只声明 H06I-R2 candidate，不声明 implemented、task_verified、integrated、accepted、H06J、installation、scheduler、live canary 或 R2 completion。

## Frozen disposition

- 本任务必须在同一 task identity 内一次收口 `FR2-H06H-001` 与 `FR2-H06I-R1-001..006`；不得为任何一项再创建微型 repair task。
- scope 内新发现直接作为本任务 finding 记录并在本 task 内处理；scope 外且不影响既定 acceptance 的观察只写入 post-R2 backlog，不改变本轮验收。
- scope 外若构成安全或既定 acceptance 阻断，立即停止并报告 freeze violation；不得自行修改 freeze、任务图或 allowed paths。
