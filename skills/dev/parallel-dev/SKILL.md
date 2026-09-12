---
name: parallel-dev
description: 并行任务派发 / multi-agent parallel / 多 dev 同时干活 / worktree 隔离 / parallel-dev — 协调端启动多个 git worktree 让不同 Dev 子 agent 并行实施互不耦合的任务。当用户说"并行修这几个""派 3 个 task 并行""worktree 隔离""parallel-dev"时触发。stack 中性 — verify 命令 / 公共文件白名单从 references/{stack}.md 读。
user-invocable: true
---

# 并行 Dev 派发(worktree-based)

为多个互不耦合的任务建 worktree,让多个 Dev 子 agent 并行实施,完成后顺序 merge develop。

**stack 决定后必先 Read 对应 references**:

| Frontend stack | 必 Read |
|---|---|
| `mobile-android` | `references/android.md` |
| `mobile-ios` | `references/ios.md` |
| `mobile-flutter` | `references/flutter.md` |
| `mobile-harmony` | `references/harmony.md` |

---

## §1 能力档

每个子 agent 读取 task 的 `capability_tier`,按目标宿主当前模型渲染(参 `/assign` skill §2)。
主协调与子任务都不得把某个宿主的型号或 thinking 语法写成共享任务真值。

---

## §2 触发条件 — 紧耦合识别 5 问

派 ≥ 2 个 task 前必跑:

| # | 问 | 命中处理 |
|:-:|---|---|
| 1 | 同文件改动? | 是 → **串行**,不 parallel |
| 2 | 共同基础设施(scaffold / utility)改? | 是 → **串行** + base task 先跑完再派 N 个 |
| 3 | task 之间有依赖关系(A 依赖 B 产出)? | 是 → **串行** |
| 4 | 单页 ≥ 2 task(进入 wizard 内多 stage)? | 是 → 1 人 1 条线 / 单 wizard 单 Dev |
| 5 | 跨任务共享资源(同 token / 同 drawable / 同 .pen 区块)? | 是 → 串行 |

任一命中 → **改串行**(用 `/assign` 顺序派,不用 `/parallel-dev`)。

---

## §3 公共文件白名单(stack 通用 — 永不并行改)

| 类型 | 通用语义 | stack 特定文件见 references §1 |
|---|---|---|
| 主入口配置 | App entry / module manifest | `AndroidManifest.xml` / `Info.plist` / `pubspec.yaml` / `module.json5` |
| Token Colors | 共享色 / 字号 / 间距 | `Colors.kt` / `AppColors.swift` / `app_colors.dart` / `AppColors.ets` |
| 全局 router | 导航 | `AppRouter.kt` / `AppRouter.swift` / `app_router.dart` / `Navigation.ets` |
| 全局 scaffold | TopBar / StateView / BottomSheet 等共享 UI 组件 | core-ui 模块下 |
| 构建配置 | dependency / build config | `build.gradle.kts` / `Package.swift` / `pubspec.yaml` / `build-profile.json5` |
| 国际化 | 文案多语言 | `strings.xml` / `Localizable.strings` / `*.arb` / `string.json` |

**改这些 = 派 1 人专修,其他 task 等其 merge develop 后再启动**。

详 stack 实际文件名 + 备选 list 见 references/{stack}.md §1。

---

## §4 执行流程

### Step 1:列任务清单

用户给 N 个并行任务,主协调端先 audit 5 问。

### Step 2:为每个任务建 worktree

```bash
git worktree add -b dev/{alias}/{module} ../{project}-{worktree-name} develop
```

worktree 命名建议:`{project}-{slug}`,与项目 root 同父目录。

### Step 3:并行 spawn N 个子 agent

用 Agent 工具同 message 内多个 tool_use 块并行启动。每个 agent prompt:

```
你是 {project} {stack} 项目的 Dev,身份 {git as-X}。

任务文件:{task-md path}
worktree:{worktree-path}
分支:dev/{alias}/{module}

执行:
1. cd 到 worktree
2. 跑 /assign skill(stack-specific verify 见 ${CLAUDE_PLUGIN_ROOT}/skills/dev/assign/SKILL.md + references/{stack}.md)
3. 修复 / 实施
4. 跑 §5 verify strict(build + install + log + screenshot)
5. 写 handoff(/handoff skill)
6. 通报主协调:任务完成 / 阻塞
```

### Step 4:主协调汇总

收齐 N 个 handoff 后:

1. 看每个 handoff `§ verify` 是否通过
2. 看 `§ escalation 候选` 是否合并冲突 / 跨任务影响
3. 按依赖顺序 merge develop(若无依赖,顺序无关)

### Step 5:清理 worktree

```bash
git worktree remove ../{project}-{worktree-name}
git branch -D dev/{alias}/{module}  # 已 merge 才 -d / 未 merge 报错
```

---

## §5 能力档矩阵(主 spawn 时给子 agent)

| 任务类型 | `capability_tier` |
|---|---|
| 架构 / 跨 module 重构 | deep |
| 新 Feature / UI 还原 | balanced |
| 复杂 bug 修 | deep |
| 字段改 / 简单 fix | light |
| 翻译 / 编译修复 | light |

---

## §6 子 agent verify 要求

每个并行 task 完工标准(与 /assign §5 一致):

1. build(stack-specific 命令见 references/{stack}.md §3)
2. install(install_cmd)
3. launch + 30s log(无 crash)
4. screenshot diff(若 UI 改)

handoff `§ verify` 必含 4 项证据。

---

## §7 失败处理

| 场景 | 处理 |
|---|---|
| 1 个子 agent 阻塞 | 不阻其他;handoff 反弹给主协调 |
| 多个 agent 共改同一文件(audit 漏)| 主协调发现 merge conflict → 撤后跑 task 改串行 |
| 修复后 verify 不过 | 子 agent handoff `-block.md`;主协调决定 retry / 改 spec / escalate |
| worktree 残留 | 跑完用 `git worktree list` + `prune` 清理 |

---

## §8 命名 / 分支约定

- worktree 路径:`../{project}-{slug}`(与项目同父)
- branch 格式:`dev/{alias}/{module}`(同 `/assign` skill)
- handoff 路径:每 worktree 内 `.ai-workspace/handoff/{date}-{slug}-result.md`

---

## §9 何时不用 /parallel-dev

| 场景 | 用什么 |
|---|---|
| 单 task | `/assign` |
| 一连串相关 fix(同模块顺序)| 多次 `/assign` |
| 单 Dev 多任务串行 | `/assign` 多次 |
| 多 Dev 但任务有依赖 | `/assign` 顺序派 |
| Crash / 偶发 bug 排查 | `/crash-fix` / `/bug-hunt` |
| Perf 诊断 | `/perf-diagnose` |
