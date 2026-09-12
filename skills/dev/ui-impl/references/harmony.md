# ui-impl Harmony 参考(`mobile-harmony`)

> 配套 `../SKILL.md`。本文件含 HarmonyOS NEXT 特定 API / 命令 / 框架决策。

## §0 写代码必读

Harmony 写代码顺序(从 `<docs-hub>/00_shared-rules/`):

```
编码原则集.md(ArkTS 习语 + 装饰器顺序)
  → 设计模式实现.md(ArkUI declarative 模式)
  → self-fix-boundary.md
  → data-sources.md
  → 才动代码
```

**Harmony 决策**:
- UI 框架:ArkUI(declarative,与 SwiftUI / Compose 同源思路)
- 状态:`@State` / `@Prop` / `@Link` / `@StorageLink` 装饰器
- 路由:`router.pushUrl` / `Navigation` 容器
- IDE:DevEco Studio
- 构建工具:hvigorw

官方文档:<https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/>

## §1 系统级问题 → AdaptiveScaffold / SafeArea

| 问题症状 | 修复位置 |
|---|---|
| 状态栏被遮挡 | 包 View 在 `Navigation` 容器(默认避让)或用 `expandSafeArea([SafeAreaType.SYSTEM])` 反向操作 |
| 内容延伸到底部安全区 | 用 `Navigation` 容器 或 `SafeAreaPadding` 修饰 |
| 键盘弹出遮挡输入框 | `keyboardAvoidMode(KeyboardAvoidMode.RESIZE)` 在 window 配置 |
| 系统弹窗显示亮色 | App `ConfigurationConstant.ColorMode.COLOR_MODE_DARK` |
| 屏幕能横屏 | `module.json5` `orientation: "portrait"` |
| 字号过大被系统放大 | ArkUI 默认尊重 dp,用 `fp` 才会系统缩放 |
| Inter 字体没生效 | `resources/base/fonts/` 加 .ttf + `module.json5` declare |

## §2 业务级 Token / API

| 业务概念 | Harmony API / 文件 |
|---|---|
| Token 文件路径 | `commons/coreui/src/main/ets/designtokens/` |
| Colors Token | `AppColors.ets`(`AppColors.accentPrimary`)|
| Typography Token | `AppTypography.ets`(`AppTypography.body1` returns text props)|
| Spacing Token | `AppSpacing.ets` |
| 文案多语言 | `resources/{locale}/element/string.json` |
| 资源引用 | `$r('app.string.xxx')` / `$r('app.color.xxx')` / `$r('app.media.xxx')` |
| Gradients | `AppGradients.ets`(LinearGradient declarations) |

## §3 截图 / 抓图命令

```bash
mkdir -p $(pwd)/.ai-workspace/screenshots
PAGE={编号}
ls $(pwd)/.ai-workspace/screenshots/${PAGE}_*after*.png 2>/dev/null | xargs -r rm

# hdc 抓图(USB 调试)
hdc shell snapshot_display -f /data/local/tmp/screen.png
hdc file recv /data/local/tmp/screen.png \
  $(pwd)/.ai-workspace/screenshots/${PAGE}_after.png

# 立即 Read 抓到的图,与 design-truth 对比
```

设备未连接 → `hdc pair`(wifi 配对)或启用 USB 调试。

## §4 翻译规则(设计稿 → ArkUI)

### §4.1 布局容器

| 设计稿 | ArkUI |
|---|---|
| FRAME + layout=VERTICAL | `Column() { ... }` |
| FRAME + layout=HORIZONTAL | `Row() { ... }` |
| FRAME + layout=none | **`Stack({ alignContent: Alignment.TopStart }) { ... }`** |
| FRAME + 子项均等宽 | `Row() { ChildComponent().layoutWeight(1) }` |
| 网格 | `Grid() { ... }` 或 `GridRow() { GridCol() { ... } }` |

### §4.2 尺寸

| 设计稿 | ArkUI |
|---|---|
| FILL | `.width('100%')` / `.height('100%')` 或 `.layoutWeight(1)` |
| HUG | 不设 size(自然 fit) |
| FIXED N | `.width(N)` / `.height(N)`(默认 vp 单位)|

### §4.3 浮层定位(layout=none 子元素)

```typescript
Stack({ alignContent: Alignment.TopStart }) {
  // 主内容
  this.mainContent()

  // 左上角:left=18, top=18
  Image($r('app.media.ic_mute'))
    .width(40)
    .height(40)
    .position({ x: 18, y: 18 })

  // 右下角:right=18, bottom=152
  this.actionRail()
    .position({ x: '100%', y: '100%' })
    .markAnchor({ x: '100%', y: '100%' })
    .translate({ x: -18, y: -152 })
}
```

