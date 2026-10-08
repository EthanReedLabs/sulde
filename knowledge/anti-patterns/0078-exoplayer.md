---
doc_id: "ap-0078"
container: anti-patterns
platform: none
summary: "0078 视频区每次切换都创建新播放器"
---

# 0078 视频区每次切换都创建新播放器

- **平台**:双端
- **复发次数**:0

## ❌ 错误

每条视频都新建一个播放器实例,导致内存暴涨 + GC 频繁。

## ✅ 正确

播放器池策略(current + prev + next 共 3 个),最远的回收复用。
