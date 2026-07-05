---
name: configure-sulde
description: sulde-cc 项目配置 / 接入 / 升级 / 团队管理 / 加 frontend / 加 scaffold / 加 skill trigger / 结束 grace period。8 mode 统一入口:init(新项目接入)/ migrate-from-v0.1.0(老版本升级)/ add-frontend / add-team-member / add-sensitive-file / add-scaffold / add-skill-trigger / end-grace。当用户跑 `/sulde-init` / `/sulde-migrate-from-v0.1.0` / `/sulde-add-*` / `/sulde-end-grace` 任一命令时触发。**单 SKILL 多 mode**,根据入口 command name 选 mode dispatch。
user-invocable: true
---

# /configure-sulde — 项目配置 / 升级 / 维护 8 mode

入口 command(在 `commands/sulde-*.md` 定义),都走本 skill。**根据用户 invoke 的 command 选 mode**。

## §0 Mode dispatch

| Command | Mode | 备注 |
|---|---|---|
| `/sulde-init [project-dir]` | **init** | 新项目从零接入 sulde-cc |
| `/sulde-migrate-from-v0.1.0` | **migrate** | v0.1.0 → v0.2.0 升级 |
| `/sulde-add-frontend <name> <path> <stack>` | **add-frontend** | 增加一个 frontend(已有项目)|
| `/sulde-add-team-member <alias> <name> <email> <frontend>` | **add-team-member** | 加团队成员 + 创建 `git as-<alias>` |
| `/sulde-add-sensitive-file <path>` | **add-sensitive-file** | 标记敏感文件(Dev 不得自发改)|
| `/sulde-add-scaffold <name> [trigger]` | **add-scaffold** | 加 scaffold 条目到 `<docs-hub>/scaffold-map.yaml` |
| `/sulde-add-skill-trigger <regex> <skill>` | **add-skill-trigger** | 加 UserPromptSubmit 触发词 → `.sulde-config.yaml: skill_triggers` |
| `/sulde-end-grace` | **end-grace** | 主动结束 7d grace period,切真 `enforcement_level` |

任一 mode 跑完输出 "next steps" 段(用户下一步操作)。

---

## §1 Mode: init(对话式 8 步)

新项目接入 sulde-cc。步骤:

1. **Detect existing** `.sulde-config.yaml`(若有,refuse + 提示 `/sulde-migrate-from-v0.1.0`)
2. **Q1**:project name(default = dir basename)
3. **Q2**:role(coordinator / dev / both,default coordinator)
4. **Q3**:stack 多选(default `[android, ios]`,可加 `flutter` / `harmony`)
5. **Q4**:design source MCP(default `pencil`)+ file 路径(`./design/app.pen` 等)
6. **Q5**:team(每个 frontend 至少 1 个 alias;先收集 N,后跑 add-team-member mode 加 alias)
7. **Q6**:enforcement_level(default `balanced`)+ grace_period_days(default `7`)
8. **Q7**:lang(default `auto`)+ os_primary_target(default `unix`)
9. **生成 `.sulde-config.yaml`** 写入 project root
10. **复制 `${CLAUDE_PLUGIN_ROOT}/template/_project/*`** 到 project root(根级 + scripts/ + docs-hub/ 骨架)
11. **复制 `${CLAUDE_PLUGIN_ROOT}/template/<stack>/*`** 到 `<frontend>/` 每个 frontend(对应 stack 骨架)
12. **写 grace marker**:`echo '{"started_at":"<ISO>","grace_period_days":7}' > .sulde-grace-started`
13. **跑各 frontend 的 `scripts/pre-commit-installer.sh`** 装 git hook
14. **cp `template/_project/docs-hub/design/page-relation.yaml.example` → `<docs-hub>/design/page-relation.yaml`**(空骨架,首次跑 `/ui-impl` 阶段 0 强制读取本图谱,缺则报错)
15. **输出 next steps**:
    - 7 day grace period 已起,hook 强制 lenient mode 直到 `.sulde-grace-ended` marker
    - 跑 `pip install -r ${CLAUDE_PLUGIN_ROOT}/hooks/requirements.txt` 装 pyyaml
    - **若多人协作**:跑 `/sulde-add-team-member` 加每个团队成员
    - **若独立开发者**:`team: []` 留空即可(`check_commit_alias.sh` hook 自动 skip alias 强制,plain `git commit` 工作)
    - **若有设计工具**(Pencil / Figma MCP):跑 `/update-design` 起初版 design-truth
    - **若无设计工具**:`.sulde-config.yaml: design_source.mcp` 设为 `none`,走手动 design-truth 流程
    - 首次跑 `/ui-impl` 前协调端**手动填一遍 `<docs-hub>/design/page-relation.yaml`**(参 yaml.example 内 schema 示例)
    - `/sulde-end-grace` 提前结束 grace

