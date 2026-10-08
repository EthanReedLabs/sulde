---
doc_id: "ap-0069"
container: anti-patterns
platform: none
summary: "0069 协调端 Bash 里 `cd` 到子端目录导致 CLAUDE.md 反复注入"
---

# 0069 协调端 Bash 里 `cd` 到子端目录导致 CLAUDE.md 反复注入

- **平台**:协调端
- **复发次数**:1

## ❌ 错误

协调端 session 内 Bash 用 `cd {子端目录}/ && ...` 跑命令(如 `cd android-project/ && ./gradlew ...` 或 `cd ios-project/ && xcodebuild ...`)。

## 为什么错

- 工作目录触及子端时,子端的 `CLAUDE.md`(数百行 / ~17 KB)会被 system-reminder 整份注入当前 context;
- 实测:子端 CLAUDE.md 被注入数十次,累计上 MB 纯重复文本;
- 这些重复进入每轮 prompt input_tokens,直接把 session 推向 token 天花板;
- session jsonl 体积里,这类重复浪费占比显著。

## ✅ 正确

协调端 Bash 始终用**绝对路径**,不 `cd` 到子端:

```bash
# ❌ 错误
cd android-project/ && ls .ai-workspace/handoff/

# ✅ 正确
ls /abs/path/android-project/.ai-workspace/handoff/
```

- Read / Grep / Edit 本就支持绝对路径,不受影响;
- 协调端工作目录**始终保持在项目 root**;
- 例外:只有用户明确要求"在某子端跑命令"(极少)才切目录,且做完立刻切回。

## lint 状态

- ⏳ TODO — 可考虑在协调端 Bash hook 里扫 `cd {子端}` 模式软警告。人工审计暂行。
- 配套:已写进协调端 CLAUDE.md「不要做的事」;memory 有个人偏好条目。
