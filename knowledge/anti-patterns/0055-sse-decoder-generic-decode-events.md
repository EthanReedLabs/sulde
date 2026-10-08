---
doc_id: "ap-0055"
container: anti-patterns
platform: cross
summary: "0055 SSE 流式协议 Decoder 对每行 generic decode<业务模型> 静默吞错 → 0 eve…"
---

# 0055 SSE 流式协议 Decoder 对每行 generic decode<业务模型> 静默吞错 → 0 events / 流空跑

- **平台**:iOS(确认) / Android(同源复用)
- **复发次数**:1

## ❌ 错误 — 症状

SSE 接入实测:path 对 + HTTP 200 + SSE 流真返多类 EVENT_TYPE(RUN_STARTED / STEP_STARTED / MESSAGES_SNAPSHOT / **STATE_SNAPSHOT** / TEXT_MESSAGE_CHUNK / STEP_FINISHED / RUN_FINISHED)— 但 **Reducer 收到 0 messages received**。

## 为什么错(根因)

`SSEStreamDecoder.decode<StateMessage>(lines:)` 对每行 SSE `data:` 行直接 `JSONDecoder.decode(StateMessage.self, from:)` — 但实际 line 是**协议 envelope** `{"type":"<EVENT>","snapshot":{...真 StateMessage...}}`,**不是直接业务模型**。decode 失败 catch silent skip → 0 events + 0 错误信号。

```
SSE 行 = data: {"type":"STATE_SNAPSHOT","snapshot":{...}}
              ↓ generic decode<StateMessage> 对外层 envelope decode
              → keyNotFound("steps") / typeMismatch → catch silent skip
              ↓
          eventIndex = 0 + 流自然结束(0 messages received)
```

envelope 双键名 + try? 吞错反模式的**流式协议层具体子集** — 协议层 envelope 包裹业务模型时,Decoder 必须知道"先剥 envelope 再 decode 业务"。

## ✅ 正确 — 修法

不用 generic decode,**Adapter 层手动 envelope parser**:

```swift
for try await line in lines {
    guard line.hasPrefix("data:") else { continue }
    let payload = String(line.dropFirst(5)).trimmingCharacters(in: .whitespaces)
    guard !payload.isEmpty, payload != "[DONE]" else { continue }

    do {
        let envelope = try JSONDecoder().decode(SseEnvelope.self, from: Data(payload.utf8))
        if envelope.type == "STATE_SNAPSHOT", let snapshot = envelope.snapshot {
            let stateMsg = try JSONDecoder().decode(StateMessage.self, from: snapshotData)
            emit(stateMsg)
        } else {
            // 处理其他 EVENT_TYPE
            log("ignoring event type: \(envelope.type)")
        }
    } catch {
        log.warning("envelope parse failed: \(error) | line=\(payload)")  // 不 silent
    }
}
```

Android 同(`SSEStreamDecoder.kt` generic decode 不工作,Adapter 层加 envelope parser)。

## 判定线

任何 SSE 流式 endpoint 实施 task md 必含:
1. envelope 格式 schema(`data: {"type","snapshot/data"}`)
2. event type 完整列表
3. 每类 type 处理策略(STATE_SNAPSHOT only emit / 其他 显式 log)
4. parse 失败 catch + 显式 log(不 silent)

## lint 状态

- iOS:⏳ TODO(grep `SSEStreamDecoder.decode<` 调用,review 是否对 envelope 直 decode 业务模型)
- Android:同
- 协调端:写 SSE 流式 task md **必显式给 envelope schema + EVENT_TYPE 列表**,不能让 Dev 凭印象 generic decode

## 关联

- envelope 双键名 + try? 吞错 — 本条是其流式 SSE 子集
- 协调端凭印象 generic decode 能 work — task md 没显式 envelope schema = 双重违规
