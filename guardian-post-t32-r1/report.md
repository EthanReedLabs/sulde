# guardian-post-t32-r1 实施与验收记录

## 冻结结论

- 本批次仍只有 R1-0、R1-A、R1-B、R1-C 四条工作流，没有创建新任务编号。
- 唯一 bootstrap worktree 是 `.worktrees/r1-git-lifecycle-bootstrap`；没有第二次例外。
- revision 128 只纠正 Codex plugin manifest 路径。早先的 revision 129 安装 grant 因错绑主工作树而被原生卡明确拒绝，没有应用、没有写 manifest。
- revision 129 发布桥已由 receipt `410b99ff381d821fadef6265984b00be4762ede787f7ece65ed5a0edcf97a409` 批准；首个 15 文件提交 `95e7d21f9c7b8dee2e1fe62174fda0d1508b3728` 已通过测试并 fast-forward 到 dev。
- revision 130 的精确删除卡虽获批准，旧运行时仍在执行前把 shell `rm` 无条件升级为 destructive；直接执行和外部 Terminal 内嵌执行均被阻止，没有删除内容。
- revision 131–133 将清理改为可恢复隔离：main 11 个、dev 4 个、task 4 个 ignored 纯 bytecode 目录共 19 个，全部逐项移动到 `.tmp/guardian-post-t32-r1-pycache-quarantine/`；三工作树完整枚举为零，Git 树不变。
- revision 134 将 release 全套暴露的两个超限组件拆回 3000 行以内，把 NativeAgentBroker fixture 改为真实 full-clone 形状，并校正新增结构化 Git profile 后的 command-effect 计数；未放宽生产 linked-worktree 拒绝策略。
- revision 135 通过 birth time 与提交时刻精确对齐，确认后续 2 个 bytecode 目录由仓库 pre-commit 的三个 Python lint 调用生成；已冻结无字节码环境修复、回归测试与两个可恢复移动，当前三工作树再次枚举为零。
- revision 134 已形成普通提交 `78f1282047f0968c7b4d5be3b4f06b5b8b7aaf2a`，父提交和 8 个路径与冻结卡一致；提交实际执行修复后的 pre-commit 后，源码树没有重新生成 bytecode。
- revision 135 已形成普通提交 `12adf93fa452e851a3a8ca860b2ef09651c929d0` 并 fast-forward 到 dev。官方隔离全套 1381 项只失败 1 项：新测试的 text subprocess 未显式固定 UTF-8 解码边界；生产代码、hook 行为及其功能回归均通过。
- revision 136 只在该 `subprocess.run` 补 `encoding="utf-8"`、`errors="replace"`；静态文本门禁与 lint 模块合计 4/4 通过，未修改 hook 或生产源码。
- revision 136 尾提交 `31e0c90848c7d3f82df6273acfdd2b8fd74e7eef` 已通过 dev 官方隔离全套 1381/1381（6 skip）和 launcher 23/23，并 fast-forward 到 main。
- revision 137 使用官方 helper 生成版本 `0.2.5+codex.20260825052334-9d641410e5`，manifest-only release commit `a6b8b63579eff393f5b23d95dec45fd33b0cb1d2` 已进入 main/dev；install 在 PreToolUse 前被旧 Guardian 拒绝，没有产生插件、registry、cache、launcher 或 scheduler 写入。
- revision 138 只修复该 install grant 的 tracked-tree 摘要自锁；提交 `327a302841ccfdd4512a3d1c413b8ba808cdbce0` 已通过 dev 官方隔离全套 1383/1383（6 skip）并进入 main/dev。
- revision 139 是唯一生产发布卡：官方 helper 和事务安装生成 `0.2.5+codex.20260825054856-106736206d`，release commit `7d642bbaf31715e3c2006c94a539fa4c4820e583` 已进入 main/dev/task；15 个 Codex jobs 已重载到同一 generation。
- 重启后的真实 `SessionStart`、`UserPromptSubmit`、Pre/Post tool roundtrip 已使 operational readiness 全部为 true；R1-C 不再有未完成门禁。

