---
name: assign
description: Dev 单任务指派 / 派给某个人 / 让 A 做 / 切到分支干活 / 执行 task md。指派一个具体任务给指定 Dev,自动切换到对应分支和 git 身份执行。当用户说"让 A 做 X""派给 Dev A""切到 dev/xxx 改 Y""/assign <path>"时自动触发。多任务由协调端拆成独立 task-md 后分别执行。stack 中性 — 团队 / 模块 / build 命令全部从 `.sulde-config.yaml` 读。
user-invocable: true
---

# /assign — Dev 端任务执行入口

接 `/assign` 后,按本 skill 流程跑:**§0 baseline 验证 → §1 启动 → §2 思考模式 → §3 执行 → §4 完工 → §5 verify strict → §6 handoff**。

## §0 baseline 验证(强制 — 跑任务前 30 秒自检)

接到 task md 后,**先 verify 协调端起草 baseline 没失效**,再开干:

| Step | 必做 | 失败动作 |
|:-:|---|---|
| 1 | Read task md `§起草前 baseline 实证` 段 — 必存在(协调端被 hook 强制) | 缺段 → 拒执行,handoff 反弹"协调端 baseline 缺,请走 writing-task-md skill 补" |
| 2 | 抽 1-2 个 task md 引用的 symbol → `grep -rn` 当前 frontend 源码 verify 字面真名仍存在 | grep 0 命中 → drift,handoff 反弹"task md 引用 X 已 rename / 删除,需 re-baseline" |
| 3 | 抽 1 个 task md 引用的 design-truth 文件(`<docs-hub>/design-truth/{pageId}.md`)→ Read 一遍,verify 段号 / 真值仍存在 | drift → handoff 反弹 |
| 4 | `git log --since=14d --oneline` 当前 frontend → 对照 task md baseline `Step 1` commit 列表 → 是否有未涵盖的新 commit 改了相关代码 | 有 → handoff 反弹"task md baseline stale,X commit 未纳入" |

**判定线**:任一 step fail → **拒执行 task md**(不动代码),立刻 handoff 反弹给协调端 re-baseline。不要"自行修复"baseline drift。

---

## §1 启动方式

### Inline 路径模式(推荐 — 无需交互问 3 问)

触发条件:`/assign` 参数含 `.ai-workspace/tasks/` 路径或 `.md` 后缀。

```
/assign 任务文件:.ai-workspace/tasks/{date}-{slug}.md
/assign 执行 .ai-workspace/tasks/{date}-{slug}.md
/assign .ai-workspace/tasks/{date}-{slug}.md
```

自动流程:

1. **Read 任务文件** → 拿到 frontmatter
2. **从 frontmatter 提取**:
   - `assignee` → 切对应 `git as-<alias>` 身份(从 `.sulde-config.yaml: team[]` 读 alias)
   - `branch` → 切到该分支(不存在则从 default branch 创建)
   - `model` → 验证模型与当前一致(已切则跳过;未切则提示用户切)
   - `思考模式 / thinking` → 设置思考模式(`think` / `think hard` / `ultrathink`)
3. 跑 §0 baseline 验证(上节 4 step)
4. 按 task md 内容执行
5. 完工按 §5 verify strict + §6 handoff

### 传统交互式(无 inline args 时回退)

依次问:

1. 指派给谁?(代号 / 姓名)— 从 `.sulde-config.yaml: team[]` 列出可选项
2. 在哪个分支上?(新建 `dev/<alias>/<slug>` / 已有分支)
3. 任务描述?

## §2 思考模式(按任务复杂度自评)

| 任务类型 | 思考模式 | 关键词 |
|---|---|---|
| 架构搭建 / 跨模块重构 | ultrathink | "ultrathink。" |
| Bug 修复 / 新 Feature 开发 | think hard | "think hard。" |
| UI 还原 / 列表页 / API 接入 | think hard | "think hard。" |
| 字段增删 / 配置修改 | think | "think。" |
| 翻译补全 / 资源添加 / 编译错误修复 | 默认 | 不加 |

执行前在内部判断 "这个任务属于哪一档",启用对应模式。

## §3 执行

