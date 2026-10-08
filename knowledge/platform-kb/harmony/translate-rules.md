---
doc_id: "platform-kb/harmony/translate-rules"
container: platform-kb
platform: harmonyos
summary: "UI 还原 task / transpile Flutter file → ArkUI ets 时**逐行 ref 本…"
---

# Flutter Dart → ArkUI 翻译 mapping 规则

> UI 还原 task / transpile Flutter file → ArkUI ets 时**逐行 ref 本规则**。规则以 `R-XX` 编号,构成翻译字典。
>
> handoff §0 trace 表必逐行 cite `Flutter file:line → R-XX → 鸿蒙 file:line → ✅/❌`。

## R-01 Widget 容器

| Flutter | ArkUI |
|---|---|
| `Container(decoration: BoxDecoration(...), child)` | `Column / Row { child }.backgroundColor().border().borderRadius()` |
| `Padding(padding, child)` | `child.padding(X)` |
| `Row / Column / Stack(children: [W1, W2])` | `Row / Column / Stack() { W1(); W2(); }` |
| `Expanded(child)` | `child.layoutWeight(1)` |
| `SizedBox(width, height)` | `Blank().width(X).height(Y)` |
| `Spacer()` | `Blank().layoutWeight(1)` |
| `InkWell(onTap, child)` | `child.onClick(()=>...)` |

## R-02 Position(Stack 内子节点)

| Flutter | ArkUI |
|---|---|
| `Positioned(left:X, top:Y, child)` | `child.position({ x: X, y: Y })` |
| `Positioned(right:X, top:Y, child)` | `child.position({ x: '100%', y: Y }).markAnchor({ x: '100%', y: 0 }).margin({ right: X })` |
| `Positioned(right:X, bottom:Y, child)` | `.position({x:'100%', y:'100%'}).markAnchor({x:'100%', y:'100%'}).margin({ right: X, bottom: Y })` |
| `Positioned.fill(child)` | Stack child 默认 fill;或 child `.width('100%').height('100%')` |
| `Align(alignment:Alignment.center, child)` | Stack `alignContent: Alignment.Center` 父层;或 child `.align(Alignment.Center)` |

## R-03 Image / R-04 Text — 详 `arkui-components.md §D §E`(具体 enum / API)

## R-05 Color / Theme(平台自动 dark 切换)

Flutter 侧语义色常量(下用中性名 `APP_*` 示意)→ ArkUI `$r('app.color.*')` 资源 token,后者随系统 light/dark 自动切换。

| Flutter | ArkUI |
|---|---|
| `HexColor.APP_T1` | `$r('app.color.text_primary')` |
| `HexColor.APP_T2/T3/T4` | `text_secondary/tertiary/quaternary` |
| `HexColor.APP_BG1/BG2/BG3` | `bg1_primary / bg2_card / bg3_mask` |
| `HexColor.APP_BTN` | `$r('app.color.brand_primary')` |
| `HexColor.APP_L1/L2` | `divider_strong / divider_soft` |
| `HexColor("#FFFFFF")` 单色 | `'#FFFFFF'` 直接字符串 |
| `HexColor("#X").withOpacity(0.2)` | `'#33X'` 8 位 hex(alpha 前):0.2=0x33 / 0.1=0x1A / 0.05=0x0D |

**禁** 直接传 Flutter HexColor 字符串值到 ArkUI(失去自动 dark 切换)。

## R-06 Unit / Size

| Flutter | ArkUI |
|---|---|
| `.w` (ScreenUtil) | `vp`(直接数值)|
| `.sp` | `fp`(直接数值)|
| `1.sw / 1.sh` | `'100%'` 宽 / 高 |
| `EdgeInsets.only(left:A, right:B)` | `.padding({ left: A, right: B })` |
| `EdgeInsets.fromLTRB` | `.padding({ left, top, right, bottom })` |

## R-07 Container 视觉

| Flutter | ArkUI |
|---|---|
| `borderRadius: BorderRadius.circular(R)` | `.borderRadius(R)` |
| `borderRadius: BorderRadius.only(topLeft:A,...)` | `.borderRadius({ topLeft: A, topRight: B, bottomLeft: C, bottomRight: D })` |
| `border: Border.all(color, width)` | `.borderWidth(w).borderColor(c)` |
| `BoxDecoration(image: DecorationImage(image, fit:fill))` | Stack 嵌套(详 `arkui-incompatibility.md I-01`)|
| `DottedBorder(dashPattern, color, radius)` | `.borderStyle(BorderStyle.Dashed).borderRadius(R).borderWidth(1).borderColor(c)` |

