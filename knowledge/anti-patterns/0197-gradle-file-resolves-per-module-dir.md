---
doc_id: "ap-0197"
container: anti-patterns
platform: android
summary: "Gradle 脚本里传了 repo 根相对路径给 file(),配置文件/规则文件静默没生效,构建无报错但行为等于没配"
sedimented_by: auto
---

# NNNN — Gradle Kotlin DSL `file(path)` 按当前模块目录解析,repo 根相对路径需 `rootProject.file()`

- **平台**:android

## ❌ 错误

在子模块的 `build.gradle.kts`(或被子模块 apply 的脚本插件)里,用 `file("config/some-rules.xml")` 之类的 repo 根相对路径引用共享配置文件:

```kotlin
// 子模块 build.gradle.kts —— 意图指向 <repoRoot>/config/detekt.yml
someTool {
    config = file("config/detekt.yml")   // ❌ 实际解析为 <module>/config/detekt.yml
}
```

路径解析不到目标文件时,多数工具**不报错**,而是静默回落默认配置/默认行为 —— 构建绿灯,配置形同虚设,直到某天发现规则从未生效。

## 为什么

- Gradle 的 `Project.file(path)` 把相对路径按**当前 project 的 projectDir** 解析,不是 repo 根;子模块里调用就是子模块目录。
- 脚本插件(`apply(from = ...)`)里调用 `file()` 同样绑定到 apply 它的那个 project,不是脚本所在目录。
- 失败模式是静默的:文件不存在时 `file()` 照样返回一个 `File` 对象(它不做存在性检查),下游工具拿到不存在的路径往往走默认值分支,零告警。
- 在根模块调试时路径恰好正确(projectDir == rootDir),迁到子模块后才悄悄失效,更难察觉。

## ✅ 正确

```kotlin
// repo 根共享文件 → 显式挂 rootProject
someTool {
    config = rootProject.file("config/detekt.yml")   // ✅ 恒定按 rootDir 解析
}
```

- 引用 repo 根共享文件一律 `rootProject.file(...)`(或 `rootProject.layout.projectDirectory.file(...)`);模块自有文件才用裸 `file(...)`。
- 对"文件缺失即等于没配"的关键配置,加显式存在性断言快速失败:

```kotlin
val cfg = rootProject.file("config/detekt.yml")
require(cfg.exists()) { "missing shared config: $cfg" }
```

## lint

```bash
# 子模块 build.gradle.kts 中裸 file(") 且参数以共享配置目录开头 → warn 复查
grep -rn --include='build.gradle.kts' -E '[^.]file\("(config|scripts|gradle)/' . \
  | grep -v 'rootProject' \
  && echo 'WARN: 裸 file() 传疑似 repo 根相对路径,确认是否应为 rootProject.file()'
```
