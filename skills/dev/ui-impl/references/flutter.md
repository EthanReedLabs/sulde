# ui-impl Flutter 参考(`mobile-flutter`)

> 配套 `../SKILL.md`。本文件含 Flutter 特定 API / 命令 / 框架决策。

## §0 写代码必读

Flutter 写代码顺序(从 `<docs-hub>/00_shared-rules/`):

```
编码原则集.md(Dart 习语 + 状态管理选择)
  → 设计模式实现.md(InheritedWidget / Riverpod / Bloc 模式)
  → self-fix-boundary.md
  → data-sources.md
  → 才动代码
```

**Flutter 决策**:
- 状态管理:Riverpod / Bloc / Provider — 项目特定,见 `.sulde-config.yaml` 或 README
- 路由:go_router / auto_route
- 平台目标:Android + iOS(同 codebase)

## §1 系统级问题 → SafeArea / MediaQuery 修复位置

| 问题症状 | 修复位置 |
|---|---|
| 状态栏 / 顶部被遮挡 | `Scaffold(appBar: AppBar(...))` 或包 `SafeArea(top: true)` |
| 内容延伸到 Home Indicator | `SafeArea(bottom: true)` |
| 键盘弹出遮挡输入框 | `Scaffold(resizeToAvoidBottomInset: true)`(默认) |
| 系统弹窗显示亮色 | `MaterialApp(themeMode: ThemeMode.dark)` |
| 屏幕能横屏 | `SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp])` |
| 字号被系统放大 | `MediaQuery.copyWith(textScaleFactor: 1.0)` 强制不缩放 |

## §2 业务级 Token / API

| 业务概念 | Flutter API |
|---|---|
| Token 文件路径 | `lib/core_ui/design_tokens/` |
| Colors Token | `AppColors.dart`(`AppColors.accentPrimary` 等)|
| Typography Token | `AppTypography.dart`(`AppTypography.body1` TextStyle)|
| Spacing Token | `AppSpacing.dart` |
| 文案多语言 | `flutter_localizations` + `intl` + `.arb` 文件 |
| Gradients | `AppGradients.dart`(`AppGradients.highlightCard` LinearGradient)|

## §3 截图 / 抓图命令

```bash
mkdir -p $(pwd)/.ai-workspace/screenshots
PAGE={编号}
ls $(pwd)/.ai-workspace/screenshots/${PAGE}_*after*.png 2>/dev/null | xargs -r rm

# Flutter screenshot 命令(需 app 已 run 状态)
flutter screenshot --out $(pwd)/.ai-workspace/screenshots/${PAGE}_after.png

# Android 真机后备(若 flutter screenshot 不工作):
adb shell screencap -p > $(pwd)/.ai-workspace/screenshots/${PAGE}_after.png

# iOS 模拟器后备:
xcrun simctl io booted screenshot $(pwd)/.ai-workspace/screenshots/${PAGE}_after.png
```

## §4 翻译规则(设计稿 → Flutter Widget)

### §4.1 布局容器

| 设计稿 | Flutter Widget |
|---|---|
| FRAME + layout=VERTICAL | `Column(children: [...])` |
| FRAME + layout=HORIZONTAL | `Row(children: [...])` |
| FRAME + layout=none | **`Stack(children: [...])`** + `Positioned` 子项 |
| FRAME + 子项均等宽 | `Row(children: [Expanded(...)])` |

### §4.2 尺寸

| 设计稿 | Flutter |
|---|---|
| FILL | `Expanded(child: ...)` 或 `SizedBox.expand` |
| HUG | 不设 size(自然 fit) |
| FIXED N | `SizedBox(width: N, height: N, child: ...)` |

### §4.3 浮层定位(layout=none 子元素)

```dart
Stack(
  children: [
    mainContent,
    // 左上角:left=18, top=18
    Positioned(
      left: 18, top: 18,
      child: muteButton,
    ),
    // 右下角:right=18, bottom=152
    Positioned(
      right: 18, bottom: 152,
      child: actionRail,
    ),
  ],
)
```