## R-08 Layout Flexbox

| Flutter | ArkUI |
|---|---|
| `mainAxisAlignment: center` | `.justifyContent(FlexAlign.Center)` |
| `mainAxisAlignment: spaceBetween` | `.justifyContent(FlexAlign.SpaceBetween)` |
| `crossAxisAlignment: center` (Row) | `.alignItems(VerticalAlign.Center)` |
| `crossAxisAlignment: start` (Column) | `.alignItems(HorizontalAlign.Start)` |
| `mainAxisSize: min` | ArkUI 默认 wrap content,无需显式 |

## R-09 Scroll / List — 详 `arkui-components.md §C`

**❗ Flutter `GridView` `mainAxisSpacing` 默认 0**:若 Flutter source 无显式 `mainAxisSpacing: X.w`,transpile 时 ArkUI `Column({ space: 0 })` / 不加 gap;**禁** 自创 20 vp 默认(会导致 cell 总高超 Scroll 容器 → 顶部 / 底部 切)。

Flutter `crossAxisSpacing` 同 — 默认 0,无显式不加。

显式值 grep:`grep "mainAxisSpacing\|crossAxisSpacing" <Flutter file>`,无 → 0。

### R-09.1 Flutter margin / padding → ArkUI 宽度预算强制规则

Flutter `Container(margin: EdgeInsets.symmetric(horizontal: 20), child: Container(width: double.infinity))` 翻译到 ArkUI 时,**禁** 写成 child 自己 `.width('100%').margin({ left:20, right:20 })`。

**正确映射**:

| Flutter | ArkUI |
|---|---|
| `ListView item margin horizontal 20` | `ListItem().padding({ left: 20, right: 20 }) + child.width('100%')` |
| `Container padding horizontal 16 + Text full width` | `Row/Column.padding({left:16,right:16}) + Text.layoutWeight(1)` 或显式 `constraintSize({maxWidth})` |

**强制自检**:每个 `.width('100%')` 都问一次:同链路是否还有 horizontal margin?父级是否已有 horizontal padding?若有,必须把 inset 上移到父容器或改 `layoutWeight(1)`。

详 `arkui-components.md §WIDTH-100-MARGIN-OVERFLOW`。

### R-09.2 Flutter AlwaysScrollableScrollPhysics → ArkUI alwaysEnabled

Flutter:

```dart
physics: BouncingScrollPhysics(
  parent: AlwaysScrollableScrollPhysics(),
)
```

ArkUI:

```ts
.edgeEffect(EdgeEffect.Spring, { alwaysEnabled: true })
```

**禁** 只写 `.edgeEffect(EdgeEffect.Spring)`:这只覆盖 Bouncing,不覆盖 AlwaysScrollable。内容不足一屏时会丢失 Flutter 弹性手感。

详 `arkui-components.md §LIST-ALWAYS-BOUNCE`。

### R-09.3 Flutter ListView.padding → ArkUI scrollable 内容内 inset

Flutter:

```dart
ListView.separated(
  padding: EdgeInsets.only(top: 29.w),
  itemBuilder: ...
)
```

ArkUI 禁止把 `top:29` 翻译到 List 外层 `Blank` 或页面级 margin。它必须属于可滚动内容本身:

```ts
List() {
  ListItem() {
    Column() { Blank().height(29) }
      .width('100%')
      .height(29)
  }

  ForEach(this.items, (item, index) => {
    ListItem() {
      this.ItemCell(item)
    }
    .width('100%')
  })
}
.layoutWeight(1)
```

**映射原则**:

| Flutter | ArkUI |
|---|---|
| `ListView.padding(top:X)` | `List` 内 header `ListItem` 高 X,或平台确认可用的 content inset |
| `ListView.padding(horizontal:X)` | `ListItem.padding({ left:X, right:X })`,child `.width('100%')` |
| `ListView.separated(separatorBuilder: SizedBox(height:X))` | item `ListItem.margin({ top: index === 0 ? 0 : X })` 或显式 separator `ListItem` |
| `ListView` 外固定 bottom widget | `List.layoutWeight(1)` + bottom widget sibling,不要塞入 List |

