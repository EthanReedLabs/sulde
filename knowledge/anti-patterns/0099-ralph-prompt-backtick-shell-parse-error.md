---
doc_id: "ap-0099"
container: anti-patterns
platform: none
summary: "Ralph PROMPT 内含反引号 / markdown fence → shell parse error 或用户…"
---

# 0099 — Ralph PROMPT 内含反引号 / markdown fence → shell parse error 或用户复制污染

- **平台**:协调端（给 Dev 派 ralph-loop 短指令时）
- **复发次数**:1
- **lint 状态**:⏳ pending（可加协调端 PROMPT 预检脚本）

## 现象

协调端写 ralph-loop 派单短指令（Dev 复制三行粘贴执行）时:

### 反例 1:PROMPT 内含反引号
```
/ralph-loop Read /path/to/task.md 严格按 `ralph 执行协议` section 执行
```

Dev 终端 shell 解析:`` `ralph 执行协议` `` 被当作 command substitution → 触发 shell parse error 或意外执行子命令。即使没报错，反引号内的中文也可能被 shell 截断/转义。

### 反例 2:协调端用 markdown code fence 包裹派单短指令
````
```
/clear
/model sonnet
/ralph-loop Read .../task.md
```
````

用户复制时连 ``` 一起带进 shell → 前 3 个反引号在 REPL 内被识别为多行 string 起始，后续指令变成 string 内容，**不触发 slash command**。

### 反例 3:PROMPT 内含多行 markdown 列表 / 表格
```
/ralph-loop Read foo.md 执行步骤:
- 步骤 1
- 步骤 2
```

`/ralph-loop` slash command 默认按单行解析，多行 markdown 内容被截断或导致命令解析失败。

## 根因

| 原因 | 说明 |
|---|---|
| 1. shell metacharacter | 反引号 `` ` `` 是 POSIX shell 的 command substitution 触发符，**任何**在 shell context 下被求值的字符串都不能含反引号（除非转义） |
| 2. REPL multi-line 解析 | 三反引号在 REPL 内识别为多行 string 起始，导致后续 `/clear` `/model` 都被吃进 string |
| 3. slash command 单行假设 | `/ralph-loop` 等 slash command 默认单行 args，多行内容被截断 |
| 4. 协调端 markdown 习惯惯性 | 协调端默认用 markdown 写文档，派单短指令也容易带 markdown 格式 |

## 修法

### 规则 1:PROMPT 内禁反引号

**所有**派给 Dev 的 ralph PROMPT 内不能含 `` ` ``。引用代码 / 协议名 / 文件名时用以下替代:

| 想说 | 别写 | 改写 |
|---|---|---|
| ralph 执行协议 section | 严格按 \`ralph 执行协议\` section | 严格按内部 ralph 执行协议 section |
| 调 grep 命令验进度 | 跑 \`grep -c xxx\` 验 | 每轮 grep 验进度（具体 grep 命令搬进 task md 内） |
| 完工 git commit | 跑 \`git commit -m "xxx"\` | 完工自动 commit merge 删分支 |

**模式**:具体命令 / 反引号包裹内容 → 全部搬进 **task md 内的 ralph 执行协议段**，PROMPT 只引用"按 task md 内 section 执行"的元指令。

### 规则 2:派单短指令输出禁 markdown fence

协调端在主对话给用户输出派单指令时，**不要用** code fence 包裹，直接平铺三行，前后加空行隔开:

> Dev 终端粘贴（三行）:
>
> /clear
> /model sonnet
> /ralph-loop Read /path/to/task.md 严格按内部 ralph 执行协议 section 执行

### 规则 3:PROMPT 保持单行短句

`/ralph-loop` 后只跟单行短句（分号 `;` 分隔多个 clause 可接受），不含换行 / 列表 / 表格。详细执行步骤搬 task md。

## 反例 vs 正例

❌ 错误:
```
/ralph-loop 跑 task md `.../foo.md`，按 `ralph 执行协议` 段执行:
- 切分支 `dev/xxx`
- 跑 `build` 验
- 完工 `git commit`
```
→ 反引号 + 多行，Dev shell parse error / REPL 截断。

✅ 正确:
```
/ralph-loop Read /path/to/task.md 严格按内部 ralph 执行协议 section 执行;不偏离 contract;每轮 grep 验进度;完工自动 commit merge 删分支 + 写 handoff 到 .ai-workspace/handoff/
```
→ 0 反引号，单行，分号分隔 4 个 clause，具体 grep / commit 命令在 task md 内。

## Lint 规则草稿

```bash
# rules/010-coordinator-prompt-shell-safe.sh
# 触发条件:协调端 session 输出含 "/ralph-loop" 或 "/assign"
# 检查:
#   1. 同一行不含 ` (反引号)
#   2. 前后 3 行不含 ``` (markdown fence)
#   3. /ralph-loop 后的 PROMPT 体不跨行（单行 < 500 字符）
# 实施位置:协调端 PostToolUse hook（Output 类型），正则扫描 assistant message
```

## 检测路径（协调端自审）

写 ralph 派单短指令前，**先在 PROMPT 内扫**:
1. 含 `` ` `` 字符?→ 移除，引用对象搬 task md
2. 含 ``` ``` ```?→ 移除 fence，改平铺
3. 跨行?→ 改单行 + 分号分隔
4. 含 `grep -c xxx` / `git commit -m "xxx"` 类具体命令?→ 搬 task md，PROMPT 只说"按 task md 内 grep / commit 协议执行"

## 关联

- 协调端凭 stale Read / 凭印象 类问题（本反模式属同源:协调端输出格式凭习惯不验）
