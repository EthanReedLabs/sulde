---
doc_id: "ap-0104"
container: anti-patterns
platform: ios
summary: "iOS 跨 Feature backport 漏接(一个 Feature 升级了时序设计,同款另一个 Feature…"
---

# 0104 — iOS 跨 Feature backport 漏接(一个 Feature 升级了时序设计,同款另一个 Feature 漏 backport)

- **平台**:iOS(单端 — Android 架构差异无对应漏接,见 §Android 评估)
- **复发次数**:0(首次沉淀)

## ❌ 错误(iOS 反例 — 旧 wave 时序)

```swift
case .chatStream(.runStarted):
    state.chatGenerate.isShowingWave = false  // ← RunStarted 立即关 wave(错)
    ...

case .chatStream(.structured(let msg)):
    state.chatGenerate.isShowingWave = false  // ← 任何 structured 立即关 wave(错)
    ...
```

→ user 真机:"loading 动画不在了,但没有消息出来,界面空白"。之前被另一反模式(每 chunk append capsule)用占位 capsule 覆盖空窗期掩盖;占位 fix 后空窗期暴露。

## 为什么错

某个 Feature 早已确定真实设计:**"wave 由 RunStarted→RunFinished 整段持续"**。backend SSE 推送时序实际:

> RunStarted → STEP_STARTED → MESSAGES_SNAPSHOT(可能 plaintext 被 parser 丢)→ STATE_SNAPSHOT(更新 stage 不进 Chat)→ structured(可能延迟)→ TEXT_MESSAGE_CHUNK(可能被 JSON 过滤)→ RunFinished

**RunStarted 到首个可见 structured message 之间存在空窗期**(数秒到数十秒)。若 RunStarted 立即关 wave → user 看到无 wave + 无 message 的空屏,体感"卡了"。

正确设计 — wave 整段持续:RunStarted 开 → 各种 event 跑 → RunFinished 关。该设计在一个 Feature 已实施,**但同款另一个 Feature 漏接此设计**(旧时序未升级)。

## ✅ 正确(对齐已升级 Feature)

```swift
case .chatStream(.runStarted):
    // 不立即关 wave(wave 由 RunStarted→RunFinished 整段持续)
    ...
case .chatStream(.structured(let msg)):
    // 不立即关 wave(同上)
    ...
case .chatStream(.runFinished):
    state.chatGenerate.isShowingWave = false  // ← 唯一关 wave 点
    ...
```

## 检测规则

```bash
# 找所有 RunStarted / Structured 立即关 wave 的反模式
grep -nE 'runStarted.*isShowingWave\s*=\s*false|structured.*isShowingWave\s*=\s*false' Sources/Feature*/
```

跨 Feature backport audit:每次某 Feature 升级类似设计(wave / 累积器 / dedupe 等)时,**协调端 task md baseline 必含 cross-Feature backport check 列**(对齐所有同设计 Feature)。

## 复盘 — 为什么漏接

占位渲染反模式在视觉上掩盖了 wave 时序漏 backport;直到占位 fix(textChunk 改 no-op)→ 空窗期暴露 → user 真机才发现漏接。教训:

1. 跨 Feature backport 必同时实施所有同设计 Feature。
2. 协调端 task md baseline 必含 cross-Feature backport check。
3. 反模式互相掩盖时,fix 一个会暴露另一个 — 必预期"fix 后真机重测,验旧 bug 真消失而非被新症状代偿"。

## §Android 同步评估

**评估结果:Android 不需要同步沉淀此反模式**。

- Android 用 wave 单例 in list(放进 messages 数组,跟其他 message 平铺),不是 iOS `isShowingWave: Bool` 独立 view modifier。
- Android 双 Feature 用同款 `appendLoadingWave` / `removeLoadingWave`,**双 Feature 设计就一致**,不存在"升级时漏 backport"风险。
- iOS `isShowingWave: Bool` 是子 state 字段,双 Feature 独立 dispatch reducer 处理时序可能 diff — 这是 iOS TCA reducer 架构特有的反模式风险。

## lint 状态

- ⏳ pending(跨 Feature backport 漏接是设计语义,非语法,grep 不住)。

## 关联

- 反模式 0103(掩盖关系 — 0103 fix 后暴露 0104)。
- 审计强制第二轮自问"fix 一个反模式是否暴露另一个"。
