# r16 first maintenance implementation — bounded source candidate reviewed

Final tested source: `f8a66f2` (2026-10-07). Three consolidated review findings
are repaired and independently reviewed; **not overall accepted or install-ready**.
Full product-entry migration, final full regression and production remain
unverified. Do not infer their completion from this bounded source result.

Production installation, main/dev, existing user hosts and production ledgers
have not been changed. No accepted/operational-ready claim. This is the original
r16 task, not an additional scope or repeated feasibility round.

## Genuine UI prerequisite

Owned Terminal window 5375; isolated run `20261006T124337Z` under
`.codex-agent/s3c-bootstrap-interactive/`. Read-only Terminal observation returned:

> You approved codex to run /Users/eric/ClaudePlugin/sulde-pro/.worktrees/
> guardian-update-continuity/.cod... this time

The same owned fixture's matching `benign_probe` tool result was exit 0 with
`BENIGN_MARKER_CREATED`; independent marker readback has `marker_matches=true`.
The host exited, no production installation was performed. Agent sent no approval
keystrokes or app-server approval replies. This proves the actual native one-shot
UI can be used; it does not approve a later installation or mint a reusable receipt.

Retain earlier observations: first probe stopped prematurely on speculative model
prefetch (invalid fixture result); a subsequent execution used persistent-prefix
approval (not one-shot proof); parent-repository discovery was corrected with an
independent Git root; run `20261006T112309Z` expired with zero provider calls and no
marker. Timeout is not Allow or Deny (KB ap-0245 read in full and applied).

## Source boundary

- `legacy_maintenance.py`: typed digest-bound input; exact roots, old CAS/cache,
  observed cohort/maintenance-host ancestry, bounded wait, deadline and one-use
  durable claim. No process-signalling capability. Unknown/new callers refuse.
- Frozen bundle executes held source bytes, including repository Python imports,
  rather than hashing then reopening a mutable worker. Sources are a complete
  catalog of release/KB/index Python modules. Interpreter/dependencies retain the
  existing candidate environment verification; not a new OS trust boundary.
- `independent_maintenance_host.py`: fixed local provider emits one exact worker
  command and may poll only its observed execution session. Official interactive
  CLI owns approval; prefetch is not completion; no client-side accept mechanism.
- Existing candidate and installation machinery retain receipt validation,
  deployment lock, rollback journal and recovery. Maintenance copies the verified
  candidate instead of executing a mutable source stager after approval.
- `maintenance-window` is distinct from fresh origin. Ordinary legacy migration
  still refuses. Future stable updates retain the original one-use claim and a
  committed transaction binding; only journal-bound retired aliases may retain
  legacy static metadata. New/unproven legacy paths still refuse.
- Installation result remains not operational-ready. Missing trust rolls back;
  physical installation alone cannot prove dual-generation live Hook coverage.

## Verification boundaries

Preliminary local checks covered context/held-source/provider contracts and real
installer transaction execution with synthetic host/candidate observations.
These fixtures do not create human authority or prove a production maintenance
window. Completed frozen-input records and review are listed below.

Invalid test/setup observations retained: fake Codex lacked `--version`; a test
used `/var` vs canonical `/private/var` for claim readback; a later ordinary-update
fixture accidentally restaged instead of consuming its prepared artifact. The
canonical claim handling is a candidate fix; fixture omissions are not old
production defects. No failing test was made green by relaxing trust/receipt/CAS.

Still outside scope: production cohort shutdown, actual production migration,
real new-host trust and live positive/negative Hook proof, Windows. Observing a
bounded process cohort is not a global admission barrier or proof against an
unrecognised/future caller; the approved maintenance-window limitation remains.

## Consolidated review, repair and evidence

Commits: `32992cb` implementation; `0e18cd4` three boundary repairs;
`f8a66f2` registry-source/cache identity correction. Subsequent report changes are
documentation-only. Official records: `.codex-agent/s3c-maintenance-evidence/formal/`.
Unique Optimus archive and independent readback: see `ARCHIVE.md`.

| Source / record | Result | Scope |
|---|---|---|
| `32992cb`, `20261007T030338.247879-ceec17f7f8c2` | 137/137, 744.908s | Initial affected regression; did not cover three review omissions |
| `32992cb` plus test-only counterexamples, `20261007T031652.857322-ecbaafb4a7fe` | 3/3 fail as expected, 106.675s | Actual installer reproduces omissions; product source unchanged |
| `0e18cd4`, `20261007T032059.524032-f70cd8e0b929` | 39 tests, 7 failures, 203.944s | Candidate regression: source/cache comparison; not an old defect or fixture excuse |
| `f8a66f2`, `20261007T032447.958171-7098a1b15369` | 39/39, 289.639s | Three counterexamples and paired normal/recovery cases pass |

