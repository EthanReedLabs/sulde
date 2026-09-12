# postmortem Android 参考(`mobile-android`)

> 配套 `../SKILL.md`。Android 特定 lint 写法 + 跨端镜像逻辑。

## §1 Android lint 规则写法

```bash
#!/usr/bin/env bash
# 例:NPE 强解 lint
set -e

VIOLATIONS=$(grep -rn '!!\b' feature-*/src/main/java core-*/src/main/java \
             --include="*.kt" 2>/dev/null | grep -v 'TODO\|allowlist' || true)

if [ -n "$VIOLATIONS" ]; then
    echo "❌ ADR 0042 (强解 !!): 强解 in non-test code"
    echo "$VIOLATIONS"
    exit 1
fi
```

### 常见 Android lint 命中点

```bash
# 强解
grep -rn '!!\b' feature-*/src/main/java core-*/src/main/java --include="*.kt"

# Coroutine 滥用
grep -rn 'GlobalScope\|runBlocking' --include="*.kt"

# 主线程阻塞
grep -rn 'Thread.sleep' --include="*.kt"

# 错误 cast
grep -rn ' as [A-Z]' --include="*.kt" | grep -v 'as\?'

# Color hex 硬编码
grep -rn 'Color.parseColor\|"#[0-9A-Fa-f]\{6\}"' --include="*.kt" --include="*.xml"

# 调试日志(prod 应清)
grep -rn 'Log.d\|println(' --include="*.kt"

# Compose 漏 `key()` in list
# (这种 grep 不准,标 `lint_status: infeasible` 或留 detekt 规则)
```

### Android lint 框架(可选,更强类型 lint)

- **ktlint**:格式 lint
- **detekt**:自定义规则 lint(Kotlin AST 级别)— 比 grep 准
- **Android lint**:`./gradlew lint` 内置

复杂规则用 detekt;简单 grep pattern 用 shell 脚本。

## §2 跨端镜像逻辑

Android 修了 X bug 时,**iOS / Flutter / Harmony 同语义文件路径映射**:

| Android | iOS | Flutter | Harmony |
|---|---|---|---|
| `feature-home/.../HomeFragment.kt` | `Sources/FeatureHome/HomeView.swift` | `lib/feature_home/` | `features/home/src/main/ets/` |
| `core-ui/.../Colors.kt` | `Sources/CoreUI/AppColors.swift` | `lib/core_ui/app_colors.dart` | `commons/coreui/src/main/ets/designtokens/AppColors.ets` |
| `core-ui/.../AppTopBar.kt` | `Sources/CoreUI/AppTopBar.swift` | `lib/core_ui/app_top_bar.dart` | `commons/coreui/src/main/ets/scaffolds/AppTopBar.ets` |
| `core-network/.../{Api}.kt` | `Sources/InfraNetwork/{Api}Client.swift` | `lib/core_network/` | `commons/corenetwork/src/main/ets/` |

写跨端 handoff 时引用对应 file 路径让协调端起草 task md。

## §3 反模式 ADR Android 常见类别

- **MVI 两层终止破坏**:reduceResult 返 Command
- **NPE 强解(`!!`)**:在非 test code
- **Flow cold/hot 错配**:repository L1 用 `Flow` 而非 `StateFlow`
- **lifecycle 不感知**:Flow collect 不在 `repeatOnLifecycle`
- **Coroutine scope 滥用**:GlobalScope / runBlocking
- **RecyclerView identity 漂**:DiffUtil `areItemsTheSame` 用 hashCode
- **资源 ID 跨 module 冲突**:不同 module 同名 ID
- **Compose recompose 频繁**:State 没拆细 + 没 derivedStateOf
