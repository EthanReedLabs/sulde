# T31 Codex 0.149.1 exact host audit

## 结果

✅ 完成检查：`scratch="$PWD/.codex-agent/.native-command-scratch"; env TMPDIR=/private/tmp CODEX_HOME="$scratch/codex-0149-1-real-test" PYTHONPATH="$PWD" T31_REAL_ONLY=1 python3 "$scratch/t31-agent-runtime-suite.py"`，exit 0；真实 audited symlink 精确报告 `codex-cli 0.149.1`，top-level/exec/app-server help、strict profile、hook parse、app-server initialize 与 installed authority readback 两项测试均通过。

✅ 完成检查：`scratch="$PWD/.codex-agent/.native-command-scratch"; env TMPDIR=/private/tmp CODEX_HOME="$scratch/codex-0149-1-worker-r2" PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 python3 "$scratch/t31-agent-runtime-suite.py"; env TMPDIR=/private/tmp CODEX_HOME="$scratch/codex-0149-1-kbvenv-r2" PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 /Users/eric/.claude/plugins/data/sulde-cc/kb/venv/bin/python "$scratch/t31-agent-runtime-suite.py"`，exit 0；worker CPython 3.9.6 与 production KB venv CPython 3.10.7 各自 54/54 通过，覆盖 future version、substring、wrapper/path alias、help、profile、broker、generation、bounded initialize 与 provider-before-launch fail-closed。

✅ 完成检查：`scratch="$PWD/.codex-agent/.native-command-scratch"; env PYTHONDONTWRITEBYTECODE=1 python3 -c "import tempfile,unittest; tempfile.tempdir='$scratch'; suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_codex_plugin_install'); result=unittest.TextTestRunner(verbosity=1).run(suite); raise SystemExit(not result.wasSuccessful())"; env PYTHONDONTWRITEBYTECODE=1 /Users/eric/.claude/plugins/data/sulde-cc/kb/venv/bin/python -c "import tempfile,unittest; tempfile.tempdir='$scratch'; suite=unittest.defaultTestLoader.loadTestsFromName('tests.test_codex_plugin_install'); result=unittest.TextTestRunner(verbosity=1).run(suite); raise SystemExit(not result.wasSuccessful())"`，exit 0；worker CPython 3.9.6 与 production KB venv CPython 3.10.7 各自 39/39 通过，官方 staging fixture 验证 577 files/366 corpus documents，且 production-mode runpy 回归、post-seal bytecode fault injection、完整安装 smoke 与零 bytecode inventory 全部通过。

✅ 完成检查：`python3 scripts/release/stage_plugin.py --target codex --platform posix --output "$PWD/.codex-agent/.native-command-scratch/t31-official-stage-20260824084717"`，exit 0；真实官方 Codex staging 生成 `0.2.5+codex.20260824084717`，验证 577 files/366 corpus documents，runtime generation 为 `0.2.5+codex.20260824084717:dbeaf8ce5708729998ffd79cfc0a367e216476d9cad756146212ce1b22d84b39`，runtime tree 无 bytecode。

✅ 完成检查：`scratch="$PWD/.codex-agent/.native-command-scratch"; stage="$scratch/t31-official-stage-20260824084717/plugins/sulde"; env -u PYTHONDONTWRITEBYTECODE -u PYTHONPYCACHEPREFIX python3 -I "$scratch/t31-staged-import.py" "$stage/runtime/scripts/kb/agent-runtime.py"; test "$(find "$stage/runtime" \( -type d -name __pycache__ -o -type f -name '*.pyc' \) -print | wc -l | tr -d ' ')" = 0; echo staged_runtime_bytecode_entries=0`，exit 0；输出 `module_loaded codex-cli 0.149.1 dont_write_bytecode True` 与 `staged_runtime_bytecode_entries=0`。

实现候选只修改六个 owned paths；未执行 commit、push、生产安装、scheduler reload、dev/main merge、production contract/ledger 写入，也未修改 Codex executable、symlink、installed authority 或 marketplace 文件。worker scoped 实现与测试通过，但官方 OS-isolated 全量 gate 因当前外层 Seatbelt 拒绝 runner 的内层 `sandbox-exec` proof 而未闭合，因此本报告不声称 T31 已完成生产发布或 system_verified。

## 过程

