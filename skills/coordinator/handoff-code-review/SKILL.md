---
name: handoff-code-review
description: 协调端 review Dev handoff 必跑 — 4 维 code review(常规检查 + 架构统一 + 复用抽取 + 最小代码改动)。当 Dev 给 handoff result.md / 用户说"review handoff / 看看 dev 做的对不对 / 检查一下 commit / dev handoff 完了"等触发词或 dev 任一 task 完工时必 invoke。区别于 multi-source-review(后者是重型 >500 行/>10 文件场景)。本 skill = 每次 handoff 轻量 review,4 维只看 1 task 范围。Outputs verdict(✅ merge OK / ⚠️ partial / ❌ block + fix task)+ 4 维表 + escalation triage。
user-invocable: true
---

# handoff-code-review — 每次 Dev handoff 必跑 4 维 review

> **Why this skill exists**:Dev handoff "shipped" ≠ "对",更不等于"最优"。常规检查只覆盖 build/runtime/visual 表层;**架构是否统一 / 复用是否到位 / 非架构问题是否最小改动**这 3 维常被遗漏 → 累积技术债 + scope 漂 + 同款 bug 反复。本 skill 强制 4 维过一遍。
>
> **不替代 multi-source-review**:那是 >10 文件 / 跨模块 / 大决策的重型 review;本 skill 是每次 Dev handoff(通常 1 task / ~几百行)的轻量 review。

---

## §0 触发条件(任一命中即跑)

| 触发 | 例 |
|---|---|
| Dev 给 handoff path | "handoff: .ai-workspace/handoff/.../X-result.md" |
| 用户口头 review | "review 一下 / 看看 dev 做的对不对 / 检查一下 commit / 评一评" |
| Dev 完工通知 | "任务还在继续吗 / dev handoff 完了 / 派下一拍前 review" |
| 协调端起新派单前 | 上一个 task 未 review 即派下一拍 → 强制 review |
| handoff 标"✅ shipped"或"✅ merge OK" | 协调端不盲信,实证 4 维 |

**不触发**:doc 起草 / 反抽 / 计划 / 用户问"plan" / 协调端自己 commit。

---

## §1 4 维检查清单(全过 + 表格输出,不可省)

### 维 1 — 常规检查 ✅ (标准 handoff 验证)

| 项 | 验证 |
|---|---|
| **build** | 构建成功 + 0 ERROR + WARN 全 stale(非本 task 引入)|
| **install** | 安装成功 + 启动成功 |
| **runtime log** | 关键路径 tag 触达(按 task 定义的埋点 tag)+ 0 FATAL / 0 crash / 0 异常 layout warn |
| **真机视觉(dual-mode 强化)** | screenshot 实证(截图归档目录)+ 视觉对比表 **light + dark each ≥ 5 元素**(per task md §5)+ each mode **❌ ≤ 1 REJECT**(per UI 还原 Pre-merge gate,per user 反馈"dark/light mode 总搞错")— Dev handoff 仅给 light 不给 dark = ❌ block + 派 fix task |
| **handoff §0 反抽对照表** | 真值源 file:line ↔ 实现端 file:line ↔ ✅/❌ 全 row 填齐 |
| **§7 自检 N 问** | UI 还原 task 全答(or 子任务相应自检)|
| **真机自动化补测** | UI 自动化 dump + click + keyEvent + dump pop verify(用户要求时强制)|

**判定**:任一缺 → ❌ block + 要求 Dev 补 handoff;全 ✅ → 进维 2。

### 维 2 — 架构统一 ⭐ (核心)

**问**:Dev 用的是项目已有 pattern,还是另起炉灶?同款问题用同款解?

| 维度 | 检查 |
|---|---|
| **路由 / 入参** | 走项目既定路由入参读法(经统一 context/param API)— 禁另起 router API;子页禁经 pageMap forward 用非统一装饰器传参 |
| **DTO 解析** | 走统一 opt helper(optNum / optStr / optBool / optArr 一类容错取值)— 禁 hardcode 字段 / 禁强转 |
| **API 调用** | 走统一 HttpClient + Result<T> 封装 — POST 参数走既定通道(与真值源等价)— 禁 raw fetch / 禁参数塞错位置 |
| **Dialog / modal** | 走项目统一 overlay pattern — 禁残留旧框架命令式 dialog API |
| **Builder / 组件复用** | 遵循平台声明式 UI 约束(如 @Builder 不支持对象参数子方法)— 多 Card / 多 Section 复用走 inline + 共用 Title Builder + 数值常量 |
| **资源迁** | 走项目资源系统约定(dark 资源目录约定 / 系统图标优先)|
| **持久化读写** | 走 STORAGE_KEY 一类常量 — 禁字面量 |
| **UI 装饰兼容坑** | 避开平台已知不渲染/不兼容属性(见平台 KB incompatibility 清单)— 用替代实现绕过 |
| **动画加载** | 避开平台已知失效加载方式 — 用直传数据绕过 |

