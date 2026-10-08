---
doc_id: "ap-0168"
container: anti-patterns
platform: ios
summary: "0168 xcodebuild 全局覆盖 Bundle ID 导致 SPM 资源 bundle 撞名"
---

# 0168 xcodebuild 全局覆盖 Bundle ID 导致 SPM 资源 bundle 撞名

- **平台**:iOS
- **复发次数**:0

## ❌ 错误

为了生成临时验证包，在 `xcodebuild` 命令行全局传入 `PRODUCT_BUNDLE_IDENTIFIER`：

```bash
xcodebuild -scheme Example \
  DEVELOPMENT_TEAM=<TEAM_ID> \
  PRODUCT_BUNDLE_IDENTIFIER=com.example.app.debug build
```

## 为什么错

- 命令行 build setting 会作用于参与构建的所有 target，而不只作用于 App target。
- 多个 SPM 资源 bundle 因而获得相同的 `CFBundleIdentifier`。
- 系统按 bundle identifier 缓存 asset catalog，标识碰撞会导致跨 bundle 错误命中或资源查找失败。
- 即使资源实际存在于 `Assets.car`，运行时仍可能报告找不到图片，具有较强迷惑性。

## ✅ 正确

- 只修改 App target 的 Bundle ID 配置，不通过 CLI 全局覆盖 `PRODUCT_BUNDLE_IDENTIFIER`。
- 临时修改应限定在本地、保持可恢复且不得提交；构建时仅传入必要的签名团队覆盖，例如 `DEVELOPMENT_TEAM=<TEAM_ID>`。
- 更稳妥的长期方案是为 App target 配置专用 build configuration 或 `.xcconfig`，明确限定设置作用域。
- 构建后检查各资源 bundle 的 `CFBundleIdentifier` 是否唯一。

## lint 状态

- ❌ 非源码级问题，常规源码 grep 无法完整覆盖外部构建命令。
- 可在构建脚本或验证流程中阻断 CLI 传入 `PRODUCT_BUNDLE_IDENTIFIER`，并增加产物唯一性检查。
- 关联：xcodebuild 设置作用域、SPM 资源 bundle 与 asset catalog 缓存。
