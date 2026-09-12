# ui-impl iOS 参考(`mobile-ios`)

> 配套 `../SKILL.md`。本文件含 iOS 特定 API / 命令 / 框架决策。

## §0 写代码必读

iOS 写代码顺序(从 `<docs-hub>/00_shared-rules/`):

```
编码原则集.md(Swift 习语优先级)
  → 设计模式实现.md(GoF 23 + 现代模式 × iOS 实现)
  → self-fix-boundary.md(改动边界)
  → data-sources.md(数据源真值)
  → 才动代码
```

**iOS UI 框架决策**:
- **SwiftUI 为主**(新 View / 业务页 / 列表)
- **UIKit 备用**(高频手势、复杂 NavigationController、特殊渲染如 SurfaceView)
- **TCA 全局**(Action 三分类、@Perception.Bindable + WithPerceptionTracking)

> ⚠️ **TCA 适用前提**
> 本 references/ios.md 的 §0 / §1 / §4 部分 / §8(TCA / SwiftUI / Perception tracking)假设项目使用 **The Composable Architecture(TCA)** 作为状态管理框架。**非 TCA iOS 项目**(纯 SwiftUI `@State` / `@Observable` / MVVM / VIPER 等)可跳过 TCA 相关章节,workflow 主线 + Token / 命令 / 验证 / 截图等仍适用。

详 `<docs-hub>/编码原则集.md` iOS 章节。

## §1 系统级问题 → adaptivePage / AdaptiveScaffold 修复位置

| 问题症状 | 修复位置 |
|---|---|
| Title / 状态栏被遮挡 | View 加 `.adaptivePage()` 或包在 `AdaptiveScaffold` 内 |
| 内容延伸到 Home Indicator 下方 | 同上 |
| 键盘弹出遮挡输入框 | `.adaptivePage(style: .form)` 自动键盘避让 |
| 刘海遮挡 | App 入口 SafeArea 默认 |
| 系统弹窗显示亮色 | App 入口 `.preferredColorScheme(.dark)` |
| 屏幕能横屏 | Info.plist `UISupportedInterfaceOrientations` 只保留 Portrait |
| 底栏被 Home Indicator 覆盖 | 用 `AdaptiveTabBar` 容器或 `.fitNavBar()` |
| 字号过大被系统放大 | AppTypography Token 用 `fixedSize` 替代 `Font.system` |
| Inter 字体没生效 | Info.plist `UIAppFonts` 注册 + Resources 加 .ttf |
| ZStack 浮层定位飘 | 用 `.stagePosition(.topLeading, padding:)` 修饰器 |

当前 View 没用 `.adaptivePage()` → 由 Agent 在任务范围内补上；若系统级容器不在当前范围，生成
精确 follow-up 任务，不让用户代改，也不要在当前 View 内加临时 SafeArea padding。

## §2 业务级 Token / API

| 业务概念 | iOS API / 文件 |
|---|---|
| Token 文件路径 | `Sources/CoreUI/DesignTokens/` |
| Colors Token | `AppColors.swift`(`AppColors.accentPrimary` 等)|
| Typography Token | `AppTypography.swift`(`AppTypography.body1` 等)|
| Spacing Token | `AppSpacing.swift` |
| 文案多语言 | `L10n.xxx` enum(由 SwiftGen 生成)/ `Localizable.strings` |
| Gradients | `AppGradients.swift`(协调端产出,Dev 不手造)|
| 选中态样式 | `ViewModifier` 或 `ButtonStyle` 切换 |

## §3 截图 / 抓图命令

```bash
# 1. 确保目录 + 清理
mkdir -p $(pwd)/.ai-workspace/screenshots
PAGE={编号}
ls $(pwd)/.ai-workspace/screenshots/${PAGE}_*after*.png 2>/dev/null | xargs rm 2>/dev/null

# 2. 确认模拟器启动 + 抓图
xcrun simctl list devices booted | head -3
xcrun simctl io booted screenshot \
  $(pwd)/.ai-workspace/screenshots/${PAGE}_after.png

# 真机:
# xcrun devicectl device snapshot --device <UDID>
# 或 Apple Devices.app 截图
```

