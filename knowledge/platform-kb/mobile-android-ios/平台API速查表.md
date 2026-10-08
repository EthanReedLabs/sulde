---
doc_id: "platform-kb/mobile-android-ios/平台API速查表"
container: platform-kb
platform: cross
summary: "适配场景的标准代码片段，写代码时直接复制粘贴。"
---

# 平台 API 速查表

> 适配场景的标准代码片段，写代码时直接复制粘贴。
> Android 和 iOS 并排，覆盖移动端常见场景。

## 一、安全区处理

### 1.1 Application/App 级全局配置

**Android** — Application.onCreate:
```kotlin
class ExampleApp : Application() {
    override fun onCreate() {
        super.onCreate()
        // 全局暗色主题防泄漏
        AppCompatDelegate.setDefaultNightMode(AppCompatDelegate.MODE_NIGHT_YES)
    }
}
```

AndroidManifest.xml:
```xml
<application
    android:name=".ExampleApp"
    android:theme="@style/AppTheme">
    <activity
        android:screenOrientation="portrait"
        android:configChanges="orientation|screenSize|keyboardHidden" />
</application>
```

**iOS** — App 入口:
```swift
@main struct ExampleApp: App {
    var body: some Scene {
        WindowGroup {
            RootView()
                .preferredColorScheme(.dark)  // 全局暗色
        }
    }
}
```

Info.plist:
```xml
<key>UISupportedInterfaceOrientations</key>
<array>
    <string>UIInterfaceOrientationPortrait</string>
</array>
<key>UIViewControllerBasedStatusBarAppearance</key>
<true/>
```

### 1.2 Activity/ViewController 基类

**Android:**
```kotlin
abstract class AdaptiveBaseActivity : AppCompatActivity() {
    protected open fun fitConfig(): FitConfig = FitConfig(statusBar = true)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowInsetsControllerCompat(window, window.decorView).apply {
            isAppearanceLightStatusBars = false
        }
    }

    override fun setContentView(view: View) {
        super.setContentView(view)
        applyFitConfig(view)
    }
}
```

**iOS (UIKit):**
```swift
open class AdaptiveViewController: UIViewController {
    open override var preferredStatusBarStyle: UIStatusBarStyle { .lightContent }
    open override var prefersHomeIndicatorAutoHidden: Bool { false }
    open override var supportedInterfaceOrientations: UIInterfaceOrientationMask { .portrait }
}
```

**iOS (SwiftUI):**
```swift
someView
    .adaptivePage()                    // 标准页面
    .adaptivePage(style: .fullscreen)  // 全屏（首页）
    .adaptivePage(style: .form)        // 表单（自动键盘避让）
```

### 1.3 状态栏避让

**Android:**
```kotlin
// 方式 1：基类自动处理
override fun fitConfig() = FitConfig(statusBar = true)

// 方式 2：View 扩展
view.fitStatusBar()

// 方式 3：手动（不推荐）
ViewCompat.setOnApplyWindowInsetsListener(view) { v, insets ->
    val top = insets.getInsets(WindowInsetsCompat.Type.statusBars()).top
    v.setPadding(v.paddingLeft, top, v.paddingRight, v.paddingBottom)
    insets
}
```

**iOS (SwiftUI):**
```swift
// SwiftUI 默认就尊重安全区，不需要特殊处理
VStack { ... }

// 如果需要忽略（如全屏视频）
.ignoresSafeArea()
```

### 1.4 底部导航栏/Home Indicator 避让

**Android:**
```kotlin
// 方式 1：基类
override fun fitConfig() = FitConfig(navBar = true)

// 方式 2：View 扩展
bottomNavWrapper.fitNavBar()
```

**iOS (SwiftUI):**
```swift
// 自定义底栏：内容在安全区内，背景延伸到屏幕底部
CustomTabBar()
    .background(
        ThemeThemeColors.navBar
            .ignoresSafeArea(edges: .bottom)
    )
```

