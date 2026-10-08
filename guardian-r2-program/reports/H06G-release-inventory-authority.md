## 结果

H06G 候选实现完成/等待协调端复审。本报告仅陈述五个 owned paths 内的候选代码、测试与静态证据，不外推协调端状态，不声称已安装、发布或完成 R2。

### run1 历史证据

run1 证据绑定 `.codex-agent/r2-h06g-release-inventory-run1.events.jsonl`，SHA-256 `aed0294e17fbd8a1db2d34e6330f4fa0a89d38f3c27f8e54bc6cfb4f45bde19d`：`item_29` 为 focused 4 tests/exit 0，`item_32` 为 affected 26 tests/exit 0/Windows skip 1，`item_36` 为 maintenance/cachebuster 5 tests/exit 0，`item_37` 为 installer 41 tests/exit 0，`item_40` 输出 `STAGER_COUNT=8 GUARDIAN_COUNT=8 UNIQUE_COUNT=8 ORDER_MATCH=true`。这些是历史事件引用，不作为当前可执行命令。

### repair1 历史证据

run1 因 `FR2-H06G-001` 的独立真实攻击被打回。repair1 证据绑定 `.codex-agent/r2-h06g-release-inventory-repair1.events.jsonl`，SHA-256 `9b6f794a0064aec6efd218fc34f3c94eca51544cde52d6a834d88c7281619aed`：`item_12` 的真实临时 Git 红灯输出包含 Guardian unknown/parent alias `DIGEST_LENGTH=64`、stager `ARTIFACT_TEXT=HOSTILE=True` 与 `SAME_PHYSICAL_COUNT=2`；`item_18` 为 hostile focused 4 tests/exit 0；`item_24` 的真实 green harness 输出 `GREEN_GUARDIAN_REJECT_COUNT=3 GREEN_STAGER_REJECT_COUNT=3 ARTIFACT_COUNT=0`；`item_20`、`item_21`、`item_22` 分别为 26/5/41 tests、均 exit 0。repair1 两条不可执行占位符已移除，以上均为历史事件精确回读，不伪装成当前 `✅` 命令。

