---
doc_id: "platform-kb/harmony/arkui-incompatibility"
container: platform-kb
platform: harmonyos
summary: "视觉异常 / 某 modifier 不渲染 → 必查本文 + 用既定 workaround。"
---

# ArkUI 不可共存 / Workaround

> 视觉异常 / 某 modifier 不渲染 → 必查本文 + 用既定 workaround。

## I-01. Column 同时 `.backgroundImage` + `.borderStyle(Dashed)` 渲染失败

**症状**:Column 既加 `.backgroundImage($r('app.media.X'))` 又加 `.borderStyle(BorderStyle.Dashed) .borderColor(c) .borderWidth(1)` → bg image 不渲染。

**实证**:某卡片组件首次 transpile 时 fail,改用纯色背景替代。

**Workaround**:嵌套 Stack 分层 — Image 独立层 + Column(dashed border)独立层:

```ts
Stack({ alignContent: Alignment.TopStart }) {
  // 层 1: bg image 全填(必 .position({x:0, y:0}) 避免拉满外层)
  Image($r('app.media.card_background'))
    .width('100%')
    .height('100%')
    .objectFit(ImageFit.Fill)
    .position({ x: 0, y: 0 });
  
  // 层 2: content + dashed border(撑外 Stack 高度)
  Column() { /* Text content + source */ }
    .borderRadius(10)
    .borderWidth(1)
    .borderStyle(BorderStyle.Dashed)
    .borderColor($r('app.color.card_border'))
    .padding({...}).margin({...});
}
```

## I-02. ArkUI Grid `rowsTemplate '1fr 1fr'` + cell `.aspectRatio()` + 横向 scroll = cell 被切

**症状**:Grid 横向(只 rowsTemplate 不 columnsTemplate)+ cell aspectRatio = cell 渲染超容器宽,第一行 / 第二行 cell 被屏幕右边 clip。

**实证**:某横向卡片 Grid + aspectRatio 257:72,第一行顶被切 / 第二行 cell 出右屏。

**Workaround**:用 `Scroll(Horizontal) > Row > ForEach chunked Column(2 cell)`:

```ts
Scroll() {
  Row({ space: 16 }) {
    ForEach(this.chunkedColumns(), (col: T[]) => {
      Column({ space: 20 }) {
        ForEach(col, (item: T) => {
          Row() { CellComponent({ item }) }.width(261).height(73);
        })
      }
      .width(261);
    })
  }
  .padding({ left: 20, right: 20 });
}
.scrollable(ScrollDirection.Horizontal)
.scrollBar(BarState.Off)
.height(2 * cellHeight + 16);
```

cell width / height 用显式数值(按真值 vp),**不用** aspectRatio。

## I-03. Image bg `.width('100%').height('100%')` 拉满外层 ListItem(无 Stack 限制)

**症状**:子 Stack 内 Image bg `.width('100%').height('100%')` + 父无 explicit height + 该 Stack 在 ListItem 内 → Image fill 整个 ListItem 高度 → 卡片视觉"超长"。

**实证**:某卡片 bg image 拉长。

**Workaround**:Image 用 `.position({ x: 0, y: 0 })`(absolute fill),让 Stack 高度由 sibling Column(content + border)撑;Image 跟随 sibling 高度。详 I-01 写法。

## I-04. `Alignment.CenterEnd` 不存在

详 `arkui-components.md §A`(9 值表)。用 `Alignment.End` 替(= 右中)。

## I-05. `NavDestination().backgroundImage()` 实测不渲染

**症状**:`NavDestination().backgroundImage($r('app.media.X')).backgroundImageSize(ImageSize.Cover)` 即便资源存在 + ImageSize 设置 + 无 `backgroundColor` 覆盖 → 页面 BG 仍是纯色,**image 完全不渲染**。

**实证**:某完成页暖米褐纹理背景始终是黑色,直到改写。

**原因**:NavDestination 顶层装饰链对 backgroundImage 支持不完整(SDK 6.1.1(24))。

**Workaround**:把 BG image 放进**内层 Stack 作首子节点**,`.objectFit(Cover).position({x:0,y:0})` 全屏铺底:

```ts
NavDestination() {
  Stack({ alignContent: Alignment.TopStart }) {
    Image($r('app.media.page_background'))
      .width('100%').height('100%')
      .objectFit(ImageFit.Cover)
      .position({ x: 0, y: 0 });
    // ... 主内容
  }
}
.hideTitleBar(true)
```

