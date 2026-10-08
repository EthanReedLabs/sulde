---
doc_id: "work-model/task-schema-v3"
container: work-model
platform: none
summary: "📍 **本文件是 task md frontmatter 字段 schema reference**(yaml 字段定…"
---

# Task / Handoff Schema v3(Agent 友好)

> 📍 **本文件是 task md frontmatter 字段 schema reference**(yaml 字段定义 + Dev session dispatch 规约),**真值入口** = `writing-task-md` skill(完整起草规则,含强制 baseline)
>
> 协调端写 task md 前**必读 writing-task-md skill**;本 schema 用于字段校验 + Agent dispatch 字段语义,不替代 skill 起草规则

---

> 比 markdown 自然语言更高效 — Dev session / 协调端 / Agent 看 YAML 直接按字段 dispatch,**不需要"理解再决策"** 的中间 token。

---

## §0 文件格式(纯 YAML)

- 文件后缀:**`.yaml`**(不再用 `.md` 含 yaml block 的 wrapper 模式)
- 文件直接 LLM dispatch:Dev session Read 文件 → yaml.safe_load → 按字段执行
- **顶层字段** = task metadata(身份/分支/能力档/工时/优先级/schema 版本)+ task body

---

## §1 task.yaml schema

```yaml
schema: task-v3                   # 必,固定 "task-v3"
id: <slug>                        # 必,task 唯一 id(与文件名同步)
identity: <enum>                  # 必,git 提交身份(Dev 姓名枚举)
git_alias: <as-a|as-b|as-c>       # 可,git 三人 alias
branch: <branch>                  # 必,目标分支
capability_tier: <enum>           # 必,宿主无关最低能力档(light/balanced/deep)
# model / thinking_mode            # 仅旧 task 读取兼容;新 task 禁止写
hours: <float>                    # 可,工时估计
priority: <P0|P1|P2>              # 可,默认 P1
reason: <string>                  # 可,task 触发原因(甲方 row N / 反模式 §x.y / etc)
preceding_handoff: <path>         # 可,前置 handoff 路径
prerequisite: <string>            # 可,启动前置条件(例:"上轮 task X 须先 commit")

target:                           # type=ui-fix / verify-redo 时必填
  page: <pageId>                  # pen-truth pageId
  node: <nodeId>                  # 设计稿 nodeId(via Pencil MCP)
  pen_truth: <path>               # pen-truth 设计稿 PNG 路径

files:
  edit: [<path>...]               # 改动文件白名单(scope 限定)
  read: [<path>...]               # 仅读不改的文件(LLM context)

fixes:                            # type=ui-fix 时必填,structured 改动清单
  - kind: <text|layout|color|font|asset|stroke|cornerRadius|frame>
    locator: <symbol-or-css>      # 控件定位(SwiftUI symbol path / Compose nodeId / CSS selector)
    from: <value>                 # 当前值(若不需删除可省)
    to: <value>                   # 期望值
    reason: <string>              # 可,1 行说明 why

prepare:                          # type=verify-redo 时填,真机环境前置
  - locale: en                    # 例:切英文 locale
  - state.item: selected          # 例:某项选中
  - state.toggle: on              # 例:toggle 选中

verify:                           # 验证策略
  pen_truth: <path>               # pen-truth PNG(默认同 target.pen_truth)
  fuzz_pct: 5                     # diff 容忍 %
  roi_config: <path>              # 可,启用 ROI 控件级 diff(long-page 必)
                                  # 例:"pen-truth/_redo/{pageId}.rois.yaml"
  scroll_position: <enum>         # 可,top/middle/bottom/full(配合 roi_config 选 ROI 子集)
                                  # 短屏真机 → top + bottom 各跑一次
                                  # 大屏真机 → full
  decision:
    A: "diff_pct < 5"             # PASS 自动 commit
    B: "5 <= diff_pct < 10"       # 不 commit / handoff
    C: "diff_pct >= 10"           # 不 commit / handoff
  user_navigation:                # user 手动操作真机指引
    - GDPR Accept All
    - Tab {某 Tab} → {某入口}
    - 屏幕停在目标页 → 报"到了"

commit:                           # decision=A 时自动跑 verify-page.sh commit
  msg: <string>                   # commit message(拟人化短句,无 AI 痕迹)
  merge_msg: <string>             # merge message
  paths: [<path>...]              # git add 路径白名单

forbid:                           # 反例清单(此 task 特有,通用反例在 task-md-template-v2.md §5)
  - <string>                      # 例:"用 Capsule() 替代 RoundedRectangle"
  - <string>

# ⚠️ ui-fix 类 task 必填 — 防视觉对齐误改业务链路
behavior_preservation:            # type=ui-fix 时必填,显式列保留的行为链路
  - <string>                      # 例:"保留 {某列表} item onTap → store.send(.itemSelected)"
  - <string>                      # 例:"保留 {某按钮} onTap → navigate(.toNextPage)"
  - <string>                      # 例:"保留 list scroll handler / refresh / pagination 不动"

handoff_path: <path>              # 必填,**.json 必,不允许 .md**
                                  # 例:".ai-workspace/handoff/{task.id}-handoff.json"

escalation:                       # 待处理 follow-up(handoff 时 Dev append 实际触发的)
  - id: <ref>                     # 例:{某统一样式 follow-up}
    desc: <string>
```

