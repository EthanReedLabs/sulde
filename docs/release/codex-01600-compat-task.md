# Codex 0.160.0 bounded compatibility task

Base: dev 3e7bdee331df03a45b947ddc5b7cb2ef19c7af76.
Branch: task/codex-01600-compat-20261003. Capability tier: deep.
Current-session human proposal revision 3; no inherited installation authority.

## Frozen outcome and scope

Audit the actual 0.160.0 executable against Sulde's used help/protocol surfaces,
installer and staged-runtime authority, and native command/Hook boundaries.
Candidate-only minimal changes to codex_cli_contract.py, agent-runtime.py,
native_agent_broker.py, installer/candidate preflight and directly affected tests,
audit tools and compatibility documentation. No installed cache or production
descriptor changes, CLI downgrade, broad version ranges or weakened assertions.

Continuous execution through evidence and review handoff; no per-suite approval.
Max zero model calls; no production install/merge/push. Scope stop: compatibility
cannot preserve current security invariants, extra authority, or external prerequisite.
Two same failures without new evidence change the diagnostic approach. New unrelated
issues are recorded, not added to acceptance. No full suite by default.

## Verification sequence

1. Capture exact CLI stdout/version, executable digest, canonical pipe help and
   locally generated schemas under isolated CODEX_HOME. Sources: actual binary;
   official https://learn.chatgpt.com/docs/app-server and /docs/security are context,
   not evidence of a specific installed patch release.
2. Baseline normal protocol/control and identity fault injection. Preserve old
   production rejection of 0.160.0 as an expected compatibility boundary, not a
   regression. Candidate must still reject old/unknown/decorated versions, identity
   drift, re-signed broker drift, unsafe permission/config inputs.
3. Real CLI -> staged installer/runtime -> actual app-server/unified executor/Hook
   no-model positive and negative checks; native shell sandbox probes separately.
4. Run affected modules, separate failing/skipped/environmental results. Never count
   fake provider or synthetic approval as real Agent/human evidence. Bind source,
   tests, schemas, executable and results. No widening to Windows claims.
5. Archive once under /Volumes/Optimus/Sulde/tasks/codex-01600-compat-20261003/;
   preserve raw failed runs, source hashes and a self-excluding manifest. Submit a
   scoped report for independent review, not self-accepted production readiness.

## Expected impact and recovery

Expected: one production version pin if behavior-compatible, migrated explicit
fixtures and real audit evidence. Unexpected protocol/security drift requires a
minimal explained repair or stop, not relaxing the gate. Production remains old
generation throughout; discard candidate on incompatibility, retain evidence.
The previous real-Agent acceptance stays unverified until a separately authorized
compatible installation and at most two real model attempts.