外层 `.backgroundColor` 也要移除,否则覆盖 image。

## I-06. `@ohos/lottie 2.0.16` `path:` 参数 GetAsset failed

**症状**:`lottie.loadAnimation({ path: 'common/lottie/anim.json', ... })` 即便文件在 HAP `rawfile/common/lottie/anim.json` 路径正确 → hilog `Ace: GetAsset failed: common/lottie/anim.json`,动画不渲染。

**实证**:某 Lottie 动画加载,首条 Lottie 实战。

**原因**:`@ohos/lottie 2.0.16-rc.3` 的 `path:` 解析与 SDK 6.1.1(24) 兼容性问题(可能漏 context 参数或 path base 解析错)。

**Workaround**:用 `animationData` 直传 JSON 对象**绕过 path 解析**:

```ts
import { util } from '@kit.ArkTS';
import lottie from '@ohos/lottie';

// Canvas.onReady() 内:
const buf: Uint8Array = await getContext(this).resourceManager
  .getRawFileContent('common/lottie/anim.json');
const str: string = util.TextDecoder.create('utf-8').decodeToString(buf);
const animData = JSON.parse(str);

lottie.loadAnimation({
  animationData: animData,        // ← 直传 object 绕过 path
  container: this.context,
  renderer: 'canvas',
  name: 'anim',
  autoplay: true,
  loop: false,
});
```

**注意**:`loadAnimation` 必须 Canvas `.onReady()` 后调,且 `animationData` 加载完成后才调(异步顺序)。

---

## I-07 `bindContentCover` chain 只生效最后一个

```ts
SomeComponent()
  .bindContentCover($$showA, builderA)  // ❌ 被覆盖
  .bindContentCover($$showB, builderB)  // ❌ 被覆盖
  .bindContentCover($$showD, builderD)  // ✅ 唯一生效
```

**症状**:`showA = true` 时 builderA 的 @Component 仍 `aboutToAppear`(进 component tree),但 overlay window 不渲染(snapshot_display + hidumper WMS 仅 1 个 window)
**Workaround**:每个独立 cover **必须**挂在独立 component 上(Stack-per-cover)

## I-08 `bindContentCover` overlay 仅 Stack 渲染;Scroll / Column silent fail

```ts
// ❌ Scroll().bindContentCover(...)  → child mount log 触发,overlay 不可见
// ❌ Column().bindContentCover(...) → 同上
// ✅ Stack() { ... }.bindContentCover(...) → overlay 正常渲染
```

**症状**:tap open cover → hilog 显示 child `aboutToAppear` → 但 snapshot 截不到 + uitest dump 不含 cover 节点
**Workaround**:**所有 bindContentCover 强制挂 Stack**;Scroll/Column 是 build root 时用 `Stack() { Scroll() { ... } }` 包裹

## I-09 嵌套 `bindContentCover`:cover 内 child component 起 sub-cover 不渲染

注:实测已证**顶层 page** 上 4 层 nested bindContentCover 可行(各自挂 page 不同 state)。**本 incompatibility 特指**:cover A 的 ChildA 自带 `.bindContentCover(...)` 挂 nested struct 的 Stack → 点 nested 按钮 → 无 mount 日志 / 无 overlay 渲染
**推测**:cover A 的 UIContext 不允许其 child 再起 sub-cover(overlay 层级 / Window 管理限制)
**Workaround**:多层 cover **全部挂最外 page**,内部 child 仅 toggle state

---

## I-10. `bindContentCover` 内异步子组件可能被快速销毁,图片/状态更新不落屏

**症状**:

- 弹窗外框、文字、按钮都出现,但中间图片为空。
- 日志显示图片已 decode 成功,随后出现类似 `View Xxx is already in process of destruction` 的状态更新丢弃。

**根因**:

- `bindContentCover` 的 builder 会把内容放进独立且生命周期不稳定的 overlay 容器。
- 子组件如果包含异步图片解码、PixelMap、lottie、`@Watch`、`@StorageLink` 或网络状态回填,异步回调可能晚于 builder 子树销毁,导致状态更新没有落到当前屏幕。
- 这不只影响 SSE / 实时流。即使是静态弹窗,只要内部有异步资源解码,也可能触发。

**Workaround**:

- 弹窗需要异步资源或响应式状态时,改成同页 `Stack` overlay:

