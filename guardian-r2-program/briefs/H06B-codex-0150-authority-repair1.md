/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06B-codex-0150-authority.json

# H06B — repair1：完整 native authority 往返与报告真值闭环

你是 `guardian-r2-worker-h06b`。在同一隔离 full clone、同一未提交 H06B
候选上继续，不得 reset、丢弃或重建现有候选。本次必须使用新的 immutable run slug
`r2-h06b-codex-0150-authority-repair1`；原始 run 及其失败事实只作为历史证据。

## 冻结权威与边界

- task-id: `H06B-codex-0150-authority`
- frozen base: `e9afaac7b6126ba2c1ccec16ac9a3367f9863820`
- task-definition SHA-256:
  `c5082ba58a0f4336087b9cb24b48434ae053c757d75003b2f3ce1c7fd8b24020`
- 原始 brief SHA-256:
  `22975aea47b7bddbbcbbbf64ad940a240e7d99d69e20b693ce3d5a5d346a1328`
- 仅允许修改原任务八个 `owned_paths`。本 repair brief、原 brief 与 task
  definition 是只读控制投影，不是任务输出。
- 保留当前生产代码候选；独立复审对共享合约、runtime、installer、stager 的
  production logic 给出 conditional PASS。除非补强测试暴露真实缺陷，不得无关重写。
- 禁止 commit、push、install、scheduler/生产 KB 写入、网络、Claude、Windows、
  删除工件、修改 `dev/main` 或扩大 authority。
- 当前 managed worker 启动期间会由可逆 wrapper 临时投影 `codex-cli 0.149.1`。
  因此 worker 内不得把 real 0.149.1 观察当作当前宿主结论，也不得重跑依赖真实
  0.150.1 的正例。协调器已在 wrapper 外取得权威正例。

## 必须关闭的四条 finding

### FR2-H06B-001 — 时间上下文误归因

现有报告把 wrapper 有意临时投影的 0.149.1 写成 wrapper 退出后的当前宿主状态，
并推导出虚假的 `HOST_MISMATCH`。重写报告时必须使用以下已验证时间线：

- wrapper:
  `/private/tmp/sulde-codex-01491.8Oc2Dm/run-h06b-with-audited-codex.zsh`
- wrapper SHA-256:
  `f37886d9cd684c166af605587133d37ecd07e6c7b9228a863e9006958cfe2ddd`
- 初始全局 Codex 为 0.150.1；worker 启动前临时投影 0.149.1；EXIT trap 输出
  `RESTORED codex-cli 0.150.1` 并校验恢复；之后协调器再次从精确 audited
  executable 回读 0.150.1。
- 删除当前报告中的 package/native mismatch、当前宿主仍为 0.149.1、npm
  缓存推测及由此产生的 H06B-F01 阻断结论。历史错误判断不得伪装为当前事实。

### FR2-H06B-002 — 真实正例缺少完整 authority roundtrip

当前 `test_audited_codex_0150_real_cli_contract` 只构造含 help hash 的局部字典，
没有证明生产同构链。补强测试必须在临时目录中完成以下完整往返，且不得安装到
生产路径：

1. 使用候选 stager/installer 构造候选 staged runtime；
2. 使用当前精确 audited executable 的真实 0.150.1 version/help/app-server
   观察生成完整 native runtime authority；
3. 写入临时 deployment/generation 描述，authority 必须包含并绑定 executable
   lexical/resolved path 与 digest、三份完整 help stdout+stderr digest、strict
   profile、app-server initialize、agent/broker/shared-contract digest、runtime tree
   digest、runtime generation；
4. 从临时 staged candidate 的 `agent-runtime.py` 调用
   `load_installed_native_authority()` 回读并校验同一完整 authority；
5. 将该完整回读对象传给 `codex_capability_preflight()`，真实 0.150.1 正例通过；
6. 至少一个 authority 字段漂移负样本必须在同一链中 fail closed。

可以把生产同构 roundtrip 放在 `tests/test_codex_plugin_install.py`，并让
`tests/test_agent_runtime.py` 的 real positive 消费其生成物/共用测试辅助；不能再用
局部手造字典替代 `load_installed_native_authority()`。worker 内只运行不依赖真实
0.150.1 的合成部分；真实正例由协调器在 wrapper 恢复后执行。

### FR2-H06B-003 — 报告结构绿但语义来源错误

六段报告必须把每个结论绑定到执行主体和时序：worker temporary projection、
wrapper restore、coordinator post-restore real positive、coordinator formal suite
不得混写。结构 parser 通过不等于语义通过；报告必须明确记录独立 code、test、
report 三路复审及其处置。不得宣称 H06/program/release accepted。

### FR2-H06B-004 — literal guard 范围不足

将机械守卫从 `scripts/**/*.py` 扩大为 repository-wide **production source** 扫描。
至少覆盖 tracked/untracked candidate 中的 `scripts/`、`hooks/`、`integrations/`、
`tools/`、`commands/` 生产文本源，按明确文本后缀读取；允许唯一生产命中
`scripts/kb/codex_cli_contract.py: codex-cli 0.150.1`。tests、fixtures、docs、
knowledge、guardian reports/briefs/task definitions 是负样本或历史证据，不得计为
生产 literal。测试必须注入另一个生产根/非 Python 文本副本，证明守卫实际判红。

## 已授权引用的协调器证据

- wrapper 外真实正例：精确 audited executable 输出 `codex-cli 0.150.1`，
  `test_audited_codex_0150_real_cli_contract` 通过。该结果属于 repair 前证据；补强
  roundtrip 后协调器会重新运行，不得预先宣称新测试通过。
- 单层 formal：
  `SULDE_AUDIT_CURSOR_HOME=/private/tmp/sulde-h06b-formal-cursors.oJx72v /Users/eric/.claude/plugins/data/sulde-cc/kb/venv/bin/python -B scripts/kb/run-isolated-tests.py tests.test_intent_guardian tests.test_intervention tests.test_agent_runtime tests.test_native_decision_journal tests.test_operational_readiness tests.test_sulde_statusline tests.test_codex_plugin_install tests.test_stage_plugin`
- repair 前结果：495 tests in 205.109 seconds，`OK (skipped=1)`；唯一 skip 是
  native Windows PowerShell；未出现 production-write 或 concurrent-production-state
  告警；cursor 保留。测试变更后协调器会重新运行 formal，报告不得把 495 误写为
  repair 后最终计数。

## worker-safe 验证

- 运行所有不要求真实 0.150.1 的 focused 合成/失败注入测试；显式列出 test id 与
  结果。
- 运行 repository-wide production literal guard 的正样本与注入负样本。
- `git diff --check`、八 owned-path 精确 scope、AST compile、零 `.pyc`。
- 对最终报告运行 `task_report_verdict` 并要求 `passed=true`、无 failure reason。
- 不在临时 0.149.1 wrapper 内运行 real 0.150.1 positive 或 formal runner；两者由
  协调器在 wrapper 恢复后单层执行。

## 最终六段报告

继续使用且只使用以下二级标题并保持顺序：

1. `## 结果`
2. `## 过程`
3. `## 遇到的问题`
4. `## 解决方式`
5. `## 遗留风险与建议`
6. `## 沉淀候选`

报告必须逐条记录发现、根因、解决、证据、未完成项；成功检查使用既有精确格式。
必须明确 H06B 只准备接受任务范围，最终 installer rollback、scheduler、Codex live、
Claude live、native Windows、同 generation 与 I01-I19 总纲验收仍由新的最终 H06
successor 完成。完成后自然结束，不 commit、不安装。
