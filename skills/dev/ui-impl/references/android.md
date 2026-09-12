# ui-impl Android 参考(`mobile-android`)

> 配套 `../SKILL.md` 使用。本文件含 Android 特定 API / 命令 / 框架决策。

## §0 写代码必读 — 关联通用规则

Android 写代码顺序(从 `<docs-hub>/00_shared-rules/`):

```
编码原则集.md(Kotlin 习语 + Compose vs XML 13 场景决策矩阵)
  → 设计模式实现.md(GoF 23 + 现代模式 × Android 实现)
  → self-fix-boundary.md(改动边界)
  → data-sources.md(数据源真值)
  → 才动代码
```

**Android UI 框架决策(2026 项目当前默认)**:
- **80% 默认 Compose** — 新 feature / state-heavy 场景
- **15% XML + ViewBinding** — 视频 / WebView / 大列表(RecyclerView)
- **5% 混合栈** — Compose 嵌 AndroidView 包 SurfaceView

详 `<docs-hub>/编码原则集.md` Android UI 场景决策矩阵。

## §1 系统级问题 → AdaptiveBaseActivity 修复位置

| 问题症状 | 真正修复位置 |
|---|---|
| Title / 状态栏被遮挡 | `AdaptiveBaseActivity.fitConfig()` 设 `statusBar=true` |
| 内容延伸到系统导航栏下方 | `AdaptiveBaseActivity.fitConfig()` 设 `navBar=true` |
| 键盘弹出遮挡输入框 | `AdaptiveBaseActivity.fitConfig()` 设 `keyboard=true` + `onKeyboardChanged` |
| 刘海遮挡 | Application 全局设置(一般已自动处理) |
| 系统弹窗显示亮色 | Application `setDefaultNightMode(MODE_NIGHT_YES)` |
| 屏幕能横屏 | Manifest 加 `screenOrientation="portrait"` |
| 底栏被三键覆盖 | 底栏所在 Activity 的 `fitConfig.navBar=true` 或单独 `fitNavBar()` |
| 字号被系统放大 | 改 Typography Token 用 `dp` 而非 `sp` |
| Inter 字体没生效 | Application 加载字体文件 + `res/font/` |

如果当前页面继承了 `AdaptiveBaseActivity` 但状态栏还有问题:检查 `fitConfig()` 配置。如果没继承，
由 Agent 在任务范围内修正基类继承关系；若该系统级文件不在当前范围，生成精确 follow-up 任务，
不要让用户代改，也不要在当前页加临时 padding。

## §2 业务级 Token / API

| 业务概念 | Android API / 文件 |
|---|---|
| Token 文件路径 | `core-ui/src/main/java/.../ui/design/` |
| Colors Token | `Colors.kt`(`Colors.accentPrimary` / `Colors.bgCard` / 等)|
| Typography Token | `Typography.kt`(`Typography.body1` / 等)|
| Spacing Token | `Spacing.kt` / `Dimens.kt` |
| 文案多语言 | `res/values/strings.xml` / `res/values-en/strings.xml` / `res/values-zh-rCN/strings.xml` |
| Drawable 圆角 | `<corners android:radius="Ndp">` |
| Drawable 渐变 | `<gradient android:startColor / endColor / angle>` |
| Drawable 描边 | `<stroke android:width / color>` |
| 选中态样式 | `selector` drawable 或代码逻辑切换 |

## §3 截图 / 抓图命令

抓当前页截图:

```bash
# 1. 确保目录存在 + 抓取前清理旧版本
mkdir -p $(pwd)/.ai-workspace/screenshots
PAGE={编号}                                     # 如 <page-a>
ls $(pwd)/.ai-workspace/screenshots/${PAGE}_*after*.png 2>/dev/null | xargs -r rm

# 2. 确认设备 + 抓图
adb devices                                     # 确认设备在线
adb shell screencap -p /sdcard/snap.png         # 抓图
adb pull /sdcard/snap.png \
  $(pwd)/.ai-workspace/screenshots/${PAGE}_after.png

# 3. 立即 Read 抓到的图,与 design-truth 设计稿对比
```

**设备未连接** → Agent 先检查模拟器、无线调试和现有设备通道。若确实需要物理接线，只请求用户
完成“连接设备并启用 USB 调试”这一外部动作；不规定回复口令。设备状态变化后由 Agent 自动重探测
并继续抓图。

## §4 翻译规则(设计稿 → Android XML / Compose)

### §4.1 布局容器

XML 路径:

| 设计稿 | XML 实现 |
|---|---|
| FRAME + layout=VERTICAL | `LinearLayout(orientation=vertical)` |
| FRAME + layout=HORIZONTAL | `LinearLayout(orientation=horizontal)` |
| FRAME + layout=none | **`FrameLayout`**(子项用 layout_gravity + margin 绝对定位) |
| FRAME + 子项均等宽 / 高 | `LinearLayout` + 子项 `layout_weight="1"` |