```ts
Stack() {
  PageContent()
  if (this.showDialog) {
    DialogContent({
      dialogInfo: this.dialogInfo,
      onClose: () => this.showDialog = false
    })
  }
}
```

- `bindContentCover` 仅保留给完全同步、无异步资源、无子组件状态回填的轻量弹层。

**已验证案例**:某完成页弹窗内图片不显示。图片组件已 decode 成功,但组件进入销毁流程。将弹窗从 `bindContentCover` 改为同页 `Stack` overlay 后图片稳定展示。

## I-11. `.blur()` ≠ Flutter `TileMode.decal`,halo 类视觉用多层 `.shadow()` 叠白

> **效果名词**:Flutter 原版 = **Ambient Glow**(环境光晕,blur+decal 取封面色外溢羽化);鸿蒙等效 = **Outer Glow**(外发光,白色多层 shadow)。`TileMode.decal` 边缘透明 = **edge feathering**。详 `translate-rules.md R-21`。

**症状**:
- 想还原 Flutter `ImageFiltered + ImageFilter.blur(sigmaX:50, sigmaY:50, tileMode: TileMode.decal) + Positioned.fill(CachedNetworkImage(coverUrl))` 产生的"卡片外柔光 halo 接近屏幕两边",用 ArkUI `Image(coverUrl).blur(50).opacity(0.55)` 配 parent `.clip(false)` **复现失败**

**根因**:
- ArkUI `.blur(radius)` **确实**会外溢节点 bounds(opacity 1.0 + parent clip(false) 时肉眼可见),但**外溢内容是模糊的有色图本身**,**不是** Flutter `TileMode.decal` 那种"边缘 fade 到 alpha 0 透明"的羽化
- 想要的"卡片外白色柔光晕"在 Flutter 实际由 `ImageFilter.blur + decal` + 容器 size > 卡片 size 的视觉合成产生(decal 让边缘像素 = 透明,blur 把透明像素 weighted 混入)
- ArkUI 无 decal tile mode 等效,纯 `.blur()` 出来的是"整片模糊有色封面外溢",非白色光晕

**Workaround**:halo 类视觉用 **多层 `.shadow()` 叠白色** 同 size 占位:

```ts
@Builder
ShareCardGlowLayer() {
  // 3 层同卡片大小的白色 RoundedRect,各叠不同 radius 白色 shadow
  // 内层 cover 全盖,只剩 shadow 从边缘外溢成 halo
  Stack({ alignContent: Alignment.Center }) {
    Column()
      .width(this.shareCardW())
      .height(this.shareCardH())
      .borderRadius(this.shareW(18))
      .backgroundColor(Color.White)
      .shadow({ radius: this.shareW(300), color: 'rgba(255,255,255,0.4)', offsetX: 0, offsetY: 0 })  // 外:halo 接近屏幕边
    Column()
      .width(this.shareCardW()).height(this.shareCardH())
      .borderRadius(this.shareW(18)).backgroundColor(Color.White)
      .shadow({ radius: this.shareW(180), color: 'rgba(255,255,255,0.5)', offsetX: 0, offsetY: 0 })  // 中:过渡
    Column()
      .width(this.shareCardW()).height(this.shareCardH())
      .borderRadius(this.shareW(18)).backgroundColor(Color.White)
      .shadow({ radius: this.shareW(80), color: 'rgba(255,255,255,0.65)', offsetX: 0, offsetY: 0 })  // 内:紧贴卡片
  }
}
```

**调参起点**(供首次实施)— 外 300 / 中 180 / 内 80,opacity 0.4 / 0.5 / 0.65。真机调到 user 视觉确认即可。

**已验证案例**:某分享弹窗 glow 对齐 Flutter。前序 task md 推 1 个方向(放大模糊 Image + clip(false))实测错,改 `.shadow()` 多层叠白色 ship。

**关联**:translate-rules R-21(Flutter `ImageFiltered halo` / `BoxShadow halo` → ArkUI 多层 `.shadow()` 叠白)

---

## I-12. `bindMenu` / `bindContextMenu` 不能直接承载 Flutter 自定义 popup

**症状**:

- Flutter 原版 popup / dropdown 只有一层圆角背景 + shadow。
- 鸿蒙使用 `bindMenu(this.moreMenu)` 或 `bindContextMenu(this.menuBuilder, ...)` 后,即使 `moreMenu()` 内部已经设置了背景、圆角、阴影,真机仍看到内容外多一层浅色/深色背景框。
- 用户常描述为"有奇怪边框",但实际通常是**系统 menu 承载层默认背景**。

