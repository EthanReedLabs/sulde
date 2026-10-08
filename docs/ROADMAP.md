# sulde-cc Roadmap

> ⚠️ **DEPRECATED**(2026-05-25):本 roadmap(v1)已被 [`ROADMAP-v2.md`](./ROADMAP-v2.md) 取代。
> **不要**作为实施依据 — v2 重画了 P2/P3 边界(`_project/` 全归 P2)、加了 LICENSE 切 BSL v1.1 + migration 段、缩到 4 stack(harmony 移 v0.2.1)。
> 本 doc 保留作历史档案。

---

> 跨 session 分阶段实施 spec。每 phase 入口 file 清单 + 完工 verify checklist。

---

## v0.2.0 mobile-first(当前)

详细设计 → `V0.2.0-DESIGN.md`

### Phase 1 — Hooks + Skills 核心(~10-12h)

**Goal**:declarative → enforcing 转换;协调端 + Dev + git path 11 hook 全套落地。

#### Tasks

| # | Task | Files | Time |
|:-:|---|---|:-:|
| P1.1 | 3 entrypoint scripts | `hooks/pre-tool-use.sh` + `hooks/user-prompt-submit.sh` + `hooks/session-start.sh` | 1.5h |
| P1.2 | `lib/sulde-common.sh`(walk-up config + role detect + frontend path 解析)| `hooks/lib/sulde-common.sh` | 1.5h |
| P1.3 | `lib/enforcement.sh`(`sulde_exit_or_warn()` helper)| `hooks/lib/enforcement.sh` | 0.5h |
| P1.4 | 11 子 logic 各 ~50 行 bash | `hooks/lib/check-{task-md-baseline,handoff-verify,subdir-cd,git-commit-alias,branch-protect,branch-format,commit-alias,ai-traces}.sh` + `hooks/lib/{skill-trigger,perf-gate,claude-md-inject}.sh` | 4h |
| P1.5 | `hooks/hooks.json` v0.2.0 注册 3 entrypoint | `hooks/hooks.json` | 0.2h |
| P1.6 | `skills/coordinator/writing-task-md/SKILL.md` 加 §0.5 generic 移动端版 | 同 | 1.5h |
| P1.7 | `skills/dev/assign/SKILL.md` 加 §0 baseline verify + §5 verify strict | 同 | 1h |
| P1.8 | 新建 `skills/dev/handoff/SKILL.md`(5 段强制)| 同 | 1h |
| P1.9 | 新建 `skills/coordinator/configure-sulde/SKILL.md`(sulde-init + 3 mode)| 同 | 2h |
| P1.10 | 新建 `commands/sulde-init.md` + `commands/sulde-add-{sensitive-file,scaffold,skill-trigger}.md` | 4 commands | 0.5h |
| P1.11 | `plugin.json` skills 字段加 configure-sulde / handoff | 同 | 0.1h |
| P1.12 | P1 unit test(dry-run 3 entrypoint + 11 子 logic + skill mode)| `tests/p1-hook-dryrun.sh` | 1.5h |

**Verify checklist**:
- [ ] `bash hooks/pre-tool-use.sh < test-input.json` 各 case 通过(coordinator Write task md / Dev Write handoff / Bash cd subdir / Bash git commit)
- [ ] `bash hooks/user-prompt-submit.sh` skill-trigger + perf-gate 命中
- [ ] `bash hooks/session-start.sh` 注入 CLAUDE.md head -60(若 .sulde-config 配)
- [ ] `lib/sulde-common.sh` walk-up 找 `.sulde-config.yaml` work / 项目无 config 时 silent
- [ ] `lib/enforcement.sh` strict/balanced/lenient 三档 exit code 正确
- [ ] `skills/coordinator/writing-task-md/SKILL.md` §0.5 完整
- [ ] `skills/dev/{assign,handoff}/SKILL.md` spec 完整
- [ ] `skills/coordinator/configure-sulde/SKILL.md` 4 mode 完整
- [ ] `plugin.json` skills 字段含 5 个 skill 路径
- [ ] dry-run tests 全过

---

### Phase 2 — Template 5 stack(~5-7h)

**Goal**:`template/{android, ios, flutter, rn, harmony}/` 各完整骨架,sulde-init cp 即用。

#### Tasks

| # | Task | Files | Time |
|:-:|---|---|:-:|
| P2.1 | `template/_project/`(项目根:README + .gitignore + .sulde-config.yaml.example + scripts + docs-hub 骨架)| ~10 files | 1h |
| P2.2 | `template/android/` 完整骨架 | ~12 files | 1h |
| P2.3 | `template/ios/` 完整骨架 | ~12 files | 1h |
| P2.4 | `template/flutter/` 完整骨架 | ~12 files | 1h |
| P2.5 | `template/rn/` 完整骨架 | ~12 files | 1h |
| P2.6 | `template/harmony/` 完整骨架 | ~12 files | 1h |
| P2.7 | sulde-init skill 复制 logic 实测(每 stack dry-run)| — | 1h |

