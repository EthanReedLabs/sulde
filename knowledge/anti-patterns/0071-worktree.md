---
doc_id: "ap-0071"
container: anti-patterns
platform: none
summary: "0071 worktree 创建在项目目录之外"
---

# 0071 worktree 创建在项目目录之外

- **平台**:双端
- **复发次数**:0

## ❌ 错误

```bash
git worktree add /tmp/some-name -b dev/xxx develop
```

## 为什么错

worktree 散落各处难管理 / 项目级配置不生效 / 容易被误删。

## ✅ 正确

```bash
git worktree add .worktrees/xxx -b dev/xxx develop
```
