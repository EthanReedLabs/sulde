## 结果

H06B repair2 已完成最终报告的来源/时序修复。FR2-H06B-001、FR2-H06B-002、FR2-H06B-004 在 H06B 候选中为 `fixed current`；FR2-H06B-003 经执行主体/观察时点分段及独立 code、test、report 三路复审，在本报告中为 `fixed current`；FR2-H06B-005 保持 `transfer/open`，等待新的最终 H06 successor 在 fleet safe point 完成验收。当前结论仅是 **H06B 已准备由协调器接受任务范围**，不代表 H06、program 或 release accepted。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v tests.test_agent_runtime.AgentRuntimeTests.test_audited_codex_0150_real_cli_contract`，exit 0；wrapper 恢复后由协调器在 full clone 执行，1 test in 2.647s，`OK`。候选 stager 生成 605 文件并验证 366 篇知识文档；临时 marketplace、KB 与 deployment 形成完整 authority，staged runtime 通过 `load_installed_native_authority()` 回读同一对象并交给 preflight，重新签名的 broker digest 漂移由物理文件复核 fail closed；没有生产安装。

✅ 完成检查：`SULDE_AUDIT_CURSOR_HOME=/private/tmp/sulde-h06b-repair1-formal-cursors.An5fq9 /Users/eric/.claude/plugins/data/sulde-cc/kb/venv/bin/python -B scripts/kb/run-isolated-tests.py tests.test_intent_guardian tests.test_intervention tests.test_agent_runtime tests.test_native_decision_journal tests.test_operational_readiness tests.test_sulde_statusline tests.test_codex_plugin_install tests.test_stage_plugin`，exit 0；repair1 formal 运行一由协调器以 8 模块单层命令执行，495 tests in 223.734s，`OK (skipped=1)`，唯一 skip 是 native Windows PowerShell。process guard 观察到测试子进程零生产 KB 写入，但在 verified read-only boundary 后发现无关外部会话并发更新三个 intent 文件；因此这是测试通过证据，不是 quiet fleet-safe 证据。

✅ 完成检查：`SULDE_AUDIT_CURSOR_HOME=/private/tmp/sulde-h06b-repair1-quiet-formal-cursors.eJVZpy /Users/eric/.claude/plugins/data/sulde-cc/kb/venv/bin/python -B scripts/kb/run-isolated-tests.py tests.test_intent_guardian tests.test_intervention tests.test_agent_runtime tests.test_native_decision_journal tests.test_operational_readiness tests.test_sulde_statusline tests.test_codex_plugin_install tests.test_stage_plugin`，exit 0；repair1 formal 运行二由协调器以相同 8 模块单层命令执行，495 tests in 226.579s，`OK (skipped=1)`，唯一 skip 仍是 native Windows PowerShell。process guard 再次证明测试子进程零生产写入，但外部会话在验证窗口提交 native decision/receipt/head；因此也不是 quiet fleet-safe 证据。

✅ 完成检查：`git diff --check`，exit 0；当前候选无 whitespace error。

✅ 完成检查：`shasum -a 256 scripts/kb/codex_cli_contract.py scripts/kb/agent-runtime.py scripts/release/install_codex_plugin.py scripts/release/stage_plugin.py tests/test_agent_runtime.py tests/test_codex_plugin_install.py tests/test_stage_plugin.py`，exit 0；七个 SHA-256 逐项等于 repair2 baseline 中捕获的 repair1 终态候选 blob。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -c 'import json,subprocess;from pathlib import Path as P;t=json.loads(P("guardian-program/task-definitions/H06B-codex-0150-authority.json").read_text());c={str(p) for p in P("guardian-program/briefs").glob("H06B-codex-0150-authority*.md")}|{"guardian-program/task-definitions/H06B-codex-0150-authority.json"};x=set(subprocess.check_output(["git","diff","--name-only"],text=True).split())|set(subprocess.check_output(["git","ls-files","--others","--exclude-standard"],text=True).split());assert x==set(t["owned_paths"])|c;print("SCOPE owned=8 controls=4 changed=12")'`，exit 0；8 个 owned outputs 加 4 个只读控制投影的精确 scope 成立。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -c 'import ast;from pathlib import Path as P;ps=("scripts/kb/codex_cli_contract.py","scripts/kb/agent-runtime.py","scripts/release/install_codex_plugin.py","scripts/release/stage_plugin.py","tests/test_agent_runtime.py","tests/test_codex_plugin_install.py","tests/test_stage_plugin.py");[ast.parse(P(p).read_text(),filename=p) for p in ps];print("AST 7")'`，exit 0；七个 Python 输出均可 AST compile。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -c 'import re;from pathlib import Path as P;h=re.findall(r"^## .+$",P("guardian-r2-program/reports/H06B-codex-0150-authority.md").read_text(),re.M);assert h==["## 结果","## 过程","## 遇到的问题","## 解决方式","## 遗留风险与建议","## 沉淀候选"];print("HEADINGS 6")'`，exit 0；六个二级标题逐字、唯一且顺序正确。