Compose 路径(若使用):

| 设计稿 | Compose 实现 |
|---|---|
| FRAME + layout=VERTICAL | `Column { ... }` |
| FRAME + layout=HORIZONTAL | `Row { ... }` |
| FRAME + layout=none | `Box(contentAlignment = Alignment.Center) { ... }` |
| FRAME + 子项均等宽 | `Row { item.weight(1f) }` |

### §4.2 尺寸

| 设计稿 | XML | Compose |
|---|---|---|
| FILL | `0dp` + `weight=1` 或 `match_parent` | `Modifier.fillMaxWidth()` / `fillMaxHeight()` |
| HUG | `wrap_content` | 自然(不加 modifier) |
| FIXED N | `Ndp` | `Modifier.width(Ndp)` |

### §4.3 浮层定位(layout=none 子元素)

XML:
```xml
<FrameLayout>
    <View
        android:layout_gravity="start|top"
        android:layout_marginStart="18dp"
        android:layout_marginTop="18dp" />
    <View
        android:layout_gravity="end|bottom"
        android:layout_marginEnd="18dp"
        android:layout_marginBottom="152dp" />
</FrameLayout>
```

Compose:
```kotlin
Box(modifier = Modifier.fillMaxSize()) {
    SomeView(modifier = Modifier
        .align(Alignment.TopStart)
        .padding(start = 18.dp, top = 18.dp))
    AnotherView(modifier = Modifier
        .align(Alignment.BottomEnd)
        .padding(end = 18.dp, bottom = 152.dp))
}
```

### §4.4 间距

| 设计稿 | XML | Compose |
|---|---|---|
| itemSpacing=N(纵向) | 子项 `marginTop=Ndp`,首个不加 | `Column(verticalArrangement = Arrangement.spacedBy(Ndp))` |
| itemSpacing=N(横向) | 子项 `marginStart=Ndp`,首个不加 | `Row(horizontalArrangement = Arrangement.spacedBy(Ndp))` |
| padding T/R/B/L | 容器 `padding{Top|End|Bottom|Start}` | `Modifier.padding(top, end, bottom, start)` |

### §4.5 对齐

| 设计稿 | XML | Compose |
|---|---|---|
| primaryAxis=CENTER(横向) | `gravity=center_vertical` | `Row(verticalAlignment = Alignment.CenterVertically)` |
| primaryAxis=SPACE_BETWEEN | 用 Spacer View 或首尾不加 margin | `Row(horizontalArrangement = Arrangement.SpaceBetween)` |
| counterAxis=CENTER | 子项 `layout_gravity=center` | `Modifier.align(Alignment.Center)` |

### §4.6 视觉

| 设计稿 | XML | Compose |
|---|---|---|
| fill 颜色 | `android:background` 引 Colors Token | `Modifier.background(Colors.xxx)` |
| stroke N px | drawable shape `<stroke>` | `Modifier.border(Ndp, color)` |
| cornerRadius N | drawable shape `<corners android:radius>` | `Modifier.clip(RoundedCornerShape(Ndp))` |
| cornerRadius 999 | drawable shape `<corners android:radius="999dp">` | `Modifier.clip(CircleShape)` |
| 图片背景 | `ImageView` + `scaleType="centerCrop"` | `Image(painter, contentScale = ContentScale.Crop)` |

### §4.7 文字

| 设计稿 | XML | Compose |
|---|---|---|
| TEXT | `TextView` | `Text` |
| fontSize N | `textSize` 引 Typography | `style = AppTypography.xxx` |
| fontWeight 700 | `fontFamily="@font/inter_bold"` | `fontWeight = FontWeight.Bold` |
| fontWeight 600 | `fontFamily="@font/inter_semibold"` | `fontWeight = FontWeight.SemiBold` |
| fontWeight 500 | `fontFamily="@font/inter_medium"` | `fontWeight = FontWeight.Medium` |
| fill 颜色 | `textColor` 引 Colors | `color = Colors.xxx` |
| letterSpacing 0.5 | `letterSpacing="0.03"`(0.5px ÷ fontSize) | `letterSpacing = 0.03.em` |
| 大写 | `textAllCaps="true"` | `text.uppercase()` |

## §5 Step 0.5 / Step 5 Build + Install + 截图

```bash
# 编译安装(Debug)
./gradlew :app:assembleDebug
# Windows: gradlew.bat :app:assembleDebug

adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n {package}/.MainActivity

# 抓截图(基线 / 验证)
adb shell screencap -p > .ai-workspace/screenshots/${PAGE}_before.png
# ... 修复 + 重新 install + 重新启动 + 重新抓
adb shell screencap -p > .ai-workspace/screenshots/${PAGE}_after.png
```