**Verify checklist**:
- [ ] 5 stack template 总 ~70 文件全部到位
- [ ] 每 stack CLAUDE.md.template stack-specific 段填全(build_cmd / install_cmd / log_cmd / lint_cmd)
- [ ] 每 stack .gitignore.template 含 stack 特定 ignore(Pods/ vs node_modules/ vs .dart_tool/ etc.)
- [ ] 每 stack scripts/pre-commit-installer.sh 可执行
- [ ] sulde-init dry-run android → user_project/android/ 完整复制
- [ ] sulde-init dry-run 5 stack 全选 → 5 frontend 全 copy

---

### Phase 3 — docs-hub mobile 化 + ADR 示例(~3-4h)

**Goal**:`template/_project/docs-hub/` 内填 mobile 默认内容,新项目装即获方法论。

#### Tasks

| # | Task | Files | Time |
|:-:|---|---|:-:|
| P3.1 | `docs-hub/00_shared-rules/data-sources.md.template`(mobile:design-truth > PRD > scaffold > 业务层) | 1 | 0.5h |
| P3.2 | `docs-hub/00_shared-rules/verify-build.md.template`(5 stack build/install/真机 verify)| 1 | 1h |
| P3.3 | `docs-hub/00_shared-rules/self-fix-boundary.md.template`(Dev 自发修复 5 类敏感清单)| 1 | 0.5h |
| P3.4 | `docs-hub/00_shared-rules/perf-diagnosis.md.template`(性能诊断门控 + 5 stack 工具)| 1 | 0.5h |
| P3.5 | `docs-hub/00_shared-rules/model-strategy.md.template`(Dev 端 sonnet / opus / haiku 选择)| 1 | 0.3h |
| P3.6 | `docs-hub/ADR/0001-coordinator-impression-based-dispatch.md.template`(generic 0100 mobile 版)| 1 | 0.5h |
| P3.7 | `docs-hub/ADR/0002-scaffold-bypass.md.template`(generic 0097 mobile 版)| 1 | 0.5h |
| P3.8 | `docs-hub/ADR/0003-mobile-cold-flow-stateflow.md.template`(generic 0098,Android Kotlin Flow 通用)| 1 | 0.3h |
| P3.9 | `docs-hub/ADR/_frontmatter.schema.yaml` v0.2.0 升级(加 platforms enum:[android, ios, flutter, rn, harmony, coordinator]) | 1 | 0.2h |
| P3.10 | `docs-hub/ADR/INDEX.md` 加 0001-0003 行 + 移动端 ADR 累计 | 1 | 0.2h |

**Verify checklist**:
- [ ] 5 个 00_shared-rules 文件 generic mobile(无 Freebeat 痕迹)
- [ ] 3 个 ADR 示例 generic mobile(无 Freebeat 痕迹,可 placeholder 引导用户加项目特定 case)
- [ ] _frontmatter.schema.yaml 加 mobile-family platforms enum
- [ ] INDEX 含 3 ADR 示例 + 1 example(0000)

---

### Phase 4 — Release(~1.5-2h)

**Goal**:对外发布 v0.2.0 mobile-first。

#### Tasks

| # | Task | Files | Time |
|:-:|---|---|:-:|
| P4.1 | `docs/METHODOLOGY.md` mobile-first 重写(保留 7 层金字塔 generic + 加 "Why mobile-first" 段 + 5 stack 应用示例) | 1 | 0.5h |
| P4.2 | `README.md` 改 "mobile-first" banner + Quick start with sulde-init + 保留 N-end "Beyond mobile" 子段 | 1 | 0.5h |
| P4.3 | `plugin.json` bump version 0.1.0 → 0.2.0 + keywords 加 `mobile-android`, `mobile-ios`, `flutter`, `react-native`, `harmony` | 1 | 0.1h |
| P4.4 | `docs/GETTING_STARTED.md` 改 sulde-init 流程 | 1 | 0.3h |
| P4.5 | CHANGELOG.md 新建 v0.2.0 段(11 hook + 5 stack + configure-sulde skill + ADR + etc.) | 1 | 0.2h |
| P4.6 | git commit + push GitHub | — | 0.2h |
| P4.7 | GitHub release tag v0.2.0 + release notes | — | 0.2h |

**Verify checklist**:
- [ ] METHODOLOGY mobile-first 段 + 7 层金字塔 generic 保留
- [ ] README banner mobile-first + Quick start sulde-init
- [ ] plugin.json version 0.2.0 + keywords 5 stack 加完
- [ ] CHANGELOG 含 11 hook + 5 stack + configure-sulde 等
- [ ] git tag v0.2.0 + release notes 含 migration from v0.1.0

---

## v0.2.1+(open questions)

### v0.2.1(~6-8h)

