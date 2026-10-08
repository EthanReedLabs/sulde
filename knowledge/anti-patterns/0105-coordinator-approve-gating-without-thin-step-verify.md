---
doc_id: "ap-0105"
container: anti-patterns
platform: none
summary: "协调端 approve gating 契约凭\"通用 UX 模式\"未验 thin step running 行为"
---

# 0105 — 协调端 approve gating 契约凭"通用 UX 模式"未验 thin step running 行为

- **平台**:协调端
- **复发次数**:0(归因到"凭印象不查实证"同源根因)

## ❌ 错误

协调端 review approve Dev 提交的 gating / 解锁数派生 contract 时,凭 "通用 UX 模式 — 早一点解锁让 user 看生成态" 想当然 approve,**未让 Dev 实证 step running 时 step 内字段是否有数据填充 view**。

真值:**thin step**(只 thinking 无 result_summary 的 step,如某分析 step 的 running 帧)running 时 step 内字段为空,UI 解锁但页面**空白**,user 体感比"晚一点解锁但有数据"更差。

```
Dev 提交 gating contract(reachedStageCount 数 success + running)
↓
协调端凭 "早解锁让 user 看生成态" approve "✅ running 也算已达"
↓
未问 Dev "thin step running 时 step 内是否有数据"
↓
Dev 跑出来 → user 真机推翻 "下一步 running 时才看见上一步数据"
↓
Dev 改 success only
```

## 为什么错

**协调端 review approve gating 契约时缺 "thin step running 行为实证" 硬约束**:

- 协调端有能力让 Dev 真机 dump 一帧 state snapshot 验证 thin step running 时字段内容,但没硬约束 review 前必查。
- 凭 "通用 UX 模式" / "平台 HIG 风格" 等抽象原则代替实证。
- gating / 解锁数派生类逻辑**对 step 数据时序敏感** — 不实证就 approve = 凭印象设计。

## ✅ 正确

```
Dev 提交 gating / 解锁数 contract
↓
协调端 review 前先问 Dev:
  "thin step running 时 step 内字段是否有数据填充 view?"
↓
Dev dump 一帧 state snapshot 实证:running 时字段为空
↓
协调端 approve 时显式标:
  "success only(thin step running 时字段空,running 解锁=空白)"
↓
Dev 跑一次到位
```

机制层强制内容:

| 强制内容 |
|---|
| review approve gating / 解锁数派生 contract 前**必让 Dev 实证 "step running 时字段是否有数据填充 view"** |
| thin step**不要 "running 也算已达"** — 解锁后空白页 user 体感更差 |
| task md review approve 段必 quote Dev 实证 |
| 新契约必显式标 "success only" 或 "running 也算已达 + 数据填充实证 line N" |

## lint 状态

- ⏳ pending(协调端判断类,grep 不住)→ 进 task md review checklist。

## 协调端自检(review gating / 解锁数 contract 前)

- [ ] 是否问 Dev 实证 "step running 时字段是否有数据填充 view"?
- [ ] 列出 thin step 清单(只 thinking 无 result_summary 的 step)?
- [ ] 新契约显式标 "success only" 或 "running + 数据填充实证 line N"?
- [ ] 双端同步 verify(Android 同款解锁数派生同病同修)?

任一 ❌ = 不 approve contract,补实证再 review。

## 关联

- 协调端起草 / approve 前未跑 baseline 实证(本款是其在 gating contract review 路径的子模式)。
- 不凭印象下发 task。
