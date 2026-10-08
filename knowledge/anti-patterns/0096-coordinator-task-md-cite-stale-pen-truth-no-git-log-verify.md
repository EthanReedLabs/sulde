---
doc_id: "ap-0096"
container: anti-patterns
platform: none
summary: "协调端写 task md 引过时设计真值没 git log verify → 差点造成代码回退"
---

# 0096 — 协调端写 task md 引过时设计真值没 git log verify → 差点造成代码回退

- **平台**:协调端
- **复发次数**:1
- **lint 状态**:⏳ pending（无法 lint 化，人工 checklist）

> 📍 本反模式已并入"协调端凭印象 / stale Read / 缺 baseline 同源根因" master；保留作历史档案。

## 现象

协调端在双端 audit 对照后写某 P0 fix task md，其中子任务要求:

> **登录 overlay 颜色改为白色 50% alpha**
>
> 当前问题:某端当前 overlay 实现用深黑 70%，与设计真值不符。
> 真值（设计真值文档 — 甲方实时修正）:overlay 颜色改为白色 50% alpha。

Dev 收到 task md 后，**没有盲跑代码**，而是先 grep 当前实施 + Read git log:

- 当前代码实际是黑色毛玻璃（`.ultraThinMaterial + Color.black.opacity(0.15)`）
- git log 显示该 overlay 改动是较近一次"登录黑色毛玻璃"的 commit — **甲方第 3 次修正**
- memory 记录该次修正后真值就是黑色毛玻璃方向

Dev 命中自发修复边界 STOP（scaffold 层 + 跨页统一属性 + 数据源真值冲突），没动代码 + handoff 详细 escalate。

**若 Dev 盲跑** task md = 把黑色毛玻璃改回白 50% alpha = **回退甲方第 3 次修正** = 严重反模式。

## 根因

协调端写 task md 时 audit 路径:

1. 派 subagent 对照设计真值 + audit 结果
2. subagent 报告 "某端历史用深黑 70%，设计真值是白色 50%，需 fix"
3. **协调端直接采纳 subagent 结论写进 task md** — 没做以下 verify:
   - ❌ 没 `git log {目标文件}` 看 overlay 改动历史
   - ❌ 没 grep 当前代码实际 overlay 值
   - ❌ 没 Read memory（明确记录甲方第 3 次修正）
   - ❌ 没 Read 设计真值文档之后的章节（是否有"修正历史"段）

**核心问题**:**设计真值文档本身停留在较早的修正版本，没同步甲方最新一次修正**。subagent 看到的是设计真值，但**真值过时**。

这本质是"协调端 audit 凭症状推 Module 跳 grep 接口契约"反模式的**镜像变种** — 那个是漏 grep 接口文档，本条是漏 grep 当前代码 + git log。

## 损失

- Dev 工时浪费（警觉性高，自己定位真值 + 写 escalate handoff）
- 协调端 + Dev 来回沟通时间
- 设计真值文档长期不同步
- 若 Dev 盲跑 = 回退 + 后续需第二次 fix（双倍工时）
- 反模式认知积累:**audit 引用设计真值不等于真值**（设计真值文档自身可能过时）

## 防再犯 checklist（协调端写 task md 涉及设计真值引用前必跑）

| Step | 内容 |
|---|---|
| 1 | **git log {目标文件} 看近 30 天改动**:若有近期改动 → 真值可能比设计真值文档新 |
| 2 | **grep 当前代码实际值**:对照设计真值引用值，若不一致 → 当前代码可能就是新真值 |
| 3 | **grep memory**:找相关 project / feedback memory，可能记录甲方临时修正 |
| 4 | **Read 历史 handoff archive 近 30 天**:看是否有相关改动 |
| 5 | **若以上任一发现"真值已迁移" → 同步更新设计真值文档 + 标 deprecated**，再决定是否派 task md |
| 6 | task md 内引用设计真值时，必加版本时间戳（如"设计真值 YYYY-MM-DD 版本"）让 Dev 警觉 |

## lint 候选

⏳ pending — 无法 lint 化（协调端文档 / task md 操作流程，非代码层）。

候选规则:
- 若 task md 内引用设计真值路径 → grep 该文档中是否含"已废弃 / deprecated / 修正"等关键词，若有 → 警告"真值可能过时"
- 若 task md 要求"修改某 scaffold 文件" → 必加"先 git log {文件} 近 30 天"前置 checklist

## 关联

- 凭印象不查实证（上层根因）
- 协调端 audit 跳 grep 接口契约（镜像变种）
