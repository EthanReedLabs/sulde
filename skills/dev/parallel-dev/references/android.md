# parallel-dev Android 参考(`mobile-android`)

> 配套 `../SKILL.md`。Android 特定公共文件 / 构建命令。

## §1 公共文件白名单(永不并行改)

```
app/AndroidManifest.xml                          # 主入口配置
app/src/main/res/values/strings.xml             # 多语言入口
app/src/main/res/values-*/strings.xml           # 各语言
core-ui/src/main/java/.../Colors.kt              # 共享色 token
core-ui/src/main/java/.../Typography.kt          # 共享字号 token
core-ui/src/main/java/.../Spacing.kt             # 共享间距
core-ui/src/main/java/.../AppRouter.kt           # 全局路由
core-ui/src/main/java/.../AppTopBar.kt           # 标题栏 scaffold
core-ui/src/main/java/.../AdaptiveStateView.kt   # 三态 scaffold
core-ui/src/main/java/.../AdaptiveBaseActivity.kt # 基类
*/build.gradle.kts                                # 构建配置
gradle/libs.versions.toml                        # 依赖版本(catalog)
settings.gradle.kts                              # module 注册
gradle.properties                                # 全局属性
proguard-rules.pro                               # 混淆规则
```

任一文件出现在 ≥ 2 task 的 scope 内 → **串行**。

## §2 worktree 模板

```bash
# 建 worktree(从 develop)
git worktree add -b dev/{alias}/{module} ../<project-android>-{slug} develop

# Dev 完工后(从 worktree 内)
cd ../<project-android>-{slug}
./gradlew :{module}:assembleDebug
# install + verify(详 §3)

# 主协调 merge(从主 repo)
cd <project-android>
git checkout develop
git -c user.name="{name}" -c user.email="{email}" merge dev/{alias}/{module}
git branch -d dev/{alias}/{module}
git worktree remove ../<project-android>-{slug}
```

## §3 子 agent verify 命令

```bash
# Build
./gradlew :{module}:assembleDebug
# 或全 app
./gradlew assembleDebug

# Install
adb install -r app/build/outputs/apk/debug/app-debug.apk

# Launch
adb shell am start -n {package}/.MainActivity

# 30s log 抓
adb logcat -c
sleep 30
adb logcat -d -s AndroidRuntime:E '*:S' | tail -20  # 无 crash/error

# Lint
./gradlew :{module}:lint
```

## §4 常见并行场景

| 场景 | 是否可并行 |
|---|---|
| 不同 feature 模块 UI 改(feature-home + feature-discover)| ✅ |
| 同 module 不同文件 | ⚠️ 看是否共享 base class / 顺序更稳 |
| 多 Dev 修各自负责的 page | ✅ |
| 全局 token 改 + 各 feature 应用 | ❌ — token 先,feature 后(串行) |
| 多 module Compose 接入 | ⚠️ — 若动 build.gradle 串行;若只动 ui 文件可并行 |
