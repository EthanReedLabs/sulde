---
doc_id: "platform-kb/harmony/arkui-components"
container: platform-kb
platform: harmonyos
summary: "用 ArkUI 组件 / 看到视觉异常 / 不确定 API 行为前必读。"
---

# ArkUI 组件 API 行为

> 用 ArkUI 组件 / 看到视觉异常 / 不确定 API 行为前必读。

## A. Alignment enum 9 值真值清单

ArkUI `Alignment` **仅 9 值**:

| Enum | 含义 |
|---|---|
| `TopStart` / `Top` / `TopEnd` | 左上 / 中上 / 右上 |
| `Start` / `Center` / `End` | 左中 / 居中 / **右中**(不是 `CenterEnd`)|
| `BottomStart` / `Bottom` / `BottomEnd` | 左下 / 中下 / 右下 |

**禁** `Alignment.CenterEnd` / `Alignment.CenterStart`(编译 ERROR `does not exist`)。

## B. Stack / Layout

| 场景 | 写法 |
|---|---|
| Stack 默认子节点对齐 | Flutter Stack 默认 topLeft → ArkUI 必显式 `Stack({ alignContent: Alignment.TopStart })` |
| Stack 内子节点单独定位 | `child.align(Alignment.X)`(per-child override)|
| Stack 内右下定位 | `.position({ x: '100%', y: '100%' }).markAnchor({ x: '100%', y: '100%' }).margin({ right: X, bottom: Y })` |
| Row gap | `Row({ space: 12 })` 构造参(非 `.gap()`)|
| 等比子组件 | `.layoutWeight(1)` |
| 空白占位 | `Blank().width(X)` 或 `Blank().layoutWeight(1)` |

## C. List / Scroll / Grid

| Flutter 行为 | ArkUI 写法 |
|---|---|
| `GridView horizontal crossAxisCount:2` 2 行横滑 | **不用 Grid**(实战曾遇 cell 被切);改 `Scroll(ScrollDirection.Horizontal) > Row { ForEach chunked Column(2 cell stacked) }` |
| `physics: BouncingScrollPhysics` | ArkUI List / Scroll 默认 bouncing |
| 隐藏 scroll bar | `.scrollBar(BarState.Off)` 必加(默认显)|
| `RefreshIndicator(onRefresh)` 真刷新 | 公共 Refresh 组件(`{ onRefresh, content }`)|
| `NotificationListener<ScrollUpdateNotification>` 仅 over-scroll(无 RefreshIndicator)| **禁**用公共 Refresh 组件包(会启用真刷新);Stack 直接 `List` + `onDidScroll` 拿 offset(per parallax)+ `if (offset<0) Image fill_space` 视觉 |

## D. Image

| Flutter | ArkUI |
|---|---|
| `BoxFit.fill` | `ImageFit.Fill` |
| `BoxFit.cover` | `ImageFit.Cover` |
| `BoxFit.contain` | `ImageFit.Contain` |
| `Image.asset(AC.X)` | `Image($r('app.media.X'))`(去 prefix)|
| `Image.network(url)` placeholder/error | `Image(url).alt($r('app.media.placeholder'))` |
| `image.color: c` tint | `.fillColor($r('app.color.X'))` 仅单色 png |
| Image fill 父 Stack 不撑外 ListItem | `.position({ x: 0, y: 0 })` absolute fill(某列表 cell 教训)|

## E. Text

| Flutter | ArkUI |
|---|---|
| `fontSize: 14.sp` | `.fontSize(14)`(fp 等价)|
| `FontWeight.w400 / w500 / w600` | `FontWeight.Regular / Medium / Bold` |
| `style: TextStyle(height: 1.5)` | `.lineHeight(font_size * 1.5)` 直接 vp |
| `maxLines: 1, overflow: ellipsis` | `.maxLines(1).textOverflow({ overflow: TextOverflow.Ellipsis })` |
| `RichText(TextSpan(children))` | `Text() { Span(s1); Span(s2); }` 或 `Row { Text; Text }` |

## F. AppBar / SafeArea

**❗ 公共 Scaffold 组件已自加 statusBar padding**(scaffold 内部 `.padding({top: topInset, bottom: bottomInset})`)→ 页面自定义 AppBar 内**不可**再加 `.padding({top: statusBarHeight})` 叠加(教训:双重 padding = statusBar × 2 ≈ 60dp 间隔)。

**bg image 穿透 statusBar 正确写法**(reverse 公共 Scaffold padding):

