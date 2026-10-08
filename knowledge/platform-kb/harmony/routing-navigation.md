---
doc_id: "platform-kb/harmony/routing-navigation"
container: platform-kb
platform: harmonyos
summary: "集中式路由常量 + 薄封装 util,是 ArkUI 端替代 Flutter GetX 命名路由的通用形态:"
---

# 路由 / 导航

## A. Routes / Router util

集中式路由常量 + 薄封装 util,是 ArkUI 端替代 Flutter GetX 命名路由的通用形态:

```ts
// common/constants/Routes.ts
export enum Routes {
  Login = 'login',
  List = 'list',
  Detail = 'detail',
  SubDetail = 'sub-detail',
  // ...
}

// common/utils/Router.ts
Router.push(Routes.X, params: object | undefined);
Router.pop();
Router.replaceUrl(Routes.X, params);
```

## B. 路由 pattern:**禁 `@Entry` 新 page**

子页面用 `@Component + NavDestination`。`@Entry` 仅根壳页(RootMainPage 等顶级)。

```ts
@Component
export struct SomePage {
  build() {
    NavDestination() {
      // page content
    }
    .title('某页标题');
  }
}
```

## C. NavPathStack

`@kit.ArkUI NavPathStack` **全局 declare class,不 import**(详 `arkts-language.md §E`):

```ts
const navStack: NavPathStack = AppStorage.get<NavPathStack>('navStack') ?? new NavPathStack();
```

根壳页内 `Navigation(navStack) { ... }.navDestination(this.pageMap)`,pageMap 是 `@Builder pageMap(name: string)` 含 `case Routes.X: SomePage(...);`。

## D. Get.to / Get.dialog 映射

| Flutter | ArkUI |
|---|---|
| `Get.to(()=> Page())` | `Router.push(Routes.X, params)` |
| `Get.toNamed("/x?id=1")` | parse URL → `Router.push(Routes.X, { id: 1 })`(命名路由 URL→Route 反射需单独实现)|
| `Get.back()` | `Router.pop()` |
| `Get.dialog(W, barrierColor, useSafeArea)` | `CustomDialogController({ builder: W, alignment, customStyle: true }).open()` |
| `Get.dialog(W, barrierDismissible: false)` | `CustomDialogController({ builder: W, autoCancel: false })` |

## E. Banner / cell tap 多类型分发(Flutter `toXxxInPage` 4 类)

常见首页 banner / 列表 cell 的 `type` 字段分发是 4 类通用形态:

- 1 → WebView(web url)
- 2 → 命名路由(URL `/x?id=1` 解析跳)
- 3 → 二级详情页
- 4 → 外部浏览器(launchUrl)

basic shell wire 阶段可仅 log;完整 4 类分发 + URL parser 建议留独立 task 收口。

## F. 根壳页 pageMap

新 page 加 case,Routes 加 const(同步)。pageMap 是 `@Builder pageMap(name: string)`,switch on name:

```ts
@Builder
pageMap(name: string): void {
  if (name === Routes.Login) { LoginPage(); }
  else if (name === Routes.List) { ListPage(...); }
  // ...
}
```

## G. NavPathStack.pop(result) 直传不 wrap

ArkUI 真签名:`pop(result?: Object, animated?: boolean): NavPathInfo | undefined`。result 是**直接传值**,**不**用 `{result: value}` 包一层。

```ts
// ❌ 错(Router.pop 起源 bug)
Router.stack?.pop({ result: '+852' });  // popInfo.result = { result: '+852' } 对象
// onPop callback resolve({result:'+852'}) → .then((code: string) => code.length === undefined)

// ✅ 正
Router.stack?.pop('+852' as Object);  // popInfo.result = '+852' string
// onPop callback resolve('+852') → .then((code: string) => code.length === 4) ✓
```

`onPop` 收到 `PopInfo { info: NavPathInfo; result: Object }`,其中 `result` **就是** pop 时传入的 Object,无额外 wrap。

**配套**:`Router.push(routeName, param).then((v: T) => ...)` 接收 pop 返回值;NavStackLike interface 应声明 `pop(result: Object): void` 不要 `pop(result: { result: Object })`。

## H. pageMap @Builder 必注册全 routes else-if

`Navigation(navStack).navDestination(this.pageMap)` 的 builder 必含**所有 Routes 的 else-if 分支**。漏注册 = `Router.push(Routes.X)` 静默渲染**空白页**(NavDestination 不画 content)→ "没数据"假象。

```ts
@Builder
pageMap(name: string): void {
  if (name === Routes.Login) { LoginPage(); }
  else if (name === Routes.LoginCaptcha) { LoginCaptchaPage(); }
  else if (name === Routes.List) { ListPage(); }
  else if (name === Routes.Detail) { DetailPage(); }     // ⚠️ 加新 page 必加分支
  else if (name === Routes.SubDetail) { SubDetailPage(); } // ⚠️ 漏 = 空白
  // 没匹配 → NavDestination 渲染空 = bug
}
```

**自检**:加新 Route enum 后 grep `pageMap` 找所有 builder,**逐个**加 else-if 分支;Routes.ts 与 pageMap **数量必相等**。

