# sulde-cc Onboarding — 给新项目 / 老项目接入用

> 适用对象:任何想用 sulde-cc 协调多端 Claude Code 工作流的项目(coordinator + N Dev sessions)。
> 适用版本:v0.1.x(当前 release)。v0.2.0 mobile-first 设计完成,实施中 — 见 `V0.2.0-DESIGN-v2.md`。
> 替代关系:本 doc 比 `GETTING_STARTED.md` 更完整 — 增加老项目接入路径 + 非 GitHub install + project-private skill 机制。

---

## 0. 快速决策矩阵

| 你的场景 | 走章节 |
|---|---|
| 新项目 + 在 GitHub | §1 + §2 + §3 |
| 新项目 + 内网 / 气隙 | §1 + §2(方案 B/C)+ §3 |
| 老项目接入 | §1 + §4 + §5 |
| 已用 sulde,想加项目特定 skill | §6 |
| Mobile 项目 + 想要 v0.2.0 体验 | §7(等 v0.2.0 实施完工)|

---

## 1. Prerequisites

- **Claude Code** 已装(任何版本支持 plugin v2)
- 项目根有 git 仓库(可初始化空仓库:`git init`)
- 可选:用户 git identity 已配(`git config user.name`)— sulde 会在 task md 内引用作者
- v0.2.0+ 才需要:**Python 3.6+** + pyyaml(`pip install pyyaml`)— v0.1.x 全 bash,无 Python 依赖

---

## 2. Install sulde-cc(4 种方式)

### 方案 A:GitHub 公开仓库(最简单)

```
/plugin marketplace add EthanReedLabs/sulde-cc
/plugin install sulde-cc@sulde-cc
```

适合**有 GitHub 访问**的所有开发者。装完 plugin 进 Claude Code 全局,对所有项目可用(但 opt-in,只对有 `.sulde-config.yaml` 的项目生效)。

### 方案 B:本地路径(离线 / 私有改动)

```sh
# 先 clone 到你能访问的本地路径
git clone https://github.com/EthanReedLabs/sulde-cc.git /Users/you/path/to/sulde-cc

# 或从你的 fork
git clone git@github.com:your-org/sulde-cc-fork.git /Users/you/path/to/sulde-cc
```

```
/plugin marketplace add /Users/you/path/to/sulde-cc
/plugin install sulde-cc@sulde-cc
```

适合:**fork 改了想本地试**、**离线 / 内网开发**、**多个版本共存**(每个目录就是一个 marketplace)。

### 方案 C:内网 git server

```
/plugin marketplace add ssh://git@gitlab.company.com/team/sulde-cc.git
/plugin install sulde-cc@sulde-cc
```

或 HTTPS:`https://gitlab.company.com/team/sulde-cc.git`。

适合:**公司内部 GitLab / Gitea / Bitbucket**。

> ⚠️ Claude Code Plugin v2 对完整 git URL 的支持度未二次实证。若失败,降级到方案 B(clone 到本地再 add)。

### 方案 D:tar / zip 分发(气隙环境)

```sh
# 打包方(可联网机器)
cd ~/path/to/sulde-cc-parent     # 含 sulde-cc/ 的父目录
tar czf sulde-cc-v0.1.1.tar.gz sulde-cc/

# 分发方(气隙机器)
mkdir -p ~/claude-plugins
tar xzf sulde-cc-v0.1.1.tar.gz -C ~/claude-plugins/
/plugin marketplace add ~/claude-plugins/sulde-cc
/plugin install sulde-cc@sulde-cc
```

适合**纯气隙环境**(金融 / 国防 / etc.)。

---

## 3. 新项目接入(15-20 min)

### Step 1 — 装 plugin(§2 任选)

### Step 2 — 把 template 复制到新项目(3 min)

**先找到 plugin install 实际位置**(Claude Code 协议未硬定义父目录,因 marketplace 名 / 装机方式而异):

```sh
# macOS / Linux — 自助找
find ~/.claude -maxdepth 5 -type d -name "*sulde*" 2>/dev/null
# Windows — Git Bash / WSL2 内同上;PowerShell:
# Get-ChildItem -Path $env:USERPROFILE\.claude -Recurse -Directory -Filter '*sulde*'

# 把找到的路径设为变量(本 doc 后续用 $SULDE 引用)
export SULDE=$(find ~/.claude -maxdepth 5 -type d -name "sulde-cc" 2>/dev/null | head -1)
echo "Found sulde at: $SULDE"
```

