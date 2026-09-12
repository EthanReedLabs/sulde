# parallel-dev Flutter 参考(`mobile-flutter`)

> 配套 `../SKILL.md`。Flutter 特定公共文件 / 构建命令。

## §1 公共文件白名单

```
pubspec.yaml                          # 依赖 + asset 入口(并行改必冲突)
pubspec.lock                          # 依赖锁(commit 与否项目定)
analysis_options.yaml                 # 分析配置
lib/main.dart                         # 入口
lib/app/                              # App 壳
lib/core_ui/app_colors.dart           # 共享色
lib/core_ui/app_typography.dart       # 共享字号
lib/core_ui/app_router.dart           # 全局路由(go_router / auto_route 配置)
lib/core_ui/app_top_bar.dart          # 标题栏 scaffold
lib/core_ui/adaptive_state_view.dart  # 三态 scaffold
lib/core_localization/                # i18n 资源
android/app/build.gradle              # Android 端原生配置
android/app/src/main/AndroidManifest.xml
ios/Runner/Info.plist                 # iOS 端
ios/Runner.xcodeproj/project.pbxproj  # iOS pbxproj(同 iOS gotcha)
```

## §2 worktree 模板

```bash
git worktree add -b dev/{alias}/{module} ../<project-flutter>-{slug} develop

cd ../<project-flutter>-{slug}
flutter pub get
flutter build apk --debug

cd <project-flutter>
git checkout develop && git merge dev/{alias}/{module} && git branch -d dev/{alias}/{module}
git worktree remove ../<project-flutter>-{slug}
```

## §3 verify 命令

```bash
flutter analyze
flutter build apk --debug      # Android target
flutter build ios --no-codesign --debug  # iOS target(需 macOS)
flutter install
flutter run --release
```

## §4 Flutter 并行特定 gotcha

- **Hot reload state 残留**:每个 worktree 独立 device 运行,不要共用一台模拟器(都 attach 同 device 时混乱)
- **pubspec.yaml + pub.lock**:多 worktree 同时改依赖必冲突,串行
- **跨平台 verify**:Flutter task 通常要求 Android + iOS 双端 build,worktree 内必双端跑(主协调汇总时双端证据齐)
- **L10n .arb 文件**:翻译并行可,但生成的 `app_localizations*.dart` 由工具产物,改字符串 → 重生成 → 文件冲突

> 占位说明:v0.2.1 初版基于 Flutter 3.x 项目结构。