模拟器未启动:`xcrun simctl boot "iPhone 17 Pro"` 启动。

**模拟器导航边界(团队约定)**:
- ✅ 只截当前可见页
- ❌ **禁用** `osascript` + AppleScript 自动 tap / swipe(需 Accessibility 权限,用户不开放)
- ❌ **禁用** `xcrun simctl ui ... tap`(不支持 tap element)
- **当前页不是目标页** → Agent 先尝试项目现有 deep link、UI test、launch argument 或导航脚本。
  确无自动入口且必须由人操作模拟器时，只说明要到达的页面和可观察终态；不规定固定回复。
  页面到达后由 Agent 自动重探测并继续截图。

## §4 翻译规则(设计稿 → SwiftUI / UIKit)

### §4.1 布局容器

SwiftUI 路径:

| 设计稿 | SwiftUI |
|---|---|
| FRAME + layout=VERTICAL | `VStack(spacing: N) { ... }` |
| FRAME + layout=HORIZONTAL | `HStack(spacing: N) { ... }` |
| FRAME + layout=none | **`ZStack(alignment: .topLeading) { ... }`** |
| FRAME + 子项均等宽 | `HStack { item.frame(maxWidth: .infinity) }` |

UIKit 路径:

| 设计稿 | UIKit |
|---|---|
| FRAME + layout=VERTICAL | `UIStackView(axis: .vertical, spacing: N)` |
| FRAME + layout=HORIZONTAL | `UIStackView(axis: .horizontal, spacing: N)` |
| FRAME + layout=none | `UIView` + manual `NSLayoutConstraint` |
| FRAME + 子项均等宽 | `UIStackView(distribution: .fillEqually)` |

### §4.2 尺寸

| 设计稿 | SwiftUI | UIKit |
|---|---|---|
| FILL | `.frame(maxWidth: .infinity)` / `maxHeight: .infinity` | `widthAnchor.constraint(equalTo: ...)` |
| HUG | 不设 frame(自然 fit) | intrinsic content size |
| FIXED N | `.frame(width: N)` / `.frame(height: N)` | `widthAnchor.constraint(equalToConstant: N)` |

### §4.3 浮层定位(layout=none 子元素)

```swift
ZStack(alignment: .topLeading) {
    mainContent

    // 左上角:left=18, top=18
    muteButton
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(.leading, 18)
        .padding(.top, 18)

    // 右下角:right=18, bottom=152
    actionRail
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomTrailing)
        .padding(.trailing, 18)
        .padding(.bottom, 152)
}
```

### §4.4 间距

| 设计稿 | SwiftUI |
|---|---|
| itemSpacing=N | `VStack(spacing: N)` / `HStack(spacing: N)` |
| padding T/R/B/L | `.padding(.top, T).padding(.trailing, R).padding(.bottom, B).padding(.leading, L)` |

### §4.5 对齐

| 设计稿 | SwiftUI |
|---|---|
| primaryAxis=CENTER | `Spacer()` 两端包裹 或 `.frame(alignment: .center)` |
| primaryAxis=SPACE_BETWEEN | `item1; Spacer(); item2` |
| counterAxis=CENTER | `VStack(alignment: .center)` / `HStack(alignment: .center)` |

### §4.6 视觉

| 设计稿 | SwiftUI |
|---|---|
| fill 颜色 | `.background(AppColors.xxx)` |
| stroke N px | `.overlay(RoundedRectangle(cornerRadius: N).stroke(AppColors.xxx, lineWidth: N))` |
| cornerRadius N | `.clipShape(RoundedRectangle(cornerRadius: N))` |
| cornerRadius 999 | `.clipShape(Capsule())` |
| 图片背景 | `AsyncImage().resizable().aspectRatio(contentMode: .fill).clipped()` 或 Kingfisher `KFImage` |

### §4.7 文字

