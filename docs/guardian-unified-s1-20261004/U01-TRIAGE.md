# U01 installer WIP triage

Baseline: ac5dc9c. Status: needs-design-before-next-production-install.
This is a read-only comparison, not independent validation of the old draft.

The existing worktree `.worktrees/sulde-orchestration-iteration` is preserved.
Its uncommitted installer adds `_verify_journal_terminal_state` and rollback fence
cleanup. It is not safe to merge as-is:

- The draft parser checks schema/id/final stage but omits authoritative journal
  sequence, record hashes, previous-hash chain, full schema and metadata checks.
  Non-object JSON rows can also raise uncontrolled errors. The existing
  `install_transaction_journal.Transaction.read_records` enforces these facts.
- Simply requiring an existing terminal journal introduces a dead end for the
  legitimate crash window after fence publication but before `begin_transaction`.
  Current `_install_locked` publishes the fence before the journal begins.
- Conversely current `recover_only` treats missing transaction directory as
  proof that production never changed, even though disappearance/corruption is
  not that proof. The current normal fixture even uses a non-official transaction
  id (`orphan-transaction`), so it does not establish production identity safety.

Disposition: neither blindly adopt the stricter WIP nor declare current recovery
fully validated. Before a new production release, freeze the pre-mutation fence
and durable transaction publication protocol together, reuse the official secure
journal reader, and prove both crash boundaries. Missing/corrupt facts remain
unknown; a legitimate pre-mutation interruption needs positive durable evidence
for a bounded recovery, not mere file absence. Exact transaction identity and
independent postconditions must precede clearing a terminal fence.

Required cases: normal pre-mutation interruption; failure before/after durable
journal publication; same/foreign transaction; lost/corrupt/hash-mismatched log;
readback-verified rollback; committed transaction; repeated recover-only;
concurrent admission. Use the existing real installer fixture, not a handwritten
journal schema. Do not change production fences to demonstrate a test.

This S1 batch does not install or change installer protocol. U01 is an explicit
production-release prerequisite, not an excuse to merge an unreviewed draft or
prevent scoped source fixes from being reviewed. No old WIP or .ua file changed.
