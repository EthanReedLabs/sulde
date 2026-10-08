# Codex 0.160.0 compatibility — scoped candidate ready for independent review

## Outcome and boundary

The used CLI protocol and permission boundaries passed this macOS, zero-model
audit. Candidate-awaiting-independent-review; not a production installation,
Windows acceptance, general Agent capability result, or full-suite release verdict.
Base: dev `3e7bdee331df03a45b947ddc5b7cb2ef19c7af76`.
Task: `task/codex-01600-compat-20261003`, human-approved revision 3.

The prior installed runtime's refusal of 0.160.0 is the expected old exact-version
boundary, not a reproduced B2 defect. The candidate supports exact 0.160.0 while
continuing to reject 0.155.1, 0.159.0, 0.160.1, 0.161.0, other historical versions,
decorated/unsuccessful version outputs, identity and authority drift. No range gate.

## Actual change

- Production: `codex_cli_contract.py` exact pin 0.155.1 -> 0.160.0 only. Installer,
  runtime, broker and Hook policy implementation did not need compatibility edits.
- Explicit version fixtures and overlay compatibility statement migrated; historical
  release reports preserved. Tests retain/reinforce rejection assertions.
- Audit runner supports a separately declared observed target (audit-only, never
  execution authority), external private evidence root and bounded evidence reuse.
- Added a stand-alone actual OS sandbox audit and final evidence readback/sealing
  tool. No use of SULDE_TEST_MODE to turn the real CLI gates into fixture passes.

This is not compatibility inferred from a version-string replacement: the actual
0.160.0 CLI consumed an isolated staged runtime authority and ran the host/Hook
checks below. Installation remains a separate authority and acceptance boundary.

## Evidence

Private evidence root:
`/Volumes/Optimus/Sulde/tasks/codex-01600-compat-20261003/`.
Each batch records its exit code, source hashes, CLI digest, command and elapsed
time. Final `SUMMARY.json` and self-excluding `FINAL-SHA256.json` bind the union.

| Batch | Result | Scope |
|---|---|---|
| baseline-surfaces | exit 0; 440 generated schema files | Actual version/help/schema, isolated CODEX_HOME; no model |
| baseline-injection | 59 passed | Existing identity/broker normal controls and rejection invariants |
| candidate-injection | 64 passed | Same broker/binding suite plus installer/runtime/candidate version and help rejection cases |
| candidate-entry | 3 passed; 21.94 s | Real CLI pipe/PTY, staged-runtime authority, actual app-server/unified-exec/PreToolUse, Git lifecycle |
| candidate-native | 19 passed; 70.65 s | Real PostToolUse, composition and session paths; synthetic receipt tests separately scoped |
| candidate-os-boundary | 19 actual OS operations | 2 exact owned-write positives; 17 denied escape/destructive/network negatives |
| candidate-regression | interrupted -15; 396.05 s | Preserved original partial batch, never labeled suite success |
| candidate-regression-remainder | 151 selected: 148 passed, 3 skipped; 124.25 s | Completes union with 134 byte-equivalent explicit prior passes |

Affected regression union: **285 unique cases, 282 passed, 3 skipped**. Counts
overlap with other audit batches; do not sum them into an inflated test total.
Two skips are older environment-gated real-CLI entries; the new explicit opt-in
live audit executed their pipe/PTY and staged-runtime preflight behaviors. Third
skip is native Windows PowerShell, still unverified.

### Why the regression was stopped and resumed

The old module-level selection discovered the same base installer methods through
two pure-addition subclasses. Their fixture/setup methods are not overridden;
108 inherited duplicates repeat the expensive crash/recovery matrix. Stop affected
only verified test process group 44799, not other sessions or production processes.

The amended audit selector executes the base cases once plus every subclass-owned
case; it refuses deduplication when a subclass overrides base behavior. Reuse checks
CLI identity/version, interpreter, umask, script/test inventory and bytes plus original
log digest. Only exact complete one-line unittest OKs qualify: no partial line,
standalone provider 'ok', skips or interrupted case. The final readback checks
reused and newly selected sets are disjoint and cover the entire unique selection.
This is scoped audit tooling, not a new global caching policy or removal of tests.

