---
doc_id: "ap-0038"
container: anti-patterns
platform: none
summary: "Wizard / 多 step 任务书未列 step 编号 → Dev 误按 pageId 字母推导顺序"
---

# 0038 — Wizard / 多 step 任务书未列 step 编号 → Dev 误按 pageId 字母推导顺序

- **平台**:协调端 task md 写作
- **复发次数**:1
- **lint 状态**:协调端任务书写作类，无法静态扫描

## ❌ 错误

协调端 task md 只列 pageId 不列 wizard step #，Dev 按任务书行号或 pageId 字母推导 step 顺序：

```markdown
| # | sub-page | pen-truth 文档 | view 文件 |
|---|---|---|---|
| 1 | {流程入口} Chat | ... | ... |
| 2 | {子页 A} Input Analysis | ... | ... |   ← Dev 看 #2 想到"step 2"，实际是 wizard Step 1
| 3 | {子页 B} Music Analysis | ... | ... |   ← Dev 误以为 step 3，实际 = wizard Step 2
| 4 | {子页 C} Style Framework | ... | ... |
| 5 | {子页 E} References | ... | ... |        ← 跳号（无子页 D），Dev 不知道
| 6 | {子页 E1} Reference Dialog | ... | ... | ← dialog 不是 step，Dev 容易当 step 6
```

## 为什么错 — pageId 命名约定与 wizard step 编号**不直接对应**

| 命名约定问题 | 表现 |
|---|---|
| **L1**：某 pageId 无 letter 后缀但是 wizard Step 1 | 直觉以为它是 host / 入口，下一个字母页才是 step 1。实际反过来 |
| **L2**：pageId 跳号（只有 A/B/D...） | 某 step 在 PRD 里被砍/合并，但 pageId 保留命名。Dev 不知道偏移 |
| **L3**：带 `1` 后缀的 pageId 是 dialog 子页（不是 step） | 后缀让人猜不出是 step 还是 dialog，序号不可线性映射 |
| **L4**：任务书行号 #N 与 wizard step # 偏差 | 任务书首行可能是非 wizard 入口；dialog 行夹在 step 行中 |

## ✅ 正确（必列 wizard step # 列 + 显式标 dialog / 跳号）

```markdown
> ⚠️ **pageId ≠ wizard step #**：对照本表 wizard step # 列实施，不要按 pageId 字母推导。
> 每个 sub-page 实施前先 grep pen-truth 文档头部的 `> **属于**：Wizard Step N/M` 确认 step 编号。

| # | wizard step # | sub-page | pen-truth 文档 | view 文件 |
|---|---|---|---|---|
| 1 | — 入口（非 wizard）| {流程入口} Chat | ... | ... |
| 2 | **Step 1/N** | {子页 A} | ... | ... |
| 3 | **Step 2/N** | {子页 B} | ... | ... |
| — | **Step 3/N 跳号（无某子页 — 产品规划留缝）**| — | — | — |
| 4 | **Step 4/N** | {子页 D} | ... | ... |
| 5 | (dialog，非 step) | {子页 D1} Dialog | ... | ... |
```

关键改动 4 点：① 加 "wizard step #" 独立列；② 跳号位置显式占行；③ dialog 子页显式标 `(dialog，非 step)`；④ 任务书顶部加 `pageId ≠ wizard step #` 提示。

## lint 状态

- ❌ 协调端任务书写作类，无法静态扫描

## 预防原则（给协调端）

写**任何 wizard / 多 step / 多 stage / 流程**对齐任务时：

1. 派任务前：`for f in pen-truth/{prefix}*.md; do grep "Step.*/" "$f"; done` 扫所有 step # 元数据
2. 任务书表格加"wizard step #"独立列，每行显式填 `Step N/M` / `(dialog，非 step)` / `(非 wizard)` / `跳号`
3. 任务书顶部加显式提示 `pageId ≠ wizard step #`
4. **判定线**：任务书表格无"wizard step #"列 = 不合格，重写

## 关联

- 反模式 0037（多 sub-page 粒度过粗，本条是其细化）/ 0034 / 0035 协调端写作问题
- pen-truth 元数据约定：`> **属于**：Wizard Step N/M`
