---
doc_id: "tech-docs/案例研究/06-HarmonyOS-ArkUI工程/ArkUI浮层体系的响应式-宽度-键盘三类深水区"
container: case-studies
platform: none
summary: "**技术域**：HarmonyOS ArkUI 工程 — 声明式浮层（floating surface）架构 **难度…"
---

# ArkUI 浮层体系的响应式 / 宽度 / 键盘三类深水区

> **技术域**：HarmonyOS ArkUI 工程 — 声明式浮层（floating surface）架构
> **难度**：⭐⭐⭐⭐⭐
> **关键词**：bindContentCover / bindSheet / @Builder overlay / @StorageLink reactive 脱钩 / UIContext / KeyboardAvoidMode / keyboardHeightChange / px2vp / onAreaChange / Stack overlay / 浮层分层宽度 / 承载边界
> **可迁移场景**：任何声明式 UI 框架里「浮层是独立于页面的容器」的场景 —— 弹窗、底部 sheet、全屏 cover、二级输入面板、嵌套浮层；跨端理解「物理挂载 ≠ 语义存活」「视觉层 ≠ 单一宽度」「系统能力有作用域边界」三类深水区。

---

## 一、场景与系统架构

移动端应用大量使用**浮层（floating surface）**：底部弹起的 sheet、覆盖全屏的 cover、二级输入面板、操作菜单。ArkUI（声明式 UI 框架）提供两组系统浮层承载 API：

- `bindContentCover(isShow, builder, options)`：全屏覆盖浮层，内容由一个 `@Builder` 方法提供。
- `bindSheet(isShow, builder, options)`：半模态底部 sheet，可设定高度、宽度、圆角。

这两个 API 有一个共同的、极易被忽视的本质：**它们把 `@Builder` 里的内容渲染到一个与当前页面「分离」的 overlay 容器里**。这个「分离」在三个正交维度上同时成立，而每一个维度都会击穿一条页面开发者的直觉假设：

| 维度 | 页面开发者的直觉 | 浮层的真相 | 击穿后的症状 |
|---|---|---|---|
| **生命周期** | view tree 物理挂上了 → 响应式订阅就活着 | overlay 容器的 `@Component` 实例响应式订阅会在挂载后毫秒级被 dispose | 流式数据、异步资源更新不落屏 |
| **视觉分层** | 浮层就是「一个宽度」 | 遮罩 / 承载 / 视觉面板 / 内容约束 / 嵌套子浮层是 5 个独立层 | 承载层变窄、白色面板变窄、二级浮层漏改 |
| **系统服务作用域** | 页面设了 `KeyboardAvoidMode.RESIZE` → 里面所有东西都会避让键盘 | 系统避让只作用于外层窗口 / 页面布局区，不作用于浮层内自绘的二级底部 overlay | 二级输入面板被键盘盖住 |

### 浮层体系结构图

```
Page (UIContext A)
│
│  bindContentCover / bindSheet  ← 系统在此切换到一个「分离」的 overlay 容器
▼
System Overlay Carrier  ← 独立生命周期 + 独立 UIContext + 独立返回栈 frame
├── 遮罩层 (scrim)            width: 100% / viewport   —— 点击关闭 hit area
├── 承载层 (container)         bindSheet.width 控制的是这一层，不是内容宽
│   └── 视觉面板层 (panel)     背景色 / 圆角 / 阴影挂这里；全宽 or 窄卡片是设计决策
│       └── 内容约束层 (content)  width = contentWidth；justifyContent(center)
│           ├── TextInput
│           └── 嵌套子浮层 (nested overlay)  ← 自绘 Stack({alignContent: Bottom})
│               └── 又一套 panel / content / TextInput
```

**核心洞察**：这张图里，从 `System Overlay Carrier` 往下的每一层，都不继承 `Page` 的任何假设——不继承页面的响应式上下文寿命、不继承页面的宽度语义、不继承页面的键盘避让作用域。三类深水区，本质是**同一件事在三个维度上的表现**：浮层是一个独立的 frame。下面分三类症状展开，最后收敛回这个统一根因。