**复制实现** 见 §9 跨目录 cp 权限段。

---

## §2 Mode: migrate(v0.1.0 → v0.2.0)

老版本(`v0.1.0`)用户升级。步骤:

1. **Read existing** `.sulde-config.yaml`(v0.1.0 schema)
2. **显示 diff**:
   - `frontend-a` placeholder → 提示 rename(用户选 `android` / `ios` / `flutter` / `harmony`)
   - 新增字段填 default(`enforcement_level: balanced` / `lang: auto` / `enforcement_grace_period_days: 7` / `scope_inheritance: parent` / `os_compatibility: {primary_target: unix, windows_shell_hint: git-bash}` / `build_verify: {...}` / `enforcement: {...}`)
   - skill paths 从 v0.1.0 的 user-private bundle → v0.2.0 generic(假定用户没改 plugin 源)
3. **Dry-run write** to `.sulde-config.yaml.v2-preview`
4. **用户 confirm** → 备份原 file 为 `.sulde-config.yaml.v0.1.0-backup` → 写新 file
5. **写 grace marker** `.sulde-grace-started`(7d grace 让用户适应新 enforcement)
6. **输出 migration report + next steps**:
   - `pip install -r ${CLAUDE_PLUGIN_ROOT}/hooks/requirements.txt`(Python 依赖,breaking change)
   - 跑各 frontend 的 `scripts/pre-commit-installer.sh` 装 v0.2.0 git hook
   - **v0.1.0 退路**:若有问题 `/plugin install skills@sulde-cc@0.1.0`(MIT,无 Python 依赖)

---

## §3 Mode: add-frontend

Args: `<name> <path> <stack>`(例:`/sulde-add-frontend harmony ./harmony mobile-harmony`)

1. Read existing config → 检查 name 不重复
2. Append to `frontends:` 数组
3. 复制 `${CLAUDE_PLUGIN_ROOT}/template/<stack>/*` 到 `<path>/`(用户可未存在该目录,创建)
4. 跑 `<path>/scripts/pre-commit-installer.sh` 装 git hook
5. 输出 next steps:`/sulde-add-team-member <alias> <name> <email> <frontend-name>` 给新 frontend 配人

可用 stack(v0.2.0):`mobile-android` / `mobile-ios` / `mobile-flutter` / `mobile-harmony`。

---

## §4 Mode: add-team-member

Args: `<alias> <name> <email> <frontend>`(例:`/sulde-add-team-member as-c Carol carol@team.com flutter`)

1. Read existing config → 检查 alias 不重复
2. Append to `team:` 数组:
   ```yaml
   - alias: as-c
     name: Carol
     email: carol@team.com
     frontend: flutter
   ```
3. **创建 git alias** `as-<alias>`:
   - 写入项目 `.git/config` 的 `[alias]` section:
     ```
     [alias]
       as-c = "!SULDE_COMMIT_ALIAS=as-c git -c user.name='Carol' -c user.email='carol@team.com' commit"
     ```
   - 注:`SULDE_COMMIT_ALIAS` 是 sentinel,`check_commit_alias.sh` pre-commit hook 据此放行
4. 输出 next steps:
   - 用 `git as-c commit ...` 提交
   - alias 是 per-repo,新 clone 需重跑本 mode 或手动加 alias

---

## §5 Mode: add-sensitive-file

Args: `<path>`(例:`/sulde-add-sensitive-file core-ui/AppRouter.kt`)

1. Read existing config → append to `scope_sensitivity.sensitive_files:` 数组(去重)
2. 输出 reminder:Dev 端 self-fix-boundary 会 block 自发改这些文件;改动必经 task md

---

## §6 Mode: add-scaffold

Args: `<name> [trigger-regex]`(例:`/sulde-add-scaffold AppTopBar "TopBar|TitleBar"`)