若找不到 → plugin 未装成功,回 §2 检查 `/plugin install` 输出。

**然后复制 template**:

```sh
cd ~/path/to/your-new-project

# 复制 docs-hub 骨架
cp -r "$SULDE/template/docs-hub" ./
# 复制一个 frontend 骨架(改名匹配你的项目)
cp -r "$SULDE/template/frontend-a" ./web
# 复制 .sulde-config 例子
cp "$SULDE/template/.sulde-config.yaml.example" ./.sulde-config.yaml
```

### Step 3 — 填 `.sulde-config.yaml`(5-10 min)

打开 `.sulde-config.yaml`,改以下字段:

```yaml
enabled: true

role: coordinator                # 项目根 session 跑协调端就标 coordinator
                                 # 若单 dev 项目无协调:both
                                 # 若是 Dev session(cd 进 frontend):dev

docs_hub: ./docs-hub             # 你 step 2 复制的目录名(可以改 ./docs / ./meta / 任意)

frontends:                       # 每个 Dev 工作目录一条
  - name: web
    path: ./web                  # 相对项目根
    stack: web                   # web / mobile-ios / mobile-android / backend / 自定义
  - name: mobile
    path: ./mobile
    stack: mobile-ios

design_source:                   # 可选 — 无设计稿就整段删
  mcp: pencil                    # pencil / figma / sketch / custom
  file: ./design/app.pen
  asset_root: ./design/assets/

team:                            # 每个 frontend 至少 1 个 git alias
  - alias: as-a
    name: Alice Liu
    email: alice@company.com
    frontend: web

project:
  name: my-project
```

### Step 4 — 给每个 frontend 写 CLAUDE.md(3 min/frontend)

```sh
cp "$SULDE/template/frontend-a/CLAUDE.md.template" ./web/CLAUDE.md
```

打开 `./web/CLAUDE.md`,替换占位符:
- `{{frontend_name}}` → `web`
- `{{frontend_path}}` → `./web`
- `{{git_alias}}` → `as-a`
- `{{author_name}}` / `{{author_email}}` → 团队成员信息
- `{{integration_branch}}` → `develop`(或 `main`)

### Step 5 — 配 git alias(每个 team member 1 次,2 min)

```sh
git config alias.as-a "commit --author='Alice Liu <alice@company.com>'"
# 每个 alias 一条
```

之后 Dev 用 `git as-a commit -m "..."` 提交,作者身份明确。

### Step 6 — 验证 sulde 已激活(1 min)

在项目根开 Claude Code session,输入:

```
帮我看看 sulde 配置
```

若 sulde plugin 检测到 `.sulde-config.yaml`,会在 UserPromptSubmit hook 内输出 reminder,提示用 `writing-task-md` skill。

**预期看到的 reminder 长这样**(stderr 输出,Claude 会读到并在回复里 reference 对应 skill):

```
⚠️ 协调端 skill 自动触发提醒(本轮 prompt 命中以下场景,**动作前必先 Read 对应 skill**):

  • 配置 sulde 相关
    → Read `.claude/skills/configure-sulde.md`(或对应 skill)

完整规则在上述 skill 文件中(CLAUDE.md 已迁出不复述)。
```

看到 reminder = ✅ sulde 激活。若**没看到任何 reminder**(直接得到 generic 回答):
- 检查 `.sulde-config.yaml.enabled: true`
- 检查 cwd 在 `.sulde-config.yaml` 所在目录或子目录(plugin walk-up 找配置)
- 检查 plugin 装上了(`/plugin list` 应显示 `sulde-cc`)

### Step 3.5 — 22 skill 入门学习顺序(推荐 ~30 min)

装 plugin 后 `/help` 会显示 22 skill,陌生用户容易迷糊从哪起。**按使用频次分 3 层学习**:

#### 🔴 Week 1 必读(高频日用 — 不读会卡在第一个 task)

| skill | 作用 | 何时用 |
|---|---|---|
| `writing-task-md` | 协调端写 task md 的契约 | 派活前必读 |
| `assign-android` / `assign-ios` | Dev 端接 task md 的流程 | Dev 收 task 后必读 |
| `multi-source-review` | 完工自检 / 评估流程 | claim 完工前 + 用户问"什么问题"|

