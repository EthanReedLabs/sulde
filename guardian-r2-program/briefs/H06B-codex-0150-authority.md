/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06B-codex-0150-authority.json

# H06B — 统一 Codex 0.150.1 原生执行权威

## 身份与边界

- task-id: `H06B-codex-0150-authority`
- frozen base: `e9afaac7b6126ba2c1ccec16ac9a3367f9863820`
- provider: Codex only；不得调用或依赖 Claude Code。
- 仅允许修改任务定义中的八个 `owned_paths`。只读 task/brief 投影不属于任务输出。
- H06B 因与旧 H06 的 installer 路径冲突而在任务图中形式化 supersede 旧 H06；这不代表 release acceptance。协调器会在 H06B accepted 后登记新的最终 H06 successor。
- 禁止安装、调度器变更、生产 KB 写入、网络、push、merge、commit、删除既有工件或修改 `dev/main`。
- 编辑只用原生 `apply_patch`；测试使用 `PYTHONDONTWRITEBYTECODE=1` 与 `python3 -B`。

## 必须解决的根因

当前 global Codex 是 `codex-cli 0.150.1`，但 `agent-runtime.py` 与 installer 各自硬编码 `0.149.1`，导致真实 CLI 正例和最终安装 authority fail closed。不得只把两处字符串机械改成新版本；同一根因已跨 runtime、installer 和测试复发，必须形成共享真值和机械防复发守卫。

1. 新建 `scripts/kb/codex_cli_contract.py`，作为生产唯一真值，至少导出精确 audited executable、`codex-cli 0.150.1` 和稳定的版本身份辅助；保持 import 只读、零环境/文件副作用。
2. `scripts/kb/agent-runtime.py` 与 `scripts/release/install_codex_plugin.py` 必须从共享模块导入同一 authority，不再定义生产版本副本；错误信息从共享值派生，禁止残留误导性的 `0.149.1` 文案。
3. 统一版本观察语义：版本身份取成功命令的精确 stdout；stderr 诊断不得污染版本值。help authority 继续绑定三份完整 stdout+stderr，任何 diagnostic/help bytes drift 均 fail closed。
4. `scripts/release/stage_plugin.py` 必须把未提交的新共享模块纳入窄 `REQUIRED_RUNTIME_SOURCE_FILES`，让候选阶段的 staging/installer 测试与最终 tracked artifact 同构。
5. 在三份测试文件中覆盖：
   - 共享值为精确 `codex-cli 0.150.1`，runtime 与 installer 身份一致；
   - staged runtime 包含共享模块，已安装 runtime 可导入；
   - real CLI positive 使用真实 0.150.1 production authority；
   - 0.149.1、future、substring、executable alias、help diagnostic、generation/profile/broker/tree drift 全部 fail closed；
   - installer smoke、authority readback 和 rollback 保留 exactly-once/恢复不变量；
   - 机械扫描测试保证生产 audited-version literal 只存在于共享模块，测试 fixture 可显式保留旧版本负样本。
6. 不得降低 exact-version、executable digest、help observation、strict profile、app-server initialize、runtime generation/tree 或 broker authority 中任何一项。

## 必跑验证

先运行窄测试，再运行受影响组合；managed worker 不得在外层 Seatbelt 内嵌套 formal runner。协调器会在候选后独立运行单层 formal suite。

- 共享合约、runtime real/synthetic CLI、installer native authority、stage inventory 与 rollback 聚焦测试。
- `tests.test_agent_runtime`、`tests.test_codex_plugin_install`、`tests.test_stage_plugin` 的受影响集合。
- `git diff --check`、八路径精确 scope、AST compile、零 `.pyc`。
- 故意提供旧 0.149.1、future/substring、别名 executable 与 help stderr drift，确认负样本实际判红；不得通过适配测试绕过 production path。

## 报告契约

必须写 `guardian-r2-program/reports/H06B-codex-0150-authority.md`，且恰好包含以下六个二级标题并按顺序出现：

1. `## 结果`
2. `## 过程`
3. `## 遇到的问题`
4. `## 解决方式`
5. `## 遗留风险与建议`
6. `## 沉淀候选`

每条当前成功检查用 `✅ 完成检查：\`<精确命令>\`，exit 0；<可观察结果>`。历史失败只引用 append-only finding，不把历史非成功退出状态复制成当前检查。报告必须明确：

- `FR2-H06-001` 的代码候选是否已解决，以及真实 0.150.1 authority 证明边界；
- 发现了什么、根因是什么、解决了什么；
- exact changed paths、测试数、负样本、worker 限制；
- 未安装、未修改生产、未触碰 `dev/main`；
- H06B 不是 H06/program/release accepted，最终 installer rollback、scheduler、Codex/Claude live、Windows 与同 generation 仍由新 H06 successor 验收。

## 结束条件

完成代码、测试和六段报告后自然结束；不 commit、不 push、不 install。任何 owned-path 外修改、production write、测试适配绕过或无法证明的结果都必须报告为未完成。
