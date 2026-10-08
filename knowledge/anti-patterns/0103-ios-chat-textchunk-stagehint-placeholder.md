---
doc_id: "ap-0103"
container: anti-patterns
platform: ios
summary: "iOS Chat 流式 textChunk 临时用占位 capsule 渲染(无累积无 JSON 过滤)"
---

# 0103 — iOS Chat 流式 textChunk 临时用占位 capsule 渲染(无累积无 JSON 过滤)

- **平台**:iOS
- **复发次数**:0(首次沉淀)

## ❌ 错误(iOS 反例 — 占位渲染旧实现)

```swift
case .chatStream(.textChunk(_, let chunk)):
    // assistant 流式 text chunk — 占位渲染到 stageHint(留待升级再按 messageId 累成 typing 气泡)
    if !chunk.isEmpty {
        state.chatGenerate.messages.append(ChatMessage(kind: .stageHint(stageName: chunk)))
    }
    return .none
```

## 为什么错(三重缺陷)

### 缺陷 1:每个 chunk 单独 append 一条 message

`TEXT_MESSAGE_CHUNK` 是 LLM 流式输出协议 — backend 每 5-10 字符推一个 chunk,**同一 messageId 的多个 chunk 应累积到单 message bubble**(增量更新文本),不是每个 chunk append 一条独立 capsule。真机后果:user 看到大量小 capsule chips 列表,极丑。

### 缺陷 2:无 JSON 过滤(stringified JSON 被当文本直显)

Backend 可能在 `TEXT_MESSAGE_CHUNK.delta` 推 stringified JSON object(与结构化快照同源,双 channel 重复推送)。不过滤 → 整坨 `{"type":"...","name":"..."}` raw JSON 当文本直接显示。

### 缺陷 3:重复消息无去重

累积快照(后端每次推全量 messages)若不 dedupe → 同款消息重复多次显示。

## ✅ 正确

### 设计原则:双 Feature 不同行为(严格按各自业务设计)

| Feature 类型 | textChunk 处理 | Why |
|---|---|---|
| **structured-only 流** | `no-op`(丢弃) | 走结构化快照推 stage 推进,不依赖 textChunk 渲染 |
| **chat 流** | 累积器 + 三层防御 | 推流式 LLM 回复,需 stream 累积渲染 |

### structured-only 流正确实现

```swift
case .chatStream(.textChunk(_, let chunk)):
    // 该流不依赖 textChunk 渲染,只走结构化快照
    return .none
```

### chat 流正确实现(三层防御)

```swift
case .chatStream(.textChunk(let messageId, let chunk)):
    guard !chunk.isEmpty else { return .none }
    // 防御 1: jsonStreamIds 持久 set
    guard !state.chatGenerate.jsonStreamIds.contains(messageId) else { return .none }

    let last = state.chatGenerate.messages.last
    let existingText: String
    if case .assistantStream(let lastId, let text) = last?.kind, lastId == messageId {
        existingText = text
    } else {
        existingText = ""
    }
    let newText = existingText + chunk

    if newText.trimmingCharacters(in: .whitespaces).hasPrefix("{") {
        // 防御 2: JSON 过滤 — 累积文本以 `{` 开头 → 标 JSON + 整流丢弃
        state.chatGenerate.jsonStreamIds.insert(messageId)
        if case .assistantStream(let lastId, _) = last?.kind, lastId == messageId {
            state.chatGenerate.messages.removeLast()
        }
    } else if case .assistantStream(let lastId, _) = last?.kind, lastId == messageId {
        // 防御 3: 同 messageId 累积(替换末尾)
        state.chatGenerate.messages.removeLast()
        state.chatGenerate.messages.append(ChatMessage(kind: .assistantStream(messageId: messageId, text: newText)))
    } else {
        state.chatGenerate.messages.append(ChatMessage(kind: .assistantStream(messageId: messageId, text: chunk)))
    }
    return .none
```

### 三层防御 Why

| 层 | 防御场景 |
|:-:|---|
| 1. `jsonStreamIds` 持久 set | 同 messageId 推连续 N 个 chunk,首 chunk 已判 JSON 整流丢弃,后续 chunk 必 skip(防再次累积成新 JSON message)|
| 2. `startsWith("{")` JSON 过滤 | backend 同源双 channel 推 stringified JSON — 列表不 dedupe 会显两次,用 JSON 过滤掉 textChunk 版本 |
| 3. messageId 累积(增量更新)| LLM 流式连续短 chunk,列表末尾若同 messageId → drop + 替换累积全文(单 bubble 不分裂)|

## 检测规则

- 静态 grep:`grep -nE 'chatGenerate\.messages\.append.*stageHint.*chunk'` 命中 = 反模式复发。
- 运行时实证:syslog grep `TEXT_MESSAGE_CHUNK` 频次 vs message 数量 — 基本一致 = 反模式;远小于(累积成单 message)= 正确。

## 复盘 — placeholder 长期未升级的教训

旧实现留注释"升级再按 messageId 累成 typing 气泡"知道是 placeholder,但未 schedule 升级,N 月后后端真实推 stringified JSON 暴露视觉。**所有 placeholder 注释必含 "TODO 时间预算 + trigger 条件"**,不能留"升级再说"。

## lint 状态

- ⏳ pending(可静态 grep `messages.append.*stageHint.*chunk` 误用)。

## 关联

- 同源 webview localStorage 注入(backend 双 channel 同源风险类比)。
- 反模式 0104(被本款占位渲染掩盖的 wave 时序漏 backport)。