---

## §K. NavPathStack 嵌套路由必走 inner ctx.pathStack

**症状**:嵌套 `Navigation(innerNavStack) { ... }` 子 page(某导航壳页内的详情页)用全局 `Router.push(Routes.X, ...)` → NavDestination 渲空 → **整页黑屏**。

**根因**:`Router.bind(this.navStack)` 绑定的是根壳页 global navStack;`Router.push` 推到该栈。但目标 `Routes.X` 注册在**内层**壳页 stack 的 pageMap,global stack pageMap 无该 case → NavDestination 找不到 builder → 渲空 → 黑屏。

**Workaround**(内层壳页既有 pattern):

```ts
private onHistoryClick(): void {
  const info = this.queryNavigationInfo();
  const stack = info?.pathStack;
  if (stack === undefined || stack === null) {
    hilog.error(...);
    return;
  }
  const param: HistoryRouteParam = { itemId: this.itemId };
  stack.pushPath({ name: Routes.HistoryRecord, param: param as Object });
}
```

**判别 protocol**(走 `Router.push` 前必跑):
1. 该 Routes.X 是否注册在根壳页 pageMap?— ✅ → 用 `Router.push`
2. 否则注册在 nested NavPage(某内层壳页)pageMap?— 必走 `queryNavigationInfo().pathStack.pushPath`
3. 双 stack 都无?→ 加 pageMap case + 选合适 stack

**反模式**:用 `@ohos.router.pushUrl({url:...})` 绕开 NavPathStack — `router.back()` 栈空 fallback ability terminate(会把整个 ability 关掉),两套路由系统混用是根源。

**ArkTS 严格**:`pushPath({name, param})` 的 param 必须 typed interface(eg `HistoryRouteParam`),否则触发 `arkts-no-untyped-obj-literals` build fail。

---

## §POP-WITH-RESULT — Router.pop typed result(Flutter Get.back equiv)

**Why**:Flutter `Get.back(result: x)` 子页返结果给父页 `await Get.to(...)`,鸿蒙端需配套 typed result。

### Pattern

```ts
// Routes.ts — RouteParams + RouteResults 双表同步
export interface FlagResult {
  isFlag: boolean;
}
export type SearchResult = string | FlagResult | null;

// 注册 param
[Routes.Search]: { typeTag: 'modeA' | 'modeB'; isShowFlag?: boolean; isFlag?: boolean };
// 注册 result type
[Routes.Search]: SearchResult;
```

### 子页:`Router.pop<'Search'>(result)`

```ts
// SearchPage.ets 结果分支
async submitKeyword(): Promise<void> {
  ...
  if (typeTag === 'modeB') {
    if (trimmed === '<某特殊关键词>') {
      Router.push(Routes.SpecialBranch, { isFlag: true }).catch(...);
    } else {
      Router.pop<'Search'>(trimmed);   // ⚠️ typed pop result
    }
  }
}
```

### 父页:`await Router.push` 拿 result + 更新 state + reload

```ts
// 某父列表页 onSearchTap pattern
private async onSearchTap(): Promise<void> {
  const result = await Router.push(Routes.Search, {
    typeTag: 'modeB',
    isShowFlag: ...,
    isFlag: ...,
  }).catch((e: Error): SearchResult => {
    hilog.warn(LOG_DOMAIN.UI, TAG, 'nav err=%{public}s', e.message);
    return null;
  });
  this.onSearchResult(result);
}

private onSearchResult(result: SearchResult): void {
  if (typeof result === 'string' && result.length > 0) {
    this.applySearchKeyword(result);   // ⚠️ keyword 类
    return;
  }
  if (result !== null && (result as FlagResult).isFlag === true) {
    this.enterFlagMode();              // ⚠️ flag 类
  }
}
```

### 反模式

| ❌ | ✅ |
|---|---|
| 用 `EventHub.emit` + `Router.pop()` 不带 result(数据双链)| `Router.pop<'X'>(result)` typed result 单链 |
| `RouteParams` 加 param 不同步 `RouteResults` | 双表同步,缺一不可 |
| `await Router.push().catch` 没 fallback return | `catch((e): T => return null)` typed fallback |
| 子页 fire-and-forget Router.push 替 pop result | Router.pop with result(对位 Flutter `Get.back(result)`) |

---

## §OVERLAY-FRAMES — 浮层返回栈 frame 归属机制(详子文件)

浮层开着时 push 新页面 → 新页返回误关下层浮层;`await Router.push` 手势返回不 resolve;
`NavPathInfo.onPop` **系统返回手势不触发**(实机实证)。三症状一套机制解决:

> **凡进入导航栈的页面必有归属 frame;handleBack 只关最顶 frame 之上的浮层;frame 注销走真实栈对账,零依赖 onPop。**

新增内层直推页必接 2 行 `RouteFrameHolder`;新增 `await Router.push` 必对 undefined 判空。
完整症状/根因/规则/约定/evidence → [`routing-navigation-overlay-frames.md`](./routing-navigation-overlay-frames.md)