| 设计稿 | SwiftUI |
|---|---|
| TEXT | `Text("内容")` |
| fontSize N, weight 700 | `.font(.custom("Inter-Bold", size: N))` 或 `AppTypography.xxx` |
| fontSize N, weight 600 | `.font(.custom("Inter-SemiBold", size: N))` |
| fontSize N, weight 500 | `.font(.custom("Inter-Medium", size: N))` |
| fill 颜色 | `.foregroundColor(AppColors.xxx)` |
| letterSpacing 0.5 | `.tracking(0.5)` |
| 大写 | `.textCase(.uppercase)` 或 `text.uppercased()` |
| lineHeight N | `.lineSpacing(N - fontSize)` |

## §5 Step 0.5 / Step 5 Build + Install + 截图

```bash
# 编译(模拟器,纯逻辑可)
xcodebuild -project <project>.xcodeproj -scheme <project> \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -skipMacroValidation build

# 真机 build(必加 ENABLE_DEBUG_DYLIB=NO 防 SIGTRAP)
xcodebuild -project <project>.xcodeproj -scheme <project> \
  -destination 'platform=iOS,id=<UDID>' \
  -allowProvisioningUpdates -skipMacroValidation \
  ENABLE_DEBUG_DYLIB=NO \
  clean build

# Install(devicectl,Xcode 26.4.1 bug 时切 ios-deploy):
xcrun devicectl device install app --device <UDID> "$APP_PATH"
# 或: ios-deploy --id <UDID> --bundle "$APP_PATH" --no-wifi --justlaunch

# Launch:
xcrun devicectl device process launch --device <UDID> ai.<project>.app

# Log(idevicesyslog 兼容性更稳):
idevicesyslog -u <UDID>

# 截图:
xcrun simctl io booted screenshot path/to.png  # 模拟器
xcrun devicectl device captureScreenshot --device <UDID> path/to.png  # 真机
```

完工三步 + install 到真机(`/assign` skill §5 verify strict 已含):
```bash
APP_PATH=$(find ~/Library/Developer/Xcode/DerivedData/<project>-*/Build/Products/Debug-iphoneos \
    -maxdepth 1 -name "<project>.app" -exec stat -f "%m %N" {} \; | sort -rn | head -1 | cut -d' ' -f2-)
ios-deploy --id <UDID> --bundle "$APP_PATH" --justlaunch
```

## §6 iOS 移动端专项规范

### §6.1 安全区处理

SafeAreaInsets 自动处理,SwiftUI 默认尊重:

```swift
// 全屏视频:延伸到安全区
videoPlayer.ignoresSafeArea()

// 列表页:默认在安全区内
VStack { content }  // 不需要额外处理

// 底栏:固定底部含安全区
VStack {
    mainContent
    customTabBar.padding(.bottom, 0)
}
.ignoresSafeArea(edges: .bottom)  // 底栏背景延伸到 Home Indicator 下方
```

UIKit:
```swift
view.insetsLayoutMarginsFromSafeArea = false  // 全屏视频
customTabBar.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor)
tabBarBackground.bottomAnchor.constraint(equalTo: view.bottomAnchor)
```

底栏关键:**内容区**在安全区内,**背景色**延伸到屏幕底部。

### §6.2 屏幕适配

设计稿 402×874 ≈ iPhone 14/15 393pt 宽。

| 设备 | 屏幕宽 | 注意 |
|---|---|---|
| iPhone SE 3 | 375pt | 底栏 5 Tab 较挤 |
| iPhone 14/15 | 393pt | 设计稿基准 |
| iPhone 14/15 Plus | 430pt | 更宽,padding 不变 |
| iPhone 15 Pro Max | 430pt | 同上 |

`.frame(maxWidth: .infinity)` + `.padding` 自适应。视频区 `.aspectRatio(9/16, contentMode: .fit)`。

### §6.3 触控热区

最小 44×44pt(Apple HIG):