## 已解决问题

### R1-0：Git 生命周期 bootstrap 自锁

- `agent-runtime.py` 新增结构化 `provision`、`commit`、`merge`，每个动作绑定精确仓库、worktree、ref/SHA 和内容路径。
- provision 只允许从精确 `dev` 基线创建仓内 `.worktrees/<task>`，禁止 force/remove/prune，且要求 primary/dev 清洁。
- commit 绑定父提交、暂存树、精确路径和单行消息；禁止额外 staged、unstaged、untracked 内容。
- merge 只允许 task→dev、dev→main 的精确 fast-forward，并在共享 common-dir 锁下串行。
- `launcher_contract.py` 将该入口纳入 digest-pinned command-effect snapshot；Guardian 消费结构化内容 targets，未开放通用 `.git` 路径权限。

### R1-A：历史 effect 与 native recovery 自锁

- 历史 attempt 缓存没有 `replay_authoritative=true` 时，只允许追加 `abort` 终态；retry/reprobe 继续拒绝。
- abort 不伪造旧外部操作成功或失败，原 attempt 真值保持 `unknown`。
- native recovery 按 transaction 独立处理；单项失败形成确定证据并继续后续已批准事务。

### R1-B：Git 100644 导致完成证据假失败

- 新增 completion permissions 物化器：先验证整个 evidence/snapshot/prepared 集合，再把文件 0644 收紧为 0400、目录 0755 收紧为 0700。
- 校验 owner、文件类型、硬链接、symlink、路径边界、JSON 绑定和内容 SHA；任何一项失败时不执行任何 chmod。
- 因而 Git fresh clone/worktree 的规范 100644 不再直接判失败，最终 immutable 完成态仍严格要求 0400。

### R1-C 前置：拒绝不应制造无意义暂停

- 实测官方 cachebuster helper 省略显式 token 时，旧运行时把同名维护脚本降为 destructive，虽未执行仍暂停整条 lane。
- 新规则只识别“无 shell 组合、官方 helper 绝对路径、规范 Sulde plugin root、确实存在 manifest”的省略-token 形状；固定 `deny + pause=false`，不产生 open event 或 pending verification。
- 该规则不授予执行权；显式 proposal-bound token 和精确 grant 仍是执行前提。
- 真实 `rm -rf`、脚本漂移、替代 helper、shell 组合和非法 argv 继续走原 destructive 安全门。

### R1-C 前置：人类批准的精确 shell 删除不可达

- 根因不是用户未授权：旧归一化器把所有 shell `rm` 直接标为 generic destructive，而既有人工删除辅助函数只接受 `tool:apply_patch`，原生卡即使同时批准 `local_write`、`destructive` 和全部路径也无法命中允许分支。
- 新规则只识别单条 literal `rm`、固定 `r/f` 参数、现存普通文件或目录、无 symlink/通配/变量/组合/路径穿越的精确目标，并规范化为 `local_write + destructive_local_operation +` 逐路径 delete operation。
- 只有同一份原生人类卡同时具备双效应、精确 allowlist、有效 proposal digest 和 receipt 才允许；回执缺失或路径越界固定拒绝但不暂停，真正通用 destructive 仍 hard deny 并 safety pause。
- completed 回调允许已删除目标不存在，但保留 dispatch 的绝对目标和 operation 形状，避免成功删除后产生事件配对债务。

### R1-C 前置：pre-commit 自己污染 release closure

