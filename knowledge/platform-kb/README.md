---
doc_id: "platform-kb/README"
container: platform-kb
platform: none
summary: "**平台事实速查层**:每个平台一套「rules + workaround」查询库,写该平台代码 / 排该平台视觉异常…"
---

# 平台知识库(platform-kb)

> **平台事实速查层**:每个平台一套「rules + workaround」查询库,写该平台代码 / 排该平台视觉异常前先查。
> 区别于同层其他 4 类:`anti-patterns`(单点反模式)/ `tech-docs`(通用原则)/ `案例研究`(深复盘)/ `work-model`(工作法)。平台 KB 收的是**平台机制事实**(某 API 行为 / 某组合不可共存 / 某 workaround),不是方法论也不是单次事故。

## 定位

- **来源**:各项目 Layer1 的平台知识库(如 `<repo>/docs-hub/harmony-kb/`),按 [`../SEDIMENTATION-STANDARD.md`](../SEDIMENTATION-STANDARD.md) 轻脱敏(删项目页名 / 版本累积来源行,保留平台 API 与 workaround)。
- **消费**:该平台 Dev / 协调端起 task 前 lookup;找已知 rule + workaround,未命中再实施 + 回补。

## 子体系(随来源项目平台扩展)

| 平台 | 目录 | 状态 |
|---|---|---|
| HarmonyOS / ArkUI / ArkTS | [`harmony/`](./harmony/) | 已建(13 篇速查) |
| Android / iOS | [`mobile-android-ios/平台API速查表.md`](./mobile-android-ios/平台API速查表.md) | 已建(双端并排速查) |
| Android | `android/` | 规划(现有反模式已覆盖大量 Android;需要独立速查层时新建) |
| iOS | `ios/` | 规划(同上) |

> 新平台来源项目 → 新增 `platform-kb/{platform}/`,加法维度,不动既有结构。
