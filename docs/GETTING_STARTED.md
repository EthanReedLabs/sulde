# Getting Started (v0.2.0)

This is a historical v0.2.0 walkthrough. For the current source and MIT license,
start with the [README](../README.md), [host setup](DEVELOPMENT.md), and
[licensing guide](LICENSING.md).

> Go from "I cloned sulde-cc" to "my first Dev session is running a task-md" in about 10 minutes.

This walkthrough assumes you have Claude Code installed, Python 3.6+ available, and a mobile project (or empty directory) where you want to adopt the methodology.

---

## 1. Install the plugin (~ 2 min)

```sh
# Historical v0.2.0 (mobile-first, BSL 1.1, Python hooks)
/plugin marketplace add EthanReedLabs/sulde-cc
/plugin install sulde-cc@sulde-cc

# Python dependency (one time per machine)
pip install pyyaml>=6.0
```

Codex 独立安装或升级使用一体化安装器：

```sh
python3 /path/to/sulde-cc-pro/scripts/release/install_codex_plugin.py --dry-run
python3 /path/to/sulde-cc-pro/scripts/release/install_codex_plugin.py --json
```

它只有在自包含 artifact、插件注册、缓存摘要、稳定 launcher、scheduler generation 和 Intent
Guardian 合成 Hook smoke 全部通过后才成功；失败会恢复旧注册、launcher、owner/runner、actor
文件及加载状态。成功结果固定为 `status=generation_verified`，表示 source、artifact、runtime、
launcher、owner 与 actor 同代；整体 `operational_ready=false` 只保留到真实宿主 Hook 验证完成。
若 `kb_initialization_command` 非空先执行它；`scheduler_reconciliation_command` 应为空。随后在
当前或新 Codex 会话产生真实 Hook 证据并通过 doctor，才算整体 operational ready。staged
generation descriptor、installed deployment、stable launcher 和 scheduler owner 必须是同一
runtime 全树摘要；未知 `com.sulde.*` actor、`.git`、
`__pycache__/*.pyc`、symlink、稳定 runner 摘要或 runtime 摘要漂移都会失败闭锁。退役
cache-repair actor 只归档并留下幂等 tombstone，旧 repair 脚本和
rollback 都不会重新创建整树链接。安装器会保留旧缓存
整树快照；若 Codex 在注册切换时清理旧目录，会先恢复静态树，再把所有可识别旧缓存中的
Hook 启动入口换成摘要绑定的当前运行时桥。失败回滚同样恢复安装前整树，而不是只恢复两个
入口文件。稳定桥能让仍被宿主调用的 Hook 入口使用新代码，但不能恢复已经丢失的
PreToolUse 订阅。安装 JSON 因此默认报告 `hook_restart_required=true`，并另报
`hook_hot_rebind_available`；只有真实负向 canary 证明执行前拒绝且 marker 不存在，才能判定
当前会话无需重启。Post-only 的物化拒绝会锁存为监督缺口，doctor 在下一次匹配的
可信负向 canary proof 前保持 degraded；SessionStart 不构成执行前证明，也不会清除该缺口。
静态 Skill 清单仍由 Codex 在会话开始时快照。

安装 smoke 是 `synthetic_smoke`，不冒充真实会话覆盖。新会话里运行：

```sh
intent-guardian doctor --workspace /path/to/project --provider codex
```

`approval_capture.status=live_verified` 才表示聊天批准能可靠落账；`synthetic_only` 或
`unobserved` 时批准通道不可用。旧会话桥接成功时，当前 thread 的下一条提示即可产生新
运行时的真实证据，无需为了 Hook 策略丢弃上下文。Agent 会为当前人工提案准备不含授权的结构化续接包；
重启恢复原 thread，或在同一工作区新开已加载 hook 的会话后，`SessionStart` 自动恢复
任务边界，再由新会话独立记录人的选择。不要在旧会话反复发送批准，也不要使用复制的
`approve-proposal` 命令代替审阅；`approve-event` 已退役，事件摘要永远不产生权限。
人工审阅时系统展示自然语言决策卡。Codex 由 Agent 在当前对话发起一次原生
`PermissionRequest`，人只按 Allow/Deny；不回复固定短语、不复制 digest/命令，也不另开终端。
没有该原生边界的宿主才使用可读文字选择。满足门禁的确定性任务可由 `agent-policy` 独立决断；可读任务范围内的
可逆外部效果由 Agent 执行并独立验真。主观、公开/新受众、破坏性、有费用、密钥外发、
范围扩大或有未知事实的任务不能走该通道。
若项目曾从临时 worktree 移走，Agent 先运行 `intent-guardian doctor --scan --provider codex`；
不要复制活动 JSON。Agent 展示迁移或归档的原生 Allow/Deny，Allow 后执行
`rebind-workspace` 并在新目录重新审阅当前方案；若任务已放弃，则由 Agent 执行
`retire-workspace` 归档关闭。

