/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06G-release-inventory-authority.json

# H06G repair2 — 关闭 pre-lstat 顺序与证据占位符

## Frozen continuation

- 沿用 H06G task definition、base `f0e845617867c1710b636205c6798d03140d1646`、五个 exact owned paths 及 run1/repair1 全部证据。
- 不新建任务、不扩路径；不得 commit、install、scheduler/生产 KB 写、push、merge、调用 Claude 或修改 task/brief control projection。
- 保持 `PYTHONDONTWRITEBYTECODE=1`、`python3 -B`，编辑只用 `apply_patch`。

## Independent blocking findings

### FR2-H06G-002

repair1 两侧 validator 在 frozen exact tuple 比对前调用 `root.resolve()` 与 `Path.resolve(strict=False)`。独立把 `os.lstat` 设为 fail-fast sentinel 后，Guardian/stager 的 unknown 与 reorder 四次均先抛 `AssertionError: os.lstat reached`，而不是 domain error。现有 sentinel 只守 Git/hash/copy/prepare_output，报告“source lstat 未触达”过强。

### FR2-H06G-003

repair1 durable report 两条 ✅ 检查使用不可执行占位符：

- `python3 -B -c '<real temporary Git + tuple-patch red harness>'`
- `python3 -B -c '<real temporary Git + unknown/alias green harness>'`

字面执行均为非零、stdout 为空且 SyntaxError，却被写成 exit 0 与具体输出。真实结果存在 repair1 events 的 item_12/item_24，但报告未用可执行回读命令或摘要绑定。

## Required repair

1. 两侧 validator 在类型、absolute/空/`..`、词法 duplicate 检查后，立即用纯内存逐项/顺序比较 `current_tuple == frozen_exact_tuple`；unknown、reorder、缺项、额外项必须在任何 `root.resolve`、`Path.resolve`、`os.lstat`、`readlink` 或其他文件系统探针前返回 domain error。
2. 只有 exact-match frozen tuple 才允许后续 canonical/physical topology 检查；保留 resolved identity duplicate/越界保护，但不得把它冒充无效 tuple 的第一道 gate。
3. 扩充 hostile sentinel：对 unknown、reorder、absolute、`..` alias、parent symlink alias 与 wrong type，至少同时守 `os.lstat`、readlink、Git、hash、copy、prepare_output；两侧均证明 invalid tuple 的 filesystem/downstream touch 为 0。
4. 保留不设 sentinel 的真实临时 Git/文件攻击与 artifact=0，以及 repair1 全部 focused/affected/maintenance/cachebuster/installer 回归。
5. 报告追加 repair2，并修正 repair1 两条占位符：
   - 可移除 ✅ 形式，改为历史叙述并精确引用 repair1 item；
   - 或使用真实可执行 `jq -e` 回读 item_12/item_24，并绑定稳定事件/receipt SHA。
   禁止任何不可执行占位符作为 ✅ 实际命令。必须由独立字面执行验证命令、exit 与输出一致。
6. 报告仍只声明候选等待协调端；记录 FR2-H06G-002/003、修复顺序、命令/退出码/计数及 Windows skip，不声称 task_verified/accepted/install/R2。

## Verification

- focused 必须新增 pre-lstat/readlink 顺序攻击并转绿。
- 重跑 `tests.test_stage_release_inventory`、`tests.test_stage_plugin`、五项 maintenance/cachebuster、`tests.test_codex_plugin_install`。
- 对报告每条 ✅ 命令做可执行性/占位符审计；strict schema failures=0。
- effective diff 仍精确五个 owned paths；四份 control projection（task、run1 brief、repair1、repair2）hash 不变；无 pyc、无生产写。
