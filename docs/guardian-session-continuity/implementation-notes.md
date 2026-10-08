# Implementation and evidence boundaries

This is a development candidate, not production acceptance.

## Lifecycle projection

The authoritative signed observations remain in `host-capabilities.jsonl`.
Per-provider/session HMAC-signed indexes retain original timestamps, generation
identities, recent hooks and a trusted lifetime start. Reads scan a bounded delta
or tail; they never create a lock or repair history. Publication is nonblocking
and per-session, after the original append. Source replacement, torn rows,
missing source, changed checkpoints and bad signatures cannot invent evidence.

Explicit `rebuild-host-observations` is Agent-owned derived-data maintenance.
It has no arbitrary output directory, never edits original logs, and resumes
through signed segment checkpoints. It is not a doctor side effect and not a
permission/effect reconciliation command. Errors report inconclusive; they do
not pause a task or settle debt. Full-prefix validation happens only here.

Committed handoff/adoption/release writers record signed non-authorizing edges
after route publication. A current exact Pre/Post pair must match both loaded
module and artifact identities before an old workspace's lifecycle fact can be
used. No approval capability, task grant, pending effect or authority is carried.
Unknown or corrupt lineage is observation degradation, not fallback permission.

Historical edge recovery is deliberately limited to the current edge when its
original paired decision/execution or release evidence survives. It does not
claim recovery of an arbitrary missing historical chain. Full keyless or lost
audit reconstruction remains inconclusive. An already-valid historical fact is
not a fresh SessionStart and retains its original time.

The HMAC/provenance key and control writers remain trusted, as in the existing
host contract. These projections are not a new security boundary against an OS
owner rewriting the key, runtime and all source authorities. Index file fsync
and atomic replacement provide crash-safe publication; loss of an unpersisted
directory entry is recoverable telemetry loss, not execution authority.

## Native acceptance

The new test stages and installs an artifact in independent candidate roots,
discovers/trusts it using actual Codex CLI APIs, and drives actual unified exec.
Only the model-response stream is a deterministic loopback fixture. No external
model request, business-system replay or injected Guardian proof is used.

One native session executes a data-method local write. Its real observations are
aged out of the global tail; a fresh candidate CLI rebuilds the derived index,
with the source SHA unchanged. An independent low-risk target proposal is
applied, then the formal registered-worktree adoption route commits. A real
target-workspace tool pair makes lifecycle continuity observable in another fresh
candidate process. Malformed composition and unknown receivers deny their call
but permit the following ordinary write. The final destructive v2 probe is
pre-denied and binds the actual denial to both runtime identities.

This does not prove Windows live behavior, Desktop behavior or a production
installation. Static skill-catalog refresh is distinct from Hook continuity.

## Verification retention

`verify-session-continuity.py` uses the official OS-isolated runner and retains
private per-run logs and summaries under the task's `.sulde/data/` directory.
Reports include source content identity, base HEAD, output digest, exit status,
elapsed time and structured native/performance evidence. Report-only documents
are excluded from their own source digest. Generated logs/JAR/TLC states are not
committed. A changed source invalidates that run's acceptance automatically.

TLC models are offline protocol checks, not proofs that Python or the host follows
the model. Positive models and intentionally defective variants are both checked.
The test suite and real native evidence remain separate required layers.
