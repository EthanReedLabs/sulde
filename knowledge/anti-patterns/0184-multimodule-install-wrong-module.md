---
doc_id: ap-0184
container: anti-patterns
platform: android
summary: 代码明明改了,真机上还是旧行为——排查半天发现 install 任务跑的不是应用模块
related: [work-model/verify-build, ap-0048]
---

# 0184 — 多模块工程 install 跑错模块,制造"改了没生效"假象

- **平台**:Android(Gradle 多模块;其他构建系统同理)

## ❌ 错误

在多模块工程里凭模块名直觉跑 install 任务(如对共享 UI/库模块执行
`:<库模块>:installDebug`),装上的是该模块自带的测试/演示 APK,
真正的应用模块从未更新。

## 为什么

多模块工程里多个模块都能产出可安装的 APK(库模块的 androidTest/demo 包同样能装)。
装错模块不报任何错——设备上出现的是旧版应用 + 一个不起眼的测试包,
表现为"代码已改而设备仍是旧行为",极易被误诊为缓存、构建增量或代码本身的问题,
排查方向整个跑偏。

## ✅ 正确

- install 一律用**应用模块**的任务(`:<应用模块>:installDebug`);
  不确定哪个是应用模块时 `./gradlew projects` + 查 `com.android.application` 插件
- 安装后按 verify-build 的显式验证步确认新包生效(versionCode/构建时间戳/
  可观察的行为差异),不拿"安装命令 exit 0"当证据——同族陷阱见 ap-0048
  (验证时拣到旧产物,同样是"证据无效"型假象)