---

## 二、问题现象（三类症状 + 实测）

三类症状相互独立、可分别复现，但都指向浮层的「分离」本质。

### 症状一：响应式停更（reactive detachment）

一个用 `bindContentCover` 承载的对话弹窗，内部组件用 `@StorageLink` / `@Watch` 订阅一个持续写入的流式文本源（如逐字返回的文本流）。现象：

- 弹窗外框、按钮、标题都正常显示，**但流式文字完全不刷新**，UI 静止。
- 数据侧日志证明文本确实在持续写入全局状态（多轮 `textLen=320/204/196` 的写入记录），但视图无反应。
- 另一个「看似正常」的加载弹窗，用同样 pattern 却能显示——但仔细看只是一个自播放的 `LoadingProgress` 动画（不依赖任何响应式），并非响应式真的活着。

**实测（已观测）**：在挂载时刻打点，时间线清晰可见——
```
t=.524ms  @Component aboutToAppear（进 component tree）
t=.526ms  overlay 物理 mount 完成
t=.526ms  同一帧内 aboutToDisappear 触发
t=.530ms  首帧图片 render（view tree 仍留屏）
```
即：view tree 物理留屏，但响应式订阅在 **mount 后约 2–4ms 内即被 dispose**。这不是「没渲染」，是「渲染了但订阅断了」。

同类还有一个变体（已观测）：静态弹窗内含异步图片解码，外框 / 文字 / 按钮都在，**唯独中间图片空白**；日志显示图片已 decode 成功，紧接着出现类似 `View ... is already in process of destruction` 的状态更新丢弃——异步回调晚于 overlay 子树销毁，更新没落到当前屏。

### 症状二：宽度错层（layered width）

平板适配中，一个底部 sheet 内含「新增 / 编辑」二级输入弹窗。设计要求：白色面板撑满全屏宽，内部标题 / 输入框 / 图标选择居中限宽。返工现象：

- 把 `bindSheet.width` 设成「内容宽」（一个窄值）→ **整个底部 sheet 承载层变窄**，而不是内容变窄。
- 把白色背景 / 圆角挂到限宽的内容 `Column` 上 → **视觉面板本身变窄**，露出两侧空隙。
- 只改了入口 sheet，**漏掉「点新增 / 点编辑」后弹出的二级浮层**，二级浮层仍是错的窄宽。

**实测（已观测）**：连续两轮只调宽度数字都对不上；直到停下来画出分层图，才发现是「把 5 个层压成 1 个数字」在建模。这是「症状指向层级建模缺失」的典型——数字调不对不是数字问题。

### 症状三：键盘遮挡（keyboard avoidance boundary）

同一个二级输入面板，输入时被软键盘盖住一部分。外层页面 / sheet **已经**设置了 `KeyboardAvoidMode.RESIZE`。返工现象：

- 面板底部被键盘盖住；滑动截图能看到面板完整存在（说明数据没丢、渲染没失败，纯粹是被覆盖）。
- 「面板先飞起来、再出现键盘」，面板和键盘之间间隔很大（一次错误尝试的副作用：单位用错 / 抬升过量）。
- 反复重装仍然遮挡——因为根因不在参数。

**实测 vs 预期**：截图确认「只有底部输入面板被遮，外层页面 / sheet 背景与主内容仍正常」→ 这是**已观测的分层判据**，直接指向「内层自绘 overlay 未避让」而非「页面 resize 失效」。修复后「键盘弹起时面板完整露出、无大间隔」是**已观测**结果；抽成通用 helper 后的多页复用收益是**预期方向**，尚未在多处复测。

---

## 三、根因分析（深挖到平台机制层）

### 根因一：`@Builder` overlay 的响应式生命周期与物理挂载解耦

ArkUI 声明式响应式的工作方式：`@StorageLink` / `@StorageProp` / `@Watch` / `@ObjectLink` 在 `@Component` 实例构造时建立**订阅（subscription）**，当被订阅的状态变化时 notify 该实例重新 render。订阅的生命周期本应与组件实例一致。

