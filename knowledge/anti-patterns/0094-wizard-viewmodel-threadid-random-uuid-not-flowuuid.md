---
doc_id: "ap-0094"
container: anti-patterns
platform: none
summary: "Wizard ViewModel 会话 ID 凭本地随机 UUID 不接 server 返回 ID → 后端报错"
---

# 0094 — Wizard ViewModel 会话 ID 凭本地随机 UUID 不接 server 返回 ID → 后端报错

- **平台**:双端通用
- **复发次数**:4（同一 bug 4 个独立文件，Dev 知识未跨 Feature 扩散）
- **lint 状态**:⏳ pending（候选规则见末尾）

## 现象

进多步创作流（wizard）→ 选输入 → 填 prompt → Submit 后:
- 后端流式接口（SSE）反复返通用错误码 + "Oops, an error occurred. Please try again."
- 用户感受:流程无法启动 / 异常结束
- 多轮诊断后才定位

## 根因

Wizard ViewModel 用 `UUID.randomUUID().toString()` 本地随机生成会话 ID（threadId / sessionId），**首次 Submit 流程后没用 createSession 接口返的 server 端会话 ID 替换**:

```kotlin
// ❌ 现状（多处文件同模式）
private var threadId: String = UUID.randomUUID().toString()
// 整个 ViewModel 生命周期都用这个 random UUID
// Submit 成功后没有 setFlowUuid(result.taskId) 类替换路径
```

后端拿到 random UUID 查 session record → 找不到对应 createSession 创建的 server ID → 返错误码。

接口契约明确:
- 创建会话接口返 server 生成的 ID（形态如 `M001505982717874016256`）
- **"创建成功后，最关键依赖字段是这个 server 端会话 ID"**
- 后续所有流式接口 / 状态查询 / 参数详情接口的会话 ID 字段都必须等于它

**一端某 Feature 已正确实施**（参考）:

```swift
// ✅ 正确 pattern — .run 内 sequential
return .run { send in
    let submitResult = try await aiClient.submit(.someFlow(params))
    await send(.result(.submitSucceeded(taskId: submitResult.taskId)))
    try? await Task.sleep(for: .milliseconds(300))
    let threadId = submitResult.taskId   // ← 直接用 server 返回 ID
    let stream = chatStreamClient.sendUserMessage(.someAgent, composedText, threadId)
    ...
}
```

**4 处复发**（同 bug 模式）:同一 wizard 模式跨 2 端 × 2 Feature，其中 1 处单独修对，说明 Dev 知识未跨 Feature 扩散 — 修对的那个团队读了接口契约，其他 3 个团队没读 / 没修。

## 修法

### 方案 A（命令式 ViewModel）:`setFlowUuid` setter + caller 桥接

```kotlin
private var threadId: String = UUID.randomUUID().toString()   // 保留作 init fallback

/**
 * Submit 成功后立即调，用 server 返回 ID 替换本地 random threadId.
 * 后续所有 streamSession / checkStatus / loadState 都用 server ID.
 */
fun setFlowUuid(flowUuid: String) {
    threadId = flowUuid
}
```

### 方案 B（TCA reducer）:sequential `.run`

```swift
return .run { send in
    let submitResult = try await aiClient.submit(.someFlow(params))
    await send(.result(.submitSucceeded(taskId: submitResult.taskId)))
    let threadId = submitResult.taskId   // ← 直接 sequential 用
    let stream = chatStreamClient.sendUserMessage(.someAgent, text, threadId)
    ...
}
```

或 reducer 内 `state.threadId = action.taskId` 替换 random UUID。

## 防御机制（架构规范文档化）

> ### Wizard ViewModel 会话 ID wire 规范
>
> 所有调流式接口的 wizard ViewModel **必须**:
> 1. ViewModel state 会话 ID 字段允许 random UUID 作 init **fallback**（防起手空指针）
> 2. **Submit 成功后立即替换** 为 createSession response 的 server 端会话 ID
> 3. 后续所有 streamSession / checkStatus / loadState 用该字段（已是 server ID）
> 4. Resume 入口（历史会话恢复）同样接 server ID 入参替换
>
> **禁止**:Submit 成功后保持 random UUID;random UUID 作流式接口会话 ID

## Lint 候选

```bash
# Android: grep `var threadId.*= UUID.randomUUID` 同 ViewModel 内必有 setFlowUuid / threadId = .*taskId
grep -rn "threadId.*= UUID.randomUUID" <feature 源码目录>/ | while read line; do
    file=$(echo "$line" | cut -d: -f1)
    if ! grep -q "setFlowUuid\|threadId = .*taskId\|threadId = flowUuid" "$file"; then
        echo "⚠️ $file: threadId random UUID init 但无 server ID 替换路径"
    fi
done
# iOS: grep `var threadId.*= UUID().uuidString` 同文件内必有 state.threadId = .*taskId reduce
```

## 协调端反省

本 bug 多轮 fix 失败的 process root cause:协调端跳过"grep 接口契约 + PRD 对照"步骤，没在第一轮发现 wire bug。第一轮 grep 接口契约 + grep 双端 ViewModel 会话 ID 来源 = 立即定位全部 wire bug。

## 关联

- 协调端 audit 凭症状推 Module 跳过 grep 接口契约（本 bug 多轮 fix 失败的 process root cause）
- 接口契约:createSession / checkStatus / 流式接口入参契约
