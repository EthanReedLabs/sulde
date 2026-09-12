---
name: ui-impl
description: UI 还原 / UI 对齐 / UI 校验 / 对照设计稿修 UI / 截图对比修复 / 检查页面是否与设计稿一致 / fix UI / verify UI alignment with design — 从 <docs-hub>/design-truth/{pageId}.md 真相文档 + 设计稿 PNG 精确审查页面 UI 还原度,按布局/颜色/字号/间距 Token 修复偏差。当用户提到"UI 对齐"、"对照设计稿"、"还原 UI"、"页面跟设计稿不一致"、"UI 偏差"、"UI 校验"、"按设计稿修"、提供 App 运行截图时自动触发。stack 中性 — 平台特定 API / 命令 / 框架决策从 references/{stack}.md 读。
user-invocable: true
---

# UI 精确还原(design-truth + stack-references)

从 `<docs-hub>/design-truth/{pageId}.md` 读取**协调端从设计源 MCP 直接提取的页面真相文档**,审查当前代码偏差,翻译为目标 stack 实施代码,逐组件修复。

**stack 决定后必先 Read 对应 references 文件**(命令 / 框架决策 / 系统级修复位置全在那里):

| 你的 frontend stack(`.sulde-config.yaml: frontends[].stack`)| 必 Read |
|---|---|
| `mobile-android` | `references/android.md` |
| `mobile-ios` | `references/ios.md` |
| `mobile-flutter` | `references/flutter.md` |
| `mobile-harmony` | `references/harmony.md` |

**数据源已切换(强制)**:
- ✅ 新:`<docs-hub>/design-truth/{pageId}.md`(节点树文档)+ `.png`(视觉参考)+ `{pageId}-resources/`(代码资源包,如有则集成)
- ❌ 废弃:`ui-spec.json` / `figma-raw.json`(Figma 导出管道丢失 gradient + icon_font,数据不完整)
- ❌ 废弃:Figma 链路同步脚本

**目标页 design-truth 不存在** → 写 handoff 到 `.ai-workspace/handoff/{date}-design-truth-needed-{pageId}.md` 请求协调端用设计源 MCP 生成,等真相文档就绪再启动 /ui-impl。

---

## §1 系统级 vs 业务级问题分类(关键路由)

**修复 UI 偏差前必须先判断问题分级。系统级问题不在当前页修,去底层基础设施修。** 具体修复位置因 stack 不同(`AdaptiveBaseActivity` / `.adaptivePage()` / Theme override / etc.)— 详 references/{stack}.md §1。

### 系统级问题(不在当前页修)

发现以下问题时,不要在当前页打补丁。若底层路径已在当前任务边界内，由 Agent 直接转到底层修；若属于独立范围，由 Agent 生成并执行受管后续任务。只有产品语义或范围取舍不明确时才请用户决策，不让用户承担修复动作:

| 问题症状 | 修复位置(stack 通用语义,具体 API 见 references) |
|---|---|
| 状态栏 / 导航栏被遮挡 | scaffold 容器(safe area / status bar 修饰) |
| 内容延伸到系统底部(Home Indicator / nav bar) | 同上 |
| 键盘弹出遮挡输入框 | scaffold 容器(keyboard adjust modifier) |
| 刘海 / 挖孔屏遮挡 | App 入口 SafeArea 默认 |
| 系统弹窗显示亮色(暗色泄漏) | App 入口 force dark mode |
| 屏幕能横屏 | App config 锁定竖屏 |
| 底栏被系统覆盖 | 底栏容器 nav-inset / safe-area-bottom 处理 |
| 字号过大被系统放大 | Typography Token 用 fixed-size 替代 system-scaled |
| 自定义字体没生效 | App 资源注册 |

### 业务级问题(在当前页修)

以下问题在当前页面用 Token 替换硬编码:

