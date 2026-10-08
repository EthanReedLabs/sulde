---
doc_id: "work-model/lossless-knowledge-dedup"
container: work-model
platform: none
summary: "知识判重合并不是删除较短文档：必须先做双向差集，把技术真值与复发次数、lint、静态门禁、review checklist、别名关系等治理资产无损并入 canonical，再用 tombstone 保留旧身份。"
related: [platform-kb/harmony/arkui-layout-scroll-shell, ap-0147]
sedimented_by: auto
---

# 知识判重必须无损合并技术真值与治理资产

## 问题

两篇文档描述同一根因时，较短的一篇常被判为“子集”并直接删除或重定向。但它仍可能
独有复发次数、lint 可行性、静态 grep、review checklist、适用边界或历史引用。若只比较
技术正文，合并后的 canonical 看起来更整洁，实际防复发能力却下降。

## 合并事务

1. **冻结输入**：记录两篇原文路径、`doc_id` 与内容摘要，完整读取后再决定 canonical；
   excerpt、标题和篇幅不能作为子集判定依据。
2. **做双向差集**：分别列 `A-B` 与 `B-A`，至少覆盖技术机制、症状/证据、复发次数、
   lint 状态、自动门禁、review checklist、操作前提、aliases/supersedes 和相关引用。
3. **选择 canonical**：按权威来源、稳定路径、范围与现有活跃引用选择，不按“哪篇更长”
   选择。把双向差集的有效并集写入 canonical，并标出治理元数据的来源。
4. **保留 tombstone**：旧路径和旧 `doc_id` 保留为 deprecated 重定向，只包含身份、目标和
   迁移说明；技术真值只维护一份。
5. **迁移消费者**：更新活动引用、facet 索引、aliases/supersedes 与 manifest；历史审计
   引用可以保留，但必须能沿 tombstone 到达 canonical。
6. **原子验证**：frontmatter lint、活动引用扫描、INDEX/MANIFEST 生成检查、相关 golden
   检索和 `git diff --check` 同批通过后才算合并完成。

## Review checklist

- [ ] canonical 包含两边全部独有治理字段，而不只是技术正文。
- [ ] 复发次数按可追溯事件合并，没有因换路径归零或重复相加。
- [ ] lint/静态门禁与人工 review 项均有落点；不适用项明确写原因。
- [ ] tombstone 不残留第二份可编辑技术真值。
- [ ] 活动消费者不再引用旧技术页；旧 `doc_id` 仍可解析。
- [ ] 索引、manifest、相关测试与检索回归全部通过。

## 判定线

“保留文档覆盖被删文档的大意”不是无损合并。只有双向差集归零，且旧身份可追溯、活动
消费者已迁移、治理门禁未减少，才允许关闭判重任务。