```ts
Stack({ alignContent: Alignment.Bottom }) {
  Image($r('app.media.header_bg')).width('100%').height('100%').objectFit(ImageFit.Fill);
  // alpha bg layer
  Row() { /* 头像+昵称+操作 */ }.width('100%').height(44);
}
.width('100%')
.height(this.statusBarHeight + 44)
.padding({ top: this.statusBarHeight })       // 内容 (Row) 在 statusBar 下方
.margin({ top: -this.statusBarHeight });       // ❗ 关键:负 margin 抵消公共 Scaffold 自加 topInset,让 Stack 反向延展到 statusBar 上方

// statusBarHeight 必走 STORAGE_KEY 常量:
// @StorageProp(STORAGE_KEY.PlatformStatusBarHeight) statusBarHeight: number = 0;
```

**禁** `.expandSafeArea(...)` 单独用(在公共 Scaffold 的 appBar slot 内不生效,曾走错 fix 方向)。

---

## F-old. AppBar / SafeArea(legacy)

Flutter `Container(height: statusBarHeight + navBarHeight, decoration: bg image)` AppBar 总容器穿透 statusBar:

```ts
Stack({ alignContent: Alignment.Bottom }) {
  Image($r('app.media.header_bg')).width('100%').height('100%').objectFit(ImageFit.Fill);
  // alpha bg layer
  Row() { /* 头像 + 昵称 + 操作 */ }.width('100%').height(44).alignItems(VerticalAlign.Center);
}
.width('100%')
.height(this.statusBarHeight + 44)
.padding({ top: this.statusBarHeight })
.expandSafeArea([SafeAreaType.SYSTEM], [SafeAreaEdge.TOP]);

// statusBarHeight 来源:@StorageProp('PlatformStatusBarHeight')
// EntryAbility onWindowStageCreate 写入:
//   const area = win.getWindowAvoidArea(WindowAvoidAreaType.TYPE_SYSTEM);
//   AppStorage.SetOrCreate('PlatformStatusBarHeight', px2vp(area.topRect.height));
```

**禁** 仅 `expandSafeArea` 不加 height + padding(曾走错 fix 方向:image bg 只在 44 vp navBar 显,不扩到 statusBar)。

## G. Canvas / Custom Painter

```ts
private settings: RenderingContextSettings = new RenderingContextSettings(true);
private context: CanvasRenderingContext2D = new CanvasRenderingContext2D(this.settings);

build() {
  Canvas(this.context).width(X).height(X).onReady(() => this.paint());
}

paint(): void {
  const ctx = this.context;
  ctx.lineWidth = 12;
  ctx.strokeStyle = '#FCA14C';
  ctx.beginPath();
  ctx.arc(cx, cy, r, startAngle, endAngle);  // angle 同 Flutter: -π/2 = top, 顺时针
  ctx.stroke();
}
```

## §G. PNG `.fillColor()` 不生效(仅 SVG)— opacity / colorFilter / 双 PNG 替代

**症状**:`Image($r('app.media.icon_good')).fillColor($r('app.color.brand_primary'))` → **PNG asset 未变色**。

**原因**:`.fillColor()` 仅对 **SVG / SymbolGlyph 矢量**生效;PNG / JPG raster 无效。

**3 个 Workaround**(由优到劣):

| # | 方案 | 适用 |
|---|---|---|
| 1 | **opacity 模拟 grey-out**:`Image(icon).opacity(selected ? 1.0 : 0.35)` | 选中/未选切态(如表情 pill)|
| 2 | **`.colorFilter(new ColorFilter([...]))`** 矩阵变换 | 复杂染色;ColorMatrix 4×5 数值 |
| 3 | **asset 提前出彩色 + 灰色两版本 PNG** | 精准颜色 / 性能优 |

**实证**:某表情 pill 3 个 PNG(good/same/bad)选中/未选切色。

## §H. 右贴布局 → `.markAnchor` + `.position 100%`(Length 不支持算术)

**症状**:试图把 child 元素右贴 parent Stack 右边,无固定 vp 屏宽前提:

```ts
// ❌ ArkUI Length 不支持算术
.position({ x: '100% - 242', y: 0 })
```

**Workaround**:用 `markAnchor` 把 child 的右上角作锚点,再 `position` 到 parent 100%:

```ts
Canvas(this.context).width(242).height(267)
  .markAnchor({ x: 242, y: 0 })     // 锚点 = child 右上(等于 width)
  .position({ x: '100%', y: 53 })   // 锚点贴 parent 100% 位置
```

**实证**:某图右贴 parent Stack。

