## 结果
✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest tests.test_agent_runtime.AgentRuntimeTests.test_runtime_imports_exact_shared_codex_cli_authority tests.test_agent_runtime.AgentRuntimeTests.test_shared_codex_help_observation_normalizes_environment_and_exact_warning tests.test_agent_runtime.AgentRuntimeTests.test_codex_preflight_requires_profile_parse_and_app_server_handshake tests.test_agent_runtime.AgentRuntimeTests.test_synthetic_incompatible_codex_help_fails_closed tests.test_agent_runtime.AgentRuntimeTests.test_codex_preflight_rejects_help_diagnostic_stderr_drift tests.test_agent_runtime.AgentRuntimeTests.test_codex_preflight_rejects_path_alias_future_and_substring_versions tests.test_codex_plugin_install.CodexPluginInstallTests.test_installer_imports_shared_codex_cli_authority tests.test_codex_plugin_install.CodexPluginInstallTests.test_installer_cli_smoke_uses_successful_stdout_identity_only tests.test_codex_plugin_install.CodexPluginInstallTests.test_installer_cli_smoke_rejects_noncanonical_help_diagnostics_and_bytes tests.test_codex_plugin_install.CodexPluginInstallTests.test_recovery_rejects_recomputed_native_authority_drift`，exit 0；10 个 shared-helper/runtime/installer 正负样本全部通过。
✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest tests.test_agent_runtime.AgentRuntimeTests.test_codex_preflight_requires_profile_parse_and_app_server_handshake tests.test_agent_runtime.AgentRuntimeTests.test_codex_initialize_retries_are_bounded_and_stop_at_first_success tests.test_agent_runtime.AgentRuntimeTests.test_audited_codex_0150_real_cli_contract tests.test_agent_runtime.AgentRuntimeTests.test_synthetic_incompatible_codex_help_fails_closed tests.test_agent_runtime.AgentRuntimeTests.test_codex_preflight_rejects_help_diagnostic_stderr_drift tests.test_agent_runtime.AgentRuntimeTests.test_codex_preflight_rejects_path_alias_future_and_substring_versions`，exit 0；6 个 runtime preflight 受影响用例通过，真实 0.150.1 roundtrip staged 605 files 并验证 366 篇 corpus 文档。
✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest tests.test_codex_plugin_install`，exit 0；42 个 installer 组合用例全部通过，临时 staging 均位于受管 scratch。
✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -c 'import ast,pathlib; [ast.parse(pathlib.Path(p).read_text(), filename=p) for p in ["scripts/kb/codex_cli_contract.py","scripts/kb/agent-runtime.py","scripts/release/install_codex_plugin.py","tests/test_agent_runtime.py","tests/test_codex_plugin_install.py"]]; print("AST_OK 5")'`，exit 0；五个 Python 变更文件均可解析。
✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -c 'import json; from pathlib import Path; from tests.test_agent_runtime import load_runtime_module; m=load_runtime_module(); p=Path("guardian-r2-program/reports/H06E-codex-help-authority.md"); v=m.task_report_verdict(p.read_text(encoding="utf-8"), m.report_contract_for_brief("# H06E\n")); print(json.dumps(v,ensure_ascii=False,sort_keys=True)); assert v["passed"]'`，exit 0；报告满足 `sulde-worker-report-v1`，无 failures。
✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -c 'import json,subprocess; task=json.load(open("guardian-program/task-definitions/H06E-codex-help-authority.json")); owned=set(task["owned_paths"]); tracked=set(subprocess.check_output(["git","diff","--name-only"],text=True).splitlines()); untracked=set(subprocess.check_output(["git","ls-files","--others","--exclude-standard"],text=True).splitlines()); preexisting={"guardian-program/briefs/H06E-codex-help-authority.md","guardian-program/task-definitions/H06E-codex-help-authority.json"}; effective=tracked | (untracked-preexisting); print(sorted(effective)); assert effective == owned'`，exit 0；本次 effective diff 精确等于 task definition 的六个 owned paths，另有两份协调器预置 untracked authority 文件保持未改。

### repair1

✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -c 'import importlib.util,os,pathlib,subprocess; p=pathlib.Path("scripts/kb/codex_cli_contract.py"); s=importlib.util.spec_from_file_location("c",p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); e=m.codex_probe_environment(os.environ); rows=[subprocess.run([str(m.AUDITED_CODEX_EXECUTABLE),*a],input="",capture_output=True,text=True,encoding="utf-8",errors="strict",env=e,check=False,timeout=15) for a in (("--help",),("exec","--help"),("app-server","--help"))]; print([sorted({ord(ch) for ch in r.stdout if ord(ch)<32 or 127<=ord(ch)<=159}) for r in rows])'`，exit 0；真实 `codex-cli 0.150.1` 三份 help 的控制码集合均仅为 `[10]`，没有 TAB 字节，因此 repair1 只允许 LF。
RED 证据：`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest tests.test_agent_runtime.AgentRuntimeTests.test_shared_codex_help_observation_normalizes_environment_and_exact_warning tests.test_agent_runtime.AgentRuntimeTests.test_audited_codex_help_observation_matches_real_pty_and_nonpty_parents tests.test_codex_plugin_install.CodexPluginInstallTests.test_installer_cli_smoke_rejects_noncanonical_help_diagnostics_and_bytes`，旧实现返回码为 1；四个具名控制字均出现 `CodexCliContractError not raised`，installer 因错误放行继续进入第五码面 probe，真实 `openpty` 在 managed outer profile 被 `Operation not permitted` 拦截，形成 repair1 红灯与环境边界证据。
✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v tests.test_agent_runtime.AgentRuntimeTests.test_shared_codex_help_observation_normalizes_environment_and_exact_warning tests.test_codex_plugin_install.CodexPluginInstallTests.test_installer_cli_smoke_rejects_noncanonical_help_diagnostics_and_bytes`，exit 0；2 个共享入口/installer 控制字用例通过；共享入口穷举拒绝除 LF 外的 64 个 ASCII/C1 控制码，installer 具名拒绝 U+009B、CR、BS、NUL。
✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v tests.test_agent_runtime.AgentRuntimeTests.test_audited_codex_help_observation_matches_real_pty_and_nonpty_parents`（父宿主 `tty=true`），exit 0；同一 production-spec 小型 probe 分别从普通 non-PTY 与真实 pseudo-terminal 父宿主运行真实 0.150.1 version 与三份 help，1 test OK，三份 canonical surface、逐份 SHA-256 与总 digest 相等。
✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -c 'import json; from tests.test_agent_runtime import observe_audited_codex_help_from_parent as observe; print(json.dumps(observe(pseudo_terminal=False),sort_keys=True))'` 与同命令的 `pseudo_terminal=True`（父宿主 `tty=true`），均 exit 0；两边总 digest 都是 `b20b713507ea6beccecf0208be2b7825c950375de305d456fa539eda0d4c5247`，长度都是 `5731/3957/3206`，逐份 SHA-256 都是 `e8ecd554…/e504bac5…/95d29003…`。
✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v tests.test_agent_runtime.AgentRuntimeTests.test_runtime_imports_exact_shared_codex_cli_authority tests.test_agent_runtime.AgentRuntimeTests.test_shared_codex_help_observation_normalizes_environment_and_exact_warning tests.test_agent_runtime.AgentRuntimeTests.test_codex_preflight_requires_profile_parse_and_app_server_handshake tests.test_agent_runtime.AgentRuntimeTests.test_codex_initialize_retries_are_bounded_and_stop_at_first_success tests.test_agent_runtime.AgentRuntimeTests.test_audited_codex_0150_real_cli_contract tests.test_agent_runtime.AgentRuntimeTests.test_synthetic_incompatible_codex_help_fails_closed tests.test_agent_runtime.AgentRuntimeTests.test_codex_preflight_rejects_help_diagnostic_stderr_drift tests.test_agent_runtime.AgentRuntimeTests.test_codex_preflight_rejects_path_alias_future_and_substring_versions tests.test_codex_plugin_install.CodexPluginInstallTests.test_installer_imports_shared_codex_cli_authority tests.test_codex_plugin_install.CodexPluginInstallTests.test_installer_cli_smoke_uses_successful_stdout_identity_only tests.test_codex_plugin_install.CodexPluginInstallTests.test_installer_cli_smoke_rejects_noncanonical_help_diagnostics_and_bytes tests.test_codex_plugin_install.CodexPluginInstallTests.test_recovery_rejects_recomputed_native_authority_drift`，exit 0；run1 的 12 个 focused/real 正负组合全部通过，真实 roundtrip staged 605 files 并验证 366 篇 corpus 文档。
✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest tests.test_codex_plugin_install`，exit 0；repair1 后 42 个 installer 用例在 154.255 秒内全部通过。
✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -c 'import ast,pathlib; paths=["scripts/kb/codex_cli_contract.py","scripts/kb/agent-runtime.py","scripts/release/install_codex_plugin.py","tests/test_agent_runtime.py","tests/test_codex_plugin_install.py"]; [ast.parse(pathlib.Path(p).read_text(encoding="utf-8"),filename=p) for p in paths]; print("AST_OK",len(paths))'`，exit 0；repair1 的五个 Python owned files 均可解析，输出 `AST_OK 5`。
✅ 完成检查：`git diff --check`，exit 0；无 whitespace error 输出。
✅ 完成检查：`PYTHONDONTWRITEBYTECODE=1 python3 -B -c 'import json,subprocess; task=json.load(open("guardian-program/task-definitions/H06E-codex-help-authority.json",encoding="utf-8")); owned=set(task["owned_paths"]); tracked=set(subprocess.check_output(["git","diff","--name-only"],text=True).splitlines()); untracked=set(subprocess.check_output(["git","ls-files","--others","--exclude-standard"],text=True).splitlines()); authority={"guardian-program/briefs/H06E-codex-help-authority.md","guardian-program/briefs/H06E-codex-help-authority-repair1.md","guardian-program/task-definitions/H06E-codex-help-authority.json"}; effective=tracked | (untracked-authority); print(sorted(effective)); assert effective==owned'`，exit 0；repair1 当前 effective diff 精确等于六个 owned paths，协调器预置 authority 输入保持在 diff 之外且未修改。

## 过程
从 frozen base `f0e845617867c1710b636205c6798d03140d1646` 开始，先读取 task definition 与 KB 原文 `ap-0201`、`ap-0224`。红灯阶段新增的 4 个 focused 用例因共享 helper 缺失而报错，随后实现转绿。

`scripts/kb/codex_cli_contract.py` 现在是 version/help probe 环境、help canonical bytes 与 observation SHA-256 的唯一实现。installer seal 和 runtime preflight 均导入同一函数；warning 字面量、终端/颜色环境规则与 help hashing 未复制到调用方。

保留 executable lexical/resolved path 与文件 digest、exact `codex-cli 0.150.1`、required help tokens、return code、strict profile/hook parse、app-server initialize、broker/runtime/tree/generation 和 authority digest gate。

未执行 install、scheduler/生产 KB 修改、commit、push、merge，也未触碰 dev/main。

### repair1

协调端独立审查以 `FR2-H06E-001` 打回 run1：只查 `ESC` 不是完整控制字边界，U+009B、CR、BS、NUL 都能进入 authority；run1 所谓 PTY 用例只改 environment mapping，未建立真实 PTY 父宿主。`FR2-H06E-002` 又证明环境固定后仍继承父 stdin，导致普通父宿主与真实 PTY 父宿主观测分别为 `b20b7135…` 与 `3da94b7a…`。

repair1 先在旧实现上运行新增攻击与 PTY 用例取红，再审计真实 0.150.1 字节；三份 help 只有 LF 控制码，不需要 TAB 例外。随后把 environment 与立即 EOF 合并为同一 `CodexProbeSpec`，runtime 与 installer 均只从 `codex_probe_spec` 取得这两项边界。

最终真实父宿主双观测恢复为同一 `b20b7135…` digest；run1 的 warning、stderr、return code、token、version、re-signed authority、profile/broker/runtime/tree/generation 负样本继续保留并通过。

## 遇到的问题
FR2-H06D-002：同一 `codex-cli 0.150.1` 的 help stdout 会继承父进程 PTY、`TERM` 与颜色变量，导致 installer、PTY、sandbox 和 external raw digest 不一致。

FR2-H06D-004：sandbox 可能额外产生唯一已知的完整 PATH-alias permission warning；旧实现将 stdout+stderr 原样拼接并在 installer/runtime 各自哈希，使非致命环境诊断造成 authority drift。

SKIP（managed outer profile）：完整 `tests.test_agent_runtime` 不作为本 worker 的完成证据。其通用 fixture 固定在 worktree 根创建 `tmp*`，被本任务 exact-owned-path sandbox 以 `Operation not permitted` 拒绝；协调器按任务书在单层 formal 环境独立运行。受影响且不越界的 runtime 组合已单独通过。

### repair1

`FR2-H06E-001`：run1 的 `canonicalize_codex_help` 仅拒绝 U+001B，遗漏其余 ASCII/C1 控制码，攻击者可把终端控制、行内覆盖、退格或 NUL 写入被 sealing/runtime 共用的 help authority。

`FR2-H06E-002`：run1 只固定环境，没有关闭五次 identity/help/profile-help probe 的 stdin；`capture_output=True` 不会关闭 stdin，真实 PTY 父宿主仍可改变 CLI 输出。

SKIP（managed outer profile）：普通 non-PTY unittest 进程内调用 `os.openpty()` 被 `Operation not permitted` 拒绝；未扩权。相同测试在宿主提供的真实 PTY 下 exit 0，并且协调端仍需在单层 formal 环境重跑其 `openpty` 分支。

## 解决方式
共享环境 helper 复制 caller mapping 后移除宿主终端标识，并固定 `TERM=dumb`、`NO_COLOR=1`、`CLICOLOR=0`、`CLICOLOR_FORCE=0`、`FORCE_COLOR=0`；原 mapping 保持不变。

共享 canonical helper 只接受空 stderr 或与 frozen 文本逐字节相等的完整 PATH-alias warning，只接受三个 return code 为 0 的 help probe，拒绝 ANSI stdout，并对三份 canonical stdout bytes 以 NUL 分隔计算同一 digest。

负样本覆盖 warning 多一字符、第二条诊断、未知 stderr、ANSI/语义 stdout 漂移、缺 token、非零 return code、0.149/future/alias/substr version 以及 re-signed help authority drift；精确 warning 与无 warning 得到相同 observation。

### repair1

共享 canonicalizer 逐字符检查码点，拒绝除 U+000A LF 外的 U+0000–U+001F 与 U+007F–U+009F；没有使用可能遗漏 CR、BS、NUL 的正则，也没有只枚举 ESC/C1 CSI。真实字节审计没有发现 TAB，所以没有增加 TAB 例外。

共享 `CodexProbeSpec` 同时携带 no-color environment 与空字符串 stdin。runtime 五次 `subprocess.run` 显式传 `input=probe_spec.stdin`，installer 五次 runner 调用显式传其既有的 `input_text=probe_spec.stdin`；两边环境都来自同一 spec，不在调用方复制交互边界。

真实 PTY 测试的小型 probe 导入 production contract，校验 exact 0.150.1 version，运行三份真实 help，并用 `canonical_codex_help_observation` 比较 canonical bytes、逐份 digest、总 digest 与长度；没有 mock `isatty`，也没有用 TERM 字典冒充 PTY。

## 遗留风险与建议
该例外严格绑定当前已知 `codex-cli 0.150.1` 诊断全文；未来版本或任何新增 stderr 会 fail closed，需要新的审计任务，不应放宽为 substring/regex。

本报告不声称 H06D 或 R2 已完成；两者仍由协调器执行单层 formal、集成与系统级验收。H06E 本身未安装到生产。

### repair1

普通 non-PTY suite 在当前 managed outer profile 会对真实 `openpty` 分支环境性 skip；协调端必须在单层 formal 环境确认该分支不 skip。worker 已用宿主真实 PTY 跑同一测试并通过，但不替代协调端 formal gate。

本次仍未 install、commit、push、merge、修改 scheduler/生产 KB 或调用 Claude，也未完成 H06D/R2。未来 Codex 版本若新增合法控制字或 stderr，必须以新的真实字节审计任务更新 frozen contract，不能放宽为通用控制码或 diagnostic 匹配。
