# M1: individual host reload works; first migration is not production-ready

2026-10-06. Revision 12, baseline ab8b419; tested HEAD
222b1b86d0627e611f64ff8c825bfbc9a306edf0. Status: bounded-experiment-review-passed;
global migration and production acceptance remain unverified. No product source,
migration gate or production state changed.

## Outcome and actual observations

The real installed Codex 0.160.0 app-server can reload a previously loaded thread's
Hook commands without restarting that process. This requires a reload in **each
observed host**, after the new exact Hook hashes are trusted. Neither successful
plugin registration nor plugin/reconcile was sufficient in this experiment.

| Stage, in execution order | A callbacks | B callbacks | New C callbacks |
| --- | --- | --- | --- |
| Normal legacy control | 0.0.1, five events | 0.0.1, five events | not started |
| Official plugin add 0.0.2; old cache absent; C trusts new hashes | none | none | 0.0.2, five events |
| plugin/reconcile on A, response changedPlugins=[] | none | none | not exercised |
| config/batchWrite reloadUserConfig=true on A | 0.0.2, four events | none | not exercised |
| Same reload on B | not exercised again | 0.0.2, four events | not exercised |

Every observed turn's actual unified-exec `printf m1` returned exit 0. In the five
no-callback observations, neither the fixture trace nor host Hook-completion
notifications contained callbacks. Thus successful tool execution alone cannot
establish that a Guardian Hook protected it. This is a synthetic-plugin coverage
gap observation, **not a claim that any production business command bypassed Sulde**.

A PID 10753/thread 01a11071-a59a-7282-accc-98b67fe1798d and B PID 10766/thread
01a11071-a5e4-7b71-94c3-d092397b98d2 remain identical across their turns. C PID 10809
starts after plugin replacement and before explicit old-host reload. Callback
records bind event, session/call, physical script, script SHA256 and monotonic time;
host notifications also bind thread and turn. The same probe source is deliberately
used at both paths, so its content hash alone does not identify a version: command
version and actual physical target are needed as well.

Five-event controls include SessionStart, UserPromptSubmit, PreToolUse, PostToolUse,
Stop. After reload the same existing thread has four turn events: SessionStart is
not replayed. PermissionRequest was registered but never exercised. None of these
observations prove all six Sulde production events or Guardian decisions.

## Interpretation and limits

- Proven: per-observed-host hot reload is feasible, and reloading A does not refresh
  B. This corrects any unqualified claim that existing threads must always restart.
- Proven: official add removed the old cache before these old-host observations;
  plugin/reconcile alone did not restore their callbacks. All updates used supported
  CLI/RPC surfaces and exact synthetic hashes in the isolated home.
- Not proven: whether the missing callbacks arise internally from cached trust,
  stale registration, missing cache, or their combination. New-hash trust was written
  through C before the old-host turns; A/B may retain different in-memory config.
  Do not turn this observation into an unsupported single-code-path root cause.
- Not proven: a global census/admission barrier, replaying in-flight events, the
  prune-time interleaving, rollback with old live callers, or real product trust and
  install. The new caller tests only post-registry/pre-explicit-old-reload.
- The parent owns each fixture's stdio RPC connection. This does not show that Sulde
  can obtain a control connection to arbitrary already-running CLI/Desktop hosts.
- No production authority is inferred from fixture trust writes. Approval never and
  danger-full-access apply only inside the official outer OS isolation; the sole tool
  command is fixed printf, the model is a loopback deterministic Responses fixture.
  Existing user processes are never signalled. Windows is outside this experiment.

## Durable evidence and cost

Official runner records under `.codex-agent/s3c-m1-evidence/formal/`:

| Record | Tested HEAD | Result | Wall time | Log SHA256 |
| --- | --- | --- | --- | --- |
| 20261006T085916.065751-55ba833f5a1e | 030b539 | 3 tests completed, no input drift | 7.906s | 77a509d6ac3dd042d2f4f43de86c921478cb0a647248d7f9e96898b8403a71b1 |
| 20261006T090042.859022-4d3750365670 | 222b1b8 | 3 tests completed, no input drift | 7.866s | 39c871a67c27fe6331427ed766fb6dc1aa19b9547b684dc9e473023b49e89f26 |

