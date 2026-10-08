/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06G-release-inventory-authority.json

# H06G — release inventory authority superseding repair

## Frozen authority

- base：`f0e845617867c1710b636205c6798d03140d1646`。
- provider：Codex deep/high only；不得调用 Claude。
- H06G 追加式 supersede 已 blocked 的 H06F；不得直接复用或改写 H06F 报告，需在本任务五个 exact paths 中独立重建候选。
- 不得 commit、install、改 scheduler/生产 KB、push、merge 或触碰 dev/main；`PYTHONDONTWRITEBYTECODE=1`、`python3 -B`，编辑只用 `apply_patch`。

## Accepted diagnosis

- `FR2-H06E-004`：stager 的显式 runtime tuple 已包含 `scripts/kb/codex_cli_contract.py`，Guardian maintenance authorization tuple 漏项。
- `FR2-H06F-001`：H06F 虽补齐 tuple 并逐输入验证 digest，但重复路径负样本只是当前态静态断言；独立攻击向真实 stager tuple 注入重复项后得到 `DUPLICATE_INJECTION_COUNT=2`。H06F 报告还越权声称 task completion/acceptance。

## Required repair

1. Guardian tuple 按 stager 稳定顺序精确补齐 shared contract；Guardian 在任何摘要/授权处理前拒绝重复显式路径。
2. stager 在任何 inventory copy/hash 处理前拒绝 `REQUIRED_RUNTIME_SOURCE_FILES` 中的重复路径；不得依赖最终 set 或覆盖去重。
3. 测试必须 hostile patch 两侧 tuple 注入重复项，并分别调用真实 Guardian digest 与真实 stager inventory 入口，断言明确失败；不得 mock 被测 validator/digest/copy 实现。
4. 保留并强化：8 个输入逐个扰动均改变授权 digest、恢复后回到基线；unknown 未跟踪路径不进入授权；symlink、non-regular、tracked duplicate、缺文件与 stage allowlist 均 fail closed。
5. 报告只可声明“候选实现完成/等待协调端复审”，禁止使用“任务完成”“task acceptance”“accepted”；记录 H06F 被打回、红绿证据、命令/退出码/计数、skip 和未安装/未完成 R2。

## Verification

- focused hostile duplicate + exact tuple/every-input digest。
- affected：`tests.test_stage_release_inventory`、`tests.test_stage_plugin` 与相关 cachebuster/workspace digest tests。
- task report 必须通过 worker schema；effective diff 精确等于五个 owned paths；无 pyc、无 authority control projection 修改。
