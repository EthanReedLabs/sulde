# sulde-cc Roadmap v2

> 跨 session 分阶段实施 spec。v2 同步 `V0.2.0-DESIGN-v2.md` 修订。
> v1 ROADMAP 已废弃(保留 `ROADMAP.md` 作历史),实施按本 doc。
>
> **v2 主要变化**:
> - P2/P3 边界重画(`_project/` 全归 P2,docs-hub 内容填充归 P3)
> - 4 stack(android / ios / flutter / harmony — RN 移 v0.2.1,2026-05-25 revised)
> - Hook bash → Python(工时持平)
> - P4 加 LICENSE 切 BSL v1.1 + migration 段
> - 加 4 命令(migrate / add-frontend / add-team-member / end-grace)

---

## v0.2.0 mobile-first(当前)

详细设计 → `V0.2.0-DESIGN-v2.md`

### Phase 1 — Hooks(Python)+ Skills 核心(~10-12h)

**Goal**:declarative → enforcing 转换;协调端 + Dev + git path 11 hook 全套落地;Python 化跨 OS。

#### Tasks

| # | Task | Files | Time |
|:-:|---|---|:-:|
| P1.1 | 3 Python entrypoint scripts(顶部含 #22 优雅降级:try import yaml + ImportError fallback)| `hooks/pre_tool_use.py` + `hooks/user_prompt_submit.py` + `hooks/session_start.py` | 1.5h |
| P1.2 | `lib/sulde_common.py`(walk-up + role detect + frontend path + worktree/submodule/monorepo)| `hooks/lib/sulde_common.py` | 2h(v2 加 multi-root 略加)|
| P1.3 | `lib/enforcement.py`(`sulde_exit_or_warn()` + grace_period + i18n stderr)| `hooks/lib/enforcement.py` | 1h(v2 加 i18n 略加) |
| P1.4 | 7 check_*.py(Python 实现 11 子 logic 中 7 个 Claude Code 类)| `hooks/lib/check_{task_md_baseline,handoff_verify,subdir_cd,git_commit_alias}.py` + `hooks/lib/{skill_trigger,perf_gate,claude_md_inject}.py` | 4h |
| P1.5 | `hooks/git-precommit/*.sh`(4 个 git pre-commit bash hook)| `hooks/git-precommit/check_{branch_protect,branch_format,commit_alias,ai_traces}.sh` | 1h |
| P1.6 | `hooks/hooks.json` v0.2.0 注册(matcher 显式 Bash/Write)| `hooks/hooks.json` | 0.2h |
| P1.7 | `hooks/requirements.txt`(pyyaml>=6.0)| 同 | 0.1h |
| P1.8 | `skills/coordinator/writing-task-md/SKILL.md` 加 §0.5 generic 移动端版 | 同 | 1.5h |
| P1.9 | `skills/dev/assign/SKILL.md` 加 §0 baseline verify + §5 verify strict | 同 | 1h |
| P1.10 | 新建 `skills/dev/handoff/SKILL.md`(5 段强制)| 同 | 1h |
| P1.11 | 新建 `skills/coordinator/configure-sulde/SKILL.md`(8 mode)| 同 | 2.5h(v2 扩 4 → 8 mode 略加)|
| P1.12 | 新建 8 commands | `commands/sulde-init.md` + `commands/sulde-migrate-from-v0.1.0.md` + `commands/sulde-add-{sensitive-file,scaffold,skill-trigger,frontend,team-member}.md` + `commands/sulde-end-grace.md` | 1h(v2 扩自 4 commands)|
| P1.13 | `.claude-plugin/plugin.json` 加 `hooks` + skills 字段更新 | 同 | 0.1h |
| P1.14 | P1 unit test(dry-run 3 entrypoint + 7 check + 8 commands skill mode) | `tests/p1_hook_dryrun.py` | 1.5h |

**总计**:~17h(v2 略增,因 Python 化 multi-root + i18n + grace + migrate mode + 8 commands)

> 备注:v2 工时 ~17h 比 v1 的 10-12h 多 ~5h,反映 multi-root / i18n / grace / migrate mode / 多 3 commands 的复杂度。实施仍建议 1 个 session(同 dev 跨 day)。

#### Verify checklist

- [ ] `python3 hooks/pre_tool_use.py < test-input.json` 各 case 通过(coordinator Write task md / Dev Write handoff / Bash cd subdir / Bash git commit)
- [ ] `python3 hooks/user_prompt_submit.py` skill-trigger + perf-gate 命中
- [ ] `python3 hooks/session_start.py` 输出 `hookSpecificOutput.additionalContext` 含 CLAUDE.md head -60
- [ ] `lib/sulde_common.py` walk-up 在 worktree / submodule / monorepo 各 work + 非 sulde 项目 silent exit
- [ ] `lib/enforcement.py` strict/balanced/lenient 三档 + grace period forced lenient + i18n 切换 zh/en 工作
- [ ] `hooks/git-precommit/*.sh` 4 个独立 dry-run pass
- [ ] `skills/coordinator/writing-task-md/SKILL.md` §0.5 完整
- [ ] `skills/dev/{assign,handoff}/SKILL.md` spec 完整
- [ ] `skills/coordinator/configure-sulde/SKILL.md` 8 mode 完整(init / migrate / 5 add-* / end-grace)
- [ ] `plugin.json` `hooks` 字段声明 + 5 个 skill 路径
- [ ] dry-run tests 全过
- [ ] Windows Git Bash 跑通(若手边有 Windows 环境;否则 P4 release 前补)

---

### Phase 2 — Template `_project/` + 4 stack 骨架(~6-7h)

**Goal**:`template/_project/`(根级 + scripts + .sulde-config + docs-hub 骨架)+ `template/{android,ios,flutter,harmony}/` 各完整骨架,sulde-init cp 即用。

> **v2 修订(S3 fix)**:`_project/` 全部归 P2(不与 P3 并行)。

#### Tasks

| # | Task | Files | Time |
|:-:|---|---|:-:|
| P2.1 | `template/_project/` 根级 + scripts | `README.md` + `.gitignore.template`(含 `.sulde-grace-*` marker #23 + `.claude/` + `CLAUDE.md` + `.ai-workspace/`)+ `.sulde-config.yaml.example`(含 v2 新字段)+ `scripts/coordinator-baseline.sh.template` + `scripts/health-check.sh.template` + `scripts/README.md` | 1h |
| P2.2 | `template/_project/docs-hub/` 骨架(空目录 + README,内容 P3 填)| `docs-hub/README.md` + `docs-hub/coordinator-todos.md.template` + `docs-hub/{00_shared-rules,design-truth,ADR}/README.md` | 0.5h |
| P2.3 | `template/android/` 完整骨架 | ~12 files(CLAUDE.md.template + .ai-workspace/{7}/README.md + scripts/pre-commit-installer.sh + .gitignore + README cross-OS 段)| 1h |
| P2.4 | `template/ios/` 完整骨架(同 P2.3 结构)| ~12 files | 1h |
| P2.5 | `template/flutter/` 完整骨架 | ~12 files | 1h |
| P2.6 | `template/harmony/` 完整骨架(ArkTS + hvigorw + DevEco;CLAUDE.md.template 引 §7.2 命令)| ~12 files | 1.5h |
| P2.7 | sulde-init skill 复制 logic 实测(每 stack dry-run + copy_template helper 跨 OS)| — | 1.5h(v2 加跨 OS 略加)|

**总计**:~7h

#### Verify checklist

- [ ] `template/_project/` 完整(根级 + scripts + docs-hub 骨架,~10 file)
- [ ] 4 stack template 总 ~50 文件全部到位
- [ ] 每 stack CLAUDE.md.template stack-specific 段填全(build_cmd / install_cmd / log_cmd / lint_cmd,含 verify 注释 URL)
- [ ] 每 stack .gitignore.template 含 stack 特定 ignore
- [ ] 每 stack README cross-OS 段含 Windows / WSL2 / Git Bash 提示
- [ ] 每 stack scripts/pre-commit-installer.sh 可执行 + OS detect 段
- [ ] sulde-init dry-run android → user_project/android/ 完整复制
- [ ] sulde-init dry-run 4 stack 全选 → 4 frontend 全 copy
- [ ] copy_template 在 macOS + Linux 跑过(Windows 留 P4 release 前)

---

### Phase 3 — docs-hub 内容填充 + ADR 示例(~4h)

**Goal**:`template/_project/docs-hub/` 内 mobile generic 内容填充。

> **v2 修订(S3 fix)**:P3 只动 `template/_project/docs-hub/` 内容(P2 已建好骨架)。P2 / P3 不并行(共享目录)。

#### Tasks

| # | Task | Files | Time |
|:-:|---|---|:-:|
| P3.1 | `docs-hub/00_shared-rules/data-sources.md.template`(mobile:design-truth > PRD > scaffold > 业务层)| 1 | 0.5h |
| P3.2 | `docs-hub/00_shared-rules/verify-build.md.template`(4 stack build/install/真机 verify + 跨 OS)| 1 | 1h |
| P3.3 | `docs-hub/00_shared-rules/self-fix-boundary.md.template`(Dev 自发修复 5 类敏感清单)| 1 | 0.5h |
| P3.4 | `docs-hub/00_shared-rules/perf-diagnosis.md.template`(性能诊断门控 + 4 stack 工具)| 1 | 0.5h |
| P3.5 | `docs-hub/00_shared-rules/model-strategy.md.template`(Dev 端 sonnet / opus / haiku 选择)| 1 | 0.3h |
| P3.6 | `docs-hub/ADR/0001-coordinator-impression-based-dispatch.md.template`(generic 0100 mobile 版)| 1 | 0.5h |
| P3.7 | `docs-hub/ADR/0002-scaffold-bypass.md.template`(generic 0097 mobile 版)| 1 | 0.5h |
| P3.8 | `docs-hub/ADR/0003-mobile-cold-flow-stateflow.md.template`(generic 0098,Android Kotlin Flow 通用)| 1 | 0.3h |
| P3.9 | `docs-hub/ADR/_frontmatter.schema.yaml`(v0.2.0 加 platforms enum:[android, ios, flutter, harmony, coordinator]) | 1 | 0.2h |
| P3.10 | `docs-hub/ADR/INDEX.md` 加 0001-0003 行 + 移动端 ADR 累计 | 1 | 0.2h |

**总计**:~4h

#### Verify checklist

- [ ] 5 个 00_shared-rules 文件 generic mobile(无 Freebeat 痕迹)
- [ ] 3 个 ADR 示例 generic mobile(无 Freebeat 痕迹,可 placeholder 引导用户加项目特定 case)
- [ ] _frontmatter.schema.yaml 加 mobile-family platforms enum(含 harmony,去 rn)
- [ ] INDEX 含 3 ADR 示例 + 1 example(0000)
- [ ] 每文件含 "How to use this template" 段(用户改完后该删 / 该改的标记)

---

### Phase 4 — Release(~2.5h)

**Goal**:对外发布 v0.2.0 mobile-first + 切 BSL v1.1。

> **v2 修订**:
> - 加 LICENSE 切 BSL v1.1 步骤(M1 fix)
> - CHANGELOG 加 migration from v0.1.0 段(S4 fix)
> - bump version 0.1.0 → 0.2.0

#### Tasks

| # | Task | Files | Time |
|:-:|---|---|:-:|
| P4.1 | `docs/METHODOLOGY.md` mobile-first 重写(保留 7 层金字塔 generic + 加 "Why mobile-first" 段 + 4 stack 应用示例 + 跨 OS 段)| 1 | 0.5h |
| P4.2 | `README.md` 改 mobile-only banner(v2 撤"Beyond mobile" 子段 — S1 诚实化)+ Quick start with sulde-init + **Prerequisites 段含 Python 3.6+ + pyyaml + v0.1.0 退路 link(#22)** + cross-OS 段 | 1 | 0.5h |
| P4.3 | `LICENSE` 替换 MIT → BSL v1.1(M1 fix) + `LICENSE-v0.1.0-MIT-archive`(保留 v0.1.0 MIT 历史 grant)| 2 | 0.3h |
| P4.4 | `CONTRIBUTING.md` 加 CLA(BSL 商业条款保护) | 1 | 0.3h |
| P4.5 | `.claude-plugin/plugin.json` bump version 0.1.0 → 0.2.0 + license `BUSL-1.1` + keywords 加 `mobile-android / mobile-ios / flutter / harmony`(去 react-native)+ `hooks` 字段 | 1 | 0.1h |
| P4.6 | `docs/GETTING_STARTED.md` 改 sulde-init 流程(含 7 day grace + 跨 OS 提示) | 1 | 0.3h |
| P4.7 | `CHANGELOG.md` 新建 v0.2.0 段(11 hook Python / 4 stack / 8 commands / configure-sulde 8 mode / migration v0.1.0 → v0.2.0 段 / breaking change 段) | 1 | 0.3h |
| P4.8 | git commit + push GitHub | — | 0.1h |
| P4.9 | GitHub release tag v0.2.0 + release notes(链 migration guide) | — | 0.1h |

**总计**:~2.5h

#### Verify checklist

- [ ] METHODOLOGY mobile-first 段 + 7 层金字塔 generic 保留 + 跨 OS 段
- [ ] README banner mobile-only(S1 诚实化:撤 "Beyond mobile"; v0.3+ 待 N-end)+ Quick start sulde-init + Python 依赖 + cross-OS
- [ ] LICENSE = BSL v1.1 + LICENSE-v0.1.0-MIT-archive 留作历史 grant
- [ ] CONTRIBUTING CLA 段
- [ ] plugin.json version 0.2.0 + license BUSL-1.1 + keywords 4 stack + hooks 字段
- [ ] CHANGELOG 含 11 hook Python + 4 stack + 8 commands + configure-sulde 8 mode + migration 段 + breaking change(Python 依赖)
- [ ] git tag v0.2.0 + release notes 含 migration from v0.1.0 + Python 依赖说明
- [ ] GitHub Discussions / Issues template 起一条 "v0.2.0 questions" pinned post

---

## v0.2.1+(open questions)

### v0.2.1(~6-8h)

| # | Item |
|:-:|---|
| 0 | **dev skill refactor**(2026-05-25 实施完成):7 dev skill(ui-impl / crash-fix / perf-diagnose / bug-hunt / code-review / parallel-dev / postmortem)从 `dev-android/` + `dev-ios/` 双份 → 单 `dev/<skill>/SKILL.md + references/{android,ios,flutter,harmony}.md`。**理由**:v0.2.0 留下的 14 个 duplicate dev-android + dev-ios SKILL.md 阻碍 Flutter / Harmony 使用 `/ui-impl` / `/crash-fix` 等 skill 时获得 stack-specific guidance。Refactor 后单 skill 自动按 frontend stack route 到对应 references。**非 ROADMAP 原计划项,2026-05-25 用户提出后即时实施 + retroactive 登记** |
| 1 | 协调端 PreToolUse(Write pen-truth supplement)hook 拦缺三方判定 |
| 2 | 协调端 PreToolUse(Write ADR)hook 拦缺 frontmatter / baseline |
| 3 | 加 stack:**React Native**(2026-05-25 revised — RN demoted from v0.2.0 in favour of Harmony)|
| 4 | 加 stack:KMP / Capacitor Mobile / Tauri Mobile(每加 1 stack ~1.5h Python)|
| 5 | i18n 加 ja / es / pt-BR(community contrib)|

### v0.3(~15-25h)

| # | Item |
|:-:|---|
| 6 | template/_generic/_backend/_web/ N-end 兜底(若用户 demand)|
| 7 | Inter-project common antipattern pool(跨项目 ADR 共享 + opt-in 继承)|
| 8 | `sulde audit` CLI(扫项目 ADR 覆盖率 / handoff 积压 / scaffold-bypass)|
| 9 | `sulde lint --pending` CLI(列待 lint 化 ADR)|
| 10 | `sulde common-antipatterns add <id>` CLI(项目 opt-in pool ADR)|

---

## 完工后 sulde-cc 形态(v0.2.0)

```
sulde-cc/  (v0.2.0)
├── .claude-plugin/
│   └── plugin.json                          # 0.2.0 + license BUSL-1.1 + hooks + keywords mobile-first
├── README.md                                # mobile-only banner + sulde-init quick start + Python deps + cross-OS
├── CHANGELOG.md                             # v0.2.0 完整变更 + migration from v0.1.0
├── LICENSE                                  # BSL v1.1
├── LICENSE-v0.1.0-MIT-archive               # 留存 v0.1.0 MIT 永久 grant
├── CONTRIBUTING.md                          # 加 CLA
├── commands/                                # v2 扩 4 → 8 commands
│   ├── sulde-init.md
│   ├── sulde-migrate-from-v0.1.0.md
│   ├── sulde-add-sensitive-file.md
│   ├── sulde-add-scaffold.md
│   ├── sulde-add-skill-trigger.md
│   ├── sulde-add-frontend.md
│   ├── sulde-add-team-member.md
│   └── sulde-end-grace.md
├── docs/
│   ├── METHODOLOGY.md                       # mobile-first 重写 + 跨 OS 段
│   ├── GETTING_STARTED.md                   # sulde-init 流程 + grace period
│   ├── V0.2.0-DESIGN.md                     # v1(留作历史)
│   ├── V0.2.0-DESIGN-REVIEW.md              # v1 review(留作历史 + 含 §9 v2 实证 addendum)
│   ├── V0.2.0-DESIGN-v2.md                  # 当前 spec(本 doc 配套)
│   ├── ROADMAP.md                           # v1(留作历史)
│   ├── ROADMAP-v2.md                        # 当前 roadmap
│   └── i18n/                                # 多语言 docs(zh / en)
├── hooks/                                   # v2 全 Python
│   ├── hooks.json                           # 3 entrypoint Python 注册 + matcher Bash/Write
│   ├── pre_tool_use.py
│   ├── user_prompt_submit.py
│   ├── session_start.py
│   ├── requirements.txt                     # pyyaml>=6.0
│   ├── lib/
│   │   ├── sulde_common.py                  # + worktree/submodule/monorepo
│   │   ├── enforcement.py                   # + grace_period + i18n
│   │   ├── check_task_md_baseline.py
│   │   ├── check_handoff_verify.py
│   │   ├── check_subdir_cd.py
│   │   ├── check_git_commit_alias.py
│   │   ├── skill_trigger.py
│   │   ├── perf_gate.py
│   │   └── claude_md_inject.py
│   └── git-precommit/                       # git side bash(仍 .sh)
│       ├── check_branch_protect.sh
│       ├── check_branch_format.sh
│       ├── check_commit_alias.sh
│       └── check_ai_traces.sh
├── skills/
│   ├── coordinator/
│   │   ├── writing-task-md/SKILL.md         # 加 §0.5
│   │   └── configure-sulde/SKILL.md         # 8 mode
│   ├── dev/
│   │   ├── assign/SKILL.md                  # 加 §0 + §5 verify
│   │   └── handoff/SKILL.md                 # 新建
│   └── shared/
│       └── update-design/SKILL.md           # 增强 Pencil MCP
├── template/                                # v2 4 stack(android / ios / flutter / harmony — RN 移 v0.2.1)
│   ├── _project/                            # 项目根模板(全归 P2)
│   │   ├── README.md
│   │   ├── .gitignore.template
│   │   ├── .sulde-config.yaml.example       # mobile default schema + v2 新字段
│   │   ├── scripts/
│   │   │   ├── coordinator-baseline.sh.template
│   │   │   └── health-check.sh.template
│   │   └── docs-hub/                        # 骨架 P2,内容填 P3
│   │       ├── 00_shared-rules/             # 5 文件 mobile generic(P3 填)
│   │       ├── design-truth/
│   │       └── ADR/                         # 3 mobile 示例(P3 填)
│   ├── android/                             # 4 stack 完整骨架
│   ├── ios/
│   ├── flutter/
│   └── harmony/
└── tests/
    └── p1_hook_dryrun.py                    # Phase 1 hook dry-run 测试(Python)
```

---

## Phase 间依赖(v2 重画)

```
P1 (hooks Python + skills + commands) ─→ P2 (template _project/ + 4 stack骨架)
                                          │
                                          ↓
                                         P3 (docs-hub 内容填充,共享 _project/ 目录)
                                          │
                                          ↓
                                         P4 (release + BSL 切 + tag)
```

→ **P1 必先**(blocker)
→ **P2 / P3 不并行**(共享 `_project/docs-hub/` 目录,S3 fix)
→ P4 最后

> 注:P2 内部 4 stack 可并行(每 stack 1 worktree,互不重叠)— 1 个 session 多 worktree 派给 dev 跑也 OK。

---

## 跨 session 实施纪律(防 §0100 复发)

每次 session 开始 P1 / P2 / P3 / P4 前:

1. Read 本 ROADMAP-v2 找当前 phase
2. Read `V0.2.0-DESIGN-v2.md` 找对应 §(spec 不偏离)
3. 跑 Phase verify checklist 全过才标 done
4. 每 phase 1 commit(不 squash)+ branch `dev/v0.2.0-p<N>-<slug>`
5. P1-P4 全过 → merge `dev/v0.2.0` → main → tag v0.2.0

### 关键提醒(v2 强调)

- **Python 化别回退 bash**:跨 OS 关键,任何"改回 bash 更快"的想法 → 撤,凭印象偏离 v2 spec
- **`_project/` 全归 P2 别启 P3 早**:S3 fix 的原因
- **migration mode 必含**(`/sulde-migrate-from-v0.1.0`):S4 fix,v0.1.0 用户公开 GitHub `EthanReedLabs/sulde-cc`,已有 MIT grant,必要兼容
- **grace period 必含**(default 7d):S2 fix,首装体验保护
- **LICENSE 切 BSL 前 v0.1.0 MIT archive 必留**:M1 + 法律 commit 历史

---

## v2 vs v1 工时变化

| Phase | v1 工时 | v2 工时 | 增减 | 原因 |
|:-:|:-:|:-:|:-:|---|
| P1 | 10-12h | ~17h | +5-7h | 8 commands(+ 4)/ 配 multi-root / i18n / grace / migrate mode / Python rewrite(略复杂)|
| P2 | 5-7h | ~7.5h | +0.5-2.5h | 4 stack(swap rn↔harmony,harmony +0.5h)+ _project/ 全归 P2(+) + 跨 OS README(+)|
| P3 | 3-4h | ~4h | 0 | 同 |
| P4 | 1.5-2h | ~2.5h | +0.5-1h | + LICENSE BSL 切 + CHANGELOG migration 段 + CONTRIBUTING CLA |
| **总** | **~19-25h** | **~30h** | **+5-11h** | v2 修订增添的 multi-root / cross-OS / migration / 4 mode 命令 / BSL 切的合理成本 |

> 总 ~30h(集中 3-4 session)— 比 v1 估算多 ~5-10h,但反映 v2 修订的真实复杂度。建议每 phase 1 个 session,合计 4 session 完成 v0.2.0 release。

---

**ROADMAP-v2 起草人**:协调端 Claude Opus 4.7。
**起草日期**:2026-05-25。
**入口**:实施任一 phase 前 Read 本 doc + V0.2.0-DESIGN-v2.md 锚定 spec。
