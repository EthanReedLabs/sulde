/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:继续同一 T31：修复 F31-001 的 importlib 自缓存时序，保持六路径冻结，完成双解释器定向验证并更新原报告。

# T31 Codex 0.149.1 exact host audit

Resume-only closeout: the prior controlled run reached its 1800-second hard
limit after implementing the six-path candidate, passing the complete owned
module suites (54/54 and 38/38), completing scratch official staging, and
writing `guardian-program/reports/T31-codex-0149-1-host-audit.md`. Do not rerun
full discovery or expand the implementation. Inspect the current exact owned
diff and report, correct only an evidenced defect if one remains, then return a
final response with each required report heading exactly once and at least one
evidenced `✅ 完成检查` line so agent-runtime can close the existing campaign.

Coordinator re-verification recorded F31-001 at program sequence 324. Under
the production KB venv (CPython 3.10.7), the current fresh-interpreter smoke's
`importlib.util.spec_from_file_location(...).loader.exec_module(...)` writes
`runtime/scripts/kb/__pycache__/agent-runtime.cpython-310.pyc` before the
entrypoint can execute its bytecode guard. Three installer acceptance tests
therefore roll back, even though the Python 3.9 worker topology passed. An
isolated `runpy.run_path` load of the same entrypoint completed without any
bytecode. Correct this exact loader-order defect inside the existing owned
installer/runtime/tests, prove the smoke still calls the real installed
`load_installed_native_authority()` in production mode, rerun both owned
modules with the production KB venv as well as the worker interpreter, and
update the existing report. This is an in-task correction, not a new task or
permission to expand the six-path freeze.

Implement only `guardian-program/task-definitions/T31-codex-0149-1-host-audit.json`
from base `096226c1b70e3cde51f97906d45ff266ec25a0b8`.

The coordinator may have pre-staged a minimal bootstrap candidate because the
old exact 0.149.0 runtime cannot launch the current 0.149.1 Codex provider.
Treat every pre-staged byte as untrusted input: compare it with real read-only
`--version`, top-level/`exec` help, profile and app-server initialize probes;
correct or reject it before claiming success.

Keep exact fail-closed semantics. Do not accept a version family or arbitrary
patch, do not change the Codex executable/symlink, and do not edit installed or
production state. Update only the six owned paths. Use a single fresh Codex
cachebuster suitable for the repository's official installer; do not edit any
marketplace file.

Coordinator bootstrap observation: the isolated installer returned success but
its sealed runtime subsequently contained CPython bytecode under
`runtime/scripts/kb/**/__pycache__`, so `load_installed_native_authority()`
correctly failed closed before provider launch. Determine and fix this
post-seal mutation inside the owned installer/runtime/test paths; installation
must not report success while its own smoke leaves the native runtime authority
unloadable.

Required verification includes focused agent-runtime and installer tests,
future/substr/wrapper/help/profile/broker/generation negative cases, a real
0.149.1 contract probe, and the report sections `结果`, `过程`, `遇到的问题`,
`解决方式`, `遗留风险与建议`, `沉淀候选`. The worker must not perform production
installation, scheduler reload, main merge or production ledger writes.