## §I. Scroll 绝对 offset 必用 Scroller.currentOffset()(某页 AppBar 渐显)

ArkUI `Scroll().onScroll((xOffset, yOffset) => ...)` 中 xOffset/yOffset 是**每帧 delta**(非绝对位)。累加得绝对偏移**实测 fling 丢帧漂移**。

**正路**:`Scroller` controller + `.currentOffset().yOffset`

```ts
private scroller: Scroller = new Scroller();
@State private appBarAlpha: number = 0;

Scroll(this.scroller) { ... }
  .onScroll(() => {
    const y = this.scroller.currentOffset().yOffset;  // 绝对偏移
    let a = y / 200;
    if (a < 0) a = 0;
    else if (a > 1) a = 1;
    this.appBarAlpha = a;
  })
```

对位 Flutter `scrollNotification.metrics.pixels` 用法。

**注意**:Scroller 必 new 1 次绑 Scroll() 构造参,多 Scroll 共用同一 Scroller → runtime error。

## §J. bindContentCover 自定义底部 sheet

`bindContentCover` Builder 默认填满全屏。Flutter `showDialog + Align(bottomCenter) + Container(height: N)` 等价实施:

```ts
@Builder
private SheetContent(): void {
  Stack({ alignContent: Alignment.Bottom }) {  // ← 外 Stack 底部对齐
    Stack({ alignContent: Alignment.TopStart }) {
      Image($r('app.media.sheet_bg'))
        .width('100%').height(711).objectFit(ImageFit.Fill)
      Column() { /* 卡内容 */ }.width('100%')
    }
    .width('100%').height(711)  // ← 内卡固定高(Flutter 真值)
  }
  .width('100%').height('100%')
  .backgroundColor(Color.Transparent)  // ← 上方透明
}

build() {
  NavDestination() { ... }
    .bindContentCover(this.showSheet, this.SheetContent(), {
      modalTransition: ModalTransition.DEFAULT,
      onDisappear: () => { this.showSheet = false }
    })
}
```

**bindSheet vs bindContentCover**:Flutter 用 `showDialog + Align(bottom) + Container(height)` 非 `showModalBottomSheet` → 鸿蒙端 bindContentCover + Stack 自定义底部对齐 1:1 视觉。Flutter 用 `showModalBottomSheet` → 鸿蒙端 bindSheet。

---

## §V. Timeline cell pattern(border-left vertical line + Span inline onClick)

### V.1 border-left 替 Divider 实现 vertical line

**症状**:Row 内 `Divider.vertical(true)` 期望填满 Row 高度作 timeline 竖线,实测 cell 显得过高(体感"一屏只有一个 cell")。

**Workaround**:用 Column 自身 **border-left** 实现 vertical line。Border 是 box 自身一部分,无额外高度开销:

```ts
Row() {
  Blank().width(7.75);  // 左 spacer 对齐 dot 中心(dot 16 wide, center 8 - 0.25 half line = 7.75)
  Column { content }
    .layoutWeight(1)
    .padding({ left: 15.5, top: 9, bottom: 8 })
    .border({
      width: { left: this.isLast ? 0 : 0.5 },  // 末 cell 隐 line
      color: $r('app.color.text_quaternary'),
    });
}
```

### V.2 跨 cell vertical line 自然 connect

List 无 item 间距 + 各 cell body 末加 `margin bottom 8` 延伸 line 到 cell 底 → adjacent cell 顶 dot row 16vp + 自己 body line 顶部 → 视觉上 line 从 dot A 下方延伸到 dot B 上方,经 dot B 圆点显隔后续 line。

### V.3 Span 内 onClick 实现 inline 可点击文字

**对位 Flutter `RichText > TextSpan + TapGestureRecognizer`**(某折叠富文本组件):

```ts
Text() {
  Span(this.truncatedText()).fontSize(12).fontColor($r('app.color.text_secondary'));
  Span('...').fontSize(12).fontColor($r('app.color.text_secondary'));
  Span(' 查看更多')
    .fontSize(12).fontColor($r('app.color.text_secondary'))
    .opacity(0.5)
    .onClick(() => this.onTap());  // ✅ Span 支持 onClick
}
.lineHeight(20)
.width('100%')
.textAlign(TextAlign.Start);
```

**注意**:Span 受 `Text.maxLines + Ellipsis` 影响 — Ellipsis 从末尾 cut,会把最后的 Span(如 "查看更多")截掉。若 manually truncate 已 fit,**删 maxLines/Ellipsis**,Text 自然 wrap。

### V.4 Refresh 在 NavDestination 内

