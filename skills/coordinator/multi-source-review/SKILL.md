---
name: multi-source-review
description: >-
  多源评审 / 三角验证 / 防单源误判。用于重大文档、大改动、发版前检查和跨决策边界改动；
  自动编排多源实证、区分代码与文档审查，并将 finding 分类为真实缺陷、上下文缺失、
  用户语义决策和低优先级建议，拒绝盲目实施或表演式同意。
user-invocable: true
---

# multi-source-review — 多源评审 + 分类决策

> **Why this skill exists**:单 reviewer 实证 critical claim 有失误风险(协议字段名错 / grep 范围漏 / context 偏差)。盲目接受全部 finding = 反向破坏。盲目推翻 = 错过真问题。本 skill 提供**实证 + 三角 + 分类决策**的可执行流程。

---

## §-1 前置条件(plugin 依赖)

本 skill 引用以下外部 skill / subagent:

| 引用 | 来源 | 必装否 |
|---|---|:-:|
| `general-purpose` subagent | Claude Code 内置 | ✅ 始终可用 |
| `Plan` / `Explore` subagent | Claude Code 内置 | ✅ 始终可用 |
| `claude-code-guide` subagent | Claude Code 内置(部分版本)| 检查 Task tool schema;不可用 → Agent 改用当前宿主的通用审查能力并自行查官方文档 |
| `superpowers:receiving-code-review` | `superpowers` plugin | 强烈推荐(本 skill §5 引其方法论)|
| `superpowers:verification-before-completion` | 同上 | 类 A 实施完后用 |
| `mattpocock-skills:grill-with-docs` | `mattpocock-skills` plugin | §3 候选组合可选 |
| `mattpocock-skills:improve-codebase-architecture` | 同上 | §3 候选组合可选 |
| `mattpocock-skills:zoom-out` | 同上 | §3 候选组合可选；不能由 Agent 调用时选用等价的当前宿主审查能力 |

**依赖处理**:Agent 先发现当前宿主已有能力。缺少可选 plugin 时默认用内置审查能力降级；若安装确有材料收益且涉及外部变更，展示宿主原生 Allow/Deny，Allow 后由 Agent 安装并验证。不得把安装命令交给用户。

---

## §0 触发条件

任一命中 → 启动本 skill:

| 触发 | 例 |
|---|---|
| 重大 doc 起草后 | >500 行设计 doc / 涉及协议字段 / 含架构决策 |
| 重大 code merge 前 | >10 文件 / 跨模块 / breaking change / 第三方依赖切换 |
| 发版前 final check | tag / release 前 |
| 用户主动问 | "现在有什么问题 / 哪里需要修 / review 一下" |
| 自审触发 | 你自己起草后觉得"是不是漏了什么"|
| 跨决策边界改动 | public/private / license 切换 / scope 大调 |

**不触发**:小 bug fix / 一行改 / 局部 refactor / 临时实验。

---

## §1 第一步:区分代码评估 vs 文档评估

不同目标维度不同,**不可混评**。

### 1.1 代码评估维度

| 维度 | 检查点 | 工具 |
|---|---|---|
| **协议合规** | API contract / framework convention / hook spec / schema | `claude-code-guide` subagent(若是 Claude Code) / 官方 docs WebFetch |
| **安全** | secrets / auth / injection / OWASP / XSS / SQL | grep secrets / 静态分析 / dep scan |
| **性能** | 算法复杂度 / 资源占用 / 并发 / 内存泄漏 / N+1 | profiler / benchmark / Diagnose skill |
| **测试覆盖** | 单测 / 集成 / edge cases / regression | coverage report / TDD skill |
| **runtime 实证** | build / install / 启动 / 跑得通 | verification-before-completion skill |
| **依赖一致** | lock file / version drift / cyclic dep | dep tree / lock check |

### 1.2 文档评估维度

| 维度 | 检查点 | 工具 |
|---|---|---|
| **路径实证** | 每个引用 file path / URL / command 实测可达 | `ls / find / curl / WebFetch` |
| **链接有效** | 相对 / 绝对 / GitHub 渲染 / 跨 doc 引用 | grep `\.md\)` + 实测点击 |
| **内容准确** | claim vs 实际 codebase / 数字一致 / 段落间不矛盾 | grep + 计数 verify |
| **PII / secrets** | 真名 / email / API key / 绝对路径 / 公司内部 URL | `grep -rE` 多 pattern |
| **reviewer context** | reviewer 是否清楚 doc 服务的 audience / 决策边界 | 跨 review 对照 |
| **可执行性** | 跟着 doc 步骤走能完成目标吗?有断点吗? | 假装新用户走一遍 |
| **deprecation 链路** | 老 doc 是否标 DEPRECATED 指向新 doc | grep "DEPRECATED" + 头部 banner |