## §6 Android 移动端专项规范

### §6.1 安全区处理

通过 `WindowInsetsCompat` 处理,**不使用硬编码 padding**:

```kotlin
WindowCompat.setDecorFitsSystemWindows(window, false)

ViewCompat.setOnApplyWindowInsetsListener(rootView) { view, insets ->
    val systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
    view.setPadding(systemBars.left, systemBars.top, systemBars.right, systemBars.bottom)
    insets
}
```

各区域规则:

| 区域 | 处理 |
|---|---|
| 状态栏 | 内容延伸下方(沉浸式),`isAppearanceLightStatusBars = false`(暗背景亮文字) |
| 导航栏(底部虚拟键)| 自定义底栏加 `navigationBars` inset paddingBottom |
| 刘海 / 挖孔屏 | `LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES` |
| 全屏页(首页视频)| 隐藏系统栏:`WindowInsetsControllerCompat.hide(...)` |
| 键盘弹出 | 监听 `WindowInsetsCompat.Type.ime()`,输入框区域自动上推 |

底栏安全区:
```xml
<FrameLayout
    android:fitsSystemWindows="false"
    android:paddingBottom="@{navigationBarInset}">
    <!-- 内层是设计稿的 95dp 底栏 -->
</FrameLayout>
```

### §6.2 屏幕适配

设计稿 402×874(约 393dp 宽,iPhone 尺寸)。Android 实际 360dp~412dp。

| 策略 | 实现 |
|---|---|
| 宽度自适应 | `match_parent` + `padding`,不写死宽度 |
| 比例保持 | `ConstraintLayout` + `app:layout_constraintDimensionRatio="9:16"` |
| 固定值转比例 | 设计稿 362px → 用 `match_parent` 减左右 padding(20dp) |
| 底栏固定高度 | 高度 62dp 固定,宽度撑满减 padding |
| 文字不截断 | 关键文字 `wrap_content`,长文案 `ellipsize="end"` + `maxLines` |

小屏适配(360dp 宽,Samsung A 系列):底栏 5 个 Tab 等分约 62dp 宽,CREATE 按钮 76dp → `min(76dp, 可用空间)`。

### §6.3 触控热区

最小 48×48dp(Material Design 标准):

```xml
<FrameLayout
    android:layout_width="48dp"
    android:layout_height="48dp"
    android:clickable="true">
    <ImageView
        android:layout_width="40dp"
        android:layout_height="40dp"
        android:layout_gravity="center" />
</FrameLayout>
```

### §6.4 文字适配 dp vs sp

- **dp(固定)**:底栏文字(9)、Tab 标签(13)、状态栏 — 结构性
- **sp(可缩放)**:正文、通知标题 / 摘要、任务标题 — 内容性

### §6.5 键盘处理

```xml
<activity android:windowSoftInputMode="adjustResize" />
```

输入框页用 `adjustResize`,无输入框页不设。

### §6.6 状态栏样式

```kotlin
WindowInsetsControllerCompat(window, window.decorView).apply {
    isAppearanceLightStatusBars = false   // 亮色图标 / 文字(暗背景)
    isAppearanceLightNavigationBars = false
}
```

### §6.7 手势冲突

| 冲突 | 处理 |
|---|---|
| 首页竖滑(ViewPager2)vs 系统返回 | ViewPager2 默认处理 |
| 左右切 Tab vs 视频区水平手势 | `ViewPager2.isUserInputEnabled` 控制 |
| 视频区下拉刷新 vs 视频区上下滑 | 视频区消费竖向手势时,禁用下拉刷新 |
| 底部弹窗拖动 vs 列表滚动 | `BottomSheetBehavior` + `NestedScrollView` |

### §6.8 列表性能

| 组件 | 实现 |
|---|---|
| 首页 Feed | `RecyclerView` + `ViewHolder` 复用 + 预加载 3 条 |
| 发现页瀑布流 | `StaggeredGridLayoutManager` + DiffUtil |
| 通知列表 | `RecyclerView` + DiffUtil |
| 任务中心 | `RecyclerView` + Paging3(cursor 分页) |

图片加载统一用 Coil:
```kotlin
imageView.load(url) {
    placeholder(R.drawable.placeholder_dark)
    error(R.drawable.placeholder_dark)
    crossfade(200)
}
```

### §6.9 动效

