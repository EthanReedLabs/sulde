---
doc_id: "ap-0129"
container: anti-patterns
platform: cross
summary: "0129 后端 boolean 字段语义不明时直传 UI state 不取反 + 标 #once 跳过沉淀"
---

# 0129 后端 boolean 字段语义不明时直传 UI state 不取反 + 标 #once 跳过沉淀

- **平台**:iOS / Android
- **复发次数**:0

## ❌ 错误

后端 boolean 字段语义不明(如 `openWatermark` = "是否加水印" vs "是否去水印"),接 UI state(`isRemoveWatermark`)时不 verify 语义就直传,且 commit 标 `#once`(一次性,无需沉淀):

```swift
// ❌ 凭印象猜成正向,未取反
openWatermark: state.watermark.isRemoveWatermark
```

`isRemoveWatermark` = UI"去水印开关"(用户点了 = true)。真值 `openWatermark` = "是否加水印"。**直传 = 语义颠倒**:用户点去水印 → `openWatermark=true` → 后端理解"加水印" → 反向行为。

`#once` 反沉淀效应:不进反模式集合 / 无 lint / 不派跨端 audit → 同一映射错误**一次性铺到多个共用该组件的 Feature** + **埋雷数周**。

## 为什么错

- 凭字段名(open / enable / disable / show)直觉映射,不 verify 真值。
- 共享 UI state 接多个 Feature 时,各自分支映射 → 一次错铺多处。
- `#once` 跳过沉淀流程 = 天然可复发的错误不留痕。

## ✅ 正确

```swift
// 接后端 boolean 前必先确认语义(抓 web 真包 / 对照另一端真值)
openWatermark: !state.watermark.isRemoveWatermark   // 真值:openWatermark = "是否加水印"
```

共享 UI state 接多 Feature 时,映射逻辑**收敛到 Adapter 层一处**:

```swift
private func mapWatermark(_ removeWatermark: Bool) -> Bool { !removeWatermark }
// 多个创作流都 call mapWatermark(...)
```

铁律:
1. 接后端 boolean 前必先确认语义(抓 web 真包 / grep 另一端实证 / 读后端文档),禁凭字段名直觉映射。
2. 语义类映射 bug **禁标 `#once`**(天然可复发),必走沉淀流程。
3. 共享 UI state 接多 Feature 时,映射逻辑必收敛到一处(Adapter 层 helper)。
4. 协调端起 task md 时 boolean 字段必 quote `mapping verified by:`(真包 url / git log -S verify / 文档段)。
5. `#once` 严限"一次性误操作 / 填错 URL / typo / 单点 hardcode";涉映射 / boolean 语义 / 共享组件接线 → 禁 `#once`。

## lint 状态

❓ 仅人工 checklist — soft 警告:commit message 含 boolean 字段映射关键词(`openX`/`enableY`/`toggle`)+ 标 `#once` → 警告"boolean 语义映射禁 #once"。语义验证 lint 不能 100% 抓,需 reviewer 主动问"boolean 真值 verify 了吗?"

## 关联

- adapter wrap ≠ 真链路(同源:凭印象映射不 verify)
- 自发修复 mini-checklist(scope 是否只在原 bug 内)