**判定**:
- ✅ 全部走既定 pattern → 进维 3
- 🟡 局部偏离 + Dev §upgrade 已报清楚 → 接受 + handoff escalation
- 🔴 多处自创 pattern / 偏离已知 rule + 未 escalate → ❌ block + 派 fix task

### 维 3 — 复用 / 抽取复用 ⭐ (反 over-engineer + 反 copy-paste)

**问**:既有组件 / 工具 / asset 被复用了吗?新建的有没有过度抽取?

| 维度 | 检查 |
|---|---|
| **既有 asset 复用** | 资源迁前先 ls 资源目录 grep 同款文件(前序 task 已迁过的应复用,不再 cp)|
| **既有 model 复用** | grep 现有 model 目录是否覆盖本 task 字段(应加字段而非新建近重复 model)|
| **既有 API 复用** | grep 现有 api 目录 既有 method(前序 task 已加的应复用)|
| **既有 component 复用** | grep 现有 view 目录 现有 Cell / Dialog / Card(前序已建的复用其 pattern,不重抽)|
| **既有 token / constants 复用** | color token + Sizes / FONT_SIZE constants — 禁 hardcode hex / 禁 magic number |
| **既有系统图标复用** | 系统图标候选已 verified 的直接复用 |
| **新抽取是否值得** | 同款 pattern ≥ **3 处用**才抽 @Builder / Helper;1-2 次用 inline(per「复用最小代码」原则)— **eg 抽了发现平台不支持后改回 inline = ✅ 正确退步,不强抽** |

**判定**:
- ✅ 复用充分 + 不过抽 → 进维 4
- 🟡 漏复用 1-2 处(eg 新 asset 应复用)→ 接受 + 记 escalation 后续修
- 🔴 整体 copy-paste 既有逻辑 / 或 1-2 次用强抽 helper → ❌ block + 派 refactor

### 维 4 — 非架构问题最小最少代码改动 ⭐ (反 scope 漂)

**问**:小问题用了大改动吗?顺手 fix 其他?out-of-scope 自加?

| 维度 | 检查 |
|---|---|
| **改动文件数 vs task scope** | task md §改动文件清单 估 N file,实际 ≤ N + 1(允许小冗余);> N+2 → 嫌疑 scope 扩(per「协调端·Dev 复用最小 task scope」原则)|
| **改动行数 vs 视觉范围** | UI polish ~50-200 行 / 单点 wire ~5-20 行 / 完整新 page ~200-500 行;远超估算 → 嫌疑 scope 扩 |
| **顺手 fix 其他** | grep diff 看是否 fix 了 task 外文件(eg 修了某无关页的 deprecated warning 但 task 是另一页)→ 🔴 顺手 fix 是 scope 漂(per scope 自检 3 问)|
| **scope 邻问拍板** | handoff §scope 自检列出"相邻问题"但 Dev 没动 → ✅ 自律好;Dev 主动扩 + 没 escalate → 🔴 block |
| **out-of-scope 显式不动** | task md 明示"不动 X / Y / Z"(eg "不动路由表 / 不动主页 pageMap")→ grep diff verify 真没动 |
| **scaffolding 副产品** | 新建 X 但本 task 用不到所有 method → 🟡 only-what-needed 原则(**不许 stub** 同时也 **不许 over-build**)|
| **comment 残留** | `// TODO: xxx` `// removed: xxx` `// FIXME` 等 — 用户实施前应清 |

**判定**:
- ✅ 改动量与 scope 匹配 + 无顺手 fix → final ✅ ship
- 🟡 1-2 处轻微扩,Dev §upgrade 标 → 接受
- 🔴 显著扩 / 顺手 fix 多 → ❌ block + 退回 task 重做

---

## §2 输出格式(强制)

每次 review 必输出**完整 4 维表 + verdict**,不可只口头说"OK":

```markdown
## handoff review:<task slug>

| 维 | 1 常规 | 2 架构 | 3 复用 | 4 最小改动 |
|---|:-:|:-:|:-:|:-:|
| 状态 | ✅ | ✅ | 🟡 | ✅ |
| 关键发现 | build OK / log clean | 路由走统一 param API ✅ | 资源 X 应复用,Dev 新迁 | 改动 N file 与 scope 一致 |

**verdict**: ✅ merge OK / ⚠️ partial(merge + escalation)/ ❌ block(派 fix task)

**escalation 候选(转后续 task)**:
- [ ] 维 N 的 🟡 项 → ...
```

