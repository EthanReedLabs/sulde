---
doc_id: "platform-kb/harmony/state-management"
container: platform-kb
platform: harmonyos
summary: "状态管理"
---

# 状态管理

## A. ArkUI 装饰器

| 装饰器 | 用途 |
|---|---|
| `@State` | Component 内本地状态 |
| `@Prop` | 父传子(单向同步,子改不回传父)|
| `@Link` | 父传子(双向,子改 + 父刷新)— **必由父 @State 字段绑**(详 `arkts-language.md §F`)|
| `@Observed @ObjectLink` | 嵌套 Object 字段响应 |
| `@StorageProp(KEY)` | 与 AppStorage 全局 key 双向同步(只读)|
| `@StorageLink(KEY)` | 与 AppStorage 双向(子改回写 AppStorage)|

## B. AppStorage(应用全局 KV)

```ts
AppStorage.SetOrCreate('K', value);   // 返回 void,详 arkts-language §G
const v = AppStorage.get<T>('K');      // 读取

@StorageProp('K') someField: T = defaultValue;  // 自动响应
```

## C. AppPreferences(持久化,@kit.ArkData)

```ts
// data/storage/AppPreferences.ts
await AppPreferences.setSomeFlag(true);
const shown: boolean = await AppPreferences.getSomeFlag();

// 加新字段:
await AppPreferences.getInt('some_key', 0);
await AppPreferences.setInt('some_key', someId);
await AppPreferences.remove('some_key');
```

新增 key 同步加到 `common/constants/StorageKeys.ts`(eg `STORAGE_KEY.SomeFeatureId`)。

## D. EventHub(事件总线)

```ts
// EventHub pattern
import { EventHub } from '../../services/EventHub';

// 订阅(aboutToAppear)
const subId = EventHub.getInstance().subscribe('SomeRecordSucceedEvent', (event: SomeRecordSucceedEvent) => {
  // handle
});

// 取消(aboutToDisappear)
EventHub.getInstance().unsubscribe(subId);
```

Flutter `AppEvent.getInstance().on<E>().listen(...)` 对位。

## E. EventWiring pattern(封装多事件订阅)

某页用一个 `XxxEventWiring` 封 multi-event subscribe:

```ts
this.wiring.wire({
  onForeground: () => this.fetchAll(),
  onSomeRecordSucceed: (recordTime: string) => { /* 局部 refresh */ },
  onReloadSomething: () => { ... },
  // ...
});

// aboutToDisappear:
this.wiring.unwire();
```

Wire 表对位 Flutter controller `_initEvent()` 内各 `_event = AppEvent.X.listen(...)`。

## F. GetX `controller.update(['id'])` → ArkUI 自动响应

Flutter `update(['some_id'])` 触发该 id 的 GetBuilder rebuild。ArkUI **不需要手动触发** — `@State` 字段改即自动响应该字段引用的子树。

## G. 全局用户态服务

```ts
// services/UserService.ts 内
this.currentUser  → AppStorage.SetOrCreate(STORAGE_KEY.UserCurrent, user);
this.isLoggedIn() → @StorageProp(STORAGE_KEY.UserIsLoggedIn) 在 component 读
this.isVip()      → @StorageProp(STORAGE_KEY.UserIsVip)
```

login/logout/profile change → 用户态服务更新对应 AppStorage key → @StorageProp 自动响应所有引用 component(eg 顶栏头像 / 昵称)。

不需要手动 fire 某 reload 事件;但若 Flutter 有 `_reloadUserInfoEvent`,ArkUI 页可保留 wire 作为额外信号 redundancy。

---

## X. Cross-UIContext state pattern(spike 实测验证)

跨 `bindContentCover` overlay 的 parent ↔ child state 同步,4 candidate 实测对比:

| Candidate | parent→child | child→parent | rapid 100ms×50 | cover 关重开残留 | nested L2 | Verdict |
|---|:-:|:-:|:-:|:-:|:-:|---|
| **A `@StorageLink('key')`** | ✅ | ✅ | ✅ 全 50 到 | ✅ AppStorage 持久 | ❌ 嵌套 cover 限制 | ⭐ transient 共享 state 首选(见 X.4 收窄)|
| **B `@Provide / @Consume`** | ✅ | ✅ | ✅ | ✅(parent struct 不销毁)| 同嵌套 cover 限制 | ✅ works(6.1.0(23) SDK 已修;**次于 A**,依赖 tree shape)|
| **C EventHub `common.UIAbilityContext.eventHub`** | ⚠️ 时序限制(child 未挂载丢事件)| ✅ | ⚠️ child 未挂载丢 | ❌ 无内置 state | 同上 | 仅事件型单次通知(eg dialog confirm)|
| **D callback prop**(parent setter via @Builder param) | ✅ snapshot only(❌ ongoing reactive)| ✅ | ✅ parent 端 | ✅ parent @State 持久 | 同上 | 仅 one-shot value pass(eg 选择器关闭回传)|

