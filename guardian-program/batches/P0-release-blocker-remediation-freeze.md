# P0 Release Blocker Remediation — Frozen Scope

## Authority and baseline

- Program: `guardian-remediation-r97`
- Coordinator / single writer: `guardian-coordinator`
- Source baseline: `0dce1005d244af7e5b509513226bcfe8a2f11b4f`
- Integration branch: `dev`
- Successor: `T27-release-blocker-remediation`
- Superseded release task: `T26-production-session-recovery`
- Production contracts, approval stores, effect ledgers and historical event logs
  remain append-only inputs. They may not be edited, deleted, reordered or
  replayed.

## Frozen defects

This successor contains exactly three repair groups:

1. A resolved `abort` ends retry authority but does not prove external effect
   truth. Such debt remains visible and continues to block the same canonical
   resource across sessions, but it must not make every unrelated current lane
   globally non-operational.
2. A live `SessionStart` with no current prompt, or a session whose activity TTL
   expired while idle, is projected as a non-authoritative waiting state. It is
   yellow in user-facing status; no readiness fact is fabricated. Runtime,
   generation, contract, hook, approval or effect failures remain red.
3. The three observed scheduler failures are closed: the macOS system Python
   can parse the non-ASCII `auto-distill.py` entrypoint in the LaunchAgent
   environment, and mem-sync resolves exactly one branch upstream before an
   explicit pull instead of relying on ambiguous implicit pull configuration.

## Inherited release outcome

The successor also completes the original T26 delivery gates:

- independently verified `dev` enters `main` only after the full isolated suite;
- the official transactional Codex installer creates one new cachebuster and
  generation-fenced scheduler reconciliation;
- the exact sessions `019fee8b-bcad-7623-be8e-dd3743f69039` and
  `01a02cbe-3377-7ac1-a9e5-362def3fb765` produce real current-generation host
  evidence and can execute unrelated work without replaying the historical
  Figma download effects.

## Explicit non-goals

- No broad Intent Guardian refactor or additional decomposition task.
- No direct production cache patch and no manual LaunchAgent plist edit.
- No historical ledger settlement, deletion, truncation or synthetic callback.
- No Figma retry, reprobe or fabricated effect success/failure.
- No weakening of same-resource cross-session debt, typed native authority,
  material CAS or unknown-generation fail-closed behavior.
- No additional task unless a new independently verified release blocker is
  reported to the user and explicitly approved.

## Merge and release order

1. One isolated worker changes only the registered paths from the frozen base.
2. Focused tests and failure injections pass before the worker commit is merged
   to `dev`.
3. The exact integrated `dev` commit passes the complete OS-isolated suite.
4. `dev` merges to `main`; then and only then the official installer and
   generation-fenced scheduler reconciliation run.
5. Scheduler 15/15 and both exact live sessions pass before T27 acceptance and
   final program completion.
