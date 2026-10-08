---
doc_id: "ap-0135"
container: anti-patterns
platform: cross
summary: "0135 跨端导航 routing id 串单一 extra 传 vs 分离参数传 — Android 易污染下游"
---

# 0135 跨端导航 routing id 串单一 extra 传 vs 分离参数传 — Android 易污染下游

- **平台**:Android / iOS(跨端架构对照)
- **复发次数**:0

## ❌ 错误

模块 A → 模块 B 导航 / Intent / delegate 传参时,把 **routing id**(类型字符串如 `"mv_agent"`)和**业务数据**(prompt / params / source)用**同一单一 extra 串**传递,而非分离参数 / 结构化对象:

```kotlin
// HomeFragment.kt
intent.putExtra("remix_type", createType)  // ⚠️ createType = "mv_agent" 串单一 extra

// 下游 Activity
val remixType = intent.getStringExtra("remix_type")
SelectStyleTag(remixType)  // ⚠️ 被当 style tag 接

// Store 通用 append 机制(设计给"选风格 chip"用)
"$currentPrompt, ${intent.tag}"  // ⚠️ "mv_agent" 拼到 prompt 末尾 → 污染提交 BE
```

根因:routing id 与业务数据语义边界模糊;单一 extra 无字段类型保护;通用 "append tag" 机制不区分 caller。

## 为什么错

下游模块接收时无 type 字段语义边界,在通用 "append tag" / "selectStyle" 机制中把 routing id 当成业务数据消费 → routing id 泄漏进 submit body,污染提交。

## ✅ 正确(架构天然免疫)

```swift
// delegate 用分离参数
case navigateToCreate(type: String, sourceId: String?, remixSource: RemixSource?)

// 路由层:type 仅 switch 消费,不下传子 State
switch type {
case "feature_a": return .featureA   // ✅ type 仅路由判断
}
state.pendingRemix = remixSource   // ✅ 只业务数据进子 State,type 路由层即丢弃

// 子 Feature prompt 来源 = 结构化对象字段,直接赋值无 append
state.prompt = params.prompt   // params.type 从未被读取
// 唯一 append 口子由用户 UI delegate 触发,source 隔离
```

铁律:
1. **routing id 与业务数据分离传**:导航 / Intent / delegate 必用分离参数(`type` + `sourceId` + `payload`)或结构化对象,不串单一 extra。
2. **routing id 不下传子模块**:`type` 仅在路由层 switch / match 消费,不进任何子 State 字段。
3. **通用 append / select 机制必 source 隔离**:caller source 必约束(仅 user-driven UI delegate),不接受 routing 层透传。
4. **submit body 字段独立编码**:`prompt`(业务数据)+ `type`(routing id)在 adapter / API request body 内必独立字段,严禁 string concat。

适用扩展:DeepLink 解析 / 跨 Tab 跳转 args / Notification Intent extras / 跨端 message 协议 — 凡带 routing 信息 + 业务数据,必 type field + data field 分离。

## lint 状态

❓ — Android:grep Intent extra 同时含 routing id + getStringExtra 后 concat 进其他字符串 → 警告。iOS 架构层免疫(delegate 强类型分离参数 + struct payload),无需 lint。

## 关联

- 跨端镜像 L10n key 多用未 grep(同源跨端架构对照价值)
- audit subagent 凭关键词不 verify(本批协调端 task md 偏差 `"mv"` ≠ `"mv_agent"` 同源)
