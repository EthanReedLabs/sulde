# code-review Flutter 参考(`mobile-flutter`)

> 配套 `../SKILL.md`。Flutter 特定架构契约 / lint / 常见反模式。

## §1 架构合规 checklist(队友 1)

| 维度 | 检查项 |
|---|---|
| 状态管理 | 项目用的库一致(Riverpod / Bloc / Provider 等),**不混用** |
| Widget 树深度 | 不超过项目约定(一般 < 20 层) |
| 模块依赖 | feature_X 不依赖 feature_Y;依赖 core_* |
| Const constructors | 凡能 const 的 widget / config 必加 `const`(rebuild 性能)|
| Null safety | 强解(`!`)只在已 verify 非 null 处用 |
| Platform channel | iOS + Android 实现对称 / 错误码统一 |
| git 身份 + 分支 + AI 痕迹 | 同 Android / iOS |
| commit message | 中文拟人化 |
| pubspec.yaml | 依赖版本固定到 minor(不用 `^`)对生产 build |
| `lib/core_ui/` 改动 | 必走协调端 task md |

## §2 代码质量 / 性能 checklist(队友 2)

| 维度 | 检查项 |
|---|---|
| 内存 | StreamSubscription cancel in dispose / Controller dispose / ImageCache size |
| 异步 | `await` 异常处理 / Future cancellation |
| setState | `if (mounted) setState(...)` 检查 |
| 列表性能 | ListView.builder 用 / cacheExtent / RepaintBoundary |
| 图片 | CachedNetworkImage 用 / placeholder + fadeIn / thumbnail / cacheManager |
| 重 build | const constructor / Widget split / Selector pattern |
| Platform channel | Try/catch on PlatformException / timeout / 失败兜底 |
| 跨端一致 | Android + iOS verify(double check screenshots) |

## §3 Lint / 静态分析命令

```bash
# Flutter analyzer
flutter analyze 2>&1 | head -40

# Dart format check
dart format --set-exit-if-changed lib/

# 反模式 grep
grep -rn '!\s*[.;)\]]' lib/ --include="*.dart" | head -20   # 强解
grep -rn 'late ' lib/ --include="*.dart" | head -20         # late 滥用
grep -rn 'print(' lib/ --include="*.dart" | head -10        # print 不能进 release

# build verify
flutter build apk --debug 2>&1 | grep -E "warning|error" | head -20
```

## §4 项目模块映射

Flutter 典型分包:

```
lib/
├── main.dart
├── app/                  App 壳
├── core_ui/              共享 UI / 主题 / 字体 / token
├── core_network/         网络层
├── core_storage/         存储
├── feature_home/         首页(Dev A)
├── feature_discover/     发现
├── feature_create/       创建
├── feature_inbox/        通知
└── feature_profile/      我的
```

> 占位说明:v0.2.1 初版基于 Flutter 3.x 典型项目结构。项目实际接入时按采用的 state 库 + 路由方案补充契约规则。
