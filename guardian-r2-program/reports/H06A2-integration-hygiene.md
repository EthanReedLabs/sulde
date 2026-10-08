## 结果

H06A2 candidate verification 已完成，现可交由协调器执行 append-only task evidence/state transitions。协调器 formal 结果只关闭 H06A2 test acceptance；本报告不声称 H06 或 program acceptance，也不声称已安装、发布或审计 global Codex 0.150.1。

✅ 完成检查：`/private/tmp/sulde-codex-01491.8Oc2Dm/run-h06a2-formal-with-audited-codex.zsh`，exit 0；协调器以 SHA-256 `8598f825c27c334c97ea80cc39dd04f2b1dbaef6c00f7783f69a0798956c2051` 的 formal wrapper 临时投影 sealed `codex-cli 0.149.1`，在 cursor `/private/tmp/sulde-h06a2-formal-cursors.GvGO32` 运行 439 tests，95.211 秒，全部 `OK`；real-CLI authority 正例、help stderr drift 负例、executable/version 负例及 generation/profile/broker 负例均实际运行，production guard clear，未出现 concurrent-production-state diagnostic；wrapper 输出 `RESTORED codex-cli 0.150.1` 并保留 cursor，之后独立 readback 再次观察到 global `codex-cli 0.150.1`。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v tests.test_intent_guardian_state tests.test_subprocess_text_encoding_guard tests.test_agent_runtime.AgentRuntimeTests.test_codex_preflight_rejects_path_alias_future_and_substring_versions tests.test_agent_runtime.AgentRuntimeTests.test_synthetic_incompatible_codex_help_fails_closed tests.test_agent_runtime.AgentRuntimeTests.test_codex_preflight_rejects_help_diagnostic_stderr_drift`，exit 0；8 tests 全部 `OK`，覆盖 import graph/line limits、四处 UTF-8 text subprocess 与 invalid-byte、executable alias/future/substring version、synthetic incompatible help 和 diagnostic stderr drift。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -c 'import ast,sys; [compile(ast.parse(open(p,encoding="utf-8").read(),p),p,"exec") for p in sys.argv[1:]]; print("ast_compile_ok=8")' scripts/kb/intent_guardian_parts/approvals.py scripts/kb/intent_guardian_parts/recovery.py scripts/kb/intent_guardian_parts/resources.py tests/test_agent_runtime.py tests/test_grant_broker.py tests/test_intent_guardian.py tests/test_recovery_supervisor.py tests/test_resource_adapters.py`，exit 0；输出 `ast_compile_ok=8`。

✅ 完成检查：`git diff --check`，exit 0；无 whitespace error。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -c 'import hashlib,json,subprocess; from pathlib import Path; t=Path("guardian-program/task-definitions/H06A2-integration-hygiene.json"); a=set(json.loads(t.read_text(encoding="utf-8"))["owned_paths"]); controls={"guardian-program/briefs/H06A2-integration-hygiene.md":".codex-agent/r2-h06a2-integration-hygiene.brief.md","guardian-program/briefs/H06A2-integration-hygiene-repair1.md":".codex-agent/r2-h06a2-integration-hygiene-repair1.brief.md","guardian-program/briefs/H06A2-integration-hygiene-repair2.md":".codex-agent/r2-h06a2-integration-hygiene-repair2.brief.md"}; c=set(controls)|{str(t)}; s=subprocess.run(["git","status","--porcelain=v1"],capture_output=True,text=True,encoding="utf-8",check=True).stdout.splitlines(); o={r[3:] for r in s}; assert o==a|c,(o,a|c); assert all(r[:2]=="??" for r in s if r[3:] in c); assert all(Path(p).read_bytes()==Path(q).read_bytes() for p,q in controls.items()); assert hashlib.sha256(t.read_bytes()).hexdigest()=="e04be7e6f3e1abf078549613d8439f346b77d1406b5e0a5ee3cf360608555d57"; print("scope_ok task_deltas=9 control_projections=4 controls_unchanged=true")'`，exit 0；输出 `scope_ok task_deltas=9 control_projections=4 controls_unchanged=true`。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -c 'import subprocess; from pathlib import Path; base="1b793c6ba8b76acd069510ed893de77228d581c6"; paths=["scripts/kb/intent_guardian_parts/recovery.py","scripts/kb/intent_guardian_parts/resources.py"]; expected={paths[0]:2993,paths[1]:3000}; out=[]; [(lambda current,prior,p: (current.__len__()==expected[p] or (_ for _ in ()).throw(AssertionError((p,len(current),expected[p]))), [line for line in current if line.strip()]==[line for line in prior if line.strip()] or (_ for _ in ()).throw(AssertionError(p)), out.append(f"{Path(p).name}: physical={len(current)} nonblank_preserved={len([line for line in current if line.strip()])}")))(Path(p).read_text(encoding="utf-8").splitlines(),subprocess.run(["git","show",f"{base}:{p}"],capture_output=True,text=True,encoding="utf-8",check=True).stdout.splitlines(),p) for p in paths]; print("; ".join(out))'`，exit 0；输出 `recovery.py: physical=2993 nonblank_preserved=2927; resources.py: physical=3000 nonblank_preserved=2903`。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -c 'from pathlib import Path; p=list(Path(".").rglob("*.pyc")); assert not p,p; print("pyc_count=0")'`，exit 0；输出 `pyc_count=0`。

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -c 'import json; from pathlib import Path; from tests.test_agent_runtime import load_runtime_module; m=load_runtime_module(); report=Path("guardian-r2-program/reports/H06A2-integration-hygiene.md").read_text(encoding="utf-8"); brief=Path("guardian-program/briefs/H06A2-integration-hygiene-repair2.md").read_text(encoding="utf-8"); verdict=m.task_report_verdict(report,m.report_contract_for_brief(brief)); print(json.dumps(verdict,ensure_ascii=False,sort_keys=True)); assert verdict["passed"] and not verdict["failures"]'`，exit 0；输出 `{"check_count": 8, "failures": [], "passed": true, "schema": "sulde-worker-report-v1"}`。

