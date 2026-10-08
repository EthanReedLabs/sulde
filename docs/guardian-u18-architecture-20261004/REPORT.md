# U18 architecture candidate

Status: candidate; coordinator review/integrated verification pending. No self-acceptance.

Base: `ef5e7d68556cee9122d422f1074fd1bdaeff2e7e`, branch
`task/guardian-u18-architecture-20261004`. Authorized revision 4 scope only.

## Result and source scope

- `resources.py`: 3111 → 2942 lines. Three memory functions moved verbatim to
  `resource_memory.py` (182 lines); original resources exports and recovery
  reference remain the same function objects. No memory behavior change intended.
- `state.py`: 2994 → 2992 lines. Pure `plugin_creator_dependency` import moved to
  module scope. That dependency imports only AST/Path; no import-time I/O or cycle.
- `policy.py` product source unchanged (2991 lines).
- No installer, predictive tests, production configuration, installed runtime,
  dev merge, push, cleanup or actual SSH execution.

## Freeze obligations retained

The original `BASE=77c5929d7a69ffada7b205d431db82e24bd4e87c` stays unchanged.
No digest or whole-file candidate baseline was substituted.

The tests now explicitly recognize the previously reviewed semantic deltas:
historical-retirement gate, Git stdin read proof, bounded deploy narrowing,
trusted Guardian help, exact datetime receiver proof, bounded SSH effect
classification and remote resource identity, authenticated risk review/dispatch
binding, and no-card effect-barrier denial. Exact statement slices are scoped
to unique owners, checked in full with count/adjacent-anchor constraints, then
inverted. Every unchanged AST node must still equal 77c after reconstruction.
The new SSH function is an explicit complete AST slice, not a hash exemption
for a previously existing owner. Its fixed neighboring owners are checked.

The three extracted memory functions must each equal their original 77c AST,
have exactly the expected import bindings/aliases/order, no extra module
execution, no extra/duplicate function, and be reinserted at the original
anchor before the whole resources AST comparison. Separate tests verify the
real resources/recovery exports are identical objects. Existing unused imports
in resources were intentionally retained; unrelated cleanup is not in scope.

The moved `consumed_grant_decision` projection is separately reconstructed from
77c's original deny/allow constructors, preserving every keyword and branch
shape except the explicitly reviewed blocker reason text. This keeps the old
constructor protection despite policy's extracted call.

Mutation pairs reject deleted/reordered receipt checks, foreign event identity,
missing broker arguments, early allow, duplicate owners/branches, unrelated
tails, weakened help/datetime/deploy/remote checks, memory receipt bypass and
wrong helper import sources. Existing cycle, no-facade, delayed-import,
3000-line, callback and fresh import-order guards remain active.

These are exact boundaries for already reviewed deltas, not a proof that all
future changes or all security behaviors are defect-free. Behavioral gates and
independent coordinator review remain required.

## Evidence

All commands used `/Users/eric/.sulde/data/kb/venv/bin/python -B`.
New subprocess calls explicitly use UTF-8 and `errors="replace"`.

1. Before product edits, same original entry:
   `-m unittest tests.test_control_composition_architecture tests.test_intent_guardian_state`
   ran 20 tests, 6 failures: policy AST, policy import set, resources AST,
   state delayed import (two guards), resources 3111-line limit. Other 14 normal
   architecture cases passed. Source identities: policy `a95180567bf27717bd8113bb7642017474f07a0bd481e2d99fe25fe59d3dc74c`,
   resources `16e7f1ff4b5025617ee641710038513c7072b43db1cc00571408cc7d495e5db2`.
2. Candidate same 20 assertions passed. Final combined architecture entry adds
   `tests.test_guardian_u18_architecture`: **31/31 passed** (7.977 s).
3. Affected production modules:
   `tests.test_guardian_memory_consistency tests.test_intent_guardian_resources
   tests.test_guardian_s1_semantics tests.test_guardian_s1_grants
   tests.test_control_composition tests.test_predecessor_composition`:
   **120/120 passed** (21.080 s).
