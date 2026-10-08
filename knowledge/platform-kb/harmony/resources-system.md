---
doc_id: "platform-kb/harmony/resources-system"
container: platform-kb
platform: harmonyos
summary: "HarmonyOS **资源目录同名覆盖**(0 代码改动):"
---

# 资源 / 主题系统

## A. dark mode 平台原生切换机制

HarmonyOS **资源目录同名覆盖**(0 代码改动):

```
entry/src/main/resources/
├── base/
│   ├── element/color.json     ← light 套(一组 app_* token)
│   └── media/foo.png          ← light asset
└── dark/
    ├── element/color.json     ← dark 套(同名 token,不同 hex)
    └── media/foo.png          ← dark asset(同名覆盖,system dark 时自动用)
```

`$r('app.color.app_text_primary')` 自动取 base 或 dark;`$r('app.media.foo')` 同。

## B. Flutter `*_dark.png` → 鸿蒙 `dark/media/<base名>.png`

Flutter 常用 `isDarkMode ? A.X_dark : A.X` 切换。鸿蒙 cp 去 `_dark` 后缀,放 dark/media/:

```bash
# Flutter <flutter>/assets/images/foo_dark.png → 鸿蒙 dark/media/foo.png(去 _dark 后缀)
cp <flutter>/assets/images/foo_dark.png \
   <harmony>/entry/src/main/resources/dark/media/foo.png
```

**Flutter 无 `_dark` 变体的 asset**:dark mode 也用 `base/media/` light 版(与 Flutter 同行为)。

## C. color token 表(light/dark 成对结构示例)

一套 token 在 base + dark 两表同名、hex 不同,页面只引 token 名。下表演示如何把 Flutter color 常量映射为鸿蒙 token(token 名 / hex 均为示例):

| token | light hex | dark hex | Flutter 对位常量 |
|---|---|---|---|
| app_bg1_primary | #FFFFFF | #111111 | APP_BG1 |
| app_bg2_card | #F8F8F8 | #1F1F1F | APP_BG2 |
| app_bg3_mask | #0A000000 | #0AFFFFFF | APP_BG3(black/white opacity 0.04)|
| app_bg4_alt | #FFFFFF | #444444 | APP_BG4 |
| app_text_primary | #333333 | #CCCCCC | APP_T1 |
| app_text_secondary | #666666 | #888888 | APP_T2 |
| app_text_tertiary | #999999 | #999999 | APP_T3 |
| app_text_quaternary | #CCCCCC | #444444 | APP_T4 |
| app_divider_strong | #E5E5E5 | #444444 | APP_L1 |
| app_divider_soft | #F2F2F2 | #2D2D2D | APP_L2 |
| app_brand_primary | #FCA14C | #FCAE65 | APP_BTN |
| app_contrast_invert | #FFFFFF | #000000 | APP_NORMAL/INVERT |
| app_alert_red | #F44336 | #F44336 | (跨主题同)|
| app_card_bg | #CD9269 | #A86E45 | 某卡片纯色底(若用 bg image 则忽略 token)|
| app_card_border | #FFE09F | #7A5300 | 某卡片 dashed border |
| app_card_content_text | #C68556 | #CD9269 | 某卡片正文 |
| app_card_source_text | #CE946A | #D4A17D | 某卡片出处 |
| app_card2_border | #0D000000 | #2D2D2D | 某卡片 border(light = #000 5% / dark = APP_DARK_L2)|

## D. 鸿蒙 resource naming 限制

- 仅 `[a-z0-9_]+`,首字符 a-z
- 不含 keyword
- 不可 `_` 开头 / `-` hyphen

Flutter `home_back_up_dark.png` 命名 OK → cp 为 `home_back_up.png` 放 dark/media/。

## E. 加新 token

base + dark 两表同时加 entry,name 一致,hex 不同:

```json
// base/element/color.json
{ "name": "app_X", "value": "#LIGHT" }

// dark/element/color.json
{ "name": "app_X", "value": "#DARK" }
```

ets 用 `$r('app.color.app_X')`,平台自动切换。

