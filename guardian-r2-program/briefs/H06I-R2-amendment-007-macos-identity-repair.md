# H06I-R2 Amendment-007 — macOS TMPDIR identity repair

## Authority

This is an append-only repair to `H06I-R2-interruption-authority`, authorized by the current human session. The parent failure is `FR2-H06I-R2-016` and is recorded in `guardian-r2-program/H06I-R2-COORDINATOR-MATRIX-FAIL.json`.

## Frozen scope

Work only in the existing isolated full clone from base `10ad8d876d74fe5c4dea8e3b1cc27e178078bdc2`. The only owned paths are:

- `scripts/kb/agent-runtime.py`
- `scripts/kb/native_agent_broker.py`
- `tests/test_agent_runtime.py`
- `tests/test_native_agent_broker.py`
- `guardian-r2-program/reports/H06I-R2-interruption-authority.md`

Do not create a successor task, widen paths, alter coordinator events, install, push, merge, start H06J, or modify the report until verification is green.

## Required repair

Use one shared physical-identity canonicalization rule for comparisons that currently mix the lexical macOS `/var/folders` spelling with the kernel's `/private/var/folders` spelling. Fix the owned-path validator in `agent-runtime.py` and full-clone validator in `native_agent_broker.py`. Preserve fail-closed behavior for unrelated escapes, symlink parents, external roots and swap attacks.

Add exact host-default-TMPDIR regression coverage for both validators. Keep existing focused hostile tests intact.

## Verification order

Run the 11 focused tests, the complete runtime module, the complete broker module, combined runtime+broker modules, the same matrix with `TMPDIR=/private/tmp`, and a fresh `git clone --no-hardlinks` clone with the frozen five paths projected. Include root-swap, parent-swap, post-read replacement, local-interruption and report duplicate/conflict/bad-command-hash/missing-binding checks. Any failure stops the task and records red evidence; no retry is automatic. Stage-two self-host verification is allowed only after all coordinator checks pass.

## Report discipline

The final report may claim only checks executed in this amendment and must bind the exact commands, environment, candidate hashes and evidence artifacts. Do not rebind Amendment-005 or Amendment-006 predecessor facts as current results.

## 沉淀候选

问题语境：focused identity coverage passed while two other production path validators still compared lexical and physical macOS temporary-directory spellings. Evidence status: verified. 路由正样本：所有进入 `relative_to` 或 full-clone identity comparison 的路径先经过同一物理身份层。路由反样本：只修 Seatbelt profile 生成器而保留 owned-path/full-clone 旧比较。执行正样本：默认 host TMPDIR 先行通过完整模块后再执行显式 private/tmp 与 fresh clone。执行反样本：先用 private/tmp 绿结果掩盖默认 host TMPDIR 错误。
