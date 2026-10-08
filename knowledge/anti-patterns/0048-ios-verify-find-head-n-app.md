---
doc_id: "ap-0048"
container: anti-patterns
platform: ios
summary: "0048 iOS verify 任务 `find ..."
related: [ap-0184]
---

# 0048 iOS verify 任务 `find ... | head -1` 拣到 N 天前旧 .app → 验证证据无效

- **平台**:iOS(verify 流程类)
- **复发次数**:≥4

## ❌ 错误 — 症状

`xcrun simctl install` + `launch` 跑起来的 App 表现与代码不符。改完默认 Real 路径后,simulator 跑的还是 Mock 路径 — 实际是 install 了多天前的 .app,新 build 根本没 install。

## 为什么错(根因)

`~/Library/Developer/Xcode/DerivedData/<App>-<hash>` 累积 N 个不同 hash 子目录(跑了多次,每个 worktree / clean build / scheme 切换都生成新 hash)。

shared-rules `verify-build.md` 的 install 步骤里若用 `find ~/Library/Developer/Xcode/DerivedData/<App>-* -name <App>.app | head -1`,**`find` 默认按目录顺序而非 mtime 倒排** → 拣到的可能是多天前的旧 build。

→ verify 任务的"截图证据"实际可能跑的是旧版本,**客观证据失效**(截图 ✅ 但 ✅ 的是旧 build)。

## ✅ 正确 — 修法

1. **install 路径必按 mtime 倒排 + 主动清理**:
   ```bash
   # 选最新 .app
   APP_PATH=$(find ~/Library/Developer/Xcode/DerivedData/<App>-*/Build/Products/Debug-iphonesimulator -name "<App>.app" -exec stat -f "%m %N" {} \; 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)

   # 跑完清理非最新 hash 目录
   ls -dt ~/Library/Developer/Xcode/DerivedData/<App>-*/ | tail -n +2 | xargs rm -rf
   ```
2. **shared-rules `verify-build.md` install 段强制写 mtime 选包**
3. iOS task 提供 `scripts/run-app.sh` 一键(build → 选最新 .app → install + launch → 清旧)
4. **framework link 不等于 App 已重打包**：KMP 只跑 framework/link smoke 后，必须再跑
   Xcode App target 的 device build。安装前记录 `.app` 主二进制与内嵌 Kotlin framework
   的 mtime/哈希，确认它们来自本轮构建；只看到 framework 任务成功不得复用旧 `.app`。

## 判定线

iOS verify task md 的 simulator install 段若出现 `head -1` / `head -n 1` 而无 `sort -rn` mtime 排序 → 违规。协调端 review 时 grep:

```bash
grep -rn "DerivedData/.*head -1" .ai-workspace/tasks/ scripts/  # 应 0 命中
```

真机 probe 若本轮没有 Xcode App target build 记录，或 `.app` 内 framework 摘要与本轮产物
不一致，也按旧包证据处理，不得用结果判断修复有效/无效。

## lint 状态

- iOS:⏳ TODO(可加 pre-commit grep 检查)
- Android:❌ N/A(`assembleDebug` 输出固定路径 `app/build/outputs/apk/debug/app-debug.apk`,无 hash)

## 关联

- shared-rules `verify-build.md` install 段(必带 mtime 选包)
- 客观证据失效(截图证据指向错版本)