### §4.4 间距

| 设计稿 | Flutter |
|---|---|
| itemSpacing=N | `SizedBox(height: N)` / `(width: N)` 子项之间 — 或 `Wrap(spacing: N)` |
| padding T/R/B/L | `Padding(padding: EdgeInsets.fromLTRB(L, T, R, B), child: ...)` |

### §4.5 对齐

| 设计稿 | Flutter |
|---|---|
| primaryAxis=CENTER | `MainAxisAlignment.center` |
| primaryAxis=SPACE_BETWEEN | `MainAxisAlignment.spaceBetween` |
| counterAxis=CENTER | `CrossAxisAlignment.center` |

### §4.6 视觉

| 设计稿 | Flutter |
|---|---|
| fill 颜色 | `Container(color: AppColors.xxx)` 或 `decoration: BoxDecoration(color: ...)` |
| stroke N px | `BoxDecoration(border: Border.all(width: N, color: ...))` |
| cornerRadius N | `BoxDecoration(borderRadius: BorderRadius.circular(N))` |
| cornerRadius 999 | `ClipOval` 或 `borderRadius: BorderRadius.circular(999)` |
| 图片背景 | `Image.network(url, fit: BoxFit.cover)` 或 `CachedNetworkImage` |
| gradient | `BoxDecoration(gradient: LinearGradient(...))` |

### §4.7 文字

| 设计稿 | Flutter |
|---|---|
| TEXT | `Text("内容", style: AppTypography.xxx)` |
| fontSize N, weight 700 | `TextStyle(fontFamily: 'Inter', fontWeight: FontWeight.w700, fontSize: N)` |
| fill 颜色 | `style: TextStyle(color: AppColors.xxx)` |
| letterSpacing 0.5 | `letterSpacing: 0.5` |
| 大写 | `text.toUpperCase()` |
| lineHeight N | `height: N / fontSize` |

## §5 Step 0.5 / Step 5 Build + Install + 截图

```bash
# 环境验证
flutter doctor

# Debug build (Android)
flutter build apk --debug
flutter install                              # 装到连接的设备

# Release build (perf 测试)
flutter run --release

# Log
flutter logs > .ai-workspace/diag/${TASK}-log.txt

# Lint
flutter analyze
dart format --set-exit-if-changed lib/
```

**Hot reload ≠ verify**:§5 verify 必跑 `flutter run --release`,不能仅靠 hot reload(state 残留会掩盖 crash)。

## §6 Flutter 移动端专项规范

### §6.1 安全区处理

```dart
Scaffold(
  body: SafeArea(
    top: true,         // 状态栏避让
    bottom: false,     // 底栏自行处理 Home Indicator
    child: content,
  ),
)
```

### §6.2 屏幕适配

```dart
// 媒体查询拿屏幕尺寸
final size = MediaQuery.of(context).size;

// 比例保持
AspectRatio(aspectRatio: 9 / 16, child: videoPlayer)

// 撑满
Expanded(child: content)
```

### §6.3 触控热区

```dart
GestureDetector(
  behavior: HitTestBehavior.opaque,  // 整个区域可点击
  onTap: () { },
  child: SizedBox(width: 48, height: 48, child: child),
)
```

### §6.4 文字适配

```dart
// 防系统字号缩放
MediaQuery(
  data: MediaQuery.of(context).copyWith(textScaleFactor: 1.0),
  child: child,
)

// 长文案截断
Text("长文本", maxLines: 1, overflow: TextOverflow.ellipsis)
```

### §6.5 键盘处理

`Scaffold(resizeToAvoidBottomInset: true)` 默认开启,自动避让。

### §6.6 状态栏样式

```dart
// 在 main.dart
SystemChrome.setSystemUIOverlayStyle(SystemUiOverlayStyle(
  statusBarColor: Colors.transparent,
  statusBarIconBrightness: Brightness.light,  // 亮色图标(暗背景)
));
```

