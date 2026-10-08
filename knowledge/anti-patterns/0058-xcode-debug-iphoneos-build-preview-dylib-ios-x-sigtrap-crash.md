---
doc_id: "ap-0058"
container: anti-patterns
platform: cross
summary: "0058 Xcode 26 Debug-iphoneos build 默认注 __preview.dylib → iO…"
---

# 0058 Xcode 26 Debug-iphoneos build 默认注 __preview.dylib → iOS 16.x 真机启动 SIGTRAP crash

- **平台**:iOS(确认) / Android(❌ N/A,无 SwiftUI Previews 类机制)
- **复发次数**:1(实证 5 次连续真机启动 SIGTRAP)

## ❌ 错误 — 症状

iOS 真机连续启动 crash(iPhone X iOS 16.7,Xcode 26 beta build):

- App tap launch → 屏幕闪一下 → 退回桌面,启动即 crash
- idevicesyslog 0 行 App 相关(启动太快无 stdout)
- idevicecrashreport 拉 .ips:`bug_type 309 + EXC_BREAKPOINT (SIGTRAP)`
- crash thread frame 0 = `lldb_image_notifier`(dyld load 阶段)
- otool 看 `.app/`:`__preview.dylib + <App>.debug.dylib` 在顶层

## 为什么错(根因)

Xcode 26 起 Debug build 默认开 SwiftUI Previews 调试 dylib 注入(`ENABLE_DEBUG_DYLIB=YES`),原本只 simulator 用,Xcode 26 把 Debug-iphoneos build 也注入。iOS 16.x 真机 dyld 加载 `__preview.dylib` 时**load fail SIGTRAP**(dylib 链接到 simulator-only 符号 / iOS 16 dyld 不识别 SwiftUI Previews 协议)。

iOS 17+ 真机 dyld 改进可能不报错,但 iOS 16.x 真机一律 crash。

## ✅ 正确 — 修法

xcodebuild 必加 `ENABLE_DEBUG_DYLIB=NO`:

```bash
xcodebuild -project <App>.xcodeproj -scheme <App> \
    -destination 'platform=iOS,id=<UDID>' \
    -allowProvisioningUpdates -skipMacroValidation \
    ENABLE_DEBUG_DYLIB=NO \
    clean build
```

实证修复后:
- `__preview.dylib` 消失
- `<App>.debug.dylib` 消失(原本 0.5MB stub,主二进制要 dlopen)
- 主二进制自包含
- iOS 16.7 真机启动 OK

## 判定线

iOS task md 验证段 / shared-rules verify-build / iOS CLAUDE.md 编译验证规则段 必含:

```bash
grep "ENABLE_DEBUG_DYLIB=NO" task.md
grep "ENABLE_DEBUG_DYLIB=NO" <shared-rules>/verify-build.md
grep "ENABLE_DEBUG_DYLIB=NO" <ios>/CLAUDE.md
```

任一缺失 = 真机 build 不合格。

## Why 不上 lint

- xcodebuild build setting 是命令行 flag,文件层 grep 不到
- 替代方案:协调端 task md 模板硬编码 + iOS CLAUDE.md 编译规则段硬编码 + shared-rules verify-build 段硬编码,**3 处冗余**

## lint 状态

- iOS:协调端 CLAUDE.md / iOS CLAUDE.md / shared-rules verify-build 三处硬编码 ✅
- Android:N/A(Android 无 SwiftUI Previews 类机制)

## 关联

- shared-rules `verify-build.md` iOS 真机段(`ENABLE_DEBUG_DYLIB=NO` 必加)
- iOS crash 5 阶段诊断 sequence(本案为典型实例)
- 协调端 Bash 不跑 lldb / GUI / 长阻塞(stuck 让用户跑 / Dev session 跑)