- 颜色不对 → 用 AppColors Token 替换硬编码 hex
- 字号不对 → 用 AppTypography Token 替换硬编码字号
- 间距不对 → 用 AppSpacing Token
- 圆角不对 → 修对应 shape / cornerRadius
- 组件层级错 → 改容器嵌套
- 文案不对 → 改 L10n 资源
- 选中态样式 → 改对应 view modifier 或 drawable

具体 Token API 名称 + 文件路径见 references/{stack}.md §2。

---

## §2 思考模式(强制)

**执行 `/ui-impl` 时必须启用 ultrathink 深度思考模式。** UI 还原是高精度任务。

```
ultrathink。

角色:高级移动端工程师 + 严苛设计还原审查者

执行流程(5 阶段思考,每阶段不少于 3 步):

阶段 1【观察】
  - 列出截图与设计稿的所有视觉差异(不少于 8 项)
  - 标注每项差异的优先级(P0 严重 / P1 中 / P2 微调)

阶段 1.5【节点循环对比 — 强制】
  - 按 design-truth/{pageId}.md 节点树**逐节点**对照实施(不只宏观偏差清单)
  - for each 节点 in design-truth.md:
    1. Read 节点关键属性 ≥ 3 项(fill / stroke / cornerRadius / 字号字重 / padding / aspectRatio / icon 名 等)
    2. grep / Read 实施代码对应 view / drawable / token
    3. 输出对照行: `[节点名 / design-truth 真值 / 实施值 / 状态 ✅/⚠️/❌]`
    4. ⚠️/❌ → 阶段 3 修;✅ → 跳下一节点
    5. **非 design-truth 元素自审**(自加 / 修改 / 删除 — 必显式列原因 + 决策依据)
  - 铁律:
    - ❌ 禁止凭印象判"已对齐" — 每节点必有客观证据(file:line / drawable 内容 / grep 实证)
    - ❌ 节点属性对照表只列"节点存在"不列具体属性 = 不合格
    - ❌ Read design-truth/.png 必跑(实施前 + handoff 前各 1 次)
    - ✅ 完整对照表必塞 handoff `§ 2 节点对照表`(协调端 review 必看)
  - 对照表格式模板(handoff §2):
    ```markdown
    | design-truth 节点 | 关键属性(真值) | 实施 | 状态 |
    |---|---|---|---|
    | §2.1 头像 `<node-id>` | ellipse 56×56 / gradient 180° #3CFF52→#38D9A8 | <stack-specific 实施位置> | ✅ |
    | ... | _____ | _____ | _____ |
    ```

阶段 2【根因】
  - 对每项 P0/P1 差异分析根因(不是表面修改)
  - 区分:是布局结构问题 / 数值偏差 / 适配问题 / 业务逻辑冲突

阶段 3【方案】
  - 每项给 2-3 种修复方案
  - 标注:实现成本、对其他模块的影响、风险
  - 选最优方案

阶段 4【自我批判】
  - 检查所选方案是否会破坏现有业务逻辑(events / state observation / data bindings)
  - 检查是否引入了硬编码(颜色 / 字号 / 间距)
  - 检查是否符合 UI 适配规范(用 scaffold 工具)
  - 如果有问题,回到阶段 3 重选

阶段 5【执行 + 验证】
  - 应用修复
  - 列出修改的文件清单
  - 提示用户截图验证
```

禁止跳过任何阶段直接给代码。

---

## §3 启动方式

### §3.1 截图对比修复(主要方式)

```
/ui-impl ~/Downloads/screenshot.png
```

用户提供一张 App 运行截图路径,Dev 自动完成全部工作:

1. 用 Read 工具**读取用户提供的运行截图**
2. **自动判断**这是哪个页面(通过底栏选中态、页面结构、Tab 标题判断)
3. Read 对应的设计稿截图:`<docs-hub>/design-truth/{pageId}.png`
4. **两张图并排对比**,逐区域找出所有视觉差异
5. Read `<docs-hub>/design-truth/{pageId}.md` 的**精确数值**(hex 色值 / gradient stops / 字号 / 间距 / 圆角 / icon 名)
6. 输出偏差清单(视觉差异 + 精确数值应该是多少)
7. **结合 PRD 检查冲突**(参 §6)
8. 逐项修复代码(只改 UI 样式,不碰业务逻辑)
9. 修复完成后告知用户重新截图验证