Without `pyyaml` the enforcement hooks degrade gracefully to no-op + a stderr warning. Your workflow does not break, but you lose the gating value. Install it.

After install you should see 5 skills and 8 commands available:

```
/sulde-init                       /sulde-add-frontend       /sulde-add-team-member
/sulde-migrate-from-v0.1.0        /sulde-add-sensitive-file  /sulde-add-scaffold
/sulde-end-grace                  /sulde-add-skill-trigger
```

The local intent guardian starts in workspace-scoped `shadow` mode through prompt, tool-lifecycle and `Stop` hooks—even in a résumé or writing folder without `.sulde-config.yaml`. It writes only local contract/audit state and makes no extra model call unless semantic critic is explicitly enabled. Mobile engineering gates, KB auto-recall and project skill triggers remain opt-in until `.sulde-config.yaml` exists.

## 2. Initialize your project (~ 3 min)

In your project root, run:

```sh
cd ~/path/to/your-mobile-project
```

In a Claude Code session there, run:

```
/sulde-init
```

The wizard asks ~8 questions:

1. project name (default = dir basename)
2. role (`coordinator` / `dev` / `both`; default `coordinator`)
3. stacks (multi-select: `android`, `ios`, `flutter`, `harmony`; default `[android, ios]`)
4. design source MCP (`pencil` / `figma` / `sketch` / custom; default `pencil`)
5. team (one alias per frontend at minimum; can defer with `/sulde-add-team-member` later)
6. enforcement level (`strict` / `balanced` / `lenient`; default `balanced`)
7. grace period days (default `7`)
8. language (`auto` / `en` / `zh` / `ja`; default `auto`)

It then:
- writes `.sulde-config.yaml`
- copies `template/_project/*` to your project root (README, .gitignore.template, scripts/, docs-hub/ skeleton)
- copies `template/<stack>/*` to each `frontends[].path`
- installs git pre-commit hooks via each frontend's `scripts/pre-commit-installer.sh`
- drops a `.sulde-grace-started` marker — for 7 days, enforcement runs at `lenient` regardless of your config so first-week mistakes don't block you

## 3. Add team members (~ 2 min)

For each developer in your project, run:

```
/sulde-add-team-member <alias> <name> <email> <frontend>
```

Example:

```
/sulde-add-team-member as-a Alice alice@example.com android
/sulde-add-team-member as-b Bob   bob@example.com   ios
```

This appends to `.sulde-config.yaml: team[]` and creates a per-repo `git as-<alias>` shell alias that sets `SULDE_COMMIT_ALIAS=<alias>` so the `check_commit_alias.sh` pre-commit hook lets the commit through. Plain `git commit` without `git as-<alias>` is now blocked.

## 4. Bootstrap design-truth (~ 5-15 min depending on design size)

If your project has a design tool with MCP support (Pencil / Figma):

```
/update-design                                                  # not yet bundled — see skills/coordinator/
```

For now, manually create `<docs-hub>/design-truth/<page-id>.md` per page using `<docs-hub>/design-truth/_example.md.template` as the skeleton. Each page truth doc should include:

- Node tree (component nesting + style props)
- Visual key attributes (font, color, corner radius)
- Asset reference list (per-stack paths for `cp`)
- Implementation hard constraints (which scaffolds to use)

## 5. Dispatch your first task-md (~ 3 min)

In your coordinator session at project root:

> "Dispatch a task to the android frontend: change the home tab count from 3 to 2."

The `UserPromptSubmit` hook surfaces a `[sulde:writing-task-md]` reminder. Invoke the skill, follow its §0 6-step audit + §0.5 5-step baseline. The skill's enforcement gate (the `check_task_md_baseline.py` PreToolUse hook) blocks Write of any task-md missing the `§起草前 baseline 实证` section.

Write the task-md to `./android/.ai-workspace/tasks/<YYYY-MM-DD>-home-tabs-reduction.md`.

## 6. Execute the task (~ depends on task)

In a **separate** Claude Code session running inside `./android/`:

```
/clear
/model sonnet
/assign .ai-workspace/tasks/<YYYY-MM-DD>-home-tabs-reduction.md
```

The `dev/assign` skill:

