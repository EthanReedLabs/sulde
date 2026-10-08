/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06G-release-inventory-authority.json

# H06G repair1 — 关闭 unknown 与 canonical alias 注入

## Frozen continuation

- 沿用 H06G task definition、base `f0e845617867c1710b636205c6798d03140d1646` 与五个 exact owned paths。
- 这是 run1 的原任务返修，不新建任务、不丢弃 run1 与 H06F 失败证据；不得 commit、install、改 scheduler/生产 KB、push、merge、调用 Claude 或修改 control projection。
- 保持 `PYTHONDONTWRITEBYTECODE=1`、`python3 -B`；编辑只用 `apply_patch`。

## Independent blocking finding

`FR2-H06G-001` 已由协调端登记。run1 两侧只做 `len(tuple) == len(set(tuple))` 的词法去重，独立真实临时 Git 攻击证明：

- 向 tuple 注入存在的 `scripts/kb/hostile-unknown.py` 后，Guardian 成功生成 64 字符授权 digest；
- stager 接纳该未知 regular file，真实 `copy_entry` 把 `HOSTILE=True` 复制到 artifact runtime；
- 注入 `scripts/kb/alias-parent/../approval_timeout_policy.py` 后，词法 set 认为不同，但 Guardian 仍授权，stager inventory 对同一 resolved source 计数为 2。

因此 run1 只关闭 exact duplicate，没有满足 frozen exact allowlist、unknown input、canonical alias 与 duplicate physical resource 在 hash/copy/grant 前 fail closed。静态 tuple 对比测试不能替代生产入口验证。

## Required repair

1. Guardian 与 stager 各自使用不可由待验证 tuple 派生的冻结八项 canonical allowlist；入口第一步验证当前 tuple：
   - 每项为平台正确的 `Path` 类型；
   - 必须是规范相对路径，拒绝 absolute、空/`.`、任何 `..`、alias；
   - 内容与顺序逐项精确等于冻结八项；
   - 词法和规范/物理身份均不得重复。
2. 验证必须发生在 `git ls-files`、`git_entries`、SHA-256、lstat、copy 或 maintenance grant 之前；失败只返回明确 domain error，不触达下游。
3. 新增两侧真实生产入口 hostile tests，至少覆盖：
   - exact duplicate；
   - 存在的 unknown regular file；
   - `..` canonical alias 指向同一物理文件；
   - reorder；
   - absolute path；
   - parent-directory symlink alias。
4. 测试不得 mock 被测 validator/digest/copy；可以把下游 Git/hash/copy 入口设为 fail-fast sentinel，以证明无触达，但还必须至少用真实临时 Git/真实文件与真实入口证明 unknown/alias 被拒绝且 artifact 未产生。
5. 保留 run1 已通过的八项逐输入 digest/copy、tuple 外 unknown 忽略、final symlink/nonregular/missing/nonzero stage、maintenance one-shot/cachebuster 以及 installer 回归。
6. 报告追加 repair1，明确 run1 为什么被独立攻击打回、红灯与绿灯、真实 unknown/alias 产物证据、命令/退出码/计数；只能声明候选等待协调端，不得声明 task_verified、accepted、安装或 R2 完成。

## Verification

- 先在旧 run1 实现上取得 unknown regular 与 `..` alias 两侧均被接纳的红证据，再修复转绿。
- 重跑 focused hostile matrix、`tests.test_stage_release_inventory`、`tests.test_stage_plugin`、五项 maintenance/cachebuster 与 `tests.test_codex_plugin_install`。
- 最终 effective diff 仍精确等于原五个 owned paths；task/brief control projection hash 不变；无 pyc、无生产写。
