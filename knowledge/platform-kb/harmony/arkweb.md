---
doc_id: "platform-kb/harmony/arkweb"
container: platform-kb
platform: harmonyos
summary: "`@kit.ArkWeb` 的 `Web` 组件用法 + 渲染陷阱。"
---

# ArkWeb / Web 组件

> `@kit.ArkWeb` 的 `Web` 组件用法 + 渲染陷阱。看到 Web 渲染空白 / 加载 HTML 字符串 / 注入 theme CSS 时 Read。

## A. 渲染 HTML 字符串:用 data-URI src,不用 controller.loadData

后端返回**裸 HTML 字符串**(如协议 / 隐私页),要在原生 `Web` 壳里渲染。

**❌ 坑**:`controller.loadData(doc, "text/html", "UTF-8")` 在本场景渲染**空白**。
- hilog:`PageFailedProvisionalLoad … ERR_ABORTED(-3)`
- 根因:`WebviewController` attach 到 `Web` 组件有时序依赖;`loadData` 在 controller 尚未 attach 时调用 → abort。

**✅ workaround**:用 **data-URI 作 `src`**,只在内容 ready(loaded 态)时渲染 `Web`,消除 controller 时序依赖:

```ts
// doc = 已组装好的完整 themed HTML 字符串
Web({
  src: 'data:text/html;charset=UTF-8,' + encodeURIComponent(doc),
  controller: this.controller,
})
```

要点:
- `encodeURIComponent(doc)` 必须 —— 否则 HTML 里的 `#` / `&` / 空格破坏 URI。
- `charset=UTF-8` 必带,否则中文乱码。
- 配合 state machine(loading / error / loaded),**仅 loaded 态才 build `Web`**,不要一进页就 attach 空 controller。

## B. 注入 theme 色(dark/light 跟随系统)

CSS 内**不能用 `$r()`**(那是 ArkUI 资源引用,不是 CSS)。须取**当前有效色模式**的 literal 颜色注入:

```ts
// getColorSync 自动跟随 app 有效色模式(dark/light),无需手写分支
const bgArgb = resourceManager.getColorSync($r('app.color.bg_primary'));
const fgArgb = resourceManager.getColorSync($r('app.color.text_invert'));
const bgHex = argbToCssHex(bgArgb);   // 0xAARRGGBB → '#RRGGBB'
const fgHex = argbToCssHex(fgArgb);
// 注入:body{background:${bgHex}} + *{color:${fgHex}!important}
```

- `getColorSync` 跟随系统色模式 → dark/light 由构造保证一致,**无硬编码字面值**(满足反模式禁区:禁硬编码色)。
- `*{color:FG !important}` 对齐 Flutter 侧 `Html(style:{"*": Style(color: <文字色常量>)})` 的全局文字色覆盖。
- 建议抽复用模板(`argbToCssHex` + `buildThemedHtmlDoc`)放 `common/utils/`。

## 关联

- 非标准信封端点(裸 HTML 非 `{code,msg,data}`)的接收 → 见 `network-api.md §C`
- color token 真值 / dark 资源 → 见 `resources-system.md`