✅ 完成检查：`find . \( -name __pycache__ -o -name '*.pyc' \) -print`，exit 0；无输出，候选内零 `__pycache__`/`.pyc`。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -c 'import json,runpy;from pathlib import Path as P;m=runpy.run_path("scripts/kb/agent-runtime.py");v=m["task_report_verdict"](P("guardian-r2-program/reports/H06B-codex-0150-authority.md").read_text(),m["report_contract_for_brief"](P(".codex-agent/r2-h06b-codex-0150-authority-repair2.brief.md").read_text()));assert v["passed"] is True and v["failures"]==[];print(json.dumps(v,sort_keys=True))'`，exit 0；`task_report_verdict` 返回 `passed=true`、`failures=[]`，无 failure reason。

## 过程

先核验 frozen base `e9afaac7b6126ba2c1ccec16ac9a3367f9863820`，以及 task definition、original brief、repair1 brief 的 SHA-256 分别为 `c5082ba58a0f4336087b9cb24b48434ae053c757d75003b2f3ce1c7fd8b24020`、`22975aea47b7bddbbcbbbf64ad940a240e7d99d69e20b693ce3d5a5d346a1328`、`972cfbc248f5c2c5dbf2993f4e7ddc0ad525f38d7bc2d3a706399bc8e422746c`。repair1 wrapper SHA-256 为 `e4b86cc8dd9675130049ef2b29a3fab911c85e9bc0656b187ab468976995af4b`；repair1 managed run 终态为 `status=success rc=0 duration=1168s`，随后 wrapper 明确输出 `RESTORED codex-cli 0.150.1`。这些事实按 wrapper/restore 时序记录，不与 worker 临时投影混写。

repair1 worker 在隔离候选中完成 authority 补强：生产 authority 绑定 audited executable 的 lexical/resolved path 与 digest、精确版本、三份完整 help stdout+stderr 联合 observation digest、strict profile、app-server initialize、agent/runtime、broker、shared contract、runtime tree 与 runtime generation。独立 code 路复核 seal/readback 字段并补上 shared contract 显式 path/digest；独立 test 路将真实正例改为临时 stager → installer seal → deployment write → staged runtime readback → preflight，并加入重签 broker digest 漂移负样本；独立 report 路按 worker temporary projection、wrapper restore、coordinator post-restore real positive、coordinator formal suite 切分来源和时点。

repair2 worker 没有重跑 real CLI、formal 或 installer/stager 全套，只重写本报告并执行 worker-safe 静态验收。七个代码/测试文件保持 repair1 终态候选字节不变：`scripts/kb/codex_cli_contract.py`、`scripts/kb/agent-runtime.py`、`scripts/release/install_codex_plugin.py`、`scripts/release/stage_plugin.py`、`tests/test_agent_runtime.py`、`tests/test_codex_plugin_install.py`、`tests/test_stage_plugin.py`。本报告 `guardian-r2-program/reports/H06B-codex-0150-authority.md` 是第八个 owned output。

四个只读控制投影不是任务输出：`guardian-program/task-definitions/H06B-codex-0150-authority.json`、`guardian-program/briefs/H06B-codex-0150-authority.md`、`guardian-program/briefs/H06B-codex-0150-authority-repair1.md`、`guardian-program/briefs/H06B-codex-0150-authority-repair2.md`。

## 遇到的问题

FR2-H06B-001 的根因是把 worker temporary projection 的进程内观察误归因到 wrapper 退出后的宿主；经来源/时序切分及 restore 后协调器证据复核，在 H06B 候选中为 `fixed current`。

FR2-H06B-002 的根因是旧 real-positive 以局部手造 help 字典绕过 staging、installer authority seal、deployment descriptor 与 staged runtime readback，且 shared contract 缺少显式 path/digest；完整 authority roundtrip 和显式 shared-contract digest 已补齐，在 H06B 候选中为 `fixed current`。

FR2-H06B-003 的根因是结构合格的旧报告仍混写 worker、wrapper 与 coordinator 的证据。当前报告将 source/time 分段并记录独立 code、test、report 三路复审及处置，在当前报告中为 `fixed current`。

FR2-H06B-004 的根因是旧机械 guard 只扫描 `scripts/**/*.py`，无法发现其他生产根或 TOML/JSON/shell 中复制的 audited-version literal；guard 已扩展到实际生产文本根和后缀，并以跨根非 Python 注入负样本证明会判红，在 H06B 候选中为 `fixed current`。

FR2-H06B-005 不是 H06B 代码失败。只读控制调查把 formal 窗口内 writer 精确归因到独立 Codex session `019fee8b-bcad-7623-be8e-dd3743f69039`，workspace `/Users/eric/iquokkaApp/iquokka-harmony`，任务为 HarmonyOS IAP 中文错误提示。其 active intent 为 revision 75/enforce；09:05–09:06 的 approved proposal native transaction 从 `approval_decided` 依次推进至 `committed`，之后继续产生 live-verified Hook 事件。该会话不是 H06B worker，也未修改 H06B clone；协调器未中断、暂停或杀掉用户的无关任务。该 finding 保持 `transfer/open`。

## 解决方式

installer seal 新增 `codex_cli_contract_path` 与 `codex_cli_contract_sha256`；staged runtime 的 `load_installed_native_authority()` 要求字段集合完全一致，并独立核验 shared contract 路径和 regular-file digest、authority canonical digest、deployment digest、runtime tree 与 generation。真实 roundtrip 使用临时 marketplace/KB/deployment，从候选 stager 和 installer 形成完整对象，再由 staged runtime 回读并送入 preflight；重签的伪造 broker digest 仍被物理文件复核 fail closed。

repository-wide guard 遍历工作树中实际存在的 `scripts/`、`hooks/`、`integrations/`、`tools/`、`commands/` 生产文本，排除 tests、fixtures、docs、knowledge 与 guardian 控制/报告材料。生产唯一允许命中为共享模块中的 `codex-cli 0.150.1`；注入 `integrations/codex/copied-contract.toml` 后出现第二命中并判红。

证据归因保持两个不变量：两次 formal 的 495 tests 和零测试子进程生产写入都是有效通过证据；同一窗口的外部生产状态更新也必须显式保留。外部并发告警既不被描述为 H06B 代码失败，也不被删除或改写成 guard clear。FR2-H06B-005 交由新的最终 H06 successor 在经协调的 fleet safe point 获取 quiet formal/install/live 同 generation 证据。

## 遗留风险与建议

H06B 当前只准备由协调器接受任务范围，不是 H06、program 或 release accepted。新的最终 H06 successor 仍必须把以下项目作为硬门槛：最终 installer rollback、scheduler、Codex live、Claude live、native Windows、同 generation、I01-I19 与全部 13 failure axes；并在 fleet safe point 获得 quiet formal/install/live 同 generation 的同窗证据。两次 repair1 formal 均不能替代该 quiet fleet-safe 终验。

本 repair2 worker 未运行 real CLI、formal 或 installer/stager 全套，未 install，未操作 scheduler、生产 KB 或全局配置，未访问网络或调用 Claude，未 reset、commit、push、merge，未修改 `dev`、`main` 或七个代码/测试输出。

## 沉淀候选

问题卡候选（evidence_status: `confirmed`）——时间上下文误归因：可逆宿主投影如果没有绑定“执行主体 + 观察时点 + restore 后复核”，会把 worker 内临时状态误写为当前宿主事实。路由正样本：分别记录 worker projection、wrapper restore、coordinator post-restore；路由反样本：跨时点复用一次版本观察。执行正样本：当前状态结论来自 restore 后精确 executable 回读；执行反样本：从临时投影推导宿主持久状态。

问题卡候选（evidence_status: `confirmed`）——关键 shared contract 显式 digest：runtime tree digest 不能替代关键共享合约文件的显式 path/digest authority 字段。路由正样本：stager/installer 复制后同时绑定 shared contract、agent、broker 与 generation/tree；路由反样本：仅因共享文件位于 tree 内就省略关键字段。执行正样本：readback 同时复核 canonical authority 与每个关键 regular file；执行反样本：只重算 authority JSON digest 而不对照物理文件。

问题卡候选（evidence_status: `confirmed`）——并行活跃宿主污染全局生产快照：测试子进程零生产写入不等于全局快照 quiet，其他合法活跃会话仍可在 formal 窗口推进生产 intent。路由正样本：process guard 证明测试子进程零写入，同时将外部变更按 session/workspace/transaction 归因并保留告警；路由反样本：看到测试全绿便把并发生产差异归为被测代码回归或直接写成 guard clear。执行正样本：协调器在 fleet safe point 获取 quiet formal/install/live 同 generation 证据且不擅自终止无关任务；执行反样本：在活跃 fleet 中把一次移动快照当作 release 终验，或为清除告警中断用户会话。按单写者纪律，本任务只在 handoff 报告沉淀候选，没有写入生产知识库。