### 1.5 键盘避让

**Android:**
```kotlin
// Activity 基类
override fun fitConfig() = FitConfig(keyboard = true)
override fun onKeyboardChanged(imeHeight: Int, visible: Boolean) {
    // 响应键盘变化（如推按钮）
    binding.createButton.translationY = if (visible) -imeHeight.toFloat() else 0f
}

// AndroidManifest.xml
<activity android:windowSoftInputMode="adjustResize" />
```

**iOS:**
```swift
// SwiftUI — 自动处理
TextField("Prompt", text: $prompt)
    .scrollDismissesKeyboard(.interactively)  // iOS 16+ 下滑收起

// 输入框自动上推
ScrollView {
    ... content ...
    TextField(...).id("input")
}

// 按需忽略键盘顶起底栏
.ignoresSafeArea(.keyboard, edges: .bottom)
```

## 二、触控热区扩展

**Android** — 最小 48×48dp:
```xml
<!-- 扩展触控区但不改变视觉 -->
<FrameLayout
    android:layout_width="48dp"
    android:layout_height="48dp"
    android:clickable="true"
    android:foreground="?selectableItemBackgroundBorderless">
    <ImageView
        android:layout_width="40dp"
        android:layout_height="40dp"
        android:layout_gravity="center" />
</FrameLayout>
```

**iOS** — 最小 44×44pt:
```swift
Button(action: {}) {
    Image(systemName: "speaker.slash")
        .frame(width: 40, height: 40)
}
.frame(width: 44, height: 44)
.contentShape(Rectangle())  // 整个 44×44 可点击
```

## 三、滚动行为

**Android** — 去掉蓝色过度滚动:
```xml
<RecyclerView android:overScrollMode="never" />
<ViewPager2 android:overScrollMode="never" />
```

**iOS** — 隐藏滚动条:
```swift
ScrollView(.vertical, showsIndicators: false) { ... }
```

## 四、下拉刷新

**Android:**
```xml
<androidx.swiperefreshlayout.widget.SwipeRefreshLayout
    android:id="@+id/swipe_refresh">
    <RecyclerView ... />
</SwipeRefreshLayout>
```

```kotlin
binding.swipeRefresh.apply {
    setColorSchemeColors(ThemeColors.accentPrimary)
    setProgressBackgroundColorSchemeColor(ThemeColors.bgCard)
    setOnRefreshListener { viewModel.refresh() }
}
```

**iOS:**
```swift
List { items }
    .refreshable {
        await store.send(.refresh).finish()
    }
```

## 五、按压反馈

**Android** — Ripple:
```xml
<!-- 图标按钮：圆形水波纹 -->
<ImageView android:background="?selectableItemBackgroundBorderless" />

<!-- 卡片：矩形水波纹 -->
<MaterialCardView android:foreground="?selectableItemBackground" />
```

**iOS** — 自定义 ButtonStyle:
```swift
struct PressableStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .opacity(configuration.isPressed ? 0.6 : 1.0)
            .animation(.easeInOut(duration: 0.1), value: configuration.isPressed)
    }
}

Button(action: {}) { ... }.buttonStyle(PressableStyle())
```

## 六、图片加载

**Android (Coil):**
```kotlin
imageView.load(url) {
    placeholder(ColorDrawable(ThemeColors.bgCard))
    error(ColorDrawable(ThemeColors.bgCard))
    crossfade(200)
    transformations(RoundedCornersTransformation(12f.dp))
}
```

**iOS (Kingfisher):**
```swift
KFImage(url)
    .placeholder { ThemeThemeColors.bgCard }
    .fade(duration: 0.2)
    .resizable()
    .aspectRatio(contentMode: .fill)
    .cornerRadius(12)
```

## 七、视频播放

