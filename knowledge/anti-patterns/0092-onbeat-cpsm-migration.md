---
doc_id: "ap-0092"
container: anti-patterns
platform: none
summary: "单模块长期密集 patch 散落 → 抽统一 State Module 收敛重构"
---

# 0092 — 单模块长期密集 patch 散落 → 抽统一 State Module 收敛重构

- **平台**:双端 + 协调端
- **复发次数**:0（预防性沉淀，不是 bug 复盘）

> 本条记录"一片代码被密集 patch 堆叠后，何时该停止继续 patch 改为架构层根治"的工作模型。

## 1. 现象（约 14 天密集观察期）

双端某复杂列表/媒体模块各 ~25 commit / 14 天，全部围绕同一片代码堆叠性能 patch:

**典型 commit 主题**:player 生命周期抽离 / 三级缓存启动预热 / 进场动画期间不渲染卡片 / player attach 延后 / 多 State 合并 enum / Equatable + .equatable() 跳过无变化卡片重算 / fast swipe 期间跳过媒体创建 / 主线程 init 移后台……

每次 patch 触动同样的几个超大文件（一个 2000+ 行 View + 一组 Adapter/Manager 合计 ~1500 行）。

**症状**:
- 同一片代码层层加防御，主路径已乱
- 双端各自演化，出现多项不对称防御（一端有一端缺）
- 期间登记的多条性能反模式 ADR 都指向同一片代码

## 2. 根因

**单卡视觉状态**是多个数据源合成:`(data) × (player handle) × (cache hit) × (selected) × (mute) × (scroll-suppression) × (animation phase)`。

双端历史上各自把这些数据源散布到 5+ 个文件，View 在 body / onBind 内手工合成。每加一项防御 = 所有数据源的合成逻辑都要碰一次。

域语言漂移:双端**计算同一概念**（此卡此刻能否播媒体）但词汇不同，协调端写 task md 翻译成本极高。

## 3. 解（架构层根治方向）

新建 **Card Playable State Module**（统一状态模块）:

- 把多数据源中 2 项（player handle + cache）owned 到 Module 内
- 其余 input 通过 imperative setter 上报
- 输出统一 `PlayableState` enum
- 双端共享 contract，跨 Feature 复用

迁移 phase:
- Phase 0（协调端）:spec doc + 领域语言文档 + ADR stub
- Phase 1（双端并行）:Module 骨架 + 单测 ≥ 90%
- Phase 2（双端并行）:切换 + 删旧 PlayerManager / cache / scroll guards
- Phase 3（双端并行）:清理 dead code + lint 状态 enforce

## 4. 迁移期暴露的协调端 grilling 漏题（教训）

Phase 0 多轮 grilling 仍漏掉若干 critical question，导致 Phase 1.5 / 1.5b 返工:

1. **谁负责驱动**:Module 借了 player handle 后，谁负责 setMediaItem / prepare / play / pause（spec 只说"handle opacity"未明示 driver API）→ 结果 Module 0 处调驱动 API → player 永远空白
2. **循环播放支持**:spec 完全没提循环播放，但业务必循环
3. **volume 公式与真 UX 冲突**:全局 mute 按钮含选中态，但公式 selection 优先 → 公式需反转（muted 优先于 selected）
4. **凭印象写 API 版本**:spec 凭印象写某 API 是 iOS 17+，实际 iOS 18+
5. **public API fire-and-forget + caller 假设源码顺序**:setter 都是 `Task { await actor.X }` / `scope.launch { actor.X }` 异步 fire-and-forget;caller 顺序调 `register → setVisibility → setMuted`，但 **Swift actor non-FIFO message ordering** + **Kotlin Mutex 非严格 FIFO** → early setter 早于 register 到达 actor → `guard let entry else return` silent no-op → 初始状态丢失 → 媒体不播 / mute 无反应

→ 修法:ModuleActor 加 `pendingPerCardInputs` 缓冲（对称 `pendingSubscribers`），setter 未 register 时缓冲，register 时迁回初始状态。

**协调端 grilling 必含的 critical question 模板**:
> "public API 是否 fire-and-forget？caller 是否假设源码顺序 = 处理顺序？对 actor/Mutex 非 FIFO 是否有 buffer 防 setter 丢失？谁负责驱动底层资源？边界 case（循环 / 静音公式 / 版本兼容）是否在 spec 明示？"

## 5. Lint 状态变化（重构后）

| 原 ADR 主题 | 原 lint 状态 | 重构后 |
|---|---|---|
| 每次 new player | pending | **enforced**（Module 内禁直接 init） |
| UI 时序约束 | pending | **enforced**（Module 内置 phase 处理，不需 task md 段） |
| LazyVStack closure 参数 Equatable | pending | **enforced**（View 不再传 closure，改 observe PlayableState） |
| onAppear loadMore 风暴 | pending | partial（loadMore guard 仍在 Feature 层） |
| PreferenceKey 不可靠 | rejected | **enforced**（Module 接 bool，caller 转译） |

## 6. 复盘要点候选

- 14 天密集 patch 后什么时候应该意识到"该重构而非继续 patch"
- 协调端 grilling 多轮（架构改进 skill）的有效性
- Module 跨 Feature 复用第一次落地，何时拉第二个 Feature 复用作实证
- spec doc + 图 + lint 三件套是否真消除回归

## 关联

- 上游 ADR:每次 new player / UI 时序约束 / LazyVStack closure / onAppear 风暴 / PreferenceKey 不可靠