```ts
Refresh({ refreshing: $$this.refreshing }) {
  List() { ForEach ... }.width('100%').height('100%')
}
.layoutWeight(1).width('100%')
.onRefreshing(() => this.loadData())
```

`$$` 双向 binding,Refresh 内 child 必单一 List/Scroll/Grid。

### V.5 折叠文本算法 ArkUI 启发式近似

**Flutter 折叠文本组件**:`TextPainter.didExceedMaxLines` runtime measure + 二分查最大 N 使 `substring(0,N)+"..."+查看更多` 恰好 fit 2 lines。

**ArkUI 启发式**(无 build 期 runtime measure):

```ts
// 12sp 中文 ~12vp/char, content width ~294vp → ~24 char/line, 2 lines ≈ 48 char threshold
private isExceedMaxLines(): boolean { return this.answerText.length > 48; }
private truncatedText(): string { return this.answerText.substring(0, 40); }
```

**升级路径**:用 `@kit.ArkUI MeasureText.measureTextSize({textContent, fontSize, constraintWidth, maxLines})` runtime 测高度 → 计算 lineCount → 精算法对位 Flutter。

---

## §GRID-TRAILING-SPACER:Grid trailing scroll spacer 模拟 Flutter SliverToBoxAdapter

**问题**:Flutter Stack(scrollView + bottom 200vp shading overlay + button)布局 — items 滚动经过 shading 时被 alpha gradient mask 出 fade 效果,scroll 末时 last items 因 trailing `SliverToBoxAdapter(270.h)` 自动顶到 shading 上方清晰区。

**❌ 错误做法**:`Grid.padding({bottom: 200})` — ArkUI Grid padding 是 layout inset(挤压 items 在 inner area),**不是 scrollable extension**。Items 不能 scroll past natural end → 无 fade + last items 仍在 viewport 边缘可点但无渐隐。

**✅ 正确做法**:在 ForEach 后追加 N 个透明 GridItem 作 scroll spacer:

```ts
Grid() {
  ForEach(this.list, (item) => {
    GridItem() { CellView({ item }); }.aspectRatio(98/48)
      .onClick(() => onTap(item));
  }, (item) => `cell-${item.id}`);
  // Trailing scroll spacer:N 个透明 GridItem 对位 Flutter SliverToBoxAdapter(270.h)
  ForEach([0,1,2,...,N-1], (i) => {
    GridItem() { Row(); }.aspectRatio(98/48); // Row() 占位,Blank() 不可直挂 GridItem
  }, (i) => `spacer-${i}`);
}
.columnsTemplate('1fr 1fr 1fr')
.rowsGap(24).columnsGap(16)
.padding({left:32, right:32}) // 不加 bottom!
```

**N 取值**:总 spacer 高度 ≥ overlay 高度。eg overlay 200vp,3 cols × aspectRatio 98/48 ≈ row 49vp + gap 24 → 需 5 行 = 15 个 spacer ≈ 5*49 + 4*24 = 341vp 安全。某页 aspectRatio=1,row ~100vp,3 行 9 spacer ≈ 332vp 即够。

**⚠️ 坑**:`Blank()` 不能直接挂 GridItem(`ERROR 10903329 / 10905201: 'Blank' component can only be nested in the 'Row,Column,Flex' parent component`)。用 `Row()` 或 `Column()` 占位。

---

## §TEXT-LAYOUTWEIGHT-OVERFLOW:Text 在 layoutWeight Column 不自动 shrink

**陷阱**:`Text(maxLines:1) + textOverflow Ellipsis` 在 `Column.layoutWeight(1)` 父容器内 **不一定触发 ellipsis 截断**!ArkUI Text 默认 wrap-content,长文 Text 自身扩宽 → 推挤兄弟节点(如固定宽按钮)→ 视觉 "贴住" 或溢出。

**对比 Flutter**:`Expanded(Column [Text(maxLines:1, overflow:ellipsis)])` — Expanded 显式约束 Column 宽度,Column 把约束传给 Text → Text 自动 ellipsis 截断。**ArkUI 在 layoutWeight 内的约束传递行为不同**。

### 2 种修法

**A. 加 `.width('100%')` 强制 ellipsis 截断**
```ts
Text(this.descText)
  .width('100%')          // ← 关键!强约束才能 ellipsis 触发
  .maxLines(1)
  .textOverflow({ overflow: TextOverflow.Ellipsis });
```
**适用**:Flutter 端文字也允许 ellipsis(eg 列表 cell 副标题 / 标题超长)

