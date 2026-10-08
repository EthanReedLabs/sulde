# Heartbeat repair: production release and real observation

Date: 2026-09-23. Supersedes only the **not installed** phase status in README.md;
the root-cause qualifications and historical evidence boundaries remain valid.

## Result

The repair and version update were fast-forwarded into local dev. Installed source:
`7b7b9de363d56fc7f4ad9bc6718f8678a5a03355`.
Version: `0.2.5+codex.20260923070231-1c75e2322a`.
Generation:
`0.2.5+codex.20260923070231-1c75e2322a:52b868dc1e00490ed686cd4605e563655f07887cb6c9222a5e7b4284645336ef`.

Official installation, current-session live pre-execution protection, scheduler,
fresh-process MCP transport, and **one actual Codex heartbeat** passed. No remote
push or main modification occurred. This report/readback helper is a subsequent
documentation-only commit, not part of the installed source commit above.

## Scope and authority

Native revision 3 approval receipt:
`5e5a65d41feb12aca98ae4ff75104d2662598878ec3a7026ee3cb446669931b5`.
The card declared version/install maintenance, local dev merges, a single
`heartbeat --beat --observe-only` using the existing Codex provider with at most
one generation plus one bounded compression, independent readback, reporting and
current task-resource cleanup. No self-repair dispatch, historical problem closure,
new provider, external synchronization or arbitrary control-plane edits were included.

All six input hashes in regression-evidence.json were rechecked unchanged before
release. The prior 84-test passing record was reused; no redundant full suite ran.
The official cachebuster helper changed only the version field; plugin validation
and Git whitespace checks passed. Cachebuster and install v2 grants were each used
once and independently became `system_verified`; no pending verification or open
intervention remained. No manual production manifest/cache/ledger edits occurred.

## Candidate and installation evidence

Candidate: `heartbeat-release-20260923`.
Receipt: `4f7b6da72e22712e4f8a2c43387e4c1bdfbb6dd358c6f0afa230aedf3944c42b`.
Prepare: 2.125 s; verify: 18.125 s; both exit 0. Exact candidate source matched
the dev/source commit above. Promotion ran once and exited 0.
Installer-internal total: 44.728 s, including 25.442 s snapshot/prepare. These are
phase timings, not total Agent/human-approval wall time or a measured overall speedup.

Candidate verification included actual CLI app-server/unified-exec/Hook protection,
packaged MCP and isolated scheduler entrypoints. Candidate-only native human UI
and production scheduler remained unobserved by design. Initial untrusted Hook
discovery was not relabeled trusted; real candidate canary used its candidate trust.

Production doctor: ready; deployment generation verified; owner active; scheduler
16/16 loaded with no failed/missing/retired labels. Native pairing settled;
effect debt clear. Six required Sulde Hooks are uniquely enabled/trusted.
Current-session negative canary was actually denied before deletion; official
proof finalize succeeded:

- Proof `af40e42ca71a3b7b9569d8c0064999f1a700fc4db9aae773050dd97fa88b4247`.
- Actual PreTool event `e8c813731e2137decfa0ccfc`.
- Loaded module `4f723803be8759d00d7fc98687e01f5612bc3fb5e77dfb2aa4858222993e1e30`.
- Artifact generation exactly matches the generation above; no fabricated event.

A fresh MCP server process followed the actual Codex stdio projection: initialize,
tools/list and kb_status passed (8 tools, 3 responses, 1.059 s). The existing
conversation MCP was not reconnected. The returned background snapshot was still
degraded; transport success was not used to overwrite its health value.

## Real production heartbeat and independent readback

Executed once using the newly installed runtime and managed Python, with
`SULDE_RUNTIME_PROVIDER=codex`, bytecode disabled, `--beat --observe-only`.
It used the existing headless Codex runtime port, not a fixture or direct callback.
No retry or second canary occurred. Exit 0 alone was not accepted as proof: the
read-only helper inspected production state before/after in separate processes.

| Observation | Before | After |
|---|---|---|
| Sequence | 133 | 134 |
| Mode | degraded | result |
| Failure reason | self_fixed_sections_changed | absent |
| Compression attempts | 0 | 0 |
| SELF characters | 7614 | 7825 (within 8000) |
| Fixed bytes | 7190 | 7190 |

Fixed-prefix SHA-256 before and after:
`5d4901ac73260c416886e9e24ab422fe8c2c91dc66840a09b53cb0f39ba54d31`.
Installed heartbeat SHA-256 matched the accepted source:
`4de930bddb88c7132e80aa8ce3d407d39e5f1d47bf385c774b2eb1c29887036f`.
Beat 134 observation timestamp: `2026-09-23T08:39:46.970261+00:00`.
Machine counts: window entries 143, window edges 0, totals 48587/2320, new log lines 50.
The global SELF changed only within the mutable suffix; no rejected model prompt or
complete SELF body was copied into the release evidence.

## Still not proven / retained follow-up

- One actual successful heartbeat verifies this bounded production example, not
  an indefinite recurrence-free period or every historical failure's root cause.
- LIFE state readback was generated at 08:36:29Z, before beat 134, and still projected
  beat 133. Its degraded aggregate is retained, not rewritten by this acceptance.
  Observe the next normal lifecycle/snapshot refresh before claiming its projection
  reflects the new beat; no extra lifecycle dispatch was added in this stage.
- The historical broad heartbeat problem still has 50 occurrences, status open,
  no repair_commit and no independent closure receipt. That count includes the
  broader failure category and is not 50 proven instances of the same root cause.
  Do not close it merely because this one heartbeat succeeded.
- Background lack of a current human lane and unverified external synchronization
  remain distinct from session-bound interactive readiness. No all-LIFE or entire
  Guardian program closure is claimed.
- Session/Prompt continuity is telemetry, not new authority. Static Skill catalog
  pickup remains a new-session matter; the current session's live Hook already passed.

## Durable evidence

Ignored private root archive: `.local-evidence/heartbeat-release-20260923/`, outside
the task worktree, directory 0700, JSON files 0600. Contains prepare/verify/promote,
doctor, live proof, MCP and before/after heartbeat readback plus command result.

| File | SHA-256 |
|---|---|
| verify.json | e5504b98ed8bec96e3c9d28b25077729bdf52b93b4dcbe004542a87fc99d554c |
| promote.json | e4176b0f70b6b5431c13edba745ae789c955fffc4041c7dbc1e26b75ea9f2819 |
| doctor.json | 2b51a7496e0cb39978066da11ed328afb351bf9922f2e97efc108b1688853d58 |
| heartbeat-before.json | d850b77cd46fe741ec6a69c36a61453ed78efffba4af64901fa94f6e50a18de6 |
| heartbeat-after.json | 19d1bdbde84613a5e0b6898ef21f93e75303a017526d5a0720ae4e9970233686 |
| heartbeat-command.json | 676d300ab25081dc2bcbbdf405e01ccc6691484c23d31e36fa09a9b25b80db15 |

## 沉淀候选 update

The existing README Layer1 candidate now has one observed production execution
positive: real model response, fixed-prefix digest unchanged, sequence advanced,
failure reason cleared, no compression/retry. Historical per-incident cause and
long-run reliability remain inconclusive. Independent knowledge verification rules
influenced the fresh-process readback and dual-generation canary checks; no formal
KB or memory graph write was performed.