## F. Flutter Material Icons(font glyph)→ 鸿蒙映射策略

### F.1 根因
Flutter `Icon(Icons.image_outlined, color:..., size:..)` 渲染的是 **Material Icons 字体 glyph**,不是 png 文件 —— Flutter 工程 `assets/images/` 里**不存在** `image_outlined.png`。Dev 没法 `cp` 迁。看到 `Icons.xxx` 就喊"没法迁"是误判,必须按 F.2 顺序处理。

### F.2 处理顺序(优先级)

| # | 方案 | 适用 | trade-off |
|---|---|---|---|
| 1 | **`SymbolGlyph($r('sys.symbol.xxx'))`** | 优先 | 0 资源迁移,自动 dark 适配,系统级一致。**风险**:`sys.symbol.` 名要 verify,不存在就不渲染 |
| 2 | Material Symbols 官方 PNG 下载 → 鸿蒙 resources | SymbolGlyph 无对应/视觉偏 | 跟 Flutter 字体 hinting 不完全一致,但视觉等价;需 base + dark 双套 |
| 3 | ArkUI Shape/Path 自绘 | 极简图形(× / +) | 工时高,通常不值;复杂图标(如 image_outlined)别试 |

### F.3 SymbolGlyph 候选名速查

Material → 鸿蒙 `sys.symbol.<name>` 候选(Dev 实施时**真机渲染验证**,首个渲染成功的留下,全失败 → F.4 PNG):

| Material Icon | 候选 sys.symbol 名(按可能性排) | size 等价 | 用例 |
|---|---|---|---|
| `Icons.image_outlined` | **✅ `picture`(真机 verified)** / photo / image / pictures | 24 默认 | 某页底部加图按钮 |
| `Icons.close` | `xmark` / `close` / `x` | 16-24 | 弹窗/header 关闭 |
| `Icons.delete_forever` | `trash` / `delete` / `trash_fill` | 24 | 删除项 |
| `Icons.query_builder` | `clock` / `time` / `watch` | 12-16 | 计时 |
| `Icons.search` | `magnifyingglass` / `search` | 16-24 | 搜索框 |
| `Icons.arrow_back_ios` | `chevron_left` / `arrow_left` | 24 | 返回 |

### F.4 PNG fallback(SymbolGlyph 全失败时)

下载途径(让用户提供,不引第三方):
1. https://fonts.google.com/icons 选目标 icon → Style: **Outlined** → 24dp → 下载 PNG(`@1x` 24px、`@2x` 48px、`@3x` 72px;鸿蒙单分辨率即可,取 @3x 72px 居中)
2. 命名:**snake_case,无 _outlined 后缀**(eg `Icons.image_outlined` → `ic_image.png`),per §D naming 规则
3. 放置:`entry/src/main/resources/base/media/ic_image.png` + dark 同名覆盖(若需色差)
4. 用:`Image($r('app.media.ic_image')).fillColor($r('app.color.app_text_primary')).width(24).height(24)`(透明底 PNG + `.fillColor` 染色)

### F.5 SymbolGlyph size / color 写法

```ets
SymbolGlyph($r('sys.symbol.picture'))
  .fontSize(24)                                  // 等价 Material Icon size
  .fontColor([$r('app.color.app_text_primary')]) // 等价 color(数组语法)
  .fontWeight(FontWeight.Regular)
```

⚠️ `fontColor` 必须 **数组语法**(支持多色 symbol);单色用 1 项数组。

### F.6 判定线 / 反模式

- ❌ 看到 Flutter `Icons.xxx` 就喊"没法迁"放弃 — 必先按 F.2 顺序试 SymbolGlyph / PNG 下载
- ❌ 用项目已迁的其他 PNG 占位当某 icon — 视觉不对,handoff 必标偏
- ❌ 引第三方 icon font 库 — 违反"鸿蒙原生实现不引第三方漂移"规则
- ✅ Dev 先 SymbolGlyph candidate 全试 → handoff 报哪几个 render OK / 全失败 + 当下用 PNG(留 verify trace)
- ✅ 协调端 task md 写 Material Icons 用例时**必给 F.3 候选清单**,不让 Dev 自猜