### §3.2 用户说"截图"自动抓取(团队约定)

抓图命令因 stack 不同,见 references/{stack}.md §3。命名规则统一:

```
{页面编号}_before.png    # 修改前的基线(保留对比)
{页面编号}_after.png     # 当前最新效果(每次新抓覆盖)
```

仅用 before/after,不要 v2/v3/v4 累积。

#### 清理策略(强制)

| 时机 | 动作 |
|---|---|
| 抓新图前 | 删除该页面的历史版本截图 |
| 修复完成 + 用户确认对齐 | 删除该页面的 `_after.png` |
| 每周自动 | 删除 7 天前所有截图 |
| 提交代码前 | 检查 `du -sh .ai-workspace/screenshots/` 应 < 5MB |

### §3.3 按页面编号实现(无截图时)

```
/ui-impl 01
```

直接从 `<docs-hub>/design-truth/{pageId}.md` + `.png` 读规格对照代码修复。

### §3.4 只审查不修改

```
/ui-impl 01 audit
```

---

## §4 阶段 0:页面关系识别(强制 — 任何启动方式都必走)

**核心目的**:避免"A 页面改成 B 页面"。多设计稿场景下 agent 分不清「页面 / 状态 / 流程」关系,在错的文件上做对的改动。读 `<docs-hub>/design/page-relation.yaml` 建立显式关系。

### Step 0.1:读图谱

```bash
cat <docs-hub>/design/page-relation.yaml
```

位置在协调端管辖,Dev 只读。

### Step 0.2:定位本次任务涉及的所有页面

从用户描述提取页面编号(例:"对齐某列表页" → 查图谱找 `<page-a>` + `<page-a-state>`)。**必须把以下全部纳入视野**:

- 该页本身
- 该页的 `states`(同页不同状态分支)
- 该页的 `children`(弹出的 modal / 子页)
- 该页的 `next`(流程下一步,若任务涉及)
- 该页的 `parent`(上下文参考,一般只读不改)

### Step 0.3:按 type 字段分流

| type | 含义 | 实现动作 |
|---|---|---|
| `page` | 独立页 | 改对应 `<stack>.file` |
| `modal` | 底部弹窗 / Sheet / 浮层 | 改对应 file;**它是 modal 不是新页** |
| `state` | 同页不同 state 分支 | **绝对不要新建文件**;改 `state-of` 指向的宿主文件,加条件渲染 |
| `dialog` | 系统对话框 | 改 dialog 布局 |

**关键**:看到 `type: state` 意味着这是状态分支(例如 `<page-a-state>` 是 `<page-a>` 的 selected 态),**禁止新建文件** — 这是「A 改成 B」踩坑根因。

### Step 0.4:图谱缺项(status=todo 或 file=??)怎么办

1. 按命名规律 heuristic 初判(字母后缀=state / 数字递增=流程 / 多一位=父子)
2. 这是产品映射歧义时，展示可核验依据并让用户做自然语言或宿主原生选择；不得要求固定回复
3. 选择确定后，由当前 Agent 在任务边界允许时更新 yaml；否则自动生成并路由给协调 Agent 的受管后续任务，不让用户手工改文件
4. Agent 回读更新后的 yaml 并继续本任务；路由失败时保留原状态并报告精确 blocker

### Step 0.5:定白名单(边界)

读完图后,**允许改的文件列表**:

- 目标页的 `<stack>.file`
- 目标页 `states` 的宿主文件(若目标页本身是 state,改宿主)
- 目标页 `next` 的下一步文件(若任务涉及流程)
- core-ui 模块共享 Token(仅**追加**,不改既有)

