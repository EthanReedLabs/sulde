---
doc_id: "ap-0056"
container: anti-patterns
platform: none
summary: "0056 CLAUDE.md / shared-rules 改动后,Dev session 旧 system-remi…"
---

# 0056 CLAUDE.md / shared-rules 改动后,Dev session 旧 system-reminder 注入快照不更新 → 新规则不生效

- **平台**:协调端 + Dev(session 机制类)
- **复发次数**:1

## ❌ 错误 — 症状

协调端落地双端 CLAUDE.md 新提交规则例外(`/assign` 接 task md 含完工三步 = 预授权,Dev 自动 commit + merge):
- 协调端修 CLAUDE.md ✅
- 双端 task md 派出(含完工三步 git 命令)
- iOS Dev 自动跑完工三步 ✅
- **Android Dev 仍等用户口头授权**(新规则没生效)→ 连续第 3 次 dirty 等授权

## 为什么错(根因)

CLAUDE.md / 项目规则文档通过 **session 启动时**的 `<system-reminder>` 注入 — Dev session 内的 system-reminder 是启动时快照,**后续 CLAUDE.md 改动对该 session 无效**。

差异表现:
- 一端 session 行为本就不依赖该规则(本就预授权)→ 改规则前后行为一致
- 另一端 session 严格按旧 CLAUDE.md 等授权 → 改规则后 session 仍是旧规则

## ✅ 正确 — 修法

协调端**派 task md 前**(若 Dev session 已运行)**必让 Dev 跑 `/clear` 重启 session**,新 session 启动时 CLAUDE.md 注入是最新版。

新派单格式(协调端派单短指令段强制):

```
# {端} 终端(session 已运行时必加 /clear)
/clear
/model {opus|sonnet|haiku}
/assign 任务文件:.ai-workspace/tasks/{date}-{slug}.md
```

**例外**:Dev session 是新启动(第一次派 task)→ 不需 /clear。

## 判定线

- 协调端 CLAUDE.md / shared-rules / 反模式集合改动后,**必显式提示**所有运行中的 Dev session 跑 /clear 才生效
- 默认派单短指令带 `/clear` 前缀(用户能判断 session 状态时可省;协调端不假设状态,默认带前缀)

## lint 状态

- 协调端:CLAUDE.md 派单短指令段 `/clear` 前缀已加
- Dev:N/A(被动接受 system-reminder 注入,无法自检)
- 用户:派单前看到 `/clear` 提示就跑(无成本)

## 关联

- 协调端登记反模式后忘记应用 — 规则落地不通知 Dev /clear = 双重违规
- 协调端 CLAUDE.md 派单短指令段(`/clear` 前缀)
