---
doc_id: "ap-0076"
container: anti-patterns
platform: none
summary: "0076 提交后不删除已合并分支"
---

# 0076 提交后不删除已合并分支

- **平台**:双端
- **复发次数**:0

## ❌ 错误

合并到 develop 后保留分支 → 几十个分支堆积 → 找不到当前活跃的。

## ✅ 正确

合并验证无问题后立即删除:

```bash
git branch -d dev/xxx            # 本地（-d 安全删除）
git push origin --delete dev/xxx # 远程
```
