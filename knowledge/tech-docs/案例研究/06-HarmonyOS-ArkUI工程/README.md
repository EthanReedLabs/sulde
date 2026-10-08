---
doc_id: "tech-docs/案例研究/06-HarmonyOS-ArkUI工程/README"
container: case-studies
platform: none
summary: "HarmonyOS 原生(ArkTS + ArkUI Stage Model)与 Flutter→ArkUI 转译深水…"
---

# 06 — HarmonyOS / ArkUI 工程

> HarmonyOS 原生(ArkTS + ArkUI Stage Model)与 Flutter→ArkUI 转译深水区案例。每篇为一个真实问题的完整复盘:现象 → 根因(深挖到 ArkUI 渲染 / ArkTS 类型系统机制)→ 修复 → 可迁移原则。已脱敏、项目无关。

## 收录方向

- **ArkUI 渲染 / 响应式机制**:`@Builder` reactive 脱钩、bindContentCover / 浮层状态、布局锚点宽度语义、字体颜色渲染差异。
- **ArkTS 类型系统 / 编译**:`instanceof` narrowing、`@Prop`/`@Link` 传播、`any` 禁用下的等价建模。
- **Flutter → ArkUI 转译**:三方 / 复杂控件能力对照(lazy builder ↔ eager array)、滚动 physics、picker、rich text。
- **平台适配**:键盘避让、深浅色主题、字号缩放、平板 / 横竖屏。

## 案例

| 案例 | 技术域 | 难度 |
|---|---|---|
| [SSE 流式响应的生命周期、分帧与静默解码陷阱](./SSE流式响应的生命周期与分帧.md) | 流式网络 / ArkTS | ⭐⭐⭐⭐ |
| [ArkUI 浮层体系的响应式 / 宽度 / 键盘三类深水区](./ArkUI浮层体系的响应式-宽度-键盘三类深水区.md) | ArkUI 渲染 / 浮层 | ⭐⭐⭐⭐⭐ |

> 随沉淀持续增长,走 `curate-to-kb` 三道门(C 验真 / A 对齐标杆 / B 脱敏)。

## 案例统一模板

对齐 [`../README.md#案例统一模板`](../README.md) 五段结构 + 头部元信息 + 可选技术深问。标杆深度见 `01-Android媒体与性能工程/视频列表四类典型缺陷与离屏渲染架构.md`。
