---
doc_id: "platform-kb/harmony/arkui-layout-scroll-shell"
container: platform-kb
platform: harmonyos
summary: "ArkUI 页面壳须区分固定区、完整滚动视口和浮层占用；悬浮底栏的尾部避让由宿主统一派生，安全区仅计一次。"
related: [ap-0151]
aliases: [ap-0147]
supersedes: [ap-0147]
sedimentation_schema: 2
problem_type: bug-fix
evidence_status: verified
---

# ArkUI 滚动页壳 / 固定标题栏 / 悬浮底栏避让规则(v1.2)

> 适用:某 Tab 首页、某二级列表页、某个人页、带吸顶/渐显标题栏、滚动背景、parallax、弹性 overscroll 的页面。  
> 先读本文件,再改控件级 UI。

## 问题原型

固定标题、滚动背景、视口和安全区不分层，会导致回弹覆盖标题、错误 offset 驱动视觉或重复留白。
若又将普通底栏改成全屏 overlay，却继续沿用子页原有尾距和固定按钮位置，就会出现底栏本身
正确、列表最末入口或操作按钮却被覆盖的情况。内容可见和可点击必须分别检查。

## 根因与证据

页面壳的固定区、滚动区和浮层占用没有形成一致的布局契约。新实证中，旧固定按钮的 bounds
与悬浮栏相交；宿主统一派生避让预算、列表和按钮分别消费后，双主题已测目标露出，
多个入口经实际点击打开，相关几何与状态测试通过。完整宿主和安全区测量不支持本次故障
来自“主容器重复计算 safe”，因此不能未经测量就删除系统安全区。

新增 verified 限于上述布局与已实际打开的入口；长列表未滚到真正末尾、未测的路由/系统版本
及未重新构建的集成包均不继承为通过。原页面壳、实际 offset 和缩放规则保留其既有依据，
本次不声称将旧规则全部重新运行验收。

已有避让案例记录了双主题十二组布局、三个实际打开的入口及五十六项相关宿主测试通过；
同批仍有两项不相关的既有测试失败，相关通过不等于全套通过。未专项运行的低版本
fallback 及后续整合产物不继承通过；名义动画峰值的几何计算不等于逐帧实测。
固定标题与 body 分层、预测量或 delta 累加导致的 offset 偏差仍按原 A–H 规则单独核验。

## 适用边界

- 固定标题与滚动 body 的页面按 A–H；全屏重叠悬浮底栏额外按 I 处理内容尾部与固定按钮。
- 页面壳已为非重叠底栏扣除高度、或独立路由没有底栏时，不应再添加悬浮底栏总预算。
- 键盘、弹窗自身避让、透明层抢触摸分别诊断；内容已露出仍滑不动时先查 ap-0151。
- 一台设备的 safe、底栏高度或总避让量不能直接成为所有页面的常量。
- 内容已露出但仍点不到时核对真实命中区域和手势归属，不能继续无限加底距；
  本条不证明任何系统版本的材质或视觉效果。

## 判定样本

### 路由正例

- **输入**：全屏自定义悬浮底栏盖住列表最末卡片或固定按钮，子页仍用普通底栏时期的间距。
- **预期**：apply
- **原因**：浮层占用没有向滚动尾部及固定按钮消费点传递。
- **来源**：observed

- **输入**：列表回弹时背景盖住固定标题，或标题渐显使用滚动 delta 累加而与实际位置脱节。
- **预期**：apply
- **原因**：页面壳分层或实际 offset 来源不符合既有规则。
- **来源**：constructed

- **输入**：全屏自定义悬浮底栏盖住滚动列表最后的内容或固定按钮，末尾操作无法点击。
- **预期**：apply
- **原因**：同时命中全屏 overlay、内容消费点及未传递的浮层占用预算。
- **来源**：observed