但 `bindContentCover` / `bindSheet` 的 `@Builder` 内创建的 `@Component` 实例，运行在一个**独立且生命周期不稳定的 overlay 容器**里。实测行为（SDK 6.1.x 级别）：

- **view tree 物理 mount + 首帧渲染正常**——所以你看得到外框、静态内容、能自播放的动画。
- **但响应式订阅在 mount 后 2–4ms 内即被 disposed**——后续 source state 变化无法 notify 到这个已「脱钩」的 view。

这解释了为什么「静态弹窗看似 work，响应式弹窗必 fail」：

| 弹窗类型 | 是否依赖 mount 后的响应式更新 | 结果 |
|---|---|---|
| 一次性 confirm / 分享 / badge 展示（mount 时读一次即定） | 否 | ✅ 看似正常（其实只是一次性 read） |
| `LoadingProgress` 自播放 spinner | 否（动画自驱动） | ✅ 看似正常（陷阱：别用它反映响应式进度） |
| 流式文本 / SSE / 动态 list / 异步图片回填 | **是** | ❌ mount 后订阅已 dispose，更新不落屏 |

这个陷阱的隐蔽之处：静态场景的「成功」会诱导你相信 pattern 没问题，直到上响应式场景才暴露——而此时你会误以为是响应式代码本身写错了。

这套 overlay 容器还有一系列相关限制（同源于「overlay 容器是分离且受限的」）：

- **同一节点链式挂多个 cover，只有最后一个生效**：前面的 `@Component` 仍会 `aboutToAppear`（进 component tree），但 overlay window 不渲染（窗口管理层只保留 1 个）。每个独立 cover 必须挂在**独立节点**上。
- **cover 内容根节点只有 `Stack` 能渲染**，`Scroll` / `Column` 作根会 silent fail（child mount 日志触发，但 overlay 不可见）。需要滚动时用 `Stack() { Scroll() { ... } }` 包裹。
- **嵌套 cover 受限**：cover A 的 child 再起 sub-cover 不渲染（overlay 层级 / Window 管理限制）；多层浮层必须全部挂最外层页面，内部 child 只 toggle state。

### 根因二：浮层视觉是 5 层叠加，不是 1 个宽度

「浮层的宽度」这个说法本身就是 bug 的温床。一个底部 sheet 在视觉上至少是 5 个独立层，每一层的宽度语义和背景归属都不同：

```
sheet container width = viewportWidth()      ← bindSheet.width 控制的是这一层
sheet visual panel width = 100%              ← 背景 / 圆角 / 阴影挂这一层
sheet content width = contentWidth()         ← 输入框 / 标题居中限宽在这一层
```

常见误建模，本质都是「层坍缩」：

1. 把 `bindSheet.width` 当内容宽 → **承载层**被限窄（设计要的是全屏承载）。
2. 把背景色 / 圆角挂到限宽内容 `Column` → **视觉面板层**变窄，两侧露空。
3. 把「内容居中」误解为「整个面板居中限宽」→ panel 和 content 两层混为一层。
4. 为所有 sheet 统一套一个固定宽（如某个常量 vp）→ 忽略「全屏面板 + 居中内容」这种形态。
5. 只改入口 sheet，漏掉点「新增 / 编辑 / 更多」后的二级浮层——**嵌套子浮层层**继承了同样的分层，但没被同步处理。

一个放大问题的机制陷阱：机械替换 ArkUI 组件层级时，很容易破坏 `@Builder` 方法的括号配对，导致后续 build 被解析进 UI 树内部——层级建模错误会连带引入语法层的隐性错位。

**根因命名**：公共度量 API 若只有一个含混的 `sheetWidth()`，它同时承担了「承载层宽」和「内容层宽」两个语义，调用方无从知道自己在设哪一层——**命名坍缩直接导致建模坍缩**。

### 根因三：`KeyboardAvoidMode.RESIZE` 的作用域边界