### §6.7 列表性能

```dart
// 用 ListView.builder 避免一次性 build 所有 item
ListView.builder(
  itemCount: items.length,
  itemBuilder: (ctx, i) => ItemWidget(item: items[i]),
)

// 大列表加 cacheExtent + RepaintBoundary
ListView.builder(
  cacheExtent: 500,
  itemBuilder: (ctx, i) => RepaintBoundary(child: ItemWidget(item: items[i])),
)
```

### §6.8 图片加载

```dart
// CachedNetworkImage 推荐(替代 Image.network):
CachedNetworkImage(
  imageUrl: url,
  placeholder: (ctx, url) => Container(color: AppColors.bgCard),
  errorWidget: (ctx, url, e) => Container(color: AppColors.bgCard),
  fadeInDuration: Duration(milliseconds: 200),
)
```

### §6.9 动效

```dart
// 缩放动效
AnimatedContainer(
  duration: Duration(milliseconds: 200),
  transform: Matrix4.identity()..scale(isPressed ? 0.95 : 1.0),
  child: button,
)

// Hero 动画
Hero(tag: 'avatar', child: avatarImage)
```

### §6.10 方向锁定

```dart
// main() 入口
WidgetsFlutterBinding.ensureInitialized();
SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]);
```

### §6.11 跨平台差异点

Flutter 同 codebase 双端运行,以下场景**必须双端 verify**:

- Platform channel(MethodChannel / EventChannel)— 改动后 Android + iOS 都跑
- 字体渲染(Android 系统字体 vs iOS 自带字体)
- 滚动行为(Android `OverScroll` 蓝光 vs iOS `Bouncing`)
- 触觉反馈(`HapticFeedback.lightImpact` 双端实现不同)
- 状态栏 / 安全区(Android 三键 vs iOS Home Indicator)

handoff `§ verify` 必含双端 build 证据。

### §6.12 Null safety 红线

避免 `!` 强解包(网络 / platform channel 来的数据)。用:

```dart
// ✅ 安全
final value = data?.field ?? defaultValue;

// ❌ 危险
final value = data!.field;
```

## §7 图标资源映射 — Flutter 实施

Flutter 用 `flutter_svg` 加载 Lucide SVG,或用项目 Icon Font 包。

放置:`assets/icons/{name}.svg` + `pubspec.yaml` declare。

通用 Lucide → Flutter asset 命名约定:

```dart
// asset
SvgPicture.asset(
  'assets/icons/heart.svg',
  width: 18,
  colorFilter: ColorFilter.mode(AppColors.textPrimary, BlendMode.srcIn),
)

// icon font(若项目用 flutter_icons 包)
Icon(LucideIcons.heart, size: 18, color: AppColors.textPrimary)
```

| Lucide 名 | Flutter asset / IconData |
|---|---|
| volume-x | `assets/icons/volume_x.svg` / `LucideIcons.volumeX` |
| heart | `assets/icons/heart.svg` / `LucideIcons.heart` |
| share-2 | `assets/icons/share_2.svg` / `LucideIcons.share2` |
| download | `assets/icons/download.svg` / `LucideIcons.download` |
| sparkles | `assets/icons/sparkles.svg` / `LucideIcons.sparkles` |
| house | `assets/icons/house.svg` / `LucideIcons.house` |
| search | `assets/icons/search.svg` / `LucideIcons.search` |
| plus | `assets/icons/plus.svg` / `LucideIcons.plus` |
| bell | `assets/icons/bell.svg` / `LucideIcons.bell` |
| user | `assets/icons/user.svg` / `LucideIcons.user` |

> **占位说明**:本 references/flutter.md 是 v0.2.1 初版,主要工作流 / 翻译规则已完整。项目实际接入 Flutter 时,根据采用的 state 库(Riverpod / Bloc / Provider 等)在 §0 + §2 加项目特定 conventions。如发现遗漏的细节,提 PR 完善。
