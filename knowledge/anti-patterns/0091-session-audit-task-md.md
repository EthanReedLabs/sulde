---
doc_id: "ap-0091"
container: anti-patterns
platform: none
summary: "协调端 session 切换后忘记派发过的任务，重新 audit 重写已完工 task md"
---

# 0091 — 协调端 session 切换后忘记派发过的任务，重新 audit 重写已完工 task md

- **平台**:协调端
- **复发次数**:2
- **lint 状态**:✅ 已接（`coordinator-baseline.sh` + SessionStart hook + 协调端审单 Step 0）

> 📍 本反模式已并入"协调端凭印象 / stale Read / 缺 baseline 同源根因" master；保留作历史档案 + 旧编号引用。

## 现象

协调端在 `/clear` / 新窗口 / 上下文超限触发新 session 后:
- task 状态不跨 session 持久化（协调端工具设计如此）
- 协调端新 session 启动时无任何"前 session 派过什么 task"的认知
- 用户提新问题 → 协调端 audit 当前代码 / 接口 → 起草 task md → 但**事实上前 session 已派 + Dev 已完工 + commit 已合主干**
- 协调端凭"看代码" 误判:看到某适配器 wired → 以为"已 wire = 重复"，实际那是 Dev 跑前 session task md 后的 commit 留下的
- 用户实测发现 → 报告协调端"重复派活"

**复发 2 的新根因**:audit 前未 `git log -S "symbol"` 反向搜索目标 token;`grep find -name X` 仅在 task md 目录命中，**未进实际源码目录**双重 verify。机制虽已建（baseline + Step 0）但未覆盖"基于 stale 文件内容审视当前状态"这条新分支。

## 根因

1. 协调端 handoff 处理规则只要求"触发性扫描"（每次被告知 / 周期审计），**没有"启动 session 必扫"硬约束**
2. 协调端 task md 审单全是"看代码 + 看文档"，**没有"看历史 task md / handoff archive / git log"的 Step 0**
3. 协调端派 audit subagent 时 prompt 不要求查历史，subagent 看 mockFallback 就判"未 wire"
4. 协调端凭"看代码下结论"前**没 git log 验证当前 commit 是不是协调端自己 task md 跑出来的产物**

## 修法

**机制 — 已接**:

1. `coordinator-baseline.sh` — 自动汇总双端 active handoff + archive 近 14 天 + 主干近 14 天 commit + active task md + 待派清单
2. SessionStart hook — 自动跑 baseline 注入 session
3. 协调端审单加 Step 0:派 task md / audit subagent / 给 Dev 派单前必看 baseline + git log + handoff archive 真值，**不凭"看代码"下结论**

**审 audit subagent prompt 必含 Step 0**:
```
Step 0（强制）:Read 协调端 baseline
  + ls 双端 handoff/archive/ 近 14 天
  + git log --oneline --since=14d
回报"这个领域近 14 天已做了什么"摘要，再做 audit。
```

## 反例 vs 正例

❌ 错误:
```
1. 用户问"未实现接口"
2. 协调端 audit 当前代码 + 查文档
3. 看到 mockFallback / 推测"未 wire"
4. 写 task md
→ 派 Dev = 重复执行已完成工作
```

✅ 正确:
```
1. 用户问"未实现接口"
2. 协调端先看 SessionStart 注入 baseline（已自动注入）
3. baseline 显示双端近 14 天已 commit 哪些 + 已派哪些 task md
4. 派 audit subagent 前 prompt 加 Step 0 "先看历史"
5. audit 报告后协调端再 git log 验证当前 commit 是否 Dev 刚跑出来的产物
6. 再决定写 task md / 撤回
```

## 修法补充（复发 2 起强化）

复发 2 暴露:原修法覆盖"启动 session 必扫 baseline"，但未覆盖"基于 stale 文件内容审 audit 当前状态"。新增 3 步:

1. **stale Read 自审**:协调端读完任一源码 / 文档文件后，**若该文件 mtime > 1 小时前**，做 audit 结论前必 git log -S 反向搜索目标 token
   ```bash
   git -C <仓库> log -S "<symbol>" --since=30d --oneline
   # 若有 commit 命中 → 已实现，本次 audit 结论"缺失"为错
   ```
2. **grep 必落源码目录，不只 task md 目录**:
   ```bash
   # ❌ 错:grep -rn <symbol> <仓库>/.ai-workspace/tasks/ — 0 命中误判为"未实现"
   # ✅ 正:grep -rn <symbol> <仓库>/<core 模块>/ <仓库>/feature-*/src/
   ```
3. **协调端写"双端 audit"类 task md 前 4 步硬约束**:
   - SessionStart baseline scan（已自动注入，Step 0）
   - `git log --oneline --since=14d` 双端
   - `grep -rn` 关键 symbol 在源码目录（不仅 task md 目录）
   - `git log -S "symbol"` 反向搜索 commit 历史

任一步缺 → 双端 audit task md 不可派，先补完 4 步再写。

## 关联

- 协调端文档凭印象 / 凭印象不查技术真值 — 同类问题不同场景
- 协调端 audit 跳步类反模式 — 同源
- `coordinator-baseline.sh` + SessionStart hook
