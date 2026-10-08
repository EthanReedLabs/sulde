# Evidence-bound external-effect recovery

capability_tier: deep
Baseline: dev ec60b61dbe7c2f83f8ed3d1bb3d9fb0ca885d71a.
Worktree: .worktrees/guardian-effect-recovery-20261004.

Confirmed case: an external Bash attempt became unknown, received eight reprobe
authorizations despite verification_kind=unsupported, then abort. A later SSH
remote mkdir was mislabeled unresolved_local_write and blocked as "same target".
Original and new SSH destination literals differ, but literals alone are not
proof of distinct resources (SSH configuration/aliases/forwarding can intervene).

Frozen scope:
1. Classify SSH execution at its actual transport boundary; remote mutations
   must not become local paths or read-only because of argument text.
2. Explain blocker relations accurately (proved same, dependency, unproved).
   Preserve conservative handling of genuinely unknown targets and alias history.
3. Reject futile reprobe before native approval when no executable verification
   contract exists; disclose missing facts through intervention report/card.
4. Provide bounded append-only recovery for an aborted attempt once a concrete
   verifier/resource binding exists, reusing identity CAS and existing native
   intervention authorization, not a blanket supersede or success assertion.
5. Cover normal paired cases, failure injection, native/Hook or CLI entry and
   affected tests. Archive baseline/candidate evidence under Optimus.

Preserve old events byte-for-byte; no production debt changes, remote calls,
plugin install, push, main merge or new model calls. Failed test setup is not a
defect baseline. Source repair is not production recovery. Original unsupported
debt cannot be called settled without new independent facts.

Continue to independent review within scope. Two attempts without new evidence
require a diagnostic-method change. Stop for missing authority, unsafe evidence
claims or required scope expansion. No full suite by default: shared recovery,
resource normalization and native approval consumers require affected regression.

Expected impact: intervention store/recovery projection, resource classifier,
native decision preflight, CLI and focused tests. Compare actual scope at closeout.
KB ap-0242 applies to the separation of approval/abort from external effect truth;
its read-only-debt clearing recipe does not apply to this external write.
