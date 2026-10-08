---
doc_id: "ap-0037"
container: anti-patterns
platform: none
summary: "多 sub-page 链路 / wizard 流程对齐任务用单行表对待 → 视觉粒度严重丢失"
---

# 0037 — 多 sub-page 链路 / wizard 流程对齐任务用单行表对待 → 视觉粒度严重丢失

- **平台**:协调端 task md 写作
- **复发次数**:1
- **lint 状态**:协调端任务书写作类，无法静态扫描

## ❌ 错误

协调端老任务对 wizard 链路用一行表，把一整条多 sub-page 流程压成一行：

```markdown
| pageId | 名称 | 对应 View |
|---|---|---|
| {主页} Add Music | MusicPickerView |
| {子页} Music Selected | MusicPicker 已选态 |
| {流程入口} Chat | GenerationView (Chat tab) |
| {流程容器} Preview | GenerationView (Preview tab) |  ← ❌ 一行包含十几个 sub-page
```

## 为什么错

- 该容器在 PRD 定义里是 **十几个独立 sub-page**
- 每个 sub-page 有独立 pen-truth 文档（百行级）+ 独立视觉规格 + 独立交互
- 任务粒度只到"容器 tab"层 → Dev 把"对齐 tab 容器结构"当成"对齐整条链路"完成
- 实际每个 sub-page 没有逐项 diff pen-truth，导致**容器对了但每个 stage 内部视觉全没对**
- 用户验收时发现"链路与设计稿没对齐"，回头复查发现根本没派过细粒度任务

同源问题模式：任何 wizard / 多 stage / 多 sub-page 流程都可能踩（多步创作流 / 多 tab 子页面 / 多档卡片页等）。

## ✅ 正确（协调端任务书展开 sub-page）

```markdown
## {流程} 全链路视觉对齐（双端各派）

逐 sub-page 必须独立列出 + 关联 pen-truth + 期望容差：

| sub-page | pen-truth 文档 | 当前 view 文件 | 关键 diff 点 |
|---|---|---|---|
| {子页1} | pen-truth/{id1}.md（N 行） | {View1} | 顶部 header / 输入卡 / 配色与节点 |
| {子页2} | pen-truth/{id2}.md（N 行） | {View2} | … |
| {子页3} | pen-truth/{id3}.md | {View3} | pill 色阶 / block 结构 |
| ...（每 sub-page 一行）|

**Dev 必须逐 sub-page 对照 pen-truth 跑 visual diff，handoff 内显式说明每 sub-page 改了哪些属性。**
```

## lint 状态

- ❌ 协调端任务书写作类，无法静态扫描

## 预防原则（给协调端）

写**多 sub-page / wizard / 多 stage 流程**对齐任务时，**任务书每行只能管 1 个 sub-page**：

1. 派任务前必须 `ls pen-truth/{prefix}*.md` 列出该链路所有 sub-page
2. 任务书表格的"对应 View / Fragment"列必须细到每 sub-page 一行
3. 任务书显式要求 Dev "逐 sub-page 对照 pen-truth diff，handoff 写每 sub-page 改的 token / 节点"
4. **任何"链路 / 流程 / wizard"对齐任务，行数 < sub-page 数 = 必踩此坑**

**判定线**：任务粒度行数 < pen-truth 文件数 ⇒ 任务书不合格，重写。

## 关联

- 反模式 0034（任务书硬约束写字面行数）/ 0035（引用旧版 PRD）— 同源协调端写作问题
- 反模式 0038（wizard step 编号）/ 0039 / 0040 — 协作类联防
