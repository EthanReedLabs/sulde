/model
选择:gpt-5.6-sol（若当前可用列表无此型号，选择 deep 档或更高的 Codex 模型）
/reasoning
选择:high 或更高
执行任务文件:guardian-r2-program/task-definitions/H06A2-integration-hygiene.json

# H06A2 integration hygiene — managed repair brief

You are `guardian-r2-worker-h06a2`. Work only in the isolated full clone supplied
by the coordinator. This is a finding-driven successor to the unstarted H06A;
do not rebuild the R2 plan, rewrite accepted H00-H05 events, install anything,
modify dev/main, access external systems, or delete inherited artifacts.

## Frozen authority

- Task: `H06A2-integration-hygiene`.
- Base/head before work: `1b793c6ba8b76acd069510ed893de77228d581c6`.
- Task-definition SHA-256:
  `e04be7e6f3e1abf078549613d8439f346b77d1406b5e0a5ee3cf360608555d57`.
- This brief's SHA-256 is supplied by the coordinator at launch and must match
  the read-only projected copy.
- Allowed paths are exactly the nine paths in the task definition. The durable
  report path is mandatory; no other source, test, control, Git metadata,
  runtime, cache, package, launcher, scheduler or user state may change.

## Verified failures to close

1. `tests.test_agent_runtime.AgentRuntimeTests.test_installed_codex_0149_real_cli_contract`
   hard-codes 0.149.1 while the global CLI has moved to 0.150.1. The test must
   derive the exact audited executable/version contract from the installed
   native execution authority, still failing closed on executable, version,
   help/profile/broker or generation drift. Do not accept arbitrary versions,
   substrings, PATH aliases, future versions or caller claims.
2. `tests.test_intent_guardian_state` reports a delayed import of the facade in
   `approvals.py`, plus `recovery.py=3031` and `resources.py=3029`. Remove the
   delayed facade dependency and bring both components to <=3000 physical lines
   by eliminating duplicated/thin logic or redundant structure. Preserve public
   behavior; do not weaken the architecture guard or merely change its limit.
3. `tests.test_subprocess_text_encoding_guard` identifies text subprocess calls
   at `test_grant_broker.py:490`, `test_intent_guardian.py:10317`,
   `test_recovery_supervisor.py:1220` and `test_resource_adapters.py:47`.
   Every call must set `encoding="utf-8"` and `errors="replace"`; keep invalid
   byte visibility and existing assertions.

## Required verification

- Run the three focused guards:
  `tests.test_intent_guardian_state`,
  `tests.test_subprocess_text_encoding_guard`, and the exact installed real-CLI
  contract test.
- Run the affected H01-H05 suites for approvals/grant broker, recovery
  supervisor, resource adapters/routing, recovery/readiness/statusline.
- Run the H00-supported KB-venv `-B` isolated suite for the six frozen Guardian
  domains. Record exact command, exit, count and any production-write-guard
  observation separately; never hide or reinterpret a nonzero result.
- Run AST/compile without bytecode, `git diff --check`, exact nine-path scope,
  and a before/after inventory proving no new or modified `.pyc`.
- The report must contain exactly once and in order: `## 结果`, `## 过程`,
  `## 遇到的问题`, `## 解决方式`, `## 遗留风险与建议`, `## 沉淀候选`.
  Record FR2-H06-003, 004, 006 and 007, every new finding encountered, what was
  fixed, what remains for H06, and a truthful completion check.

Stop with an explicit incomplete report if any frozen condition cannot be
proved. Do not claim H06, installation, Codex 0.150.1 installed authority,
Claude live, Windows, rollback, dev/main merge or production acceptance.