1. Reads the task-md frontmatter (assignee, branch, model)
2. Verifies §0 baseline (4-step gate: task md has baseline section, cited symbols still grep, cited design-truth still exists, recent commits don't invalidate)
3. Switches branch + `git as-<alias>` identity
4. Executes the contract
5. Runs §5 verify-strict (build / install / launch+log / screenshot)
6. Writes a handoff at `.ai-workspace/handoff/<YYYY-MM-DD>-home-tabs-reduction-result.md` per the `dev/handoff` skill's 5-section format
7. Stages the diff; **does not auto-commit or auto-push** — waits for your confirmation

## 7. Coordinator reviews + dispatches follow-ups

Back in your coordinator session, the next `/clear` will SessionStart-inject the head of `CLAUDE.md` + optionally the output of `scripts/coordinator-baseline.sh` so you see what the dev produced.

Read the handoff's `§ verify` (build evidence) + `§ escalation 候选` (out-of-scope problems the dev noticed). Decide:
- merge the dev's branch into integration
- or dispatch a follow-up task-md for escalation items

## 8. End the grace period

After ~1 week, you'll have a feel for the hooks. Switch to your real enforcement level:

```
/sulde-end-grace
```

This drops a `.sulde-grace-ended` marker. From here on, hooks enforce at the level configured in `.sulde-config.yaml: enforcement_level` (default `balanced`):

| Level | PreToolUse(Write) | PreToolUse(Bash) | UserPromptSubmit |
|---|---|---|---|
| `strict` | block (JSON deny) | block (exit 2) | reminder |
| `balanced` (default) | block | block | reminder |
| `lenient` | warn (allow) | warn (allow) | reminder |

## 9. Author your first real ADR (when you hit a recurring pattern)

sulde-cc ships three example ADRs (`0001`-`0003`) for mobile-generic anti-patterns + `0000-example.md` for format reference. Once your project hits a recurring incident specific to it, author `<docs-hub>/ADR/{NNNN}-{slug}.md` following `_frontmatter.schema.yaml`. Add a row to `INDEX.md`. Track recurrence over time — the ADR registry is the single most valuable artifact a long project accumulates.

---

## What to read next

- [`docs/METHODOLOGY.md`](METHODOLOGY.md) — the 7-layer pyramid + reasoning
- [`docs/V0.2.0-DESIGN-v2.md`](V0.2.0-DESIGN-v2.md) — hook protocol, schema details, grace mechanics
- `<docs-hub>/00_shared-rules/*` (after `/sulde-init`) — data-sources / verify-build / self-fix-boundary / perf-diagnosis / model-strategy
- `${CLAUDE_PLUGIN_ROOT}/skills/dev/assign/SKILL.md` + `dev/handoff/SKILL.md` — day-to-day Dev workflow

## Migrating from v0.1.x

```
/sulde-migrate-from-v0.1.0
```

Reads existing `.sulde-config.yaml`, dry-runs upgrade to `.sulde-config.yaml.v2-preview`, asks for confirmation, backs up the original as `.sulde-config.yaml.v0.1.0-backup`, and drops a 7-day grace marker. The CHANGELOG has the breaking-change list (Python dependency is the main one).

If you cannot install Python 3.6+ in your environment, stay on v0.1.x:

```
/plugin install skills@sulde-cc@0.1.0
```

The v0.1.0 tag remains MIT-licensed and Python-free in perpetuity.

## Troubleshooting

**The hooks are not running**

```sh
/plugin list                    # verify sulde-cc shows
python3 -c "import yaml"        # verify pyyaml installed (silent = ok; error = pip install pyyaml)
```

If project enforcement, KB recall or skill triggers still don't fire, check that `.sulde-config.yaml` exists in your project root or an ancestor. The intent guardian does not require that file; inspect it with `intent-guardian report --workspace /path/to/project`.

如果状态显示 `🔴 接线未同步`，说明插件源码/缓存与共享 KB home 的派生 launcher 不一致：

```sh
bash /path/to/current/runtime/scripts/kb/bootstrap.sh --launchers-only --host codex
```

该模式只刷新并验证六个 launcher，不创建 venv、不下载模型、不重建索引。
若摘要错误由 `__pycache__/*.pyc` 引起，附加
`--repair-generated-bytecode`；它仅在剩余树与 sealed generation 精确一致时清理字节码，
其他漂移仍保持 fail-closed。

**Pre-commit hook blocks `git commit`**

Use `git as-<alias> commit ...` (configured by `/sulde-add-team-member`). To disable: set `enforcement.branch.commit_alias_required: false` in `.sulde-config.yaml`.

**Want to disable enforcement temporarily**

Set `enabled: false` in `.sulde-config.yaml` (kill switch). Or drop to `lenient` for warnings without blocking. Re-enable when ready.

**Trigger keywords don't match my project's vocabulary**

Add custom triggers via `/sulde-add-skill-trigger <regex> <skill> [role]`. The `skill_trigger.py` hook merges your additions with the built-in defaults on every prompt.

**A Dev session is touching files outside its frontend**

Check the Dev's `CLAUDE.md` has the "do not edit files outside this frontend" rule (the v0.2.0 templates include it). If yes, the Dev is ignoring it — file an ADR.
