/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06B-codex-0150-authority.json

# H06B — repair2：最终报告与并发生产证据归因闭环

你是 `guardian-r2-worker-h06b`。在同一隔离 full clone、同一 repair1 候选上
继续。本次使用新的 immutable run slug
`r2-h06b-codex-0150-authority-repair2`，只允许重写已 owned 的
`guardian-r2-program/reports/H06B-codex-0150-authority.md`；七个代码/测试输出
必须保持字节不变。不得 reset、commit、install、push、merge、访问网络、调用
Claude、操作 scheduler/生产 KB 或修改 `dev/main`。

## 冻结权威

- frozen base: `e9afaac7b6126ba2c1ccec16ac9a3367f9863820`
- task-definition SHA-256:
  `c5082ba58a0f4336087b9cb24b48434ae053c757d75003b2f3ce1c7fd8b24020`
- original brief SHA-256:
  `22975aea47b7bddbbcbbbf64ad940a240e7d99d69e20b693ce3d5a5d346a1328`
- repair1 brief SHA-256:
  `972cfbc248f5c2c5dbf2993f4e7ddc0ad525f38d7bc2d3a706399bc8e422746c`
- repair1 wrapper SHA-256:
  `e4b86cc8dd9675130049ef2b29a3fab911c85e9bc0656b187ab468976995af4b`
- repair1 managed run terminal:
  `status=success rc=0 duration=1168s`，随后明确输出
  `RESTORED codex-cli 0.150.1`。
- 只读控制投影现在为四个：task definition、original brief、repair1 brief、
  本 repair2 brief。它们不是任务输出。

## 协调器已验证、可直接写入报告的最终证据

### 真实 0.150.1 完整 authority roundtrip

wrapper 恢复后，协调器在 full clone 运行：

`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v tests.test_agent_runtime.AgentRuntimeTests.test_audited_codex_0150_real_cli_contract`

结果：exit 0，1 test in 2.647s，`OK`；候选 stager 生成 605 文件并验证
366 篇知识文档；临时 marketplace、KB、deployment 形成完整 authority，staged
runtime 通过 `load_installed_native_authority()` 回读同一对象并交给 preflight；
重新签名的 broker digest 漂移被物理文件复核 fail closed。没有生产安装。

### repair1 formal 运行一

cursor:
`/private/tmp/sulde-h06b-repair1-formal-cursors.An5fq9`

同一 8 模块单层命令运行 495 tests in 223.734s，`OK (skipped=1)`，exit 0；
唯一 skip 是 native Windows PowerShell。process guard 没有观察到测试子进程的生产
KB 写入，但在 verified read-only boundary 后检测到无关外部会话对三个 intent
文件的并发更新。因此这是测试通过证据，不是 quiet fleet-safe 证据。

### repair1 formal 运行二

cursor:
`/private/tmp/sulde-h06b-repair1-quiet-formal-cursors.eJVZpy`

同一 8 模块单层命令运行 495 tests in 226.579s，`OK (skipped=1)`，exit 0；
唯一 skip 仍是 native Windows PowerShell。process guard 仍证明测试子进程零生产
写入，但外部会话在窗口内提交 native decision/receipt/head，故也不是 quiet
fleet-safe 证据。

### FR2-H06B-005 的精确归因

只读控制调查将 writer 归因到独立 Codex session
`019fee8b-bcad-7623-be8e-dd3743f69039`，workspace
`/Users/eric/iquokkaApp/iquokka-harmony`，任务为 HarmonyOS IAP 中文错误提示；
其 active intent 为 revision 75/enforce，09:05–09:06 的 approved proposal native
transaction 从 approval_decided 依次推进至 committed，并继续产生 live-verified
Hook 事件。该会话不是 H06B worker，未改 H06B clone；协调器没有中断、暂停或杀掉
用户的无关任务。此 finding 保持显式并转交新的最终 H06 successor，在 fleet safe
point 取得 quiet formal/install/live 同 generation 证据。

## 报告修复要求

保持且只保持六个二级标题顺序：

1. `## 结果`
2. `## 过程`
3. `## 遇到的问题`
4. `## 解决方式`
5. `## 遗留风险与建议`
6. `## 沉淀候选`

必须做到：

1. 将 post-repair real positive 与两次 495-test 结果写成协调器证据，明确执行主体、
   cursor、计数、耗时、唯一 skip、process guard 零测试写入与外部并发警告。
2. 不把并发警告描述为 H06B 代码失败，也不把它删掉或写成 guard clear。
3. FR2-H06B-001、002、004 在 H06B 候选中 fixed current；FR2-H06B-003 由
   source/time 分段和独立三路复审在当前报告中 fixed current；FR2-H06B-005 保持
   transfer/open，等待最终 H06 fleet-safe 验收。
4. 明确七个代码/测试文件未变，报告是第八个 owned output；列出四个只读控制投影。
5. 明确 H06B 仅准备由协调器接受任务范围，不是 H06/program/release accepted。
   最终 installer rollback、scheduler、Codex live、Claude live、native Windows、
   同 generation、I01-I19 与 13 failure axes 全部仍是新最终 H06 successor 的硬门槛。
6. 继续保留沉淀候选：时间上下文误归因、关键 shared contract 显式 digest，以及
   “并行活跃宿主会污染全局生产快照；最终验收必须由 fleet safe point 协调”的问题卡。

## worker-safe 验证

- 不运行 real CLI、不运行 formal、不运行 installer/stager 全套。
- 运行 `git diff --check`、七个代码/测试 blob 与 repair1 前快照一致、八 owned
  outputs 加四控制投影精确 scope、AST compile、零 pyc。
- 对最终报告运行 `task_report_verdict`，必须 `passed=true` 且无 failure reason。
- 完成后自然结束，不 commit、不安装。