All four records: `input_drift=false`. Final log SHA256 independently reread:
`2a9d4b6638669d9aed72e50c5823443fc00cccaf53bd3a69dc4bf2e9f1bfd461`.
Original 137-test log SHA256:
`209636327144f193b53f257de1d4654d286dbbdba37790021253218f5d24609c`.
Counts overlap; do not sum them as unique coverage. Neither is a final full-suite
certificate. Failed records remain unchanged.

Repairs:

1. Only first legacy migration: read CAS-bound deployment, refuse stable lineage,
   match active registry identity, check legacy registration at the canonical
   installed cache. Registry source and cache path are distinct producer fields.
2. Under deployment lock: validate receipt/identity/context and durably claim
   before canonical candidate publication. Candidate bookkeeping and the lock
   itself are not misrepresented as having no writes. No maintenance home/memory
   migration; identity-map checks use `allow_upgrade=False`, refusing an old map
   needing upgrade without rewriting pointer/map. Ordinary default is unchanged.
3. Consumer itself requires the complete Python source catalog and every digest.
   Missing/extra/substituted keys refuse; installer fixture uses the full catalog.

The source/cache mistake was exposed by valid normal controls and corrected
against actual CLI/CAS producer shape. The reviewer's preliminary predicate probe
mocked CAS and was not installer evidence; the subsequent three official actual
entry counterexamples provide stronger evidence. A single diagnostic replay has
no separate archive; its same error is preserved in the official failed batch.

Reviewer `/root/architecture_analysis` rechecked the same three findings at
`f8a66f2` and reread the final record: bounded repair review passed. See
`BOOTSTRAP-INDEPENDENT-REVIEW.md`. No additional feature-discovery round.

## Completion boundary / next gate

Implemented and scoped-tested: independent-host transport source, exact worker,
complete consumer bindings, one-use claim, existing transaction/rollback wiring,
and maintenance provenance for subsequent ordinary stable updates.

Not proven: `prepare_draft → isolated host freeze → native human choice → frozen
worker → installer` in one complete product-entry run. Genuine one-shot UI
evidence is a benign marker; installer evidence uses synthetic host/candidate
observations. Do not splice them into production acceptance. No final all-module
regression, production cohort/migration, actual new-host trust/live positive and
negative Hook proof, or Windows acceptance.

The earlier plan to run full regression was deferred after review and repair.
The prior full run took about 31 minutes; another full run plus closeout no longer
fits the remaining **90-active-minute** r16 budget. Human/tool approval wait is
not active execution time. This is a pending release gate, not a waived gate or
a reused full pass.

Next bounded task: exercise the existing complete entry with disposable
installation/cohort roots and exact native one-shot approval, then final
release-level regression on frozen inputs. Preserve old production on failure.
Production versioning/install authority and actual trust/live verification remain
separate prerequisites. Scoped repair review alone does not authorize merge/install.

## Execution cost and sediment candidate

No comparison workload or additional CLI task-model run was launched; the probe
used a fixed loopback provider. Coordinator/reviewer token usage was not metered;
no token savings or measured hot-path speedup claimed. Changes are in maintenance/
installation, not ordinary Agent Hook execution.

Layer1 card (local report only; formal KB and memory graph were not written):

- Type: regression. Goal: exact old-Hook maintenance without wider permissions.
  Trigger: a new predicate consuming two CLI inventory projections.
- Symptom: valid legacy migration refused in seven tests after boundary repair.
  Expected: compare source identity with source identity; separately check cache
  protocol. Actual: source path compared with cache path.
- Root cause: consumer conflated distinct producer fields; unit fixture initially
  mirrored that error. Evidence: **verified**, failed official run, producer code,
  corrected same-entry run. Excluded: old production defect, missing human
  consent, or justification for weakening the migration predicate.
- Correction: separate identities; retain real-installer normal controls with
  negative tests. The failures and final evidence IDs are listed above.

| Sample | Expected | Reason / origin |
|---|---|---|
| Route positive: registry source differs from installed cache | apply | Same role distinction; observed installer fixture |
| Route negative: two fields genuinely identify the same resource | skip | Distinct-role premise absent; constructed |
| Execution: source-to-source match plus separate cache protocol check | pass | Both invariants hold; observed final run |
| Execution: reshape fixture to equate paths, or drop protocol checking | fail | Conceals mismatch or weakens scope; first observed, second constructed |

Before shared sedimentation, remove project paths, IDs and commits. Reusable
core: verify consumer assumptions against actual producers, not fixtures that
repeat the same assumptions. Suggested container: anti-patterns; consumers:
review checklist and fixture authoring. Coordinator deduplication required.
