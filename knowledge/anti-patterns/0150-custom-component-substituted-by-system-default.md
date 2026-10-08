---
doc_id: "ap-0150"
container: anti-patterns
platform: cross
summary: "反抽自绘公共组件时用系统默认组件替代(丢宽度/圆角/遮罩/动画真值)"
---

# 0150 — 反抽自绘公共组件时用系统默认组件替代(丢宽度/圆角/遮罩/动画真值)

- **平台**:跨端
- **复发次数**:1
- **lint 状态**:pending(待 task md / handoff 模板强制校验)

## 现象

反抽某来源端的自定义公共 UI(弹窗 / bottom sheet / menu / picker / loading)时,只追到**公共组件的调用名**就收手,目标端直接拿一个**同类系统/默认组件**(系统 dialog / 系统 sheet / 系统 picker)顶上。

结果:业务逻辑能跑通(弹窗能弹、回调能返回"确定/取消"),但**视觉全错**——宽度、圆角、背景色、遮罩(barrier/scrim)、按钮顺序、字体、间距、进出场动画都不是源端真值,而是平台默认样式。

这不是平台差异,也不是源端真值找不到,而是 **UI 反抽停在公共组件的调用名,没继续追到公共组件源码的叶子/依赖闭包**。

## 为什么

1. **调用链没有闭包**
   - 已追到业务触发点和"某公共弹窗组件"的调用名。
   - 没继续打开该公共组件的**源码文件**,漏掉承载层(route/dialog/overlay)和内容层(私有 builder)。

2. **把自绘公共 UI 当成普通系统弹窗**
   - 源端的公共组件是**自定义 UI**,不是系统 Alert。自绘的宽度/圆角/遮罩/动画本身就是该组件存在的意义。
   - 目标端复用了一个已有的同类系统封装,顺手引入了平台默认样式。

3. **只迁 callback,没迁承载层 + 内容层**
   - 业务上能返回结果,视觉上缺失源端的 route/dialog、barrier、alignment、transition、button layout。

4. **缺少公共 UI 依赖现状审计**
   - 没有证明目标端现有的同名 service/component 与源端**视觉/行为 1:1**,直接复用把隐藏差异带进验收。

## ✅ 正确

只要源端出现**自定义公共 UI**(弹窗 / bottom sheet / menu / button / title bar / loading / refresh / 富文本 / 三方 widget),反抽必须做 **公共 UI 依赖闭包 sweep**,追到叶子:

强制调用链闭包:

```
页面/控制器 → 公共 widget/service → 私有 builder → 三方/默认样式 → 资源/色值 token
```

每个公共 UI 依赖逐层反抽:

| 层级 | 必查内容 |
|---|---|
| 承载层 | route/dialog/overlay/barrier/safeArea/alignment/transition/dismiss |
| 内容层 | width/height/constraints/padding/margin/radius/bg/shadow/blur |
| 文字层 | title/content/button text/font/weight/color/align/max lines |
| 按钮层 | 顺序/主次/click handler/disabled/pressed/loading/语义 |
| 资源层 | image/icon/lottie/dark-light variant/tint/color token |
| 主题层 | light/dark/fixed-light/system theme vs app theme |
| 三方默认层 | framework / 三方 package 默认参数 |

禁止:

- 源端调自绘公共弹窗 / sheet 时,目标端直接换成系统 dialog、系统 button、系统 sheet。
- 只迁业务 callback,不迁弹窗承载层和内容层。
- 看到目标端已有同名 service/component 就判定等价——必须先审计并证明 1:1,否则先把源端自绘组件移植成目标端公共组件,再替换所有系统组件式误用。

## lint 状态

- ⏳ pending。难静态检查(需比对源端组件闭包 vs 目标端实现)→ 进 task 起草 / UI 反抽 checklist:"源码出现自定义公共 UI → 做依赖闭包 sweep,承载层+内容层+文字层+按钮层+资源层+主题层逐层反抽,禁用系统默认组件替代"。
