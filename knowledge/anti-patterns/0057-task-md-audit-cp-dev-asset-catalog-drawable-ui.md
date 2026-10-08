---
doc_id: "ap-0057"
container: anti-patterns
platform: none
summary: "0057 协调端 task md 漏 audit \"资源 cp 实证\" → Dev 实施漏拷资源 / Asset Ca…"
---

# 0057 协调端 task md 漏 audit "资源 cp 实证" → Dev 实施漏拷资源 / Asset Catalog / drawable 缺失 → UI 渲染空白

- **平台**:协调端(task md 写作类) + 双端实施
- **复发次数**:1

## ❌ 错误 — 症状

真机实测 — 首页 share / download / heart 按钮**没有图标**(空白)。协调端 audit 实情:

- 图标组件注释明示"fallback 读 bundle 里的 lucide SVG(Dev 把 SVG 拷到 Assets.xcassets/LucideIcons/)"
- 共享资源目录 ✅ **42 个 SVG 资源存在**
- `Sources/CoreUI/Resources/Assets.xcassets/LucideIcons/` ❌ **目录不存在**(Dev 实施时漏 cp)
- 所有 lucide icon 调用渲染空白

## 为什么错(根因)

协调端写 task md 时**没把"cp 资源到 bundle"明确列入 Step + 验证步骤**,Dev 严格按 task md 跑 → 实施完代码但**漏拷资源** → 真机 UI 空白。

simulator 实测未发现因为 SF Symbol fallback 路径(部分 lucide 有 SF Symbol 等价)— 真机才暴露。

## ✅ 正确 — 修法

协调端 task md 模板补"资源依赖实证"段:

1. **写 task md 时,grep 代码中所有资源引用**:`Image("xxx") / UIImage(named:) / @drawable/ / R.drawable.x`
2. **Step N 必含**:从 `pen-truth/<page>/resources/` 或 `_shared/<asset>` cp 到 iOS Asset Catalog / Android res/drawable
3. **handoff 必含**:`ls Sources/.../Assets.xcassets/<NewAssetDir>/ | wc -l` 实证资源数
4. **真机实测必含**(iOS hard rule):UI 含资源场景必跑真机看是否真显

## 判定线

协调端 task md 涉及新建 / 引用 Asset Catalog / drawable / lucide / SVG / font 等资源时,**必含"资源 cp 实证"段**:

```bash
grep -E "资源 cp 实证|Asset Catalog|cp .*\.svg|imageset|drawable|UIImage\(named|Image\(\"" task.md
```

任一缺失 = task md 不合格。

## lint 状态

- iOS:⏳ TODO(`grep "Image\(\".*\")" Sources/` 列调用 vs Asset Catalog ls 对照)
- Android:⏳ TODO(`grep "@drawable" res/layout/` vs `ls res/drawable/`)
- 协调端:CLAUDE.md 派单格式加"资源依赖实证"自检

## 关联

- 协调端凭印象 — 本条是其在"资源 cp"维度的具体子集(协调端没 audit Dev 实施时是否真拷资源)
- boilerplate 反模式 — 不同维度(那是代码 boilerplate,本条是资源 cp 实证)
- 真机 hard rule — 真机实测才能暴露此类 bug