---

## §3 反模式禁区(自我提醒)

- ❌ Dev handoff "✅ shipped" 就 ack 不实证 4 维 → 同源问题反复
- ❌ 维 2(架构)只看新代码,不交叉验既定 pattern → 偏离累积
- ❌ 维 3 漏复用 audit → 同款 asset / model / component 多次 cp,技术债爆炸
- ❌ 维 4 接受"顺手 fix" 不问理由 → scope 漂传染整个 sprint
- ❌ 不给 verdict / 不写表格 → 用户看不到明确结论,无法决策下一拍

---

## §4 升级路径(本 skill = 默认轻量;多类升级触发)

| 触发(本 skill 输出后) | 升级到 | 谁触发 |
|---|---|---|
| 维 4 嫌疑 scope 漂 / "改这么多有必要吗" | **`grill-me`**(反问决策树 stress-test)| 当前宿主可调用时由协调 Agent 调用；否则用等价审查能力 |
| 维 2 多处偏离架构 / 局部细节看不全 | **`zoom-out`**(拉高视角,可能 `disable-model-invocation`)| 可调用时由协调 Agent 调用；不可调用时使用等价架构审查，不把 slash 命令交给用户 |
| 维 2 复发型 bug 真因不定 / 多端真因诊断 | **`diagnose`**(系统化诊断,reproduce→minimise→hypothesise→instrument→fix→regression-test)| 当前宿主可调用时由协调 Agent 调用 |
| 对话压缩 / session 接力 / `/clear` 前 | **`handoff`**(session 接力别名,**与本 SKILL `handoff-code-review` 不同**)| 由协调 Agent 调用 |
| 维 1 真机 verify driver(build + install + start + UI 自动化)| **`verify`**(跑 app 看实际行为,补强 build/install 后实测)| 由协调 Agent 调用 |
| 维 3 复用 quality + auto-fix(⚠️ 限文档/KB 类文件)| **`simplify`**(review changed code for reuse / quality / efficiency + 自动 fix)| ⚠️ **仅协调端 invoke 在 docs-hub / docs / kb 文件**;**禁** invoke 在实现端源码(源码 fix 走 Dev,per 协调端 docs-hub 维护边界)|
| Dev "我跑完了" 主动请 review | **`requesting-code-review`**(对 Dev handoff 走完整 review)| 协调端 invoke |
| Dev 收 review 反馈评是否接受 | **`receiving-code-review`**(rigour + verification,no performative agreement)| 协调端 invoke(本 SKILL §1 维 1 4 桶分类时引用)|
| 维 2 / 维 3 有 🔴 + 涉及 >10 文件 / 协议字段 / 架构决策 | **`multi-source-review`**(三角验证 + 4 桶分类)| 协调端 Read + 执行 |
| Dev 完工前 / 协调端声明 ship 前 | **`verification-before-completion`**(evidence before assertions)| 协调端 invoke |
| 大改 / 高风险 / 多端架构改造 | **宿主原生高阶 review**(多 Agent 云审)| 展示原生计费/高风险 Allow/Deny，Allow 后由协调 Agent 启动 |

### 命名实证注意

- ⚠️ **本 SKILL 名 `handoff-code-review` ≠ session 接力用的 `handoff`**;后者是对话压缩 / session 接力,本 SKILL 是单 task 4 维 review
- 部分 skill 设 `disable-model-invocation: true`(如 `zoom-out`)→ 协调端改用当前宿主可调用的等价审查能力，不要求用户代触发
- 依赖缺失时由 Agent 发现并降级；确需安装且涉及外部变更时走宿主原生 Allow/Deny，Allow 后由 Agent 安装

### 串行原则

本 skill **始终先跑**(维 1-4 表 + verdict);输出 🟡 / 🔴 后再升级。
- 🟡 多 + 维 4 嫌疑 scope 漂 → `grill-me` stress-test 真的需要这么多?
- 维 2 多处偏离已知 rule → `diagnose` 找根因 + `zoom-out` 拉视角
- 维 2 / 3 🔴 + 大改 → `multi-source-review` 三角
- 完工前 final → `verification-before-completion`
- 大架构改 / 跨模块 → 原生计费/高风险 Allow 后由 Agent 启动高阶 review

**单 task / 1-2 文件 / <500 行 → 本 skill 单飞,不升级**。

### 与既定 skill 对比(为何不替代)

