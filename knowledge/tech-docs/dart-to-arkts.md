---
doc_id: "tech-docs/dart-to-arkts"
container: tech-docs
platform: none
summary: "把一套 Flutter(Dart + GetX)现有实现逐页迁到 HarmonyOS(ArkTS + ArkUI St…"
---

# Flutter/Dart → HarmonyOS/ArkTS 转译规则总纲

> 把一套 Flutter(Dart + GetX)现有实现逐页迁到 HarmonyOS(ArkTS + ArkUI Stage Model)时的**语言 / 范式级映射 + 转译纪律**。
>
> 本文是**方法论总纲 + 语言级映射**;逐条 widget / API 查表走两份平台速查:
> - UI widget 映射字典(`Container`/`Row`/`Positioned`/`ListView`… → ArkUI)→ `../platform-kb/harmony/translate-rules.md`(R-01~R-23)
> - ArkTS 编译陷阱 / strict-mode 语言坑 → `../platform-kb/harmony/arkts-language.md`(A~K)
>
> 分层原因:widget 映射与编译坑是"事实速查",条目多、随平台 SDK 版本增删;本文是"怎么想"的稳定层,换页不变。

---

## 1. 范式映射(先对齐心智模型)

Flutter 命令式 + GetX 响应式控制器 → ArkUI 声明式 UI + 内建状态装饰器。整页翻译前先建立这张对照,避免逐 widget 直译却丢失架构语义:

| Flutter / GetX | ArkTS / ArkUI | 说明 |
|---|---|---|
| `StatelessWidget` / `StatefulWidget` | `@Component struct` + `build()` | 声明式 UI 单元 |
| `GetView<Ctrl>` / `GetBuilder` | `@Component` + `@State` / `@StorageProp` | 控制器状态下沉到组件装饰字段 |
| `controller.update(['id'])` 局部刷新 | `@State` 变更自动响应 | ArkUI 无需手动 id 刷新 |
| `Get.to(() => Page())` / `Get.toNamed` | `Router.push(Routes.X, params)` | 命名路由映射 |
| `Get.back()` | `Router.pop()` / `Router.back()` | — |
| `Get.dialog(W)` | `CustomDialogController({ builder }).open()` | 弹层承载层不同,详 §5 依赖闭包 |
| `Obx` / `GetX` 响应包裹 | `@State` / `@Link` / `@StorageLink` | 响应式绑定粒度不同 |

> 路由 / 状态细节映射走 `../platform-kb/harmony/routing-navigation.md` + `state-management.md`。

---

## 2. 语言 / 类型系统映射(Dart → ArkTS)

ArkTS = TypeScript strict 超集 + 额外禁令(禁 `any` / `unknown` / 结构化 narrowing)。以下是语言层最易翻车的几处,**与具体 widget 无关,任何页都适用**。

### 2.1 判别联合(discriminated union)必用 `instanceof`,不用字段判别

Dart 常见 `sealed class` + `switch` 穷尽;ArkTS **不支持反向 narrowing**——不能靠 `result.ok` / `result.success` 布尔字段把类型收窄。必须走 class `instanceof`:

```ts
const r: Result<T> = await api.call();
if (r instanceof ResultErr) {
  hilog.warn(...);
  return;
}
// r 在此自动 narrow 为 ResultOk<T>,r.value 可用
```

❌ 禁 `r.ok ? r.value : ...` 一类字段判别——编译不报错但类型收窄失效。

### 2.2 空安全 / 隐式布尔:后端 0/1 → bool 必显式转

Dart `late bool` 缺值不报错,运行时偏 truthy;翻到 ArkTS 后端 `0/1` number → bool 必走显式转换 helper(如 `JsonHelper.optBool(json, 'key')`),禁直接当布尔用。

### 2.3 返回类型不可省

ArkTS `arkts-no-implicit-return-types`:`async method(): Promise<X>` 的 `X` 不可省,所有方法显式标注返回类型。

### 2.4 `any` / `unknown` / `as const` 全禁