白名单外的文件一律不碰,即使看起来"顺手"也停下报告。

### Step 0.6:阶段 0 禁忌

- ❌ 用户贴 2+ 张设计稿不跑 Step 0.1-0.5 就动手
- ❌ `type: state` 的页面新建独立文件
- ❌ 跨越白名单边界改文件(哪怕"顺手")
- ❌ `status: todo` 的页面不问用户直接蒙着改
- ❌ 直接改 `page-relation.yaml`(协调端管辖,走 handoff)

阶段 0 完成后,再走 §2「思考模式」5 阶段流程。

---

## §5 数据源优先级

冲突时按优先级从高到低:

1. **PRD(最高)**:业务需求真相
2. **实施文档**:首版范围和技术方案
3. **UI 适配规范**:适配策略(必读)
4. **设计真相文档**:`<docs-hub>/design-truth/{pageId}.md` + `.png` — 协调端从 .pen / .fig via MCP 直接提取,唯一视觉真相源
5. **代码资源包(如有)**:`<docs-hub>/design-truth/{pageId}-resources/` — 协调端产出的 token / 资源代码,直接 cp 集成,Dev 不手工造
6. **用户截图**:运行截图,Read 工具读取
7. **Design Tokens**:core-ui 模块下的 Colors / Typography / Spacing

**⛔ 禁用**(已废弃):
- `ui-spec.json` / `figma-raw.json`(数据不完整)
- 旧的 Figma 链路同步脚本

---

## §6 冲突处理规则(关键)

**设计稿 ≠ 需求。设计稿只提供视觉样式,不决定业务内容。**

### 原则:设计稿取样式,PRD 取内容

| 维度 | 来源 | 说明 |
|---|---|---|
| 颜色 / 字号 / 间距 / 圆角 | 设计稿 | 视觉样式以设计稿为准 |
| 组件数量(Tab / 按钮 / 列表项)| **PRD** | 设计稿可能有多余的 |
| 功能是否存在 | **PRD + 实施文档** | 设计稿有但首版不做的就不做 |
| 按钮文案 / 列表内容 | **PRD** | 设计稿可能是占位文案 |
| 交互行为 | **PRD + 现有代码** | 设计稿是静态的 |
| 加载 / 空 / 错误状态 | **PRD + 现有代码** | 设计稿通常不画这些 |

### 修改 UI 时绝对不能做的事

1. ❌ 删除已有的业务逻辑(state machine / reducer / store)
2. ❌ 删除已有的事件监听(点击 / 滑动 / 滚动 / 生命周期)
3. ❌ 删除已有的状态管理(loading / error / empty 切换)
4. ❌ 删除已有的数据绑定(渲染中的字段映射)
5. ❌ 删除已有的导航跳转
6. ❌ 删除已有的网络请求 / 轮询逻辑
7. ❌ 把已实现的功能因为设计稿没有就删掉

### 修改 UI 时只能做的事

1. ✅ 修改布局结构(容器层级 / 类型)
2. ✅ 修改视觉属性(颜色 / 字号 / 间距 / 圆角 / 背景)
3. ✅ 修改组件尺寸(宽 / 高 / padding / margin)
4. ✅ 添加 / 修改 shape / drawable
5. ✅ 调整组件位置(浮层定位)
6. ✅ 修改文案显示样式(不改文案内容和数据源)
7. ✅ 添加设计稿要求的视觉元素(指示条、Badge 等)

### 修改前必做检查

每次修改一个文件前:

1. 读取该文件完整代码
2. 识别所有业务逻辑(events / observations / renders / dispatches / navigations)
3. 标记为"保护区",修改时不触碰这些代码
4. 只修改布局 / 样式部分

---

## §7 设计稿自动定位

用户的口语化描述自动映射到页面编号 — **项目特定 mapping 在 `<docs-hub>/design/page-name-mapping.yaml`**(若存在)或由 design-truth 文件名 grep 推断。

### 目标页 design-truth 缺失

