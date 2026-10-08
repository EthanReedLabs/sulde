---
doc_id: "platform-kb/harmony/routing-navigation-overlay-frames"
container: platform-kb
platform: harmonyos
summary: "`routing-navigation.md` 子文件(主文件超长 split)。"
---

# 路由 / 导航 — 浮层返回栈 frame 归属机制(v1.0)

> `routing-navigation.md` 子文件(主文件超长 split)。
> 涉及抽象:`OverlayBackStack`(全局浮层 LIFO 栈)+ `Router`(导航台账)+ `RouteFrameHolder`(内层直推页生命周期持有器)。

## 症状(可检索)

1. 浮层(抽屉/sheet)开着时 push 新页面,新页按返回/手势,**关掉的是下层页面的浮层**(不可见),新页留在原地;或"看不见的东西吃掉了返回"(实证:某抽屉浮层开着 → 进某页,返回后抽屉被静默关闭)。
2. `await Router.push(...)` 在用户**手势返回**时 promise 永不 resolve(await 之后的回流逻辑静默不执行,无报错)。
3. frame/清理逻辑挂在 `NavPathInfo.onPop` 上,显式 pop 正常、手势返回全失效。

## 根因(两条独立机制)

1. **全局浮层返回栈无归属**:全库页面 `onBackPressed → OverlayBackStack.handleBack()` 共享一个 LIFO 单例栈,上层页面的 handleBack 能弹到下层页面登记的浮层 entry(跨页污染)。
2. **`NavPathInfo.onPop` 只在显式 `pop(result)` 触发,系统返回手势的默认 pop 不触发**(实机 hilog 实证)。任何依赖 onPop 的清理/resolve 在手势返回路径全部失效。

## 通用规则(最终不变量)

> **凡进入导航栈的页面必有归属 frame;`handleBack()` 只关最顶 frame 之上的浮层;frame 注销一律靠与真实栈对账(`NavPathStack.getAllPathName()` 名字多重集),全线零依赖 onPop。**

| 页面进入方式 | frame 来源 | 说明 |
|---|---|---|
| `Router.push` | Router 台账 frame(带 pending resolve)| 手势返回经 `setInterception({didShow})` 转场对账,promise 以 `undefined` 结清(对齐 Flutter `Get.to` 手势返回返 null)|
| 内层 `queryNavigationInfo().pathStack.pushPath` 直推 | `RouteFrameHolder` 生命周期持有器 | `aboutToAppear` attach / `aboutToDisappear` detach;不入 Router 台账,不受对账修剪 |
| `Router.replace` / `offAll` | 无 promise frame(`resolve: null`)| replacePath 无 onPop 钩子已无所谓,注销走对账 |

对账触发时机:`handleBack()`/`hasOverlay()` 前置钩子、`Router.push` 入口、`setInterception.didShow`(每次导航转场后)。`popTo/clear/offAll` 按语义显式修剪。

## 增量约定(新代码必须遵守)

- ✅ 新增**内层直推页**必须接 2 行:
  ```ts
  private routeFrame: RouteFrameHolder = new RouteFrameHolder();
  aboutToAppear()    { this.routeFrame.attach('RouteName'); }
  aboutToDisappear() { this.routeFrame.detach(); }
  ```
- ✅ 新增 `await Router.push` 调用点必须**对 undefined 判空**(手势返回结清值)。
- ❌ 禁把"页面退出时必须执行"的清理只挂 `onPop`(手势返回不触发)——要么走对账,要么挂 `aboutToDisappear`。
- ❌ 禁页面 `onBackPressed` 自行特判"哪些浮层归我"(frame 已统一归属;历史上某设置页的特判已撤)。
- ❌ `OverlayBackStack.pushFrame/removeFrame` 仅 Router 与 RouteFrameHolder 调用,页面/浮层禁直接用。

## evidence

- 某抽屉浮层 → 某页链路:修复前返回关抽屉留目标页;frame 屏障后 E2E 三态全绿(sheet 开→关 sheet;无 sheet→关目标页留抽屉;再返回→关抽屉)。
- 第一版 frame 依赖 onPop → 实机泄漏(二次返回误弹某操作确认浮层)→ 实证 onPop 手势返回不触发 → 改对账。
- hilog 实证手势返回 promise 结清(`hasResult=false`)。

## 关联

`routing-navigation.md §K`(嵌套 inner pathStack 语义)· `§POP-WITH-RESULT`(typed result)· Dev 侧同节点 memory(onpop 系统返回不触发 / 浮层 frame)· `state-management.md`(OverlayBackGate 浮层登记)