1. 根据 assignee 确定 git alias 与用户名(`.sulde-config.yaml: team[]`)
2. 切换或创建对应分支
3. Read 当前 frontend `CLAUDE.md` 确认 stack-specific 规则
4. 执行任务(按 task md 步骤)
5. 改完代码 **不要自动 commit** — 等 §5 verify strict 通过再 commit

## §4 项目源码 / 模块布局

不要在本 skill 里 hardcode 模块路径 — 不同项目 / 不同 stack 不同。**两个数据源**:

| 源 | 用途 |
|---|---|
| `.sulde-config.yaml: frontends[].path` | 当前 frontend 根目录 |
| `<docs-hub>/scaffold-map.yaml` | 各 scaffold 模块 + feature 模块 + 必读规范 |

跑 `bash <docs-hub>/design/query-scaffold.sh --list`(若项目脚本存在)或 `Read <docs-hub>/scaffold-map.yaml` 查清单。

## §5 verify strict(完工前强制 — 防"代码看着对但跑不起来" 反模式)

代码改完后**不直接 commit**,先跑 build / install / log / screenshot 4 步实证:

| Step | 命令(从 `.sulde-config.yaml: build_verify[<stack>]` 读模板) | 验收 |
|:-:|---|---|
| 1 | `build_cmd` | exit 0;无 error / warning escalation |
| 2 | `install_cmd`(真机 / 模拟器,优先真机)| exit 0;app 起来 |
| 3 | `launch_cmd` + `log_cmd`(跑 10-30s 触达本 task 改动路径) | log 无 crash / fatal / 新增 error |
| 4 | 截图(`screenshots` 配置)+ Read .png — 视觉对照 task md `.ai-workspace/diag/<task>-before.png` 或 design-truth `.png` | 视觉相符;明显差异 escalate |

**判定线**:4 步任一 fail → **不 commit**,handoff 反弹"verify fail at step N,日志 / 截图见 .ai-workspace/diag/<task>-{log,screenshot}.{txt,png}"。

> **特例**:纯 doc 改动 / .ai-workspace/ 改动 / 配置改动 → §5 跳过(在 handoff 里说明跳过理由)。

## §6 handoff

完工 → 跑 `/handoff` skill(详 `dev/handoff` SKILL)。**禁止**直接对协调端说 "跑完了 / 改完了 / done" — 必走 handoff doc 留 5 段实证。

## §7 commit 规则

verify 通过 + handoff 写完后:

1. 用 task md `assignee` 字段对应的 `git as-<alias>` commit(`.sulde-config.yaml: team[].alias`)
2. commit message 中文(若项目用中文)/ 英文(若项目用英文)
3. **禁止** 在代码 / commit message / handoff 内出现 `AI / Claude / GPT / LLM / generated / auto-generated` 字样(pre-commit hook `check_ai_traces.sh` 会拦)
4. **不要自动 push** — 等用户确认

## §8 git 身份切换示例

```bash
# .sulde-config.yaml 若有:
#   team:
#     - alias: as-a
#       name: Alice
#       email: alice@team.com
#       frontend: android

# 切身份:
git config user.name "Alice" && git config user.email "alice@team.com"
# 或用 alias(项目跑过 /sulde-add-team-member 后 alias 已注入):
git as-a commit -m "feat: ..."
```

`git as-<alias>` alias 由 `/sulde-add-team-member` 创建(参 `configure-sulde` skill 的 add-team-member mode);也会设置 `SULDE_COMMIT_ALIAS` 环境变量,被 `check_commit_alias.sh` pre-commit hook 检测。

---

## 反例(常见错误,不要做)

- ❌ 拿到 task md 不跑 §0 baseline 验证就开干
- ❌ §5 verify 跳过 build / install,只 grep 代码就说"done"
- ❌ 直接 `git commit`(不走 `git as-<alias>`)→ pre-commit hook 会拦
- ❌ 改代码同时改 task md(协调端真值,Dev 不动)
- ❌ task md 引用的 symbol 已 rename → 不反弹,而是"自行猜测新名"实施

## 反模式 ADR

- `docs-hub/ADR/0001-coordinator-impression-based-dispatch.md`(Dev 端的镜像责任:接 task md 不 verify baseline 等于纵容协调端凭印象起草)
