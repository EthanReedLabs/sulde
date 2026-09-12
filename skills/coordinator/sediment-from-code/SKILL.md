---
name: sediment-from-code
description: 协调端处理 Dev 完工 handoff / merge 主干后,把代码层真值增量 sediment 到对应业务真值(BTM)doc 的完整流程。当用户说"sediment 真值 / BTM 同步 / 处理完工 handoff / sediment-from-code / module=X 同步"等触发词或协调端处理 Dev 完工 handoff 后必 invoke。覆盖状态化输入 + git log 增量算法 + AI 推荐维度归属 + 协调端 review 草稿 + sync task md 派单建议 + 双 Edit(当前快照 + timeline)+ metadata update。设计原则:代码即真值,handoff 只作触发,不作真值源。
user-invocable: true
---

# 协调端 sediment-from-code skill — 代码即真值的 BTM 增量沉淀

> **设计原则**:代码 = ground truth。handoff 会丢 / 会骗 / 会漏,只作 sediment 触发信号;真值源永远是 **git log + 双端 file:line + commit diff**。
> **关联 BTM 体系**:业务真值 `INDEX.md` + 各 `{module}-truth.md`
> **enforcement**:CLAUDE.md skill 索引含本 skill 触发条目 + baseline SessionStart hook 警告未 sediment 的 module

---

## §0 何时 invoke 本 skill

| 触发场景 | invoke 方式 |
|---|---|
| Dev 完工 handoff + merge 主干后 | `/sediment-from-code module=<module-name>` |
| SessionStart hook 警告"BTM {module}: N commit 待 sediment" | 同上,跟着 hook 提示 |
| 周期 audit(每 N 周)| 跑 subagent 兜底,本 skill 是半自动版 |

**不在以下场景 invoke**:
- ❌ Dev 完工但**未 merge 主干**(代码非 final 真值,可能 squash/refactor)
- ❌ 文档类改动(设计真值 / PRD 更新走各自路径)
- ❌ user 真机反馈(只是数据点,需 Dev verify 转 commit 后才 sediment)

---

## §1 输入接口(状态化 — 协调端零记忆负担)

### 协调端 invoke 时给 1 个参数即可

```
/sediment-from-code module=<module-name>
```

### skill 自查 commit range(基于 BTM doc frontmatter metadata)

```yaml
---
module: <module-name>
btm_version: v2
lastSedimentCommit_ios: <hash>      # DO NOT EDIT — managed by sediment-from-code skill
lastSedimentCommit_android: <hash>  # DO NOT EDIT
lastSediment: <ISO-8601 timestamp>
---
```

skill 流程:
1. Read 业务真值目录下 `{module}-truth.md` frontmatter
2. 获取 `lastSedimentCommit_ios` + `lastSedimentCommit_android`
3. 若缺(bootstrap 首次)→ STOP + 协调端显式给 `bootstrap-from=<主干>~N`(或 git tag)

### bootstrap 特殊形式

```
/sediment-from-code module=<module-name> bootstrap-from=<主干>~N
```

首次填充 BTM 当前快照 + timeline,本 skill 内置 bootstrap 子流程(scope 大,推荐派 subagent 兜底)。

---

## §2 skill 内部步骤(协调端 invoke 后 AI 自驱)

### Step 2.1 状态读取

```bash
# Read BTM frontmatter
last_ios=$(grep "lastSedimentCommit_ios:" "$BTM_DOC" | awk '{print $2}')
last_android=$(grep "lastSedimentCommit_android:" "$BTM_DOC" | awk '{print $2}')

# fallback 若 metadata 缺(BTM v1 未升级 v2)
[ -z "$last_ios" ] && last_ios="<主干>~N"
[ -z "$last_android" ] && last_android="<主干>~N"
```

### Step 2.2 git log 增量

```bash
# 双端主干自 lastSediment 后的 commit(限定 module 路径)
# module → 双端路径映射(协调端按本项目 feature 目录结构补全)
case "$module" in
    <module-a>)
        path_ios="Sources/Feature<ModuleA>/"
        path_android="feature-<module-a>/src/main/.../<module-a>/"
        ;;
    <module-b>)
        path_ios="Sources/Feature<ModuleB>/"
        path_android="feature-<module-b>/src/main/.../<module-b>/"
        ;;
    # ... 其余 module
esac

ios_commits=$(git -C "$REPO_IOS" log "${last_ios}..<主干>" --oneline -- "$path_ios")
android_commits=$(git -C "$REPO_ANDROID" log "${last_android}..<主干>" --oneline -- "$path_android")
```

### Step 2.3 对每 commit AI 推断

对每个 commit:

```bash
# 拿 diff
diff=$(git -C "$REPO" show "$commit" -- "$path")

# AI 推断(协调端在 skill 内 reasoning)
# 1. 抽取关键 file:line 改动
# 2. 抽取关键符号(函数 / 字段名 / 类名)
# 3. 推断 BTM 维度归属:
#    - 改 SSE wire / 字段落点 → 数据/协议维
#    - 改 model 字段 / join → 域模型维
#    - 改 view / 设计真值 / gating → 视图/交互维
#    - 改双端 file:line 取值 → 双端取值维
# 4. 推断双端同步状态(commit 标 ios → Android ❓ 待 verify)
```

**AI 推荐含 reasoning**(协调端 review 时看):
- 为什么入维 X
- diff 关键 file:line 截取
- 双端非对称 ❓ 项(若有)

### Step 2.4 生成 review report