→ 这 3 个 skill 是 sulde 工作流的**最小闭环**,先读完这 30 min 再用 sulde 干活。

#### 🟡 Week 2-3 按需读(中频 — 遇到对应场景再读)

| skill | 触发场景 |
|---|---|
| `dispatch-parallel-task` | 第一次派 ≥ 2 个并行 task |
| `bug-hunt-android/-ios` | 第一个偶发 bug |
| `code-review-android/-ios` | 第一次 cross-review PR |
| `update-design` | 第一次设计稿改动同步 |
| `ui-impl-android/-ios` | 第一次 UI 还原 task |

#### 🟢 用时再读(低频专项 — 不预读,用时 Read)

- `perf-diagnose-android/-ios` — 性能问题诊断
- `crash-fix-android/-ios` — Crash 系统化定位
- `parallel-dev-android/-ios` — 单端多任务并行
- `postmortem-android/-ios` — 事故复盘
- `record-prd-supplement` — 甲方需求补充登记
- `coordinator-maintenance` — 周期 audit / handoff 处理

**入门 anti-pattern**:试图一次 read 完所有 22 skill,信息过载消化不了。**按频次渐进读**,3-4 周内自然全用到。

> 注:dev-android/* 与 dev-ios/* 是双端镜像(8 对),工具链差异真(adb vs xcrun),你只读自己端即可(全 mobile 协调端读两套)。

### Step 3.6 — sample 业务术语 placeholder 提醒

22 skill 的 body 内含 `<SampleAgent>` / `<SampleRealtime>` / `<sample-feature: AI Agent>` 等占位符 — 这是从 sample 项目泛化来的**业务术语示例**。**用前必替**:用你的项目业务功能名替换(Feature 名 / page label / column 值 等)。

也可以保留占位先体验流程,熟悉 sulde 工作流后再 sed 替换。

---

## 4. 老项目接入(20-30 min)

老项目接入**最大原则**:**opt-in + 不强改 history + 不强改目录**。

### Step 1 — 评估老项目(5 min)

老项目接入前自检 4 问(决定接入方式):

| 自检问 | 处理 |
|---|---|
| `CLAUDE.md` 是否已被 git tracked? | 若是 → 保留,加 sulde 段到尾部(不替换);若否 → 加 `.gitignore` |
| `.claude/` 或类似 AI 配置目录是否存在? | 若存在 → 评估冲突,可能 `docs_hub: ./meta` 改名避开 |
| 团队是否已用 git hooks(husky / lefthook / pre-commit framework)? | 若是 → §4 step 5 共存策略;若否 → 直接装 sulde pre-commit |
| 项目目录结构是 monorepo / multi-package / 自定义? | sulde `frontends[].path` 映射已有路径即可,**不需要 move 业务源码** |

### Step 2 — 装 plugin(§2 任选)— opt-in

装完 plugin 对**所有老项目仍 silent**(无 `.sulde-config.yaml` 不激活)。可以无后顾地装。

### Step 3 — 在老项目根放 `.sulde-config.yaml`(10 min)

**老项目核心技巧:目录映射,不改名**

```yaml
# 老项目根 .sulde-config.yaml
enabled: true
role: coordinator

# ⭐ 映射到已有目录(不强求新建 docs-hub/)
docs_hub: ./docs                 # 已有 ./docs/ 直接指
                                 # 没有任何 docs 目录 → 创建 ./meta/ 或 ./docs-hub/

frontends:
  - name: web
    path: ./packages/web         # ⭐ monorepo 子包直接指(不需要移动业务源码)
    stack: web
  - name: api
    path: ./services/api
    stack: backend
  - name: mobile-android
    path: ./apps/android         # 已有 Android 子目录
    stack: mobile-android

design_source:                   # 老项目无设计稿 → 删整段
  mcp: pencil
  file: ./design/app.pen

team:                            # 列已有团队 git identity
  - alias: as-alice
    name: Alice Liu
    email: alice@company.com
    frontend: web
  - alias: as-bob
    name: Bob Zhang
    email: bob@company.com
    frontend: api

project:
  name: legacy-project           # 任意项目名

# 临时关闭(评估期 / 发版冻结期 / CI):
# enabled: false
```

落了这 file sulde 才"激活"。没动一行业务代码。

### Step 4 — 每个 frontend 加 `.ai-workspace/` 目录(2 min/frontend)

```sh
cd ./packages/web
mkdir -p .ai-workspace/{tasks,handoff,baseline,session-resume}
echo "*" > .ai-workspace/.gitignore  # 整目录不进 git(AI 痕迹隔离)
```

老项目里 `.ai-workspace/` 是 sulde 工作流必要(task / handoff / session 接力等都用它)。**默认全 ignore**,不污染 git。

### Step 5 — 与已有 git hooks 共存

若项目已用 husky / lefthook / pre-commit framework / 自管 `.git/hooks/pre-commit`:

#### 策略 A:chain — sulde 段加到已有 hook 末

```bash
# .git/hooks/pre-commit(老项目已有,加 sulde 段)
#!/bin/bash
# 原有逻辑保留
./scripts/lint.sh || exit 1
yarn test --quick || exit 1

# 加 sulde 段(只当 .sulde-config.yaml 存在时跑)
if [ -f .sulde-config.yaml ]; then
    # v0.1.x 没 git pre-commit hook 整套,只手 cp 需要的 check
    bash ${HOME}/.claude/plugins/sulde-cc/scripts/check-ai-traces.sh || exit 1
    # (v0.2.0 实施完后启用 — v0.1.x 此目录不存在,跳过本行)
    # source ${SULDE_PLUGIN_ROOT}/hooks/git-precommit/check_branch_protect.sh
fi
```

#### 策略 B:用项目 hook orchestrator(husky / lefthook)

把 sulde 检查写成 task 加进 husky `.husky/pre-commit` 或 lefthook `.lefthook.yml`。

#### 策略 C:渐进 enforcement(推荐老项目)

老项目首接入 sulde:
1. **不装** git pre-commit hook(只装 plugin + 加 `.sulde-config.yaml`)
2. 团队适应 1-3 个月,熟悉 task md / handoff 流程
3. 再加 git pre-commit(选 A 或 B)

v0.2.0 完工后:`enforcement_level: lenient` 起步 + 7 天 grace period 自动 enforce 软化(详 `V0.2.0-DESIGN-v2.md §2.3`)。

### Step 6 — 渐进采纳 docs-hub / ADR / design-truth(可选,~每月 1 项)

| 想要 | 加什么 | 阻力 |
|---|---|:-:|
| 只用 task md 派活规范 | 已就绪(plugin 装完即用 writing-task-md skill)| 0 |
| 加方法论文档 | 复 `template/docs-hub/00_shared-rules/` 到项目 `docs_hub/` | 低 |
| 加反模式 ADR 累积 | 复 `template/docs-hub/ADR/` 模板,从老项目历史事件回填 | 低-中 |
| 加设计稿单源同步 | 配 `design_source` + 用 `update-design` skill | 中(需 .pen / Figma 文件)|
| Dev 端 `.ai-workspace/` 跨 session 接力 | 每个 frontend 加目录(step 4 已做)+ 用 handoff 文件 | 中(团队需接受跨 session 工作流)|
| 全 enforcement(11 hook + 8 mode)| 等 v0.2.0 实施完工 + `/sulde-init` 引导 | 高 |

### 老项目接入红线(避坑)

- ❌ **不要**强求 `git rm` 已 tracked 的 `CLAUDE.md` / `.claude/`(改 history 高风险,团队炸锅)
- ❌ **不要**为了 sulde 移动业务源码目录(`frontends[].path` 映射已有路径即可)
- ❌ **不要**老项目首装就开 git pre-commit 硬阻塞(走渐进策略 C)
- ✅ **可以**先 1 个月只用 skill reminder(软提示),团队适应后再加 hook
- ✅ **可以**只在新功能 / 新分支用 sulde,老 bug fix 走团队原流程
- ✅ **可以**`enabled: false` 临时关 sulde(评估期 / CI / batch script)

---

## 5. 项目特定 skill(project-private)— ⭐ 核心机制

sulde-cc 提供**框架**,你的项目可能有**项目特定** skill(用户搜索习惯 / 团队约定 / 行业术语)。**不必把它们 merge 进 sulde-cc 公共仓**。

### 5.1 双层 skill loading 机制

Claude Code 在 session 内并行 load 2 类 skill:

| 来源 | 路径 | 触发优先级 | 适合 |
|---|---|:-:|---|
| **sulde-cc plugin skill** | plugin install 目录 `<sulde>/skills/`(`find ~/.claude -name "sulde-cc" -type d`) | 协议级 | 跨项目通用 |
| **项目本地 skill** | `<project-root>/.claude/skills/` | 项目级 | 项目特定 |

> 协议:Claude Code session 启动时扫两处,合并 skill list。同名 skill 项目本地版**优先**(覆盖 plugin 版)。

### 5.2 加项目特定 skill 的步骤

```sh
cd ~/your-project
mkdir -p .claude/skills

# 写 skill(单文件 .md,frontmatter 必填 name + description)
cat > .claude/skills/my-team-checklist.md <<'EOF'
---
name: my-team-checklist
description: Use when about to submit a PR for review. Walks through our team's 12-point PR checklist (security / accessibility / i18n / perf / etc.) before pushing.
user-invocable: true
---

# my-team-checklist

## 12-point PR checklist

1. [ ] Security: no secrets / no XSS / no SQL injection
2. [ ] Accessibility: keyboard nav / screen reader / contrast
3. ...
EOF

# 加 .gitignore 防 AI 痕迹进 git(若用 sulde 默认 .gitignore.template 已含)
echo ".claude/" >> .gitignore
```

或团队共享(进 git):

```sh
# 把团队共享 skill 进 git
git add .claude/skills/team-shared-*.md
# 加项目 README 说明"团队 skill 在 .claude/skills/,装 sulde-cc plugin 后自动 load"
```

### 5.3 项目特定 skill 命名建议

为避免与 sulde-cc 内置 skill 冲突:

| sulde-cc 内置 | 项目特定建议 |
|---|---|
| writing-task-md | my-team-task-md / company-task-spec |
| perf-diagnose | my-app-perf-diagnose / <project>-perf-android |
| code-review | my-team-code-review / accessibility-review |
| handoff | my-team-handoff |

### 5.4 项目特定 hook(进阶)

类似 skill,Claude Code 项目可加本地 hook:

```
<project-root>/.claude/settings.local.json
```

例如项目特定的 PreToolUse hook(配合 sulde 全局 hook):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write",
        "hooks": [
          {
            "type": "command",
            "command": "bash <project-root>/.claude/hooks/check-my-team-naming.sh"
          }
        ]
      }
    ]
  }
}
```

项目 hook + plugin hook **都跑**(没有"覆盖",一起加载)。

---

## 6. 各端工作流速查

### 6.1 协调端 session(项目根)

| 动作 | 走哪个 skill |
|---|---|
| 写 task md / 派活给 Dev | writing-task-md |
| 派 ≥ 2 个并行 task | dispatch-parallel-task |
| 设计稿更新 / 同步 | update-design |
| 处理 Dev handoff / audit | coordinator-maintenance |
| 甲方需求补充登记 | record-prd-supplement |

### 6.2 Dev session(cd 进 frontend 目录)

> ⚠️ v0.1.1 起 dev 端 skill **加端后缀**(防 plugin 内 namespace 冲突 — Claude Code 协议要求 `plugin-name:skill-name` 唯一)。Android 端用 `*-android` 后缀,iOS 端用 `*-ios` 后缀。

| 动作 | Android 端 skill | iOS 端 skill |
|---|---|---|
| 收 task md 干活 | `assign-android` | `assign-ios` |
| Bug 系统化诊断 | `bug-hunt-android` | `bug-hunt-ios` |
| Code review | `code-review-android` | `code-review-ios` |
| Crash 系统化定位 | `crash-fix-android` | `crash-fix-ios` |
| 多任务并行 | `parallel-dev-android` | `parallel-dev-ios` |
| 性能问题诊断 | `perf-diagnose-android` | `perf-diagnose-ios` |
| 复盘 / postmortem | `postmortem-android` | `postmortem-ios` |
| UI 设计稿还原 | `ui-impl-android` | `ui-impl-ios` |

Claude Code 调用形式:`/sulde-cc:assign-android` / `/sulde-cc:assign-ios`(plugin namespace + skill name)。

### 6.3 跨端 handoff

```
协调端 session ──写 task md──> <android-frontend>/.ai-workspace/tasks/{date}-{slug}.md
                                          │
                                          ↓ Dev session 用 /sulde-cc:assign-android
                              Dev 改代码 + 完工写 handoff
                                          │
                                          ↓
协调端 session <──Read handoff── <android-frontend>/.ai-workspace/handoff/{date}-{slug}-result.md
```

---

## 7. v0.2.0 mobile-first 预览(实施中)

完整设计 → `V0.2.0-DESIGN-v2.md` + `ROADMAP-v2.md`。

v0.2.0 主要差异(实施完工后):

| 维度 | v0.1.x | v0.2.0 |
|---|---|---|
| 适用 | 任何 N-end | mobile-only(android / ios / flutter / rn 4 stack)|
| install 后 | 手 cp template + 编辑 yaml | `/sulde-init` 8 步对话引导 |
| Hook 数 | 1(UserPromptSubmit skill-trigger)| 11(PreToolUse 4 + UserPromptSubmit 2 + SessionStart 1 + git pre-commit 4)|
| Skill 数 | v0.1.0 = 3 / v0.1.1(本 fork)= 21 | v0.2.0 generic 重写 ~5(coordinator + dev + shared)|
| Commands | 0 | 8(init / migrate / 5 add-* / end-grace)|
| 跨 OS | bash,Unix-like | Python 跨 macOS/Linux/Windows |
| Onboarding 体验 | 手动 4 步(15 min)| `/sulde-init` 自动 8 步(5 min)+ 7 day grace period |
| License | MIT | BSL v1.1(v0.1.0 仍 MIT 永久 grant)|
| 升级路径 | n/a | `/sulde-migrate-from-v0.1.0` 自动 patch backward-compat |

**v0.2.0 完工 ETA**:取决于 P1 实施启动时机。设计 spec 稳定,工时 ~30h(分 4 phase / 4 session)。

---

## 8. 卸载 / 临时关闭

### 临时关闭 sulde(项目级)

```yaml
# .sulde-config.yaml
enabled: false
```

→ 立即生效,plugin 在此项目内 silent。无需 uninstall。

### 卸载 plugin(全局)

```
/plugin uninstall sulde-cc
```

→ 移除 plugin,所有项目 `.sulde-config.yaml` 失效(但不删 yaml 文件,以后重装即恢复)。

### 卸载后清理(可选)

```sh
# 项目级:删 sulde 产出物(不删业务代码)
rm -f .sulde-config.yaml
rm -rf .ai-workspace        # 若你不想保留 task / handoff 历史
```

`docs-hub/` 通常保留(里面是团队方法论 ADR / 共享规则,与 sulde 解耦后仍有价值)。

---

## 9. FAQ

### Q1: 我的项目已经有完整 git hook(husky/lefthook),装 sulde 会冲突吗?

不会。sulde plugin 装完只是给 Claude Code 加 skill / UserPromptSubmit hook,**不动你的 git 仓 / git hooks**。需要 git pre-commit 时见 §4 step 5 共存策略。

### Q2: sulde-cc 这个 fork 含 "Dev A / Dev B" 等人名,我的项目用合适吗?

不合适。本 fork 是私人 fork,含 <project> 项目特定信息(开发者姓名 / Pencil MCP 路径 / 项目名)。

**给你的项目用 → 装 v0.1.0 release tag**(GitHub release 拉公开 generic 版,无私人信息),或 fork 后自己 strip。

### Q3: 我能跑 sulde 但不进 git 任何 sulde 文件吗?

可以。`.gitignore` 加:
```
.claude/
CLAUDE.md
.ai-workspace/
.sulde-config.yaml      # 若不想让其他 contributor 看到团队配置
```

→ sulde 完全本地化,git 仓零侵入。但同事装 plugin 后**他们的 session 看不到你的 .sulde-config**,要协调好(或大家用同一份 `.sulde-config.yaml` 进 git,只 `.ai-workspace/` 不进)。

### Q4: 项目同时有多个 Claude Code session(协调端 + 2 Dev),它们怎么知道各自身份?

通过 cwd + `.sulde-config.yaml.role` 字段。

- 协调端 session:cwd = 项目根,`.sulde-config.yaml.role: coordinator`
- Dev session:cwd = 某 frontend 子目录(`./web/` / `./mobile/`),sulde 自动检测属于哪个 frontend

实际你可以为每个端写**单独的 `.sulde-config.yaml`**(协调端根一份 + 各 Dev 子目录一份),`role` 不同。

### Q5: 我的项目老用 master 不是 main,sulde pre-commit 会拦吗?

v0.1.x 无 pre-commit hook,不会。v0.2.0 实施后 pre-commit 默认拦 main/develop,但 `.sulde-config.yaml.enforcement.branch.protected: [master, release]` 可改。

### Q6: 跨 session 的 `.ai-workspace/handoff/` 文件多了怎么管?

定期归档:`mv .ai-workspace/handoff/*-result.md .ai-workspace/handoff/archive/`。sulde 的 `coordinator-baseline.sh`(若装 scripts/)会统计 active 数量(协调端启动铁律)。

### Q7: v0.2.0 出来后怎么升级?

(v0.2.0 完工后)`/sulde-migrate-from-v0.1.0` 自动 patch `.sulde-config.yaml` + 备份原 file 为 `.sulde-config.yaml.v0.1.0-backup`。详 `V0.2.0-DESIGN-v2.md §9`。

### Q8: GitHub 上看到 main 分支有 21 个 skill,但 README 写 "3 core skills",是 bug 吗?

不是。**main 分支 = v0.1.1**(私人 fork,bundle 21 项目特定 skill);**v0.1.0 tag = generic 3 skill 版**(给新项目用)。

| 装哪个 | 命令 | 内容 |
|---|---|---|
| 通用 / 新项目用 | `/plugin marketplace add EthanReedLabs/sulde-cc@v0.1.0`(若支持 tag 参数)或先 clone 再 `git checkout v0.1.0` 本地装 | 3 generic skill,无项目特定信息 |
| 看作者私人沉淀 / 借鉴 | `/plugin install sulde-cc@sulde-cc`(默认 main = v0.1.1)| 21 skill 含 <project> 项目特定细节 |

### Q9: Windows 用户能用吗?

部分能。v0.1.x:
- ✅ Plugin install + skill / UserPromptSubmit hook → Windows native 都跑(Claude Code 跨平台)
- ⚠️ git pre-commit hook(若你照 §4 step 5 装)→ 需 Git Bash / WSL2(Windows native cmd 不能跑 bash 脚本)
- ⚠️ ONBOARDING §3 step 2 命令 → PowerShell 用户改用 `Get-ChildItem -Recurse` 替 `find`

v0.2.0+ 全 Python 化跨 OS,Windows native 完整支持。

### Q10: v0.1.1 装上后我看到 16 个 dev 端 skill(8 android + 8 ios),我只做 RN,要全部装吗?

不,Plugin install 全部加载但你**不需要全部用**。`/help` 列表会显示 16 个,你只用相关的(RN 用户走 `*-android` 或 `*-ios` 中接近的,或者**等 v0.2.0 mobile-first 重写**含 `dev-rn-*` 端)。

或:fork sulde-cc 删 `skills/dev-android/` 或 `skills/dev-ios/` 中你不需要的,本地装你自己的 fork。

---

## 10. 文档索引

> 链接在 `docs/` 目录内查看(相对路径);GitHub 渲染同目录文件直接点击。

| Doc | 内容 |
|---|---|
| [`../README.md`](../README.md) | sulde-cc 总览 + 5-min 装 + opt-in 设计 |
| [`GETTING_STARTED.md`](GETTING_STARTED.md) | v0.1.x 15-min walkthrough(本 doc 是其超集)|
| **`ONBOARDING.md`(本 doc)** | **完整 onboarding(新 + 老项目 + 非 GitHub + private skill)** |
| [`METHODOLOGY.md`](METHODOLOGY.md) | 7 层金字塔方法论(为什么需要 coordinator + N Dev)|
| [`V0.2.0-DESIGN-v2.md`](V0.2.0-DESIGN-v2.md) | v0.2.0 mobile-first 完整设计 spec(实施中)|
| [`ROADMAP-v2.md`](ROADMAP-v2.md) | v0.2.0 P1-P4 实施 roadmap |
| [`V0.2.0-DESIGN-REVIEW.md`](V0.2.0-DESIGN-REVIEW.md) | v1 → v2 review + 2 次实证 + 自审 audit log |

---

## 11. 反馈 / 问题

- GitHub Issues:https://github.com/EthanReedLabs/sulde-cc/issues
- 私人 fork 问题:联系本 fork owner

**License**:v0.1.x MIT 永久 grant。v0.2.0+ 切 BSL v1.1(实施完工后)。
