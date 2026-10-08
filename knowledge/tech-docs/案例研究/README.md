---
doc_id: "tech-docs/案例研究/README"
container: case-studies
platform: none
summary: "移动端（Android / iOS / HarmonyOS）疑难问题的工程案例库。"
---

# 移动端工程技术知识库（跨项目复用）

> 移动端（Android / iOS / HarmonyOS）疑难问题的工程案例库。每篇为一个真实问题的完整复盘：现象 → 根因 → 修复 → 可迁移原则。
> **定位：跨项目复用的工程参考 + 人才培养材料**（项目无关、已脱敏）。随项目积累持续完善，不针对任一交付方。

---

## 适用读者

- **工程团队**：开发媒体播放、列表性能、跨端一致性、缓存架构类功能前，先查同类案例，避免重复踩坑。
- **技术评估 / 交接**：了解项目在移动端深水区问题上的诊断深度与解决质量。
- **人才培养 / 面试**：每篇含「深问」环节，可直接作为技术案例讲解与考核材料。

---

## 知识库系统（两层 + 活回路）

本库是【活系统】的产出层，不是一次性文档。两层分工 + 一条自维持回路（防知识冻结）：

- **Layer1（内部）** = `<docs-hub>/_bugbook` + 反模式 ADR：详尽、含 commit / 类名 / 人名 / handoff，团队内 grep 复用。
- **Layer2（本库）** = 脱敏、项目无关的案例研究，跨项目复用 / 人才培养。

```
baseline 沉淀欠债指标（让欠债可见，每次启动糊脸）
  → 修前必查 Layer1（writing-task-md §0 Step 0b：review-similar 找前车之鉴）
  → 修后必沉淀 Layer1（coordinator-maintenance §4.2：归档前 add-bug）
  → 定期上浮 Layer1 → Layer2（curate-to-kb skill：脱敏精选 + 三道门质检）
```

新增案例走 `curate-to-kb` skill：执行器起草 → 三道门（C 验真 / A 质量对齐标杆 / B 脱敏）→ 达标 promote。

---

## 技术栈覆盖

| 平台 | 关键技术 |
|---|---|
| Android | ExoPlayer / RecyclerView / ViewPager2 / MediaCodec / AudioFlinger / Choreographer / 线程模型 |
| iOS | TCA（The Composable Architecture）/ swift-dependencies / SwiftUI / AVPlayer |
| HarmonyOS | ArkTS / ArkUI Stage Model / NavPathStack / bindContentCover / @Builder 响应式 / Flutter→ArkUI 转译 |
| 跨端 | 三级缓存架构 / 视觉还原 / 平台差异一致性 / 性能诊断方法论 |

---

## 目录导航

| 技术域 | 内容 | 案例数 |
|---|---|:--:|
| [01-Android媒体与性能工程](./01-Android媒体与性能工程/) | ExoPlayer 离屏渲染、RecyclerView 视频列表、滑动卡顿诊断、多路音频、音频起播延迟 | 4 |
| [02-iOS-TCA架构实践](./02-iOS-TCA架构实践/) | 依赖注入 scope、状态机闭环、模态 present 竞态、列表分页卡顿与 Perception 粒度、条件读取下的依赖追踪稳定性、缓存链路、流式快照单调合并、异步媒体子页播放所有权 | 7 |
| [03-跨端一致性工程](./03-跨端一致性工程/) | 双端对称、视觉还原、平台差异处理、并发状态竞态对称修复 | 2 |
| [04-移动端缓存架构](./04-移动端缓存架构/) | L1/L2/L3 三级缓存、stale-while-revalidate、网络层单例化与连接预热、图片加载三级缓存、HTTP 缓存、链路断裂排查、请求级单飞与多订阅者广播、用户已有资产复用 | 6 |
| [05-诊断方法论](./05-诊断方法论/) | 性能诊断 SOP、根因定位、同症多因辨析、不可复现崩溃边界防御、媒体加载失败证据优先诊断、轮询守卫三值语义、流式连接终止路径与终态闸门 | 5 |
| [06-HarmonyOS-ArkUI工程](./06-HarmonyOS-ArkUI工程/) | SSE 流式生命周期与分帧、ArkUI 浮层响应式/宽度/键盘深水区 | 2 |

> 案例数随沉淀持续增长。本库为活资产，新疑难问题修复后按统一模板落盘。

---

## 案例统一模板

每篇新增或实质更新案例使用 `templates/knowledge/case-studies.md`，确保可读、可复用、
可检索、可监督：

1. **场景与系统架构** — 问题发生的上下文与相关模块结构图
2. **问题现象** — 可观测的表现 + 实测数据（帧率 / 耗时 / Profiler trace）
3. **根因分析** — 深入到平台机制层面的原理解释（不止"改了什么"，而是"为什么会这样"）
4. **解决方案** — 具体修复与设计决策，含"为什么这样修 / 为什么不那样修"
5. **可迁移原则** — 抽离出的通用工程规律，可应用于其他项目
6. **技术深问**（可选） — 针对该案例的进阶问答，用于讲解与考核
7. **适用边界与四类样本** — 路由 `apply/skip` + 执行 `pass/fail`，逐项标
   `observed|constructed`
8. **消费与防复发** — 明确进入 Skill、门禁、测试或仅供检索

---

## 如何查阅

按技术域进入对应目录，或按关键词检索：

```bash
# 按关键词搜全库
grep -rl "ExoPlayer\|RecyclerView\|playWhenReady" .

# 按技术域浏览
ls "01-Android媒体与性能工程/"
```