```swift
Button(action: { }) {
    Image(systemName: "speaker.slash").frame(width: 40, height: 40)
}
.frame(width: 44, height: 44)
.contentShape(Rectangle())
```

### §6.4 文字适配

| 规则 | 实现 |
|---|---|
| 不写死宽度 | `maxWidth` |
| 长文案截断 | `.lineLimit(1).truncationMode(.tail)` |
| 全大写 | `.textCase(.uppercase)` |
| Dynamic Type 支持 | 正文 `AppTypography.body1`(允许缩放)|
| 固定大小 | 底栏 / Tab 用 `.font(.custom("Inter", fixedSize: 9))` |

### §6.5 键盘处理

```swift
TextField("Prompt", text: $prompt)
    .scrollDismissesKeyboard(.interactively)

VStack {
    ScrollView { content }
    createButton
}
.ignoresSafeArea(.keyboard)  // 按需:键盘不推底部按钮
```

### §6.6 状态栏样式

```swift
.preferredColorScheme(.dark)  // SwiftUI 全局

override var preferredStatusBarStyle: UIStatusBarStyle { .lightContent }  // UIKit
```

Info.plist:
- `UIViewControllerBasedStatusBarAppearance = YES`
- `UIStatusBarStyle = UIStatusBarStyleLightContent`

### §6.7 手势冲突

| 冲突 | 处理 |
|---|---|
| 首页竖滑 vs 系统返回 | UIPageViewController 竖向不冲突 |
| 左右切 Tab vs 视频区水平 | `.gesture(DragGesture().onChanged { })` 优先级 |
| 底部弹窗拖动 vs 内部 ScrollView | `.presentationDetents` |
| 返回手势 vs 横向 ScrollView | `interactivePopGestureRecognizer` 优先 |

### §6.8 列表性能

| 组件 | 实现 |
|---|---|
| 首页 Feed | UIPageViewController + UIViewController 复用池 |
| 发现页瀑布流 | UICollectionView + CompositionalLayout + DiffableDataSource |
| 通知列表 | SwiftUI `List` 或 `LazyVStack` + `.onAppear` 懒加载 |
| 任务中心 | LazyVStack + 触底分页 |

图片加载用 Kingfisher:
```swift
KFImage(url)
    .placeholder { Color(AppColors.bgCard) }
    .fade(duration: 0.2)
    .resizable()
    .aspectRatio(contentMode: .fill)
```

### §6.9 动效

| 场景 | 实现 |
|---|---|
| 页面切换 | UINavigationController 默认 |
| 底部弹窗 | `.sheet` / `.presentationDetents([.medium, .large])` |
| 点赞 | `.scaleEffect` + `withAnimation(.spring())` |
| Tab 切换 | `.matchedGeometryEffect` 或 `withAnimation(.easeInOut(duration: 0.2))` |
| 列表加载 | `.transition(.opacity)` |
| 加载态 | 自定义 `ShimmerModifier` |

### §6.10 图片加载态

| 状态 | 表现 |
|---|---|
| 加载中 | 暗色占位 `AppColors.bgCard` + shimmer |
| 加载成功 | fade 200ms 渐显 |
| 加载失败 | 暗色占位(不显示错误图标) |

### §6.11 无障碍

```swift
.accessibilityLabel("静音")
.accessibilityHidden(true)   // 装饰性图片
.accessibilitySortPriority()  // VoiceOver 顺序
.dynamicTypeSize(.large ... .accessibility3)  // 限制范围
```

对比度 ≥ 4.5:1。

### §6.12 方向锁定

```swift
func application(_ application: UIApplication,
    supportedInterfaceOrientationsFor window: UIWindow?) -> UIInterfaceOrientationMask {
    return .portrait
}
```

Info.plist:`UISupportedInterfaceOrientations` 只保留 `UIInterfaceOrientationPortrait`。

### §6.13 按压 / 点击反馈

```swift
struct PressableButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .opacity(configuration.isPressed ? 0.6 : 1.0)
            .animation(.easeInOut(duration: 0.1), value: configuration.isPressed)
    }
}

struct ScaleButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.95 : 1.0)
            .animation(.spring(response: 0.2), value: configuration.isPressed)
    }
}
```