`KeyboardAvoidMode.RESIZE` 的官方语义是：键盘弹出时，**调整窗口 / UIContext 的布局区**（把可用布局高度压缩）。关键词是「窗口 / 布局区」——它作用的是**系统承载层**，不作用于承载层内部你自绘的东西。

事故链路里的二级输入面板，是这样一个结构：

```
page → system sheet (bindSheet) → 自绘 Stack({alignContent: Alignment.Bottom}) → 视觉面板 → TextInput
```

这个 `Stack({alignContent: Alignment.Bottom})` 内底部对齐的自绘 Row / 面板，**不是系统 dialog、也不是页面根布局**。键盘弹出时：

- 系统按 `RESIZE` 调整了外层窗口 / 页面布局边界。
- 但这个自绘二级面板的 bottom 对齐策略是**相对它自己的 Stack** 的，系统 resize 没有、也无法去改变一个应用自绘节点的 bottom anchor。
- 结果：外层布局区变了，二级面板纹丝不动地贴在原来的底部 → 被键盘覆盖。

各 API 的键盘避让作用域必须逐个核对：

| API | 键盘避让作用域 |
|---|---|
| `KeyboardAvoidMode.RESIZE` | 窗口 / UIContext 布局区（外层） |
| `CustomDialogOptions.keyboardAvoidMode` | 只作用于 custom dialog 承载 |
| `bindSheet`（无等价 keyboardAvoidMode 时） | 内部自绘浮层要**自己**处理 |

还有一个单位陷阱：`keyboardHeightChange` 回调返回的高度单位是 **px**，布局计算（translate / height）用的是 **vp**。不转换直接用会导致「面板飞太高」——这正是「面板先飞起来再出现键盘、间隔巨大」的根因。

### 统一根因：浮层是一个独立的 frame

三类根因收敛到同一句话：**系统浮层不是「页面里的一块区域」，而是一个在生命周期、视觉分层、系统服务作用域上都与页面分离的独立 frame。** 这个「分离」还有第四个维度——**返回栈归属**：多个页面若共享一个全局浮层返回栈单例（LIFO），上层页面的返回处理会误弹到下层页面登记的浮层 entry（跨页污染）；且清理逻辑若挂在 `NavPathInfo.onPop` 上，**系统返回手势的默认 pop 根本不触发** onPop（只有显式 `pop(result)` 触发），导致手势返回路径下清理 / promise resolve 全部静默失效。这与前三类同构：都是「假设浮层继承了页面的某种上下文」，而它并没有。

---

## 四、解决方案（含 why-this-not-that）

### 方案一：响应式重场景改用同页 `Stack` overlay

彻底绕开 overlay 容器的生命周期问题——不进独立 overlay，就在**当前页面、当前 UIContext** 内用 `Stack` + `if` 条件渲染浮层：

```ts
// ❌ 反模式（响应式脱钩）：
Column() {
  // ... 主内容
}.bindContentCover($$this.showDialog, this.DialogBuilder())

@Builder
DialogBuilder() {
  StreamingDialog({ /* ... */ })  // @StorageLink / @Watch 在此全脱钩
}

// ✅ 正解（同 UIContext 同 page，响应式正常）：
Stack() {
  Column() {
    // ... 主内容
  }
  if (this.showDialog) {
    StreamingDialog({ /* ... */ })  // @StorageLink / @Watch 正常 reactive
  }
}
```

**why this**：`Stack` + `if` 的浮层内容始终在页面的 UIContext 内，`@Component` 实例的响应式订阅生命周期与页面一致，不会被独立 overlay 容器毫秒级 dispose。

**why not bindContentCover**：静态、无异步资源、无子组件状态回填的轻量弹层可以继续用 `bindContentCover`（badge 展示、一次性 confirm）——它的问题只在响应式 / 异步场景暴露。判据很简单：**弹窗内是否有 mount 之后仍需刷新的东西**（流式文本、异步图片解码、`@Watch` 回填、网络状态回填）。有 → 必 `Stack` overlay；没有 → cover 可留。

