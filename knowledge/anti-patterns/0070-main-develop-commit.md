---
doc_id: "ap-0070"
container: anti-patterns
platform: none
summary: "0070 在 main / develop 上直接 commit"
---

# 0070 在 main / develop 上直接 commit

- **平台**:双端
- **复发次数**:0

## ❌ 错误

```bash
git checkout develop
# 直接修代码
git add . && git commit -m "fix: ..."
```

## 为什么错

违反分支策略,破坏分支管理结构。

## ✅ 正确

- main / develop 禁止直接 commit;
- 所有开发在 `dev/{用户名}/{模块}` 分支;
- 完成后通过 `--no-ff` merge 进入 develop。