- `a96f057` 的提交时刻与 `sedimentation_schema.pyc` 的创建时刻一致，随后 `build-index-md.py` 导入链生成 `common/corpus_manifest/memory.pyc`；调用链唯一落在 `hooks/git-precommit/check_kb_lint.sh`。
- hook 的三个校验器都是只读，但此前未导出 `PYTHONDONTWRITEBYTECODE=1`，导致一次合法提交立刻制造 launcher release gate 禁止的 derived bytecode。
- hook 现在统一导出无字节码环境；临时 Git 仓库加 Python shim 的回归证明三个校验调用都收到该变量，lint 顺序、内容、跳过条件和失败策略不变。

### R1-C 发布：future content 与 index blob 双重绑定自锁

- r137 grant 以未来 manifest 字节覆盖计算得 `aefa3a1c…`，但仍把 `git ls-files --stage` 的旧 blob object id 纳入同一摘要；manifest 提交后，工作树字节完全相同，摘要却变为 `3c552b8a…`。
- 因而冻结的“先创建 manifest-only release commit，再安装”顺序在旧算法下必然失败：提交会改变 index object id，而安装器实际消费的只是工作树字节。此次拒绝发生在 PreToolUse，官方安装脚本未启动。
- r138 将 tracked metadata 规范化为 Git mode 与 stage，继续逐路径哈希工作树字节和全部 explicit release inputs；object id 只做格式校验，不进入摘要，任何非零 stage 固定 fail closed。
- 回归证明未来 override、`git add` 和 commit 后摘要一致；未审查内容、mode、新 tracked path、explicit release input 或冲突 stage 仍会改变摘要或拒绝。r139 必须在 helper 后、manifest commit 前用旧运行时消费新 grant，安装成功后再提交 manifest，从而完成无手改 installed cache 的 bootstrap。

## 测试与发现

- 任务分支 9 个相关模块完整套件：490/490 通过，使用生产 KB venv并设置 `PYTHONDONTWRITEBYTECODE=1`。
- launcher 完整套件：23/23 通过，包括 snapshot interpreter/script/argv 绑定、Git 生命周期精确 targets、bytecode 发布门和漂移 fail-closed。
- 先前两次 22/23 不是测试逻辑失败：launcher 发布门分别正确发现 dev 和 task worktree 的历史 ignored `__pycache__`。最初按局部目录扫描遗漏 task 的 `tools/kb-index` 与 `tests`；改为 main/dev/task 三工作树完整枚举后，共 19 个目录可恢复隔离，重跑全套后没有重新生成 bytecode。
- shell 删除新增正反回归覆盖 Bash 与 Codex `exec_command`、started/completed 形状、回执缺失、越界、shell 组合、glob、symlink、路径穿越和根目录删除。
- 系统 Python 缺少 PyYAML 曾造成测试假失败；生产运行时使用 KB venv，因此发布验收固定使用同一 venv。
- linked worktree 的 `.git` 是指针文件而非目录；测试改为从 Git 查询 common-dir，避免平台/布局假设。
- Codex CLI 可能在 stderr 输出非致命 PATH alias 警告；版本预检改为绑定精确 stdout、可执行路径和摘要，不再把任意非空 stderr 当成版本失败。
- revision 134 精确回归 55/55 通过；组件行数为 `resources.py=2988`、`recovery.py=3000`，NativeAgentBroker 使用真实 full-clone fixture，plugin install command-effect 计数为 3。
- revision 135 的 sedimentation/pre-commit 模块 2/2 通过；缓存隔离后任务 scoped 490/490 通过，且测试和修复后的 hook 均未重新生成源码树 `__pycache__`。
- dev 首轮官方隔离套件运行 1381 项，结果为 1 failure、0 error、6 skip；唯一 failure 精确定位 `tests/test_lint_sedimentation.py` 的文本子进程参数。r136 补参后的失败门与受影响模块 4/4 通过。
- r136 合并后的 dev 官方隔离套件重跑 1381 项全部通过（6 skip），launcher release gate 23/23 通过；main/dev/task 均无源码树 `__pycache__`。
- r138 release-inventory 模块 9/9 通过；Guardian、grant 与 Codex installer 定向套件 234/234 通过；R1 scoped gate 加入新模块后 590/590 通过，且测试未生成源码树 bytecode。
- r138 集成后的 dev 官方隔离全套为 1383/1383（6 skip）；launcher 23/23、release inventory 9/9 和官方 manifest validator 全部通过。
- 生产安装通过官方 cachebuster/install 链完成，artifact generation 为 `0.2.5+codex.20260825054856-106736206d:19f35d14d2d378fd7cff6c8883a2ab6a73cc9703def9b423a31ff1b976738d48`，runtime tree 为 `19f35d14d2d378fd7cff6c8883a2ab6a73cc9703def9b423a31ff1b976738d48`。
- scheduler 权威探针为 15/15 loaded、missing `[]`、failed `{}`、retired loaded `[]`；`codex-harvest` 与 `status-notify` 的 LastExitStatus 均为 0。
- 当前 active contract 的 native decision pairing settled、pending verification 为 0、effect debt blocking 为 0；`model-dispatch --provider codex` 正常输出 Codex 原生 JSON。
- 结构化 Git lifecycle 与 historical attempt abort 的生产同构 canary 均通过；没有删除、重放或直接编辑历史账本。
- 首次在工具调用内部采样 readiness 时，状态投影尚看不到该调用自身的 PostToolUse，错误沿用上一笔 completed roundtrip，短暂报告 `prompt_control=unobserved`；直接账本已证明 `2026-08-25T06:26:11.954448Z` 的 live UserPromptSubmit 存在，待上一笔 roundtrip 闭合后复验得到 `interactive_status=live_verified` 与 `operational_readiness=ready`。

