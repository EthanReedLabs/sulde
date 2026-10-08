---
doc_id: "ap-0232"
container: anti-patterns
platform: cross
summary: "流式或新发消息已经写入数据库，但 UI 继续持有无持久 ID 的临时对象，导致长按编辑、删除和重新生成按 ID 查询时静默无效"
related: [ap-0209, ap-0210, ap-0170]
sedimented_by: auto
---

# 0232 — 消息写库后不回读稳定 ID，后续按 ID 操作静默失效

- **平台**：Android / iOS / 其他本地持久化客户端
- **复发次数**：0

## ❌ 错误

发送或流式生成完成后把消息写入数据库，却继续把写库前的临时对象追加到 UI：

```kotlin
val transient = Message(id = null, clientId = requestId, text = finalText)
dao.insert(transient)
uiMessages += transient // ❌ DB 已生成主键，UI 仍持有 id=null
```

新消息当下看起来正常，但长按后的编辑、删除、重新生成通常用持久 ID 定位记录。调用拿到
`null`、临时序号或旧对象 ID 后，DAO 更新影响 0 行；若调用方没有检查 affected rows，
用户看到的就是“点击没反应”，重启后还可能重新出现已在内存中删除的内容。

## 为什么

- **持久层才是稳定身份的权威**。数据库自增 ID、UUID 默认值或去重后的 canonical row
  只有写入完成后才确定，写入前对象不能冒充已持久化实体。
- **写库成功与 UI 身份收敛是两步**。只完成第一步，文本和视觉可以正确，但所有依赖
  主键的后续命令仍连接不到真实记录。
- **流式场景会放大竞态**。临时气泡、分片累积、最终消息和数据库记录可能各有一套对象；
  若没有稳定 correlation key，刷新时还可能重复插入或替换错项。
- **截图验收容易假通过**。截图只能证明文字出现，不能证明对象已获得持久 ID；这与
  `ap-0210` 中“UI 成功不等于 DB 成功”互为正反两面。

## ✅ 正确

1. 让 insert/upsert 返回持久 ID，或写入后按稳定 correlation key 从数据库回读
   canonical row。
2. UI 只用回读后的实体替换临时对象；若数据库是单一真值，优先让 UI 订阅查询流，避免
   手工维护第二份列表。
3. 临时对象必须有显式 `persisting` 状态；编辑、删除、重新生成只能在 stable ID 到位后
   开放，不能把 `null` 偷换成 0 或数组下标。
4. DAO 更新/删除必须断言 affected rows；0 行是可观察失败，不能静默吞掉。
5. 验收覆盖：发送完成后立即编辑、删除、重新生成；杀进程冷启后再次执行；确认 UI ID、
   DB 主键和操作目标三者一致。

## lint 状态

- ⚠️ 可检：扫描 `insert(...)` 后把原对象直接追加到 UI、`id ?: 0`、用列表下标代替主键
  的路径。
- ✅ 测试门禁：DAO insert 返回值必须进入 UI 状态，更新/删除 affected rows 必须大于 0；
  冷启后的同一记录仍可编辑和删除。
- ❌ 无法只靠 grep 证明：需要验证临时对象到 canonical row 的运行时身份收敛。