| 场景 | 本 skill | grill/zoom/diagnose 套 | multi-source-review | /ultrareview |
|---|:-:|:-:|:-:|:-:|
| 每次 Dev handoff 自动跑 | ✅ 协调端自动 | ⚠️ Agent 按可用能力调用 | ❌ 重型 | ❌ billable，需原生确认 |
| 工时 | 5-10min | grill 10 / zoom 5 / diagnose 20 | 15-30min opus | 10-15min 异步 |
| token cost | 低 | 中(交互式)| 高(subagent triangulation)| 高(云 multi-agent)|
| 项目 KB 沉淀 | ✅ platform-kb + 记忆引 | ❌ 通用 plugin | ⚠️ 部分 | ⚠️ 部分 |
| 4 维输出表 | ✅ 强制 | ❌ 各 skill 输出格式不一 | ✅ 4 桶分类 | ✅ 多 agent 报告 |

---

## §5 invoke 时机

- 用户给 handoff path → **立即跑本 skill**,不直接派下一拍
- 协调端起新派单前自检 → "上一个 task review 跑过没?" 没跑 → 跑
- 已 push / 已 merge → **仍跑**(防 stack 累积偏)

---

**未命中检查项** → handoff §upgrade 报 → 协调端追加到本 skill。

---

## §6 Pre-merge dual-mode gate(per user 反馈 "dark/light mode 总搞错")

UI 还原 / transpile / reimpl 类 task,Dev handoff §视觉对比表必含 **light + dark 双 mode 截图比对**,each mode ≥ 5 元素 ❌ ≤ 1。

### §6.1 双 mode 截图取证 protocol(Dev 端,handoff 必跑)

```
# Step 1:切 light mode(App 内主题设置切 "亮" 模式)+ 截图归档
#   实现端真机截图 → screenshots/<task>-light.png

# Step 2:切 dark mode + 重 capture
#   实现端真机截图 → screenshots/<task>-dark.png

# Step 3:真值源同入口 light + dark 截图(user 提供 / 协调端取)
#   screenshots/<task>-truth-light.png + truth-dark.png

# Step 4:handoff §视觉对比表 双 mode 各 5 元素
```

注意主题切换若走 App 内设置(而非系统 toggle),则系统级 uimode 命令不生效 — 按 App 实际主题入口切。

### §6.2 handoff §视觉对比表 dual-mode 模板(强制)

```markdown
## §视觉对比表(dual-mode each ≥ 5 元素)

### Light mode

| # | 元素 | 真值源 ref | 实现端真机 | 一致? |
|:-:|---|---|---|:-:|
| 1 | page bg `#FDFBF7` | `<page>.dart:80` light | screenshots/<task>-light.png 顶部 | ✅ |
| 2 | notice card bg `#FFFCF8` | line 92 light | 同 | ✅ |
| ... | ... | ... | ... | ✅ / ❌ |

### Dark mode

| # | 元素 | 真值源 ref | 实现端真机 | 一致? |
|:-:|---|---|---|:-:|
| 1 | page bg `#111111` | `<page>.dart:80` dark | screenshots/<task>-dark.png 顶部 | ✅ |
| 2 | notice card bg `#1F1F1F` | line 92 dark | 同 | ✅ |
| ... | ... | ... | ... | ✅ / ❌ |
```

### §6.3 协调端 review verdict 判定

| 状态 | 判定 |
|---|---|
| Dev 仅给 light mode 截图 / 表 | ❌ **block** + 派 fix task "补 dark mode 截图 + verify 表" |
| Light ❌ ≥ 2 OR Dark ❌ ≥ 2 | ❌ **block** + 派 fix task |
| Light ❌ = 1 AND Dark ❌ = 1 | ⚠️ partial(merge OK + 2 escalation 候选 各 mode 各 1)|
| Light ❌ = 0 AND Dark ❌ = 0 | ✅ ship |

### §6.4 反例实证

历史:多个 polish 迭代页面因 dark mode 色值反差不足反复返工;多卡 light/dark bg 多次 fix — Dev 仅给 light 截图,user 真机切 dark mode 看才发现 issue。

→ 本 §6 强 enforce 后,Dev handoff 一开始就含 dual-mode 截图,协调端 review 一拍 verdict,不返工。

---

## §7 protocol 演进

- v1.0:初版 4 维 review(常规 / 架构 / 复用 / 最小改动)
- v1.1:维 1 强化 dual-mode 截图 + 新增 §6 Pre-merge dual-mode gate(per user 反馈"dark/light mode 总搞错"+ polish 反例)

下次升版触发:user 新反馈 + Dev handoff 实战发现未命中 review 维度。