### 1.3 混合(代码 + 文档)

实际项目常混(代码改 + doc 同步)。**先分,再合**:列出代码维度 finding + 文档维度 finding,**不要混在同一份 review prompt**(reviewer 会顾此失彼)。

---

## §2 第二步:候选 skill / Agent 矩阵(按能力)

启动 review 前**先列候选**(按 angle / 能力),不要一上来就 spawn 全部。

| skill / agent | 强项 | 适合 | 工时 |
|---|---|---|:-:|
| `claude-code-guide` subagent(若可用)| Claude Code 协议层(hook / skill / plugin / API) | 代码评估 — 协议合规 | 5-10 min |
| `general-purpose` + WebFetch 官方 docs(fallback) | 同上,若 `claude-code-guide` 不可用 | 代码评估 — 协议合规 | 8-12 min |
| `general-purpose` subagent(fresh context) | 独立视角 / 不读本 session 历史 / 综合判断 | 文档评估 — 内容质量 + 隐私 + 体验 | 10-15 min |
| `mattpocock:grill-with-docs` | 对照已有 docs / ADR / 哲学一致性 | 文档评估 — 跨 doc 一致 | 10-15 min |
| `mattpocock:improve-codebase-architecture` | 重构 / 合并 / DRY 机会 | 代码评估 — 架构层 | 10 min |
| `mattpocock:zoom-out` | 拉高视角看整体方向 | 通用 — 防陷局部 | 5-10 min |
| `superpowers:receiving-code-review` | 元 review — 处理 review feedback 不盲目 | 通用 — 必配 | 5 min |
| `superpowers:verification-before-completion` | claim 完工前自检 | 通用 — 必配 | 5 min |
| `Plan` subagent | 架构师视角 / trade-off / 实施风险 | 通用 — 大改动前 | 10 min |
| `Explore` subagent | 快速 grep / read 全 codebase 找 pattern | 代码评估 — 探索 | 5-10 min |
| 宿主原生高阶 review | 多 Agent 云审 + 可能计费 | 代码评估 — 终审 | 先展示原生计费/高风险决策，Allow 后由 Agent 启动；不可用则降级 |

**禁忌**:不要一次 spawn ≥4 subagent — 信息过载,你无法消化。

---

## §3 第三步:组合 ROI 推荐 + 让用户选

按 angle 给 **候选组合表 + 工时 + ROI 理由**,让用户挑(不是抛 N 选 1,是基于实证给推荐 + 备选)。

### 推荐组合模板

| 顺序 | skill 组合 | 目的 | 工时 |
|:-:|---|---|:-:|
| ★ 1 | 元 review + 拉高视角 | process 已有 finding 分类 + 整体方向 check | ~10 min |
| 2 | 协议层 + 内容质量 双 subagent 并行 | 第一轮覆盖代码 + 文档 双维度 | ~15 min |
| 3 | 域一致性(grill-with-docs) | 防 v2 doc 改动破坏 v1 哲学 | ~10-15 min |
| 4 | 三角验证 subagent | 防单源 reviewer 误判(见 §4)| ~10 min |
| 5 | 架构 refactor | 大改动后的 DRY 机会 | ~10 min |

**给推荐 + trade-off + 等用户选**(不直接 spawn 全部),例:

> "推荐 ★ 1 + 2 并行(~25 min)— 元 review process finding + 双 subagent 覆盖代码 + 文档双维度。
> 若担心单源风险,加 4 三角验证(~10 min);若想拉高看方向 add ★ 1 already 含 zoom-out。
> 不推荐一次 spawn ≥4 subagent(信息过载消化不了)。
> 跑 ★ 1+2 还是加 4 三角验证?"

---

## §4 第四步:三角验证铁律(critical claim 必)

**单 reviewer 实证 critical claim 不够**。任一命中 → 必三角:

