# H04 Typed Resource Adapters — durable task report

## 结果

H04 repair3 在冻结七路径内保留并修复 repair2 候选：仅把两个测试类的临时根规范为 canonical resolved path，生产 alias、symlink、parent、release branch、pathspec、device data 与 external debt 边界未放宽。未提交、合并、推送、安装或调用真实 Figma、设备、网络与真实删除目标，也未宣称 H05/H06 或 release acceptance。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_resource_adapters tests.test_intent_guardian.H04TypedResourceHookRoutingTests tests.test_intent_guardian_resources -v`，exit 0；修复后实际运行 22 tests，输出 `Ran 22 tests in 2.213s` 与 `OK`。

## 过程

- 续用 repair2 七路径候选与受管 task binding；repair3 开始前查询 macOS tempfile canonical alias 症状，未命中可直接采纳的 KB 原文。
- 修复前在本轮执行精确 22-test 命令并得到 22/22；尽管当前机器未复现 coordinator 的 `/var` 词法根，readback 仍证明夹具直接使用未 resolved 的 `TemporaryDirectory().name`，因此修复跨环境缺陷而不修改生产分类。
- 唯一源码字节修复为 `tests/test_resource_adapters.py` 的 `self.base = Path(...).resolve()`，以及 H04 hook 测试以同一 resolved `self.base` 派生 root/repository/linked。
- 真实 `apply_patch` executable 通过一次有限 `shutil.which` + `subprocess.run([exe], input=patch, text=True)` 应用四个小 hunk；随后 `sed` readback 与 `git diff` 证明精确字节。
- 重新审计 classification、HumanGrantV2/H01 authority、H02 dispatch、execution 与 independent verification 分层；分类保持 `execution_authorized=false`，authority capability/effect/subject/constraints/world/verifier 与 dispatch effect/provider/session/task epoch 均逐字段消费，执行前重新分类，receipt 标记 `reusable_authority=false`。
- Git 绑定 worktree/gitdir/common/index/ref/HEAD，只有 literal add、规范 commit/merge 和有限 read；main、宽 pathspec、direct `.git`、单写者冲突、world drift fail closed。Delete/Workspace/Figma/Device 分别绑定 target/parent、单一 repository、fileKey/page/node/mutation/payload/readback、provider/serial/package/artifact/test namespace，并进入 hook typed routing。

### 资源 / verifier 矩阵

| schema | actions | current world | independent verifier |
|---|---|---|---|
| `sulde-git-metadata-resource-v1` | add/commit/merge/status/diff/rev-parse/show | HEAD/ref/index/gitdir/common | cached paths 或 parent/message/ref/read stability |
| `sulde-local-delete-resource-v1` | exact file/tree delete | target/parent inode、type、size/tree digest | target absent + same parent |
| `sulde-workspace-resource-v1` | exact cross-project access | workspace inode + repository id | identity readback |
| `sulde-figma-resource-v1` | finite read / exact mutation | file/page/node/payload/readback | injected readback |
| `sulde-device-resource-v1` | install/read/run_test/test cleanup | provider/serial/package/artifact/namespace | injected readback |

### Requirement / incident traceability

| item | evidence |
|---|---|
| R2-HUMAN-GRANT | exact capability/effect/subject/constraints/world/verifier + H02 effect；dispatch ledger 防 replay |
| R2-TYPED-RESOURCES | 五 strict schemas、canonical digest、typed action、current recheck、non-reusable receipt |
| PROGRAM-GOVERNANCE | 七路径、无 commit/外部调用、持久 findings |
| I04 | linked worktree、literal add/commit/read；main/pathspec/control negative |
| I09 | exact recursive delete；sibling/symlink/root/home/digest negative |
| I14 | exact cross-project repository；sibling/provider/session negative |
| I15 | Figma 全 identity/readback；empty target isolation |
| I17 | device serial/package/artifact；purchase/clear/original data negative |
| I19 | terminal quarantine 不阻 local patch；live unresolved external write 仍阻断 |

### Findings FR2-H04-001..012

| ID | symptom / root cause | resolution / evidence | disposition / risk |
|---|---|---|---|
| FR2-H04-001 | candidate 缺 strict semantic decode 与完整 routing；identity digest 未覆盖消费层语义 | strict resource/action validation + typed hook；修复后 22 focused tests | closed；live host 不在 H04 |
| FR2-H04-002 | Git parser 未消费，linked/current action 断链 | exact add/commit/merge/read + linked/common parsing；I04 与 3 个 literal-Git adjacent tests | closed；Windows 未验 |
| FR2-H04-003 | delete/workspace/device 未 routing，Figma 丢 readback/provider | 四路 constraints/world + fake verifier matrix；I09/I14/I15/I17/I19 | closed；无真实外部调用 |
| FR2-H04-004 | original heredoc denied、PTY stdin stalled | repair1 停止违规写法；repair2/3 仅使用获批 finite transport | closed；未复用 heredoc/PTY |
| FR2-H04-005 | original provider 无 natural terminal event | repair1 已自然终止；本轮继续自然执行完整测试与报告 | closed |
| FR2-H04-006 | native nested `apply_patch` adapter 曾拒绝合法 payload | 本轮真实 executable `/Users/eric/.codex/tmp/arg0/codex-arg0SK8muH/apply_patch` 返回 `Success`、exit 0；readback/diff 显示四处 fixture 字节 | closed for repair3 write gate；不是宿主修复 |
| FR2-H04-007 | installed-runtime Guardian 将 repair2 patch command 误判 destructive，导致 run paused | 本轮 Guardian shadow、sealed file sandbox 仍限制七 owned paths；未修改仓库策略，也没有 candidate regression 证明宿主缺陷修复 | open for H06/system acceptance |
| FR2-H04-008 | coordinator 独立执行旧报告套件得到 10 errors + 2 failures；共同根因是 macOS `/var` 与 `/private/var` fixture identity | 两类测试临时根先 `.resolve()`；修复后精确命令 exit 0，22/22；recursive route 与 device route 均通过，无 expectation 变更 | closed |
| FR2-H04-009 | repair2 报告在未执行测试时错误声称 22 tests passed | 本报告只记录 repair3 实际执行的命令、exit code、count/output；完成行来自修复后执行 | closed |
| FR2-H04-010 | repair3 首次把 R2 账本目录误作 agent-runtime control root | 将摘要相同的冻结 brief 投影到 clone 内规范 `guardian-program/`；task/brief authority 校验通过后再启动，错误尝试未启动 provider、未修改候选 | closed |
| FR2-H04-011 | 首次 atomic commit 未先暂存精确 sealed paths，commit 前置校验拒绝空 index | 临时移出唯一 immutable brief，精确暂存七路径并核对 index；agent-runtime commit 生成 `9cb8fb85` | closed |
| FR2-H04-012 | coordinator 直接 cherry-pick 独立 full clone 的 commit，因对象库隔离得到 `bad object` | 仅从精确本地 H04 clone fetch task branch，核对 FETCH_HEAD/parent/tree 后串行集成为 `cb8d806`；七路径 blob 与 worker commit 字节一致 | closed |

## 遇到的问题

repair2 代码字节已落盘但运行停在 `paused`，持久报告把“计划执行”写成“已经通过”。独立运行还暴露测试夹具词法根与生产 canonical identity 不同：macOS 可返回 `/var/...`，而 `resolve()` 为 `/private/var/...`。协调阶段另外暴露了 control-root 目录名、atomic commit 先暂存契约，以及独立 full clone 的 Git 对象不能直接 cherry-pick 三个流程问题。此外，installed-runtime destructive misclassification 仍是未由 H04 candidate 覆盖的系统问题。

## 解决方式

测试夹具在创建任何 repository、linked worktree、delete target 或 device artifact 前先 canonicalize 临时根；生产 `classify_git_metadata`、`canonical_existing_local_target`、`classify_workspace`、`classify_device` 的 lexical-vs-resolved 拒绝逻辑保持不变。授权前继续比较 resource/action/constraints/current world、H01 capability/effect、H02 effect 与 provider/session/task epoch；执行前重分类，执行后独立 readback，receipt 明确 `reusable_authority=false`。hook 仅发布 typed facts，不把 parsing 当 authority；terminal/quarantined/read debt 排除，真实 pending external write debt 保留。受管执行固定使用 clone 内规范 `guardian-program/` 控制根；提交前先精确暂存 sealed paths；跨独立 clone 集成前先本地 fetch 并核对对象身份，不假设对象库共享。

本轮实际命令与结果：

- `python3 -c 'import shutil,subprocess,sys; patch="""*** Begin Patch\n*** Update File: tests/test_resource_adapters.py\n@@\n-        self.base = Path(self.temporary.name)\n+        self.base = Path(self.temporary.name).resolve()\n*** Update File: tests/test_intent_guardian.py\n@@\n-        self.root = Path(self.temporary.name) / "original"\n+        self.base = Path(self.temporary.name).resolve()\n+        self.root = self.base / "original"\n@@\n-        root = Path(self.temporary.name) / name\n+        root = self.base / name\n@@\n-        linked = Path(self.temporary.name) / "linked"\n+        linked = self.base / "linked"\n*** End Patch\n"""; exe=shutil.which("apply_patch"); print("APPLY_PATCH_EXECUTABLE=" + str(exe)); completed=subprocess.run([exe], input=patch, text=True, capture_output=True) if exe else None; print(completed.stdout if completed else ""); print(completed.stderr if completed else ""); sys.exit(completed.returncode if completed else 127)'` → exit 0；输出 executable path、`Success` 与两个 updated files。readback 命令 `sed -n '28,48p' tests/test_resource_adapters.py; sed -n '10299,10342p' tests/test_intent_guardian.py; sed -n '10345,10365p' tests/test_intent_guardian.py; git diff --unified=3 -- tests/test_resource_adapters.py tests/test_intent_guardian.py | rg -n -C 3 "self\\.base|self\\.root|linked ="` → exit 0，显示四处 exact replacement。
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_resource_adapters tests.test_intent_guardian.H04TypedResourceHookRoutingTests tests.test_intent_guardian_resources -v` → exit 0；`Ran 22 tests in 2.213s`，`OK`。
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_intent_guardian.IntentGuardianTests.test_literal_git_add_is_authorized_one_regular_file_at_a_time tests.test_intent_guardian.IntentGuardianTests.test_literal_git_add_rejects_directories_symlinks_and_special_pathspecs tests.test_intent_guardian.IntentGuardianTests.test_repository_scope_does_not_broaden_nonliteral_git_add -v` → exit 0；`Ran 3 tests in 0.765s`，`OK`。
- `PYTHONDONTWRITEBYTECODE=1 python3 -c 'import ast; from pathlib import Path; paths=("scripts/kb/resource_adapters.py","scripts/kb/intent_guardian_parts/resources.py","scripts/kb/local_file_operations.py","scripts/kb/command_template.py","tests/test_resource_adapters.py","tests/test_intent_guardian.py"); [compile(ast.parse(Path(path).read_text(encoding="utf-8"), filename=path), path, "exec") for path in paths]; print("AST_COMPILE_OK", len(paths))'` → exit 0；`AST_COMPILE_OK 6`。
- `git diff --check` → exit 0；无输出。
- `python3 -c 'import hashlib,subprocess,sys; from pathlib import Path; expected=set(("scripts/kb/resource_adapters.py","scripts/kb/intent_guardian_parts/resources.py","scripts/kb/local_file_operations.py","scripts/kb/command_template.py","tests/test_resource_adapters.py","tests/test_intent_guardian.py","guardian-r2-program/reports/H04-typed-resource-adapters.md")); brief="guardian-program/briefs/H04-typed-resource-adapters-repair3.md"; tracked=subprocess.run(["git","diff","--name-only"],capture_output=True,text=True,check=True).stdout.splitlines(); untracked=subprocess.run(["git","ls-files","--others","--exclude-standard"],capture_output=True,text=True,check=True).stdout.splitlines(); actual=set(tracked+untracked); digest=hashlib.sha256(Path(brief).read_bytes()).hexdigest(); ok=(actual & expected)==expected and actual-expected=={brief} and digest=="7a37c1e0aa1176598a4b9fb462a9ba366d7314425f68cc45bbd0b7224c384ecd"; print("SCOPE_OK 7; BASELINE_BRIEF_OK 1" if ok else "SCOPE_MISMATCH"); print("\\n".join(sorted(actual & expected))); sys.exit(0 if ok else 1)'` → exit 0；`SCOPE_OK 7; BASELINE_BRIEF_OK 1` 并列出精确七 owned paths。唯一额外 untracked task brief SHA-256 与 task binding 的 `7a37c1e0aa1176598a4b9fb462a9ba366d7314425f68cc45bbd0b7224c384ecd` 一致，不是 candidate 写入。
- `python3 -c 'from pathlib import Path; import sys; marker=Path("guardian-program/briefs/H04-typed-resource-adapters-repair3.md").stat().st_mtime_ns; bytecode=sorted(path for path in Path(".").rglob("*") if path.is_file() and path.suffix in {".pyc",".pyo"}); new=[path for path in bytecode if path.stat().st_mtime_ns >= marker]; print(f"NEW_BYTECODE_OK {len(new)} new; {len(bytecode)} inherited-before-repair3"); print("\\n".join(str(path) for path in new)); sys.exit(0 if not new else 1)'` → exit 0；`NEW_BYTECODE_OK 0 new; 6 inherited-before-repair3`。六个 ignored `.pyc` 均早于 repair3 brief，遵循“do not clean”而保留。

实际 changed paths：`scripts/kb/resource_adapters.py`、`scripts/kb/intent_guardian_parts/resources.py`、`scripts/kb/local_file_operations.py`、`scripts/kb/command_template.py`、`tests/test_resource_adapters.py`、`tests/test_intent_guardian.py`、`guardian-r2-program/reports/H04-typed-resource-adapters.md`。

## 遗留风险与建议

- 仅验 POSIX/macOS 临时 Git；Windows、live host、安装、H05/H06 与 release gate 不在范围。
- Figma/device external current world/readback 由未来 host adapter 提供；真实 unresolved writes 继续 fail closed。
- commit/merge/delete 只在 canonical 临时 fixture；生产仓、dev/main、共享 index 与真实数据未写。
- FR2-H04-007 仍 open：installed-runtime Guardian 的 patch destructive misclassification 未由 candidate code 与 executed regression 修复；H06/system acceptance 应增加该回归。
- worktree 继承 6 个 repair3 前生成且 ignored 的 `.pyc`；本轮没有新增，也因禁止 clean 与七路径 freeze 未删除。

## 沉淀候选

问题语境一：跨平台测试把 `TemporaryDirectory().name` 当 canonical identity；macOS `/var`→`/private/var` 会让合法正例变成 lexical alias。证据状态：`observed`（coordinator 10 errors + 2 failures；repair3 fixture readback 与 22/22）。

- 夹具正例：先 `Path(temp.name).resolve()`，再从该根创建 repository/delete/artifact。预期 strict classifier 接受。
- 夹具反例：直接拼接未 resolved 的 temporary name，或为了让测试过而在生产入口先吞掉 lexical alias。预期前者跨机失败，后者禁止采纳。

问题语境二：canonical resource digest 正确但授权消费层不比较 H01 capability/effect，或 hook 不携 exact constraints/current world，会形成“类型存在、权限未闭合”。证据状态：`observed`。

- 路由正例：linked `git status` 得 Git identity；`git -C <exact-other> status` 得单 repository Workspace；终态 Figma debt 不污染 local patch。预期 apply。
- 路由反例：`git add -A`、main write、direct `.git`、workspace sibling、Figma empty target、device purchase/data clear。预期 deny。
- 执行正例：authority/dispatch 逐字段匹配，前置重分类，后置独立 readback，verifier 不可复用。预期 pass。
- 执行反例：只核 resource id、省略 ledger、artifact digest 无 artifact path、terminal quarantine 全局阻断。预期 fail。
