---
doc_id: "anti-patterns/INDEX"
container: anti-patterns
platform: none
summary: "按**平台受控 facet**导航全部通用反模式。"
---

# 反模式索引(anti-patterns INDEX)

> 按**平台受控 facet**导航全部通用反模式。编号全局 append-only、跨来源项目单调递增,不 renumber。
> 一条反模式常跨多平台,此处按**主平台**归一;跨端/后端契约类归「跨端通用」,协作/派单/审计类归「协调端方法论」。
> 新增沉淀走 [`../SEDIMENTATION-STANDARD.md`](../SEDIMENTATION-STANDARD.md)(编号规则 / 平台受控词 / dedup-before-add / 脱敏铁律)。
>
> **平台受控词**:`Android` · `iOS` · `HarmonyOS` · `跨端通用` · `协调端方法论`(对齐 ADR frontmatter platforms enum `android/ios/flutter/harmony/coordinator/any`)。

## HarmonyOS(9)

- [`0145`](./0145-arkui-bindcontentcover-builder-reactive-detachment.md) — ArkUI `bindContentCover` + `@Builder` 内 reactive 订阅脱钩(reactive 重场景必 Stack overlay)
- [`0147`](./0147-scroll-shell-fixed-header-boundary.md) — 已弃用，重定向至 [`ArkUI 滚动页壳 / 固定标题栏`](../platform-kb/harmony/arkui-layout-scroll-shell.md)
- [`0151`](./0151-scroll-container-gesture-ownership.md) — 滚动容器内多手势共存:先划事件所有权矩阵,再写手势代码
- [`0154`](./0154-arkui-width-100-plus-margin-anchor-semantics.md) — ArkUI `width('100%') + margin` 不等价 Flutter `EdgeInsets`,布局锚点必须显式建模
- [`0155`](./0155-runtime-visual-anchor-measurement-closure.md) — 运行时视觉锚点必须闭包测量:禁止用设计常量冒充真实尖点 / 中心点
- [`0156`](./0156-arkui-floating-surface-width-layering.md) — 浮层不是一个宽度:遮罩 / 承载 / 视觉面板 / 内容必须拆层建模
- [`0157`](./0157-keyboard-avoidance-boundary-nested-overlay.md) — 键盘遮挡先判承载边界:`KeyboardAvoidMode.RESIZE` 不覆盖 bindSheet 内自绘二级底部浮层
- [`0158`](./0158-font-color-same-param-different-render-transpile.md) — 字号/颜色"同参数不同效果":转译只对字面参数,不解析到最终渲染值
- [`0240`](./0240-cross-process-session-secure-storage-only.md) — 跨进程消费者只读加密凭据导致主应用与 Extension/Widget 登录态分裂

## Android(43)

