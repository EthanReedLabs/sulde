---
doc_id: "work-model/data-sources"
container: work-model
platform: none
summary: "协调端 / iOS / Android 三端通用。"
---

# 数据来源优先级铁律(三端共享)

> 协调端 / iOS / Android 三端通用。作为唯一真值。
> **重大方法论**:协调端写 task md 必做 **UI/PRD/接口 3 维同步**(详见 §3 维同步铁律)。

---

## 优先级表

| 数据源 | 优先级 | 维度 |
|---|---|---|
| 用户实时输入(含截图)| **1(最高)** | 临时 |
| **设计真值** pen-truth/{pageId}.md + .png | **2(UI 真值)** | **UI/UX 维** |
| **真实素材切图**(设计稿 assets 包)| **2.5(实施视觉物质基础)** | UI/UX 维 |
| **PRD**(产品需求文档) | **3(产品规划)** | **PRD 维** |
| **接口文档**(API SPEC + 创作类 Agent Detail API) | **3.5(数据契约)** | **接口维** |
| UI 行为契约 | 4 | 行为补充 |
| 实施文档 | 5 | 实施 |
| 历史代码状态 | 6 | 现状 |

冲突时按优先级:
- **pen-truth 与 PRD 冲突时按 pen-truth**(UI 真值优先)
- **PRD 与接口冲突时**(如 PRD 描述字段 vs 接口字段不匹配)→ **协调端反馈甲方解分歧**,首版按接口真返回(数据驱动)
- **3 维冲突无法自决时** → 协调端反馈甲方拍板,**Dev 不自决**

---

## §3 维同步铁律(协调端核心工作方法论)

任何功能 / task md / bug 修 / 反模式 audit,协调端**必须**做 UI/PRD/接口 **3 维同步交叉验证**:

### 3 维定义

| 维 | 数据源 | 协调端读法 |
|---|---|---|
| **UI/UX** | pen-truth/{pageId}.md + .png(UI 真值);设计稿(via Pencil MCP);assets 真素材 | Read pen-truth → 多模态看 .png → grep 节点属性 |
| **PRD** | PRD §x.y 文字规格 + INDEX 定位 | INDEX 找 line N → Read offset/limit |
| **接口** | API SPEC(常规模块)+ Agent Detail API(创作类 SSE)+ 接口环境域名 | INDEX 找 endpoint 行 → Read 字段定义 + 基础模型 |

### 3 维交叉验证(协调端写 task md 必做 5 步)

**Step 1**:**UI/UX 维 audit** — Read pen-truth/{pageId}.md + .png,提取 view 必含字段清单
**Step 2**:**PRD 维 audit** — 找对应 §x.y 文字规格,提取 PRD 描述字段清单
**Step 3**:**接口维 audit** — 找对应 endpoint / 任务名,提取接口字段清单 + 基础数据模型
**Step 4**:**生成 3 维对照表**(每功能 / 阶段一表):

```markdown
| 字段 | UI(pen-truth)| PRD line | 接口字段(SSE/REST)| 双端实现位置 | 一致? |
|---|---|---|---|---|---|
| 某字段 A | {pageId} 节点 | line N | options[].name | view N | ✅ |
| 某字段 B | {pageId} block | line M | options[].xxx | view M | ✅ |
| 某字段 C | {pageId} rationale | line K | result.xxx(?) | ❌ | ⚠️ 接口字段不明 |
```

**Step 5**:**冲突项处理**:
- UI vs PRD 冲突 → 按 UI(pen-truth)
- PRD 描述字段在接口侧不存在 → 协调端**异步反馈甲方解分歧**(不阻塞)
- 接口字段在 UI/PRD 侧没设计 → 协调端补 pen-truth 或反馈甲方
- 3 维冲突写入 task md handoff 模板留 Dev 实施时 verify + 反馈

### 反例(典型 audit 实例)

某多 stage 创作流方案:

- 只对照 PRD 某章(单维度)→ 发现 PRD N 阶段
- 后查 pen-truth M 阶段(少一个中间页)
- 再查接口 unified 字段 = 简版(非 PRD 描述的多板块字段)
- **3 维都不一致** — 用户报"为什么单看 PRD 不够" → 升级方案

**修法**:协调端写 task md 前必做 3 维 audit,task md 必含 3 维对照表段。

### 3 维 audit 工时

| 范围 | 工时 |
|---|---|
| 单功能 / 单页面 | ~20-30min |
| 多 stage 流程(wizard 类)| ~1-2h |
| 跨模块大功能(登录 / 订阅 等)| ~1-1.5h |

**协调端 task md 必带"3 维对照表"段** — 缺 = 凭印象写 + 单维度数据源,违规。

---

## 真实素材切图详情(甲方提供完整包时)

