---
doc_id: "ap-0161"
container: anti-patterns
platform: ios
summary: "KMP 将 Objective-C 可失败初始化器放入 Compose 列表组合路径"
---

# 0161 - KMP 将 Objective-C 可失败初始化器放入 Compose 列表组合路径

- **平台**: iOS / KMP Kotlin Native
- **复发次数**: 1
- **lint 状态**: pending

## 错误

在 `LazyColumn` item 的 `remember(uri)` 中同步创建 `AVAudioPlayer` 并调用
`prepareToPlay()`，同时相信生成的 Kotlin 类型足以保证初始化结果非空。

## 为什么错

Objective-C failable initializer 可在文件缺失、路径失效或媒体不可解码时返回 `nil`。
历史记录保存的 app sandbox 绝对路径在重装或容器变化后可能失效。Kotlin 编译通过不代表
native 初始化必定成功，紧接着调用成员会在组合阶段产生 Kotlin NPE，让整个页面崩溃。
此外，`remember` 不会切换线程，列表滚动时仍会在 UI 路径创建和准备播放器。

## 正确

1. 组合阶段只渲染持久化的 UI 数据，不创建 native 播放器。
2. 用户点击播放后先验证路径非空且文件存在，再惰性初始化播放器。
3. 将 failable initializer 包在可失败边界中，持有 nullable 结果，禁止 `!!`。
4. 只有 `play()` 成功后才进入播放 UI 状态；失败时保持可恢复界面。
5. 相同规则覆盖消息气泡、附件预览和其他所有媒体入口。

## 原生失败原因取证

Kotlin/Native 有时只暴露“nil 后被当作非空值”的 NPE，原生初始化器的上下文没有进入
Kotlin 异常。Debug 取证可在 Swift App 入口尽早注册 `NSSetUncaughtExceptionHandler`，
把 exception `name`、`reason`、时间和当前 probe id 写入 sandbox 中的诊断文件，再由真机
验证流程拉取。它只用于补全“最终抛出了什么”，不会凭空恢复初始化器没有返回的
`NSError`，也不能替代调用前的路径/文件/可解码性检查。

诊断文件必须脱敏、仅 Debug 启用、每轮覆盖或限量保留；处理器中避免复杂分配和业务调用。
验收仍以 nullable 边界与可恢复 UI 为准，不能靠全局异常处理器把崩溃当正常控制流。

## 检查

扫描 iOS `@Composable` / `remember` 中的 `AVAudioPlayer(`、`prepareToPlay()`，并检查
Objective-C `init?` 对应调用后是否存在立即成员访问或强制解包。
