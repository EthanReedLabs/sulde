---
doc_id: "ap-0059"
container: anti-patterns
platform: none
summary: "0059 协调端漏 sweep handoff escalation → 同源问题多次回归"
---

# 0059 协调端漏 sweep handoff escalation → 同源问题多次回归

- **平台**:协调端(handoff 处理类)
- **复发次数**:4+

## ❌ 错误 — 症状

单日复发 4+ 次:
- 某 fix handoff escalation 段自承"子 Feature View 后续 sweep 候选" → 协调端**漏派后续 task** → 同日子页全部跳转失败(modal binding 不识别 state)+ 关联页按钮置灰(同因)
- 某元素此前按 PRD 加 → 后续 audit handoff Dev 自承"该元素在 pen-truth 没有对应节点" → 协调端**漏 sweep 删** → 用户报"私自加上"
- 登录态广播漏覆盖部分子 feature — 协调端历次 task md 未 audit 完整子 feature 字段清单

## 为什么错(根因)

协调端读 handoff 只看改动 / 实证 / mini-checklist 段 — **escalation / 后续 candidates 段没纳入工作流**:
- escalation 段 Dev 自承"未做 / 后续 / 候选"
- 协调端既没立即转 todo,也没派后续 task
- 累积 → 同源问题不同 task 表面修了实际未修 → 用户报回归

## ✅ 正确 — 修法

`coordinator-todos.md` 文件 + 协调端 CLAUDE.md 硬约束:

1. **每次 Dev handoff 收到必 Read escalation 段**
2. **grep "未做 / 后续 / 候选 / 待 / TODO / 暂不动 / 后续 task"** 命中即转 `coordinator-todos.md`
3. 加 P0/P1/P2 + 来源 + 触发条件
4. **不清不撤** — 派 task md 完工才标 `[x]`
5. **写新 task md 前必扫 todos**(防同源漏 sweep)

## 判定线

handoff 含 escalation 段但 `coordinator-todos.md` 无对应条 → 违规。

## lint 状态

- 协调端:`coordinator-todos.md` 文件已建 + CLAUDE.md 硬约束已加
- Dev:N/A(handoff 写 escalation 是已有客观证据规则)

## 关联

- handoff 流于声明 — 父类反模式
- 协调端凭印象 — 同源问题不审 escalation 也是凭印象的具体子集
- `coordinator-todos.md`
