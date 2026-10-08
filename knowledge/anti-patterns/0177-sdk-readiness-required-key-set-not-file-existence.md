---
doc_id: "ap-0177"
container: anti-patterns
platform: cross
summary: "0177 SDK 就绪判据只检查配置文件存在而未检查必需键集合"
---

# 0177 SDK 就绪判据只检查配置文件存在而未检查必需键集合

- **平台**:跨端
- **复发次数**:1

## ❌ 错误

启动 SDK 前只判断配置文件是否被打包：

```swift
if Bundle.main.path(forResource: configName, ofType: "plist") != nil {
    FirebaseApp.configure()
}
```

## 为什么错

文件存在只证明资源被打包，不证明它对目标 SDK 语义完整。多个 SDK 共享或生成相似配置文件时，文件可能缺少当前 SDK 必需的键，弱就绪判据会把配置错误推迟到启动期异常。

## ✅ 正确

为每个 SDK 定义必需键集合，并检查键存在、值非空且格式合法后再初始化。例如 Firebase 配置至少应按所用能力校验公开配置键，包括 `GOOGLE_APP_ID`：

```swift
if let path = Bundle.main.path(forResource: configName, ofType: "plist"),
   let plist = NSDictionary(contentsOfFile: path),
   let appID = plist["GOOGLE_APP_ID"] as? String,
   !appID.isEmpty {
    FirebaseApp.configure()
}
```

构建期应校验目标环境的完整键集合；运行时采用 fail closed，并输出不含配置值的可诊断错误。

## lint 状态

- ✅ 可在构建期校验各 SDK 配置文件的必需键集合与格式。
- 人工 review：文件名相同或配置复用时，确认其语义属于当前 SDK 与环境。
- 关联：缺文件与文件存在但语义不完整是两个独立配置风险。