- **输入**：ArkUI 固定标题栏在列表回弹时被滚动背景盖住，滚动预测值驱动的标题渐显不稳定。
- **预期**：apply
- **原因**：需要原有页面壳分层和实际 offset 规则，而非只调控件颜色。
- **来源**：constructed

### 路由反例

- **输入**：系统非重叠底栏已经从页面可用高度中扣除，现在是否还要再加一份悬浮底栏尾部预算？
- **预期**：skip
- **原因**：没有额外重叠占用，重复追加会产生双重留白。
- **来源**：constructed

- **输入**：独立路由没有底栏，或系统非重叠 Tabs 已扣除底栏高度，当前没有标题栏、滚动 offset 或宽度异常；是否仍要加悬浮底栏尾距？
- **预期**：skip
- **原因**：没有悬浮占用也没有其他页面壳异常，套用额外预算会制造双重留白。
- **来源**：constructed

### 执行合格例

- **做法或输出**：宿主统一推导避让量，列表抵扣已有尾距、固定按钮单独消费；双主题目标露出，已操作入口实际点开。
- **预期**：pass
- **原因**：验证的是内容消费点及点击可达，不只验证底栏自身。
- **来源**：observed

- **做法或输出**：宿主统一派生预算，滚动末尾抵扣已有尾距，固定按钮分别避让；双主题区域检查通过，末尾入口真实点开，玻璃背后保留滚动内容。
- **预期**：pass
- **原因**：同时验证内容可见、入口可达和背景连续，不以底栏自身外观代替业务边界。
- **来源**：observed

### 执行失败例

- **做法或输出**：底栏已正确靠近安全区，但固定按钮仍使用旧间距，实际 bounds 与底栏相交。
- **预期**：fail
- **原因**：浮层布局正确不代表页面内容已完成避让。
- **来源**：observed

- **做法或输出**：底栏可见且动画正常，固定按钮仍使用旧底距，其真实区域与底栏相交。
- **预期**：fail
- **原因**：浮层定位正确并不保证页面的内容消费点可达。
- **来源**：observed

- **做法或输出**：把一个设备的总预算写死到所有路由，只看静态底栏截图就宣布全部入口通过。
- **预期**：fail
- **原因**：忽略宿主坐标系、已有间距、动画上探与无底栏路径，缺少实际点击及列表末尾证据。
- **来源**：constructed

## 正确做法

### A. 固定 AppBar + 滚动 body 的页面壳

Flutter 常见结构:

```dart
Column(
  children: [
    AppBarLike(),
    Expanded(child: Stack(children: [background, ListView(...)])),
  ],
)
```

ArkUI 必须保持同级结构:

```ts
FixedAppBarContentShell({
  appBar: () => { this.appBarBuilder(); },
  content: () => { this.contentBuilder(); },
  bgColor: this.pageBgColor(),
})
```

`content` 区域内部会 `layoutWeight(1)` + `clip(true)`,防止 List/Scroll/背景图在滚动或弹性回弹时盖住 AppBar。

### B. 禁止用通用 Scaffold 盲套复杂 Tab 页

`BaseScaffold` 适合普通页面的 safe-area 骨架。若 Flutter 页面本身有:

- 背景图穿透状态栏
- AppBar alpha 渐变
- List/Scroll parallax
- overscroll fill image
- body 自己管理顶部视觉边界

则先判断是否必须使用 `FixedAppBarContentShell`。禁止通过调整整页 padding 或负 margin 去修局部视觉。

### C. 滚动 offset 只能取实际值

对位 Flutter `scrollNotification.metrics.pixels`:

```ts
private scroller: Scroller = new Scroller();

List(this.scroller) { ... }
  .onDidScroll(() => {
    const y = this.scroller.currentOffset().yOffset;
    this.updateScrollState(y);
  })
```

禁止:

- 用 `onWillScroll` 预测 alpha/parallax。
- 用 `onScroll` delta 累加成绝对值。
- 多个 Scroll/List 共用同一个 `Scroller`。

