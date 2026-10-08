---
doc_id: "ap-0039"
container: anti-patterns
platform: none
summary: "handoff 自检流于声明 → 用户验收发现\"未做\" → 协调端返工"
---

# 0039 — handoff 自检流于声明 → 用户验收发现"未做" → 协调端返工

- **平台**:协调端任务书 + Dev handoff 写作（与技术栈无关）
- **复发次数**:1
- **lint 状态**:写作类反模式，无法静态扫描 → 预防 = 任务书强制 + handoff 模板硬约束

## ❌ 错误（handoff 仅声明，无客观证据）

```markdown
## 完成度

| sub-page | 状态 | 主要 diff 项 | 改动文件 |
|---|:---:|---|---|
| {某子页} | 🟢 全 | 多 section + pill 配色 + 多 block | SomeView |
```

⚠️ 看着像完成，实际可能：代码没改（被后续 patch 绕过）；视觉对齐已做但默认空态遮盖 = 实测不可见；Dev 主观勾 ✅，**没有用 grep / 节点对照 / simulator 实测客观确认**。看 handoff 的协调端 / 用户**也无法判定真假**，文字声明无法证伪。一旦合主干，后续 patch 没人回头查，问题永久残留。

## ✅ 正确（handoff 必带 4 类客观证据，3 种以上必备）

#### 证据 1：grep 实际命令输出（强制粘贴 stdout）

```markdown
### Test 1：section 标题 ≥ 3
$ grep -E "Identity|Analysis|Plan" Sources/.../SomeView.swift
            title: "Identity",
            title: "Analysis",
            title: "Plan",
**3 命中** ≥ 3 ✅
```

#### 证据 2：节点对照表（每节点 pen-truth → 代码 line 号 → 状态）

```markdown
| pen-truth 节点 | 代码行号 | 实现 | 状态 |
|---|---|---|---|
| section header | line 277-303 | Section cr:20 #FFFFFF08 | ✅ |
| 2 pill | line 285-294 | 2× NeutralPill | ✅ |
... ≥ 15 节点
```

#### 证据 3：xcodebuild / gradlew 实际输出（粘贴末 3-5 行，不只声明 BUILD SUCCEEDED）

```markdown
$ xcodebuild ... build 2>&1 | grep -E "error:|BUILD SUCCEEDED|BUILD FAILED"
** BUILD SUCCEEDED **
```

#### 证据 4：simulator / 真机 截图归档（若 agent 因 macOS TCC 无法跑，显式声明 + 留给 QA）

```markdown
## 截图
未跑 simulator 截图（本轮纯逻辑 + 视觉对齐，编译验证已覆盖）。
若需视觉验收，可在本地跑 cmd+R 后人肉对图 {pageId}.png。
```

（参见反模式 0036 macOS TCC 限制 — agent 无法自动 simulator 截图，但应显式声明而非省略）

## 为什么错（根因）

- 任务书模板若只要求"声明完成度"而非"提交客观证据" → Dev 倾向最低成本写"🟢 全"（15 秒）而非真去 grep / 对照（15 分钟）
- 复发概率与 task 复杂度成正比 — 多 sub-page wizard 这种是高危区
- 一旦合主干，后续 patch 没人回头查，问题永久残留

## lint 状态

- ❌ 写作类反模式，无法静态扫描
- 预防机制 = 任务书强制 + handoff 模板硬约束

## 预防原则（给协调端）

写**任何视觉对齐 / 多节点 / 多 sub-page / 多文件**任务时，任务书强制要求：

1. handoff 必含 grep 实际输出（粘贴 stdout）
2. handoff 必含节点对照表
3. handoff 必含编译 / lint 实际输出（命令 + 末 3-5 行真实日志）
4. simulator / 真机 截图（若 TCC 限制无法跑，显式声明 + 留给 QA）
5. 任务书顶部加 ⚠️：`禁止只写"已对齐"或"🟢 全"不附 grep 输出 + 节点对照表`

**判定线**：handoff 内 grep 实际输出 + 节点对照表 任一缺失 = handoff 不合格，打回重交。

## 关联

- 反模式 0037（任务书粒度过粗）+ 0038（Wizard step 编号）+ 0039（handoff 客观证据）= 协作类三联防护
- 反模式 0036（macOS TCC 限制）— 影响证据 4 截图执行环节
