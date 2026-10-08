---
doc_id: "ap-0113"
container: anti-patterns
platform: ios
summary: "TCA .cancellable(id:) metatype 编译失败 → CancelID { case x } i…"
---

# 0113 — TCA .cancellable(id:) metatype 编译失败 → CancelID { case x } idiom

- **平台**:iOS(TCA 特定;Android Kotlin Job/cancel 无此问题)
- **复发次数**:0

## ❌ 错误

TCA `.cancellable(id: <value>)` 要求 `id` 为 `Hashable` 值。常见错误是声明空 enum 作 marker type,传 metatype `.self`:

```swift
private enum TrendingFetchID {}    // 空 enum 作 marker
return .run { send in ... }
    .cancellable(id: TrendingFetchID.self, cancelInFlight: true)  // ❌ metatype 不 Hashable
```

编译期报错:`error: type 'X.Type' cannot conform to 'Hashable'`。metatype(`X.Type`)即使其底层类型 `X` 自身可哈希,metatype 本身**不**遵循 Hashable。

## 为什么错

Swift metatype(`X.Type`)与底层类型 `X` 的 Hashable 一致性是两件事 — metatype 默认**不**遵循 Hashable;TCA `.cancellable(id:)` API 签名要求 `some Hashable & Sendable`,传 metatype 编译期立即拒。

正确做法是用 case 值作 cancel id — case 是 enum 实例值,enum 默认 Hashable 一致性自动可用(只要关联值 Hashable;无关联值的 case 直接 Hashable)。

## ✅ 正确(全仓统一 idiom)

```swift
private enum CancelID { case trendingFetch }    // 带 case 的 enum
return .run { send in ... }
    .cancellable(id: CancelID.trendingFetch, cancelInFlight: true)  // ✅ case 值 Hashable
```

如需多个 cancel id,加 case:

```swift
private enum CancelID {
    case trendingFetch
    case audioPreview
    case search
}
.cancellable(id: CancelID.audioPreview, cancelInFlight: true)
```

## 判定线

- grep `.cancellable(id:.*\.self` Swift 文件 → 反模式。
- 全仓既有 `CancelID { case x }` 习语对齐(各 Feature 统一)。

## How to apply

- 协调端 task md 涉及 TCA `.cancellable(id:, cancelInFlight:)` 时,代码示例必用 `CancelID { case x }` idiom — **禁止**写空 enum + `.self`。
- Dev 实施时按"全仓既有习语"对齐(不自造方案)。
- task md baseline grep 全仓既有 cancellable 写法实证,代码示例与既有 idiom 一致。

## lint 状态

- ⏳ pending(grep 规则简单 `\.cancellable\(id:.*\.self` 可自动化)。

## 关联

- 不凭印象下发 task / 写代码示例 master。
- 协调端写技术文档凭印象编(同源根因)。
- iOS-only(TCA 特定)。