**代价与边界**：`Stack` overlay 是「内容层」方案，如果原设计是「透明路由 + 转场动画」类浮层（进场 downToUp、背景渐暗、关闭下滑），只翻译内容层会丢掉转场状态机。这种要在同页 overlay 里**显式建状态机**：`showSheet`（是否挂载）+ `sheetTranslateY`（进场前屏外偏移，`animateTo` 到 0）+ `scrimOpacity`（独立驱动，不与位移绑定），关闭时先设 scrim 再下滑、动画结束再卸载。

### 方案二：分层宽度 API，命名即建模

修复的第一步不是调数字，是**画分层图 + 拆命名**：

```text
bindSheet.width           = sheetContainerWidth()   // 承载层：是否全屏
root bottom panel         : width(100%) + background / radius / shadow   // 视觉面板层：全宽
inner content             : width(sheetContentWidth()) + justifyContent(center)  // 内容层：居中限宽
```

**公共 API 必须按层命名**，禁止一个 `sheetWidth()` 通吃：

```ts
sheetContainerWidth()   // 承载层宽（通常 = viewport）
sheetContentWidth()     // 内容约束层宽（居中限宽）
dialogWidth()           // 中心 dialog 宽
```

**执行 checklist**（写规则 / 改浮层时逐项过）：
1. **列浮层链路**：入口浮层 + 每个二级浮层全部列出（搜 `bindSheet` / `bindContentCover` / `CustomDialogController` / `Overlay` / `新增` / `编辑` / `更多`）。
2. **逐层标宽度语义**：遮罩层（100% / viewport）/ 承载层（是否铺满）/ 视觉面板层（背景归属）/ 内容约束层（是否居中限宽）/ 嵌套子浮层（是否同策略）。
3. **背景归属检查**：`.backgroundColor` / `.borderRadius` / `.shadow` 不能无脑挂限宽内容层——先确认设计是「全宽面板」还是「窄卡片」。
4. **失败处理**：同一浮层宽度连续两轮不对，**停止调数字**，回到分层图先指出是哪一层错。

**why this**：宽度错层是「层坍缩」问题，唯一可靠解是先把层拆开，让每一层的宽度和背景归属显式化。命名分层是把这个约束固化进 API，防止下一个人再坍缩。

### 方案三：自绘二级浮层手动键盘避让

系统避让够不到的自绘 overlay，自己订阅键盘高度、实测面板高度、算受限抬升：

```text
window.on('keyboardHeightChange')  → heightPx
heightPx → px2vp(heightPx)          → keyboardHeightVp   （必须转 vp）
onAreaChange → 实测面板真实高度      → panelHeight       （不用设计稿常量）
lift = min(keyboardHeightVp, viewportHeight - panelHeight - guard)   （受限，防飞太高）
panel.translate({ y: -lift }) with animation
```

四个不可省的点：
- **转 vp**：`keyboardHeightChange` 回调是 px，不转直接用会抬升过量。
- **实测面板高度**：用 `onAreaChange` 拿真实高度，不用设计稿高度或常量——横竖屏 / 输入法高度变化时常量必错。
- **受限抬升**：`lift` 取 `min`，防止把面板顶出视口。
- **动画**：`animateTo` 平滑抬升，不突跳。

**why not 固定 translate 常量**（`bottom: 300` / `translateY: -360`）：竖屏 / 横屏 / 不同输入法高度下键盘高度不同、面板高度不同，任何固定常量只在一种配置下对。这是「连续两轮 magic number 都不对」的根源。

**why not 直接换系统 dialog**：官方 `CustomDialog` + 官方 `keyboardAvoidMode` 确实能白嫖系统避让，但如果视觉要求是「`bindSheet` 内二级全宽面板 + 内容居中 + 逐级关闭」，换成系统 dialog 会改变视觉层级和关闭行为。当视觉约束与系统 dialog 冲突时，选择局部手动避让。

