---
doc_id: "work-model/skills/dev/ui-impl"
container: work-model
platform: cross
summary: "Android/iOS Dev 以 pen-truth、运行截图和行为契约逐节点还原 UI，并保留双平台适配差异。"
---

# UI 精确还原（Android / iOS）

以协调端提供的 `pen-truth/{pageId}.md`、对应 PNG 和资源包为设计真相，以 PRD/行为契约为内容与交互真相。旧导出 JSON 只可辅助，不能覆盖 pen-truth。缺少目标页真相时写 handoff 请求协调端生成，暂停实现。

## 数据优先级

1. PRD / UI 行为契约：文案、状态、流程和交互。
2. pen-truth 文档：节点、尺寸、颜色、字体、间距、圆角和图标。
3. pen-truth PNG：视觉校验。
4. 当前代码：业务逻辑与可复用组件。

冲突时不自行发明规则：记录冲突并交协调端裁决。

## 阶段 0：关系与边界

- 读取页面关系图和行为契约索引，区分页面、状态、流程与弹层。
- 定位本次涉及的全部页面和实现文件；缺项写 handoff。
- 建立修改白名单：只改目标 UI 与必要的系统级基础设施，不碰无关业务逻辑。
- 判断系统级或业务级。安全区、键盘、方向、主题泄漏、通用字体/容器属于基础设施；颜色、字号、间距、圆角、文案和选中态通常属于页面实现。

## 五阶段执行

1. **观察**：读取运行截图和 pen-truth PNG，列出至少布局、形状、颜色、尺寸、间距、文案、缺失元素与交互状态差异，标 P0/P1/P2。
2. **逐节点证据**：遍历 pen-truth 节点，每个节点至少核对三项属性；记录真值、实施值、代码证据和 ✅/⚠️/❌。非 pen-truth 元素必须说明保留、修改或删除理由。
3. **根因与方案**：区分结构、数值、适配和业务契约冲突；P0/P1 给出备选方案、影响和风险，选择最小正确方案。
4. **执行**：优先复用 Token、组件与资源，不以页面硬编码修补系统级问题，不改业务 action/effect。
5. **验证**：重新构建并截图；实现前与 handoff 前各读取一次真相图，逐节点复扫并对比 baseline。

## 平台差异

### Android:

- 截图：真机/模拟器用 `adb exec-out screencap -p`；仅截当前页，导航能力不足时请用户手动到目标页。
- 布局：Compose/View 使用系统 insets、WindowSizeClass/约束布局与密度无关单位；避免固定屏高偏移。
- 触控与无障碍：最小热区、contentDescription、字体缩放和 RTL 必须验证。
- 键盘与系统栏：统一 scaffold/insets/IME 方案；不要在页面叠加魔法 padding。
- 列表与图片：稳定 key、懒加载、异步图片三态和避免组合期重活。
- 动效与反馈：使用平台 ripple/interaction 与可测试动画时长，遵守减少动态效果设置。

### iOS:

- 截图：用 `xcrun simctl io booted screenshot`；只截当前页，不用系统辅助功能脚本自动导航，目标页不对时请用户手动导航。
- 布局：SwiftUI/UIKit 使用 safe area、size class 和约束；不要用固定屏高或临时顶部 padding。
- 触控与无障碍：最小热区、accessibility label、Dynamic Type 与 VoiceOver 必须验证。
- 键盘与系统栏：统一页面容器处理 safe area/keyboard；方向锁定和暗色模式在入口或基础设施解决。
- 列表与图片：稳定 identity、异步图片三态、避免 body 内同步重活。
- 动效与反馈：使用平台 animation/transition/haptic，并尊重 Reduce Motion。

## 截图纪律

- 保存 `before` baseline 和当前 `after`，不累积版本号截图。
- 新截图前清理同页旧 `after`；验收后清理临时截图。
- 截图必须与同一设备、主题、语言、数据和页面状态下的真相图比较。
- 截图只是视觉证据；尺寸、颜色、字体和节点存在性仍以 pen-truth 文档为准。

## 三态视图与边界情况

对 loading/content/empty/error、选中/未选中/禁用、长文案、极端字号、弱网、深浅色、横竖屏或分屏按适用范围验证。资源缺失不得用文本字符或随意图标代替，应登记资源 handoff。

## handoff 报告

```markdown
# UI 审查报告：{页面}
- 平台 / 设备 / 主题 / 状态：
- pen-truth 与行为契约：
- baseline / after 截图：
- P0 / P1 / P2 统计：

| pen-truth 节点 | 关键属性真值 | 实施值与代码证据 | 状态 |
|---|---|---|---|
| {节点} | {至少三项属性} | {Token/组件/位置} | ✅/⚠️/❌ |

- 非真相元素决策：
- 修改文件：
- 三态视图结果：
- 未决冲突 / 风险：
```

## 禁止

- 凭印象宣称“已对齐”，或只列节点存在、不列具体属性。
- 用硬编码颜色、字体或魔法 padding 绕过 Token/基础设施。
- 为 UI 对齐改变业务状态机、网络请求或导航语义。
- 跨写协调端 pen-truth 或另一端仓库；差异与需求只写本端 handoff。