写 handoff 请协调端用设计源 MCP 生成:

```
.ai-workspace/handoff/{YYYY-MM-DD}-design-truth-needed-{pageId}.md
```

等协调端在主会话里产出后再启动。**禁止**使用废弃的 Figma 链路脚本。

---

## §8 页面 → 代码 → 开发者映射

**修改 UI 时必须切换到对应分支并使用对应的 git 身份提交。** 项目特定 mapping 在 `.sulde-config.yaml: team[]` 和 `<docs-hub>/page-owner-map.yaml`(若存在,协调端管辖)。

### 执行规则

1. 开始修改前,**先切换到对应分支**:`git checkout dev/{用户名}/{模块名}`
2. 分支不存在,从 develop 创建:`git checkout -b dev/{用户名}/{模块名} develop`
3. 修改与验证完成后，由 Agent 按任务合同使用对应 `git as-<alias>` 提交；合同不含提交时仅报告
   未提交状态，不把 Git 命令交给用户
4. 一次 `/ui-impl` 涉及多个开发者模块 → **分开提交**(各自分支 + 各自 git alias)

---

## §9 执行流程(5 步)

### Step 0:读取适配规范(每次必读)

```bash
cat <docs-hub>/00_shared-rules/verify-build.md
cat <docs-hub>/UI适配规范.md  # 若项目有
```

stack-specific 建议见 references/{stack}.md §0。

### Step 0.5:截图当前状态(修复前基线)

具体命令见 references/{stack}.md §3 截图段。

### Step 1:读取设计规格(新管道)

**唯一路径**:读协调端产出的 design-truth 真相文档 + 视觉参考。

```bash
# 目标页 pageId 的真相文档
Read <docs-hub>/design-truth/{pageId}.md
# 目标页 2x 高清视觉参考
Read <docs-hub>/design-truth/{pageId}.png

# 可选:若协调端也产出了代码资源包
ls <docs-hub>/design-truth/{pageId}-resources/  # 若存在,先 cp 集成,再改实施引用
```

目标页 design-truth 不存在 → handoff 暂停 /ui-impl(参 §3 起手)。

**绝对禁止**:Read 废弃的 `ui-spec.json` / `figma-raw.json` 或跑废弃的 Figma 链路脚本。

### Step 2:审查当前代码偏差

读取当前代码文件,逐项比对:

**结构审查**:
- 组件层级是否与设计稿一致
- 容器类型是否正确(平面布局 vs 绝对定位)
- 子项数量是否匹配(Tab 数量、按钮数量)

**数值审查**:
- 颜色是否使用 AppColors Token 且值匹配
- 字号是否使用 AppTypography Token 且值匹配
- 间距 / 圆角是否精确
- 尺寸(宽高)是否匹配

**定位审查**:
- 浮层元素的位置(top/leading/trailing/bottom)是否精确
- 对齐方式是否正确

输出偏差报告到 `.ai-workspace/ui-audit/{页面编号}.md`(格式见 §10)。

### Step 3:修复实现

按 references/{stack}.md §4「翻译规则」逐项实施。

### Step 4:自查验证

修复完成后,逐项检查(全部通过才能结束):

- [ ] 所有颜色来自 AppColors Token(无硬编码 hex)
- [ ] 所有字号来自 AppTypography Token(无硬编码字号)
- [ ] 浮层容器用绝对定位容器(详 references/{stack}.md)
- [ ] 浮层元素有精确的 alignment + padding / margin
- [ ] 圆角值精确匹配
- [ ] 子项间距用规范的 spacing 实现
- [ ] FILL 尺寸用 stack-specific 撑满方式
- [ ] 文案与设计稿完全一致(大小写、复数形式)
- [ ] Tab / 按钮数量与设计稿一致
- [ ] 底栏是自定义实现,不是系统标准组件
- [ ] 无 AI / Claude / generated 字样

### Step 5:截图验证(修复后)

