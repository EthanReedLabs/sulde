---
doc_id: "ap-0062"
container: anti-patterns
platform: ios
summary: "0062 iOS 16.x Asset Catalog SVG `currentColor` + SwiftUI Im…"
---

# 0062 iOS 16.x Asset Catalog SVG `currentColor` + SwiftUI Image `.template` 渲染兼容性 bug

- **平台**:iOS
- **复发次数**:1

## ❌ 错误

iOS 真机 SVG 图标渲染**全部空白**,即使资源就位:

- 资源 cp ✅(全部 imageset)
- `Image(rawValue, bundle: .module).renderingMode(.template)` ✅
- assetutil 验证 `Assets.car` 含图标 ✅
- 但真机 iOS 16.x 渲染**透明 frame**(无 stroke 颜色)

## 为什么错

iOS 16.x SwiftUI Image 对 SVG `stroke="currentColor"` + `.renderingMode(.template)` 兼容性 bug:
- SVG 内部 `stroke="currentColor"` 在 iOS 17+ 由 Image template tint 解析为 `.foregroundColor` 值;
- iOS 16.x 解析失败 → stroke 颜色丢失为 transparent → 渲染空白;
- iOS 17+ 修复 → **模拟器(iOS 17)不复现,真机(iOS 16)才暴露** → 容易漏检。

## ✅ 正确

走 UIKit 桥接(`UIImage.withRenderingMode(.alwaysTemplate)` 走 UIKit SVG 渲染路径,全版本稳定):

```swift
@ViewBuilder
public var image: some View {
    if let sf = sfSymbolName {
        Image(systemName: sf).renderingMode(.template)
    } else {
        // iOS 16 兼容 — UIImage 桥接走 UIKit SVG 渲染路径(全版本稳定)
        Image(uiImage: UIImage(named: rawValue, in: .module, compatibleWith: nil)?
            .withRenderingMode(.alwaysTemplate) ?? UIImage())
            .resizable()
            .scaledToFit()
    }
}
```

**判定线**:iOS 任务涉及 Asset Catalog SVG + `.template` + `currentColor` → 必走 UIImage 桥接。

## lint 状态

- 协调端 task md 模板加"SVG `.template` 必 UIImage 桥接(iOS 16 兼容)"自检;
- 自动 grep:`grep "Image(.*bundle: .module)\.renderingMode(.template)" Sources/`(命中需 audit 是否 SVG + currentColor)。

## 关联

- 0061(协调端凭印象不查技术真值)— 父类反模式
