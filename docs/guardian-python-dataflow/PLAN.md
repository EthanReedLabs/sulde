# Guardian Python data-flow repair

Status: FROZEN. Base: dev `f034452def541d2f63660a19ec5725b87b9362e1`.
Capability tier: deep. Scope: development and isolated acceptance only.

## Outcome and boundaries

Repair false `unresolved-destructive-receiver` denials for exact string/bytes
operations, without approving arbitrary objects with a method named `replace`.
Preserve the original literal/list proof and add a bounded, forward-only string
proof. Track assignment order, trusted direct pathlib read results, and local
targets of eager comprehensions over literal strings. Opaque evaluation,
namespace mutation, rebinding and unsupported control flow invalidate borrowed
facts. Deferred function/lambda/generator execution is not inferred.

The effect classifier must still visit every argument and every other call.
An actual write remains local_write; a filesystem replacement remains
destructive; unknown destructive receivers still deny without a pre-execution
pause. No changes to policy, Git/Figma, receipts, production or business files.
No merge, push, production installation, or shared knowledge write this task.

## Acceptance

1. Sanitized BOSS read_text -> replace -> write_text and repeated immutable
   assignments classify correctly; read_bytes and pathlib aliases are covered.
2. Sanitized Vario literal-key comprehension is proved locally, including inside
   an otherwise opaque script. This does not prove the entire script read-only.
3. Preserve existing negative tests; add rebindings, patched pathlib, dynamic
   arguments, unknown iterables, deferred scopes and evaluation-order attacks.
4. Persist baseline/final test source digests, exact interpreter/dependencies,
   commands, outcomes, timings and log hashes. Failed runs are not reusable.
5. Run scoped and impacted tests using the official isolated runner, and an
   actual Codex CLI / unified exec / staged artifact Hook regression. Require
   real positive execution plus destructive pre-denial with matching loaded
   module and artifact identity, not a hand-constructed proof.
6. Compare classification latency against the exact baseline. No full-suite
   repetition for documentation-only changes; expand testing if affected
   integration regressions fail. Final report distinguishes isolated evidence
   from unchanged production status.

## Knowledge applicability

ap-0243 is analogous: invocation eligibility, physical effect and lifecycle
pause are distinct. Adopt that invariant, not its historical shell-composition
policy. Keep observations as a task-local sediment candidate; no direct KB write.
