---
doc_id: "ap-0065"
container: anti-patterns
platform: none
summary: "0065 简单任务用 ultrathink"
---

# 0065 简单任务用 ultrathink

- **平台**:协调端
- **复发次数**:0

## ❌ 错误

每个任务都加 "ultrathink" 前缀,"反正深度思考更安全"。

## 为什么错

- ultrathink ≈ 64K 思考预算,简单任务浪费 token;
- 响应慢(思考久);
- 不必要的方案权衡反而把简单事变复杂。

## ✅ 正确

- 读单文件 / 简单查询 → 默认
- 中等修改 / Bug 修复 → think hard
- 架构 / UI 对比 / 根因分析 → ultrathink