### §4.4 间距

| 设计稿 | ArkUI |
|---|---|
| itemSpacing=N | `Column({ space: N }) { ... }` / `Row({ space: N }) { ... }` |
| padding T/R/B/L | `.padding({ top: T, right: R, bottom: B, left: L })` |

### §4.5 对齐

| 设计稿 | ArkUI |
|---|---|
| primaryAxis=CENTER | `.justifyContent(FlexAlign.Center)` |
| primaryAxis=SPACE_BETWEEN | `.justifyContent(FlexAlign.SpaceBetween)` |
| counterAxis=CENTER | `.alignItems(HorizontalAlign.Center)` / `(VerticalAlign.Center)` |

### §4.6 视觉

| 设计稿 | ArkUI |
|---|---|
| fill 颜色 | `.backgroundColor(AppColors.xxx)` |
| stroke N px | `.border({ width: N, color: AppColors.xxx })` |
| cornerRadius N | `.borderRadius(N)` |
| cornerRadius 999 | `.borderRadius(999)`(组件需 width = height) |
| 图片背景 | `Image($r('app.media.xxx')).objectFit(ImageFit.Cover)` |
| gradient | `.linearGradient({ angle: 180, colors: [[#3CFF52, 0], [#38D9A8, 1]] })` |
| shadow | `.shadow({ radius: N, color: ..., offsetX: ..., offsetY: ... })` |

### §4.7 文字

| 设计稿 | ArkUI |
|---|---|
| TEXT | `Text("内容")` |
| fontSize N | `.fontSize(N)` |
| fontWeight 700 | `.fontWeight(FontWeight.Bold)` 或 `.fontWeight(700)` |
| fontWeight 600 | `.fontWeight(600)` |
| fontWeight 500 | `.fontWeight(FontWeight.Medium)` |
| fill 颜色 | `.fontColor(AppColors.xxx)` |
| letterSpacing 0.5 | `.letterSpacing(0.5)` |
| 大写 | `text.toUpperCase()` 在数据层 |
| lineHeight N | `.lineHeight(N)` |
| 自定义 font | `.fontFamily('Inter-Bold')` |

## §5 Step 0.5 / Step 5 Build + Install + 截图

```bash
# 构建 Debug HAP
./hvigorw assembleHap --mode debug
# Windows: hvigorw.bat assembleHap --mode debug

# 安装(USB 调试 或 wifi 配对后)
hdc install -r build/default/outputs/default/{hap_file}.hap

# 启动 Ability
hdc shell aa start -a {ability_name} -b {bundle_name}

# Log(按 bundle 过滤)
hdc shell hilog | grep {bundle_name} > .ai-workspace/diag/${TASK}-log.txt

# Lint
./hvigorw lint
```

## §6 Harmony 移动端专项规范

### §6.1 安全区处理

ArkUI 默认尊重系统安全区。`Navigation` 容器自动避让:

```typescript
@Entry
@Component
struct MyPage {
  build() {
    Navigation() {
      Column() {
        this.content()
      }
    }
    .title('页面标题')
    .mode(NavigationMode.Stack)
  }
}
```

特殊全屏(视频):反向延伸到安全区
```typescript
this.videoPlayer()
  .expandSafeArea([SafeAreaType.SYSTEM], [SafeAreaEdge.TOP, SafeAreaEdge.BOTTOM])
```

### §6.2 屏幕适配

ArkUI 默认 vp 单位,系统自动按 DPI 适配:

```typescript
// 比例保持
Image(url).objectFit(ImageFit.Cover).aspectRatio(9 / 16)

// 撑满
this.content().layoutWeight(1)
```

### §6.3 触控热区

```typescript
Image($r('app.media.ic_mute'))
  .width(40)
  .height(40)
  .padding(4)        // 视觉 40,触控 48
  .onClick(() => { /* ... */ })
```

或 `responseRegion` 扩展:
```typescript
Image(...)
  .responseRegion({ x: -4, y: -4, width: '100%+8', height: '100%+8' })
```

### §6.4 文字适配

`fp` 跟随系统字号缩放,`vp` 固定:

```typescript
// 结构性文字固定:
Text("Home").fontSize(9)  // 默认 vp

// 内容性文字可缩放:
Text("用户名称").fontSize($r('app.float.body1_fp'))  // 用 fp 资源
```

