/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06I-R1-interruption-authority.json

# H06I-R1 — 统一 runtime 与 broker 的 awaiting-human 中断 authority

## Authority

- exact base：`10ad8d876d74fe5c4dea8e3b1cc27e178078bdc2`。
- provider：Codex deep/high；不得调用或依赖 Claude。
- 只允许修改 task definition 中五个 exact paths；禁止 commit、install、scheduler、production intent/KB、push、merge、dev/main 与网络副作用。
- 这是对失败任务 `H06I-agent-runtime-interruption-terminal` 的 superseding repair。不得复制或直接提升其候选文件；从 exact base 独立实现并验证。
- 文件修改必须使用原生 `apply_patch`。禁止 heredoc、重定向写文件、`perl -i`、`sed -i`、Python 写文件或依赖未授权临时文件的 shell 原地编辑。

## Frozen predecessor evidence

- H06H real run ledger：`/Users/eric/ClaudePlugin/sulde-cc-pro/.worktrees/r2-h06h-final-fullclone/.codex-agent/r2-h06h-final-acceptance-run1.run.jsonl`，SHA-256 `8f32a901dc01221376b13cae56ed328e4729d21dac91f5ac29b25b363f63b67a`。
- H06H provider events：同目录 `r2-h06h-final-acceptance-run1.events.jsonl`，SHA-256 `cec437d7a1d35307c90f2ceb9d333de7e556fa685c559010221e39e48fc6a62e`；`item_25` 为 heredoc/`perl -0pi` temp-file 拒绝事实。
- H06H stderr：同目录 `r2-h06h-final-acceptance-run1.stderr.log`，SHA-256 `b38d2df3d6d0624e798a39de46f6b72ef8ebce83bc023ee6c3593b22d1ce61d3`。
- H06I failed run events：`/Users/eric/ClaudePlugin/sulde-cc-pro/.worktrees/r2-h06i-interruption-fullclone/.codex-agent/r2-h06i-interruption-terminal-run1.events.jsonl`，SHA-256 `a3400d5c1f94328e27f864d1d54e01d12fe3814c4cc63f27ed66edc583d6767e`。其报告 SHA-256 为 `efcddc15305963b127c6c39fe51d9df23dc9254e4e42446de65a4ae5d750b124`，status SHA-256 为 `0a00a0f757775f6bd3ce58e067b99b2176d399d25fad50a2c5fa59ddf8930f55`。
- H06I failed candidate 暴露四个已登记 findings：`FR2-H06I-001..004`。它不得合并；可只读使用红证据与结论。

## Verified root cause

1. `agent-runtime.py` 与 `native_agent_broker.py` 各自维护一张本地中断 reason map。
2. H06I 只给 runtime map 增加 `external_effect_outcome_unknown → awaiting_human`；正式非-test 路径在 runtime 解析成功后仍调用 `native_agent_broker.build_provider_receipt/validate_provider_receipt`，broker 的第二张 map 随即拒绝同一证据。
3. H06I worker 的 managed 用例在 `SULDE_TEST_MODE=1` 下跳过 native receipt，因此未覆盖该断层；报告又把“新增断言”写成“已验证”，形成独立报告 finding。
4. H06I 的全模块与组合回归在 worker exact production profile 中于 `TemporaryDirectory(dir=ROOT)` 创建阶段被拒；协调器在隔离可写测试 scratch 中原样复跑，分别得到 65/65 与 162/162 通过。该协调器证据是 repair 输入，不是本 worker 可冒领的通过证据。

## Implementation

1. 让 runtime 与 broker 消费一个共享、精确、只读的 reason authority；禁止保留两张可漂移的 production map。共享入口必须对未知 reason fail closed，不做字符串规范化、前缀匹配或默认映射。
2. `external_effect_outcome_unknown` 只能映射到 `awaiting_human`。保留事件数量、run_id、严格顺序、严格 int returncode、disposed quiescent、reason/stop equality 与 ledger digest 全部现有检查。
3. 新增直接穿过 runtime ledger parser → production broker receipt build/validate 的测试，不设置 `SULDE_TEST_MODE`，并使用 H06H 真实五事件结构或其字节绑定 fixture。
4. 在 runtime 与 broker 测试中覆盖 missing、duplicate、reordered、reason drift、未知 reason、字符串 returncode 与非 quiescent disposal；不得只断言字典内容。
5. managed terminal 的增强断言继续保留：provider 一次、interrupt/result/disposed 各一次、单一 intervention identity、无 human decision、无盲重试、无 external effect replay、无 `post_terminal`。worker 若因 exact profile 无法进入该用例主体，报告只能写“断言已添加、待协调器执行”，不得写“已验证”。

## Verification and report truth

- worker 只运行在当前 exact profile 内可真实完成的 focused、无临时目录测试和静态检查；不得为测试扩大 production profile，也不要在 candidate report 中把受管 profile 下无法进入主体的全模块命令列为完成检查。
- coordinator 会在 candidate 终止后，于独立测试 scratch 原样运行 `tests.test_agent_runtime`、`tests.test_native_agent_broker` 与相邻 162 项组合回归；这些结果只能由 coordinator 登记。
- 报告 `guardian-r2-program/reports/H06I-R1-interruption-authority.md` 必须且只出现一次 `## 结果`、`## 过程`、`## 遇到的问题`、`## 解决方式`、`## 遗留风险与建议`。
- 每条 `✅ 完成检查：` 必须是 worker 本轮可字面执行、真实返回成功的命令。前序失败必须以冻结文件 SHA、item、错误类别和 finding 引用描述；不得把前序失败包装成 worker 完成检查，也不得隐去它仍是 blocked/failed 历史。
- 报告必须明确绑定 H06H events/stderr/run ledger 与 H06I events/report/status；记录 `FR2-H06I-001..004` 的修复方式，但只声明 H06I-R1 candidate，不声明 implemented、task_verified、integrated、accepted、H06J、install 或 R2 complete。
- effective diff 精确五个 owned paths；base、task/brief control projection hash、`.git`、`.codex-agent`、`.pyc` 不得进入候选。
