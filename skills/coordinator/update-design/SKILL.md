---
name: update-design
description: 设计稿(.pen)更新标准流程。当用户说甲方给了新 .pen / 稿件更新 / 新设计 / pencil 改了 时触发,走 Pencil MCP 标准流程:扫 .pen top-level frame 名 → diff page-relation.yaml → 对新增/改动页生成 pen-truth/{pageId}.md + .png(+ 资源包可选)→ audit-log 归档。用户不用记步骤。
user-invocable: true
---

# 设计稿更新流程(Pencil MCP + pen-truth 管道)

**废弃**:原 `sync-design.sh` (Figma 链路)已废弃,本 skill 不再触发它。

**真相源**:`.pen` 文件(默认 `<项目文档区>/design/<your-design>.pen`),通过 Pencil MCP 访问。

> ⚠️ **若 `.sulde-config.yaml: design_source.mcp` = `none`**(项目无设计工具):
> 跳过 Pencil MCP，改走**Agent 管理的本地 design-truth 流程**:
> 1. Agent 复制模板到 `<项目文档区>/design-truth/<pageId>.md`。
> 2. Agent 读取用户已经提供或可访问的外部设计源(图像、文件、链接等)，提取节点树、视觉属性和资源清单。
> 3. 缺少原始设计事实时只请求用户提供该文件/链接/截图；拿到素材后仍由 Agent 保存、命名和成文。
> 4. audit-log 登记(by: coordinator,note: "本地流程,设计源: <外部链接 / 文件路径>")。
>
> 适用场景:小项目 / 个人项目 / 无 Pencil / Figma MCP 接入 / 设计师直接给截图。

---

## 何时触发

用户消息里出现(命中任一立即走本流程):
- "设计稿更新了" / "稿件更新" / "稿更新" / "新稿"
- "甲方给了新稿" / "甲方改了稿" / "改稿了" / "甲方新版"
- ".pen 更新" / "pen 文件" / "pencil 文件" / "新设计"
- "更新 UI 稿" / "同步设计" / "拉最新 UI"
- "/update-design" / "/pen-truth"

---

## 标准 5 步流程

### Step 1:确认 .pen 文件位置

默认 `<项目文档区>/design/<your-design>.pen`。若用户说放别处,问清路径。

若甲方给了全新 .pen 替换现有文件 → 备份旧文件(可选:`cp *.pen *.pen.bak-{date}`),用新文件替换。

### Step 2:扫 .pen top-level frames,diff yaml

```
mcp__pencil__get_editor_state({ include_schema: false })
  → 列出所有 top-level frame 的 id + name
```

对比 `<项目文档区>/design/page-relation.yaml` 的 pageId 集合:

- **有新 frame、yaml 无登记** → 新增页
- **yaml 有、.pen 无对应 frame** → 删除页
- **yaml 和 .pen 一致** → 无变化(流程结束)

### Step 3:按 diff 改 page-relation.yaml

- **无变化** → 告诉用户"yaml 和 .pen 一致,无需改",流程结束
- **有新增页** → 协调端直接编辑 yaml,补条目(parent / type / entry / children / android / ios / source / status):
  - 关系不明必须问用户("06 是新 Tab 吗?还是某页的子页?"),不要硬填
  - type / state-of 必须基于 .pen export_nodes 截图或 PRD 明确证据;靠 heuristic 时标 `source: heuristic`
  - 补 pageId → .pen nodeId 映射(写入 CLAUDE.md § "page-id → .pen nodeId 映射"表)
- **有删除页** → 在 yaml 的 `audit-log` 追加 `action: remove-page`,不真删条目只加 `status: archived`(保留审计)
- **有改名页** → 改 key,grep 所有引用(parent / state-of / next)同步

### Step 4:生成/更新 pen-truth 真相文档

对每个**新增页**或**改动页**,产出 2 个文件:

```
mcp__pencil__batch_get({
  filePath: <.pen 路径>,
  nodeIds: [<对应的 .pen 节点 id>],
  readDepth: 20
})
  → 生成 <项目文档区>/design/pen-truth/{pageId}.md
     含:节点树 / fill(渐变完整数据) / stroke / effect / icon_font lucide 名 /
        文字 font / 视觉资源清单 / 跨端实现硬约束

mcp__pencil__export_nodes({
  filePath: <.pen 路径>,
  nodeIds: [<对应的 .pen 节点 id>],
  outputDir: "<项目文档区>/design/pen-truth",
  format: "png",
  scale: 2
})
  → 生成 <项目文档区>/design/pen-truth/{nodeId}.png (2x 高清)
  → 注意: export_nodes 用 nodeId 作为文件名(如 `<node-id>.png`)，由 Agent 原子重命名为 {pageId}.png 并回读校验
```