- 从基线 `096226c1b70e3cde51f97906d45ff266ec25a0b8` 逐字审查协调端预置差异。预置的 exact `0.149.1` 版本替换方向与真实宿主一致，但 cachebuster 从基线 `0.2.5+codex.20260824123238` 回退到旧 `0.2.5+codex.20260824081304`，因此未采信。
- 对 `/Users/eric/.nvm/versions/node/v18.20.8/bin/codex` 做只读 identity 检查：它仍是指向 `../lib/node_modules/@openai/codex/bin/codex.js` 的原 symlink，lexical/resolved executable SHA-256 均为 `134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477`；任务结束前复读一致。
- agent-runtime 与 installer 继续共享一个精确常量 `codex-cli 0.149.1`，没有引入版本 family、patch range、substring 或 stderr 过滤。现有负例改为精确拒绝 `0.150.0`、`wrapper codex-cli 0.149.1`、`codex-cli 0.149.1 future` 以及 executable alias。
- F31-001 的补充实证把根因进一步收敛到 loader 时序：CPython 3.10.7 的 `SourceFileLoader.exec_module()` 会在 `agent-runtime.py` 模块正文执行前先写入口自身的 `agent-runtime.cpython-310.pyc`；因此即便正文第一段设置 `sys.dont_write_bytecode=True`，也无法阻止该入口 cache。后续 `_installed_runtime_tree_sha256()` 正确把新增字节判为 drift 并 fail closed。
- 保留 agent-runtime 在首个 installed sibling import 前设置 `sys.dont_write_bytecode=True` 与 `PYTHONDONTWRITEBYTECODE=1`，继续阻止 sibling imports 自缓存；installer fresh smoke 改用 `runpy.run_path()` 执行入口，避免 importlib loader 在正文前缓存入口本身。
- installer post-seal smoke 仍显式移除 `PYTHONDONTWRITEBYTECODE`/`PYTHONPYCACHEPREFIX` 环境帮助，以 `python -I` 执行 installed agent-runtime；生产态从 runpy namespace 真实调用并逐字比对 `load_installed_native_authority()`，随后重新验证 delivery generation/tree。测试态只声明 module import 证据，不把 fake Codex authority 冒充生产 authority。正常安装与 durable recovery postcondition 都执行该 smoke。
- 新增 production-mode loader-order 回归：fixture 中的 authority 只能由 installed entrypoint 内的 `load_installed_native_authority()` 返回；worker 3.9.6 与 production KB venv 3.10.7 均通过，且调用后 runtime tree 无 `__pycache__`/`.pyc`。
- 在 scratch official stage 上用 production KB venv 生成真实 exact-0.149.1 native authority 并执行新的 smoke，结果 `authority_load_verified=true`、`loaded_by` 指向 staged `runtime/scripts/kb/agent-runtime.py`、authority SHA-256 为 `29a84a07c39e2ee6d24d027a7cfb815874fa2bd5702c8fca4df4e9c797f93979`，且 `bytecode_entries=[]`。
- 新增故障注入：runner 在 fresh load 后写入 `__pycache__/agent-runtime.cpython-313.pyc`，installer 必须因 `plugin tree contains executable Python bytecode` 拒绝；完整 fake installer 同时断言返回证据与 installed runtime bytecode inventory 为零。
- 按 `plugin-creator` 官方 `update_plugin_cachebuster.py` 默认 UTC helper 生成唯一新版本 `0.2.5+codex.20260824084717`；没有手改或调用任何 marketplace 写流程。

## 遇到的问题

- 当前受管 shell 的外层策略最初不允许 Codex 创建 PATH helper aliases，导致真实 `--version` 附带 `WARNING: ... Operation not permitted`。精确合同正确拒绝 stdout+stderr 的额外字节，不能通过过滤 stderr 解决。
- 将 `CODEX_HOME` 放在批准 scratch 且让 `TMPDIR` 指向其外部后，同一 audited executable 能创建自己的 helper alias 并精确输出版本；真实合同测试随后通过。没有修改 executable/symlink 或全局配置。
- 直接运行 owned unittest modules 时，外层策略拒绝测试在 worktree 根或系统 temp 创建 fixture；改由只调整 `tempfile.tempdir`/`temporary_directory()` 的批准 scratch runner 执行，测试源码与产品代码不为宿主限制降级。
- `plugin-creator` 自带 `validate_plugin.py` 在当前系统 Python 中因缺少 PyYAML 无法启动；没有为此安装全局依赖，改由仓库官方 staging validator 与完整 installer tests 验证 manifest/artifact。
- 知识库 CLI 因隔离 bootstrap 的 venv 缺失无法搜索；按仓库规则降级读取当前 knowledge `INDEX.md`，未发现可直接采用的 bytecode/native-authority 专项条目。
- `SULDE_AUDIT_CURSOR_HOME="$PWD/.codex-agent/.native-command-scratch/t31-audit-cursors" python3 scripts/kb/run-isolated-tests.py` 在测试 discovery 前 exit 3：外层 Seatbelt 拒绝 runner 再调用 `sandbox-exec`，原始证据为 `sandbox_apply: Operation not permitted`。
- 为校准产品回归，在批准 scratch 的真实 `.git` full clone 中使用 runner 的 `isolated_environment()` 执行 single-layer full discovery；1365 tests 中 1320 通过、6 跳过、3 failures、36 errors。失败来自 clone 无远端 `main`、缺 numpy/PyYAML、Python 3.9 API 差异、Xcode system-temp cache 与非 owned `.codex-agent/interventions` 写入被外层策略拒绝等非 T31 环境项。该运行未计为通过证据。

