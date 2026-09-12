# postmortem iOS 参考(`mobile-ios`)

> 配套 `../SKILL.md`。iOS 特定 lint 写法 + 跨端镜像逻辑。

## §1 iOS lint 规则写法

```bash
#!/usr/bin/env bash
# 例:强解 lint
set -e

VIOLATIONS=$(grep -rn '!\s*[.;)\]\}]' Sources/ --include="*.swift" 2>/dev/null \
             | grep -v 'XCTestCase\|Tests/\|UnitTest' || true)

if [ -n "$VIOLATIONS" ]; then
    echo "❌ ADR 0042 (Optional 强解): 强解 in non-test code"
    echo "$VIOLATIONS"
    exit 1
fi
```

### 常见 iOS lint 命中点

```bash
# 强解
grep -rn '!\s*[.;)\]\}]' Sources/ --include="*.swift"

# try!
grep -rn 'try!' Sources/ --include="*.swift"

# Color 硬编码
grep -rn 'Color(red:\|UIColor(red:\|#[0-9A-Fa-f]\{6\}' Sources/ --include="*.swift"

# .font(.system(size:))(应用 AppTypography)
grep -rn '\.font(\.system(size:' Sources/ --include="*.swift"

# print(...) in non-test
grep -rn 'print(' Sources/ --include="*.swift" | grep -v 'Tests/'

# @Perception.Bindable 不配 WithPerceptionTracking
grep -A 5 '@Perception.Bindable' Sources/ --include="*.swift" \
  | grep -B 5 'var body:' | grep -v 'WithPerceptionTracking'
```

### iOS lint 框架(可选)

- **SwiftLint**:配 `.swiftlint.yml` 加 custom_rules(YAML 内 regex)— 比 grep 准
- **SwiftFormat**:格式
- **某些行为型规则**(`@Perception.Bindable` 配对 `WithPerceptionTracking`)只能 grep + 人工,标 `lint_status: infeasible` 或 partial

```yaml
# .swiftlint.yml example
custom_rules:
  no_force_unwrap_in_production:
    name: "Force unwrap in production"
    regex: '!\s*[.;)\]\}]'
    excluded_paths:
      - Tests
    message: "Avoid force unwraps in production code (ADR §0042)"
    severity: warning
```

## §2 跨端镜像逻辑

iOS 修了 X bug 时,**Android / Flutter / Harmony 同语义路径映射**:

| iOS | Android | Flutter | Harmony |
|---|---|---|---|
| `Sources/FeatureHome/HomeView.swift` | `feature-home/.../HomeFragment.kt` | `lib/feature_home/` | `features/home/src/main/ets/` |
| `Sources/CoreUI/AppColors.swift` | `core-ui/.../Colors.kt` | `lib/core_ui/app_colors.dart` | `commons/coreui/src/main/ets/designtokens/AppColors.ets` |
| `Sources/CoreUI/AppTopBar.swift` | `core-ui/.../AppTopBar.kt` | `lib/core_ui/app_top_bar.dart` | `commons/coreui/src/main/ets/scaffolds/AppTopBar.ets` |
| `Sources/InfraNetwork/{Client}.swift` | `core-network/.../{Api}.kt` | `lib/core_network/` | `commons/corenetwork/src/main/ets/` |
| `Sources/{FeatureSampleAgent}/` | `feature-create/<sample-agent>/` | `lib/feature_create/` | `features/create/src/main/ets/` |

## §3 反模式 ADR iOS 常见类别

- **TCA Action 三分类破坏**:Result Action 返 `.run`
- **`@Perception.Bindable` 不配 `WithPerceptionTracking`**:iOS 16+ body 不刷新
- **强解 `!`**:Optional 强制解包
- **try! / try?**:silent error 吞错
- **`[weak self]` 漏**:Combine sink / async closure 持有 strong ref
- **store(in: &cancellables) 漏**:Combine subscription leak
- **主线程违规**:UIKit / SwiftUI 操作不在 main
- **Scope keyPath / casePath 错**:TCA Scope 嵌套不匹配
- **链式 .run**:`.run` 内 `send` 触发新 `.run`(应单 .run 内 for await 平铺)
- **deinit 漏 removeObserver**:KVO / NotificationCenter 漏注销

## §4 SwiftUI 类 / 行为型 — `lint_status: infeasible` 模板

```markdown
---
adr: "0043"
title: "@Perception.Bindable 不配 WithPerceptionTracking"
platforms: [ios]
first_logged: <date>
recurrence: 1
lint_status: infeasible    # ← 这个不能 grep 严判
---

## Mitigation
### Long-term
- 仅人工:code review 必查;PR template 加 "@Perception.Bindable 检查"
- 部分自动化:`grep '@Perception.Bindable' Sources/` + 5 行内必出现 `WithPerceptionTracking` — soft check
```

诚实标"仅人工"比强造不准 lint 更负责任。
