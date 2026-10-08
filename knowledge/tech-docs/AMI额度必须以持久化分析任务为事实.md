---
doc_id: "tech-docs/AMI额度必须以持久化分析任务为事实"
container: tech-docs
platform: none
summary: "动作分析额度不能从缓存结果或 UI 内存计数。"
---

# AMI 额度必须以持久化分析任务为事实

动作分析额度不能从缓存结果或 UI 内存计数。缓存只覆盖成功结果，无法表示进行中的任务，也无法阻止并发请求。

可靠做法是把持久化 assistant 分析占位当作 reservation：创建任务时写 `ANALYZING`，完成后改 `DONE`，失败改 `FAILED`。月度统计只计算 `ANALYZING/DONE`，因此进行中请求立即占位、失败自动释放、重试可复用原记录。

额度校验和 reservation 必须在同一数据库事务内，否则两个会话都可能在写入前读到相同余量。自然月边界必须按用户当前时区计算，不能用固定 30 天窗口。

订阅层只提供 tier，额度策略将 tier 映射为明确上限。商店交易是 entitlement 真值；UI 只消费 entitlement，不使用可篡改的本地布尔值。