## 过程

- 冻结 identity 保持为 base `1b793c6ba8b76acd069510ed893de77228d581c6` 与 task-definition SHA-256 `e04be7e6f3e1abf078549613d8439f346b77d1406b5e0a5ee3cf360608555d57`；八个既有 code/test delta 原样保留，本轮只重写第九个 owned path，即 durable report。
- 四份未变 read-only control projection 是 original brief、repair1 brief、repair2 brief 与 task definition；前三份分别与对应 `.codex-agent/*.brief.md` 字节一致，task definition 的 digest 与冻结值一致。它们不计为 task output。
- FR2-H06-003 对应 delayed import 加 recovery/resources line limits，已修复；FR2-H06-004 对应四处 UTF-8 subprocess calls，已修复。
- FR2-H06-006 记录原 H06 对八个 predecessor paths 没有 authority；H06A2 拥有本次 repair authority，但不 retroactively widen H06。FR2-H06-007 记录 H06A 未拥有 mandatory report path；H06A2 已将本报告纳入 owned paths。
- FR2-H06A2-002 对应 authority positive 使用 isolated HOME 与 weaker help checking；现已使用 `SULDE_PRODUCTION_KB_HOME` 和 production-isomorphic preflight 修复。FR2-H06A2-003 对应 report mappings/provenance 错误；已由本报告修复。
- 所有历史事实继续由 append-only findings 与 managed run artifacts 保存；本 success report 只呈现当前有效证明，不复制会被严格 report contract 解释为当前失败的历史退出码文本。

## 遇到的问题

- FR2-H06A2-001：managed outer Seatbelt 不能运行 nested formal runner；协调器改在单层 OS isolation 中完成 439-test formal run 后已解决。
- FR2-H06A2-004：repair brief 曾复用 immutable run slug；协调器已使用新 slug 解决，task authority 保持不变。
- FR2-H06A2-005：repair1 report 中的历史非成功退出文本会使严格契约把当前报告判为不合格；现将精确历史留在 append-only findings/managed artifacts，仅在本报告记录当前 proof。
- FR2-H06-009：provision/run Git layout 不一致；physical full clone 已解决运行布局问题，且不改变 task code result。

## 解决方式

- FR2-H06-002：本次 quiet formal run 观察到清晰 production boundary，production guard clear 且无 concurrent-production-state diagnostic，已为协调器 resolution 提供证据。
- worker 侧仅重跑允许的 8 项 focused negatives/architecture/UTF-8 checks 与静态范围检查；没有在 managed provider sandbox 内重跑 real installed positive 或 formal suite。
- 报告逐项绑定 frozen authority、协调器 wrapper/cursor/test count、worker-safe 实测输出和 finding provenance；当前状态是 H06A2 candidate verification complete，可进入协调器 append-only task evidence/state transitions。
- 未 reset、discard、rebuild、commit、push、install，未运行 Claude/Windows/scheduler/rollback，未修改 Git metadata、dev/main、外部或生产状态，也没有 release claim。

## 遗留风险与建议

- FR2-H06-001 仍 open，并已 transferred to H06B：formal wrapper 临时使用的 audited authority 是 sealed `codex-cli 0.149.1`；恢复后的 global `codex-cli 0.150.1` readback 不会使 0.150.1 自动成为 installed audited authority。
- 本次 formal result 仅支持 H06A2 test acceptance 与协调器后续状态转移；H06 总体验收、program acceptance、安装/回滚、Windows 与 release 均不在本任务结论内。
- 建议协调器以 append-only 方式登记本报告、formal cursor 与 wrapper digest，关闭相应 H06A2 findings，并保持 FR2-H06-001 在 H06B 的开放状态。

## 沉淀候选

- 问题语境：受管 outer Seatbelt 与 nested native isolation 叠加会改变真实 CLI help observation，并使 formal runner 无法提供可接受证明；严格 success report 还会把历史退出码 token 当作当前状态。证据状态：confirmed；证据位于 append-only findings、managed run artifacts，以及协调器单层 439-test cursor。
- 路由正样本：real authority 从 `SULDE_PRODUCTION_KB_HOME` 的 deployment descriptor 进入 production-isomorphic preflight；formal verification 在 physical full clone 的单一 OS-isolation layer 执行。路由反样本：信任 isolated HOME、维护 weaker stdout-only help hash、在 managed Seatbelt 中嵌套 formal runner。
- 执行正样本：durable success report 只引用 append-only 历史，并逐条记录当前命令、成功退出与可观察结果。执行反样本：把历史失败命令原文复制进当前 success report，或把 restored global version 解释为 installed audited authority。
