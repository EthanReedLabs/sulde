---
name: handoff
description: Dev 写 handoff 给协调端 / 任务完工交接 / /handoff / 提交 handoff doc / 交接给协调端。任务执行完毕,Dev 写一份结构化 handoff doc 把改动 / verify 证据 / escalation 候选交给协调端。当用户说"写 handoff""提交 handoff""交接给协调端""跑完了写交接"时触发。**handoff 必含 5 段强制**,缺段会被 PreToolUse hook `check_handoff_verify.py` 拦截。
user-invocable: true
---

# /handoff — Dev 完工交接 doc

任务执行结束 → 写 handoff doc 给协调端。**5 段强制**(缺一段 → hook 拦 Write),路径固定 `{frontend}/.ai-workspace/handoff/{YYYY-MM-DD}-{slug}-result.md`。

---

## §0 何时写 handoff

| 场景 | 写? | 命名后缀 |
|---|:-:|---|
| 跑完 task md(成功)| ✅ | `-result.md` |
| 跑 task md 中途遇阻 / 需协调端拍板 | ✅ | `-block.md`(无 `-result`)|
| 自发改动(非 task md 驱动 — 受 `self-fix-boundary.md` 约束)| ✅ | `-selffix.md` |
| 跑 audit / 诊断 subagent | ✅ | `-audit.md` |
| 真机 verify 抓的诊断数据 | ✅(归 `.ai-workspace/diag/` 不归 handoff) | n/a |

写入路径:`{frontend}/.ai-workspace/handoff/{YYYY-MM-DD}-{slug}-{result|block|selffix|audit}.md`

---

## §1 5 段强制内容(全含 → hook 放行)

handoff doc 必含以下 5 段(段标含**关键字串**,被 hook 字面检测):

### § 改动文件清单

列本次改了哪些文件 + 改了什么(用 file:line 引用,不空话)。

模板:
```markdown
## § 改动文件清单

- `feature-foo/src/main/java/.../FooView.kt:42-68` — 加 onAppear delay 150ms 防 jank
- `feature-foo/build.gradle.kts:14` — bump compose 1.6.1 → 1.6.2
- `.ai-workspace/diag/2026-05-25-foo-before.png` — 截图归档(verify 用)
```

**禁忌**:写"改了 FooView 相关逻辑"(太抽象)— 必引用 file:line。

### § verify(build / install / runtime 三联实证)

`assign` skill §5 跑的 4 步必复述结果。无 verify = handoff 不合格:

```markdown
## § verify

### Build
```
$ ./gradlew :app:assembleDebug
BUILD SUCCESSFUL in 32s
```

### Install
```
$ adb install -r app-debug.apk
Performing Streamed Install
Success
```

### Runtime log(10s)
- 无 crash / fatal / 新增 error
- 关键路径触达:adb logcat 抓到 `FooView onAppear` log 1 次,delay 后批量绑定开始

### Screenshot diff
- before:`.ai-workspace/diag/2026-05-25-foo-before.png`
- after:`.ai-workspace/diag/2026-05-25-foo-after.png`
- 视觉对照 design-truth `<docs-hub>/design-truth/03A1.md` §3.2 → ✅ 相符
```

**禁忌**:"build 过了 / 没问题" 一行 — 必贴命令 + 输出 / 路径。

### § escalation 候选(协调端待办)

跑过程中发现的"应给协调端拍板的问题",不要自行扩 scope。预登记:

```markdown
## § escalation 候选

- [ ] iOS 也有相同代码路径(`Sources/FeatureFoo/FooView.swift:55`)— 是否对称 fix?(scope 扩散,需协调端拍板)
- [ ] design-truth 03A1 §3.2 字号 25/600 vs scaffold AppTopBar 20sp 偏 5sp — 是 scaffold 应改 / 还是接受?
- [ ] 无 → 写 "本任务无 escalation"
```

### § 时序约束 / 性能数据(若 task 涉及性能)

若 task md 含"时序约束"或 "perf" 段 → handoff 必含真机数值:

```markdown
## § 时序约束 / 性能数据(本 task perf 相关)

- 进场动画 P50:120ms(before)→ 95ms(after,Profiler `gfxinfo dumpsys`)
- jank frame ratio:8.2%(before)→ 0.3%(after)
- 主线程 spike:无(after,Perfetto trace `diag/foo-trace.perfetto-trace`)
```

非 perf task → 写"本任务无性能指标"或省略本段。

### § baseline 反向 verify(可选,推荐)

如果 §0 baseline 验证(assign skill)过程中**发现 task md baseline drift** → 在 handoff 里说明:

```markdown
## § baseline 反向 verify

- task md `§起草前 baseline 实证` Step 4 引用 `AppTopBar.kt:56` → 当前 commit `abc1234` 已 rename 为 `AppTopBarView.kt:58`(发现于 §0 step 2 grep)
- 不阻塞本任务执行(改动点不依赖该 symbol),但**协调端起草 fix task 时需 re-baseline**
```

---

## §2 文件名规则

`{YYYY-MM-DD}-{frontend}-{slug}-{result|block|selffix|audit}.md`

例:
- `2026-05-25-android-foo-jank-fix-result.md`(成功完工)
- `2026-05-25-ios-bar-state-block.md`(中途阻塞,需协调端拍板)
- `2026-05-25-android-removed-stale-dep-selffix.md`(自发清理 stale dep,在 self-fix-boundary 内)

---

## §3 完工后动作

1. Write handoff doc(hook 通过)
2. `git add` 改动 + handoff doc + diag 截图 + log file
3. **不 commit** — 等 §1 § verify 段被你自己 Read 一遍 review 通过
4. `git as-<alias> commit -m "..."`(走 alias,被 pre-commit hook check_commit_alias 校验)
5. **不 push** — 等用户 / 协调端确认

---

## §4 反模式(常见错误,不要做)

- ❌ 直接对协调端说 "跑完了" / "改完了" / "done" 不写 handoff doc
- ❌ handoff 只写 § 改动文件清单 / 缺 § verify → hook 拦
- ❌ § verify 写"build 过了"一行无命令 / 无输出
- ❌ § escalation 候选写"无" 但实际发现了相邻问题没登记
- ❌ 把 verify 截图 / log 散在 `.ai-workspace/screenshots/` `.ai-workspace/log/` → 统一归 `.ai-workspace/diag/{date}-{slug}-{purpose}.{ext}` 方便协调端 grep
- ❌ handoff doc 内出现 `AI / Claude / GPT / generated` 字样 → pre-commit hook 拦

## §5 协调端如何用这份 handoff

写完后协调端会:

1. Read 你的 handoff doc(SessionStart 已扫 `.ai-workspace/handoff/active/`)
2. § verify 三联实证 cross check
3. § escalation 候选 → 协调端 review 后写新的 bounded task-md；不把候选当作已批准工作
4. handoff 处理完归档到 `.ai-workspace/handoff/archive/`

**你的 handoff 质量 = 协调端能不能信任 "Dev 跑完了"** — 直接影响下个 task md 是否还需重新 verify。
