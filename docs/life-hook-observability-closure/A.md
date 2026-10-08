# A — Hook failure observability

Intent: `interactive:db613882e8d8ba05a196234d`. Base: `f687193` (remote dev readback matched).
Scope: task worktree development and isolated tests only. Production is not repaired by this commit.

## Evidence and attribution

The original rollout for session `019fee7c-fb72-7252-a4e7-9349cbc9372a`
identifies **iquokka**, startup CLI 0.147.0. Readback found 10,982 event messages,
9,411 response items and 195 world states, but no structured Hook execution result
events. The read-only host logs query for this thread also returned no Hook-target
rows. These observations cannot exclude Hook failures or reconstruct every loaded
version. No business action was repeated to reproduce an error.

Current configuration inventory (configured/trusted does **not** prove loaded):

| Source | Event / matcher | Entry / version | Evidence status |
|---|---|---|---|
| iquokka project `.codex/hooks.json` | PostToolUse / Write\|Edit | `bash /d/HarmonyProject/iquokkaApp/scripts/check-task-md-phase-split.sh` | Confirmed incompatible local path; file absent. Cannot explain every tool event. External repository read-only; patch deferred for exact approval. |
| Sulde current plugin | SessionStart, UserPromptSubmit, PreToolUse, PermissionRequest, PostToolUse, Stop | `scripts/run-hook.sh`; 0.2.5+codex.20260907071718-6e84c50faf | Current registry/cache verified; target session's actual loaded generation inconclusive. |
| Sulde legacy trust entries | SessionStart, UserPromptSubmit | old `hooks.json`, alongside current `hooks/hooks.json` | Trusted hashes remain; historical loaded generation inconclusive. Retired caches are not evidence of execution. |
| understand-anything 2.9.6 | PostToolUse / Bash | `node "${CLAUDE_PLUGIN_ROOT}/hooks/post-tool-use-auto-update.mjs"` | Enabled; runtime variable injection inconclusive. No third-party cache edits. |
| understand-anything 2.9.6 | SessionStart / all | shell stale-graph check, same environment variable in emitted reference | Enabled; loaded target-session snapshot inconclusive. |
| Figma 2.0.21 cached entry | PostToolUse / Write\|Edit | `./scripts/post_write_figma_parity_check.sh` | Cached declaration only; no corresponding enable entry in inspected config. Loaded status unknown. |
| retired cognee trust entries | PostToolUse, PreCompact, SessionStart, SessionEnd, UserPromptSubmit ×2, Stop | trusted legacy IDs | No current enable entry observed; historical execution unknown. |

Confirmed own-source defects: the previous recorder imports the failing runtime,
silently swallows its own failure, and hashes a missing module's **path** into a
purported module identity. Ordinary shell help is classified as sealed maintenance.
These defects justify the patches independently of the unlocated business exit 1.

## Changes and boundaries

- Independent standard-library recorder has no Guardian imports, contract or ledger
  locks. It preserves call/session/workspace/lane correlation as hashes and uses
  `unknown` for unavailable identities. Module bytes are hashed only when readable.
- POSIX and PowerShell wrappers forward child output and payload, retain child exit
  facts, and distinguish permission denial, child outcome and audit delivery.
  Normal Hook exit policy stays separate. Recorder outage never retries an action.
- The bounded SQLite buffer admits at most 2,048 events, has a 16 MiB page ceiling
  and a 50 ms lock wait. Duplicate IDs are idempotent. Saturation/unavailability is
  visible on stderr and readback; existing evidence is never evicted to hide a fault.
- Child output is forwarded, with only 8 KiB tails held transiently for categorical
  classification. Commands, prompts, tool results and raw output are not persisted.
- `--ingest-host-result` accepts the explicit normalized host schema when a host
  provides results; it does not invent a native host API or trust imported telemetry
  as authorization or effect verification. Automatic third-party host delivery is
  not available in the inspected session and remains a blind spot.
- Exact repository-owned help calls and valid Skill registration are distinct from
  sealed maintenance. Extra writer argv and malformed registration do not gain
  authority. No new ordinary Git or Figma control was introduced.

## Validation

`tests.test_hook_observer_closure`: 7 tests passed, including real subprocesses for
missing script, missing interpreter, exception, timeout, recorder unavailable,
normal output and policy denial; actual POSIX wrapper with missing adapter;
single-action counter proves successful action is not repeated after audit failure.
Real help executes in an isolated root without installing anything. Import tests
prove raw prompt/output fields are dropped and tool outcome stays unknown.

The larger A suite and content-bound evidence are recorded in `A-tests.json`.

## Unpassed / blind spots / approvals

- **inconclusive**: exact issuer and loaded snapshot of historical business exit 1.
  No full-host result API was observed. Pre-observer, no-interpreter and whole-tree
  host termination cannot be guaranteed by an in-process package observer.
- **Windows pending**: PowerShell implementation requires Windows CLI acceptance,
  including process-tree timeout. macOS success is not Windows evidence.
- **deferred**: project path correction and third-party adapter repair require
  explicit scope approval after source/host proof; no external cache modified.
- **production pending**: merge, push, formal installation, live business-session
  recovery and external synchronization remain separately approved operations.

## 沉淀候选

Evidence status: verified (isolated fault injection), historical attribution
inconclusive. Problem: a diagnostic recorder imports the same runtime that failed,
then silently swallows its own error and substitutes a path hash for missing code.
Route positive: tool succeeds while audit callback fails; require independent
telemetry. Route negative: explicit policy denial with intact audit; do not change
permissions. Execution positive: real failing process, unknown unavailable identity,
visible recorder outage, one successful business action. Execution negative:
blanket exit 0, forged generation, raw prompt logging or repeating successful work.
Single writer must deduplicate before knowledge-base admission.