### X.1 推荐选型

| 场景 | 用 | 原因 |
|---|:-:|---|
| dialog 内文字流式累积 / loading state / 文案动态变 | **A** | reactive + 持久 + 不依赖 tree |
| dialog 在 strict tree-scoped(已知 parent-child 关系)+ 不需持久 | B(次选 A)| works |
| dialog 一次性 confirm event | C(若已有 eventHub init)| 单次轻量 |
| 选择器关闭回传单值 | D | 简单 1 次 |

### X.2 关联 ArkUI 限制(per `arkui-incompatibility.md`)

- `bindContentCover` chain 只生效最后一个 → Stack-per-cover workaround
- `bindContentCover` overlay 仅 Stack 渲染 → Scroll/Column 必 Stack 包裹
- 嵌套 cover sub-cover 不渲染 → 多层 cover 全挂最外 page
- arkts-language.md @Builder param by-value 不 reactive → 内联 `this.stateX` 或拆 @Component

### X.3 实证要点

- 跨 cover 失败时,用 Candidate A `@StorageLink('dialog_*')` 多 key 替换 @Link 可修复
- 同 page 同 UIContext 场景(无需 cross-cover)直接用 `@State`

---

### X.4 ⚠️ 修正:Candidate A 适用 scope 收窄 + Stack overlay 推荐

**Critical 反直觉**:X.1 "Candidate A `@StorageLink` 首选" 实测**仅适用静态 mount-once read** 场景。**reactive 持续变化场景实测 fail**。

| 场景 | 推荐 | 原因 |
|---|---|---|
| reactive 流式 text / SSE 流式 / live list 刷 / dynamic state 频变 | ❌ `bindContentCover @Builder`(Candidate A/B/C/D 全脱钩)→ ✅ **Stack overlay 同 UIContext**(`if (this.showX) { XComponent({...}) }`) | bindContentCover @Builder 内 @Component mount 后 2-4ms 即 dispose,reactive subscription 脱钩 |
| 静态 dialog(badge get / share / 一次性 confirm)| ✅ `bindContentCover` + Candidate A `@StorageLink` | mount 一次性 read OK,无 reactive 需求 |
| LoadingProgress 自动画(spinner 不依赖 state)| ⚠️ `bindContentCover` 看似 work 但假性 — Loading 自动画掩盖 reactive fail | spinner 假性通过教训 |

### X.5 ⭐ 实施模式(reactive 场景 Stack overlay)

```ts
// ✅ 正解 — Stack overlay 同 UIContext 同 page
@Component
struct ParentPage {
  @State showDialog: boolean = false;
  @StorageLink('dialog_text') dialogText: string = '';

  build() {
    Stack() {
      Column() {
        // ... main page content
        Button('open dialog').onClick(() => this.showDialog = true)
      }

      if (this.showDialog) {
        RespondDialog({
          show: $showDialog,
          // ... props
        })  // ← 同 UIContext,@StorageLink/@Watch 正常 reactive
      }
    }
  }
}

@Component
struct RespondDialog {
  @Link show: boolean;
  @StorageLink('dialog_text') dialogText: string = '';  // ✅ reactive 通
  @StorageLink('dialog_is_loading') isLoading: boolean = false;

  build() {
    // SSE writes AppStorage → @StorageLink 自动 reactive 更新 UI
    Text(this.dialogText)
    if (this.isLoading) LoadingProgress()
  }
}
```

### X.6 何时用 bindContentCover vs Stack overlay(决策树)

```
dialog 内是否需要 SSE / 流式 / live data reactive 更新?
  ├ 是 → Stack overlay 同 UIContext + @StorageLink/@Link 直接 reactive
  └ 否 → 弹窗内部是否有异步图片解码 / PixelMap / lottie / @Watch / @StorageLink / 网络回填?
        ├ 是 → Stack overlay 同 UIContext
        └ 否 → 是否需要全屏 modal + barrier + slide-in 系统动画?
              ├ 是 → bindContentCover + 一次性 mount(static)
              └ 否 → Dialog / Sheet API
```

### X.7 修正:静态弹窗里有异步子状态也不要用 `bindContentCover`

