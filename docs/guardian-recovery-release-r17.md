# Recovery closure r17: release held at isolated candidate verification

Date: 2026-09-07. Intent: completion:267ee3915da180f817ed2ddd, revision 17.

## Completed

- Reviewed recovery commits 21e8dae and 76fcad3; task worktree was clean.
- Ran the supported isolated runner against exact source 76fcad30b8d5bfac51202e3651047e8ffeb2fce2 using the installed KB venv interpreter.
- Modules: test_production_recovery_control, test_production_recovery_readiness, test_launcher_split_recovery, test_launcher_contract, test_sulde_paths, test_codex_hook_bridge, test_recovery_lane, test_recovery_supervisor, test_stage_release_inventory.
- Result: 137 tests, OK, 14.001 seconds. These are scoped regressions, not a full-suite or native UI proof. Existing developer test groups are not added to this count.
- Fast-forwarded local dev from bd25bd0 to 76fcad3 after scoped checks. This occurred before the candidate failure below was discovered; dev is now release-held, not release-accepted.
- Native proposal Allow applied revision 17. Official helper consumed its one-shot cachebuster grant; plugin structure validation and diff check passed.
- Candidate version: 0.2.5+codex.20260907044716-3a49940f13. Cachebuster-only commit: 1d87724b6f648ec04898c1c6ca73228ee94c0c88, on task/guardian-posttool-resilience, not dev.

## Candidate failure and independently reproduced root cause

Candidate recovery-r17 was prepared in an isolated temporary root. Its artifact runtime digest is 9f144590dbc7b298f9fe50714881424ea6fd6e0252dc870e69a5b81085372524.

Verification stopped at pre-execution-proof-finalize with: `pre-execution probe lacks one live exact PreToolUse denial`.
State is verification_failed, receipt_sha256 is null, promotion_consumed is false. The prepared probe has no started_event_id or decision_fingerprint. A denial-shaped response therefore cannot establish the expected task-policy denial.

Read-only local reproduction against the same source:

```python
route_native_recovery(
    {"toolName": "functions.exec", "toolInput": "text(1);"},
    runtime=Path.cwd(), event="PreToolUse",
)
```

This raises `AttributeError: 'str' object has no attribute 'get'` at production_recovery_control.py:286 before parsing the command or accessing the recovery state. The early recovery route assumes dictionary tool input, whereas the unified-exec wrapper provides JavaScript source text. PreTool and PostTool adapters call this route before ordinary normalization; their exception handlers do not cover this AttributeError.

Root-cause status: verified for input-shape failure. End-to-end repaired candidate and real same-session recovery remain unverified. This reproduction is a local diagnostic, not native host evidence.

## Production and authority boundaries

Production deployment was independently reread and remains 0.2.5+codex.20260906133700-210c01af6d:24aa74726ff6c3b6a887d2a28c5687655e20c1ba47d9fe27fc674f8c69b19a83. No promotion or installation was attempted. The install grant is unconsumed; current contract pending verification and open event counts are both zero.

No push, production rollback, source-code repair, or task resource cleanup was performed. Main and user .ua changes remain untouched. Failed candidate artifacts and original audit records are retained. The coordinator also encountered a rejected combined help command; subsequent Guardian help calls used separate exact invocations, with no attempt to bypass the restriction.

The host reported saving an exact approval-command prefix even though the coordinator supplied no prefix_rule. Do not reuse that saved prefix as authority for a new proposal. This is a separate host-observation concern, not the cause of this candidate failure.

## Required bounded repair before another release attempt

1. Amend source-repair authority: revision 17 currently covers the manifest and release report, not recovery source changes.
2. Type-check/classify native tool inputs before dictionary access. Non-recovery wrapper inputs must continue through ordinary Guardian normalization, not be granted recovery privileges or silently allowed on parser failure.
3. Cover real adapter subprocesses for string functions.exec payloads in PreToolUse and PostToolUse, direct dictionary recovery calls, malformed inputs, identity mismatch and composed-command negatives. Confirm exact native approval semantics remain unchanged.
4. Run scoped regressions and the actual isolated candidate verifier. Create a fresh candidate and newly bound grants after source changes; do not reuse r17 verification or installation authority.
5. Keep production unchanged until the candidate passes. Thereafter perform separately authorized real same-session recovery acceptance, recording Allow/Deny, exact repair, independent verifier and continuation of the original task.

## Sedimentation candidate

- Context: adding an early recovery entry ahead of ordinary tool normalization.
- Symptom: scoped direct-shell tests pass; unified-exec candidate produces an unrelated failure/denial and lacks the expected audit proof.
- Cause: dictionary-only assumption on a host field whose valid wrapper representation is a string.
- Evidence: exact source reproduction above and failed candidate state; verified for this shape bug, unresolved for corrected host behavior.
- Routing positive: new early handler touches tool_input before normalization; review every host input representation.
- Routing negative: well-formed direct shell dictionary already reaches exact approval and independent verification; do not diagnose that as a wrapper-shape failure.
- Execution positive: non-recovery wrapper returns to the ordinary normalization/enforcement chain, confirmed by a real adapter subprocess and candidate proof.
- Execution negative: swallow all exceptions or treat unrecognized input as authorized recovery.
- No knowledge-base source was modified. This report is a review candidate, not independently attested knowledge.