**真相文档模板参考**:`<项目文档区>/design/pen-truth/<page-a>.md`(通用样板)

**文档必含段落**(依样板):
- §0 结构总览(节点树,短)
- §1-N 逐区域详细(每区带子节点表:id / type / 关键属性)
- §8.1 渐变清单(type / gradientType / rotation / colors / 两端建议资源名)
- §8.2 lucide 图标清单(节点 id / iconFontName / size / fill / 位置 / Android drawable 名 / iOS SF Symbol 对应)
- §8.3 纯色 fill 清单(hex 色值 + token 候选)
- §9 跨端实现硬约束(数据源优先级 / 视觉资源禁用清单 / lint 规划 / 已确认越位修正项)
- §10 更新触发条件

### Step 4.5:生成代码资源包(可选,建议做)

若该页有视觉资源(gradient / lucide icon),协调端可顺手产出 `pen-truth/{pageId}-resources/` 目录含:

- `android/drawable/` — gradient XML + lucide vector XML
- `android/values/colors_{pageId}_patch.xml` — hex 色值 token 增量
- `android/kotlin/LucideIcon.kt` — enum 追加本页用到的 lucide
- `ios/AppGradients.swift` — 命名 LinearGradient 追加
- `ios/LucideIcon.swift` — enum + SF Symbol 映射追加
- `ios/AppColors+{pageId}.swift.patch` — 增量 token 追加
- `README.md` — Dev **完整替换 checklist**(逐项打勾表格,**不是"示例几处"**,避免 Dev 漏项)

**参考样板**:`pen-truth/<page-a>-resources/`(Android + iOS 完整 checklist 样板)

### Step 5:audit-log 归档 + 告知

在 page-relation.yaml 末尾的 `audit-log` 段追加:
```yaml
- date: YYYY-MM-DD
  action: pen-truth-update
  page: <pageId(s)>
  by: coordinator
  note: |
    通过 Pencil MCP batch_get + export_nodes 产出 pen-truth/{pageId}.md + .png
    (+ resources/ 若该页有视觉资源)
```

告诉用户:"Pen-truth 已就绪,两端 Dev 下次 /ui-impl 自动读新版"。

---

## page-id → .pen nodeId 映射维护

`.pen` 节点 id 是短随机字符串(如 `<node-id>`),**不等于** page-relation.yaml 的 pageId(`<page-a>`/`<page-a-state>`).

- **手工方式**:每次 Step 2 做 `get_editor_state` 时,按 name 匹配定位 nodeId
- **已确认映射**(增量维护,写入协调端 CLAUDE.md):
  - `<page-a>` → `<node-id>`

**建议**:未来在 page-relation.yaml 的每个页面 entry 加一个 `pen-id: <nodeId>` 字段,便于 skill 化自动映射。

---

## 禁忌

- ❌ 跑已废弃的 `sync-design.sh` / `fetch-design-image.sh` / `extract-page.sh`(Figma 链路)
- ❌ 生成 `ui-spec.json` / `figma-raw.json` 或让两端读(数据残缺,会造成视觉退化)
- ❌ 改 pen-truth/{pageId}.md 不同步改 page-relation.yaml 的 impl-note
- ❌ 碰到关系不明硬填 yaml(必须问用户)
- ❌ 触发词命中但不引导(用户问的是 UI 问题,但语境含"稿更新了"就必须先走本流程)

---

## 与 /ui-impl skill 的分工

- **协调端 `/update-design`**(本 skill):产出 pen-truth 真相文档 + 资源包,不碰两端源码
- **两端 `/ui-impl`**:读 pen-truth 真相文档 → 改两端源码
- **边界**:协调端永远不直接改 `<android-frontend>/` / `<ios-frontend>/` 的源码(`.ai-workspace/tasks/` 任务文件除外)

---

## 首版样板

- 某页面 pen-truth 真相:`<项目文档区>/design/pen-truth/<page-a>.md`
- 某页面视觉参考:`<项目文档区>/design/pen-truth/<page-a>.png`(2x)
- 某页面资源包:`<项目文档区>/design/pen-truth/<page-a>-resources/`
- lucide 图标总清单:`<docs-hub>/design/pen-truth/lucide-icons-used.md`(42 unique × 385 调用)

后续页面逐个按本流程跑,按两端 Dev 开发节奏按需供给,不追求一次性全量。