4. `tests.test_native_memory_consistency`: **2/2 passed** (35.267 s), isolated
   real Codex CLI/app-server + loopback mock provider. Ten annotations, attribution
   denial, and intentionally lost Post recovery without replaying annotation.
   Candidate artifact generation suffix
   `28ba50538a6edfd4ed9d77d497d6c718f339afabd57d54b115e70119a71a734b`.
   Mock provider is not evidence of an external provider operation. No SSH.
5. Real `intent-guardian.py --help`, six original fresh component import orders
   and two new memory/recovery import orders passed. Source-extraction test also
   compares state AST excluding imports to ef5e7d6: exact equality.
6. `git diff --check` passed. Full suite deliberately not run here; coordinator
   owns the integrated full run and performance comparison.

## Separate tooling/fixture events

- Optional read-only inline AST/difflib diagnostic was denied by the installed
  PreToolUse classifier with: “对象类型未能证明；该方法可能改变文件，当前调用需明确目标和风险后再执行”.
  It read `git show`, parsed AST and printed fragment lengths; the final display
  expression used `src(y)[:120].replace('\n', ' | ')`. No event/session identifier
  was supplied in the tool response. It was not retried/rephrased; coordinator
  explicitly directed skipping this optional diagnostic. Static test implementation
  and normal unittest entries continued. Installed classifier unchanged.
- Initial native memory fixture failed because candidate packaging enumerates
  tracked files and the new helper was not yet staged. After normal `git add`,
  missing-module failure disappeared. This was distinct from the diagnostic denial.
- Then the managed sandbox denied binding the fixture's loopback server. Normal
  permission escalation allowed the unchanged native unittest entry, which passed.
  No alternate transport or permission bypass was used.

## Skills and knowledge use

Dispatch-task continuous-execution discipline was retained; KB search/read of
AP0018 and AP0092 informed leaf ownership and dependency/global checks. Diff skill
graph metadata was inspected, but its commit `265c5473...` predates changed source;
source/AST/callers, not the stale graph, supplied evidence. No out-of-scope graph
overlay or KB mutation was made. Use `/understand` separately if a current graph
is desired; it is not needed for these conclusions.

## 沉淀候选（Layer1；仅任务内，不写知识库）

- 问题类型：design-decision / regression。
- 任务目标与预期：保持已审阅行为的架构拆分，不能靠冻结换基线掩盖漂移。
- 触发场景：将全局依赖函数移到新模块，同时迁移 AST 冻结守卫。
- 症状：只比较函数 AST 不能保护新模块的同名导入绑定。
- 根因：Python 函数使用定义模块 globals；函数文本未变不代表依赖来源未变。
- 已排除：现有 recovery 级 receipt monkeypatch 不受影响，真实 native memory 正常。
- 证据状态：verified（构造 mutation，不是实测生产事故）。
- 一手证据：`test_memory_body_receipt_and_foreign_identity_mutations_rejected`、
  `test_extracted_memory_exports_are_identical_objects_and_globals`、native suite。
- 正确做法：逐函数旧 AST + 精确 imports + 导出身份 + 真实行为/入口配对。

| 样本 | 内容 | 预期 | 判定原因 | 来源 |
|---|---|---|---|---|
| 路由正例 | 跨模块提取使用全局依赖的函数 | apply | 定义模块globals改变 | observed |
| 路由反例 | 同模块纯格式化，无依赖改变 | skip | 没有global-owner迁移 | constructed |
| 执行合格 | 旧体/导入绑定/导出对象/入口均验 | pass | 保留完整行为依赖 | observed |
| 执行失败 | verify别名换成normalize但只比函数体 | fail | 同名依赖被替换 | constructed |

上浮前泛化项目路径/提交/函数名；可复用内核为“AST等价重构须同时证明定义模块
全局绑定”。建议 anti-patterns / review checklist；交协调端判重，不在本轮入库。