| 场景 | 实现 |
|---|---|
| 页面切换 | `overridePendingTransition` 或 Navigation Anim |
| 底部弹窗 | `BottomSheetDialogFragment` 默认动画 |
| 点赞缩放 | `ObjectAnimator` scaleX/Y 1.0→1.3→1.0 |
| Tab 切换 | 自定义 indicator + `ValueAnimator` 平移 |
| 列表加载 | `RecyclerView.ItemAnimator` 或 item alpha 动画 |
| 加载态 | `shimmer` 或 AlphaAnimation |

### §6.10 图片加载态

| 状态 | 表现 |
|---|---|
| 加载中 | 暗色占位 + shimmer 微光 |
| 加载成功 | crossfade 200ms 渐显 |
| 加载失败 | 暗色占位图(不显示错误图标) |
| 无图片 | 同加载失败,暗色占位 |

占位颜色 `Colors.bgCard`(#12161C)。

### §6.11 无障碍

```xml
<ImageView
    android:contentDescription="静音"
    android:importantForAccessibility="yes" />

<!-- 装饰性图片 -->
<ImageView
    android:importantForAccessibility="no" />
```

对比度 ≥ 4.5:1(WCAG AA)。

### §6.12 分割线

- 列表项之间:不用 `DividerItemDecoration`,用间距(`itemSpacing`)
- 设置页项之间:1dp 分割线,颜色 `Colors.borderDefault`(#1A202A)
- 区块之间:间距分隔(12~24dp),无线条

### §6.13 Toast / Snackbar

```kotlin
Snackbar.make(view, message, Snackbar.LENGTH_SHORT).apply {
    setBackgroundTint(Colors.bgSurface)
    setTextColor(Colors.textPrimary)
    setActionTextColor(Colors.accentPrimary)
    anchorView = bottomNavView  // 底栏上方
}.show()
```

### §6.14 弹窗 dim 背景

| 弹窗 | dim 颜色 | 圆角 |
|---|---|---|
| BottomSheetDialog | `#80000000` | 顶部 24dp |
| AlertDialog | `#80000000` | 16dp |
| 全屏 Dialog | 无 dim | 无 |

```xml
<style name="BottomSheetStyle" parent="Widget.MaterialComponents.BottomSheet">
    <item name="shapeAppearanceOverlay">@style/BottomSheetRounded</item>
</style>
<style name="BottomSheetRounded">
    <item name="cornerSizeTopLeft">24dp</item>
    <item name="cornerSizeTopRight">24dp</item>
</style>
```

### §6.15 Badge 角标

```kotlin
val badge = TextView(context).apply {
    text = if (count > 99) "99+" else count.toString()
    setTextColor(Colors.navActiveText)
    setBackgroundResource(R.drawable.bg_badge)
    textSize = 8f
    gravity = Gravity.CENTER
    minWidth = 16.dp
    height = 16.dp
    setPadding(4.dp, 0, 4.dp, 0)
}
```

### §6.16 空 / 加载 / 错误态统一结构

```xml
<ViewFlipper android:id="@+id/stateContainer">
    <include layout="@layout/state_loading" />  <!-- shimmer 骨架屏 -->
    <RecyclerView />                            <!-- 内容态 -->
    <include layout="@layout/state_empty" />    <!-- 插图 + 文案 + CTA -->
    <include layout="@layout/state_error" />    <!-- 文案 + Retry -->
</ViewFlipper>
```

骨架屏色:基底 `Colors.bgCard`(#12161C),光泽 `Colors.bgCardHover`(#171C24)。

### §6.17 多窗口 / 分屏(禁用)

```xml
<activity android:resizeableActivity="false" />
```

### §6.18 暗色主题防泄漏

```kotlin
AppCompatDelegate.setDefaultNightMode(AppCompatDelegate.MODE_NIGHT_YES)
```

```xml
<style name="AppTheme" parent="Theme.MaterialComponents.NoActionBar">
    <item name="colorSurface">@color/bgPrimary</item>
    <item name="android:windowBackground">@color/bgPrimary</item>
    <item name="android:navigationBarColor">@color/bgPrimary</item>
    <item name="bottomSheetDialogTheme">@style/BottomSheetDark</item>
</style>
```

## §7 图标资源映射 — Android 实施

Android 用 Vector Drawable(从 Lucide SVG 转换),放在 `res/drawable/`。

**drawable 不存在**:从 <https://lucide.dev/icons/> 下载 SVG,用 Android Studio Vector Asset 工具导入。

图标 tint 颜色:`ImageViewCompat.setImageTintList()` 或 XML `app:tint`。

通用 Lucide → Android 命名约定:

| Lucide 名 | Android Drawable |
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
| link | `ic_link` |
| mail | `ic_mail` |
| message-circle-more | `ic_message` |
| send | `ic_send` |
| trash-2 | `ic_trash` |
| folder | `ic_folder` |
| image | `ic_image` |
| corner-down-left | `ic_corner_down_left` |