修复代码后,**必须重新编译安装并截图验证**(具体命令见 references/{stack}.md §3 + §5)。

截图后对照设计稿规格逐项确认:

1. 读取截图文件,识别当前页面视觉结构
2. 与 `design-truth/{pageId}.md` 节点树逐项比对
3. 仍有偏差 → **继续修复并重复 Step 3→5**,直到无明显偏差
4. 最终截图和偏差报告归档到 `.ai-workspace/ui-audit/`

**关键:Step 5 不通过就不能结束任务。** 写完代码不算完成,截图验证通过才算完成。

---

## §10 偏差报告格式

写入 `.ai-workspace/ui-audit/{页面编号}.md`:

```markdown
# UI 审查报告:{页面名}

审查时间:{时间}
模式:{audit / fix}
Stack:{android / ios / flutter / harmony}

## 偏差统计
- 检查项:N 项
- 通过:N 项
- 偏差:N 项(已修复 / 待修复)

## 偏差明细
| # | 组件 | 属性 | 设计稿 | 代码 | 状态 |
|---|---|---|---|---|---|
| 1 | Tab 栏 | 数量 | 2 个 | 3 个 | 已修复 |

## 修改的文件
- {stack-specific file paths}
```

---

## §11 通用 UI 规范(stack 通用约束)

以下规范在每个页面实现时都遵守,不需要设计稿单独标注:

| 维度 | 通用约束 | stack 特定实施详见 references/{stack}.md §6 |
|---|---|---|
| 安全区 | scaffold 容器处理 status / nav / keyboard inset | §6.1 |
| 屏幕适配 | 设计稿 402×874 → 容器跟屏幕走、组件跟设计稿走 | §6.2 |
| 触控热区 | 最小 44~48 单位 | §6.3 |
| 文字适配 | 多语言膨胀(德语 +30% / 日语 -20%)+ 结构性 vs 内容性文字 | §6.4 |
| 键盘处理 | adjustResize / scroll-on-focus | §6.5 |
| 状态栏样式 | 暗色主题全局 | §6.6 |
| 手势冲突 | ViewPager / List / NestedScroll | §6.7 |
| 列表性能 | RecyclerView / LazyVStack / DiffUtil 等 | §6.8 |
| 动效 | 页面切换 / 弹窗 / 点赞 / Tab / 列表 / 加载 | §6.9 |
| 图片加载态 | 暗色占位 + shimmer + fade | §6.10 |
| 无障碍 | contentDescription / accessibilityLabel | §6.11 |
| 分割线 | 暗色主题间距分隔为主 | §6.12 |
| Toast / Snackbar | 底栏上方,自定义 Token | §6.13 |
| 弹窗 dim 背景 | 50% 黑 | §6.14 |
| Badge 角标 | 16dp / 8sp 文字 | §6.15 |
| 空 / 加载 / 错误态结构 | 4 态统一容器 | §6.16 |
| 多窗口 / 分屏 | 禁分屏(保证 UI 不变形) | §6.17 |
| 暗色主题防泄漏 | App 入口 force dark | §6.18 |

---

## §12 图标资源映射

设计稿使用 Lucide 图标库。各 stack 资源命名 + 集成方式见 references/{stack}.md §7。

通用 Lucide → 项目内 token 命名约定:

