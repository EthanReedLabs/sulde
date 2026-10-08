# Codex 0.160.0 — independent review and integration handoff

Date: 2026-10-03. Intent: completion:d91a9fb3412f974b9dd0fbd3.
Reviewed candidate: `a0c346fc877987497db1e6c4138eb775f541583c`.
Base dev: `3e7bdee331df03a45b947ddc5b7cb2ef19c7af76`.
Independent reviewer: `/root/compat_independent_review`, read-only review.

## Decision

**scoped review_passed**: no blocking candidate findings. Eligible for local dev
integration and subsequent separately authorized installation preparation. This
is not production installation acceptance or real-Agent behavior acceptance.

The reviewer independently checked:

- Production code changes only the exact CLI pin; broker, runtime, installer
  transaction and Hook policy implementation remain unchanged.
- Old/future/decorated/unsuccessful version identities remain rejected.
- All 484 FINAL-SHA256 entries match; 401 scripts/tests hashes match the candidate.
- Every reused test has a complete original one-line OK. 134 reused and 151 newly
  selected cases are disjoint and cover 285 cases (282 passed, three skipped).
- Both installer subclasses are pure additions. All 108 omitted inherited cases
  map to retained base tests. The original interrupted batch remains exit -15.
- Actual CLI/staged-runtime/PreToolUse/PostToolUse logs support the scoped claims;
  actual PreToolUse records both generation identities and pre-execution denial.
- Native OS evidence supports two allowed and 17 denied operations, with synthetic
  authority explicitly distinguished from production authorization.
- Diff whitespace check passes and the candidate worktree is clean.

No tests or model calls were repeated for this review. Coordinator separately
read back all 484 evidence hashes with zero mismatch. Evidence remains in
`/Volumes/Optimus/Sulde/tasks/codex-01600-compat-20261003/` without rewriting its
historical SUMMARY or source-bound archive. This document is a later review,
not part of the original tested candidate; it changes no scripts/tests inputs.

## Integration authority and checks

Current-session native Allow applied revision 4, receipt
`a18cf1f45e9e41254ed2f9aeb32b0e1fdd0060b9b3b2bca41b4a9c04ecb2e751`.
It permits this review record and local dev integration only. No install grant,
cachebuster, push, main release, CLI change or real model call is authorized.

Integration must verify clean worktrees, expected dev predecessor, reviewed
candidate ancestry and identical integrated tree. Reuse the scoped audit for
unchanged inputs; do not describe it as a newly executed full suite. Preserve
the existing main and remote refs. Git commit identities and integration outcome
are observable in history and the coordinator's final handoff.

## Installation prerequisite discovered, not a candidate regression

Read-only checks found both these paths absent on this host:

- `~/.codex/skills/.system/plugin-creator/SKILL.md`
- `~/.codex/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py`

A filename search of installed skills/plugin caches, stable launchers and the
candidate repository found no replacement cachebuster helper. The existing
Guardian `_codex_plugin_cachebuster_binding` in
`scripts/kb/intent_guardian_parts/state.py` requires the exact official helper
path and fails if unavailable. No maintenance proposal, helper execution or
production installation was attempted. Why it disappeared is **inconclusive**.
This is an environmental prerequisite, not a failure of the one-line version
compatibility repair. It is also not grounds to fabricate the file, weaken
digest checks, hand-edit immutable caches or reuse old maintenance authority.

Next bounded work: establish the current supported helper/installation workflow
from verifiable official sources, then either restore the authentic supported
dependency with authorization or explicitly design a separately reviewed
maintenance-adapter change. Freeze that scope before changing control-plane code.
After the prerequisite is met, authorize fresh cachebuster/install actions,
verify a candidate before promotion, check current-generation live Hooks, and
only then resume the frozen real-Agent sample (previous two-call budget unused).

## Retained boundaries

Windows, production switching and real model behavior remain unverified.
The wrapper/native-payload identity distinction is an existing design limitation;
installation must recheck both identities and actual version. This audit's reuse
logic is not a universal cache guarantee. Historical debt, broader lifecycle
acceptance and multi-sample comparison remain separate tasks.

No new KB fact is published. Helper disappearance has no verified causal diagnosis.
