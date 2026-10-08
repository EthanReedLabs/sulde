---
doc_id: "ap-0166"
container: anti-patterns
platform: android
summary: "0166 Material 2 主题使用 Material 3 专属组件导致静默不渲染"
---

# 0166 Material 2 主题使用 Material 3 专属组件导致静默不渲染

- **平台**:Android
- **复发次数**:1

## ❌ 错误

在继承 `Theme.MaterialComponents` 的 Material 2 页面中直接使用 Material 3 专属组件，例如 `materialswitch.MaterialSwitch`。代码可以编译、运行也不崩溃，但控件不可见。

## 为什么错

- Material 3 专属组件依赖 Material 3 主题属性和默认样式。
- Material 2 主题缺少对应属性时，组件的 track、thumb 或形状 drawable 可能为空。
- 因为没有崩溃且 XML 中确实存在控件，静态审计很容易把“存在”误判成“已渲染”；在空形状上追加 tint 也无法修复。

## ✅ 正确

- 在 Material 2 主题中使用兼容组件，例如 `switchmaterial.SwitchMaterial`，并按需显式配置 tint。
- 若必须使用 Material 3 专属组件，应先将该页面完整迁移到兼容的 Material 3 主题，而不是只替换单个控件。
- 遇到“编译通过、不崩溃、控件不显示”，优先核对组件所属 Material 版本与当前主题。
- 以运行时截图或真机验证作为渲染真值，不能只依赖 XML grep。

## lint 状态

- ✅ 可 lint：在 Material 2 主题范围内阻断已知 Material 3 专属组件，并为明确迁移的页面设置受控白名单。
- 人工 review：lint 未覆盖的新组件需核对主题属性依赖。
- 关联：静态存在不等于运行时渲染成功。