| 素材类别 | 协调端路径(占位) | Android 目标 | iOS 目标 |
|---|---|---|---|
| 分享平台 logo | 设计稿 assets/share/*.png | core-ui drawable/ic_share_*.png | CoreUI Resources/Share*.imageset/ |
| 创作流配图 | 设计稿 assets/agent/*.{png,jpg} | feature-create res/drawable/ | FeatureCreate Resources/ |
| 平台 icon(PNG + SVG)| assets/icon*/*.png + 矢量 svg | drawable/ic_*.png 或 vector | Resources/*.imageset/ |
| 付费背景 | assets/pay/*.png | feature-profile drawable/ | FeatureProfile Resources/ |
| 品牌 logo(渐变)| 素材/logo/*.{svg,png} | core-ui drawable/logo_*.png | CoreUI Resources/Logo*.imageset/ |
| 第三方登录 icon | 素材/登录 icon/*.{svg,png}(@3x)| feature-auth drawable/ic_provider_*.png | FeatureAuth Resources/ |
| cover 测试占位 | 设计稿 images/remote-*.jpg | 测试用,正式从 staging-api 取 cdn URL | 同 |
| asset-manifest 索引 | 设计稿 asset-manifest.json | — | — |

**Why 列入数据源 Tier 2.5**:

之前 Dev 看 pen-truth.md 的视觉描述(如 "某品牌渐变色" + "Lucide icon")→ 用 Vector / placeholder 自造 → **像而不真**。现在设计稿包给了真切图(`assets/*.png` + SVG),Dev 直接 cp 即可 100% 还原。

**禁忌**:

- ❌ Dev 自造图片资源(若设计稿 assets 已有真切图)
- ❌ 用 Vector / placeholder / drawable shape 模拟应该是 PNG 切图的素材
- ❌ 引用过时 mock URL(改用占位图 / staging-api 真 cdn)
- ❌ 协调端 pen-truth 文档不列资源引用清单(Dev 看不到该 cp 哪个文件 → 又退回自造)

---

## 典型冲突场景

### 1. wizard step 数(PRD vs pen-truth)

- PRD 写 N stage(含某中间阶段)
- **pen-truth 真值**:footer 写 "Step N of M"(无该中间阶段,合并到末页)
- **决策**:按 pen-truth M stage
- 历史踩坑:协调端跟 PRD 写 task md → Dev 实施 N stage 偏离;某次修复按 pen-truth 修回 M stage,又有人自发改回 N stage(自发修复扩散违规)

### 2. wizard step # 与 pageId 命名不对应

- 直觉以为 "{父页} 是 host,{子页} 是 step 1"
- **pen-truth 元数据 `> 属于:某 Wizard Step X/N`**:父页 = Step 1/N,子页 = Step 2/N
- 中间某子页跳号(无 sub-page),后续 step # 顺延

### 3. 架构层节点位置(wizard stepFooter)

- PRD 没明确说 stepFooter 在哪
- **pen-truth 结构节点树**:`resultsPanel > [contentArea, stepFooter]`(stepFooter 在 panel 内,不是 host 全局)
- 历史踩坑:Dev 加到 host 全局 → 用户报"分离 / 间距不一"

---

## Why pen-truth 优先

- PRD 是产品规划描述(战略/文案/范围),**视觉/结构细节常与 pen-truth 不一致**(产品规划演进时设计稿先改,PRD 后跟)
- pen-truth 是设计稿真值导出,**含完整结构节点树 + 节点属性 + 视觉资源清单 + 图标名 + fill 渐变完整数据**
- pen-truth.md(结构 + 属性)+ .png(真实视觉)双数据源,**.md + .png 都要看**(.png 多模态视觉对比 catch 隐藏细节)

---

## How to apply

### 协调端(写 task md 时)

1. **每写一个 task md 前**(跨依赖任务尤其重要):
   ```bash
   grep -A20 "结构节点树" pen-truth/{pageId}.md     # 看完整结构 + 嵌套关系
   grep "属于" pen-truth/{pageId}.md                # 验证 wizard step #
   ```
   + **Read pen-truth/{pageId}.png**(多模态视觉)

2. **task md 内显式列数据源对照表**(若 PRD 与 pen-truth 冲突):
   ```markdown
   | 维度 | pen-truth 真值 | PRD 描述 | 决策 |
   |---|---|---|---|
   | wizard stage 数 | M(Step N of M)| N(含某中间阶段)| **按 pen-truth M stage** |
   ```

3. **数据源优先级判定线**:**pen-truth 与 PRD 冲突时,task md 写 PRD 描述 = 协调端 task md 不合格,重写**。

### iOS / Android Dev(自发修 bug 时)

1. 涉及视觉/文案/stage 数 → 改前必 Read 对应 `pen-truth/{pageId}.md` + `.png`
2. **不要凭印象 / 凭 PRD 字面 / 凭最近用户口头反馈作决策**
3. PRD 写 "N 个 stage" 但 pen-truth footer 写 "Step N of M" → **按 footer M**

---

## 关联

- 反模式集合(数据源跳读是同源根因)
- 反模式集合(Dev 自发改时也要按 pen-truth)
- 子端 `自发修复边界` 段
