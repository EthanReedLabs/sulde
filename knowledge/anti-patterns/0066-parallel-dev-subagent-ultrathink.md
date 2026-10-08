---
doc_id: "ap-0066"
container: anti-patterns
platform: none
summary: "0066 parallel-dev 所有 subagent 都用 ultrathink"
---

# 0066 parallel-dev 所有 subagent 都用 ultrathink

- **平台**:协调端
- **复发次数**:0

## ❌ 错误

3 个 subagent 都用 ultrathink,思考预算 = 64K × 3 = 192K。

## ✅ 正确

按子任务复杂度分配:
- 架构改动子任务 → ultrathink (64K)
- UI 还原子任务 → think hard (16K)
- 翻译 / 资源子任务 → 默认 (0)
- 总预算 ~80K,节省 ~58%