---

## G. Dark mode visual verify 5 问

Dev 实施 + handoff 写完前必跑 dual-mode visual self-check(同 `translate-rules.md`,本段重复 reinforce 入资源系统 KB):

1. 此 asset Flutter 端有 `_dark` variant? — `ls <flutter>/assets/images/X_dark.png` verify
2. dark variant 迁鸿蒙 `dark/media/X.png` **文件名去 `_dark` 后缀**? — `ls resources/dark/media/X.png` verify
3. 鸿蒙端 `$r('app.media.X')` 在 light + dark mode 显示 image 不同? — 真机切 light/dark mode(App 内主题切换入口)visually verify
4. alpha mask 图 `.fillColor()` 用 dark-aware token(`$r('app.color.app_*')`)而非 literal hex? — grep 代码 verify
5. handoff §视觉对比表 **light + dark each ≥ 5 元素 ❌ ≤ 1**? — per handoff pre-merge gate 要求

任一 No → handoff 标 partial,**禁** 标 ✅ shipped。

## H. Page-specific hardcoded hex 处理(非通用 token 时)

某些 page 用 page-specific hardcoded hex(非 §C 通用系列),eg:

| Page | element | light hex | dark hex |
|---|---|---|---|
| 某页 A | page bg | `#FDFBF7` | `#111111` |
| 某页 A | notice card bg | `#FFFCF8` | `#1F1F1F` |
| 某页 B | share btn bg(某分支)| `#1AC68556`(C68556 alpha 0.1)| 同(该分支默认 light)|

### H.1 协调端 task md 必给 light + dark 一对儿 hex

协调端起 task md 时必列两 hex,**禁** 单值。

### H.2 Dev 实施用 const 显式存

```ts
private readonly PAGE_BG_LIGHT = '#FDFBF7';
private readonly PAGE_BG_DARK = '#111111';
@State private isDarkMode: boolean = false;

aboutToAppear() {
  // 跨 lifecycle 同 mode:per state-management §isDarkMode
  this.isDarkMode = (this.getUIContext().getHostContext()?.config?.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK);
}

build() {
  Stack() { ... }
    .backgroundColor(this.isDarkMode ? this.PAGE_BG_DARK : this.PAGE_BG_LIGHT)
}
```

### H.3 反模式

- ❌ 单 hex literal(失去 dark 自适应)— eg `.backgroundColor('#FDFBF7')` 在 dark mode 仍显示白
- ❌ 推断"这页用 BG1 / BG2"(可能 page-specific 非 token 真值)— grep Flutter 真值再断言
- ❌ Page-specific hex 加到 base/dark color.json 当 token(污染 token 命名空间,只有可复用 ≥ 3 page 才加 token)

详 `translate-rules.md`(grep-first)+ `state-management.md §isDarkMode`。

## I. Asset 命名映射 — 详 `translate-rules.md`

完整 Flutter ↔ 鸿蒙 asset 命名双向 lookup table 详 `translate-rules.md`,本 file 不重复维护,避免双 source。

---

## §J — Flutter `.withOpacity(N)` ↔ ArkUI ARGB hex alpha 对照

**Why**:Flutter `Color.withOpacity(0.05)` 转 ArkUI 等价 hex 需公式 + 表。

### 公式

```
alpha_byte = Math.round(255 × opacity)
hex_prefix = alpha_byte.toString(16).padStart(2, '0').toUpperCase()
ARGB hex = "#" + hex_prefix + RGB_no_prefix
```

例:APP_BTN(light `#FCA14C`) `.withOpacity(0.05)`:
- alpha = Math.round(255 × 0.05) = 13 = `0x0D`
- ARGB hex = `#0D` + `FCA14C` = `#0DFCA14C`

### 常用对照表

