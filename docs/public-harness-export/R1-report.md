# Public Harness export — R1 local repair and verification

Date: 2026-09-12. **Bounded local verification passed; public release not accepted.**

## Delivered

1. Empty memory queries now check for entries before importing NumPy or loading
   an embedding model. They return `[]` without embedding, downloading or
   mutating memory. Missing/corrupt schema still errors, caller-owned connections
   remain open, owned connections close, and nonempty search retains its model
   and embedding behavior. Four new tests plus existing memory regressions pass.
2. The public candidate derives VERSION from the source Claude manifest. All
   eight Claude Hook events / nine handlers are preserved and routed through
   a reviewed launcher. Both wrappers validate the Python/PyYAML requirement,
   prefer the configured private runtime venv, set UTF-8/no-bytecode, reject
   unknown arguments and preserve the child's stdin/exit status. The POSIX
   process test exercises all eight underlying entrypoint files. Windows
   execution has not been claimed.
3. Public tests now require the full event inventory, not the old three-handler
   subset. No failing assertion was deleted: the exact existing assertion is
   upgraded to nine handlers plus all eight event names. Unexpected source test
   or Hook command drift prevents the adaptation.
4. Added a data-free normative contribution guide and full-Harness candidate
   README. Neither is copied from the formal corpus. The formal knowledge
   manifest still contains zero documents.
5. Seven files receive explicit synthetic example/identity substitutions. The
   export manifest records each original and transformed content digest and
   preserves executable mode. Source files and original failure evidence are
   not rewritten by the exporter. Actual business names and the identified real
   session UUIDs no longer appear in these exported regression examples.
6. The private probe driver records executed test counts, rejects zero-test
   discovery, retains failed/timed-out probes as failures, and permits exact
   additional test modules/methods. It cannot push or install into production.

## Frozen source and evidence

- `509e99e876b4f24df40af1a3603bb9a8eb70743a`: exporter, public overlay and empty-memory fix.
- `2564020e5b07a9d360e36b003f3c6ca1c4b6fb09`: final exported source; Hook contract
  adaptation, synthetic provenance and mode preservation.
- Public baseline unchanged: `c966bae1477423ee3a64fd2a6d02fdcb91a43913`.
- Candidate: `.sulde/public-export/review-004/tree`, **594 files**.
- Private manifest: `.sulde/public-export/review-004/review.json`.
- Manifest SHA-256:
  `0aabb2a772761f992f8b985f3b77fb01229b2331f6f6de3dd20392d59ed05e75`.
- Primary probe evidence: `.sulde/public-export/validation-004/results.json`.
- The later report/probe-runner commit changes only private verification inputs,
  not the exported source snapshot above.

## Actual results

| Verification | Result |
|---|---|
| Exporter, path/data boundaries and real POSIX launcher transport | 19 tests passed |
| Exported candidate targeted regressions | 147 tests passed, zero failed |
| Existing public toolkit | 10/10 passed (included in 147) |
| Empty KB/memory initialization | Passed, no formal data imported |
| Actual MCP stdio initialize/list + KB and memory queries | Passed; both searches returned `[]` |
| Claude package | Passed |
| Codex POSIX and Windows packages | Both passed |
| Official Codex plugin structure validator | Both packages passed |
| Scoped private-source memory regressions | 4 new + 7 noise + 3 embed-actor + 9 mixed-host passed |

The final bounded probe run took 12.093 seconds total. The MCP process covering
initialize/list and both empty queries completed in 0.644 seconds. The original
equivalent probe failed after 39.656 seconds of unnecessary model-loading
retries. These are single-run observations, **not a general latency benchmark**.

The 147 candidate tests include corpus (5), common index (8), MCP entry (9),
knowledge history (5), public toolkit (10), session continuity (4), memory graph
quality (19), graph audit (5), interventions (75), empty startup (4), and three
targeted Guardian cases for session isolation / rollout-based recovery identity.
Do not add overlapping private-source reruns to this count as unique coverage.

## Privacy review and remaining release gates

All **399 formal corpus input files** remain excluded. The candidate's
`knowledge/` contains only generated empty metadata and the new generic
contribution standard. Project memory, vectors, production ledgers, receipts,
internal reports and private Git history remain outside the candidate.

The scanner now has **41 review findings**, down from the initial 95. This is
not a count of leaked secrets: 14 are identified synthetic negative samples or
scanner syntax (example usernames/Windows paths, a deliberately fake token,
a generated intervention-shaped ID, and key/path redaction patterns). They
remain visible rather than being silently suppressed by a broad exemption.

Publication still requires:

1. **Portable, verified executable identity.** The audited Codex executable and
   its tests are tied to a private-machine path. Replace that with an explicit,
   verifiable host configuration while retaining version/help/content identity,
   proposal/grant binding and clear failure behavior. Do not use an unchecked
   PATH lookup or a fake placeholder to silence the scan. This has downstream
   installer and Agent-runtime consumers, so it needs coordinated regression.
2. **Remaining machine/repository metadata.** Generalize legacy launchagent and
   staging path consumers, private repository URLs/names and their relevant
   regression assertions. Preserve coherent execution/verifier path resolution.
3. **Synthetic fixtures.** Replace the two excluded production-derived fixture
   dependencies, or explicitly separate private historical acceptance assertions
   from public runtime regression. Do not copy private ledger/report payloads
   merely to make discovery pass. Check remaining corpus-dependent evaluations.
4. **Final whole-candidate verification.** Full candidate source tests,
   isolated bootstrap installation and real host Hook/approval checks remain
   open. Windows package generation is not Windows runtime acceptance. Native
   approval of the exact target/snapshot and public publication are later gates.

No main/dev merge, remote push, production installation, public checkout change,
formal knowledge write or project-memory migration occurred in R1. Private
`main` remains `bd216b3d29e37b1aaf0e6be0c930b5221a925562`, `dev` remains
`e61683c08aaf97db3e8e9d105ea3154ec217061c`. Existing main `.ua` changes remain.
The task branch is retained, not treated as a completed/merged resource.

## 沉淀候选更新（保留私有任务内，未写正式知识或项目记忆）

The baseline report's empty-store root cause is now **verified with a fix**.
Its constructed execution-positive case is backed by the real MCP stdio probe:
empty results, no model cache needed, and no production memory access.
The negative case remains preserved in `validation-001`. Missing schema and
nonempty model requirements continue to fail/execute according to their original
contracts. This is the evidence transition; it does not convert local candidate
tests into production installation acceptance.

Additional workflow observation: a launcher migration can preserve execution
semantics while intentionally expanding an old test's inventory. The correct
public adaptation tests the full event/handler set, actual stdin and exit-code
transport, and rejected unknown selectors. Merely changing a numeric assertion
without those checks would be insufficient evidence.