### repair2

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v tests.test_stage_release_inventory.ReleaseInventoryTests.test_hostile_allowlists_fail_before_filesystem_or_downstream_touch tests.test_stage_release_inventory.ReleaseInventoryTests.test_real_unknown_and_alias_attacks_create_no_artifact tests.test_stage_release_inventory.ReleaseInventoryTests.test_authorization_digest_covers_every_explicit_release_input tests.test_stage_plugin.StagePluginTests.test_required_runtime_source_inventory_is_exact_and_unique`，exit 0；4 tests 全部 `OK`。hostile matrix 覆盖 exact duplicate、unknown、`..` alias、reorder、absolute、parent symlink alias、wrong type 与 empty；两侧明确断言 `os.lstat`/`os.readlink` 调用为 0，Guardian Git/hash 与 stager Git/hash/copy/prepare_output 调用亦为 0；真实临时 Git/文件攻击保持无 sentinel 且 artifact=0。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v tests.test_stage_release_inventory tests.test_stage_plugin`，exit 0；26 tests 全部 `OK`，native Windows PowerShell 条件项 skip 1；unknown、tracked duplicate、symlink/non-regular/missing、nonzero stage、staging allowlist 与 8 项逐输入 digest/copy 回归均通过。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v tests.test_intent_guardian.IntentGuardianTests.test_human_readable_plugin_maintenance_grants_are_ordered_and_one_shot tests.test_intent_guardian.IntentGuardianTests.test_v2_release_requires_install_before_scheduler_and_launcher_binding tests.test_intent_guardian.IntentGuardianTests.test_v2_install_wrapper_is_one_shot_and_near_misses_fail_closed tests.test_intent_guardian.IntentGuardianTests.test_cachebuster_continuation_requires_exact_manifest_and_tree_proof tests.test_intent_guardian.IntentGuardianTests.test_cachebuster_continuation_closes_with_system_verification`，exit 0；5 tests 全部 `OK`，maintenance 顺序、one-shot、workspace digest 与 cachebuster 无回归。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v tests.test_codex_plugin_install`，exit 0；41 tests 全部 `OK`，仅使用临时夹具，stage artifact/native inventory/rollback 通过，未执行真实安装。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -c 'import json; from pathlib import Path; from tests.test_agent_runtime import load_runtime_module; m=load_runtime_module(); report=Path("guardian-r2-program/reports/H06G-release-inventory-authority.md").read_text(encoding="utf-8"); brief=Path("guardian-program/briefs/H06G-release-inventory-authority-repair2.md").read_text(encoding="utf-8"); verdict=m.task_report_verdict(report,m.report_contract_for_brief(brief)); print(json.dumps(verdict,ensure_ascii=False,sort_keys=True)); assert verdict["passed"] and not verdict["failures"]'`，exit 0；输出 `{"check_count": 5, "failures": [], "passed": true, "schema": "sulde-worker-report-v1"}`，strict schema failures=0。

## 过程

- 冻结 base 保持为 `f0e845617867c1710b636205c6798d03140d1646`；四份 control projection 的 SHA-256 保持为 task `15439b6f52b0d62f078c58fd1333558362d621fc591b8d1d982041bc90ebae2b`、run1 brief `37f7ca134cf496cccf91b730d220f5889e638fe419f8ab0bec76b65961d7727c`、repair1 `e7a380ae2ebaf392f866255377f444c1b703d5dac106ec2b84a0e8d240bfefd3`、repair2 `66906542c668e9e8a0d72fe8a7b5edd37399e96593b7245a54fd01be17f80135`，均为只读 control projection。
- H06F 已被协调端打回；其重复路径负样本只验证静态当前态，真实 tuple 注入仍返回两份同路径 inventory，且报告越过候选边界。本任务没有复用或改写 H06F 报告，而是在 H06G 五个 exact paths 内独立重建。
- 修复前红证据命令为 `set +e; PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v tests.test_stage_release_inventory; red_status=$?; set -e; printf 'BASELINE_RED_STATUS=%s\n' "$red_status"; test "$red_status" -eq 1`，exit 0；可观察到 9 tests 中 exact tuple 对比不一致，包装输出 `BASELINE_RED_STATUS=1`。随后真实入口 hostile injection harness 自身 exit 0，观察到 Guardian 未拒绝重复 tuple，且 `STAGER_DUPLICATE_INJECTION_COUNT=2`。
- 修复后 Guardian 按 stager 稳定顺序补齐 `scripts/kb/codex_cli_contract.py`；两侧入口均先保存 tuple 快照并检查唯一性，再开始 Git 枚举、摘要、inventory copy/hash 相关处理。
- 8 个显式输入逐个改变内容时授权 digest 均变化，每次恢复原字节后均回到同一基线；新增 unknown 未跟踪文件不改变授权 digest。
- repair1 红灯在修改前取得：unknown 被 Guardian 绑定进 64 字符授权 digest，并由 stager 的真实 `copy_entry` 写出 `HOSTILE=True`；`scripts/kb/alias-parent/../approval_timeout_policy.py` 与 canonical 路径指向同一 resolved source，Guardian 仍授权，stager inventory 计数为 2。
- repair1 修改后，Guardian digest、stager `release_entries` 以及 `stage_claude`/`stage_codex` 均先验证当前 tuple；staging 入口在 `prepare_output` 前验证，因此 hostile tuple 不会创建 artifact 目录。
- repair2 将纯内存 exact tuple/order 比较移到所有 resolve/physical topology 探针之前；只有 frozen tuple 精确匹配后，才运行 resolved identity duplicate 与越界保护。
- run1 的八项逐输入 digest/copy、tuple 外 unknown 忽略、final symlink/nonregular/missing/nonzero stage、maintenance one-shot/cachebuster 与 installer 证据全部保留并重跑。
- repair2 final scope gate 以 task `owned_paths`、`git status --porcelain=v1`、四份 control SHA-256、base HEAD、四个 Python AST、全树 pyc、五条 `✅` 命令及 report contract 作机械对比，exit 0；输出 `BASE_MATCH=true EFFECTIVE_OWNED_COUNT=5 CONTROL_COUNT=4 CONTROL_UNCHANGED=true AST_COUNT=4 PYC_COUNT=0`、`REPORT_CHECK_COUNT=5 REPORT_PLACEHOLDER_COUNT=0 REPORT_FAILURE_COUNT=0 REPORT_HEADING_COUNTS=1`、`REPORT_PROHIBITED_TERM_COUNT=0`。

## 遇到的问题

- 工程知识库 CLI 因受管临时环境缺少其 venv 无法启动；按仓库规则降级读取 `knowledge/INDEX.md` 与 `anti-patterns/0220-recency-overrides-standing-instructions.md` 全文，采用其逐项对表与禁止越权外推原则。
- 首轮 hostile Guardian 测试 patch 了 facade 导出的常量，而真实 digest globals 属于 `intent_guardian_parts.state`，因此没有形成真实攻击；随后改为 patch 函数定义模块的 tuple，生产 digest 本身未被 mock。
- native Windows PowerShell 在当前 macOS 宿主不可用，affected suite 中对应既有平台测试 skip 1 项；其余 Windows artifact staging 测试实际通过。
- run1 的 `len(tuple) == len(set(tuple))` 只检查词法重复：unknown 值仍可进入 tuple，含 `..` 的不同词法值也可解析为同一文件，因此静态 tuple 对比不能证明生产入口 fail closed。
- `FR2-H06G-002`：repair1 的 exact tuple gate 位于 `root.resolve()`/`Path.resolve()` 之后，独立 `os.lstat` fail-fast 攻击让 unknown/reorder 先触发 filesystem sentinel；旧报告关于 source lstat 零触达的表述缺少对应守卫。
- `FR2-H06G-003`：repair1 两条 `✅` 使用不可执行占位符，字面执行与报告的 exit/output 不一致；真实结果实际保存在 repair1 events 的 `item_12`/`item_24`。
- 受管 shell 禁止 heredoc；第一次 shell `apply_patch` 因无法创建 heredoc 临时文件返回非零状态，且未产生修改，随后改用标准输入管道调用同一 `apply_patch` 完成编辑。

## 解决方式

- `state.py` 的显式授权 tuple 现与 stager 的 8 项 allowlist exact、unique、stable-order 一致；`_workspace_tracked_tree_sha256` 在运行 Git 枚举或摘要逻辑前拒绝重复显式路径。
- `stage_plugin.py` 的 `release_entries` 在运行 `git_entries` 或处理任何 required source 前拒绝重复路径，不依赖 set/覆盖行为消除攻击输入。
- hostile tests 只 patch 两侧生产 tuple，并分别调用真实 digest 与真实 inventory 入口；没有 mock 被测 validator、digest 或 copy 实现。既有 symlink、non-regular、missing、tracked dedupe、nonzero stage 和 artifact allowlist 反样本继续执行。
- 全程使用 `PYTHONDONTWRITEBYTECODE=1` 与 `python3 -B`；未 commit、push、merge、install，未修改 scheduler、生产知识库、Git metadata、dev/main 或 authority control projection。
- Guardian 与 stager 各自保留一份独立字面量冻结八项 canonical allowlist；待验证 tuple 不能生成或改写冻结真值。validator 依次执行类型、absolute/空/`..`、词法 duplicate、纯内存 exact tuple/order gate；仅 exact match 后才执行 resolved identity duplicate 与越界保护。
- Guardian 失败统一返回 `IntentGuardianError`，stager 失败返回带 `invalid required runtime source allowlist` domain 前缀的 `ValueError`；在错误前不运行 Git 枚举、SHA-256、source `lstat`、copy 或 maintenance grant。
- hostile matrix 仅 patch 待验证 tuple；validator、digest 与 copy 实现未被 mock。Guardian 对 `os.lstat`、`os.readlink`、Git、SHA-256，stager 对 `os.lstat`、`os.readlink`、Git、SHA-256、copy、prepare_output 使用 fail-fast sentinel 并逐项断言 call count=0；另有不设 sentinel 的真实临时 Git/真实文件/真实 stage 入口验证 artifact 数为 0。

## 遗留风险与建议

- 本候选仍需协调端独立复审 effective diff、worker report 与 release-level gate；H06G 状态迁移不属于 worker 权限。
- native Windows PowerShell 路径本轮仅保留既有 skip，建议协调端在 Windows 验证环境补跑对应平台项。
- 当前未安装候选，也未执行 scheduler/生产知识库变更；R2 尚未收口，不能由本报告推导 release 或 program 结论。
- repair2 最终 scope/schema/命令审计已由本轮本地 gate 机械核对；协调端仍需独立复核，worker 不迁移 H06G 状态。
