## 结果
✅ LIFE-P0 报告收尾竞态、复合命令效果分类与 lane 自锁回归通过：`/usr/bin/env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests /Users/eric/.sulde/data/kb/venv/bin/python -B -m unittest tests.test_agent_runtime tests.test_command_policy tests.test_intent_guardian`，exit 0；Ran 361 tests in 92.539s，OK (skipped=17)，覆盖报告稳定读回、引号/注释/解释器源码参数、真实 shell 执行边界、可信运行器诊断、非法组合拒绝和真实破坏性暂停；candidate_sha256=c7e881abdcf5b7897b9046ac58efb1a0a870908e7d125a7f88c76020ed202409；execution_binding_sha256=bc8106eef11688d7accf985f53772f7ed84250dc7a32e859c05f940074670160；environment_sha256=cb1a4ed90d98d010c332b6047365021d9c9ca97b9337fb45c93cc411fd5456f3；command_sha256=76a4d65a5b8592d851a6c28b0a4703eef8f51cd3d74ce868c25c58d4f14f4370；count=361
✅ clean commit 的隔离候选整链验收通过：`python3 scripts/release/candidate_codex_plugin.py --candidate-home /Users/eric/.sulde/candidates/codex --json verify life-p0-control-3329ec6`，exit 0；status=verified，verify_total=18600.061ms，artifact、isolated registry、6 个真实 Hook、PreTool 双代际 denial、MCP、doctor 与 scheduler entrypoint 均返回受支持证据；candidate_sha256=c7e881abdcf5b7897b9046ac58efb1a0a870908e7d125a7f88c76020ed202409；execution_binding_sha256=bc8106eef11688d7accf985f53772f7ed84250dc7a32e859c05f940074670160；environment_sha256=868f63cea546bc6a4a06b59bedd8317d0912094601652eefdfbcb83163439d45；command_sha256=8f6a599d20a74d1ec5fd1696b91582306eeb0d2b6f0307a81197dff22bab582f；count=1

## 过程
- `agent-runtime.py` 仅在 provider final 与 durable report 的最终权威闭合边界提供 200ms 有界重读；首次读取固定根、父目录与文件身份，只有同一文件在界内变成 canonical bytes 且连续两次版本稳定才可结算。持久不一致、路径替换、符号链接、父目录漂移、读中修改和匹配后再改写继续 fail closed，运行器不会重写 durable report 来制造一致。
- `resources.py` 先按真实 shell 执行边界提取负向证据。单引号、注释、普通 argv、Python `-c` 源码里的 `rm -rf` 只是数据；顺序、条件、管道、后台段、命令替换、反引号、进程替换或直接调用里的真实 `rm` 仍分类为 destructive。
- 可信脚本带额外 shell 组合时，语法无效与物质效果身份分离：无破坏性证据的组合为 unknown，生成 `invalid-composition` 并在执行前拒绝，但不暂停健康 lane；含真实破坏性段时维持 destructive、deny 与 safety pause。
- 只有 launcher snapshot 中摘要固定、路径固定、解释器固定的已安装 `agent-runtime.py` 的 `--help`、`verify --help` 或结构正确的 verify 诊断可成为 read；候选同名脚本、run 动作、相对 worktree、非法 slug、未知参数都不能获得只读权威。
- candidate_sha256 来自按路径排序的 6 个源码/测试文件“路径 + 内容 SHA-256”规范 JSON 清单，不含报告和临时控制文件。环境摘要绑定 base commit、Python 3.10.7 真实解释器、macOS arm64、`PYTHONDONTWRITEBYTECODE=1` 与 `PYTHONPATH=tests`。
- 官方候选工具从 clean commit `3329ec6785a4e87867ee2e0d0be2d477b47c9e7c` 构建隔离 generation `0.2.5+codex.20260904062410-ee5ad4b306:3db13f345210a912b19b456e8456d72ad3866615e63616448d7f654433a02159`；prepare 2468.43ms，verify 18600.061ms，production deployment/launcher/scheduler owner 的 prestate 摘要保持不变。

## 遇到的问题
- 生产旧代运行器的两次受管执行都在写测试资料时触发安全停止：第一次把 `python -c` 源码参数中的删除命令样本当成执行，第二次把传给 patch 的补丁正文当成执行。两条旧 ledger 与各自 denial 原样保留；候选实现、协调端复核与本报告没有改写这些历史事实。
- 第一轮留下的 13 项聚焦通过记录与 R1 的解析器候选分别复用，协调端补齐真实 normalization/GuardianSession 正反例后执行 20 项聚焦回归，再按影响范围执行 361 项模块全测；没有重复仓库全量测试。
- 一次静态检查入口生成了 3 个 `.pyc`；精确只读定位后通过 `git clean -fdX --` 仅清理两个任务 worktree 缓存目录。最终候选不含 `__pycache__` 或 `.pyc`，后续语法检查改用内存 `compile()`。
- 候选 verifier 按设计不写正式 `deployment-generation.json`；通用 L3 运行器因此拒绝把隔离 registry 冒充正式部署。该尝试没有进入当前成功证据，也没有通过手工 descriptor 绕过。当前 system evidence 使用官方 candidate verification receipt `8b9f8321e9c88f6aacc77841e673181db024830174c4822dfaa02e9c13a01ce5`。

## 解决方式
- 将“命令不可组合”建模为 invocation violation，将“存在真实破坏性原语”建模为 effect；策略仅在后者或其他既有 safety 条件成立时暂停 lane。
- 新增生产形状的 Python 源码写入、printf/rg 数据、注释、嵌套引用，以及 `;`、`&&`、`||`、管道、后台执行、命令/进程替换正反例；同步更新旧断言，不再把 `touch` 或未知 formatter 冒充 destructive。
- 报告闭合保留 descriptor-relative、无符号链接和单硬链接约束，并在短窗口内固定首次身份；稳定匹配后才写 `.last.md`，随后再次回读 durable report 验证版本未变。
- 受影响的 `test_agent_runtime`、`test_command_policy`、`test_intent_guardian` 三个模块在同一候选字节上全部通过；`git diff --check` 无输出。

## 遗留风险与建议
- 生产代际仍运行旧分类器，因此正式安装之前的含删除样本测试会继续触发旧安全停止；发布阶段应使用已验证的候选 receipt，并在正式切换后以新代际重放同一命令和报告闭合 canary。
- shell 是开放语法；本实现的执行段解析只用于证明负向 destructive 证据，不授予 read 或写权限。无法完整解析的组合继续维持 unknown/deny，不得通过解析缺口获得执行权。
- 本任务范围没有改动生产插件、scheduler、intent/effect 日志、dev、main 或其他 worktree；安装、集成合并和 P1B 复验由后续依赖阶段处理。