- [`0001`](./0001-placeholder-1-1.md) — 在每个页面单独修系统级问题
- [`0002`](./0002-linearlayout.md) — 浮层用 LinearLayout 排列
- [`0003`](./0003-bottomnavigationview.md) — 用标准 BottomNavigationView 实现自定义形状底栏
- [`0004`](./0004-placeholder-1-4.md) — 颜色硬编码
- [`0005`](./0005-placeholder-1-5.md) — 主内容区固定高度
- [`0007`](./0007-sp-dp.md) — 字号既用 sp 又用 dp 混乱
- [`0008`](./0008-placeholder-1-8.md) — 标题贴状态栏 / 三层根因
- [`0009`](./0009-inset-navigationbars.md) — 底栏 inset 误用 navigationBars + 容器固定高度
- [`0011`](./0011-vector-shape.md) — 视觉资源降级:渐变 / vector → 纯色 / 简单 shape 占位
- [`0012`](./0012-mvi-adaptivebaseactivity-inset.md) — MVI 基类不继承统一自适应基类 → 每个二级页重复补状态栏手动 inset
- [`0015`](./0015-android-edittext-adaptivebaseactivity.md) — Android EditText 页面应继承统一基类默认"点外部收键盘"
- [`0016`](./0016-reduceresult-command.md) — reduceResult 中产生 Command
- [`0018`](./0018-feature-feature.md) — Feature 直接依赖另一个 Feature
- [`0019`](./0019-aiservice.md) — Service 为每种类型写单独的方法
- [`0021`](./0021-fragment-adaptivebasefragment-onbackpressed.md) — Fragment 绕过统一返回钩子(AdaptiveBaseFragment.onBackPressed）
- [`0026`](./0026-exoplayer-recyclerview-viewpager2-setplayer-early-return.md) — ExoPlayer 池复用 + RecyclerView/ViewPager2 复用 → 同实例 setPlayer early return → 黑屏
- [`0031`](./0031-ui-uiautomator-dump.md) — UI 对齐任务误用 uiautomator dump 代替多模态看图
- [`0032`](./0032-gdpr.md) — 首启不弹 GDPR 同意弹窗
- [`0033`](./0033-google-services-json-gitignore-build.md) — google-services.json 被 .gitignore 全量拦截导致 build 失败
- [`0098`](./0098-cold-flow-stateflow-update-broken.md) — Cold flow 暴露 StateFlow 但更新链断 — 不订阅 events 的消费者读到永恒初始快照
- [`0101`](./0101-android-okhttp-factory-multi-instance.md) — Android core-network factory 多实例化反模式
- [`0102`](./0102-android-ios-webview-evaluatejavascript-localstorage-injection.md) — WebView evaluateJavascript 注入 localStorage 的 3 个时序坑
- [`0108`](./0108-di-singleton-runtime-config-stale.md) — DI 单例 + 运行时配置 = stale state
- [`0109`](./0109-uri-cross-activity-permission.md) — URI 跨 Activity FLAG_GRANT_READ_URI_PERMISSION 未传
- [`0110`](./0110-naked-toLong-external-id.md) — 裸 toLong / toInt 解析外部 ID 串
- [`0112`](./0112-fragmentmanager-result-mismatch.md) — childFragmentManager show + parent setFragmentResultListener 错配
- [`0115`](./0115-encryptedsharedpreferences-no-decrypt-fallback-startup-crash.md) — EncryptedSharedPreferences 无解密兜底启动闪退
- [`0117`](./0117-coil-crossfade-drawable-cast-bitmapdrawable.md) — Coil 全局 crossfade → ImageView.drawable 强转 BitmapDrawable 崩
- [`0118`](./0118-coil-hardware-bitmap-software-canvas-black.md) — Coil 默认 allowHardware=true → HARDWARE bitmap 画到软件 Canvas 全黑
- [`0119`](./0119-upload-service-image-falls-to-music-branch.md) — 通用 UploadService 对纯文件(image / 头像)无分支,落 else 当业务存
- [`0123`](./0123-backend-uses-http-200-code-minus1-for-business-errors.md) — 后端业务错误全 HTTP 200 + code≠0,客户端 HTTP 401/403 拦截器是死代码
- [`0133`](./0133-register-unregister-lifecycle-mismatch-leak.md) — register/unregister 跨生命周期级别不对称 → 重复注册泄漏
- [`0135`](./0135-cross-end-routing-id-single-extra-vs-separate-params.md) — 跨端导航 routing id 串单一 extra 传 vs 分离参数传 — Android 易污染下游
- [`0136`](./0136-cross-end-color-format-rgba-argb-opacity-pitfall.md) — pen-truth 颜色 8 位 hex 跨端格式陷阱 — RGBA(设计稿)vs ARGB(Android)vs opacity(iOS)
- [`0138`](./0138-component-builtin-control-default-empty-callback-dead-button.md) — 组件内建交互控件 + 默认空 callback → 死按钮 / 列表复用 placeholder 串台
- [`0139`](./0139-music-duration-sec-ms-truncate.md) — duration 秒→ms 先截断后乘(单位口径漂移)
- [`0159`](./0159-compose-list-eager-audio-init-main-thread.md) — Compose 懒列表 item 在组合期同步读取音频 metadata + `MediaPlayer.prepare()` → UI 主线程连续掉帧
- [`0163`](./0163-fragment-hidden-lifecycle-visibility-decoupled.md) — hide/show 宿主下 Fragment 生命周期与可见性解耦,持续任务必须双重门控
- [`0166`](./0166-m3-widget-in-m2-theme-silent-no-render.md) — Material 2 主题使用 Material 3 专属组件导致静默不渲染
- [`0169`](./0169-video-feed-resume-no-surface-rebuild-frozen.md) — 长后台恢复只开启播放而不重建 surface 导致画面冻结
- [`0172`](./0172-kotlinx-serialization-encode-defaults-off-wire.md) — `kotlinx.serialization` 未开启默认值编码，协议必填字段未写入 wire
- [`0175`](./0175-foreground-service-startforeground-five-second-deadline.md) — 前台服务未在五秒时限内调用 `startForeground`
- [`0238`](./0238-kmp-common-resource-assumed-in-android-assets.md) — 误以为 KMP 公共资源会自动进入 Android APK Assets

## iOS(48)

- [`0006`](./0006-swiftui-vstack-hstack.md) — SwiftUI 浮层用 VStack/HStack
- [`0010`](./0010-ios-contextmenu-confirmationdialog.md) — iOS 长按菜单用 `.contextMenu` 而不是 `.confirmationDialog`
- [`0013`](./0013-pill-bg-tab-frame.md) — 选中态 pill bg 撑满整个 tab frame
- [`0014`](./0014-swiftui-scrollview.md) — SwiftUI 固定区放 ScrollView 内 + 键盘自动顶整页
- [`0017`](./0017-ios-result-action-run.md) — iOS Result Action 返回 `.run`
- [`0020`](./0020-run.md) — 长时工作流链式触发新 `.run`
- [`0022`](./0022-delegate-reducer.md) — 登录拦截 delegate 设计了但父 reducer 没接住
- [`0023`](./0023-feature-new-avplayer-exoplayer-mediaplayer.md) — Feature 模块自建 AVPlayer / ExoPlayer / MediaPlayer 实例
- [`0024`](./0024-swiftui.md) — SwiftUI 高频驱动手势组件的 5 类性能与正确性陷阱
- [`0025`](./0025-toggle-guest.md) — toggle / 偏好类组件对 guest 用户应允许视觉切换，不强行打断主流程
- [`0036`](./0036-macos-tcc-claude-code-agent.md) — macOS TCC 拦截 Claude Code agent 模拟器自动化输入
- [`0048`](./0048-ios-verify-find-head-n-app.md) — iOS verify 任务 `find ... | head -1` 拣到 N 天前旧 .app → 验证证据无效
- [`0050`](./0050-envelope-msg-vs-message-decode-try.md) — 后端 envelope 双键名(`msg` vs `message`) + 严格 decode + `try?` 三连 → 全模块静默
- [`0051`](./0051-ios-sheet-fullscreencover-bottomdrawer-zstack-overlay.md) — iOS 底部抽屉禁 `.sheet` / `.fullScreenCover` → 必须用 BottomDrawer ZStack overlay
- [`0055`](./0055-sse-decoder-generic-decode-events.md) — SSE 流式协议 Decoder 对每行 generic decode<业务模型> 静默吞错 → 0 events / 流空跑
- [`0058`](./0058-xcode-debug-iphoneos-build-preview-dylib-ios-x-sigtrap-crash.md) — Xcode 26 Debug-iphoneos build 默认注 __preview.dylib → iOS 16.x 真机启动 SIGTRAP crash
- [`0062`](./0062-ios-x-asset-catalog-svg-currentcolor-swiftui-image-template.md) — iOS 16.x Asset Catalog SVG `currentColor` + SwiftUI Image `.template` 渲染兼容性 bug
- [`0063`](./0063-swiftui-offset-hit-testing.md) — SwiftUI `.offset` hit-testing 不随渲染移动
- [`0064`](./0064-tca-perception-bindable-withperceptiontracking.md) — TCA `@Perception.Bindable` + `WithPerceptionTracking` 必配对
- [`0085`](./0085-swiftui-lazyvstack-view-closure-body.md) — SwiftUI LazyVStack 子 View 含 closure 参数 → 父 body 重算时子树永远无法跳过
- [`0086`](./0086-onappear-store-action-fast-swipe-action.md) — 滚动列表 `onAppear` 触发 store action → fast swipe 时 action 风暴
- [`0087`](./0087-swiftui-tca-escaping-closure-withperceptiontracking.md) — SwiftUI + TCA escaping closure 漏 WithPerceptionTracking 五大触发点
- [`0088`](./0088-swiftui-button-frame-contentshape-hit-testing.md) — SwiftUI Button `.frame()` 无 `.contentShape()` 致 hit-testing 命中区偏小
- [`0089`](./0089-swiftui-preferencekey-geometryreader-lazycontainer.md) — SwiftUI PreferenceKey + GeometryReader 在 LazyContainer ScrollView 内不可靠
- [`0093`](./0093-cache-file-no-extension-avplayer-fails.md) — Cache 文件用 hash 命名无扩展名 → iOS AVPlayer 解码失败 -11828
- [`0103`](./0103-ios-chat-textchunk-stagehint-placeholder.md) — iOS Chat 流式 textChunk 临时用占位 capsule 渲染(无累积无 JSON 过滤)
- [`0104`](./0104-ios-round3-backport-cross-feature-miss.md) — iOS 跨 Feature backport 漏接(一个 Feature 升级了时序设计,同款另一个 Feature 漏 backport)
- [`0107`](./0107-fixture-must-mirror-sse-wire.md) — fixture 必须逐行镜像真实 SSE wire
- [`0111`](./0111-swiftui-nested-button-custom-tap.md) — SwiftUI 嵌套空 Button + 自定义 tap modifier 手势冲突
- [`0113`](./0113-tca-cancellable-metatype-fail.md) — TCA .cancellable(id:) metatype 编译失败 → CancelID { case x } idiom
- [`0114`](./0114-tca-delegate-no-parent-dismiss-and-commit-nil-overrides.md) — TCA picker delegate 不关父态 + commit(nil) 误擦互斥兄弟字段
- [`0116`](./0116-ios-uikit-present-while-dismissing-chained-sheet-race.md) — iOS UIKit 链式 sheet present-while-dismissing 竞态
- [`0122`](./0122-client-placeholder-fakes-backend-business-field.md) — 客户端用占位逻辑伪造后端缺失的业务字段 → 占位与真实状态脱钩
- [`0127`](./0127-tca-non-idempotent-effect-no-reentrancy-double-fire.md) — TCA / MVI effect 发非幂等网络副作用无防重入 + 非 cancellable → 多触发源双发
- [`0128`](./0128-ios-custom-player-missing-state-ended-replay.md) — iOS 自定义播放器漏 STATE_ENDED → seekTo(0) → 视频「只能播一次」
- [`0129`](./0129-backend-boolean-semantic-unclear-direct-pass-once-sediment-bypass.md) — 后端 boolean 字段语义不明时直传 UI state 不取反 + 标 #once 跳过沉淀
- [`0132`](./0132-poll-first-failure-treated-as-no-task-duplicate-paid-merge.md) — poll-first 把"查询失败 null"当"无任务" → 重复付费
- [`0137`](./0137-real-adapter-delegates-mock-data-source-falsified.md) — Real adapter 委托 mock 导致数据源失真
- [`0140`](./0140-swiftui-id-rebuild-store-view-divergence.md) — SwiftUI `.id(version)` 整树重建后 TCA store/view 发散
- [`0165`](./0165-ios16-multi-navigationdestination-push-hang.md) — iOS 16 同一 NavigationStack 注册多个 navigationDestination 导致 push 卡死
- [`0167`](./0167-perception-conditional-read-unstable-tracking.md) — Perception 条件读取导致本轮依赖追踪集不稳定
- [`0168`](./0168-xcodebuild-global-bundleid-override-spm-collision.md) — xcodebuild 全局覆盖 Bundle ID 导致 SPM 资源 bundle 撞名与 asset 错乱
- [`0171`](./0171-swift-actor-reentrancy-no-keyed-singleflight.md) — actor 可重入导致同 key 请求未单飞
- [`0173`](./0173-async-result-missing-cancel-and-identity-guard.md) — 异步结果写回缺少取消与 identity 双保险
- [`0176`](./0176-security-scoped-url-copy-inside-access-window.md) — security-scoped URL 未在授权窗口内复制
- [`0179`](./0179-strings-quote-syntax-plutil-all-locales.md) — `.strings` 引号语法错误未用 `plutil` 校验全部 locale
- [`0233`](./0233-kotlin-module-version-drift-native-irlinkageerror.md) — Kotlin 多模块依赖版本漂移在原生侧表现为 IrLinkageError
- [`0236`](./0236-cvpixelbuffer-cross-coroutine-without-retain.md) — AVFoundation 帧跨协程前未在回调窗口 retain

## 跨端通用(45)

- [`0027`](./0027-ui.md) — 修改 UI 时删除业务逻辑
- [`0067`](./0067-ui-vs.md) — 修复 UI 时不分类系统级 vs 业务级
- [`0068`](./0068-feature.md) — Feature 模块重复造脚手架轮子
- [`0070`](./0070-main-develop-commit.md) — 在 main / develop 上直接 commit
- [`0071`](./0071-worktree.md) — worktree 创建在项目目录之外
- [`0072`](./0072-commit-message.md) — commit message 用英文
- [`0073`](./0073-commit-message-ai.md) — commit message 写得像 AI 报告
- [`0074`](./0074-git.md) — 复合命令 `&&` 链 + 主目录污染 → git 卡死
- [`0075`](./0075-placeholder-5-6.md) — 主目录污染
- [`0076`](./0076-placeholder-5-7.md) — 提交后不删除已合并分支
- [`0077`](./0077-placeholder-6-1.md) — 列表里图片不复用
- [`0078`](./0078-exoplayer.md) — 视频区每次切换都创建新播放器
- [`0079`](./0079-s.md) — 长时轮询固定间隔死循环
- [`0081`](./0081-en-zh.md) — 多语言只翻部分语言
- [`0082`](./0082-placeholder-7-3.md) — 长文案在小屏溢出
- [`0083`](./0083-task.md) — 视觉对齐 task 误改业务链路
- [`0084`](./0084-task-md-ui-jank.md) — 协调端 task md 缺 UI 时序约束 → 双端动画 jank 对称返工
- [`0090`](./0090-reducer-feature-distinctby-key-distinct.md) — Reducer / Feature 内 `distinctBy` 改 key 不实测 distinct 数量
- [`0094`](./0094-wizard-viewmodel-threadid-random-uuid-not-flowuuid.md) — Wizard ViewModel 会话 ID 凭本地随机 UUID 不接 server 返回 ID → 后端报错
- [`0142`](./0142-shallow-source-reverse-multi-round-rework.md) — 浅层反抽源码(grep 采样 + 无运行时实证 + 无跨端能力探针)→ 累积漂移 + 多轮返工
- [`0144`](./0144-experimental-branch-no-merge-to-mainline.md) — spike/实验分支禁 merge 回主干(简化版入口/系统文件回灌主链路)
- [`0146`](./0146-scenario-state-matrix-and-resource-isolation.md) — UI 还原前先建「场景 × 状态」矩阵,主题策略不同的资源必须拆名隔离
- [`0148`](./0148-third-party-widget-state-machine-before-transpile.md) — 三方/复杂控件转译前必先抽状态机 + 内部数据模型 + 平台能力对照
- [`0149`](./0149-ui-sweep-misses-business-side-effect-chain.md) — 页面同步只对齐可见像素,漏掉业务副作用链路
- [`0150`](./0150-custom-component-substituted-by-system-default.md) — 反抽自绘公共组件时用系统默认组件替代(丢宽度/圆角/遮罩/动画真值)
- [`0152`](./0152-image-asset-render-semantics-not-hash.md) — 图片资源对齐必须反抽渲染语义,禁止只校验 asset hash
- [`0153`](./0153-payment-platform-branch-store-query-not-a-gate.md) — 支付链路商店商品查询是展示/诊断,不是购买前置 gate(且平台分支必须先拆)
- [`0160`](./0160-kmp-objective-c-variadic-interop.md) — KMP Kotlin/Native 直接把 Kotlin 值传入 C/Objective-C variadic API,编译通过但真机在 Foundation 格式化阶段野指针崩溃
- [`0161`](./0161-kmp-failable-initializer-eager-media-composition.md) — KMP 在 Compose 列表组合期调用 Objective-C 可失败媒体初始化器,失效沙盒路径触发 NPE 并增加滚动卡顿
- [`0162`](./0162-mvi-reducer-hardcoded-english-toast-i18n-leak.md) — MVI reducer 硬编码用户可见字符串导致 i18n 泄漏与重复提示
- [`0164`](./0164-response-dto-typed-by-assumption-not-capture.md) — 响应 DTO 按假设强类型建模而未对照真实响应
- [`0170`](./0170-synthetic-id-collision-collection-trap.md) — 用可塌缩字段合成 ID 导致集合陷阱或列表错乱
- [`0174`](./0174-native-app-reuses-web-channel-captcha-gate.md) — 原生客户端复用人机校验前置的 Web 通道导致渠道契约错配
- [`0177`](./0177-sdk-readiness-required-key-set-not-file-existence.md) — SDK 就绪判据只检查配置文件存在而未检查必需键集合
- [`0178`](./0178-diagnostic-log-compile-gate-and-redaction.md) — 流式诊断日志缺少编译闸与字段脱敏双闸
- [`0232`](./0232-persisted-message-ui-keeps-transient-id.md) — 消息写库后不回读稳定 ID，后续按 ID 操作静默失效
- [`0235`](./0235-generated-launcher-not-refreshed-after-spec-change.md) — launcher 规范更新但已生成包装器仍是旧壳
- [`0237`](./0237-native-async-inference-close-race.md) — 异步原生推理提交与关闭并发
- [`0241`](./0241-windows-wsl-sqlx-migration-line-ending-checksum.md) — Windows 与 WSL 构建的迁移行尾不一致导致 SQLx 校验冲突
- [`0246`](./0246-shared-consumable-sku-unfinished-transaction-already-owned.md) — 共享消耗型 SKU 的未完成交易阻塞跨内容购买
- [`0249`](./0249-manual-task-inherits-scheduled-opt-in-filter.md) — 手动全量任务复用定时 opt-in 过滤导致空跑成功
- [`0253`](./0253-interrupted-animation-accumulated-deformation.md) — 可中断动画在已有形变上重复叠加导致尺寸累积越界

- [`0250`](./0250-method-name-risk-without-receiver-proof.md) — 同名方法缺少对象类型证明导致文本操作误拦截
- [`0251`](./0251-optional-enrichment-invalidates-unrelated-approval.md) — 可选记忆增强被错误计入无关业务审批依赖
- [`0252`](./0252-test-interpreter-preflight-too-late.md) — 实际测试解释器的依赖预检放得太晚

## 协调端方法论(51)

- [`0028`](./0028-placeholder-3-2.md) — 提交身份和分支不匹配
- [`0029`](./0029-placeholder-3-3.md) — 给终端发指令时让用户手动转述差异
- [`0030`](./0030-dev-git.md) — 已弃用：跨多个 Dev 模块使用同一 git 身份（重定向至 [`0028`](./0028-placeholder-3-2.md)）
- [`0034`](./0034-placeholder-3-8.md) — 任务书硬约束写字面行数而非意图
- [`0035`](./0035-prd-prd-v3.md) — 协调端任务书引用旧版 / 简版 PRD 而非最新详版 PRD
- [`0037`](./0037-sub-page-wizard.md) — 多 sub-page 链路 / wizard 流程对齐任务用单行表对待 → 视觉粒度严重丢失
- [`0038`](./0038-wizard-step-step-dev-pageid.md) — Wizard / 多 step 任务书未列 step 编号 → Dev 误按 pageId 字母推导顺序
- [`0039`](./0039-handoff.md) — handoff 自检流于声明 → 用户验收发现"未做" → 协调端返工
- [`0040`](./0040-placeholder-3-14.md) — 节点对照表只验证节点存在，不验证视觉属性细节 → "对齐"假象
- [`0041`](./0041-placeholder-3-15.md) — 协调端登记反模式后第一时间忘记应用 → 同源问题立刻复发
- [`0042`](./0042-task-md-fallback-dev-fallback.md) — task md 留 fallback 口子 + 跨依赖糅合 → Dev 走 fallback 合规但违反用户意图
- [`0043`](./0043-dev-bug.md) — Dev 自发修小 bug 时改动范围扩散到敏感字段 → 协调端协作类防护被绕过
- [`0044`](./0044-token-dev-fail.md) — 协调端写技术文档/任务书时凭印象编"项目实际状态"(类名 / 文件名 / token 名 / 方法签名)→ Dev 抄错引发编译 fail
- [`0045`](./0045-dev-task-handoff-develop-audit.md) — Dev 完成 task 但未走完"出 handoff + 合主干 + 删分支"完整闭环 → 协调端 audit 时状态不一致
- [`0046`](./0046-task-md-spec-service-dev.md) — 协调端写双端 task md 未硬约束 Spec / Service 组织一致 → 双端 Dev 各自合理选择 → 后续接口接入差异
- [`0047`](./0047-real-debug-mock-debug-real-task.md) — 跨端默认 Real 路径不对称(一端 DEBUG 默认 Mock,另一端 DEBUG 默认 Real)→ 同 task 验收结果迥异
- [`0049`](./0049-spec-feature-client-mock.md) — Spec Feature 层抽象 Client 留 Mock 不易察觉 → 主线流量 0 真后端命中
- [`0052`](./0052-task-md-prd-pen-truth-ui-prd-sse.md) — 协调端写 task md 凭单一数据源(只看 PRD 或 pen-truth 或接口),未做 UI/PRD/接口 3 维交叉验证 → SSE 真数据来时字段对不上 → 返工
- [`0053`](./0053-pen-batch_get-json-png-task-md.md) — 协调端读 .pen batch_get 拿 JSON 节点数据但不导 .png 视觉对照 → 凭文字描述猜形态 → 双端 task md 反复误派
- [`0054`](./0054-task-md-boilerplate-model-sonnet-dev.md) — 协调端 task md 给完整代码 boilerplate + 标 model: sonnet → Dev 退化翻译机 / 不抽抽象 / 不思考复用
- [`0056`](./0056-claude-md-shared-rules-dev-session-system-reminder.md) — CLAUDE.md / shared-rules 改动后,Dev session 旧 system-reminder 注入快照不更新 → 新规则不生效
- [`0057`](./0057-task-md-audit-cp-dev-asset-catalog-drawable-ui.md) — 协调端 task md 漏 audit "资源 cp 实证" → Dev 实施漏拷资源 / Asset Catalog / drawable 缺失 → UI 渲染空白
- [`0059`](./0059-sweep-handoff-escalation.md) — 协调端漏 sweep handoff escalation → 同源问题多次回归
- [`0060`](./0060-spec.md) — 双端 Spec 进度不同步 → 跨端漂移视觉/行为不一致
- [`0061`](./0061-placeholder-3-42.md) — 协调端凭印象不查技术真值
- [`0065`](./0065-ultrathink.md) — 简单任务用 ultrathink
- [`0066`](./0066-parallel-dev-subagent-ultrathink.md) — parallel-dev 所有 subagent 都用 ultrathink
- [`0069`](./0069-bash-cd-claude-md.md) — 协调端 Bash 里 `cd` 到子端目录导致 CLAUDE.md 反复注入
- [`0091`](./0091-session-audit-task-md.md) — 协调端 session 切换后忘记派发过的任务，重新 audit 重写已完工 task md
- [`0092`](./0092-onbeat-cpsm-migration.md) — 单模块长期密集 patch 散落 → 抽统一 State Module 收敛重构
- [`0095`](./0095-coordinator-audit-skip-api-spec-grep-step.md) — 协调端 audit root cause 凭症状推 Module 跳过 grep 接口契约 → 多轮 fix 失败
- [`0096`](./0096-coordinator-task-md-cite-stale-pen-truth-no-git-log-verify.md) — 协调端写 task md 引过时设计真值没 git log verify → 差点造成代码回退
- [`0097`](./0097-scaffold-bypass-business-layer-direct-call.md) — scaffold 已建但业务层散落直接调底层 API → 视觉 / 行为不一致 + 跨期复发
- [`0099`](./0099-ralph-prompt-backtick-shell-parse-error.md) — Ralph PROMPT 内含反引号 / markdown fence → shell parse error 或用户复制污染
- [`0105`](./0105-coordinator-approve-gating-without-thin-step-verify.md) — 协调端 approve gating 契约凭"通用 UX 模式"未验 thin step running 行为
- [`0106`](./0106-coordinator-impl-task-md-default-platform-pattern-no-pen-truth.md) — 协调端实装 task md 凭"通用平台模式"决定播放/弹窗/导航形态不查 pen-truth
- [`0120`](./0120-coordinator-api-doc-v2-skip.md) — 协调端 API 文档多版本漏读 → 凭印象判 BE 阻塞
- [`0121`](./0121-coordinator-endpoint-vs-scenario-mismatch.md) — 协调端只看 endpoint 名 / schema 字段,漏看章节标题 / 场景定位
- [`0124`](./0124-backend-endpoint-wrapped-but-feature-never-calls.md) — adapter wrap ≠ 真链路 — 验链路必查文档 + 消费方 + live 正向验证
- [`0125`](./0125-backend-error-text-ui-mismatch-truth-nested.md) — 后端错误话术 UI 抽象不匹配 + 可操作真因藏在子对象
- [`0126`](./0126-final-video-render-state-must-mask-not-fallback-placeholder.md) — 异步渲染期必须有明确"合成中"态 + 不露占位 fallback
- [`0130`](./0130-coordinator-cross-sync-l10n-key-multiuse-without-grep.md) — 协调端跨端镜像 task md 写 L10n 文案 diff 前未 grep 全部引用点 → 一 key 多用直改污染
- [`0131`](./0131-audit-subagent-commit-mapping-by-keyword-not-diff.md) — audit subagent 把 commit 归为某需求修复时凭 commit message 关键词匹配,未 verify diff
- [`0134`](./0134-coordinator-prd-pen-cross-check-gap.md) — 协调端 pen-truth 批量铺设时未做 PRD↔设计稿反向校验
- [`0141`](./0141-single-state-screenshot-sticky-scroll-misjudge.md) — 凭证据不足的截图判 UI 对齐(sticky/scroll 方向、视觉差异来源)
- [`0143`](./0143-dev-work-outside-dispatch-boundary.md) — Dev 主任务 ship 后自驱 polish bundle 绕过协调端 task md 边界
- [`0234`](./0234-historical-evidence-written-as-current-status.md) — 把历史证据用现在时写成当前状态
- [`0239`](./0239-provider-specific-model-leaks-into-shared-task.md) — 提供方专属模型泄漏进共享任务契约
- [`0242`](./0242-read-only-mcp-interruption-false-effect-intervention.md) — 只读 MCP 中断被错误升级为外部效果干预
- [`0243`](./0243-control-composition-misclassified-as-destructive-pause.md) — 控制命令组合违规被误升级为破坏性暂停
- [`0244`](./0244-explicit-git-add-collapsed-to-repository-scope.md) — 精确 Git 暂存被压成仓库级权限
- [`0245`](./0245-permission-request-timeout-is-not-authority.md) — 人工审批超时不是授权结果