**B. 收紧兄弟节点尺寸,给 layoutWeight Column 更多自然宽度**
- 缩 Row padding / Blank gap / 固定宽兄弟尺寸
- 让最长文自然 fit,无需 ellipsis
**适用**:Flutter 端文字完整不省略(用户能感知 "..." 是 drift)

### 实战案例(某记录卡)
- 改前:Row padding L20 R16 + Blank 20 + 文字 Column.layoutWeight(1) + Blank 8 + 按钮 58x32 → 文字 Column ~150vp 临界,长文 144vp 推按钮贴
- 改后:Row padding L12 R10 + Blank 14 + 文字 + Blank 4 + 按钮 48x28 → 文字 Column ~184vp,长文 144vp 自然 fit ✅(走方案 B,因 Flutter 端不省略)

### How to apply
- 用户报 "文字贴住相邻元素 / 截断异常" 视觉 → 第一嫌疑 layoutWeight Text 不 shrink
- 检查 Text 是否有 `.width('100%')` / `.constraintSize({maxWidth})` 显式约束
- Flutter 端文字完整不省略 → 方案 B(收紧兄弟尺寸 + 加小 Blank 呼吸空隙)
- Flutter 端有 ellipsis → 方案 A 加 `.width('100%')`

---

## §SHEET-BARRIER-SCRIM — bindContentCover 无 default barrier scrim

**症状**:`bindContentCover` 出场 sheet 无 dim/scrim,体感"顶着背景上去"。

**根因**:ArkUI `bindContentCover` 不自带 Flutter `showModalBottomSheet.barrierColor` 等价 default barrier。需手动 Stack wrap + `Color.Black.opacity(@State)` overlay + `animateTo` fade-in,否则视觉硬切。

**修法**:
```ts
@State private scrimOpacity: number = 0;

@Builder
private SheetCoverBuilder(): void {
  Stack({ alignContent: Alignment.Bottom }) {
    Column().width('100%').height('100%')
      .backgroundColor(Color.Black)
      .opacity(this.scrimOpacity)
      .onClick(() => this.closeSheet());
    SheetContent({ ... }).onClick(() => {});  // 阻冒泡
  }
  .width('100%').height('100%')
  .onAppear(() => {
    animateTo({ duration: 250, curve: Curve.EaseOut }, () => { this.scrimOpacity = 0.4; });
  });
}

private closeSheet(): void {
  animateTo({ duration: 200, curve: Curve.EaseIn }, () => { this.scrimOpacity = 0; });
  setTimeout(() => { this.showSheet = false; }, 200);
}

.bindContentCover($$this.showSheet, this.SheetCoverBuilder(),
  { modalTransition: ModalTransition.DEFAULT })
```

**关键**:close 也要 animate-out(否则硬切)+ sheet `.onClick(() => {})` 阻冒泡。

---

## §SCROLL-FADE-ONWILLSCROLL — onWillScroll 每帧 vs onDidScroll 滞后

**症状**:Scroll fade(AppBar alpha)用 `.onDidScroll` 滞后,体感不平滑。

**根因**:`.onDidScroll` 滚动**结束后**触发,`.onWillScroll` 每帧**预判触发**(对位 Flutter `NotificationListener<ScrollUpdateNotification>`)。

**修法**:
```ts
.onWillScroll((scrollOffset: number, _state: ScrollState, _src: ScrollSource) => {
  // 每帧拿 delta + currentOffset() 预判 + 同帧更新 appBarAlpha + scrollOffset state
  const current = this.scroller.currentOffset().yOffset;
  this.updateScrollState(current + scrollOffset);
})
.onDidScroll((_offset: number, _state: ScrollState) => {
  // 最终绝对 offset 校准
  this.onScroll();
})
```

**rule**:fade-on-scroll / parallax 用 `onWillScroll`;只要最终位置用 `onDidScroll`。

---

## §BUTTON-GAP-COLLAPSE — FlexAlign.SpaceBetween 窄屏 collapse 0

**症状**:Row 用 `justifyContent(FlexAlign.SpaceBetween)` + 2 buttons 各 hardcoded width,窄屏(360vp)真机看到 2 button **挨住**,无 gap。

**根因**:button width 163 × 2 + outer padding 20+20 = 366vp,360vp 屏 overflow → SpaceBetween gap **collapse 到 0** + 内容截断。

**修法**:
```ts
Row() {
  Text('重置').layoutWeight(1).height(48).borderRadius(24);  // ⚠️ flex 自适应
  Blank().width(12);                                           // ⚠️ 显式 12vp gap
  Text('确定').layoutWeight(1).height(48).borderRadius(24);
}
.width('100%').padding({ left: 20, right: 20 });
```