| 触发 | 例 |
|---|---|
| 协议字段 / 字段名 | reviewer 说 "API X 字段是 Y" → 必 WebFetch 官方 docs 原文 quote |
| 数字 / 计数 | reviewer 说 "N 处文件含 X" → 必自己 grep 复核 |
| 路径 / URL | reviewer 说 "path Z 是 standard" → 必实测 `ls / find` |
| 推翻之前决策 | reviewer 说 "之前 architectural decision 是错的" → 必让独立 reviewer 二次确认 |
| 协议未明 / 行为不定 | reviewer 说 "协议没说清楚" → 必 WebFetch 找更细 docs(可能 reviewer 漏看)|

### 三角验证 prompt 模板

```
独立三角验证 [target] 的 [N] 项 critical claim。**不读本 session 上下文,只看 codebase + 官方 docs 实证**。

前 [N] 份 review 给 [M] 项 finding,其中 [K] 项 critical claim:
1. [claim 1]
2. [claim 2]
...

前 reviewer 可能偏差:
- reviewer 1: [可能偏差]
- reviewer 2: [可能偏差]

三角验证 [K] 项:
### V1. [claim 1]
实证命令:[精确 bash command 或 WebFetch URL]
判定:✅ 真 / ❌ 误 / ⚠️ 部分

### V2. ...

输出综合判定:[K] 项中真正必修哪几项 / 哪几项 reviewer 误判。
```

### 实战教训(本 skill 来源 case)

| Case | 错 | 三角验证 catch |
|:-:|---|---|
| 1 | 单 reviewer 说"协议没说清楚同 name skill 行为"| WebFetch 官方原文 quote:`Plugin skills use a plugin-name:skill-name namespace` — reviewer 漏看 |
| 2 | 单 reviewer 说"N 处含 X token" | 自己 `grep -rln "X" .` 复核;reviewer 可能漏 grep 范围 / 用错 file glob → 数字偏高或偏低 |
| 3 | 单 reviewer 实证不存在的协议字段(`statusMessage`)| 第二 reviewer WebFetch 官方表 — 字段不存在 |

---

## §5 第五步:用 receiving-code-review 4 类分类 finding

review 结果到手后 **不盲目实施 / 不盲目推翻**。按 4 类分:

### 🔴 类 A — 真 bug(无论 context 都修)

- 协议错(JSON 字段名错 / schema 不合规)
- broken reference(引用不存在 file / tag / URL)
- runtime 失败(装上跑必坏)
- 绝对路径写死(换机器坏)
- 安全漏洞

**处理**:**立即修**,不需用户确认。

### 🟡 类 B — Reviewer 缺 context(不修 + 标 reasoning)

- 基于错误假设的 finding(reviewer 不知 audience / 决策边界)
- 跟用户之前决策冲突的"建议"
- 重新发明轮子的"professional feature"(YAGNI)

**处理**:**不修** + 文档/commit message 标 "push back reasoning: reviewer 不了解 [X]"。

**不要 performative agreement**(避免:"You're absolutely right" / "Great point" / 然后全实施)。

### 🟠 类 C — 跨决策边界(必用户拍)

- 涉及 architectural decision(public/private / license / scope)
- 涉及 trade-off(性能 vs 可读性 / 短期 vs 长期)
- 涉及第三方影响(团队成员 PII / 已 release 用户兼容)

**处理**:**STOP 实施**,列出 trade-off + 推荐路径 + 等用户拍。

### 🟢 类 D — Nit / 可选(列出供参考)

- 措辞 / 格式
- 风格偏好
- 边缘 edge case

**处理**:列出,**不一定修**。若工时短(<5 min)且无害,顺手改。

---

## §6 第六步:跨决策边界识别(stop and discuss)

任何 finding 命中以下 → **停**,问用户:

| 边界 | 例 |
|---|---|
| public / private | "应该转 private repo" / "应该公开" |
| license | "应该切 BSL / 应该 MIT" |
| scope | "应该删 / 应该加 feature" |
| breaking change | "应该 force push / rewrite history" |
| 第三方 PII | "应该删真名 / email" |
| 架构 | "应该重写 / 应该 deprecate" |

**禁忌**:reviewer 推荐的 architectural change **绝不**直接实施,即使听起来合理。

---

## §7 第七步:输出最终决策矩阵

完成上述步骤后,给用户清晰的 **决策矩阵**(template):