用显式 `interface` 或 `Object` cast 替代。这是 ArkTS strict mode 的硬约束,不是风格建议。

> 完整编译陷阱表(装饰字段撞基类名、`AppStorage.SetOrCreate` 返回 void、`@Builder` 对象参数限制、`@Builder` param by-value 不 reactive、资源类型限制等)→ `../platform-kb/harmony/arkts-language.md`。翻译遇到编译 ERROR **先查那张表再动手**。

---

## 3. 单位 / 尺寸 / 色值 / 字重的语言级映射

这四类是"跨每一页复用"的系统性映射,单独列出(逐 widget 视觉属性映射见 platform-kb translate-rules.md R-06/R-07/R-05)。

### 3.1 单位系统

| Flutter(ScreenUtil) | ArkTS/ArkUI | 备注 |
|---|---|---|
| `.w` | `vp`(直接数值) | 逻辑像素 |
| `.sp` | `fp`(直接数值) | 字号 |
| `1.sw` / `1.sh` | `'100%'` 宽 / 高 | 屏占比 |
| `EdgeInsets.only(left, right)` | `.padding({ left, right })` | — |
| `EdgeInsets.fromLTRB` | `.padding({ left, top, right, bottom })` | — |

### 3.2 色值:走系统资源 token,不硬编码 hex

Flutter 侧语义色常量(下用中性名 `APP_*` 示意)→ ArkUI `$r('app.color.*')` 资源 token,后者随系统 light/dark **自动切换**:

| Flutter | ArkUI |
|---|---|
| `HexColor.APP_T1` | `$r('app.color.text_primary')` |
| `HexColor.APP_BG1/BG2/BG3` | `bg1_primary / bg2_card / bg3_mask` |
| `HexColor.APP_BTN` | `$r('app.color.brand_primary')` |
| `HexColor("#FFFFFF")` 单色字面量 | `'#FFFFFF'` 直接字符串 |
| `HexColor("#X").withOpacity(0.2)` | `'#33X'` 8 位 hex(alpha 前置):0.2=0x33 / 0.1=0x1A / 0.05=0x0D |

**禁**把 Flutter 语义色的 hex 字符串直接搬进 ArkUI——会丢失自动 dark 切换。语义 token 的 light/dark 双 hex 真值表见 translate-rules.md R-18;页级非语义硬编码 hex 用 `@State isDarkMode` 双值显式存(R-20.5)。

### 3.3 字重:w600 ≠ Bold

| Flutter weight | ArkUI |
|---|---|
| w400 / Regular | `FontWeight.Regular` / `Normal` |
| w500 / Medium | `FontWeight.Medium` |
| **w600 / SemiBold** | **`.fontWeight(600)` 数值**(ArkUI 无 SemiBold 枚举) |
| w700 / Bold | `FontWeight.Bold` |

❌ 禁用 `FontWeight.Bold`(=700)替 Flutter `w600`——偏粗、视觉不一致。

---

## 4. Widget 映射字典(索引,详表在 platform-kb)

逐 widget → ArkUI 组件的映射构成一部 `R-XX` 编号字典,transpile 时**逐行 ref**。这里只列骨架,完整表 + 每条陷阱在 `../platform-kb/harmony/translate-rules.md`:

| 段 | 覆盖 |
|---|---|
| R-01 / R-02 | 容器(`Container`/`Row`/`Column`/`Stack`/`Expanded`/`SizedBox`)、`Positioned` / `Align` 定位 |
| R-03 / R-04 | Image / Text(具体 enum/API 在 `arkui-components.md`) |
| R-07 / R-08 | 圆角 / 边框 / 虚线 视觉;Flexbox 主轴/交叉轴对齐 |
| R-09 | Scroll / List / Grid — spacing 默认 0 铁律、`width('100%')` + margin 溢出、`ListView.padding` 内容内 inset、`AlwaysScrollable` → `alwaysEnabled` |
| R-11 | Scaffold + AppBar → 自定义标题栏 + 状态栏 SafeArea |
| R-21 | Flutter halo/glow(`ImageFiltered + TileMode.decal`)→ ArkUI 多层 `.shadow()` 叠白 |
| R-22 / R-23 | 弹层 / 侧滑 / 行内富文本翻译 gate;公共 UI 依赖闭包 gate |