**rule**:窄屏 button row 用 `layoutWeight(1) + Blank(N) + layoutWeight(1)` 显式 gap,**禁** hardcoded width + SpaceBetween(在 overflow 时无声 collapse 0)。

---

## §IMAGE-FILLCOLOR-RASTER — fillColor 栅格 png 不可靠

**症状**:Dark mode 下 Image `fillColor($r('app.color.text_primary'))` (dark = #FFFFFF) 期望切亮色,实际仍显原 png 颜色。

**根因**:`fillColor` 仅对 alpha mask(SVG / 单色透明 png)生效;**栅格 PNG**(多色 / 带 alpha 通道实色像素)`fillColor` 行为不一致。

**修法**:
- 双 png 套(base + dark 各一份,文件名同):ArkUI 自动按 ColorMode 选 dark/media 目录
- 若用 `fillColor` 兜底,验 png 真是 alpha mask(`file` 命令 + 像素扫描)
- 重绘 dark 变体:base sample `#000000/A161` → dark sample `#FFFFFF/A161`(同 alpha 翻色)
- 常见落地:图标类 png 在 `dark/media/` 目录另放白色 alpha shape 变体,ArkUI 按主题自动挑选

**rule**:dark mode 翻色 = 双 png 套优先,fillColor 仅 SVG / 已验 alpha mask 时用。

---

## §COLUMN-LEFT-ALIGN — Column 默认 horizontal Center

**症状**:tip box 内 Text 标题 + 子行默认居中,与 Flutter `crossAxisAlignment: CrossAxisAlignment.start` 不符。

**修法**:Column **必加** `.alignItems(HorizontalAlign.Start)`,否则默认 Center alignment。

```ts
Column() {
  Text('小贴士').fontSize(12);
  // tip rows
}
.alignItems(HorizontalAlign.Start)   // ⚠️ 必加
.width('100%')
```

**rule**:1:1 Flutter `crossAxisAlignment.start` → ArkUI Column `.alignItems(HorizontalAlign.Start)` 不能漏。

---

## §WIDTH-100-MARGIN-OVERFLOW — `width('100%') + horizontal margin/padding` 会右侧溢出

**症状**:页面视觉整体像 Flutter,但卡片 / 行 / 描述块右侧超出屏幕或被裁切。常见于 `ListItem` / `Row` / `Column` 子组件写了 `.width('100%')`,同时自己又写 `.margin({ left, right })` 或父子两层都叠加 horizontal padding。

**根因**:ArkUI 中子组件 `.width('100%')` 先按父容器全宽计算,再叠加自身 horizontal margin,最终实际占用宽度 = `父宽 + left + right`,不会像 Flutter `Container(margin)` 那样自动从可用宽度里扣除 margin。

**禁用写法**:

```ts
Column() { ... }
  .width('100%')
  .padding(16)
  .margin({ left: 20, right: 20 }) // ❌ 100% + 40vp,右侧必有溢出风险
```

带 padding 的容器内,子 Text 再 `.width('100%')` 也可能二次撑宽:

```ts
Row() {
  Text(desc).width('100%') // ❌ Row 自己已有 left/right padding 时高风险
}
.width('100%')
.padding({ left: 16, right: 16 })
```

**正确做法**:

1. 外部间距放父容器 / `ListItem.padding`,内容卡片只 `.width('100%')`。
2. 带 horizontal padding 的 Row 内,文本优先 `.layoutWeight(1)` 或显式 `constraintSize({ maxWidth })`,不要无脑 `.width('100%')`。
3. 写任何 `width('100%')` 前做宽度预算:`100% + margin? + parent padding? + child padding?`。预算不为屏宽内闭合即不准提交。

```ts
ListItem() {
  Column() { ... }
    .width('100%')
    .padding(16)
    .borderRadius(20)
}
.width('100%')
.padding({ left: 20, right: 20 }) // ✅ 父层扣除左右 inset

Row() {
  Text(desc)
    .layoutWeight(1) // ✅ 占剩余空间,不冲破 Row padding
}
.width('100%')
.padding({ left: 16, right: 16 })
```

**强制 review gate**:

- 看到 `.width('100%')` 同链路带 `.margin({ left/right })` → 必改。
- 看到 `ListItem { child.width('100%').margin(left/right) }` → 必改为 `ListItem.padding(left/right) + child.width('100%')`。
- 看到 padded Row 内 `Text.width('100%')` → 必检查是否改为 `layoutWeight(1)`。

**实战来源**:某选择页卡片 `.width('100%') + margin({left:20,right:20})` 导致右侧超屏。

---

## §LIST-ALWAYS-BOUNCE — Flutter AlwaysScrollable 必映射 `edgeEffect(..., { alwaysEnabled: true })`

**症状**:改成 ArkUI `List` 后顶部固定了,但用户反馈"弹性列表没有了"。内容不足一屏或刚好接近一屏时,下拉/上拉没有 Flutter 的 bounce 手感。

**根因**:ArkUI `List.edgeEffect(EdgeEffect.Spring)` 默认 `alwaysEnabled: false`,只有内容超过一屏才有回弹。Flutter `BouncingScrollPhysics(parent: AlwaysScrollableScrollPhysics())` 表示内容不满一屏也始终可滚动回弹。

**正确映射**:

```ts
List() { ... }
  .width('100%')
  .layoutWeight(1)
  .scrollBar(BarState.Off)
  .edgeEffect(EdgeEffect.Spring, { alwaysEnabled: true })
```

**禁用写法**:

```ts
List() { ... }
  .edgeEffect(EdgeEffect.Spring) // ❌ 只等价 Bouncing,不等价 AlwaysScrollable
```

**强制 review gate**:

- Flutter 出现 `AlwaysScrollableScrollPhysics` → ArkUI `List/Scroll/Grid.edgeEffect` 必带 `{ alwaysEnabled: true }`。
- Flutter 只有普通可滚动且内容必超一屏 → 可只用 `.edgeEffect(EdgeEffect.Spring)`。
- 用户说"弹性列表没有了 / 拉不动 / 内容少时不回弹" → 第一检查 `alwaysEnabled`。

**实战来源**:某选择页 Flutter `BouncingScrollPhysics(parent: AlwaysScrollableScrollPhysics())` 漏译为单参数 `EdgeEffect.Spring`。

---

## §SAFEAREA-APPBAR-FIXED — NavDestination 自定义标题栏必须显式处理状态栏

**症状**:标题栏"飞到状态栏里面",返回按钮 / 标题被系统状态栏遮挡,或不同页面标题栏纵向位置不一致。

**根因**:`NavDestination().hideTitleBar(true)` 后系统标题栏不再帮页面处理安全区。自定义公共 AppBar / `Row title bar` 若直接放在根 `Column` 顶部,就会从屏幕 y=0 开始布局,与状态栏重叠。

**禁用写法**:

```ts
NavDestination() {
  Column() {
    CommonAppBar({ title: '标题' }) // ❌ hideTitleBar 后直接顶到 y=0
    // content
  }
}
.hideTitleBar(true)
```

**标准模板**:

```ts
NavDestination() {
  Column() {
    Blank().height(this.statusBarHeight)

    CommonAppBar({
      title: '标题',
      showBack: true,
      bgColor: $r('app.color.light_bg2_dark_bg1'),
    })

    List() { ... }
      .layoutWeight(1)
  }
  .width('100%')
  .height('100%')
  .backgroundColor($r('app.color.light_bg2_dark_bg1'))
}
.hideTitleBar(true)
```

**强制 review gate**:

- 看到 `.hideTitleBar(true)` + 自定义 AppBar → 必查是否有 `statusBarHeight` spacer 或复用已验证 Scaffold。
- 标题栏背景色必须和页面顶部背景色一致,不能只给 content 背景。
- 全屏背景图 / 沉浸式头图是例外,但必须显式写负 margin / overlay 策略并标注真值来源,不能误删 safe spacer。
- 若使用公共 Scaffold,先查本文 §F 是否已经内置 topInset,避免重复加 `Blank().height(statusBarHeight)`。

**实战来源**:多页修复中多次出现"标题栏飞到状态栏",包括某协议 / FAQ / 专业版相关页面。

---

## §LIST-TOP-ANCHOR — 数据列表首项必须由 List 自身锚定顶部

**症状**:第一个数据总是不能贴近顶部,整体偏低;改动外层 `Blank` / `Column.layoutWeight` 后不同屏幕表现不稳定。

**根因**:`Scroll { Column { Blank(top); ForEach(...) } }.layoutWeight(1)` 把滚动内容、顶部占位、外层弹性高度混在一起。ArkUI 在父子多层 `layoutWeight` / `Blank` / 固定底部 sibling 组合下,首项锚点容易被外层弹性分配影响。

**禁用写法**:

```ts
Scroll() {
  Column() {
    Blank().height(29)      // ❌ 列表 top padding 放在外层 Column
    ForEach(data, itemView)
  }
}
.layoutWeight(1)
```

**标准模板**:

```ts
List() {
  ListItem() {
    Column() {
      Blank().height(29)    // ✅ Flutter ListView.padding(top:29) 的内容内 header
    }
    .width('100%')
    .height(29)
  }

  ForEach(this.items, (item, index) => {
    ListItem() {
      this.ItemCell(item)
    }
    .width('100%')
    .padding({ left: 20, right: 20 })
    .margin({ top: index === 0 ? 0 : 12 })
  })
}
.width('100%')
.layoutWeight(1)
.scrollBar(BarState.Off)
.edgeEffect(EdgeEffect.Spring, { alwaysEnabled: true })
```

**底部固定区分工**:

```ts
Column() {
  CommonAppBar(...)

  List() { ... }
    .layoutWeight(1)       // ✅ 只有中间滚动区吃剩余高度

  Row() { this.ProtocolText() }
    .margin({ bottom: 57 }) // ✅ Flutter 若是 body 外固定底部,不要塞进 List
}
```

**强制 review gate**:

- 页面主体是数据集合 → 优先 `List/ListItem`,不要用 `Scroll + Column + ForEach` 模拟列表。
- Flutter `ListView.padding(top:X)` → ArkUI 必放进可滚动内容内部(header `ListItem` / content inset),不能放到 List 外层。
- 有固定底部协议 / 按钮 / footer → 中间 `List.layoutWeight(1)`,底部作为 sibling;除非 Flutter footer 本身在 List 里。
- 用户说"整体靠下 / 第一条不在顶部 / 弹性列表导致偏移" → 第一检查是否违反本规则。

**实战来源**:某选择页 `Scroll + Column + Blank + ForEach` 改为 `List + header ListItem + item ListItem` 后首项稳定。

---

## §TEXT-WIDGETSPAN-INLINE — Flutter RichText/WidgetSpan 必保持行内布局

**症状**:SSE 流式文字后的"三个点" loading 跑到气泡右侧,没有紧跟文字尾部。

**根因**:Flutter `RichText(TextSpan(children:[TextSpan(...), WidgetSpan(child: Image/Lottie)]))` 是行内排版。鸿蒙若翻译成 `Row { Text().layoutWeight(1); Image() }`,图片会按 Row 的剩余宽度靠边,不是文字流的一部分。

**标准映射**:

```ts
Text() {
  Span(content)
  ImageSpan($r('app.media.loading_dots'))
    .width(18)
    .height(6)
    .verticalAlign(ImageSpanAlignment.CENTER)
}
```

**强制 review gate**:

- Flutter 出现 `RichText` / `Text.rich` / `WidgetSpan` / `InlineSpan` → ArkUI 必优先用 `Text { Span(); ImageSpan(); }` 或等价行内能力。
- 禁止把 `WidgetSpan` 翻译成 sibling `Row/Image`,除非 Flutter 真值本来就是 Row。
- 流式文本 / AI 回应 / 句尾 loading 都要真机验证"图标是否紧跟最后一个字符"。

**实战来源**:某聊天 cell SSE loading dots。Row 翻译导致 dots 靠右,改 `ImageSpan` 后与 Flutter `WidgetSpan` 语义一致。

---

## §TEXTINPUT-PROGRAMMATIC-FOCUS — 程序拉起键盘时必须同步本地 focus 态

**症状**:进入聊天页后键盘已经显示,但输入框仍使用失焦态背景 / 间距;或键盘动画后 UI 才补跳一次。

**根因**:ArkUI `focusControl.requestFocus()` / `inputMethod.showTextInput()` 不保证立即触发组件 `onFocus` 回调。若 UI 依赖 `onFocus` 才更新 `inputFocused`,程序拉起键盘时会出现状态滞后。

**标准做法**:

```ts
// 调 requestFocus/showTextInput 前先同步 UI state
this.inputFocused = true;
focusControl.requestFocus('inputField');
inputMethod.getController().showTextInput();
```

**强制 review gate**:

- 任何页面存在"进入后自动聚焦 / 发送后重新聚焦 / 切换 emoji 后重新聚焦" → 本地 focus state 必在调用 requestFocus 前同步。
- `onFocus/onBlur` 只作为用户手动焦点变化的补充,不能作为程序聚焦的唯一状态来源。
- 键盘相关 UI 必验证:进入页、发送后、切换面板、返回/收起键盘四态。

**实战来源**:某聊天页自动拉起键盘时 `inputFocused` 未及时更新,导致输入栏位置/背景不稳定。