Three tests = one observation matrix plus two encoding-guard checks, not three
production acceptance scenarios. The matrix asserts valid normal controls and tool
completion, then captures migration outcomes rather than asserting every migration
succeeds. Independent readback is required to interpret those observations. The
official planner labels risk=refactor because it sees the new fixture; the recorder
explicitly selects targeted scope and full_suite_satisfied=false. This is intentional
for tests/docs-only work, not satisfaction of a product refactor's release gate.

The final run records `codex-cli 0.160.0` and the resolved codex.js launcher hash
61b0194f3bb6534439c8d26a3ed57d0805f84b884588b761795323eeb92fcf70.
That is a JS launcher hash, not a seal of the complete native binary dependency tree.
The two raw logs retain callback identities, host notifications, RPC replies and
owned-process stderr (empty). Source bytecode cleanup removed zero files before/after.

A preliminary experiment completed in 4.970s but its tool output was truncated and
was not durably archived; it is not acceptance evidence. The first durable run added
script identity/time and the B control after A reload; the final run additionally
recorded host version/launcher identity. No external/paid model calls, no external
network actions, no full-suite rerun, no product changes. Coordinator reasoning/token
cost was not separately metered and is unknown, not zero.

## Minimal first-migration contract (design only)

Independent review by the separate update_review agent read the fixture, both
durable records and this report, independently recomputed log hashes and asserted
all five callback/no-callback phases, PID/thread continuity and physical targets.
No blocking finding; no experiment rerun. Its approval is of evidence and stated
boundaries, not an authorization or acceptance of global migration.

Keep the existing legacy rejection gate. M1 does not authorize implementing or
applying a first-migration transition. The transition must have these obligations:

1. Bind old/new installation identities, exact registration/trust definitions,
   candidate identity and migration transaction ID. Preflight before production
   writes. Discovery can never create a fresh-lineage attestation for a legacy root.
2. Establish a supported boundary that prevents unswitched callers from performing
   material work while registrations/cache/trust change. A process list, heartbeat,
   empty thread list or successful plugin/reconcile is not that boundary.
3. If a supported per-host control channel and complete caller coverage are available,
   reload and verify actual new-entry callbacks per caller, including a boundary new
   caller, before releasing admission. Bind real Guardian denial to both loaded module
   and artifact identity in the later product acceptance, not this synthetic probe.
4. On partial reload, missing coverage, trust refusal or crash, do not report ready.
   Restore a verified usable registration/entry while retaining the boundary; if
   recovery cannot be verified, remain recovery-required. File rollback alone does
   not prove already-loaded callers were restored. Never clear old effect uncertainty.

**Next decision is bounded:** a hot first migration is not justified by current
evidence. Choose a supported complete-caller barrier/control channel, or an explicitly
approved one-time maintenance migration with independently verifiable quiescence and
reopening. Do not silently stop sessions or turn a human's assertion into an automated
proof. If neither can be established, retain the old production install and report
the host prerequisite; do not keep repeating the same matrix or add another general
permissions control plane. Ordinary later stable-to-stable updates are a separate path.

## Sedimentation candidate (not written to the fact KB)

- Context: shared plugin cache updated while two real host processes retain loaded
  threads. Evidence status: verified for this isolated host mechanism; internal root
  cause and all-caller migration remain inconclusive.
- Routing positive: exact registered/trusted replacement plus per-host reload and
  actual callback identity. Routing negative: successful add/reconcile alone.
- Execution positive: unchanged A/B PID+thread execute cache-external callback only
  after their respective reload. Execution negative: tool exits 0 with no callbacks;
  reloading A cannot stand in for reloading B.
- Do not generalize this into host-wide reachability or permission to stop user work.