### §1.1 type 枚举

| type | 用途 | 必填字段 |
|---|---|---|
| `ui-fix` | UI 视觉对齐(本类 occupy ~60%)| target / files / fixes / verify / commit |
| `verify-redo` | 上轮 verify FAIL 复测 | target / prepare / verify / commit |
| `bug-fix` | 行为 bug 修复(crash / state / logic)| files / fixes / commit |
| `feature` | 新功能 | files / commit |
| `refactor` | 重构 | files / commit |
| `audit` | 仅审计 + handoff,0 改动 | files (read only) |

### §1.2 fixes[].kind 枚举

| kind | locator 形式 | from/to 类型 |
|---|---|---|
| `text` | `<viewSymbol>.label` / `<id>.text` | string |
| `layout` | `<viewSymbol>` | "fixed-bottom-outside-scrollview" / "match_parent" / 等指令 |
| `color` | `<viewSymbol>.fill` / `.background` | hex color "#RRGGBB" |
| `font` | `<viewSymbol>.font` | "Inter-SemiBold/14" / "Inter-Bold/24" |
| `asset` | `<viewSymbol>.icon` | "@drawable/ic_xxx" / "Image('xxx')" |
| `stroke` | `<viewSymbol>.stroke` | "1pt #RRGGBB" |
| `cornerRadius` | `<viewSymbol>` | int |
| `frame` | `<viewSymbol>` | "{width}x{height}" 或 "fill_container" |

---

## §1.3 type=ui-fix 完工自审清单(防视觉对齐误改业务链路)

Dev 完工 commit 前**必跑**(集成在 task-runner / verify-page.sh):

```bash
# Step A — diff 行为链路 grep(0 命中 = 安全)
DIFF=$(git diff develop..HEAD -- {files.edit})
echo "$DIFF" | grep -iE "onTap|onClick|setOnClickListener|store\\.send|store\\.intent|navigate|popToRoot|dismiss|onBackTapped|delegate|button\\b" \
    && echo "⚠️ diff 含行为链路关键词 — Dev 必显式确认每行非误改" \
    || echo "✅ diff 0 行为链路改动"

# Step B — handoff 行为链路自审段(必填)
# {handoff JSON 内含 behavior_audit 段 — 见 §2}
```

---

## §1.4 handoff 输出强制要求

| 项 | 要求 |
|---|---|
| **后缀** | `.json` 必(不允许 `.md` / `.yaml`)|
| **路径** | `.ai-workspace/handoff/{task.id}-handoff.json` |
| **格式** | 严格按 §2 schema(`json.loads()` 必能解析) |
| **判定** | Dev 完工写 `.md` handoff = 反模式;协调端 review 时退回让 Dev 重写 .json |

→ **协调端写 task md 时必含 `handoff_path` 字段**:

```yaml
handoff_path: .ai-workspace/handoff/{task.id}-handoff.json   # 必填,扩展名 .json
```

---

## §2 handoff.json schema

`verify-page.sh capture` 输出 + Dev append 的 final handoff:

```json
{
  "task": "<task.id>",
  "branch": "<branch>",
  "ts": "ISO-8601",
  "decision": "A|B|C",
  "diff_pct": 4.235,
  "fuzz_pct": 5,
  "passed": true,
  "screenshot": "/tmp/...png",
  "diff_png": "/tmp/...png",
  "stat": {
    "files": 2,
    "insertions": 45,
    "deletions": 38
  },
  "commit": "abc123 feat: ...",       // 仅 decision=A 时
  "merge": "def456 merge: ...",       // 仅 decision=A 时
  "deviations": [                     // 仅 decision=B/C 时,每项 < 30 字
    {
      "control": "{某按钮}",
      "issue": "底部不可见 — 短屏视口"
    }
  ],
  "escalation_triggered": [           // 仅当 task.yaml escalation[] 中真触发
    "{某 follow-up id}"
  ],
  "behavior_audit": {                  // ⚠️ ui-fix task 必填 — 防误改业务链路
    "diff_keyword_hits": 0,            // git diff 内 onTap/onClick/store.send/navigate 等关键词命中行数
    "preserved_handlers": [            // 实证保留的行为链路(每条对应 task.yaml behavior_preservation)
      "{某列表} item onTap → store.send(.itemSelected) ✅ 保留",
      "{某按钮} onTap → navigate(.toNextPage) ✅ 保留"
    ],
    "explicit_handler_changes": []     // 若 diff 命中关键词,逐条解释为何这是预期改动(空数组 = 无任何 handler 改动)
  }
}
```

---

## §3 渐进迁移

| 阶段 | 范围 |
|---|---|
| Phase 1 | 少量试点 task → YAML |
| Phase 2 | 主页面 / wizard 后续 全 YAML 写 |
| Phase 3 | 老 task md 不动(归档),新 task 全 YAML |

---

## §4 LLM Agent dispatch 规则(Dev session 看 task.yaml)

```
1. Read task.yaml
2. 按字段执行(不自然语言推理):
   - target.pen_truth → Read 真值
   - files.edit → 改动白名单(scope 限定 — 改这些之外的 = scope 扩散)
   - fixes[] → for each fix:
       - 找 locator 对应的 SwiftUI symbol / Compose node / XML id
       - 替换 from → to
   - prepare[] → 提示 user 操作真机
   - verify.user_navigation → 提示 user 导航
3. 编译 + 跑 verify-page.sh capture
4. 按 verify.decision 自动决策:
   - A → verify-page.sh commit(预授权)
   - B / C → 不 commit + 写 handoff.json(用 §2 schema)
5. handoff.json 内 deviations[] / escalation_triggered[] 自动 append
```

---

## §5 协调端写 task.yaml 5 步审单(同 v2 模板 §8)

| Step | 内容 | 防的反模式 |
|---|---|---|
| 1 | Read pen-truth/{pageId}.md + .png(target.pen_truth) | .pen 节点不导 .png 凭文字猜 |
| 2 | grep PRD INDEX § + API SPEC INDEX(写到 fixes[].reason)| 单维度数据源 |
| **3** | **Read 双端当前实施 + grep audit `currentState` vs pen-truth 真值**(写 fixes[].from) | 单维度数据源复发 |
| **3.5** ⭐ | **双端 audit:其中一端可能已 100% 对齐**(若是 → 标 `status: closed-no-op` 不派 task)| 防协调端凭 pen-truth 真值 + 推断写 fixes 而未 audit 当前实施已对齐 |
| 4 | WebFetch 技术真值(框架 bug)— 写 forbid[] | 凭命名假设 |
| 5 | task.yaml 含:① fixes[] 完整列举 ② forbid[] 特有反例 ③ escalation[] 候选预登记 ④ **`view_render_mode` 字段**(brand-png-direct / lucide-bg-tint / sf-symbol-fallback)防 cp asset 类 task 漏指定 view 渲染方式 ⑤ ui-fix 类必含 `behavior_preservation` 段 ⑥ `handoff_path: ....json` 必填 | 协调端凭印象 / 视觉误改链路(综合)|

---

## §6 收益(per task vs v2 markdown)

| 项 | v2 markdown | v3 YAML | 节省 |
|---|---:|---:|---:|
| task 文件长度 | ~50 行 | ~25 行 | ÷2 |
| Dev LLM 推理 token(自然语言理解→dispatch)| ~3K | ~600 | ÷5 |
| handoff 长度 | ~30 行 markdown | ~12 行 JSON | ÷2.5 |
| 协调端 review token | ~1.5K | ~300 | ÷5 |
| **每 task 总节省** | **~7K** | **~1.5K** | **÷4-5** |

**累积**:数十个后续 task → 大量 token 节省 + 工作日时间节省。