长文案截断:
```typescript
Text("长文本")
  .maxLines(1)
  .textOverflow({ overflow: TextOverflow.Ellipsis })
```

### §6.5 键盘处理

window 配置:
```typescript
windowStage.getMainWindow().then((window) => {
  window.setKeyboardAvoidMode(window.KeyboardAvoidMode.RESIZE)
})
```

### §6.6 状态栏样式

```typescript
// EntryAbility.ets
async onWindowStageCreate(windowStage: window.WindowStage) {
  const mainWindow = await windowStage.getMainWindow()
  await mainWindow.setSystemBarProperties({
    statusBarColor: '#00000000',
    statusBarContentColor: '#FFFFFF',  // 亮色文字(暗背景)
  })
}
```

### §6.7 手势

```typescript
.gesture(
  PanGesture()
    .onActionUpdate((event: GestureEvent) => { /* ... */ })
)
.gesture(
  LongPressGesture({ duration: 500 })
    .onAction(() => { /* ... */ })
)
```

手势冲突用 `priorityGesture` / `parallelGesture` 解决。

### §6.8 列表性能

```typescript
List({ space: 12 }) {
  ForEach(this.items, (item: Item) => {
    ListItem() {
      this.itemView(item)
    }
  }, (item: Item) => item.id.toString())  // keyGenerator 必填
}
.cachedCount(5)  // 缓存数,优化滚动
.onReachEnd(() => {
  // 触底加载更多
})
```

LazyForEach 用于超长列表:
```typescript
LazyForEach(this.dataSource, (item) => { ... })
```

### §6.9 图片加载

```typescript
Image(this.url)
  .alt($r('app.media.placeholder_dark'))  // 占位
  .objectFit(ImageFit.Cover)
  .borderRadius(8)
  .width(44).height(44)
```

第三方:`@ohos/ImageKnife` 等(若项目用)。

### §6.10 动效

```typescript
animateTo({ duration: 300, curve: Curve.Spring }, () => {
  this.scaleValue = isPressed ? 0.95 : 1.0
})

.scale({ x: this.scaleValue, y: this.scaleValue })
```

### §6.11 方向锁定

`module.json5`:
```json
{
  "module": {
    "abilities": [{
      "name": "EntryAbility",
      "orientation": "portrait"
    }]
  }
}
```

### §6.12 装饰器 / 状态管理(关键)

```typescript
@Component
struct MyView {
  @State count: number = 0    // 内部状态
  @Prop title: string = ''    // 父传入(单向)
  @Link items: Item[] = []    // 父传入(双向)
  @StorageLink('theme') theme: string = 'dark'  // 全局 storage

  build() { ... }
}
```

**装饰器顺序固定**:`@Entry @Component struct ...`,调换报错。

**`@State` 对象 / 数组 mutation 不触发刷新**:
```typescript
// ❌ 不刷新
this.items.push(newItem)

// ✅ 刷新
this.items = [...this.items, newItem]
```

## §7 图标资源映射 — Harmony 实施

Harmony 用 `resources/base/media/` 下 SVG / PNG。

放置:
```
resources/
└── base/
    ├── media/
    │   ├── ic_heart.svg
    │   ├── ic_share.svg
    │   └── ...
```

引用:
```typescript
Image($r('app.media.ic_heart'))
  .width(18)
  .height(18)
  .fillColor(AppColors.textPrimary)  // SVG 才支持 fillColor
```

通用 Lucide → Harmony media 命名约定:

| Lucide 名 | Harmony media |
|---|---|
| volume-x | `ic_volume_off` |
| heart | `ic_heart` |
| share-2 | `ic_share` |
| download | `ic_download` |
| sparkles | `ic_sparkles` |
| house | `ic_home` |
| search | `ic_search` |
| plus | `ic_plus` |
| bell | `ic_bell` |
| user | `ic_user` |
| play | `ic_play` |
| arrow-down | `ic_arrow_down` |
| arrow-right | `ic_arrow_right` |
| check | `ic_check` |
| chevron-right | `ic_chevron_right` |
| ellipsis | `ic_more` |
| trash-2 | `ic_trash` |
| folder | `ic_folder` |
| image | `ic_image` |

> **占位说明**:本 references/harmony.md 是 v0.2.1 初版。Harmony 工具链 + ArkUI API 更新较快,项目实际接入时根据 DevEco Studio 当前版本 + HarmonyOS API level 在 §0 + §5 / §6 调整命令版本。