### D. Flutter ScreenUtil 统一映射

后续页面禁止复制 `FLUTTER_DESIGN_WIDTH` / `display.getDefaultDisplaySync()` / `densityPixels`。

统一使用:

```ts
FlutterScreenUtil.scaleForWidth(FlutterScreenUtil.FONT_MAX_WIDTH)
FlutterScreenUtil.scaled(value, FlutterScreenUtil.FONT_MAX_WIDTH)
FlutterScreenUtil.adaptive(value, FlutterScreenUtil.TABLET_MAX_WIDTH)
```

常量示例(取值随各项目 Flutter 设计稿而定):

| 常量 | 值 | 用途 |
|---|---:|---|
| `DESIGN_WIDTH` | 390 | Flutter 设计宽 |
| `DESIGN_HEIGHT` | 844 | Flutter 设计高 |
| `FONT_MAX_WIDTH` | 414 | 手机字体/首页视觉 cap |
| `TABLET_MAX_WIDTH` | 655 | tablet/宽屏内容 cap |

### E. 宽度预算硬规则

`.width('100%')` 与 horizontal margin 不能直接叠加。优先:

- 把左右间距放到父级 `padding({ left, right })`。
- 子节点用 `.layoutWeight(1)` 承接剩余宽度。
- 横向列表 item 用 `ListItem.padding({ left, right }) + child.width('100%')`。

每个 UI task 必须 grep 新增/修改链路里的 `.width('100%')` 并审计同链路 horizontal margin/padding。

### F. 状态栏与标题栏

只允许一个层级处理 statusBar height:

- 普通页面:由页面壳或 BaseAppBar 显式处理。
- 固定 Tab 首页:AppBar 自己包含 `statusBarHeight + navHeight`,body 从 AppBar 下方开始。
- 背景穿透状态栏:必须证明 Flutter 真值也是穿透,并写清楚 top inset 抵消原因。

禁止把“标题栏飞到状态栏”修成全页 padding,这会推坏底部固定按钮和滚动首项。

#### F.1 SideSheet / Drawer 顶部 inset 必按 Flutter 承载层反抽

**症状**:抽屉 / 侧滑页顶部整体偏低,或 Header 比 Flutter 多出一截状态栏高度。

**根因**:Flutter `SideSheet` / `Drawer` / `showGeneralDialog` 这类承载层通常已经从屏幕顶端开始布局,内部 Header 的 `marginTop` 是业务数值,不是 `statusBarHeight + marginTop`。鸿蒙如果在抽屉组件内部再加 `Blank().height(statusBarHeight)`,就会重复处理 safe-area。

**强制 review gate**:

- 先定位 Flutter 承载层:是 `Scaffold body`、`SafeArea` 内、`SideSheet`、`Drawer`、`showDialog` 还是自绘 `Stack overlay`。
- Flutter 内层已有明确 `top: X.w / margin(top:X.w)` 时,鸿蒙只翻译 X,不要再凭经验叠加 `statusBarHeight`。
- 只有 Flutter 明确使用 `SafeArea(top:true)` 或 AppBar 页面壳时,鸿蒙才加状态栏 spacer。
- 抽屉宽度、圆角、Header top、底部按钮边距全部用同一 `fw()` / ScreenUtil 映射,不能固定 vp 混用。

**实战来源**:某侧滑抽屉页。Flutter `SideSheet(width:W.w)` 内 Header `marginTop:M.w`;鸿蒙初版额外加 `statusBarHeight` 导致整体偏低。

### G. 提交前验证

至少验证:

1. 首屏初始态。
2. 向上滚动中间态。
3. 吸顶/标题栏完全显示态。
4. 下拉 overscroll 态。
5. dark/light 双模式。
6. 小屏/普通屏至少一种真机截图。

**未命中** → handoff §upgrade 报 → 协调端追加。

