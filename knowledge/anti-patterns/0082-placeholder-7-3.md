---
doc_id: "ap-0082"
container: anti-patterns
platform: none
summary: "❌ **错误**:硬编码 width，长文案被截断或挤压。"
---

# 0082 — 长文案在小屏溢出

❌ **错误**:硬编码 width，长文案被截断或挤压。

✅ **正确**:用 wrap_content + maxLines + ellipsize="end"（或等价的自适应宽度 + 行数限制 + 省略号）。