```
## 最终决策矩阵(综合 N 份 review + 实证)

### 🔴 类 A — 必修(M 项,立即实施)
| # | finding | 实证理由 |
| A1 | ... | ... |
...

### 🟡 类 B — 不修(K 项)
| # | finding | push back reasoning |
| B1 | ... | reviewer 缺 [context] |
...

### 🟠 类 C — 用户拍(P 项)
| # | finding | 决策路径(P1/P2/P3 + trade-off)|
| C1 | ... | P1: 操作 X, trade-off Y; P2: ... |
...

### 🟢 类 D — Nit(Q 项,可选)
- ...

## 推荐
基于实证 trade-off,推荐 [路径]。理由:[1-2 句]。
```

然后:
1. **不等用户**:类 A 立即实施(短的 inline,长的下个 message commit)
2. **等用户**:类 C 必等拍
3. **不实施**:类 B 不修(commit message / doc 内标 reasoning)
4. **可选**:类 D 列供参考

---

## §8 反模式(本 skill 防止的 case)

### 反模式 1:Performative agreement

❌ 看 reviewer finding → "都对!实施!" → 全改 → 引入新 bug + 推翻自己之前决策

✅ 实证每项 → 分 4 类 → 类 A 改 / 类 B 不改 / 类 C 等用户

### 反模式 2:单源协议实证

❌ 派 1 个 claude-code-guide → "官方说 X 字段" → 信仰 → 实施 → P1 翻车

✅ 派 2 个独立 subagent (或 1 个 + 自己 WebFetch 二次)→ 对比 quote → 一致才信

### 反模式 3:Reviewer 跨决策边界,盲目接受

❌ reviewer 说"应该 force push rewrite history" → 立即跑 `git push --force` → 团队炸锅

✅ 识别"force push" = 跨架构边界 → 类 C → 列 trade-off → 等用户拍

### 反模式 4:代码评估 + 文档评估 混 prompt

❌ "review 这个 PR" → reviewer 顾代码漏 doc / 顾 doc 漏代码

✅ 分两个 prompt:一个聚焦代码(协议 / 安全 / 性能),一个聚焦文档(路径 / 链接 / PII)

### 反模式 5:数字 / 计数 finding 不自己 grep verify

❌ reviewer 说 "8 处含 X" → 直接信 → 列入修 list

✅ 自己 `grep -rln "X" .` → 实证后再 list(reviewer 可能漏 grep 范围 / 用错 glob,数字易偏)

---

## §9 触发例(自检该不该用本 skill)

### 该用

- "我刚把 v0.2.0 设计 doc 改完,review 一下"
- "这个 PR 改了 15 个 file,merge 前 review"
- "现在有什么问题?"(用户主动问)
- "应该 commit + push 吗?"(claim 完工前)

### 不该用

- "改个 typo"
- "这一行能不能这样写?"
- "解释一下这段代码"

---

## §10 与其他 skill 配合

| skill | 何时配合 |
|---|---|
| `superpowers:receiving-code-review` | 本 skill §5 4 类分类引用其方法论 |
| `superpowers:verification-before-completion` | 类 A 实施完后用它 verify |
| `mattpocock:grill-with-docs` | §3 推荐组合的候选之一 |
| `writing-task-md`(若 sulde-cc 装)| review 类 A 修复若 >30 行,走 task md |

---

## §11 输出 commit 时

类 A 修复后 commit message 必含:
- review source(哪几个 reviewer / subagent)
- 接受的 finding(哪几项,简号 A1-AN)
- push back 的 finding(哪几项 + reasoning)
- 等用户拍的 finding(哪几项 — commit 时未实施)

**真实例**(取自一次 plugin v0.1.x review,作为格式参考 — 你的项目用对应 finding 编号填):

```
fix: address multi-source review findings A1-A7

Reviewers: <protocol-review-subagent> + <content-review-subagent> +
<triangulation-subagent>.

Accepted (N fixes):
  A1: <finding 1 short description> → <action taken>
  A2: <finding 2> → <action>
  ...

Pushed back (M findings):
  B1: "<finding>" — reviewer assumed <X>; user decision: <Y>
  B2: ...

Deferred to user decision (K):
  C1: <decision-boundary finding> — see follow-up <doc / issue>
```

> ⚠️ 上面是**模板示例**,不是硬性 require 字段。关键纪律是 3 段:Accepted / Pushed back / Deferred(每个 finding 都要给个明确的"我做了什么")。

---

**Final rule**:本 skill 的目的不是"做全所有 review",而是**用最少 token + 最准确 finding 出可执行决策**。Over-review 也是反模式。