1. Read `<docs-hub>/scaffold-map.yaml` → append:
   ```yaml
   - name: AppTopBar
     triggers: ["TopBar", "TitleBar"]
     contract: <docs-hub>/scaffolds/AppTopBar.md  # 需协调端补
     owner: coordinator
   ```
2. 提示协调端补 `<docs-hub>/scaffolds/<name>.md` 契约文档

---

## §7 Mode: add-skill-trigger

Args: `<regex> <skill> [role]`(例:`/sulde-add-skill-trigger "pen-truth.*更新" update-design coordinator`)

1. Append to `.sulde-config.yaml: skill_triggers:`(已是 v0.2.0 字段)
   ```yaml
   skill_triggers:
     - regex: "pen-truth.*更新"
       skill: update-design
       role: coordinator
       reminder: "Invoke the update-design skill..."
   ```
2. 输出 reminder:hook `skill_trigger.py` 会在 UserPromptSubmit 时合并 default + user triggers

---

## §8 Mode: end-grace

无 args。

1. 检查 `.sulde-grace-started` 存在(若不存在 → "no grace period active")
2. 写 `.sulde-grace-ended`(空 file 即可,或 `{"ended_at": "<ISO>"}` 内容)
3. 输出:enforcement 立刻切回 config `enforcement_level`(strict / balanced / lenient)
4. 提示:`.sulde-grace-*` marker 已加 `.gitignore`(不进 git,per-machine state)

---

## §9 跨目录 cp 权限 / 实现细节(B4 fix)

复制 template 时:

```python
import shutil
from pathlib import Path

PLUGIN_ROOT = Path(os.environ["CLAUDE_PLUGIN_ROOT"])  # set by Claude Code
src = PLUGIN_ROOT / "template" / "_project"
dst = Path(project_root)
shutil.copytree(src, dst, dirs_exist_ok=True)
# Re-apply executable bit on scripts (Python copytree preserves mode on Unix
# but Windows file modes are limited)
for sh in dst.glob("**/*.sh"):
    sh.chmod(sh.stat().st_mode | 0o755)
```

**权限失败**:用户 home / project 权限不够 → skill 输出"无权限写 X,手动 cp 命令:..."降级。

**跨 OS** windows:
- `shutil.copytree` works
- `.sh` 在 Windows 没 executable bit,git pre-commit 会以 bash 解释器跑(via Git for Windows / WSL2)— `pre-commit-installer.sh` 内含 OS detect 提示

---

## §10 default 字段写入(各 mode 共用)

写 `.sulde-config.yaml` 时,**默认字段** + **必填字段** 区分:

| 字段 | 默认 | 必填? |
|---|---|:-:|
| `enabled` | `true` | ❌ |
| `role` | `coordinator` | ✅ |
| `frontends[]` | — | ✅(至少 1)|
| `docs_hub` | `./docs-hub` | ❌ |
| `enforcement_level` | `balanced` | ❌ |
| `enforcement_grace_period_days` | `7` | ❌ |
| `lang` | `auto` | ❌ |
| `design_source` | `pencil` + `./design/app.pen` | ❌ |
| `team[]` | — | ❌(可后补)|
| `build_verify` | per-stack 默认(android / ios / flutter / harmony) | ❌ |
| `enforcement` | 各子项默认 | ❌ |
| `session_baseline` | `{claude_md_inject_lines: 60}` | ❌ |
| `scope_sensitivity` | `{sensitive_files: [], sensitive_scaffolds: []}` | ❌ |
| `os_compatibility` | `{primary_target: unix, windows_shell_hint: git-bash}` | ❌ |
| `scope_inheritance` | `parent` | ❌ |
| `antipattern.index_path` | `./docs-hub/ADR/INDEX.md` | ❌ |
| `skill_triggers[]` | `[]` | ❌ |

---

## §11 mode 错误处理

| Error | 处理 |
|---|---|
| `.sulde-config.yaml` 不存在 但 mode != `init` | 提示 "run `/sulde-init` first" |
| `.sulde-config.yaml` 存在 但 mode == `init` | 提示 "use `/sulde-migrate-from-v0.1.0` to upgrade or delete `.sulde-config.yaml` to re-init" |
| add-* 重名 | 提示 + abort(不覆盖) |
| copytree 权限失败 | 输出降级手动 cp 命令 |
| 用户 Ctrl-C 中途退出 | `.sulde-config.yaml.v2-preview` 保留,提示"恢复"路径 |