详 `arkui-components.md §LIST-TOP-ANCHOR`。

## R-10 Routing / State

| Flutter | ArkUI |
|---|---|
| `Get.to(()=> Page())` | `Router.push(Routes.X, params)` |
| `Get.toNamed("/x?id=1")` | `Router.push(Routes.X, { id: 1 })` |
| `Get.back()` | `Router.pop()` / `Router.back()` |
| `Get.dialog(W)` | `CustomDialogController({ builder: W }).open()` |
| `GetView<Ctrl>` | `@Component struct + @State / @StorageProp` |
| `controller.update(['id'])` | ArkUI @State 自动响应 |

详 `routing-navigation.md` + `state-management.md`。

## R-11 AppBar / SafeArea — 详 `arkui-components.md §F`

### R-11.1 Flutter Scaffold + AppBar → ArkUI 自定义标题栏 SafeArea

Flutter `Scaffold(appBar: BaseAppBar(...), body: ...)` 默认由 Flutter/SafeArea 体系处理状态栏。ArkUI 若用:

```ts
NavDestination() { ... }.hideTitleBar(true)
```

则必须显式处理状态栏:

```ts
Column() {
  Blank().height(this.statusBarHeight)
  BaseAppBar({ title: '标题', bgColor: pageBg })
  Content().layoutWeight(1)
}
.backgroundColor(pageBg)
```

**禁** 直接把 `BaseAppBar` 放在 y=0。用户反馈"标题栏飞到状态栏"时,第一检查本规则。

详 `arkui-components.md §SAFEAREA-APPBAR-FIXED`。

## R-12 Custom Painter / Canvas — 详 `arkui-components.md §G`

## R-X2 Flutter NotificationListener 仅 over-scroll(非真刷新)

Flutter `NotificationListener<ScrollUpdateNotification>` 仅:
- `controller.offset = pixels`(供 AppBar alpha 算法)
- `controller.onScroll(pixels)`(供 backImage parallax 算法)

**禁** transpile 用 `BaseRefresh({ onRefresh, content })`(启用真刷新跟 Flutter 不一致)。

**正确**:Stack 直接放 List(无 Refresh 包装),`onDidScroll` 取 `scroller.currentOffset().yOffset` 给 parallax + alpha。下拉 over-scroll 是 ArkUI List 默认 bouncing;背景填充由 `if (scrollOffset < 0) Image height -scrollOffset` 自动视觉 fill。

详 `arkui-components.md §C`。

## R-15 NavPathStack.pop signature

`Router.pop(value)` 必直传不 wrap。详 `routing-navigation.md §G`。

```ts
// ❌ Router.stack?.pop({ result: value });    // popInfo.result 多套一层
// ✅ Router.stack?.pop(value as Object);      // popInfo.result === value
```

## R-16 pageMap 全 routes 注册

`Navigation(navStack).navDestination(this.pageMap)` 的 `@Builder pageMap(name)` 必含**所有** Routes else-if 分支。漏注册 = NavDestination 渲染空白("没数据"假象)。详 `routing-navigation.md §H`。

加新 Route 后:Routes.ts enum + 所有 pageMap 宿主页同步加 else-if,**数量必相等**。

## R-17 Flutter 真值 grep-first 铁律

UI / UX / 业务"不一致"时**第一动作 = grep Flutter file:line 抓真值**,禁猜数值 / 字重 / 色值 / 边距。