| Lucide 名 | 项目内 token 名 | 尺寸 | 常见颜色 |
|---|---|---|---|
| volume-x | `iconVolumeOff` | 16 | textPrimaryTransparent |
| heart | `iconHeart` | 18 | textPrimary |
| share-2 | `iconShare` | 18 | textPrimary |
| download | `iconDownload` | 18 | textPrimary |
| sparkles | `iconSparkles` | 18 | accentPrimary(Remix) |
| house | `iconHome` | 18 | 底栏选中 / 未选中 |
| search | `iconSearch` | 18 | 底栏 |
| plus | `iconPlus` | 18 | accentPrimary(Create) |
| bell | `iconBell` | 18 | 底栏 |
| user | `iconUser` | 18 | 底栏 |
| play | `iconPlay` | 16 | textPrimary |
| arrow-down | `iconArrowDown` | 24 | textPrimary |
| arrow-right | `iconArrowRight` | 18 | accentPrimary |
| check | `iconCheck` | 12 | navActiveText |
| chevron-right | `iconChevronRight` | 16 | textSecondary |
| ellipsis | `iconMore` | 20 | textPrimary |
| link | `iconLink` | 20 | textPrimary |
| mail | `iconMail` | 20 | textPrimary |
| message-circle-more | `iconMessage` | 20 | textPrimary |
| send | `iconSend` | 22 | textPrimary |
| trash-2 | `iconTrash` | 16 | textPrimary |
| folder | `iconFolder` | 16 | textTertiary |
| image | `iconImage` | 16 | textTertiary |
| corner-down-left | `iconCornerDownLeft` | 16 | textSecondary |

图标 tint 颜色必须用 AppColors Token,具体 API 见 references/{stack}.md §7。

---

## §13 交互状态映射(通用)

设计稿是静态一帧,以下交互状态需要代码实现:

### 底栏 Tab 状态

| 状态 | 背景 | 图标色 | 文字色 | 圆角 |
|---|---|---|---|---|
| 选中 | accentPrimary #3CFF52 | navActiveText #08100B | navActiveText | 26 |
| 未选中 | 透明 | navInactive #737C87 | navInactive | 26 |
| Create(常驻特殊态)| accentPrimaryBg #18221A | accentPrimary | accentPrimary | 28 |

### Tab 栏状态

| 状态 | 文字色 | 字重 | 指示条 |
|---|---|---|---|
| 选中 | textPrimary #FFFFFF | 700 | 28×3 accentPrimary 全圆 |
| 未选中 | textSecondary #7F8893 | 600 | 40×2 borderDefault 全圆 |

### 按钮状态

| 状态 | 表现 |
|---|---|
| 正常 | 设计稿默认样式 |
| 按压 | 透明度 0.7 或 ripple / scale 反馈 |
| 禁用 | 透明度 0.4 + 不可点击 |
| 加载中 | 内容替换为 ProgressBar 14dp |

### 点赞状态

| 状态 | 图标 | 颜色 |
|---|---|---|
| 未点赞 | heart(空心) | textPrimary |
| 已点赞 | heart-filled(实心) | accentLike #FF6B6B |

---

## §14 边界情况处理

| 场景 | 处理 |
|---|---|
| 文字超长(用户名 / 标题)| 1 行 + 末尾省略号 |
| 列表为空 | EmptyStateView(插图 + 文案 + CTA)|
| 图片加载失败 | 暗色占位 bgCard,不显示错误图标 |
| 网络断开 | 顶部 Snackbar 提示,保留上次缓存数据 |
| 视频不可播放 | 显示封面图 + "Video unavailable" 文案 |
| 列表数据量大(100+)| stack-specific 列表组件 + DiffUtil 等价 |
| 快速连续点击 | 按钮 debounce 300ms / 列表项 throttle |

---

## §15 职责边界

**本 skill 只负责 UI 视觉实现,不处理以下内容**:

- 业务逻辑(state machine / reducer / store)
- 网络请求 / API 调用
- 数据持久化
- 路由跳转逻辑
- 状态管理(loading / error / empty 切换)

这些由 `/assign` 或 `/parallel-dev` 通过业务逻辑任务处理。

---

## §16 规则

1. 完成验证后按任务合同由 Agent 提交；需要扩大范围时走原生确认，不要求用户执行 Git
2. 颜色 / 字号 / 间距必须用 Design Token
3. 图标必须用 Vector / SVG / SF Symbol(按 stack),颜色通过 tint 设置,不硬编码
4. commit message 用中文(若项目语言)
5. 代码中禁止出现 AI / Claude / GPT / LLM / generated / auto-generated 字样
