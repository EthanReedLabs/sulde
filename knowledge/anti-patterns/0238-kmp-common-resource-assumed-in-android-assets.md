---
doc_id: "ap-0238"
container: anti-patterns
platform: android
summary: "KMP 公共源码集里存在资源文件并不证明它会进入 Android APK assets；编译和状态测试全绿，安装后仍可能在首次读取时崩溃。"
related: [ap-0057, ap-0224]
---

# 0238 — 误以为 KMP 公共资源会自动进入 Android APK Assets

- **平台**：Android / Kotlin Multiplatform
- **复发次数**：1

## ❌ 错误

把 prompt、配置或模型词表放进 KMP 公共源码集的 resources 目录，Android 端直接用
`AssetManager.open(relativePath)` 读取。源码存在、模块能编译、状态机测试全绿，就认定资源
已经可用。安装后首次创建模型或业务引擎时才因 `FileNotFoundException` 崩溃。

## 为什么错

- KMP resources、JVM classpath resources、Compose Multiplatform Resources 和 Android
  assets 是不同打包契约。
- 具体文件是否进入 APK/AAB、以什么路径出现，取决于插件、target 和 source-set 配置。
- 单元测试往往从宿主文件系统或测试 classpath 读取，没有经过最终 Android 产物。
- 依赖注入外层常把底层资源异常包装成“实例创建失败”，掩盖真正缺失路径。

## ✅ 正确

1. 当前仅 Android 消费时，把文件放在明确的 Android assets source set，并让读取 API 与
   打包位置一致。
2. 真正跨端共享时使用明确的 multiplatform resource 方案，为每个平台实现资源可达性测试。
3. 构建后列出 APK/AAB 内的预期路径；不能只检查源码目录或 `assemble` 返回成功。
4. 在安装包环境执行一次真实读取，并覆盖 Debug、Release、压缩与 shrink 配置。
5. 资源加载错误保留 expected path 和底层异常，便于从依赖注入失败追到打包层。
6. Kotlin/AGP/Compose 工具链升级后重跑产物级检查，不能把旧版本行为当永久契约。

## lint 状态

- ⚠️ 可检：Android `AssetManager` 路径对应文件只存在于公共 resources，Android assets 中
  没有同路径文件或显式打包配置。
- ✅ 构建门禁：解包 APK/AAB 并断言关键运行时资源路径存在，再执行设备/仪器化读取测试。
- ❌ 源码文件存在、编译成功或 JVM 单元测试通过都不是 Android 资源可达性证据。