## 终态门禁（已闭合）

1. revision 138 提交 `327a3028` 已按冻结路径形成并进入 dev/main。
2. dev supported isolated full suite 1383/1383（6 skip）、launcher 23/23、manifest/release inventory 9/9 与三工作树 bytecode 枚举全部通过。
3. 唯一 r139 cachebuster/install 双 grant 已创建、独立校验并各消费一次；没有复用 r137 grant。
4. 官方 helper、事务安装、manifest-only release commit `7d642bba` 按冻结顺序完成；registry/cache/launcher 均由官方链写入。
5. installed-artifact smoke、scheduler/status、model-dispatch、当前 session hooks、historical abort 和安全 Git lifecycle canary 全部通过；operational readiness 为 ready，R1-C 关闭。

## 非 R1 阻断的全局观察项

- 当前 active contract/workspace 的 effect debt 为 0，scheduler 与 interactive readiness 均 ready。
- 全局聚合状态仍有 37 条 event-contract violation，57 个观测源中 46 个 healthy；这些来自跨 workspace/store 的历史事件投影，不是本 R1 当前 lane 的权限债务。
- 沙箱内状态探针无法读取 launchctl 和 0400 journal 时会制造假红；本次验收使用沙箱外只读权威探针纠正。全局事件合同清理和探针自观察时序作为后续候选，不在 r139 冻结范围内扩成新任务。

## 沉淀候选

### 候选 1：任务 worktree 规则与受保护 Git common-dir 形成 bootstrap 自锁

- 问题语境：仓库强制任务在 worktree 开发，但守卫永久禁止 `.git`，旧 agent-runtime 又只能消费已有 worktree。
- 证据状态：verified；生产仓库无法由协调端或 Dev provision，唯一一次精确 bootstrap 后真实临时仓库回归已通过。
- 路由正样本：必须 worktree、无受控 provision、普通 `git worktree add` 被阻止。
- 路由反样本：已有隔离 worktree 且只读查询可运行，不属于 bootstrap 自锁。
- 执行正样本：digest-pinned 结构化 provision，绑定 dev SHA、分支、仓内路径、清洁状态和一次性后置条件。
- 执行反样本：开放通用 `.git`、允许 force/remove/prune，或并发写 shared common-dir。
- 建议路由：anti-patterns；与 worktree/并行 Git 写既有条目判重后并入或系列新增。