某购买页重实现的多轮 polish 验证:靠猜的典型翻车点:
- 分隔线用 `divider_strong`(#E5E5E5),Flutter 对应 token 实为 `#F2F2F2`(详 §R-18)
- 字重无脑 `FontWeight.Bold`,Flutter w600 = SemiBold = numeric 600(详 §R-19)
- 选择卡未选态 border width 2 透明造 halo,Flutter 真值 0
- 底部输入 dialog 以为 fullscreen,Flutter 真值 `Align(bottomCenter) + Container(height: 711.h)`

**应用**:
1. 用户报"不一致" → grep Flutter dart 文件 + Read 行号 + 记 hex/字重/边距 原始值
2. 必 grep 色值 token 定义文件(如 `lib/utils/hex_color.dart`)拿 token hex,**禁假设语义近 token**
3. Flutter `HexColor.isDarkMode ?` 分支 → 鸿蒙 `@State isDarkMode` 双值(详 `state-management.md §isDarkMode`)
4. 翻译 self-verify table:Flutter file:line ↔ ArkUI file:line ↔ 一致?

## R-18 Flutter 语义色 hex token 真值表

反抽 Flutter 色值 token 定义文件后,列 light/dark 双 hex 对照(token 名下用中性 `APP_*` / `*` 示意):

| Flutter token | light hex | dark hex | 鸿蒙 token |
|---|---|---|---|
| APP_T1 | #333333 | #CCCCCC | `text_primary` |
| APP_T2 | #666666 | #888888 | `text_secondary` |
| APP_T3 | #999999 | #999999 | `text_tertiary` |
| APP_T4 | #CCCCCC | — | `text_quaternary` |
| APP_BG1 | #FFFFFF | #111111 | `bg1_primary` |
| APP_BG2 | #F8F8F8 | #1F1F1F | `bg2_card` |
| APP_BG3 | #0A000000 | #0AFFFFFF | `bg3_mask` |
| APP_LIGHT_BG1_DARK_BG2 | #FFFFFF | #1F1F1F | `light_bg1_dark_bg2` |
| **APP_L1** | **#E5E5E5** | #444444 | `divider_strong` |
| **APP_L2** | **#F2F2F2** | #2D2D2D | `divider_soft` |
| APP_BTN | #FCA14C | #FCAE65 | `brand_primary` |
| APP_LIGHT_BTN | #FCA14C(常量,不切)| — | (literal `#FCA14C`)|

⚠️ **L1 ≠ L2** — strong 比 soft 深。某详情页 rights 表分隔用 L2(#F2F2F2)。

`withOpacity(0.1)` 等价 8 位 hex(eg `APP_BTN.withOpacity(0.1)` light = `#1AFCA14C` / dark = `#1AFCAE65`)。

## R-19 Flutter w600 ≠ ArkUI FontWeight.Bold

| Flutter weight | ArkUI 应用 |
|---|---|
| w400 / Regular | `FontWeight.Regular` 或 `FontWeight.Normal` |
| w500 / Medium | `FontWeight.Medium` |
| **w600 / SemiBold** | **`.fontWeight(600)` numeric**(ArkUI 无 SemiBold 枚举)|
| w700 / Bold | `FontWeight.Bold` |

❌ **禁** 用 `FontWeight.Bold` 替 Flutter `FontWeight.w600` — Bold=700 偏粗会视觉不一致。

## R-20 Asset 命名双向 lookup

> 常见痛点:找不到 Flutter 页面 / 图片资源、dark/light mode 总搞错。以下为 asset 迁移 + 命名铁律。

### R-20.1 Asset path 映射规则

(下用 `<flutter>` / `<harmony>` 指代两端 repo 根)

| 维 | Flutter 路径 | 鸿蒙映射 | 鸿蒙 ref |
|---|---|---|---|
| **light 单图** | `<flutter>/assets/images/X.png` | `<harmony>/entry/src/main/resources/base/media/X.png` | `$r('app.media.X')` ets / `"app.media.X"` AbilityKit |
| **dark variant** | `<flutter>/assets/images/X_dark.png` | `<harmony>/entry/src/main/resources/dark/media/X.png`(**注意:鸿蒙端文件名去 `_dark` 后缀**) | 同 `$r('app.media.X')` 自动 light/dark 切换 |
| **alpha mask 单图** | `<flutter>/assets/images/X.png`(白色 / 透明 alpha)+ Flutter 用 `color:` 参数染色 | `<harmony>/entry/src/main/resources/base/media/X.png`(单图 light/dark 同图,不分 dark 文件夹)| `$r('app.media.X')` + `.fillColor($r('app.color.X'))` 鸿蒙端染色 |
| **多分辨率 PNG** | `<flutter>/assets/images/2.0x/X.png` + `3.0x/X.png` | 鸿蒙取最高分辨率(3.0x)迁 `base/media/X.png`(单文件,鸿蒙自动 vp 缩放)| `$r('app.media.X')` |
| **SVG / Lottie** | `<flutter>/assets/lottie/X.json` | `<harmony>/entry/src/main/resources/rawfile/X.json` | `Lottie` widget `animationData: getRawFileContent('X.json')`(per `arkui-incompatibility.md I-06`)|

### R-20.2 命名规则铁律

- 鸿蒙 `media/` 内文件名 **禁含** `_dark` 后缀(系统按文件夹路径自动识别)— Flutter `X_dark.png` 必 cp 到 `dark/media/X.png` 且**去掉 `_dark`**,鸿蒙才会 light/dark 自动切换
- 文件名 ASCII / 数字 / `_` / `.`,**禁** 中文 / 大写 / 横线 `-`(鸿蒙 resource compiler 拒)
- alpha mask 图(白色/透明)→ 单文件迁 `base/media/`,**禁** 在 `dark/media/` 重复 cp 同图(冗余)— 鸿蒙端 `.fillColor()` 染色自动适配 dark token
- 全彩照片 / 渐变 jpg → 单文件迁 `base/media/`(若 Flutter 端无 `_dark` variant 就单图)

### R-20.3 Dev 实施前必跑 verify(防找不到 Flutter source / 漏迁 dark)

```bash
# Step 1:verify Flutter source 存在 + 列 dark variant
ls <flutter>/assets/images/{keyword}* | grep -E "\.(png|jpg|jpeg|webp)$"
# 输出含 X.png + X_dark.png?→ 双 mode 必双 cp

# Step 2:cp light
cp <flutter>/assets/images/X.png <harmony>/entry/src/main/resources/base/media/X.png

# Step 3:若 dark 存在,cp 去 _dark 后缀
[ -f <flutter>/assets/images/X_dark.png ] && cp <flutter>/assets/images/X_dark.png <harmony>/entry/src/main/resources/dark/media/X.png
# 注意:目标文件名 X.png(无 _dark),鸿蒙系统按 base/ vs dark/ 文件夹自动切换

# Step 4:verify 鸿蒙端两侧文件名一致
ls <harmony>/entry/src/main/resources/{base,dark}/media/X.png
# 期望:base/media/X.png + dark/media/X.png 同文件名 ✅
```

### R-20.4 dual-mode visual gap 自检 5 问

Dev 实施 + 真机 verify 时必双 mode 自检:

1. 此 asset Flutter 端有 `_dark` variant? — `ls` verify
2. dark variant 迁 `dark/media/X.png` 文件名去 `_dark` 后缀? — `ls` verify
3. 鸿蒙端 `$r('app.media.X')` 在 light + dark mode 显示 image 不同? — 真机切换 verify(应用内 深色模式 切换路径)
4. alpha mask 图 `.fillColor()` 用 dark-aware token(`$r('app.color.*')`)而非 literal hex? — grep 代码
5. asset 引用 light/dark 都正确显示后,handoff §视觉对比表 各 mode 5+ 元素 ❌ ≤ 1?

任一 No → handoff 标 partial 不 ✅ shipped(per handoff pre-merge gate)。

### R-20.5 Page-specific hardcoded hex 处理(非语义 token 时)

某些 page 用 page-specific hardcoded hex(非语义 token 系列,eg 某页 `#FDFBF7/#111111` / 某卡片 `#FFFCF8/#1F1F1F`):

- 协调端 task md 必给 light + dark hex 一对儿(per task md 规则)
- Dev 实施用 `@State` const 显式存:
  ```ts
  private readonly PAGE_BG_LIGHT = '#FDFBF7';
  private readonly PAGE_BG_DARK = '#111111';
  @State private isDarkMode: boolean = false;  // aboutToAppear 设
  // build():
  .backgroundColor(this.isDarkMode ? this.PAGE_BG_DARK : this.PAGE_BG_LIGHT)
  ```
- **禁** 单 hex literal(失去 dark 自适应)
- **禁** 推断"这页用 BG1 / BG2"(可能 page-specific 非 token 真值)

详 `state-management.md §isDarkMode`。

---

### R-21 Flutter halo 视觉 → ArkUI 多层 `.shadow()` 叠白

> **效果正式名词**:Flutter 原版(`ImageFiltered + blur + TileMode.decal` 取封面图模糊外溢)= **Ambient Glow / Ambient Lighting**(环境光晕,YouTube "Ambient Mode" 同款,光晕取自内容颜色);鸿蒙落地(多层白色 `.shadow()`)= **Outer Glow**(外发光,PS 图层样式名,纯白柔光不取内容色)。`TileMode.decal` 的边缘透明 = **edge feathering(边缘羽化)**。task md / handoff 用词统一走这两个名。

**Flutter 真值形态**(任一命中):
- `ImageFiltered(imageFilter: ImageFilter.blur(sigmaX:50, sigmaY:50, tileMode: TileMode.decal), child: 大于卡片的容器内放 CachedNetworkImage / Image)`
- `Container(decoration: BoxDecoration(boxShadow: [BoxShadow(color: Colors.white.withOpacity(0.X), blurRadius: Y, spreadRadius: Z)]))`(直接 BoxShadow halo)
- 视觉表现 = 卡片外一圈白色柔光,左右扩散,渐变 fade 到背景

**ArkUI 映射**(per `arkui-incompatibility.md I-11`):**多层 `.shadow()` 叠白色**

| Flutter 维度 | ArkUI 等效 |
|---|---|
| `BoxShadow.color` rgba(255,255,255,X) | `.shadow({ color: 'rgba(255,255,255,X)' })` |
| `BoxShadow.blurRadius` Y | `.shadow({ radius: Y })`(数值需真机调,Flutter blurRadius 不能 1:1 直译)|
| `BoxShadow.spreadRadius` Z | ArkUI 无直接等效 — 用 N 层 .shadow 叠加不同 radius/opacity 模拟扩散 |
| `ImageFiltered + TileMode.decal` | **禁** `.blur()` 替代(实测错,per I-11);用 `.shadow()` 多层叠白 |

**实施模板**(N 层叠加,N = 2-4 视效果):

```ts
@Builder
HaloLayer() {
  Stack({ alignContent: Alignment.Center }) {
    // 外层:halo 最远范围 + 最低 opacity
    Column()
      .width(cardW).height(cardH).borderRadius(R).backgroundColor(Color.White)
      .shadow({ radius: <largest>, color: 'rgba(255,255,255,<lowest>)', offsetX: 0, offsetY: 0 })
    // 中层:过渡
    Column().width(...).shadow({ radius: <mid>, color: 'rgba(255,255,255,<mid>)' })
    // 内层:halo 紧贴卡片 + 最高 opacity
    Column().width(...).shadow({ radius: <smallest>, color: 'rgba(255,255,255,<highest>)' })
  }
  // 实际卡片内容在 HaloLayer 上方一层 Stack 渲染(把白色 fill 完全盖住,只剩 shadow 外溢)
}
```

**调参起点**(供首次实施):外 300 / 中 180 / 内 80,opacity 0.4 / 0.5 / 0.65。真机 1-3 轮调到 user 视觉确认。

**已验证案例**:某报告页分享卡 glow 层。前序 task md 的"放大模糊 Image + clip(false)"方向实测错,Dev fallback 到 `.shadow()` 多层叠白色 1 轮 ship。

**判定线**:UI 类 task md 出现"halo / 柔光 / glow / 卡片周围模糊光晕"关键词 → 直接走 R-21,**禁** 推 `.blur()` 方案。

---

### R-22 Flutter 弹层 / 侧滑 / 行内富文本 翻译 gate

> 这条是 UI 1:1 对齐前置 gate。Flutter 三方控件或复合 widget 不能只迁"看得见的内容",必须先拆承载层、内容层、交互状态、单位映射。

| Flutter 真值 | ArkUI 优先映射 | 禁止项 | 关联规则 |
|---|---|---|---|
| `DropdownButton2` 自定义 menu / custom popup | `bindPopup(... popupColor: Transparent, enableArrow:false, shadow:transparent)` 或同页 `Stack overlay` 自绘 | 直接 `bindMenu/bindContextMenu` 承载自定义背景 | `arkui-incompatibility.md I-12` |
| `SideSheet` / `Drawer` / `showGeneralDialog` | 先反抽 route/overlay 是否已自带 top inset,再翻内部 margin | 默认加 `statusBarHeight` | `arkui-layout-scroll-shell.md F.1` |
| `RichText` / `Text.rich` / `WidgetSpan` | `Text { Span(); ImageSpan(); }` 保持行内布局 | 翻成 sibling `Row { Text; Image }` | `arkui-components.md §TEXT-WIDGETSPAN-INLINE` |
| `TextField` 自动 focus / `FocusNode.requestFocus` / 页面进入拉键盘 | 调焦点 API 前先同步本地 focus state | 等 `onFocus` 再改 UI 状态 | `arkui-components.md §TEXTINPUT-PROGRAMMATIC-FOCUS` |
| `.w/.h/.sp` 出现在弹层、抽屉、菜单、输入栏 | 全部使用统一 ScreenUtil/fw 映射 | 页面主体适配了,弹层仍用固定 vp | `arkui-layout-scroll-shell.md D` |

**强制 self-check**:

1. 这个 UI 是否有系统承载层?如果有,承载层背景/箭头/遮罩/安全区是否已核对?
2. Flutter 是否用了三方 widget?如果用了,是否查了三方 widget 的 `styleData / route / overlay / offset / elevation`?
3. `.w/.sp` 是否在 popup/menu/drawer/input bar 也完整映射?
4. 是否存在行内图标/动画?若存在,是否保持行内排版?
5. 是否存在程序触发 focus/keyboard?若存在,本地 UI state 是否先于系统 focus API 更新?

**实战来源**:某聊天页 更多菜单、抽屉、SSE dots、输入框 focus。

---

### R-23 Flutter 公共 UI 依赖闭包 gate

> Flutter 页面命中自定义公共 UI 组件时,不能只迁调用点。必须继续追 public API -> private builder -> theme/resource -> third-party default,再决定 ArkUI 映射。

**命中形态**:

- 公共 Dialog helper（如 `CommonDialog.showDialog(...)`）
- `Get.dialog(...)` / `Get.bottomSheet(...)` / `Get.to(... opaque:false ...)`
- `SharePlatformView` / `CommonButton` / `TitleBar` / `Loading` / refresh header/footer
- Flutter 三方 widget wrapper,如 `DropdownButton2` / picker / cached image / rich text parser

**强制反抽表**:

| 维度 | 必查 Flutter 真值 | ArkUI 映射要求 |
|---|---|---|
| 承载层 | route/dialog/overlay/barrier/alignment/safeArea/transition/dismiss | 同页 overlay 或自定义 dialog 状态机,显式实现;禁系统默认样式污染 |
| 内容层 | width/height/constraints/padding/margin/radius/bg/shadow/blur | `.width/.height/.padding/.borderRadius/.backgroundColor/.shadow` 逐项映射 |
| 文本层 | title/content/button text/font/weight/color/align/maxLines | `Text` 样式逐项映射,不套系统 Button 默认文本样式 |
| 按钮层 | 顺序/主次/handler/disabled/pressed/loading/语义 | 自绘 `Text/Row/Column` click 区域;确认/取消语义按 Flutter 原样 |
| 主题层 | light/dark/fixed-light share/system theme | 颜色 token 追到定义,不能硬编码单色 |
| 资源层 | image/icon/lottie/tint/dark variant | 资源名双向 lookup,缺资源先迁移 |
| 三方默认层 | pub package / Flutter framework 默认参数 | 查源码或 pub cache;禁止凭肉眼猜 |

**公共 Dialog helper 特例**:

- Flutter 真值在公共 util(如 `lib/utils/<common_dialog>.dart`),不是业务 page/controller。
- ArkUI 禁直接用 `promptAction.showDialog` 或系统 dialog service 替代。
- 必须移植 `Get.dialog + Center + Container(width:310.w, radius:20, bg:APP_BG2, maxHeight:0.7.sh, barrierDismissible:false, transitionDuration:100ms)` 及 `_buildTextDialog/_buildInputDialog` 的按钮/文字布局。

**已验证事故**:

- 某业务同步弹窗:Flutter 三处完成链路均调用同一公共 Dialog helper,Harmony 初版复用系统 promptAction dialog,导致 UI 与 Flutter 不一致。根因是业务链路追到了,公共 UI 依赖没有闭包反抽。

**判定线**:

UI task 中任一 Flutter 调用链出现公共 UI 依赖,但 task/handoff 没列依赖闭包表 → 禁实现、禁验收、禁声明 shipped。

---

## 字典外 widget / 未列 rule

handoff §upgrade 报"行 X 无 rule 映射,我用 Y workaround,需协调端补 rule" → 协调端 review 后追加。
