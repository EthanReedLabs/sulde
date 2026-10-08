---
capability_tier: deep
---

# Heartbeat variable-only generation contract

2026-09-23. Base dev: `2470494da35de39cc47a31021546c15ff6d07dbd`.
Implementation and test evidence: commit `4bd19ef`.
Native proposal revision 2 receipt:
`596495deb4d96c5996dc8ec317d9ebd2672ac84513145713dabedc206cb27877`.

## Result and limits

Local implementation and scoped isolation acceptance passed. No production
installation, real provider call, scheduler kick, production SELF edit, problem
ledger closure, merge into dev/main or remote push was performed. This is not a
claim that the installed heartbeat is repaired or all LIFE health is ready.

The model now returns `variable_md` and `observation`. The program preserves the
current fixed prefix and combines it with only the three ordered mutable sections
(目标栈 / 观察清单 / 自评). No complete fixed-prefix regeneration is requested.
The prompt no longer permits capability-status edits inside the immutable area.
Legacy `self_md` output is still accepted only with an exactly unchanged fixed
prefix; changed fixed content is rejected before any compression attempt.

Ambiguous JSON representations, duplicate fields, missing/extra/reordered level-1/2
headings, and unrecognized existing mutable layouts fail closed. A single bounded
compression remains available. Failure leaves old SELF intact, retains a machine
observation and never logs rejected model prose. No new provider fallback or
automatic retry was added. Unknown human-added trailing sections are deliberately
preserved by refusing the update, not silently discarded.

## Evidence and corrected causal claims

Production read-only source: heartbeat state sequence 133 at
2026-09-23T01:40:26Z, `last_mode=degraded`,
`last_degraded_reason=self_fixed_sections_changed`, fixed_chars 3270,
variable_budget 4729. Multiple distinct September beats record this reason.
The LIFE aggregate contains 50 occurrences of the broader
`heartbeat_generation_degraded` category, not proof of 50 identical causes.

Confirmed design defect: the old prompt allowed editing capability status while
the fixed-prefix equality gate rejected any such edit. Asking the model to copy
all fixed content also introduced an unnecessary regeneration failure surface.
The historical rejected candidate bodies were not retained, so the precise text
differences that caused each production failure remain inconclusive. Do not
attribute all historical incidents exclusively to the prompt contradiction.

Aggregation was inspected independently: a beat sequence provides a stable event
identity, with a processed-event ledger preventing duplicate aggregation. Tests
confirm a repeated read of one degraded beat counts once. This does not prove
all historical production counters have been independently replayed.

## Verification

Command (managed venv interpreter, bytecode disabled):

```sh
python -B scripts/kb/run-isolated-tests.py tests.test_heartbeat_variable_contract tests.test_life_health_closure tests.test_self_repair tests.test_life_cycle tests.test_dual_runtime_contract
```

- 84 passed, zero failures/errors/skips, 41.253 seconds; official OS-isolated runner exit 0.
- Includes 16 new heartbeat tests and existing lifecycle, repair and provider tests.
- Actual heartbeat CLI subprocesses ran against disposable homes and a synthetic
  stdin responder: two successive beats preserve fixed bytes and advance timestamps.
  This is real local CLI execution, not a real-model or production canary.
- New successful heartbeat state drops the old failure reason. The separately
  retained historical problem remains open with unchanged occurrence count;
  success is not manufactured into independent problem verification.
- Fixed mutation, missing/extra/reordered sections, duplicate/mixed JSON fields,
  exact 8000-character boundary including newline, existing oversized variable
  shrink, one compression, bad compression, missing definitions and timeout covered.
- Initial 13-test direct fixture run passed. An initial combined-run command used
  unqualified module names and failed five imports before test execution; corrected
  `tests.*` names passed. This was an Agent command error, not a product failure.
- Full results, the failed invocation and SHA-256 identities of all six source/test
  inputs are in `regression-evidence.json`. The code commit retains those exact bytes;
  this report is a documentation-only follow-up, not a new runtime change.
- No full repository suite: the change is confined to heartbeat generation/parser
  logic. The broader scoped suite includes its consumer, scheduler/provider and
  self-repair interfaces; no installed host wiring was altered.

## Workflow observations

The first prepare-proposal call resolved the session completion contract despite
an explicit different workspace. Its returned workspace was inspected before
approval; no material action used that draft. An explicit native workspace handoff
then bound the correct task worktree and a new native-approved proposal provided
the scope. The old draft was not applied, and no copied permission/token was used.
This routing behavior is a separate observed control-plane issue, not repaired here.

## Next release gate

1. Review the small source diff and reuse the recorded input hashes if unchanged.
2. Merge into dev only after acceptance; use the official candidate release route.
3. After installation, obtain a bounded real heartbeat/provider observation under
   explicit authorization, preserving production fixed-prefix identity. Do not
   invoke paid/provider generation merely to make this local report green.
4. Read new heartbeat state, LIFE domains and independent verification. Historical
   problem closure requires that separate verifier; do not delete or rewrite debt.
5. If this domain recovers while aggregate health remains degraded, inspect the
   other domains separately, without widening this heartbeat fix.

## 沉淀候选 — Layer1 原始问题卡

### 任务与意图

- 问题类型：bug-fix / workflow。
- 任务目标：定位并修复反复出现的心跳固定段冲突，保留权限和事实边界。
- 用户真实预期：减少自锁和重复返修；正常动作不因控制面错误受阻。
- 触发场景：固定身份/法典与可变观察共存，模型被要求重写完整文件。

### 观测与证据

- 可观察症状：不同心跳序号均记录固定段变化而降级，旧 SELF 被保留。
- 期望与实际差异：只需更新观察，实际要求重写受保护的整个文档。
- 已确认根因：提示词允许修改固定区现状标记，与逐字相等校验冲突；
  各次生产失败的具体字符差异仍 inconclusive。
- 已排除假设：不是只有一个旧状态被重复展示；不同序号确实产生失败记录。
- 证据状态：协议冲突及隔离修复 verified；生产恢复 inconclusive。
- 一手证据：基线 heartbeat.py、生产状态/逐搏日志、当前 diff、84 项隔离测试。
- 正确做法及验证：模型只提交可变区，程序保留固定区；兼容输入仍严格验证；
  连续真实 CLI 进程验证状态更新，历史问题仍独立保留。

### 正负样本素材

| 样本 | 内容 | 固定预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 固定段完整重生成且逐字校验，多搏拒绝 | apply | 输出协议与不变量冲突 | observed |
| 路由反例 | 单纯模型进程超时，没有固定段冲突证据 | skip | 不能用协议改造宣称修复超时 | constructed |
| 执行合格例 | 可变区更新、固定字节不变、历史问题未被伪造关闭 | pass | 满足边界与证据独立性 | constructed; executed in CLI fixtures |
| 执行失败例 | 忽略固定段变化或复制健康值覆盖历史告警 | fail | 放宽安全边界或伪造恢复 | constructed |

### 上浮边界

- 必须删除或泛化：路径、提交、问题标识、生产时间与个体信息。
- 可跨项目复用的内核：不要求生成器重写其无权修改的内容；由程序组合可变输出。
- 建议容器：anti-patterns。
- 候选消费者：生成协议 reviewer、lint、测试设计和知识检索。
- 未直接写入正式知识库或记忆图谱。