### H. 治理元数据（从 ap-0147 迁入）

本文件是滚动页壳、固定标题栏与实际滚动 offset 规则的唯一技术真值。旧反模式
`ap-0147` 已弃用，仅保留 tombstone 兼容历史链接；新文档、任务书和知识关系均应引用
`platform-kb/harmony/arkui-layout-scroll-shell`。

- **历史复发次数**：1（继承自 `ap-0147`，用于治理追踪，不表示本文件新增复发）。
- **lint 状态**：⏳ pending。
- **静态门禁候选**：在标题栏 alpha/parallax 场景发现 `onWillScroll` 时拒绝，要求改为
  `onDidScroll` + `currentOffset().yOffset`；不得把 `onScroll` delta 累加成绝对值。
- **review checklist**：必须填写“滚动页基础层冻结”，覆盖标题栏/body 兄弟分层、body
  `clip(true)`、实际 offset 来源，以及首屏、半滚动、吸顶完成、下拉 overscroll、
  dark/light 五态证据。
- **动手前四问**：标题栏与 body 是兄弟层还是覆盖/穿透？body 是否 `clip(true)`？
  alpha/parallax 是否来自实际 offset？状态栏高度是否只在一处处理且无双重
  padding/负 margin？任一答不上，禁止进入控件级 polish。
- **lint 范围边界**：ScreenUtil 尺寸/字号映射属于独立转译规则，不纳入上述滚动壳
  lint；其技术真值仍见本文件 D 节。

### I. 全屏悬浮底栏的内容避让预算

1. 先测宿主、系统安全区、可见底栏、动画最高遮挡边界以及目标内容的真实区域。
2. 同一页面坐标系中，B = 页面底边到最高遮挡边界的距离 + 内容间隔。
   只有宿主延伸到屏幕底部时，才可展开为 safe + gap + barHeight + upwardExcursion + clearance。
   宿主已经排除 safe 时不能再加；阴影或按压范围超出名义外框时另行核验。
3. 由宿主唯一派生 B 并传给消费页面，不各页复制常量或新增第二个全局 owner。
4. 保留需要透过材质显示的完整滚动视口，在滚动内容内增加尾距或使用 List.contentEndOffset。
   已有同坐标系尾距为 E 时，只补 max(0, B-E)，避免双重留白。
   不用不透明底部条掩盖毛玻璃背景；已有安全区或尾部 spacer 不重复相加。
5. 固定按钮与列表分开消费；底距与 B 同坐标基准时取 max(原底距, B)。
   没有悬浮底栏的宿主传零额外预算，保留页面原布局。
   不能机械地把固定按钮原间距清零。
6. 验证相关页面真实列表末尾、固定入口、双主题和多宽度/safe。动画峰值的计算余量不是
   高帧率逐帧证据；未到长列表末尾时明确标未覆盖，不用按钮通过替代。

## 兼容与降级

不要求把所有版本改成同一底栏。保留各宿主既有的非重叠/重叠策略，依据真实占用选择额外预算。
组件 API 或能力未知时先探测，不把新布局实证推导成所有设备的材质或视觉能力结论。

## 消费与防复发

- 消费者：页面壳与 UI 迁移 review、几何状态测试、运行时布局与入口验收。
- 自动检索消费者采用 `purpose=route` 让显式正反例竞争；命中 skip 不注入尾部预算。
- 必搜：barHeight、barBottomMargin、safeArea、contentEndOffset、固定按钮底距与尾部 margin。
- 实施前记录宿主坐标系、safe owner、浮层最高边界和各消费点；禁止仅移动底栏就宣布全部内容可达。
- 旧标题/offset 规则继续检查；新避让规则须另验独立路由、已有尾距抵扣和无底栏路径。
- 编译、宿主测试、设备行为、几何计算及用户视觉确认分栏；没有新增自动 Hook/lint，不能把本文登记视为自动门禁上线。
