# Independent bootstrap: bounded protocol result

Date: 2026-10-06. Status: verified-scoped (design and fixture protocol only).
Scope: revision 15; design/tests only. No product source or production changes.
Tested HEAD: `11c2131fd5e73b643d7dfbfde2e106c77d8b294c`.

## Result

An isolated Codex 0.160.0 app-server, with no discovered Hooks and no inherited
contract/auth, presents native command approval requests for unified exec. Its
policy is `on-request` with `readOnly` sandbox; the exact fixture command requests
escalation. The official test runner's production-KB read-only protection remains
in effect; this is not a claim of whole-machine confinement. The fixture's fixed
worker writes only its temporary workspace.

| Case | Independently asserted observation |
| --- | --- |
| Normal pending -> fixture accept | Marker absent at request; exact worker executes, exit 0; marker binds plan digest. |
| Same exact command, new turn | A different native request is required; fixture decline leaves original marker bytes unchanged. |
| First request declined | Completed item is declined; no marker. |
| Plan changed after prompt | Even with fixture accept, worker exits 65; no marker. |
| Pending host disconnected | Only the owned fixture process group is closed; no marker. |

Four new host tests plus M1's one and M2's two shared-fixture regression tests plus
two encoding checks: **9/9**, official duration 30.378s (unittest 29.928s), no input
drift. Only local deterministic Responses fixtures, no paid/external model calls.
Normal path is established before the negative cases. These are capability
controls on one host version, not baseline-red/candidate-green product fixes.

Evidence:

- `.codex-agent/s3c-bootstrap-evidence/formal/20261006T103515.350162-3f7923abad7e.{json,log}`
- Log SHA256 `a7ec0c6dc212a87042b58fa1dba8f9e5e91ce97f2c74bdf1d5405f7dfa80e4c2`.
- Raw native request identities, commands, synthetic decisions and command
  completion records are retained with `authority=fixture-decision-not-human`.
- Repeated request is asserted in the test; its result and reply identity are
  retained. No session/prefix acceptance is sent.

## Failed attempt retained

At `7d9ca85`, all four new cases failed at a malformed fixture assertion: native
`command` is a rendered shell argv, not the raw exec tool `cmd`. No test approval
was sent on those failed paths. This is **fixture invalidity**, not a product
denial or failed migration. Fixed by parsing exactly three shell argv entries,
checking shell/`-lc` and comparing the inner command byte-for-byte; no substring
match or policy weakening. The unchanged M1/M2 and encoding checks passed.

Record `20261006T103403.830680-bccaa7950e15`, duration 30.024s, no input drift;
log SHA256 `a64ecf50f45e5f1b7c4c8745c9987f662502ae0a653b5e0d1933be3f4c8508ba`.
Initial terminal log inspection was truncated by verbose old M1/M2 output; full
official files remained intact. Subsequent inspection used bounded result lines.

## Exact limits and next deliverable

The test client answered approvals; no real human UI approval in the independent
host was exercised. There is no production bootstrap launcher, durable one-use
maintenance worker or migration adapter in this commit. Neither this result nor
the r15 source-task approval authorizes production work. The next implementation
boundary is frozen in BOOTSTRAP-DESIGN.md, including genuine interactive approval,
immutable worker content, existing transaction/recovery, cohort and trust proof.

The M3 finding remains valid for the old product's supported in-process routes;
this new result adds a tested independent **backend protocol**, not retroactive
authority or proof the overall migration gap is closed. No full-suite run is
needed for this tests/docs-only delta. Windows and actual production installation
remain unverified. Main/dev, installed caches, user sessions and remote branches
were not changed.

The task used dispatch discipline to keep fixture correction and affected
regression in one turn; KB ap-0247 constrained claims to exact one-use decisions,
not generic Allow. Official App Server documentation informed protocol assertions.

## Sediment candidate

Layer1, following `templates/knowledge/problem-card.md`.

### Task and intent

- Problem type: workflow / host-inconsistency.
- Goal/confirmed expectation: Agent-owned maintenance with human high-risk choice,
  without copying approval strings; no production disruption in this test phase.
- Trigger: old runtime cannot load/authorize the new maintenance adapter before
  installation; a separate host backend must be distinguished from its human UI.

### Observation and evidence

- Symptom/gap: old typed routes have no first-bootstrap action; native independent
  backend can instead ask for a scoped command decision, as the log above shows.
- Confirmed cause: new runtime adapter availability was an unmet dependency, not
  a missing user statement of consent. Human UI/production integration: inconclusive.
- Excluded hypothesis: the tested native backend cannot request approval without
  Sulde Hooks (counterexample: four new cases with empty Hook inventory).
- Evidence status: verified for isolated protocol only; see exact record/hash above.
- Method: actual backend request/command outcome, precise synthetic authority label,
  paired Deny/disconnect/drift controls, no production action or borrowed receipt.

| Sample | Content | Expected | Reason | Source |
| --- | --- | --- | --- | --- |
| Route positive | Old installed recovery lacks proposed maintenance action | apply | Inspect the first authorization/loading dependency | observed |
| Route negative | Already installed typed action only needs routine verification | skip | No first-bootstrap dependency | constructed |
| Execution positive | Real request, exact command and negative controls; synthetic replies labelled | pass | Protocol evidence stays within its authority scope | observed |
| Execution negative | Fake client accept or exit 0 declared live human approval/ready | fail | Human decision and production effect are not proved | constructed |

### Promotion boundary

- Remove/generalize paths, project/task IDs and private deployment details.
- Reusable core: verify first-load authority dependencies; separate native request
  protocol, genuine human decision and verified operational effect.
- Suggested container/consumer: work-model; maintenance review and task-authoring.
- Formal knowledge base and memory graph were not written.

## Independent review

Read-only architecture reviewer independently matched the source, task boundaries,
official records and hashes: scoped pass, no blocking finding. Its terminology
clarification about the runner's limited isolation domain is incorporated above.
This is not independent acceptance of a production bootstrap or installation.