`X.6` 的"静态"只适用于完全同步内容。如果弹窗内部有异步图片解码、PixelMap、lottie、`@Watch`、`@StorageLink`、网络回填等子状态更新,即使业务数据本身是静态的,也要改用同页 `Stack` overlay。

已验证案例:某完成页奖励弹窗文字出现但图片为空。日志显示图片组件 decode 成功,但 view 已进入销毁流程。改为同页 overlay 后图片稳定展示。

## Y. ForEach 内选中 state 视觉不刷 → brute-force key 含 state

### 现象

`ForEach(arr, builder, keyGen)` 列表内 click 切换选中 state(@State selectedIdx),**视觉不更新**,即使:
- @Builder 改 inline ForEach
- 抽 @Component sub-struct + @Prop isSelected
- ForEach key 含 `${selectedIdx === i ? 1 : 0}`(只部分 cell 重建)

### 根因

ForEach 按 keyGen 判 item 同否。key 稳定 → 跳 itemBuilder 重调 → 内部 state-dep 表达式不刷新。`@Builder` primitive param 也非 reactive(详 `arkts-language.md`)。

### 修法:brute-force key 全 cell 含 state

```ts
ForEach(this.items, (m, i) => {
  Stack { ... }
    .borderColor(this.selectedIdx === i ? '#FFBD7F' : Color.Transparent)
    .onClick(() => { this.selectedIdx = i })
}, (m, i) => `${m.id}_${i}_sel${this.selectedIdx}`)  // ← key 全含 selectedIdx
```

每次 select → 所有 item key 变 → 全 destroy+recreate → 新 cell 读最新 state。

### 取舍

- ✅ 简单可靠,小列表(N<20)无感
- ❌ N=20+ list 卡顿;考虑 @Observed model + @ObjectLink

## Z. Dark mode `@State isDarkMode` + ctx.config.colorMode

### 何时需

Flutter `HexColor.isDarkMode ? dark : light` 显式分支,且无现成 `$r('app.color.xxx')` token(eg 卡片选中态 dark `#FAB16D` 0.2 alpha / light `#FAF5F1`)。

### 模板

```ts
import { common, ConfigurationConstant } from '@kit.AbilityKit';

@Component
struct MyPage {
  @State private isDarkMode: boolean = false;

  aboutToAppear(): void {
    try {
      const ctx = getContext(this) as common.UIAbilityContext;
      this.isDarkMode = ctx.config.colorMode === ConfigurationConstant.ColorMode.COLOR_MODE_DARK;
    } catch (_) { this.isDarkMode = false; }
  }
}
```

⚠️ **ctx 类型必 `common.UIAbilityContext`**,不是 generic `Context`(`Context` 无 `.config` 字段,build fail)。

### 优先级

Flutter 用 mode-aware token → 鸿蒙直接 `$r('app.color.xxx')` 让 ArkUI 自动切。**仅 Flutter 显式 `isDarkMode ?` 分支时**用 `@State isDarkMode` 双 hex。

### 局限

`aboutToAppear` 只读一次,主题切换后不自动刷新。Live 切需 `onConfigurationUpdate`(UIAbility 级)或 `@StorageProp` ThemeMode key。

详 `translate-rules.md` hex 真值表 + `resources-system.md` dark/element/color.json。

## AA. `PersistentStorage.persistProp` 仅 @StorageProp/@StorageLink binding 时 auto-sync

### 现象

启动引导 `initEarly` 调 `PersistentStorage.persistProp<T>(KEY, default)` 注册 key 为 "跨启动持久化",代码内 `AppStorage.setOrCreate(KEY, value)` 写入。**期望**:下次 cold start 读到上次写入值;**实际**:每次 cold start 读到 `default`,写入丢失。

### 根因

HarmonyOS NEXT 6.1.1 `PersistentStorage`:
- `persistProp(KEY, default)` 注册时 — 从 preferences 文件读 KEY 值;无 → 写 default 到 AppStorage + preferences。
- **AppStorage 后续变化是否自动 sync 回 preferences**,**取决于 KEY 是否被 `@StorageProp` / `@StorageLink` decorator binding 在某 component**。
- 有 binding:PersistentStorage 通过内部 listener 监听 binding 变化,自动 sync(eg `ThemeMode` 被某页 `@StorageProp(ThemeMode)` + 某 helper `AppStorage.get<number>(ThemeMode)` 多处 binding → sync OK)。
- **无 binding**:`AppStorage.setOrCreate(KEY, value)` 改 AppStorage 内存值,**但 PersistentStorage 内部 listener 未 attach → 不知道值变了 → 不写 preferences**。下次 cold start `persistProp` 又用 default 重置。