## Real protocol and boundary observations

- Canonical help digest:
  `b72404bc85056ab186f47d1c0e24fc95a98d68296e5c86151c9e5eaa1e07abb7`.
  Pipe and PTY observations agree. Exact stdout identity excludes a known stderr
  PATH-alias diagnostic; other help/diagnostic drift remains rejected.
- Installer -> staged authority -> fresh candidate runtime: strict profile parse,
  Hook parse, stdio app-server initialize succeed; re-signed broker drift rejected.
- Generated ThreadStart response retains required cwd/approvalPolicy/sandbox/thread
  fields; CommandExec retains command/cwd/timeout/sandbox inputs. New provenance
  fields do not justify changing enforcement. Actual entry tests, not schema alone,
  establish the bounded compatibility claim.
- Real PreToolUse proof:
  `4564f52fc91428caea2d23970476b28c217174111967745c8eeff43df9b64a1c`.
  Artifact generation `0.2.5+codex.20260928133227-06ce966a8d:1638d80346226a17013ca5155de9c87a22d6fd2963ec8bd09ecf6fff9bbd5844`;
  loaded module generation `4f723803be8759d00d7fc98687e01f5612bc3fb5e77dfb2aa4858222993e1e30`.
  Positive write executed, destructive negative denied before execution, marker
  absent. Ordinary outside-plan local write remains observable as existing policy
  requires; this is distinct from a managed child's exact owned-path sandbox.
- Single-seatbelt probe independently proves the managed native profile's exact
  write boundary, including tmp, adjacent/parent/symlink/pycache escapes, Git/control
  deletion, rename/replace and network denial. Its envelope is explicitly synthetic;
  it is not claimed as an installed deployment receipt or human approval.

Official context: [App Server](https://learn.chatgpt.com/docs/app-server) and
[Security](https://learn.chatgpt.com/docs/security). Current online docs cannot
establish a historical/local binary's behavior; locally generated schema and actual
host runs above are the specific-release evidence.

## Important remaining distinction: launcher vs compiled executable

The NPM JavaScript launcher hash is still
`61b0194f3bb6534439c8d26a3ed57d0805f84b884588b761795323eeb92fcf70`,
also recorded in the 0.155.1 audit. It loads a platform dependency; its unchanged
bytes do **not** prove the compiled CLI stayed unchanged. The current arm64 payload
hash is `112fae7a5a1223e673c8a1791d32338f37df8b527ff1159bb8adac6c4dbf1b4b`.
The final readback records both and checks both report actual 0.160.0.

The existing effective-version preflight caught this upgrade correctly. Stronger
transitive executable-identity binding is a separate design follow-up; this task
does not claim that a wrapper digest closes every dependency/TOCTOU risk.

## Release handoff

No production install/cachebuster, main/dev merge, push, model request, CLI update
or downgrade, global host config edit, business action or formal KB write occurred.
Previous real-Agent task remains unverified with its two-call budget unused.
Review this candidate, then separately authorize integrated candidate installation;
recheck actual CLI identity at promotion and live current-generation Hook behavior.
Only after installation resume the frozen real-Agent sample. Do not replay prior
installation receipts or call protocol success an Agent behavior result.

## Sedimentation candidates (not written to KB)

1. **Verified:** module-level discovery repeats inherited expensive installer cases.
   Route positive: pure-addition subclasses and identical base setup/methods;
   route negative: overridden setup/helpers or genuinely different environment.
   Execution positive: retain each base test once and every added case, explicitly
   map omitted duplicates and verify reuse input/log hashes. Execution negative:
   count interrupted output, skips or same names as equivalent success.
   Evidence: original/remainder logs and selection/reuse metadata.
2. **Verified observation; wider fix inconclusive:** stable NPM launcher bytes can
   dispatch a newer native payload. Route positive: actual --version differs while
   wrapper hash matches; route negative: direct content-pinned standalone executable.
   Execution positive: preserve runtime exact-version refusal and record payload
   identity; execution negative: trust wrapper hash alone or remove version gates.
   Evidence: historical 0.155.1 report plus current version/source/payload readback.
