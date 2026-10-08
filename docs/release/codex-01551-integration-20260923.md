# CLI 0.155.1 dev integration and isolated candidate

Date: 2026-09-23. Continuation of `codex-01551-audit-report.md`.

## Result

Local dev fast-forwarded from `c82d537642334645c4a08cd95f59f5c0aef86d14`
to `b0e14a431cde4ee2f0caa3e4035a0231213a1787`. Before merging, all recorded
audit inputs and the physical CLI executable still matched the accepted audit.
The official candidate prepare/verify chain on that exact dev passed. **No
production installation or promotion occurred.** No full test suite was repeated.

This integration report is a subsequent documentation-only commit, not a claim
that the candidate was prepared from a later report commit.

## Authority and preservation

- Same-session readable proposal revision 22 approved through native Allow/Deny.
- Approval receipt: `7fbbdad36c48efaa860bf82918ad9c3afb49f295461c2e975a3bd6519505c86c`.
- Scope: local merge, isolated candidate, private evidence preservation and report.
- No main merge, remote push, production cache/ledger modification, scheduler
  activation, CLI upgrade, formal KB write or old-worktree cleanup.
- Existing candidate runner reused; no new product code in this stage.
- Marketplace independently identified as local `sulde-local`, and its name
  validated with plugin-creator's official helper. No personal marketplace rewrite.

## Candidate proof

Candidate: `integration-b0e14a431cde-20260923T060954Z`.
Source tree: `598871b006e2cdabb840a904ecb2fedf94eab110`.
State: `verified`; `promotion_consumed=false`.
Verification receipt: `d4604dad9f918d2d5d103b2b0cc8dda935d7bc48f741a8f5003de075217a270f`.

| Phase | Exit | Time |
|---|---|---|
| Official prepare | 0 | 1.767 s |
| Official verify | 0 | 17.667 s |

The runner used OS write isolation against the production KB plus independent
HOME/CODEX_HOME/KB roots. Its process-guard write-attempt collection was empty.
This is the measured protection scope, not a global assertion that no unrelated
background process changed any user data during the interval.

- Artifact, isolated registry, actual Hook entrypoints and packaged/plugin MCP
  initialize checks are ready.
- Real app-server → unified exec → PreToolUse positive execution and destructive
  pre-execution denial passed, with the negative marker absent.
- Pre-execution proof:
  `e3d4b2f5db66c6346fb33deed5a3539bf629df7661752006e424e53f91352812`.
- Artifact generation:
  `0.2.5+codex.20260922005243-95a8cf2d92:b59f38733f11e47e49a3417a86ec11d24c367c99574d680dce7651d53c4e942f`.
- Loaded module generation:
  `4f723803be8759d00d7fc98687e01f5612bc3fb5e77dfb2aa4858222993e1e30`.
- Scheduler entrypoint used the isolated dry-run with 16 managed labels.

## Explicitly not proven

- `native_permission_ui=unobserved`, exit 78: isolated CLI has no current human
  PermissionRequest surface. Agent-policy activation is not human approval proof.
- `scheduler_host=unobserved`, exit 79: production labels intentionally not loaded.
- Initial Hook discovery reports untrusted sources before candidate-only trust is
  established for the real canary. Do not reinterpret that initial snapshot as
  production trusted status or invent a fully green initial inventory.
- Old tests used an outer OS boundary; this run is not new evidence of an inner
  workspace-write sibling/symlink denial. Refer to the earlier boundary report.
- Current production remains on its earlier installed bytes. The candidate's
  unchanged manifest version does not mean those bytes are already installed.
- Windows remains outside this macOS acceptance. Overall Guardian program closure
  and all historical health findings are not asserted.

## Durable evidence

Candidate state, verification receipt, and full prepare/verify logs are retained
under dev `.sulde/data/life-r1-candidates/` in the candidate and `-evidence` folders.
An additional private copy, together with the prior audit's successful and failed
runs, is stored at repository-local
`.local-evidence/codex-01551-release-20260923/` (ignored, directory mode 0700).
Every copied regular file was byte-compared and every copied symlink target was
compared without dereferencing. Inventory: 476 regular files, 6,156,886 bytes and
12 disposable CLI alias symlinks. The aliases are not standalone executable
archives or transferable authority. No evidence originals were deleted.

Typed inventory digest (sorted JSON rows, compact separators):
`cc730e4dc64462269f72afb879407bf29e948803bd9f46f1ae2d6f9b7e5934eb`.
An earlier diagnostic followed aliases and inflated the byte sum; it is not the
archive-size measurement or the accepted typed inventory above.

## Next step

Freeze the release's actual source/workspace identity, use the official
cachebuster helper under a new sealed maintenance decision, then prepare/verify
that final version and promote through the transactional installer. Keep the
existing production generation available until candidate acceptance succeeds.
Read back independent installation verification, scheduler ownership and current
session live Hook/approval evidence after promotion. Do not promote this isolated
test-host receipt as if it observed the real production prestate.

Temporary audit worktree remains available for release preparation; revision 22
explicitly excludes cleanup. Its contract is rooted in the dev worktree, so the
previously recorded cleanup routing mismatch must not be hidden with force-removal
or manual contract edits. Main and dev are kept clean after report integration.

## 沉淀候选

No new product root cause established. The existing schema/fixture knowledge rule
was applied by preserving the distinction between real execution proof, isolated
dry-run, unobserved human authority and production installation. Existing audit
Layer1 candidates remain in the preceding report; none were written into the KB.
