/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06F-release-inventory-authority.json

# H06F — release authorization inventory repair

## Frozen authority

- base：`f0e845617867c1710b636205c6798d03140d1646`。
- provider：Codex deep/high only；不得调用 Claude。
- 只允许修改 task definition 中三个 exact paths；不得 commit、install、改 scheduler/生产 KB、push、merge 或触碰 dev/main。
- `PYTHONDONTWRITEBYTECODE=1`、`python3 -B`；编辑只用 `apply_patch`。

## Confirmed failure

协调端在 1556 项 isolated campaign 中确认 `tests.test_stage_release_inventory.ReleaseInventoryTests.test_authorization_digest_covers_every_explicit_release_input` 确定性失败：

- `scripts/release/stage_plugin.py::REQUIRED_RUNTIME_SOURCE_FILES` 已包含 `scripts/kb/codex_cli_contract.py`；
- `scripts/kb/intent_guardian_parts/state.py::EXPLICIT_RELEASE_RUNTIME_INPUTS` 未包含它；
- 因此维护授权 digest 没有绑定 stager 实际消费的完整显式输入。

该 finding 已登记为 `FR2-H06E-004`。不要修改 stage inventory 来让测试变绿；shared contract 是 H06B/H06E 所需的真实 runtime 输入。

## Required repair

1. 使两个 exact tuple 完全一致，保持顺序稳定、路径唯一、无 glob/目录/未知输入。
2. 强化现有测试：不仅比较 tuple，还逐一变更每个显式 runtime 输入并证明 `_workspace_tracked_tree_sha256` 改变；不得只抽样第一个元素。
3. 增加或保持重复路径、未知路径不进入授权输入的负样本；测试不得通过 mock 绕开真实 digest 路径。
4. 报告记录失败、根因、修复、命令/退出码/计数、skip 与未安装/未完成 R2。

## Verification

- focused：`tests.test_stage_release_inventory.ReleaseInventoryTests.test_authorization_digest_covers_every_explicit_release_input` 及新增负样本。
- affected：`tests.test_stage_release_inventory` 与相关 workspace digest tests。
- task report 必须通过 worker report schema，effective diff 精确等于三个 owned paths。
