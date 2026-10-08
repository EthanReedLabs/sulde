---
doc_id: "ap-0154"
container: anti-patterns
platform: harmonyos
summary: "ArkUI `width('100%') + margin` 不等价 Flutter `EdgeInsets`,布局锚…"
---

# 0154 — ArkUI `width('100%') + margin` 不等价 Flutter `EdgeInsets`,布局锚点必须显式建模

- **平台**:HarmonyOS
- **复发次数**:1
- **lint 状态**:pending(可做 ArkTS 静态扫描:`width('100%')` 同链出现左右 margin / 固定宽度子项父级未显式 `alignItems`)

## 现象

把 Flutter `Container(margin: EdgeInsets.only(left: X, right: Y))` 机械转成 ArkUI `width('100%').margin({ left: X, right: Y })`,复刻 UI 时反复出现"左边不齐 / 底部装饰条过长 / 卡片与分组标题不对齐",要多轮微调才勉强接近 Flutter。

典型三个坑:

- **底部装饰条过长**:Flutter 用 `IntrinsicWidth` 让标题底部的短横条只跟文字同宽,ArkUI 首轮用 `width('100%')` 顶满父宽 → 横条过长。
- **固定宽度子项仍被居中**:子项改成固定宽度后,父 `Column` 没有显式 `alignItems(HorizontalAlign.Start)`,ArkUI 默认交叉轴对齐让固定宽度子项被居中,再叠加 `margin(left)` 产生二次偏移。
- **双重偏移**:子项已经是固定宽度(已经 `viewport - left - right`),却继续保留左右 margin → 外边距被算了两遍。

根因一句话:**Flutter 的 `EdgeInsets.only(left/right)` 表达的是"布局锚点 + 父约束";ArkUI 的 `width('100%') + margin(left/right)` 很容易变成"先占满父宽,再外扩或被父容器重新对齐",两者语义不等价。**

## 为什么

- ArkUI `Column/Row/Stack` 的默认交叉轴对齐**会参与固定宽度子项的定位**;不显式声明 `alignItems`,固定宽度子项被居中而非左锚。
- Flutter 的 `IntrinsicWidth / Align.centerLeft / SizedBox(width)` 表达的是明确的宽度/锚点模型,若反抽时只看到"有个左 margin"就丢掉宽度语义,ArkUI 侧无法还原。
- `width('100%')` 先占满父宽,margin 只是在满宽基础上外推/内缩,和"从某锚点起、占固定宽度"是两回事。
- 看到"不齐"只改一个数字,没有先拆**父容器对齐、子项宽度、margin/padding** 三层所有权 → 治标不治本,反复返工。

## ✅ 正确

复刻 Flutter 布局锚点时,每个可见块先选一种策略,禁止混用:

| Flutter 语义 | ArkUI 策略 |
|---|---|
| `margin left/right` 控制外部锚点 | 父 `alignItems(HorizontalAlign.Start)` + 子固定宽度 `viewport - left - right` + 仅保留单侧 left margin |
| `padding` 控制内部锚点 | 外层固定宽度,内文宽度 = 外层宽度 - paddingLeft - paddingRight |
| `IntrinsicWidth` | 用内容自适应容器或测量文字宽度,**禁止 `width('100%')`** |
| `Align.centerLeft` | 当前或父容器显式 `alignItems(Start)` / `alignSelf(Start)` |
| 边框 token | 映射同 token,不要用相近色顶替 |

固定宽度用 helper 显式建模,别散落 magic number:

```ts
// 父容器显式锚点
Column() {
  // ...
}
.alignItems(HorizontalAlign.Start)

// 内容区固定宽度 = viewport - 单侧锚点,再配单侧 margin
Text(dateText)
  .width(contentWidth(LEFT))          // viewport - LEFT
  .margin({ left: LEFT })

// 卡片/气泡:外层固定宽度,内文再扣内边距
Column() {
  Text(body).width(cardInnerWidth())  // cardWidth - padding*2
}
.width(cardWidth())                    // viewport - LEFT - RIGHT
.margin({ left: LEFT })
.padding(PAD)

// IntrinsicWidth:内容自适应,禁止 width('100%')
Row() {
  Text(title)
}
.alignSelf(ItemAlign.Start)            // 底部装饰条只跟文字同宽
```

建 `outerWidth / innerWidth / contentWidth` 一类 helper,统一从 viewport 推导宽度。

修完必须截图逐锚点复验(标题左边缘、装饰条左右边缘、卡片外框、内部头像/标题/正文左边缘、分组标题与卡片边框对齐、light/dark 同锚点一致);任一锚点不齐不能声明 1:1,构建通过不等于 UI 通过。

## lint 状态

- pending:可做 ArkTS 静态扫描 —— `width('100%')` 与 `.margin({ left` / `.margin({ right` 同链出现即告警;固定宽度子项所在父 `Column` 未显式 `.alignItems(HorizontalAlign.Start)` 即告警。
- code review 时 grep `width('100%')` + margin 同链的 UI;对 Flutter `IntrinsicWidth` 要求解释 ArkUI 等价策略,否则不验收。
- 关联:ArkUI 布局对齐类反模式(Stack/Column 默认对齐 topLeft/居中,需显式声明)。