### 候选 2：已被 PreTool 拒绝的无 token 维护调用被误升级为 destructive pause

- 问题语境：官方 cachebuster helper 的默认时间 token 无法在执行前绑定；旧分类回落为 destructive 并冻结 lane。
- 证据状态：verified；当前会话 sequence 36516 复现安全暂停，修复正反回归通过。
- 路由正样本：官方 helper、规范 plugin root、省略 token、进程未启动、拒绝后 lane 却暂停。
- 路由反样本：真实递归删除或脚本/路径漂移，仍应 hard deny 并可 safety pause。
- 执行正样本：独立 invocation-violation 路由，`deny`、`pause=false`、零效果债务。
- 执行反样本：把调用改成普通 local_write 后直接放行，或仍复用 destructive 枚举。
- 建议路由：anti-patterns；优先并入 `0243-control-composition-misclassified-as-destructive-pause` 的“密封条件违规”扩展。

### 候选 3：一次性安装 grant 绑定 active workspace 而非任务 worktree

- 问题语境：revision 129 在任务代码尚位于 linked worktree 时，自动 grant 固定到主工作树和旧 tracked-tree SHA。
- 证据状态：verified；可读卡明确显示 main manifest/root，且预计合并后 tree SHA 必然变化，因此已拒绝提案。
- 路由正样本：active contract root 与实际 release candidate worktree 不同，grant 仍静默绑定 active root。
- 路由反样本：最终 release tree 已稳定且 grant 的 workspace/manifest/tree 与实际执行完全一致。
- 执行正样本：在最终 tree 稳定后才生成一次性 grant，卡片显示实际 workspace 和未来 manifest 摘要。
- 执行反样本：在任务开发中提前生成 grant，或为图省事直接修改 main manifest。
- 建议路由：anti-patterns；与多 worktree authority/CAS 条目判重。若 installed live 仍有偏差则保持 `inconclusive` 并补证据。

### 候选 4：精确 shell 删除的人类授权在归一化层不可达

- 问题语境：原生卡已同时批准本地写、破坏性效应和精确路径，但 shell `rm` 在进入路径授权前被无条件归为 generic destructive；人工继续点击 Allow 也无法改变结果。
- 证据状态：verified；revision 130 的直接与外部 Terminal 两种执行均在进程启动前被拒绝，新增 started/completed 与正反边界回归通过。
- 路由正样本：单条 literal `rm`、精确现存普通文件/目录、无扩展语法，且当前人类 proposal/receipt 同时绑定双效应与全部路径。
- 路由反样本：glob、变量、组合、symlink、路径穿越、根路径、未知参数或缺失 receipt，均不得借精确删除通道放行。
- 执行正样本：先规范化为逐路径 typed delete，再执行 allowlist、冻结路径和原生 receipt 校验；完成回调保持同形。
- 执行反样本：在 effect==destructive 总分支后再检查人类授权，或仅凭一句“已授权”放开通用 shell。
- 建议路由：anti-patterns；与“控制面误分类为 destructive pause”判重后作为权限可达性子类收录。

### 候选 5：发布门按首个失败路径清理会形成重复假失败

- 问题语境：launcher 对 runtime 闭包中的任何 bytecode 都 fail closed，但最初只按错误消息和 `scripts/kb` 局部扫描，遗漏同一 task worktree 的 `tools/kb-index` 与 `tests`。
- 证据状态：verified；局部隔离后错误路径依次变化，完整 main/dev/task 枚举收敛到 19 个目录，随后 23/23 和 490/490 通过。
- 路由正样本：发布门报告一个 bytecode 路径，但门的真实不变量覆盖整个 runtime/worktree 闭包。
- 路由反样本：源代码或测试断言真实失败，不应归为环境残留。
- 执行正样本：先枚举完整门禁边界、分类 ignored 与 tracked 内容、一次形成精确可恢复处置清单，再重跑全套。
- 执行反样本：每看到一个失败路径就删除或追加一张授权卡，既慢又容易遗漏。
- 建议路由：anti-patterns；与发布工件污染/测试环境隔离条目判重。