**复用形态（预期方向）**：当同类自绘底部输入面板 ≥ 2 处、且都不能改系统 dialog 时，抽通用 `KeyboardAvoidingBottomOverlay`——职责：订阅 / 释放 `keyboardHeightChange`、px→vp 转换、`onAreaChange` 测真实高度、算受限 lift、统一动画、暴露 `contentBuilder` / `panelBuilder`。（单页已验证有效；多页复用收益属预期。）

### 诊断纪律：先判承载边界，再改参数

三类深水区共享一条诊断原则——**看到症状先判「谁是承载层、谁负责这件事」，不要直接改参数**：

- 键盘遮挡：先截图分层判读（只有底部面板被遮 vs 整个页面异常）→ 追承载链路 `page → sheet → 自绘 overlay → TextInput` → 查该层是否在系统避让作用域内 → 形成**单一假设**（「自绘二级 overlay 未避让」）而非「可能高度不够 / 先把 bottom 改大试试」→ 最小验证（只给目标面板加真实测量值，不同时动外层宽度 / 缩放 / 滚动）。
- 同类第二次失败必须停下：标出键盘 top / 面板 top / 面板 bottom、确认单位、重追承载链路是否还有更内层 overlay、对照官方能力边界确认 API 是否真作用到目标层。

---

## 五、可迁移原则

抽离自三类深水区的通用规律，适用于任何「浮层是独立于页面的容器」的声明式 UI 场景：

1. **声明式浮层的响应式生命周期 ≠ 物理挂载**。独立 overlay 容器（`bindContentCover` / `bindSheet` 类）里的组件，可能 view tree 物理留屏但响应式订阅已被毫秒级 dispose。判据：**弹窗内是否有 mount 之后仍需刷新的东西**（流式数据 / 异步资源解码 / `@Watch` 回填）。有 → 用同页 `Stack` + `if` 条件渲染（保持在页面 UIContext 内）；没有 → 系统 overlay 可留。永远不要用「静态弹窗能正常显示」证明「响应式弹窗也没问题」——静态的成功只是一次性 read，掩盖了订阅已断的事实。

2. **视觉层 ≠ 单一宽度**。任何浮层至少是遮罩 / 承载 / 视觉面板 / 内容约束 / 嵌套子浮层 5 层，每层的宽度语义和背景（`backgroundColor` / `borderRadius` / `shadow`）归属都要独立决定。公共度量 API 必须按层命名（`containerWidth()` / `contentWidth()`），禁止一个含混的 `width()` 同时承担多层——**命名坍缩必然导致建模坍缩**。宽度连续两轮调不对时，停止调数字，回到分层图指出是哪一层错。

3. **系统能力有作用域边界**。`KeyboardAvoidMode.RESIZE` 只作用于窗口 / 页面布局区，作用不到你在浮层内自绘的二级底部 overlay。看到「系统能力已启用」不等于「所有子节点都被覆盖」——必须逐 API 核对作用域，落在边界外的层要自己处理（手动订阅 `keyboardHeightChange` + `px2vp` + `onAreaChange` 实测 + 受限 lift）。同理，跨系统回调的单位（px vs vp）在参与布局计算前必须显式转换。

4. **浮层是独立的返回栈 frame，别假设它继承页面上下文**。浮层与页面在生命周期、视觉分层、系统服务作用域、**返回栈归属**四个维度都是分离的。凡进入导航栈的浮层必须有明确的归属 frame，返回处理只应关「属于当前最顶 frame」的浮层；清理 / promise resolve 逻辑不能只挂在「仅显式 pop 才触发」的回调上（系统返回**手势**通常不触发它），要么走与真实栈对账，要么挂组件生命周期回调。所有「浮层的坑」几乎都能归约为一句诊断问句：**「我是不是假设了这个浮层继承了页面的某种上下文，而它其实没有？」**

5. **诊断先判承载边界，再改参数**。浮层类问题（遮挡 / 错位 / 不刷新 / 返回错乱）第一步永远是追承载链路（`page → system carrier → 自绘 overlay → 视觉面板 → 输入框`）、判定「谁是承载层、这件事归哪一层负责」，形成**单一可证伪假设**，再最小验证。禁止一上来就调 magic number；同类问题第二次失败必须停下补分层证据，而不是继续试参数。

