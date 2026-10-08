---
doc_id: "ap-0125"
container: anti-patterns
platform: cross
summary: "0125 后端错误话术 UI 抽象不匹配 + 可操作真因藏在子对象"
---

# 0125 后端错误话术 UI 抽象不匹配 + 可操作真因藏在子对象

- **平台**:协调端 / Android / iOS / 后端文档
- **复发次数**:0

## ❌ 错误

后端顶层 `error_message` 引用 web 端 UI("请查看**右侧面板**并点击重新生成"),而 App 端没有侧边栏 → 用户更懵;真正可操作真因("上传的图片不合规,请替换")藏在失败子项的 `子对象/{id}/raw_error_message`,客户端 decoder 只解析顶层 `error_message_v2`,子对象真因直接丢弃。

```kotlin
// ❌ decoder 只取顶层
message = snapshot.error_message ?: snapshot.error_message_v2
// 没下钻 子对象[].raw_error_message

// ❌ 错误呈现直接透传后端话术
showToast(state.message)   // 用户看到"请查看右侧面板"但 App 没有侧边栏
```

## 为什么错

- 后端 error_message 由后端 / web 团队编写,**默认 web UI 上下文**;App 跨端复用同一份文案 → UI 引用错位。
- Schema 设计**真因 ≠ 概括**(概括给"显示用",真因给"重试 / 修复用",分两个字段合理),但 decoder 实施时容易只取概括漏掉真因。
- 错误呈现 reducer 透传后端文案 = 默认假设"后端给的就是 user-facing",跨端场景这是错的。

## ✅ 正确

```kotlin
// ✅ decoder 下钻子对象错误字段
@Serializable
data class VideoItem(
    val video_url: String?,
    val error_message_v2: String? = null,
    @SerialName("raw_error_message") val rawErrorMessage: String? = null,  // ⭐ 新增
)

// ✅ 错误呈现 reducer:优先取最具体可操作 error + suppress UI 抽象引用
private fun mergeErrorMessages(state: AgentState): String? {
    // Step 1: 失败子项的 raw_error_message(最具体可操作)
    val specific = state.items.values.mapNotNull { it.rawErrorMessage }.distinct()
    if (specific.isNotEmpty()) return specific.joinToString("\n")
    // Step 2: 无具体真因 → 回退顶层,去除 UI 抽象关键词
    val fallback = state.errorMessage ?: state.errorMessageV2 ?: return null
    return fallback
        .replace(Regex("\\b(right-side panel|top-right corner|left sidebar|sidebar)\\b", IGNORE_CASE), "")
        .replace(Regex("\\s+"), " ").trim().takeIf { it.isNotBlank() }
}
```

原则:
1. **SSE / API DTO 定义时必下钻 1-2 层子对象** verify 是否有 per-item 错误字段(`raw_error_message`/`failure_reason`),全加进 DTO 不只取顶层。
2. **错误呈现 reducer 模板化**:具体真因优先(子对象 per-item)→ 顶层 fallback → sanitize UI 抽象关键词。
3. 协调端 task md 起草 SSE/API 类必含"错误呈现 review"段(列顶层 + 子对象 error 字段 + 取哪个字段优先 + sanitize 规则)。

## lint 状态

⏳ pending — grep 后端真响应顶层 error_message 是否含端不存在的 UI 关键词(right-side panel / top-right corner / left sidebar);命中且客户端未 sanitize → 软警告。

## 关联

- adapter wrap ≠ 真链路(同源:凭"看似合理"反推 → schema 假设错)
- 后端真响应可能与文档不符
