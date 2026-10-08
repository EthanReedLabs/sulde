---
doc_id: "ap-0107"
container: anti-patterns
platform: cross
summary: "fixture 必须逐行镜像真实 SSE wire"
related: ["ap-0224"]
---

# 0107 — fixture 必须逐行镜像真实 SSE wire

- **平台**:iOS / Android(双端 mock 回放共性问题)
- **复发次数**:2

## ❌ 错误

mock 引擎 / 测试录制 / 离线回放场景中,用"人类可读摘要"或"解码后语义"作 fixture 源,丢字段。典型反例:

- ❌ 用日志摘要源转 fixture(丢 envelope marker)。
- ❌ 手工合成快照含纯文本 content(失结构化 JSON 字符串首字符)。
- ❌ 结构化卡缺关键字段(如 `step_id` / `name`)。
- ❌ 把结构化 JSON 放进流式文本 `delta`(App 主动丢 `{` 开头 chunk)。

### fixture 迭代史(典型踩坑路径)

| 版本 | 问题 |
|:-:|---|
| v1 | 状态快照仅 status 骨架,消息快照空 → 预览无内容 |
| v2 | 状态快照富 dict ✅,但结构化卡放进流式文本 delta(被 App JSON 过滤丢弃)且缺 `step_id`/`name` → 卡片不出 |
| v3 | 结构化卡回到消息快照 assistant content(带 `step_id` / `name`)→ 一端全通,另一端仍卡(message ordering / dedupe 差异)|
| v5 | 直接用真机 raw wire 抽取 → 双端全通 |

### 复发新维度(envelope 解析层)

`STATE_SNAPSHOT.payload` 含 `{snapshot: {...}}` 双层 wrap。新录制工具忠实录 Real envelope `{type, snapshot:{...state...}}`(对的),但 mock adapter 的 STATE_SNAPSHOT 分支直接拿 `payload` 当 state → 没取 `snapshot` 子层 → 状态读不到 → VM 不推进 → 卡死。**fixture 镜像 wire 对了,mock 消费端没对齐 Real adapter 的 envelope 解析**。修法:`val snap = payloadObj["snapshot"]?.jsonObject ?: payloadObj`(兼容新旧录制)。

## ✅ 正确

```jsonl
data: {"type":"MESSAGES_SNAPSHOT","content":{"messages":[{"id":"msg_xxx","role":"assistant","content":"{\"type\":\"check_step_result\",\"step_id\":\"step_xxx\",...}"}]}}
data: {"type":"STATE_SNAPSHOT","content":{"steps":[{"id":"step_xxx","task_name":"Analysis","status":"success",...}]}}
data: {"type":"TEXT_MESSAGE_CHUNK","content":{"messageId":"msg_yyy","delta":"raw 文本"}}
```

- 直接落盘 SSE 流每行 `data: <envelope>`,1:1 wrap 进 fixture line(jsonl)。
- 双端 mock 复用 Real adapter 的**同款 parser**(状态解析 + 结构化消息解析 + 内层 `content.id` dedupe)。

## 为什么错

| 原因 | 说明 |
|---|---|
| 1. 协议层多通道设计 | 流式文本通道 App 忽略 JSON;消息快照 assistant content 必为结构化 JSON string 才出可点击卡 |
| 2. App 主动过滤防御 | App 主动丢 `{` 开头 chunk(防 JSON 错放通道)— "人类可读化"fixture 命中此过滤 |
| 3. 字段必需性隐性 | `step_id` / 内层 `content.id` 用于 dedupe — 缺一即静默失败,无报错 |
| 4. 累加快照 vs 流式语义 | 消息快照是累加快照(需按内层 `content.id` dedupe);摘要化 fixture 失 id → dedupe 失效 → 同卡刷屏 |

## 判定线(违一即 fixture 必废)

1. **消息快照 assistant content 首字符必为 `{`**(JSON 起始)。
2. **状态快照 steps[].id 全字段非 null**(`step_id` 不可省)。
3. **流式 delta 是 raw string**(裸文本 / stringified JSON 任一,不 wrap 也不解码)。
4. **消息快照必含 dedupe key**(内层 `content.id`)。
5. **mock 各 event type 的 envelope 解析必须逐字段对齐 Real adapter 取法**(如状态快照取 `envelope["snapshot"]` 子层)。fixture 镜像 wire ≠ 万事大吉,mock **消费端**也要镜像 Real adapter 解析。

## §回放速度 — 单步 delay 必须封顶

### 现象

mock 回放按录制真实 timestamp 比例 delay,未封顶。录制是真实整跑(含每步 AI 生成真实等待,单步可达数百秒)。倍速后单步仍卡数十秒,UX 烂(等待时认为 mock 卡死)。

### 修法

```kotlin
companion object {
    const val MAX_STEP_DELAY_MS = 500L  // cap 砍超长 AI 等待 gap
}
val delayMs = ((event.timestampMs - prevTs) / speed).coerceIn(0L, MAX_STEP_DELAY_MS)
```

### 经验

mock/回放工具按真实时序回放时,**必给单步 delay 封顶** — 录制的真实等待(AI 生成/网络)对"验证 UI"无意义,倍速治标(单步仍长),封顶治本。

## lint 状态

```bash
# fixture(.jsonl)质量:每行必含 data: marker
for fixture in "$FIXTURE_DIR"/*.jsonl; do
    BAD=$(grep -cv '^data: ' "$fixture")
    [ "$BAD" -gt 0 ] && echo "⚠️ §0107 $fixture: $BAD 行缺 'data:' marker" && exit 1
done
```

运行时验证更直接:Test Engine 启动时按内层 dedupe 计 unique structured 数,跑完若远低于预期则 fixture 质量必差。

## 关联

- §0108(DI 单例 + 运行时配置 stale state — 同源 mock 沉淀)。
- 协调端 baseline 实证(fixture 体积决策走 user 拍板而非凭印象)。
