# postmortem Flutter 参考(`mobile-flutter`)

> 配套 `../SKILL.md`。Flutter 特定 lint 写法 + 跨端镜像逻辑。

## §1 Flutter lint 规则写法

```bash
#!/usr/bin/env bash
# 例:强解 lint
set -e

VIOLATIONS=$(grep -rn '!\s*[.;)\]\}]' lib/ --include="*.dart" 2>/dev/null \
             | grep -v 'test/\|integration_test/' || true)

if [ -n "$VIOLATIONS" ]; then
    echo "❌ ADR 0042: 强解 in non-test code"
    echo "$VIOLATIONS"
    exit 1
fi
```

### 常见 Flutter lint 命中点

```bash
# 强解
grep -rn '!\s*[.;)\]\}]' lib/ --include="*.dart"

# print
grep -rn 'print(' lib/ --include="*.dart"

# Color 硬编码
grep -rn 'Color(0x\|Colors\.\|Color\.fromARGB' lib/ --include="*.dart"

# const 漏(可优化 rebuild)
# 用 `flutter analyze` 自带的 prefer_const_constructors lint

# setState in dispose-able context
grep -rn 'setState(' lib/ --include="*.dart" | grep -B 5 'mounted'  # 反向找漏 mounted 检查
```

### Flutter lint 框架

- **`flutter analyze`**:内置,配 `analysis_options.yaml`
- **dart format**:格式
- **custom_lint**:`package:custom_lint` 写 AST 级 lint(比 grep 准)

```yaml
# analysis_options.yaml example
linter:
  rules:
    prefer_const_constructors: true
    avoid_print: true
    prefer_const_literals_to_create_immutables: true
    use_key_in_widget_constructors: true
```

## §2 跨端镜像逻辑

Flutter 修了 X bug 时,**Android / iOS / Harmony 同语义路径**:

| Flutter | Android | iOS | Harmony |
|---|---|---|---|
| `lib/feature_home/` | `feature-home/.../` | `Sources/FeatureHome/` | `features/home/src/main/ets/` |
| `lib/core_ui/app_colors.dart` | `core-ui/.../Colors.kt` | `Sources/CoreUI/AppColors.swift` | `commons/coreui/.../AppColors.ets` |
| `lib/core_network/` | `core-network/.../` | `Sources/InfraNetwork/` | `commons/corenetwork/.../` |

**Flutter 特殊**:Flutter 同 codebase 双端运行,bug 可能源自 Android / iOS 双端原生侧(`platform_channels`)— Q4 检查时不仅是"其他 frontend stack",还要看本 Flutter 项目的 `android/` + `ios/` native 子目录。

## §3 反模式 ADR Flutter 常见类别

- **强解 `!`**:`null check operator used on null value` 高频
- **`late` 滥用**:`LateInitializationError`
- **setState after dispose**:`if (!mounted) return;` 漏
- **Riverpod / Bloc 注册位置错**:`ProviderScope` 不在 `runApp` 顶层
- **StreamSubscription leak**:`subscription.cancel()` 漏 in `dispose`
- **const 漏**:rebuild 性能差
- **Platform channel timeout**:无超时 + 无错误处理
- **跨端不一致**:Android / iOS 行为差异(键盘 / 滚动 / 触感)

---

> **占位说明**:本 references/flutter.md 是 v0.2.1 初版,4 问漏斗 / lint 写法 / 跨端镜像逻辑通用。Flutter lint 框架(`flutter analyze` / `custom_lint`)+ state 库选择项目特定,实际接入时按采用方案补充对应 lint pattern + ADR 类别。