**根因**:

- Flutter `DropdownButton2.dropdownStyleData.decoration` 是业务代码直接画的 popup 内容层。
- ArkUI `bindMenu` / `bindContextMenu` 会先创建一层系统 menu popup 承载层,再把自定义 builder 放进去。
- 如果业务 builder 再画 `backgroundColor / borderRadius / shadow`,视觉上就变成"系统承载层背景 + 业务内容层背景"两层叠加。
- 只修改 builder 内容层颜色无法消掉外层默认背景,因此会反复出现"边框/背景框"返工。

**强制检查**:

对齐 Flutter 的 dialog / bottom sheet / action sheet / popup menu / dropdown 时,必须把弹层拆成两层核对:

| 层 | 必查 | 处理 |
|---|---|---|
| 承载层 | Flutter 是否有系统默认外层?ArkUI API 是否自带 menu/dialog container? | 若 Flutter 无外层,ArkUI 承载层必须透明或不用系统 menu |
| 内容层 | width / padding / radius / bg / shadow / item height / offset | 逐项按 Flutter file:line 还原 |

**Workaround**:

- Flutter 是完全自定义 popup 视觉时,优先改为同页 `Stack` 自绘 overlay popup,用显式 `position / width / padding / radius / bg / shadow` 控制。
- 若必须用系统 API,只能用于 Flutter 也是系统菜单视觉的场景;不能再给内容层画第二套背景。
- popup 点击区域 / 关闭逻辑由页面状态控制,外层透明 hit area 负责关闭,内容层只画 Flutter 那一层。

**已验证案例**:某列表项的更多菜单。Flutter `DropdownButton2` 只画 `width:130.w,padding:left14/top10/bottom10,radius8,bg light/dark token,shadow black 0.15 blur8 spread2 offset(0,2)`;鸿蒙用 `bindMenu` 后出现额外背景框,需要改同页 overlay/自绘 popup。

**关联**:feature-parity "弹层双层 gate";translate-rules 后续应补 popup menu 映射规则。

---

### I-13 Flutter 透明路由 sheet 不能只翻译成内容层 Stack overlay

**症状**:

- Flutter 弹层使用 `Get.to(... opaque:false, transition:Transition.downToUp, duration:300ms, fullscreenDialog:true)`。
- Harmony 只在当前页面 `if (showX) { Stack overlay }` 中直接渲染 sheet 内容。
- 结果:弹窗出现动画、背景变暗时机、关闭动画、按钮按压/默认样式都与 Flutter 不一致;多轮只调颜色/间距仍无法对齐。

**根因**:

- Flutter 真值分为两层:
  - 承载层:透明 route + downToUp route transition + reverse transition。
  - 内容层:Scaffold/Column/Container 自绘 sheet。
- Harmony 如果只翻译内容层,缺失 route transition 状态机;如果再用 ArkUI `Button` / 系统 dialog,又会引入平台默认样式。

**Workaround**:

- 对 `opaque:false + downToUp` 类 Flutter route,在 Harmony 同页 overlay 中显式建状态机:
  - `showSheet`:是否挂载 overlay。
  - `sheetTranslateY`:进入前为屏幕高度外偏移,`animateTo(300ms)` 到 0。
  - `scrimOpacity`:按 Flutter 页面内逻辑单独驱动,不要默认和 sheet 位移动画绑定。
  - 关闭时先按 Flutter 设 scrim,再 `animateTo(300ms)` 下滑退出,动画结束再卸载。
- Flutter `InkWell + Container` 按钮必须自绘,不要用 ArkUI `Button` 代替。
- 外部点击是否关闭要按 Flutter 承载层决定;Flutter route 顶部空白无手势时,Harmony scrim/top Blank 不要额外关闭。

**已验证案例**:某设置抽屉页 → 某详情 sheet。Flutter 使用 `Get.to(DetailSheetPage, transition:downToUp, opaque:false, duration:300ms)`,详情页延迟 250ms 将 `_opacity` 设为 0.3。Harmony 初版只直接显示内容层 overlay,导致动画/背景/按钮多轮不一致。

**关联**:feature-parity "透明路由类 sheet";translate-rules 后续应补 `Get.to opaque:false` 映射规则。

---

**未命中 incompatibility** → handoff §upgrade 报 + 提供 ArkUI 版本号 + 现象 → 协调端追加。