**Android (ExoPlayer / Media3):**
```kotlin
val player = ExoPlayer.Builder(context).build().apply {
    setMediaItem(MediaItem.fromUri(url))
    repeatMode = Player.REPEAT_MODE_ONE
    volume = if (isMuted) 0f else 1f
    prepare()
    playWhenReady = true
}
playerView.player = player
```

**iOS (AVPlayer):**
```swift
let player = AVPlayer(url: url)
player.actionAtItemEnd = .none
player.isMuted = isMuted

NotificationCenter.default.addObserver(
    forName: .AVPlayerItemDidPlayToEndTime,
    object: player.currentItem,
    queue: .main
) { _ in
    player.seek(to: .zero)
    player.play()
}
```

## 八、分享面板

**Android:**
```kotlin
val intent = Intent(Intent.ACTION_SEND).apply {
    type = "video/mp4"
    putExtra(Intent.EXTRA_STREAM, uri)
    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
}
startActivity(Intent.createChooser(intent, "Share video"))
```

**iOS:**
```swift
let activityVC = UIActivityViewController(
    activityItems: [videoURL],
    applicationActivities: nil
)
present(activityVC, animated: true)
```

## 九、保存到相册

**Android (MediaStore):**
```kotlin
val contentValues = ContentValues().apply {
    put(MediaStore.MediaColumns.DISPLAY_NAME, "export_${System.currentTimeMillis()}.mp4")
    put(MediaStore.MediaColumns.MIME_TYPE, "video/mp4")
    put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_MOVIES)
}
val uri = contentResolver.insert(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, contentValues)
uri?.let {
    contentResolver.openOutputStream(it)?.use { out -> sourceStream.copyTo(out) }
}
```

**iOS (PHPhotoLibrary):**
```swift
PHPhotoLibrary.shared().performChanges({
    PHAssetCreationRequest.creationRequestForAssetFromVideo(atFileURL: localURL)
}) { success, error in
    if success {
        // 保存成功
    }
}
```

## 十、图片裁剪

**Android (UCrop):**
```kotlin
UCrop.of(sourceUri, destUri)
    .withAspectRatio(1f, 1f)
    .withMaxResultSize(512, 512)
    .start(this)
```

**iOS (PHPicker + 自定义裁剪):**
```swift
var config = PHPickerConfiguration()
config.filter = .images
config.selectionLimit = 1
let picker = PHPickerViewController(configuration: config)
picker.delegate = self
present(picker, animated: true)
// 拿到 UIImage 后用自定义 CropView 裁剪
```

## 十一、Haptic 反馈

**Android:**
```kotlin
view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
// Android 12+
view.performHapticFeedback(HapticFeedbackConstants.CONFIRM)
```

**iOS:**
```swift
UIImpactFeedbackGenerator(style: .light).impactOccurred()
UISelectionFeedbackGenerator().selectionChanged()
UINotificationFeedbackGenerator().notificationOccurred(.success)
```

## 十二、动画

**Android (ObjectAnimator):**
```kotlin
ObjectAnimator.ofFloat(view, "scaleX", 1.0f, 1.3f, 1.0f).apply {
    duration = 300
    interpolator = OvershootInterpolator()
    start()
}
```

**iOS (SwiftUI):**
```swift
.scaleEffect(isLiked ? 1.3 : 1.0)
.animation(.spring(response: 0.3, dampingFraction: 0.5), value: isLiked)
```

## 十三、弹窗

**Android (BottomSheetDialog):**
```kotlin
class CustomBottomSheet : BottomSheetDialogFragment() {
    override fun getTheme() = R.style.BottomSheetStyle
}

// themes.xml
<style name="BottomSheetStyle" parent="Widget.MaterialComponents.BottomSheet">
    <item name="shapeAppearanceOverlay">@style/BottomSheetRounded</item>
</style>
<style name="BottomSheetRounded">
    <item name="cornerSizeTopLeft">24dp</item>
    <item name="cornerSizeTopRight">24dp</item>
</style>
```