### §6.14 滚动行为

```swift
ScrollView(showsIndicators: false) { content }

List { items }.refreshable { await store.send(.refresh).finish() }
```

### §6.15 视频叠加层

```swift
ZStack(alignment: .bottom) {
    videoPlayer
    LinearGradient(
        colors: [.clear, Color.black.opacity(0.5)],
        startPoint: .top, endPoint: .bottom
    )
    .frame(height: 200)
    .allowsHitTesting(false)
}
```

### §6.16 图片裁剪

| 场景 | 实现 |
|---|---|
| 头像 | `.clipShape(Circle())` |
| 视频封面 | `.aspectRatio(contentMode: .fill).clipped()` + 容器圆角 |
| 通知缩略图 | `.fill` + `.clipShape(RoundedRectangle(cornerRadius: 8))` |
| 模板 / 作品卡 | `.fill` + `.cornerRadius(12)` |
| 大图 | `.aspectRatio(contentMode: .fit)` |

## §7 图标资源映射 — iOS 实施

iOS 用 SF Symbol 或 Asset Catalog 内的 Lucide PDF 矢量。

- **优先 SF Symbol**(若 SF Symbol 库有等价图标)
- **次选 Lucide PDF**:协调端从 lucide.dev 下载 SVG → 转 PDF → 放 `Sources/CoreUI/Resources/Assets.xcassets/`

图标 tint:
```swift
Image("iconShare")
    .foregroundColor(AppColors.textPrimary)  // SwiftUI

uiImage.withRenderingMode(.alwaysTemplate)  // UIKit
imageView.tintColor = AppColors.textPrimary.uiColor
```

通用 Lucide → iOS asset 命名约定:

| Lucide 名 | iOS Asset / SF Symbol |
|---|---|
| volume-x | `iconVolumeOff` 或 `speaker.slash` |
| heart | `iconHeart` 或 `heart` |
| share-2 | `iconShare` 或 `square.and.arrow.up` |
| download | `iconDownload` 或 `arrow.down.circle` |
| sparkles | `iconSparkles` 或 `sparkles` |
| house | `iconHome` 或 `house` |
| search | `iconSearch` 或 `magnifyingglass` |
| plus | `iconPlus` 或 `plus` |
| bell | `iconBell` 或 `bell` |
| user | `iconUser` 或 `person` |
| play | `iconPlay` 或 `play.fill` |
| arrow-down | `iconArrowDown` 或 `arrow.down` |
| arrow-right | `iconArrowRight` 或 `arrow.right` |
| check | `iconCheck` 或 `checkmark` |
| chevron-right | `iconChevronRight` 或 `chevron.right` |
| ellipsis | `iconMore` 或 `ellipsis` |
| trash-2 | `iconTrash` 或 `trash` |
| folder | `iconFolder` 或 `folder` |

## §8 TCA / SwiftUI 专项注意点

> ⚠️ **本节仅适用 TCA 项目**。非 TCA(纯 SwiftUI `@State` / MVVM / VIPER 等)项目跳过本节,Token / 命令 / 验证步骤等其他章节不受影响。

### Perception tracking 配对(iOS 16+ 兼容)

```swift
struct FooView: View {
    @Perception.Bindable var store: StoreOf<FooFeature>
    var body: some View {
        WithPerceptionTracking {
            // body 内容
        }
    }
}
```

漏 `WithPerceptionTracking` 时 iOS 16 上 state 变化不重渲 → 反模式 §3.x。

### Action 三分类

- **View Action** 可 `.run`(网络 / 持久化 / 副作用)
- **Result Action** 只 `.none` 或 `.send(.delegate)`
- **Delegate Action** 父 Reducer 处理后 `.none`

### 长按菜单(项目契约)

iOS 必须 `.confirmationDialog(titleVisibility: .visible)`,**禁用 `.contextMenu`**(契约 §4.1)。
