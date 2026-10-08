---
doc_id: "ap-0170"
container: anti-patterns
platform: cross
summary: "0170 用可塌缩字段合成 ID 导致集合陷阱或列表错乱"
related: [ap-0198]
---

# 0170 用可塌缩字段合成 ID 导致集合陷阱或列表错乱

- **平台**:跨端
- **复发次数**:1

## ❌ 错误

接口没有主键时，客户端用可缺失或可重复的字段合成 ID。字段缺省值会让多条记录塌缩为同一标识，同一主体在同一时间粒度内产生多条记录也可能天然碰撞。

重复 ID 会被三个常见消费端放大：

- iOS `IdentifiedArray` 的唯一性前置条件触发 trap。
- Android `DiffUtil.areItemsTheSame` 产生身份歧义、错误复用或错误动画。
- Compose 列表使用重复 `key` 时触发运行时异常。

## 为什么错

- “主体字段 + 时间戳”只是看似唯一，无法覆盖字段缺失、默认值塌缩和相同时间粒度碰撞。
- 集合与列表框架把 ID 当作稳定身份契约，而不是普通展示字段。
- 崩溃或渲染异常发生在 UI 消费端，根因却位于 DTO 转换或适配层，容易排错偏移。

## ✅ 正确

1. 优先使用服务端提供的记录主键；没有主键时推动接口补充。
2. 过渡期 ID 必须不可塌缩，可加入页内稳定序号、数组 index，或在适合的生命周期内使用 UUID 兜底。
3. iOS 消费侧使用明确的重复 ID 合并策略(如 swift-identified-collections 的 `IdentifiedArray(_:id:uniquingIDsWith:)`,保留首条不 trap)，避免直接触发唯一性 trap。
4. Android 不应把可塌缩 ID 交给 `DiffUtil.areItemsTheSame` 或 Compose `key`。
5. 分页、重排或刷新场景下，需确认兜底 ID 仍然稳定；仅拼 index 不适合作为跨刷新长期身份。

## lint 状态

- ⚠️ 可做半 lint：命中 `uniqueElements`、Compose `key` 或手工 ID 拼接后，要求人工核查字段是否可缺失、可重复。
- 人工 review：新增“无主键接口 + 合成 ID”时，必须列出所有塌缩路径，并检查 IdentifiedArray、DiffUtil、Compose key 三类消费端。
- 关联：DTO 缺省值、稳定身份契约与集合唯一性约束。