---

## 六、技术深问

**Q：为什么静态弹窗用 `bindContentCover` 看似正常，一上响应式就 fail？**

> 因为独立 overlay 容器里的 `@Component` 实例，view tree 会物理 mount 并渲染首帧（所以你看得到外框、静态文字、能自播放的 `LoadingProgress`），但响应式订阅（`@StorageLink` / `@Watch`）在 mount 后约 2–4ms 内被 dispose。静态弹窗的内容在 mount 时读一次就定了，不依赖后续 notify，所以「看似正常」；而流式文本 / 异步图片回填依赖 mount 之后的持续更新，此时订阅已断，更新不落屏。危险在于：静态场景的成功会诱导你相信 pattern 没问题，等上了响应式场景暴露时，你反而会怀疑是响应式代码写错了，而不是承载 API 的生命周期问题。

**Q：`bindSheet.width` 到底控制哪一层？为什么设成内容宽会让整个 sheet 变窄？**

> `bindSheet.width` 控制的是**承载层（container）**的宽度，不是内容宽。承载层是系统 sheet 的物理边界。把它设成一个窄的「内容宽」值，等于告诉系统「整个底部 sheet 只有这么宽」——于是承载层连同它内部的视觉面板一起变窄。正确建模是三层分开：承载层 = viewport（全屏承载）、视觉面板层 = 100%（白色背景 / 圆角挂这里）、内容约束层 = 内容宽（输入框 / 标题居中限宽）。5 个层压成 1 个 `width` 数字是所有宽度返工的根源。

**Q：页面已经设了 `KeyboardAvoidMode.RESIZE`，为什么二级面板还被键盘盖住？**

> 因为 `RESIZE` 只调整**窗口 / UIContext 的布局区**（外层），而被盖住的二级面板是 `bindSheet` 内部你自绘的一个 `Stack({alignContent: Alignment.Bottom})` 里底部对齐的 Row。它不是系统 dialog、也不是页面根布局。键盘弹出时系统压缩了外层布局区，但这个自绘节点的 bottom anchor 是相对它自己的 Stack 的，系统 resize 无法、也不会去改一个应用自绘节点的对齐策略。所以它纹丝不动地贴在原底部被键盘覆盖。诊断判据：如果只有底部面板被遮、外层页面 / sheet 背景正常，就是「内层自绘 overlay 未避让」，而不是「页面 resize 失效」——不要再去调页面 / sheet 高度。

**Q：手动键盘避让为什么不能用固定 `translateY` 常量？**

> 键盘高度随输入法、横竖屏变化；面板高度随内容、屏幕方向变化。任何固定常量只在一种配置下对，换个输入法或转屏就错——这正是「连续两轮 magic number 都不对」的原因。正确做法：`keyboardHeightChange` 拿键盘高度（px，**必须** `px2vp` 转 vp）、`onAreaChange` 实测面板真实高度、`lift = min(keyboardHeightVp, viewportHeight - panelHeight - guard)` 取受限值防飞出视口、`animateTo` 平滑抬升。三个动态量（键盘高度、面板高度、视口高度）都要实测，不能有一个是常量。

**Q：为什么说这三类深水区是「同一件事」？**

> 因为它们都源于一个被忽视的架构事实：**系统浮层不是「页面里的一块区域」，而是一个独立的 frame**。这个「独立」在四个正交维度上成立——生命周期独立（响应式订阅不随页面寿命）、视觉分层独立（5 层各有宽度语义）、系统服务作用域独立（键盘避让够不到）、返回栈归属独立（返回手势 / frame 归属自成一套）。每一类 bug 都是「假设浮层继承了页面的某种上下文，而它没有」。掌握这个统一视角后，遇到任何浮层新坑，第一个诊断问句就是固定的：「我是不是又假设了它继承页面的某种上下文？」——把四个维度逐一核对，根因通常就在其中之一。