## 解决方式

- 保留 exact lexical executable、exact version、exact help observation、profile spec、broker digest、runtime generation 与 authority hash 的现有多重绑定，只把经真实 0.149.1 探针验证的精确版本同步到两端。
- 用两层互补防护覆盖完整时序：`runpy.run_path()` 避开 entrypoint pre-body cache，入口正文 guard 阻止后续 sibling imports；不在发现 `__pycache__` 后清理 sealed runtime，独立 load 后的任何 tree drift 仍触发 rollback。
- production smoke 必须从 runpy namespace 调用 installed entrypoint 的真实 `load_installed_native_authority()` 并与 sealed payload 全等；测试 fake authority 只获得 `module_load_verified=true`、`authority_load_verified=false`，避免 synthetic evidence 升格。
- 使用官方 cachebuster helper、官方 stager、真实 staged fresh-import 与两个完整 owned-module suites 构成 worker evidence；对官方 isolation bootstrap 冲突保留 fail-closed 状态并移交协调端。

## 遗留风险与建议

- 协调端必须在没有外层 nested-sandbox 冲突的 full clone 上独立运行 `python3 scripts/kb/run-isolated-tests.py`，并要求完整 suite exit 0；在此之前不得把 candidate 标为 system_verified。
- 后续 dev/main merge、官方 installer 的生产发布、`com.sulde.kb-aging`、15/15 scheduler generation、restart 后真实 Sulde Codex hooks/doctor/final-check 均属于协调端任务，本 worker 未执行也未声称完成。
- 发布时应复读 audited symlink、resolved executable SHA、exact `codex-cli 0.149.1`、help observation SHA、native authority 与 runtime generation；任何一项变化都应停止发布，不应扩大为版本 family。
- `plugin-creator` validator 的 PyYAML 依赖未封装是工具环境风险，但本候选已由仓库官方 stager/installer 路径验证；建议工具维护者为 validator 提供自包含依赖或明确 venv 入口。

## 沉淀候选

### Layer1 问题卡：authority verifier 的导入可自污染 sealed runtime

- **问题类型**：post-seal mutation / fail-closed self-poisoning
- **问题语境**：Python 入口位于 digest-bound installed runtime 内，installer 使用 `spec_from_file_location(...).loader.exec_module(...)` 做 post-seal fresh-process smoke，并依赖入口正文再关闭字节码。
- **已确认根因**：CPython importlib loader 可在入口正文执行前缓存入口自身，正文 guard 对该 `.pyc` 生效过晚；正文开始后的 sibling imports 则仍需 guard。authority loader 后续严格 tree digest 正确拒绝这些新增字节，因此 isolated install 会回滚，生产 authority 也会 fail closed。
- **证据状态**：verified。production KB venv CPython 3.10.7 的 runpy production smoke 真实加载 staged authority 且 bytecode inventory 为零；注入一个 post-seal `.pyc` 时 installer 定向测试必然拒绝；双解释器 agent-runtime 54/54、installer 39/39 通过。
- **路由正例**：任何从 immutable/digest-bound Python tree 直接启动且启动后还会自验 tree digest 的入口，都应在首个本地 import 前禁止 bytecode，并由 installer 做 fresh-process post-seal load/readback。
- **路由反例**：普通可写开发 checkout、pycache 位于外部受控 prefix 且不参与 authority digest、或根本没有 sealed-tree identity 的工具，不应机械套用此发布门。
- **执行合格例**：installer 用不预缓存入口的执行路径启动，入口再前置 `sys.dont_write_bytecode` 覆盖 sibling imports；清除环境帮助后独立调用真实 authority loader、全等比较 authority、复验 generation/tree，mutation 则 rollback。
- **执行失败例**：安装成功后再删除 cache、把 `__pycache__` 从 digest 中静默排除、只在父进程设置环境变量、或测试态把 fake authority 标记为生产 load verified。
- **建议容器**：anti-patterns。
