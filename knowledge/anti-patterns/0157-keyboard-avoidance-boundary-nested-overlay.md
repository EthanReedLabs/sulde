---
doc_id: "ap-0157"
container: anti-patterns
platform: harmonyos
summary: "键盘遮挡先判承载边界:`KeyboardAvoidMode.RESIZE` 不覆盖 bindSheet 内自绘二级底部…"
---

# 0157 — 键盘遮挡先判承载边界:`KeyboardAvoidMode.RESIZE` 不覆盖 bindSheet 内自绘二级底部浮层

- **平台**:HarmonyOS
- **复发次数**:1
- **lint 状态**:⏳ pending(可扫 `bindSheet` 内 `Stack({ alignContent: Alignment.Bottom })` + `TextInput` + 自绘 overlay 的组合)

## 现象

某底部输入面板被键盘盖住一部分;或面板先飞起来、再出现键盘,键盘与面板间隔很大。外层页面 / sheet 已设 `KeyboardAvoidMode.RESIZE`,以为"页面已避让"就继续调页面 / sheet 高度,反复调 magic number(固定 `bottom` / 固定 `translateY`)仍修不对。

实际落点:输入框位于 `bindSheet` 内容里**再次自绘**的底部 overlay —— 一个 `Stack({ alignContent: Alignment.Bottom })` 内底部对齐的自绘 `Row` / `Column`。它不是系统 dialog,也不是页面根布局。键盘弹出后系统只调整窗口 / 页面布局边界,不会自动把这个自绘二级浮层挪到键盘上方。

## 为什么

- **看到 `KeyboardAvoidMode.RESIZE` ≠ 所有浮层都会避让**。`RESIZE` 只作用于窗口 / UIContext 布局区,自绘二级 overlay 通常脱离系统键盘避让边界,保持原 `Stack` 底部对齐。
- `bindSheet` 若没有等价的 keyboardAvoidMode 能力,内部自绘浮层要自己处理避让。
- 只看当前截图不追 builder 层级 → 漏掉"sheet 里又画了一个 bottom overlay",误判成"页面 resize 失效"。
- 不确认官方回调单位:`keyboardHeightChange` 返回的是 **px**,布局计算前必须转 vp;当 vp 直接用会让面板飞太高(px 数值偏大)。
- 不测真实面板高度,用设计稿高度 / 常量估算 → 竖屏 / 横屏 / 输入法高度变化时仍错。
- 只修一个面板,漏掉同类新增 / 编辑 / 搜索 / 命名 / 备注等所有含输入框的浮层。

## ✅ 正确

**先判承载边界,再改参数**。写出承载链路,确认输入框落在哪一层:

```text
page -> system sheet/dialog/cover -> custom overlay -> visual panel -> TextInput
```

若 `TextInput` 在 system sheet 的子孙自绘 bottom overlay 内,默认系统避让不会覆盖到该层 → 手动避让:

```text
window.on('keyboardHeightChange') -> heightPx
heightPx -> px2vp(heightPx)          // 官方回调是 px,先转 vp
onAreaChange -> measure real panel height   // 实测,不用常量
lift = min(keyboardHeightVp, viewportHeight - panelHeight - guard)
panel.translate({ y: -lift }) with animation
```

要点:

1. **只给目标二级面板加真实键盘高度 + 真实面板高度计算**,不同时改外层 sheet 宽度 / 页面缩放 / 滚动容器。
2. **单位先对齐**:`keyboardHeightChange` 的 px 必经 `px2vp` 才参与布局;复用项目内既有 px→vp 策略(如 safe area / `getWindowAvoidArea` 读取处)。
3. **面板高度用 `onAreaChange` 实测**,不用设计稿常量。
4. lift 加动画,键盘弹起 / 收起不突跳;改完截图验证:键盘弹起时面板完整露出、与键盘无明显大间隔。
5. **一次修全同类面板**(新增 / 编辑 / 搜索 / 命名 / 备注 …),不只修当前一个。
6. 复用 ≥ 2 处时抽通用 `KeyboardAvoidingBottomOverlay`(订阅 / 释放 `keyboardHeightChange` + px→vp + `onAreaChange` 测高 + 受限 lift + 统一动画);视觉允许时优先改用官方 `CustomDialog` 并设官方键盘避让选项。

**禁止**:固定 `bottom: 300` / `translateY: -360`;只用 `KeyboardAvoidMode.RESIZE` 后声明完成;为避让键盘改大整个 page / bindSheet 高度;未验证 px/vp 单位就参与布局计算。

## lint 状态

- ⏳ pending —— 可扫描 `bindSheet` / `bindContentCover` 内出现 `Stack({ alignContent: Alignment.Bottom })` + `TextInput` + 自绘 overlay 组合,提示"确认二级浮层键盘避让责任层"。
- 判断类补进 task 起草 / handoff review checklist:涉及输入弹窗 / bottom sheet / content cover 时,必列承载链路 + 键盘避让责任层 + px→vp 单位确认 + 面板实测高度。