**iOS (SwiftUI):**
```swift
.sheet(isPresented: $show) {
    BottomSheetContent()
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
        .presentationBackground(ThemeThemeColors.bgSurface)
}
```

## 十四、Toast / Snackbar

**Android (Snackbar):**
```kotlin
Snackbar.make(view, message, Snackbar.LENGTH_SHORT).apply {
    setBackgroundTint(ThemeColors.bgSurface)
    setTextColor(ThemeColors.textPrimary)
    setActionTextColor(ThemeColors.accentPrimary)
    anchorView = bottomNavView  // 显示在底栏上方
}.show()
```

**iOS (自定义 Toast):**
```swift
.overlay(alignment: .bottom) {
    if showToast {
        Text(toastMessage)
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(ThemeThemeColors.bgSurface)
            .cornerRadius(8)
            .padding(.bottom, 110)  // 底栏上方
            .transition(.move(edge: .bottom).combined(with: .opacity))
    }
}
```

## 十五、Badge

**Android:**
```kotlin
val badge = BadgeDrawable.create(context).apply {
    number = count
    maxCharacterCount = 3  // 自动显示 "99+"
    backgroundColor = ThemeColors.accentPrimary
    badgeTextColor = ThemeColors.navActiveText
}
BadgeUtils.attachBadgeDrawable(badge, anchorView)
```

**iOS:**
```swift
Text(count > 99 ? "99+" : "\(count)")
    .font(.system(size: 8, weight: .bold))
    .foregroundColor(ThemeThemeColors.navActiveText)
    .padding(.horizontal, 4)
    .frame(minWidth: 16, minHeight: 16)
    .background(ThemeThemeColors.accentPrimary)
    .clipShape(Capsule())
```

## 十六、Inter 字体注册

**Android** — `res/font/` 目录:
```
res/font/
├── inter_regular.ttf
├── inter_medium.ttf
├── inter_semibold.ttf
└── inter_bold.ttf
```
在 TextView 里使用：
```xml
<TextView android:fontFamily="@font/inter_bold" />
```

**iOS** — 注册字体:
1. 把 `.ttf` 文件加到项目 Resources
2. Info.plist 添加：
```xml
<key>UIAppFonts</key>
<array>
    <string>Inter-Regular.ttf</string>
    <string>Inter-Medium.ttf</string>
    <string>Inter-SemiBold.ttf</string>
    <string>Inter-Bold.ttf</string>
</array>
```
使用：`.font(.custom("Inter-Bold", size: 13))`

## 十七、深度链接

**Android:**
```xml
<!-- AndroidManifest.xml -->
<activity android:name=".MainActivity">
    <intent-filter>
        <action android:name="android.intent.action.VIEW" />
        <category android:name="android.intent.category.DEFAULT" />
        <category android:name="android.intent.category.BROWSABLE" />
        <data android:scheme="exampleapp" />
    </intent-filter>
</activity>
```

**iOS:**
```swift
// App.swift
.onOpenURL { url in
    router.handle(url)
}

// Info.plist
<key>CFBundleURLTypes</key>
<array>
    <dict>
        <key>CFBundleURLSchemes</key>
        <array><string>exampleapp</string></array>
    </dict>
</array>
```

## 十八、日志工具

**Android (Logcat):**
```bash
# 过滤包名
adb logcat --pid=$(adb shell pidof com.example.app)

# 只看 Error
adb logcat -s AndroidRuntime:E

# 崩溃堆栈
adb logcat -b crash
```

**iOS (simctl):**
```bash
# 实时日志
xcrun simctl spawn booted log stream --predicate 'process == "ExampleApp"' --level debug

# 历史日志
xcrun simctl spawn booted log show --predicate 'process == "ExampleApp"' --last 10m

# 截图
xcrun simctl io booted screenshot /tmp/screenshot.png
```