| # | Item |
|:-:|---|
| 1 | 协调端 PreToolUse(Write pen-truth supplement)hook 拦缺三方判定 |
| 2 | 协调端 PreToolUse(Write ADR)hook 拦缺 frontmatter / baseline |
| 3 | 加 stack:KMP / Capacitor Mobile(每加 1 stack ~1h)|

### v0.3(~15-25h)

| # | Item |
|:-:|---|
| 4 | Inter-project common antipattern pool(跨项目 ADR 共享 + opt-in 继承机制) |
| 5 | `sulde audit` CLI(扫项目 ADR 覆盖率 / handoff 积压 / scaffold-bypass)|
| 6 | `sulde lint --pending` CLI(列待 lint 化 ADR)|
| 7 | `sulde common-antipatterns add <id>` CLI(项目 opt-in pool ADR)|

---

## 完工后 sulde-cc 形态

```
sulde-cc/  (v0.2.0)
├── .claude-plugin/
│   └── plugin.json                          # 0.2.0 + keywords mobile-first
├── README.md                                # mobile-first banner + sulde-init quick start
├── CHANGELOG.md                             # v0.2.0 完整变更
├── LICENSE                                  # MIT
├── CONTRIBUTING.md
├── commands/
│   ├── sulde-init.md
│   ├── sulde-add-sensitive-file.md
│   ├── sulde-add-scaffold.md
│   └── sulde-add-skill-trigger.md
├── docs/
│   ├── METHODOLOGY.md                       # mobile-first 重写
│   ├── GETTING_STARTED.md                   # sulde-init 流程
│   ├── V0.2.0-DESIGN.md                     # 本设计 doc(保留作历史档案)
│   ├── ROADMAP.md                           # 本 roadmap
│   └── i18n/
├── hooks/
│   ├── hooks.json                           # 3 entrypoint 注册
│   ├── pre-tool-use.sh                      # entrypoint 1
│   ├── user-prompt-submit.sh                # entrypoint 2
│   ├── session-start.sh                     # entrypoint 3
│   └── lib/
│       ├── sulde-common.sh
│       ├── enforcement.sh
│       ├── check-task-md-baseline.sh
│       ├── check-handoff-verify.sh
│       ├── check-subdir-cd.sh
│       ├── check-git-commit-alias.sh
│       ├── check-branch-protect.sh
│       ├── check-branch-format.sh
│       ├── check-commit-alias.sh
│       ├── check-ai-traces.sh
│       ├── skill-trigger.sh
│       ├── perf-gate.sh
│       └── claude-md-inject.sh
├── scripts/                                 # 内部脚本(非 template,sulde 本身用)
│   └── (legacy skill-trigger.sh 移到 hooks/lib/)
├── skills/
│   ├── coordinator/
│   │   ├── writing-task-md/SKILL.md         # 加 §0.5
│   │   └── configure-sulde/SKILL.md         # 新建
│   ├── dev/
│   │   ├── assign/SKILL.md                  # 加 §0 baseline verify + §5 verify strict
│   │   └── handoff/SKILL.md                 # 新建
│   └── shared/
│       └── update-design/SKILL.md           # 增强 Pencil MCP 流程
├── template/
│   ├── _project/                            # 项目根模板
│   │   ├── README.md
│   │   ├── .gitignore.template
│   │   ├── .sulde-config.yaml.example       # mobile default schema
│   │   ├── scripts/
│   │   │   ├── coordinator-baseline.sh.template
│   │   │   └── health-check.sh.template
│   │   └── docs-hub/
│   │       ├── 00_shared-rules/             # 5 文件 mobile generic
│   │       ├── design-truth/
│   │       └── ADR/                         # 3 mobile 示例
│   ├── android/                             # 5 stack 完整骨架
│   ├── ios/
│   ├── flutter/
│   ├── rn/
│   └── harmony/
└── tests/
    └── p1-hook-dryrun.sh                    # Phase 1 hook dry-run 测试
```

---

## Phase 间依赖

```
P1 (hooks + skills) ─┬─→ P2 (template — 需要 hooks/lib/ 路径稳定)
                     │
                     └─→ P3 (docs-hub — 需要 schema spec 稳定)

P2 ─┬─→ P4 (release — 需要 template 全到位)
P3 ─┘
```

→ **P1 必先**(blocker for P2/P3/P4);P2 / P3 可并行做(下次 session 并行);P4 最后。

---

## 跨 session 实施纪律(防 §0100 复发)

每次 session 开始 P1 / P2 / P3 / P4 前:

1. Read 本 ROADMAP 找当前 phase
2. Read `V0.2.0-DESIGN.md` 找对应 §(spec 不偏离)
3. 跑 Phase verify checklist 全过才标 done
4. 每 phase 1 commit(不 squash)+ branch `dev/v0.2.0-p<N>-<slug>`
5. P1-P4 全过 → merge `dev/v0.2.0` → main → tag v0.2.0
