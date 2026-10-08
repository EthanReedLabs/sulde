---
doc_id: "ap-0192"
container: anti-patterns
platform: none
summary: "并行执行多个 git 写命令(如 submodule add)时报 \"Unable to create '.git/index.lock': File exists\",部分操作随机失败留下不一致状态"
related: [ap-0074]
sedimented_by: auto
---

# NNNN — 并行 git 写操作竞争 index.lock

- **平台**:通用

## ❌ 错误

```bash
# 后台并行 / 多 agent 同时对同一仓库执行 git 写操作
git submodule add <url-a> libs/a &
git submodule add <url-b> libs/b &
wait
```

## 为什么

1. 所有写 index 的 git 命令(add / commit / checkout / merge / submodule add 等)共享同一把 `.git/index.lock` 文件锁;
2. git 拿不到锁**不排队等待,直接 fatal 退出**:先到者持锁,后到者报 `fatal: Unable to create '.git/index.lock': File exists`;
3. 并行度越高失败越随机,且"部分成功部分失败"会留下不一致中间态(如 `.gitmodules` 已写入但 index 未暂存),清理成本高于串行省下的时间。

## ✅ 正确

对同一仓库的 git 写操作**必须串行**:

```bash
for entry in "a <url-a>" "b <url-b>"; do
  set -- $entry
  git submodule add "$2" "libs/$1"   # 逐条执行,看结果再走下一条
done
```

- 多 agent / 多任务并行开发时,用 git worktree 隔离(各 worktree 有独立 index,互不竞争);
- 但**针对共享主仓 `.git` 的操作**(submodule add、主仓 merge、主仓 checkout)不受 worktree 隔离保护,仍须串行执行。

### 验收基线也必须隔离

即使没有触发 `index.lock`，人和自动执行体在同一 working tree 并行修改也会污染
`git diff`：验收器会把人的改动算进 agent 产出，或因 stash/临时清理改变基线。凡执行结果
按 diff、changed files 或 worktree 测试验收的自动任务，都应在创建时固定 base commit，
在独立 worktree 中修改和验证，并只对 `base..task HEAD` 与该 worktree 的未提交差异负责。

主目录可以继续由人工作，但不得作为自动任务的验收目录；最终 merge/主仓 git 写仍按上
述规则串行。独立 worktree 不只是并行提速工具，也是证据归属边界。