### 实证

- 某持久化标志 key 在启动引导注册 `persistProp(SomeFlag, false)`
- 全代码库 grep 该 key:仅一处 `AppStorage.get(SomeFlag)` + 一处 `AppStorage.setOrCreate(SomeFlag, true)` — **无任何 @StorageProp / @StorageLink binding**
- 实测:user 触发写入 → setOrCreate 写 AppStorage → force-stop + cold start → 逻辑判定"未写入"再触发一次(hilog 实证)
- 修复后 force-stop + cold start → 直接进入正确分支,**bug 修复实证**

### ✅ 正解:用项目自定义 `PersistentObjectStorage` 显式 set 替代 persistProp

```ts
// 启动引导 initEarly:启动 manual load 而非 persistProp
const raw = await PersistentObjectStorage.getRaw(STORAGE_KEY.SomeFlag);
let value = defaultVal;
if (raw !== null) {
  try { value = JSON.parse(raw) === true; } catch (e) { /* fallback default */ }
}
AppStorage.setOrCreate<boolean>(STORAGE_KEY.SomeFlag, value);

// 写入点:显式 await PersistentObjectStorage.set 强落盘 + setOrCreate AppStorage cache
await PersistentObjectStorage.set(STORAGE_KEY.SomeFlag, true);  // 落 preferences 文件
AppStorage.setOrCreate<boolean>(STORAGE_KEY.SomeFlag, true);   // 内存 cache 同步
```

### 何时用 persistProp / 何时用 PersistentObjectStorage(决策树)

```
该 KEY 是否被 @StorageProp / @StorageLink 在 component 引用 binding?
  ├ 是(eg ThemeMode 被多处 @StorageProp 引)
  │   → ✅ persistProp(KEY, default) 自动 sync OK
  │
  └ 否(eg 只在 service / page logic raw 读写的标志 key)
      → ❌ persistProp 不落盘
      → ✅ PersistentObjectStorage 显式 set + 启动 manual load 写 AppStorage cache
```

### 反模式 / 自检

- ❌ 启动引导 `persistProp(KEY, default)` 注册后,代码全程 raw `AppStorage.setOrCreate(KEY)` 写 + raw `AppStorage.get(KEY)` 读 — **无 @StorageProp/@StorageLink binding**:**KEY 不会跨启动持久化,bug**
- ✅ 新加 persistProp KEY 前 `grep -rn "@StorageProp.*KEY\|@StorageLink.*KEY"` 确认至少有一处 binding;无 → 改 PersistentObjectStorage path
- ✅ Audit 既有 persistProp keys:被多处 @StorageProp 引的 ✅;只 raw 读写的 ❌(应迁 PersistentObjectStorage)

---

## §STORAGE-KEY-ALIGN:同 model save/load/clear/check 必用同一 STORAGE_KEY

**陷阱**:同一 model 写一个 STORAGE_KEY,读另一个 STORAGE_KEY → feature **静默 broken**,无 error 无 crash,只是触发条件永远 false。难以排查(没有 hilog 异常)。

**反例(草稿恢复弹窗永不弹)**:
- 某 model `saveDraft/loadDraft/clearDraft` 用 `STORAGE_KEY.DraftA`(`app.xxx.draft`)
- recovery check 函数用另一个 `STORAGE_KEY.DraftB`(`app.xxx.recordDraft`)
- 两 key 都在 `StorageKeys.ts` 定义但**用途重叠**,write/read 错位 → check 条件永远 false → 恢复弹窗永远不弹
- user 反馈"草稿恢复 dialog 没出现",1 轮 grep 定位

**根因**:后续 gap task md 加 recovery check 时引入新 STORAGE_KEY 但 saveDraft 路径仍用旧 key,未同步迁移。

**审计 protocol**:
1. 协调端写涉及 STORAGE_KEY 的 task md 必明 spec:**所有 save / load / clear / check 路径都用 key X**
2. Dev 实施加新 STORAGE_KEY 前 grep `STORAGE_KEY.<key>` 全文件 — 看是否已有 similar 用途 key(避免重复定义)
3. 同 feature 写 / 读 / 清 / 触发 check 必 grep 全 callers,确保都用同一 key
4. feature "silently 不触发" 首查:grep STORAGE_KEY 全文件,看写读 key 是否一致

**Pre-ship 检查**:`grep STORAGE_KEY.<feature_key>` Harmony 全部 .ets/.ts → 列出 read sites + write sites → 比对是否描述同一 feature