```markdown
# Sediment Review Report — {module} ({date})

## 增量 commit 范围
- iOS: lastSediment=<hash> → 主干=<HEAD>(N commit)
- Android: lastSediment=<hash> → 主干=<HEAD>(M commit)

## commit-level Edit 推荐(每 commit 一段)

### {端} `<commit-hash>` — <commit-message>
- **diff 关键 file:line**:
  - `<file>:NNN` — <一行真因摘要>
- **AI 推断入维**:
  - 维 X §Y — <reasoning>
  - 双端 fix 状态同步表 — append 行(真因 / iOS ✅ commit / Android ❓ 待 verify)
- **Edit 草稿**(Agent 附证据生成，供结果审阅):
  ```diff
  @@ 维 X §Y @@
  - <旧>
  + <新>
  ```

## timeline append

每 commit 加一行(append-only):
| timestamp | 端 | 真因 | sediment 入维 | 同步表行号 | 状态变化 |

## sync task md 派单建议(基于同步表新 ❓ 行)

| ❓ 项 | 推荐派单方 | 优先级 | task md 草稿 |
|:-:|:-:|:-:|---|
| <真因 sync> | Android Dev / iOS Dev | P0/P1/P2 | <文件名 + scope 摘要> |

### 协调端建议动作
- [ ] 立即派 P0 sync task md(scope 单文件,~0.5h opus)
- [ ] P1 batch(N 项累积 ≥3 项一起派,~1-2h opus)
- [ ] P2 hold backlog(non-critical)

## Agent 判定与未决项
- [ ] 证据充分 → skill 自动 Edit BTM + update metadata，并保留 diff
- [ ] 可机械修正 → Agent 修正草稿后继续，不让用户代 Edit
- [ ] 真实语义冲突 → 只列冲突事实和两个候选结论，等待自然语言选择
- [ ] commit 与 BTM 无关 → skill 跳过 + update metadata 防下次重试
```

### Step 2.5 协调端 review + 落地

Agent 基于 report 和一手 diff 落地：
- 证据充分 → 自动执行 Edit + update metadata，并运行 BTM 结构与引用校验
- 可机械调整 → Agent 修改草稿并继续
- 两个语义方案都合理且会改变业务真值 → 向用户询问唯一高区分度问题；用户自然表达后由 Agent 落地
- 与 BTM 无关 → update metadata `lastSedimentCommit` 到 HEAD，防下次重复评估同 commit

### Step 2.6 update metadata

```bash
# skill 完工时 update BTM frontmatter
sed -i '' "s/^lastSedimentCommit_ios: .*/lastSedimentCommit_ios: $new_ios_hash/" "$BTM_DOC"
sed -i '' "s/^lastSedimentCommit_android: .*/lastSedimentCommit_android: $new_android_hash/" "$BTM_DOC"
sed -i '' "s/^lastSediment: .*/lastSediment: $(date -u +%Y-%m-%dT%H:%M:%SZ)/" "$BTM_DOC"
```

---

## §3 落地 BTM 双 Edit(当前快照维 + timeline 维)

### 双端 fix 状态同步表(update 现有行 / append 新行)

```markdown
| 真因 | Android 状态 | Android commit | iOS 状态 | iOS commit | 真机 verify | follow-up |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| <某真因> | ❓ 待 verify | — | ✅ | `<hash>` | iOS ✅ user <date> | ⏳ Android sync |
```

**update 规则**:
- 新真因首次出现 → append 新行(发现端 ✅ + 另一端 ❓)
- 已有真因,另一端 follow-up 完成 → 现有行的 ❓ 改 ✅ + 补 commit hash

### timeline append(append-only,不 update)

```markdown
| timestamp | 端 | 真因 | sediment 入维 | 同步表行号 | 状态变化 |
|:-:|:-:|---|:-:|:-:|---|
| <ISO 时间> | iOS | <某真因> | 视图维 + 同步表新增 | 第 N 行 | 新增:Android ❓ / iOS ✅ commit `<hash>` |
```

**append 规则**:
- 每 commit sediment 一行(timestamp = commit author date)
- "状态变化"列描述具体动作(新增 / Android ❓→✅ / iOS ❓→✅)
- 不允许 update 历史行(append-only)

---

## §4 反例(禁区)

- ❌ skill 直接基于 Dev handoff 描述 sediment 真值(违反"代码即真值"原则)
- ❌ 跨 worktree / 跨分支 sediment(代码未 merge 主干不算真值)
- ❌ AI 自由判断维度归属不附 reasoning(协调端无法校准)
- ❌ skill 无证据改写 BTM，或把可审阅 diff 的生成本身升级成人工确认门
- ❌ 不 update metadata `lastSedimentCommit`(下次 invoke 重复评估同 commit)
- ❌ "全自动"模式跳过协调端 review

---

## §5 与 subagent 兜底的关系

| skill(本)| subagent(兜底)|
|:-:|:-:|
| 协调端 invoke,~10-15min | 协调端派 subagent,~30-45min opus 成本 |
| Agent 判定 + 证据化 diff，歧义才询问 | 自动跑完整流程,事后 review |
| 适用增量 sediment(N 个 commit) | 适用 bootstrap / 周期 audit / 复杂 module |
| 频率高(每完工 handoff) | 频率低(每周 / 每 module 初始) |

**何时切换 subagent**:
- bootstrap 首次(commit 量超本 skill 处理量)
- skill 跑出来 ❓ 项 ≥ 10(协调端 review 负担过重)
- 复杂 module(跨双端 + 跨多 stage)

---

## §6 关联

- BTM 体系:业务真值 `INDEX.md`
- BTM doc 模板:业务真值 `{module}-truth.md`
- enforcement:baseline SessionStart hook(BTM sediment 漂移检测段)
- task md skill:`writing-task-md`(BTM 引用必填 + sync task 派单)
- 反模式:协调端凭印象同源根因 — 本 skill 是工具化防御