> 字典外 widget / 无对应 rule → handoff §upgrade 报"行 X 无 rule 映射,用 Y workaround,需补 rule",协调端 review 后追加。

---

## 5. 转译纪律(硬约束,决定一致性成败)

语言/字典对了但纪律松,仍会翻车。以下四条是复盘反复验证出的铁律。

### 5.1 grep-first 真值铁律

UI / UX / 业务"不一致"时,**第一动作 = grep Flutter `file:line` 抓真值**,禁猜数值 / 字重 / 色值 / 边距。典型翻车模式:凭印象用了近义 token(分隔线 strong vs soft 差一档灰)、字重无脑 Bold、边框宽度猜非零。

应用步骤:
1. 用户报"不一致" → grep Flutter dart 文件 + Read 行号 + 记原始 hex / 字重 / 边距
2. 必 grep 色值 token 定义文件拿 token hex,禁假设"语义近似 = 值近似"
3. Flutter `isDarkMode ? A : B` 分支 → 鸿蒙 `@State isDarkMode` 双值
4. 翻译 self-verify 表:Flutter `file:line` ↔ ArkUI `file:line` ↔ 一致?

### 5.2 逐行 trace 表

handoff §0 必逐行 cite `Flutter file:line → R-XX → 鸿蒙 file:line → ✅/❌`。一行代码对一条 rule 对一处落地,可回查、可追责。

### 5.3 公共 UI / 弹层依赖闭包(不能只迁调用点)

命中自定义公共 UI(Dialog helper、共享按钮、标题栏、refresh header)或 Flutter 三方 widget wrapper 时,必须继续追 `public API → private builder → theme/resource → 三方默认参数`,再决定 ArkUI 映射。承载层(route/overlay/barrier/safeArea/transition)、内容层、文本层、按钮层、主题层、资源层、三方默认层逐维反抽——禁用系统默认 dialog/menu 样式替代自绘。缺依赖闭包表 → 禁实现、禁验收、禁声明 shipped(详 R-22/R-23)。

### 5.4 双 mode 自检(light + dark)

asset 迁移 + 真机 verify 必双 mode 过一遍:dark variant 是否迁到 `dark/` 目录且文件名去 `_dark` 后缀、alpha mask 图 `.fillColor()` 是否用 dark-aware token、两 mode 切换后视觉对比表 ❌ 数达标。任一 No → handoff 标 partial,不标 shipped。asset 命名双向 lookup 铁律详 R-20。

---

## 6. 交叉引用

| 需要什么 | 去哪 |
|---|---|
| 逐 widget → ArkUI 映射字典(R-01~R-23) | `../platform-kb/harmony/translate-rules.md` |
| ArkTS 编译陷阱 / strict-mode 语言坑(A~K) | `../platform-kb/harmony/arkts-language.md` |
| ArkUI 组件具体 enum / API | `../platform-kb/harmony/arkui-components.md` |
| ArkUI 不可共存组合 / workaround | `../platform-kb/harmony/arkui-incompatibility.md` |
| 路由 / 导航 / overlay | `../platform-kb/harmony/routing-navigation.md` |
| 状态管理 / isDarkMode 双值 | `../platform-kb/harmony/state-management.md` |
| 资源系统 / 色值 token 表 | `../platform-kb/harmony/resources-system.md` |

> 本文与平台速查的分工:**本文回答"Flutter→ArkTS 该怎么想"(范式 + 语言 + 纪律),平台速查回答"这一行具体映射成什么"**。写 .ets 遇编译 ERROR 或查具体 widget → 先翻 platform-kb;建心智模型 / 定纪律 → 看本文。
