# postmortem Harmony 参考(`mobile-harmony`)

> 配套 `../SKILL.md`。HarmonyOS 特定 lint 写法 + 跨端镜像逻辑。

## §1 Harmony lint 规则写法

```bash
#!/usr/bin/env bash
# 例:@State 数组 mutation lint
set -e

VIOLATIONS=$(grep -rn 'this\.\w\+\.\(push\|splice\|pop\)' features/ commons/ \
             --include="*.ets" 2>/dev/null || true)

if [ -n "$VIOLATIONS" ]; then
    echo "❌ ADR 0044 (@State 数组 mutation): 用整体替换 [...arr, x] 代替 .push"
    echo "$VIOLATIONS"
    exit 1
fi
```

### 常见 Harmony lint 命中点

```bash
# @State 数组 mutation
grep -rn 'this\.\w\+\.\(push\|splice\|pop\)' --include="*.ets"

# Promise 无 catch
grep -rn '\.then(' --include="*.ets" | grep -v '\.catch'

# resource $r 路径(verify 文件存在)
grep -rn "\$r('app\." --include="*.ets" | head -20
# 需对照 resources/base/element/*.json 验

# 装饰器顺序
grep -B 2 -A 1 '@Component$' --include="*.ets" | grep '@Entry' \
  | head -10  # 应在 @Component 上方

# console.log / print(debug 残留)
grep -rn 'console\.log\|hilog\.\w\+(' --include="*.ets"
```

### Harmony lint 框架

- **hvigorw lint**:内置,DevEco Studio 工具链
- **ArkTS 自带 rule**:类型 / 装饰器顺序 / unused import

复杂 ArkTS 规则用 hvigor 自带 + 自写 shell 脚本(grep)补充。

## §2 跨端镜像逻辑

Harmony 修了 X bug 时,**Android / iOS / Flutter 同语义路径**:

| Harmony | Android | iOS | Flutter |
|---|---|---|---|
| `features/home/src/main/ets/` | `feature-home/.../` | `Sources/FeatureHome/` | `lib/feature_home/` |
| `commons/coreui/.../AppColors.ets` | `core-ui/.../Colors.kt` | `Sources/CoreUI/AppColors.swift` | `lib/core_ui/app_colors.dart` |
| `commons/corenetwork/.../` | `core-network/.../` | `Sources/InfraNetwork/` | `lib/core_network/` |

## §3 反模式 ADR Harmony 常见类别

- **@State 对象 / 数组 mutation 不刷新**:`this.items.push(x)` 应 `this.items = [...this.items, x]`
- **装饰器顺序错**:`@Component @Entry struct` 报错(必反过来)
- **Resource $r 引用 typo**:运行时崩
- **路由未注册**:`pages/X.ets` 不在 `main_pages.json` → router.pushUrl 失败
- **Promise unhandled rejection**:`.then(...)` 无 `.catch(...)`
- **LazyForEach keyGenerator 不稳定**:列表重渲乱
- **跨进程通信 RPC 异常**:`@ohos.rpc` 错误
- **Ability 生命周期违规**:`onWindowStageCreate` 之外访问 windowStage
- **TaskPool 数据传递 Sendable 不满足**:跨 worker 数据类型限制

> 占位说明:v0.2.1 初版基于 HarmonyOS NEXT API level 11/12。Harmony lint 工具链更新快,项目接入按 DevEco Studio 当前版本补充。
