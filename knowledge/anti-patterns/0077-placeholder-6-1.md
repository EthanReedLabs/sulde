---
doc_id: "ap-0077"
container: anti-patterns
platform: none
summary: "0077 列表里图片不复用"
---

# 0077 列表里图片不复用

- **平台**:双端
- **复发次数**:0

## ❌ 错误

每次列表 cell 绑定都创建新的图片请求。

## ✅ 正确

用图片加载库的内存缓存 + crossfade,复用解码后的 bitmap。
