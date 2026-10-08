---
doc_id: "ap-0040"
container: anti-patterns
platform: none
summary: "节点对照表只验证节点存在，不验证视觉属性细节 → \"对齐\"假象"
---

# 0040 — 节点对照表只验证节点存在，不验证视觉属性细节 → "对齐"假象

- **平台**:任何"视觉对齐"任务（iOS / Android / Web 同源）
- **复发次数**:1
- **lint 状态**:难静态扫描 → 预防 = 任务书强制 + handoff 模板硬约束

## ❌ 错误（节点对照表只列节点存在）

```markdown
| pen-truth 节点 | 代码行号 | 实现 | 状态 |
|---|---|---|---|
| section | line 277-303 | Section | ✅ |
| stepFooter | line N | view_step_footer.xml | ✅ |   ← 节点存在 ✅ 但缺 Step 文字 + 缺边框
| {页} title | line N | TextView | ✅ |   ← 但实施可能漏了标题文字
```

⚠️ 看着像完成，实际：
- "节点存在" ≠ "节点视觉对齐"
- pen-truth 真值含 cr / fill / stroke / 字号 / 字重 / padding / 文案 / aspectRatio 等多维属性，**任一缺失都失真**
- Dev 跑 `grep` 命中即勾 ✅，**不验证 cr=20 / fill=#FFFFFF08 / stroke=1pt 等属性**
- handoff 通过验收，但用户实测"细节都不对"

典型表现：footer 缺 "Step N of M" 文字（只画进度 bar）；panel 缺 stroke 边框；某页缺顶部标题 + 自加了不在 pen-truth 的按钮；卡 cover 占满屏（未按 pen-truth w:h 比例 aspectRatio）。

## 为什么错（根因）

1. 节点对照表的"对齐"标准模糊 — 没明确"对齐 = 节点 + N 项关键属性都正确"
2. pen-truth 双数据源未充分利用 — `.md`（结构 + 属性）+ `.png`（真实视觉），Dev 多读 .md 跳读 .png
3. 额外元素无门控 — Dev 自由发挥加 / 改元素，handoff 无强制"非 pen-truth 元素自审"段
4. 静态值代替动态值 — pen-truth 比例真值，Dev 直接固定 dp / wrap_content，跨设备失真
5. 协调端任务书也漏了 — Stage 模板可能直接漏写关键元素（如 footer 漏 "Step N of M" Text），Dev 严格按字面跑就漏了

## ✅ 正确（节点对照表升级为"节点 + 关键属性 ≥ 3 项"+ 强制视觉细节验证）

#### 升级 1：节点对照表加属性列（每节点 ≥ 3 关键属性）

```markdown
| pen-truth 节点 | 关键属性 | 实施值 | 状态 |
|---|---|---|---|
| stepFooter | h=68 / fill=#FFFFFF08 / padding=12 / Text "Step %d of %d" 16/500 / N bar | view_*.xml line N | ✅ |
| resultsPanel | cr=16 / fill=#FFFFFF08 / **stroke=1pt #3F3F46** | bg_*.xml line N | ✅ |
| {页} title | Inter SemiBold 18 #FFFFFF / margin=md | fragment_*.xml line N | ✅ |
| 卡 cover | aspectRatio=W:H / scaleType=centerCrop | item_*.xml line N | ✅ |
```

不只列节点名，**列关键属性 ≥ 3 项**（cr / fill / stroke / 字号 / padding / aspectRatio 等）。

#### 升级 2：强制 Read pen-truth/{pageId}.png（多模态对比）

实施前 + handoff 写完前各 Read 一次 .png：实施前把握整页视觉（找易漏的边框 / 间距 / 文字）；写 handoff 前自查偏差，列入"与 pen-truth.png 视觉差异自述"段。

#### 升级 3：handoff 强制 "非 pen-truth 元素自审"段

```markdown
## 非 pen-truth 元素自审

- 删除：某 Button（原因：不在 pen-truth，无产品决策依据）
- 保留：close 按钮 X（原因：产品要求应急关闭，显式声明）
- 新增：N/A
```

任何 Dev 自加 / 修改 / 移除的"不在 pen-truth"的元素必须显式列出 + 决策依据。

#### 升级 4：动态尺寸强制（防固定 dp 跨设备失真）

任何 cover / image / 大块占位尺寸**必须 aspectRatio 动态（基于 pen-truth w:h 真值）**：

- ❌ `android:layout_height="320dp"` / iOS `.frame(height: 320)`
- ✅ `app:layout_constraintDimensionRatio="W:H"` / iOS `.aspectRatio(W/H, contentMode: .fit)`

## lint 状态

- ❌ 难静态扫描（属性对照表是文档级要求）
- 预防机制 = 任务书强制 + handoff 模板硬约束

## 预防原则（给协调端）

写**任何视觉对齐**任务时，任务书强制要求：

1. 节点对照表升级：每节点列关键属性 ≥ 3 项，不只列节点名
2. Read pen-truth/{pageId}.png 必读：实施前 + handoff 写完前各一次
3. handoff 含 "非 pen-truth 元素自审"段
4. 动态尺寸强制：cover / image 尺寸必须 aspectRatio 基于 pen-truth w:h 真值
5. 协调端任务书自检：Stage 模板代码块必须含 pen-truth 真值所有关键元素，不漏写
6. **判定线**：handoff 内 "节点对照表无属性列" / "非 pen-truth 元素自审"段缺失 / 固定 dp 高度 任一 = 不合格

## 关联

- 0037 / 0038 / 0039 / 0040 = 协作类 4 联防护（任务粒度 → step 编号 → 客观证据 → 属性细节）