### 候选 6：只读 pre-commit 与发布闭包门形成派生物自锁

- 问题语境：提交 hook 运行只读 Python lint，却在源码树写入 ignored bytecode；紧随其后的 launcher release gate 又正确拒绝任何 bytecode，导致“提交成功后验收必失败”。
- 证据状态：verified；提交时间、四个 `.pyc` birth time、hook 顺序和 Python import 链完全对齐，干净临时克隆中的普通测试不会复现。
- 路由正样本：只读 hook 启动解释器、未隔离 bytecode、发布闭包禁止 derived artifact。
- 路由反样本：测试显式使用 `PYTHONDONTWRITEBYTECODE`/`PYTHONPYCACHEPREFIX` 且源码树保持不变。
- 执行正样本：在 hook 边界统一导出无字节码环境，并用 shim 验证每个 Python 子调用继承；现存残留只做可恢复隔离。
- 执行反样本：每次提交后手工删除缓存，或放宽 release gate 接受 ignored bytecode。
- 建议路由：anti-patterns；与候选 5 判重后作为“生产者与门禁互相冲突”的根因补充。

### 候选 7：未来内容 grant 同时绑定旧 index blob 会在提交后自失效

- 问题语境：维护 grant 需要先审查未来 manifest 内容，再把同一内容提交并安装；摘要同时包含工作树字节和 proposal 时刻的 index blob object id。
- 证据状态：verified；同一未来字节在旧 index 上得到 `aefa3a1c…`，提交后得到 `3c552b8a…`，r137 install 在进程启动前精确复现 grant mismatch。
- 路由正样本：stager 消费工作树字节，未来 override 与提交后文件相同，但 index object id 因正常 add/commit 改变。
- 路由反样本：工作树内容、tracked path、Git mode、stage 或 explicit release input 真正漂移，仍必须让 grant 失效。
- 执行正样本：摘要绑定消费语义（path、mode、stage、实际字节），拒绝非零 stage；bootstrap 期间在未来内容已生成但 index 尚未切换时消费旧 runtime grant。
- 执行反样本：忽略整个 tracked tree、允许任意 tree digest 漂移，或直接手改 installed cache 绕过一次性 grant。
- 建议路由：anti-patterns；与多 worktree/CAS 条目判重后作为“授权摘要绑定历史表示而非消费语义”的子类收录。

### 候选 8：状态探针在自身 PostToolUse 前读取上一笔 roundtrip 产生瞬时假红

- 问题语境：真实 UserPromptSubmit 已写入可信账本，但 readiness 命令本身正处于 PreToolUse→PostToolUse 中间；投影只能取上一笔已完成 roundtrip，并据此把新 prompt 排除。
- 证据状态：verified；账本存在 `06:26:11.954448Z` 的 current-runtime/current-session prompt，首次探针误报 unobserved，任一后续工具 roundtrip 闭合后同一探针转为 live_verified/ready。
- 路由正样本：prompt 时间晚于上一笔 completed roundtrip、当前探针已有 PreToolUse 但尚无 PostToolUse，直接账本与投影结论冲突。
- 路由反样本：账本确实没有 current-runtime/current-session prompt，或已有 Stop 晚于 prompt；此时必须保持未就绪。
- 执行正样本：投影识别当前在途只读 readiness probe，或披露 `pending_current_roundtrip` 并在闭合后自动复检；不得把一拍延迟解释为 Hook 丢失。
- 执行反样本：伪造 prompt 观测、要求用户反复重启/输入，或绕过 interactive gate 直接标记 ready。
- 建议路由：anti-patterns；与宿主自观察/CAS 自引用条目判重后并入，后续源码修复须单独冻结。
