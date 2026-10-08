---
doc_id: "ap-0075"
container: anti-patterns
platform: none
summary: "0075 主目录污染"
---

# 0075 主目录污染

- **平台**:双端
- **复发次数**:0

## ❌ 错误

```bash
# 在主目录 develop 分支上：
git add -A
git add .
git add somefile.kt   # 即使加单个文件也是错的
```

## 为什么错

- main / develop 是只能通过 merge 进入的分支;
- 主目录保持干净,所有改动应该在 dev 分支(worktree 内)做;
- 主目录有未提交改动会阻塞后续 merge / checkout / worktree remove。

## ✅ 正确

- 改动只在 `.worktrees/{user}-{module}/` 内做;
- 主目录始终 `git status` 显示 "nothing to commit";
- 如果不小心在主目录改了:`git stash` → 切到对应 worktree → `git stash pop` → 在 worktree 内提交。