| opacity | alpha decimal | hex prefix | full hex 例(BTN light #FCA14C) | 等价 token |
|---|---:|---|---|---|
| 0.04 | 10 | `0A` | `#0AFCA14C` | app_bg3(透色实例)|
| 0.05 | 13 | `0D` | `#0DFCA14C` | app_brand_primary_a05 |
| 0.10 | 26 | `1A` | `#1AFCA14C` | app_brand_primary_a10 |
| 0.20 | 51 | `33` | `#33FCA14C` | app_brand_primary_a20 |
| 0.30 | 77 | `4D` | `#4DFCA14C` | |
| 0.40 | 102 | `66` | `#66000000` | sheet scrim |
| 0.50 | 128 | `80` | `#80FCA14C` | |
| 0.60 | 153 | `99` | `#99FCA14C` | |
| 0.70 | 179 | `B3` | `#B3000000` | dialog barrier |
| 0.80 | 204 | `CC` | `#CCFCA14C` | |
| 0.90 | 230 | `E6` | `#E6FCA14C` | |
| 1.00 | 255 | `FF` | `#FFFCA14C` 或 `#FCA14C` | 不透明 |

### Token 命名 convention

新 a05 / a20 半透 token 命名:`app_<role>_a<percent>`,base + dark 同 key 不同 hex:

```json
// base/element/color.json
{ "name": "app_brand_primary_a05", "value": "#0DFCA14C" }

// dark/element/color.json
{ "name": "app_brand_primary_a05", "value": "#0DFCAE65" }   // BTN dark
```

**rule**:加新半透 token 前查表 + 确认 light/dark 各对应 hex 真值。

**evidence**:某次实证发现 tip box color 应是 `BTN.withOpacity(0.05)` 而非 `BG2 实色`,前几轮 paste 错。

---

## §K — Image `fillColor` 栅格 png 不可靠,dark mode 用双 png 兜底

**症状**:dark mode 下 Image `fillColor($r('app.color.app_text_primary'))` 期望切亮色,实际栅格 PNG 颜色不变。

**根因**:`fillColor` 仅 alpha mask(SVG / 单色透明 png)生效;多色 / 实色像素 png 行为不一致。

**修法**:
- **优先**双 png 套(`base/media/X.png` + `dark/media/X.png` 文件名同),ArkUI 按 ColorMode 自动选
- 若仍用 fillColor 兜底,先 `file` 命令验 png 是 alpha mask + 像素扫描确认

**evidence**:多次修复均落到双 png 套 —— 某 icon 加 dark 变体、某 icon base + dark 双套、filter icon 双 png 套兜底。

**rule**:dark mode 翻色优先双 png 套,fillColor 兜底仅在 SVG / 已验 alpha mask 时用。详 `arkui-components.md` 配套段。

---

## §L — 主题资源选择统一入口:统一 helper 的 `pickResource / pickRawFile`

**症状**:浅色模式展示了暗色模式插图 / lottie;切换 light/dark 后普通 Image 刷新了,但 rawfile/lottie/canvas 仍沿用旧资源。

**根因**:Flutter 常见写法是 `isDarkMode ? xxx_dark : xxx`,鸿蒙翻译时容易把 `_dark` 资源硬编码进页面。`rawfile` / lottie 不能依赖 `resources/base` + `resources/dark` 同名覆盖自动切换,已加载的数据也不会因为组件 rebuild 自动换源。

**规则**:

1. 同名图片优先用系统 overlay:`resources/base/media/foo.png` + `resources/dark/media/foo.png`,页面只写 `$r('app.media.foo')`。
2. Flutter 真值存在显式成对资源(`foo` / `foo_dark`)时,鸿蒙用统一入口:`ImageThemeHelper.pickResource(lightResource, darkResource)`。
3. rawfile / lottie 用统一入口:`ImageThemeHelper.pickRawFile('common/lottie/foo.json', 'common/lottie/foo_dark.json')`。
4. 页面必须同时监听用户主题和系统主题:`@StorageProp(STORAGE_KEY.ThemeMode) @Watch('onThemeChanged')` + `@StorageProp(STORAGE_KEY.SystemColorMode) @Watch('onThemeChanged')`。
5. `onThemeChanged()` 内需要处理非普通 Image 的资源刷新:lottie/rawfile 重新选择 path 并 reload;canvas 重新 draw;PixelMap 重新 decode。
6. 发版前 grep `_dark`,确认每个命中都是统一 helper / `dark/media` / 明确 dark-only 逻辑,禁止页面硬编码 dark 资源。

**已验证案例**:某完成页浅色模式展示了 `foo_dark.json`。修复为 `ImageThemeHelper.pickRawFile('common/lottie/foo.json', 'common/lottie/foo_dark.json')`,并在主题变化时 reload lottie 与 redraw 动效。

---

## §M — Image/Icon tint 必须追 Flutter 动态 token + 验证鸿蒙染色能力

**症状**:Flutter dark/light 中同一个图标 tint 不同,但鸿蒙实现凭肉眼或 token 名把它写成固定白色;或写成 `$r('app.color.app_*')` 后在 App 内主题与系统主题不一致时取错色;或源码写了 `.fillColor(#111111)`,但真机仍显示 PNG 原始白色。

**根因**:
- Flutter 常见写法 `Image.asset(..., color: HexColor.APP_BG1)` / `Icon(..., color: HexColor.APP_T1)` 不是静态颜色,必须继续追 `hex_color.dart` 中 `isDarkMode ? dark : light`。
- Harmony `$r('app.color.app_*')` 跟随系统 ColorMode 资源 overlay;如果项目实际 dark/light 由 App 内设置控制,需要用统一主题 helper 的 `isDarkMode()` 显式选 light/dark。
- `fillColor` 只表达"用什么色染图",不表达"这个色跟随哪个主题源";翻译时必须补齐主题源。
- `fillColor` 对栅格 PNG 不可靠。即使源码传入 dark hex,真机也可能继续显示 PNG 原始像素色。必须验证资源是否真的被染色。

**强制流程**:
1. grep Flutter 调用点:`Image.asset(... color:)` / `Icon(... color:)` / `SvgPicture(... color/filter:)`。
2. 追 `HexColor.xxx` 定义和 `refreshColors()` / `isDarkMode` 切换点,写出 light hex + dark hex。
3. 判断鸿蒙页面主题源:若跟系统 ColorMode,才可直接 `$r('app.color.app_*')`;若跟 App 内主题,必须统一 helper 显式分支。
4. 对 PNG 使用 `.fillColor(light/dark)` 前,必须做像素/真机验证:源图是否 alpha mask、真机 dark/light 是否真的变色。
5. 若真机不变色,立即按 §K 走双 png:生成 `foo_dark.png` 或 `dark/media/foo.png`,并用 `ImageThemeHelper.pickResource()` 或系统资源 overlay 选择。
6. 验收表必须列 `Flutter ref + token + light hex + dark hex + Harmony resource/expression + 真机截图结果`,不能写"白色/黑色/反色"这种归纳。

**案例**:某编辑页提交按钮。

Flutter 真值:

```dart
Image.asset(
  A.assets_images_submit_ic,
  color: HexColor.APP_BG1,
)
```

`APP_BG1 = isDarkMode ? #111111 : #FFFFFF`,因此:
- light: 对勾 `#FFFFFF`
- dark: 对勾 `#111111`

鸿蒙最终修法:

```ts
Image(ImageThemeHelper.pickResource(
  $r('app.media.submit_ic'),
  $r('app.media.submit_ic_dark')
))
```

其中:
- `submit_ic.png` 保留 Flutter 原始白色像素。
- `submit_ic_dark.png` 从原图生成,保留 alpha,非透明像素改为 `#111111`。
- 不再依赖 `.fillColor()` 给该栅格 PNG 染色。
- 同一资源的所有调用点统一改,不要只修当前页面。

**反模式**:
- ❌ 把 `APP_BG1` 口头简化成"白色图标"。
- ❌ 只看当前设备 dark 截图,没切 light 验证。
- ❌ 未确认 App 内主题源,就把 tint 写成 `$r('app.color.app_bg1_primary')`。
- ❌ 源码写了 `.fillColor(#111111)` 就认为真机一定变黑,没有截图/像素验证。
- ❌ 只修一个页面的 `submit_ic`,漏掉同资源其他调用点。
- ❌ 代码修了但注释还写 `white` / `invert`,导致下一轮继续误导。
