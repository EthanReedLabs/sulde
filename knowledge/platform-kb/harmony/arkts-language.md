---
doc_id: "platform-kb/harmony/arkts-language"
container: platform-kb
platform: harmonyos
summary: "写 .ets / 看到编译 ERROR 前必读。"
---

# ArkTS 语言陷阱

> 写 .ets / 看到编译 ERROR 前必读。ArkTS strict mode + Flutter→ArkUI 转译陷阱累积。

## A. 类型 / Type System

| ❌ 禁 | ✅ 必 | 来源 |
|---|---|---|
| `any` / `unknown` / `as const` | 显式 interface 或 `Object` cast | ArkTS strict mode |
| `result.ok ? result.value : ...` discriminated union 反向 narrowing | `if (result instanceof ResultErr) {...}` class instanceof | 49 ERROR fix 实证 |
| 隐式 return type | 显式 return type annotation(`async method(): Promise<X>` 不可省 X)| arkts-no-implicit-return-types |

## B. @Prop / @State 名撞 CustomComponent 基类(必 rename)

| ❌ 撞名 | ✅ Rename |
|---|---|
| `@Prop borderColor` | `cellBorderColor` / `outlineColor`(撞 ArkUI 链式 `.borderColor()`) |
| `@Prop direction` | `swipeDirection` / `arrowDir`(撞 base method) |
| `@Prop enabled` | `isEnabled` / `interactive` |
| `@Prop id` | `recordId` / `itemId`(撞 base id())|
| `@Prop size` | `pageSize` / `viewSize`(撞 base size())|

错信号:`Property 'X' in type 'CustomComponent' is not assignable to base type 'CustomComponent'`。

## C. Result 窄化 / 异常处理

```ts
const r: Result<T> = await api.call();
if (r instanceof ResultErr) {
  hilog.warn(...);
  return;
}
// r 自动 narrow 为 ResultOk<T>,r.value 可用
```

**禁** `r.ok` / `r.success` 字段判断 — ArkTS discriminated union 不支持反向 narrowing。

## D. JsonHelper bool 强制

后端 0/1 number → bool 需走 `JsonHelper.optBool(json, 'key')`,否则 `late bool` 不报错但运行时偏 truthy。

## E. NavPathStack import

`@kit.ArkUI NavPathStack` 是 .ets 全局 declare class,**不 import**:

```ts
// ❌ 编译 ERROR
import { NavPathStack } from '@kit.ArkUI';

// ✅ 直接用
const navStack: NavPathStack = AppStorage.get<NavPathStack>('navStack') ?? new NavPathStack();
```

## F. @Link 必有 @State 源

`@Link` 子组件必由父 `@State` 字段绑;不能由 `private` / 普通 field 绑。**49 ERROR fix 教训**:

```ts
// ❌ 父根组件 `private navStack` 无法绑 @Link
// ✅ 子组件改普通 prop:`navStack: NavPathStack = new NavPathStack();`
```

## G. AppStorage.SetOrCreate 返回 void

`AppStorage.SetOrCreate('K', v)` 返回 `void` 不是 写入后取值;分两步:

```ts
AppStorage.SetOrCreate('navStack', new NavPathStack());  // void
const stack = AppStorage.get<NavPathStack>('navStack');  // 读取
```

注:小写 `setOrCreate` 是新 API;`SetOrCreate` deprecated 但当前可用。

## H. 资源类型限制(SDK 6.1.x)

`$r('app.integer.X')` **不支持**(整数资源),用 `$r('app.float.X')` 替(float.json 加 entry)。

## I-pre. @StorageProp / @StorageLink 走 STORAGE_KEY 常量(self-fix 实证)

```ts
// ❌ 字面量 — transpile drift:协调端不知项目实际 STORAGE_KEY value
@StorageProp('PlatformStatusBarHeight') statusBarHeight: number = 0;

// ✅ 走 STORAGE_KEY 常量(common/constants/StorageKeys.ts)
import { STORAGE_KEY } from '../../common/constants/StorageKeys';
@StorageProp(STORAGE_KEY.PlatformStatusBarHeight) statusBarHeight: number = 0;
```

EntryAbility / UserService 等写入端用 STORAGE_KEY 常量(value = `'app.platform.statusBarHeight'` 等内部命名),@StorageProp 读取端必同一常量 — 字面量不匹配 = AppStorage 取不到值。

## I. ArkUI 链式 modifier API 误名

| ❌ | ✅ |
|---|---|
| `Row().gap(12)` | `Row({ space: 12 })`(构造参,非 modifier)|
| `.borderBottom({...})` | `.border({ width: { bottom: 1 }, color: X })` |
| `LoadingProgress.alignItems(...)` | 不支持容器属性,外层 Row/Column 包 |
| `promptAction from '@kit.BasicServicesKit'` | `from '@kit.ArkUI'` 真路径 |

## J. `@Builder` 不支持对象参数子方法调用

**症状**:试图用对象参数把 callable slot 传进 Builder,编译 ERROR `10905204 '$$.trailing();' does not meet UI component syntax`:

```ts
// ❌ ERROR 10905204
@Builder TitledCard($$: { title: string; slot: () => void; trailing?: () => void }) {
  Column() {
    Row() { Text($$.title); $$.trailing?.(); }  // ❌
    $$.slot();                                   // ❌
  }
}
```

**原因**:ArkUI `@Builder` 限制 — 不能通过**对象解构调用函数子参数**(slot/trailing 必须独立 `@Builder` 或 `@BuilderParam`)。

**Workaround**:**inline 各结构 + 只共用标题 Builder + 数值常量复用**,放弃对象 slot 模式:

```ts
// ✅ 共用标题 Builder + inline Card 主体
@Builder
CardTitleBar(title: string) {
  Row() {
    Divider().vertical(true).strokeWidth(4).color($r('app.color.brand_primary'));
    Text(title).fontSize(12).fontWeight(FontWeight.Regular);
  }
}

// 各 Card 主体 inline:
Column() {
  this.CardTitleBar('某卡片标题');
  this.ChartSlot();          // 独立 method 渲染
}
.padding(16).backgroundColor($r('app.color.bg_card')).borderRadius(12)
```

**实证**:某卡片 TitledCard Builder 重构。

---

## K. @Builder param 是 by-value,内部 `${param}` 不 reactive

```ts
@Builder
section(stateLabel: string, ...) {
  Text(`parent state: ${stateLabel}`);  // ❌ 不 reactive — stateLabel 在 builder 调用时取 snapshot
}

build() {
  this.section(this.stateA, ...);  // 即使 @StorageLink stateA 变,Text 不更新
}
```

**症状**:builder param `string`(或 `number / boolean`)取调用时 snapshot,parent state 变 builder 内 Text 不刷新
**Workaround**:
- ✅ builder 内**直接 ref `this.stateX`**(内联 `Text(\`...: ${this.stateA}\`)`)
- ✅ 拆 `@Component`,用 `@Prop / @Link` 显式声明 reactive
- ❌ 禁:依赖 @Builder param 做 reactive UI

实证于某 4-candidate UI section 重构(初版 `section(label)` 不刷新,改 inline `this.stateA` 后 reactive OK)。

---

**未命中 rule** → handoff §upgrade 报 → 协调端追加。
