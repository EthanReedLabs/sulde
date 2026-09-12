---
name: intent-guardian
description: Align a user's real intent with Agent execution and supervise downstream Skill, MCP, tool and external-write actions. Use for subjective editing (résumés, writing, design), ambiguous acceptance criteria, repeated corrections, "not what I meant" feedback, previously recorded preferences being ignored, high-impact MCP work, or any task where human–Agent misunderstanding could cause drift.
---

# Intent Guardian

Maintain one explicit, revisioned intent contract. Do not infer hidden preferences from scattered corrections and do not claim access to hidden model reasoning.

## Establish the contract

1. Read the `[sulde intent]` context injected for this turn. Keep its `contract=` path.
2. Mirror the user's intent as a short decision card in no more than seven fields:
   - outcome;
   - reason;
   - preserve;
   - reject;
   - freedom allowed;
   - observable acceptance;
   - unresolved decision.
3. Ask exactly one high-discrimination question only when its answer materially changes the result. Route subjective choices, scope expansion, public/new-audience communication, destructive work, persistent cost, secret egress, or a correction storm to the human-readable card. Deterministic actions already declared in the readable task scope are supervised and executed by the Agent; MCP or external transport alone does not create a second human approval ceremony.
4. Create an immutable proposal with the stable launcher. Mechanical setup is Agent work,
not a human ceremony. If no workspace contract exists, use `prepare-proposal`; it atomically
creates a non-authorizing shadow contract and the proposal, so never ask the user to copy
`create` or `activate` commands:

```sh
"${SULDE_HOME:-$HOME/.sulde}/bin/intent-guardian" prepare-proposal \
  --workspace "<workspace>" \
  --intent-id "<stable-intent-id>" \
  --objective "<confirmed outcome>" \
  --rationale "<why>" \
  --accept "<observable acceptance 1>" \
  --preserve "<must remain true>" \
  --reject "<known bad direction>" \
  --allow-path "<relative path or glob>" \
  --decision-route auto \
  --unattended-policy agent-if-eligible \
  --intent-kind "deterministic|subjective|unknown" \
  --risk "low|medium|high|unknown" \
  --effect "read|local_write|external_write|destructive|unknown" \
  --reversibility "reversible|compensatable|irreversible|unknown" \
  --cost "none|bounded|unbounded|unknown" \
  --rollback "<concrete rollback method>" \
  --unknown "<unresolved item, repeat as needed>" \
  --mode enforce
```

For an existing contract, `propose-revision` remains valid. Repeat flags for multiple items.
Omit `--allow-path` only when the task legitimately spans the workspace.
Omit `--unknown` when there is no unresolved item; never pass placeholder text literally.

The command returns two interfaces. `decision_card` is for people: outcome, reason, allowed
change, preserve/reject boundaries, acceptance, risk/recovery, authority and unknowns in plain
language. Show this card without the raw contract or digest unless the user asks for technical
details. `technical_binding` and `digest_bound_contract` are machine integrity data; never ask a
person to understand or copy them.

Follow the returned `decision_route`:

- `human`: show the readable card, then use the current host's native decision surface.
  On Codex, present the readable card through the current conversation's native Allow/Deny surface.
  Run `native-decision-preview proposal --decision approve --target current --provider codex
  --session-id <current-session> --contract <contract>` and parse its JSON. Invoke the returned
  `command_argv` as a one-time escalated command, passing the returned `description` verbatim as
  the approval justification; never request or store a persistent prefix approval. `PreToolUse`
  performs only structural/session/mode checks. The exact `PermissionRequest` records the paired
  question and returns no decision so Codex displays its own Allow/Deny UI. Allow executes the
  protected command once; Deny creates no authority and leaves the proposal unchanged. If the
  user has explicitly chosen rejection, request the corresponding `--decision reject` preview;
  native Deny is not itself a semantic rejection. On a host without a verified native bridge, keep
  the proposal pending and let the Agent establish or repair that bridge. Never ask the user to type
  a fixed phrase, copy a digest, or execute a CLI command as a substitute. Only a receipt from the
  matching host lane may apply the proposal.
- `agent`: prefer adding `--apply-agent-eligible --agent-rationale <reason>
  --agent-evidence <evidence>` to `propose-revision`. This creates, decides and applies an eligible
  proposal in one stable-launcher process, so the control command's own completion event cannot make
  its proposal stale. The same checks remain available through `agent-decide-proposal <digest>
  --rationale ... --evidence ... --provider <current-host>` for API and recovery use. The deterministic gate rechecks that the intent is
  deterministic, low-risk, local/read-only, explicitly scoped, reversible, free of persistent
  cost and unknowns, and does not expand permissions. A medium-risk proposal is also eligible only
  when every material effect is covered by a registered, one-shot, host-local continuation profile
  with exact digests, rollback and an independent verifier. Then apply the proposal. Report the
  Agent rationale and evidence; never label it human approval.

An explicit `--decision-route agent` does not bypass the gate; an ineligible proposal is routed
to `human`. Subjective expression, arbitrary/public external effects, destructive effects, persistent cost, semantic critic,
missing rollback, broad write scope or any unknown item always require a human. Tool-level event
digests are audit identities, not authority. Once the readable proposal declares the effect and
scope, the supervisor may dispatch an in-scope reversible action and retain verification debt until
independent evidence proves its outcome. A qualifying sealed
host-local chain may be decided by Agent policy without presenting a human decision surface.
Each grant must bind one
acceptance criterion, typed effect, exact target and content/runtime digests, use limit, rollback,
and an independent machine verifier. The current maintenance chain freezes the official cachebuster
helper and the subsequent transactional Codex Sulde plugin install in one readable card, one use each;
the install binds the future post-cachebuster tree. Order or digest drift cannot downgrade to ordinary
local-write authority. Agent claims of necessity, positive benefit, or confidence are
not authority. Public communication, a new audience, cost, secrets, destructive work, scope expansion,
or an unverifiable effect can never use a continuation grant.
CI/release configuration, host rules, hooks, Skills, guardian code and secret-bearing paths are
also excluded from Agent authority even when the Agent labels them low-risk. Managed L3 children
cannot create this authority at all.

`--unattended-policy agent-if-eligible` is the default. It does not approve a timed-out human
question: the complete deterministic Agent gate runs before any native prompt is presented, and
only a passing proposal is routed directly to `agent-policy`. If the gate fails and Codex displays
a `PermissionRequest`, five minutes merely marks the request as needing attention/reassessment;
silence cannot distinguish an absent person from an unobserved Deny and therefore grants no
authority. The human question remains durable for 24 hours while its card and world-state binding
stay current. A click after that TTL returns structured `approval_expired` and requires a freshly
rendered request; a click after Agent completion returns `already_agent_decided`. Use
`--unattended-policy wait` when the proposal must always remain human-owned even if it would pass
the Agent gate.
Never use `approve-proposal`, `approve-event`, `resume`, or `intervention-resolve` CLI to
manufacture a human decision. This restriction is about decision authority, not the mechanical
executor: after a live readable choice creates an exact receipt, the Agent/Hook/supervisor should
apply the approved proposal, dispatch actions inside that readable scope, or execute the selected intervention
transition through the in-host executor.
`approve-event` is a retired compatibility command: an old copied `批准事件 <digest>` is ignored,
never grants authority, and must not block the user's real task.

The unified event observer has one separate, narrower human route. When
`event-observer.py prepare-export` returns its readable export card, show the scope, exact frozen
cut, destination, included/excluded data and lack of network authority. On Codex use
`native-decision-preview observation-export --decision approve|reject` and the same one-time
PermissionRequest flow; fixed export phrases are non-authorizing. Hosts without the native bridge
keep the export pending until the Agent restores a verified native decision surface. Never substitute intent-proposal approval, event
approval, a digest command, or an Agent decision. A successful local export does not authorize
upload or any other external write.

On Codex, normal human mode is proven by an exact, live `PermissionRequest` paired to the protected
`native-decision` command. A normal `UserPromptSubmit`, a copied phrase, an opaque identifier, direct
invocation of a Hook adapter, or the Agent remembering that the user agreed cannot substitute for
that pair. The command description, provider, session, contract, decision kind, decision target and
current card must all match. The Hook must defer its decision so the Codex UI remains the authority.
Technical request IDs and proposal digests stay in the audit and are never user instructions.
The same native surface is mandatory for Codex intent confirmation, paused-contract resume and
effect-intervention reprobe/retry/abort choices. A plain `继续`, `批准当前方案`,
`确认意图镜像并恢复` or `授权重试外部操作` is context, never authority. When Stop creates a
machine-verifiable effect debt, it must run the registered independent verifier in that same Stop
boundary; do not wait for another user message merely to settle evidence already available locally.

New sessions default to independent contracts, even in the same checkout. When continuing an old
task, explicitly select its exact contract in the same physical workspace using
`prepare-task-continuation <source-contract> --contract <current-contract> --provider codex
--session-id <current-session>`. This prepares a read-only reference; it neither changes routing
nor creates a source lane. An already confirmed/busy current task needs its own explicit task
boundary, not an implicit handoff. If the old compatibility context already says
`TASK_REVIEW_REQUIRED` in the same contract, selection is unnecessary.
For the same task, run `native-decision-preview task-continuation --decision
approve --target current --provider codex --session-id <current-session> --contract <contract>` and
use its returned `command_argv` and verbatim `description` through one current-session native
Allow/Deny prompt. Allow binds only this provider/session to the exact current revision and
`task_epoch`; Deny leaves it read-only. The transition carries the objective, constraints and
acceptance criteria, but never copies the source session's grant, approval receipt, open event,
pending verification, effect debt, continuation token or other execution authority. A copied
summary, workspace path, prompt phrase, source token, another session, stale card or changed task
world cannot substitute for this decision. Keep the native command bound to the current contract;
the card names both contracts and the exact route predecessor. If interrupted, the existing
native decision recovery resumes the internal transaction; do not manufacture a source lane,
copy a token, or remove effect history. If the user wants a different task, create and approve
an explicit revision instead of using task continuation.

The following injected receipt is a legacy compatibility signal for hosts or sessions without the
native bridge, not the normal Codex approval interface:

```text
[sulde intent] CONTROL_RECORDED action=approve-proposal target=<internal-digest> receipt=<receipt-id>
```

If the native preview or `PermissionRequest` is unavailable, keep the proposal pending and run the
read-only `intent-guardian doctor --workspace <path> --provider codex` check; the CLI binds the check to the
current native session when `CODEX_THREAD_ID` is available. A provider-level live observation from
another thread does not make this thread ready. When the current session is not `live_verified`,
repair or reinstall the plugin bridge first. If a host restart is genuinely required to register a newly added Hook event and
`continuation.status=missing`, the Agent mechanically runs
`prepare-continuation --workspace <path> --provider codex`; this freezes the current decision card,
a bounded visible-dialogue tail and a lazy source reference. It carries zero approval receipts,
event grants or tool permissions. Once `continuation.status=ready`, ask the user to restart and
resume this same thread. `SessionStart` restores the frozen context, after which the human reviews
and decides through the native UI. Opening a fresh thread is not the default recovery. A synthetic
installer smoke is not live approval evidence. This hook outage blocks human mode; it does not block
a proposal that independently passes the Agent decision gate.

If `doctor --scan --provider codex` reports an orphaned workspace contract, do not copy or edit the
active JSON. Resolve the exact orphan, destination and reason read-only, then let the Agent present
the current host's native recovery decision and execute the exact rebind or retirement after Allow.
Rebinding invalidates old authority and pauses the destination until a new immutable intent proposal
is human-approved and applied; Agent-policy cannot clear a workspace-rebind or correction-storm pause.
If no trustworthy native recovery route is available, keep the orphan blocked and report that missing
capability. Do not delegate a CLI command or fixed response to the human.

For subjective work that needs an independent semantic checkpoint, first disclose that it makes extra current-provider calls over changed artifact excerpts after a local secret scan. Add `--semantic-critic` only after the user accepts that cost and data boundary. Deterministic Skill/MCP/tool supervision does not require it.

5. Register this Skill itself in Codex when the injected Sulde context requests it: run the exact `skill-start` command with this file's absolute path as `--skill-path` before following it, and the matching `skill-end` command after use. This binds the audit to the actual instruction-file digest. Claude's native Skill tool events are already observed; do not duplicate them.

## Execute under lineage

- State which contract criterion each substantial step serves.
- Invoke only relevant Skills. A Skill is procedural guidance, not new authority.
- Treat every MCP call as a capability use. Reads and local log inspection may proceed. In-scope deterministic MCP/external writes use task-level authority and immediately enter the evidence ledger; a tool success response is never proof. A bounded local `memory_annotate` requires explicit matching `extracted_by`, at most 6 entities and 3 edges, and independent SQLite verification. Malformed calls are rejected before dispatch, not classified as external effects. Valid calls have no historical-use quota; authority and verification still apply. Other MCP writes retain their effect class. Registered profiles add machine-verifiable limits, not a human button. Unknown ordinary tools degrade to observable execution when no hard-risk signal exists. Out-of-scope work requests a readable scope decision; public/new-audience, destructive, costly, secret-egress, or semantically ambiguous work remains human-routed. Unprovable outcomes stay `unknown` and notify a person only for the missing fact or choice.
- Keep task facts in authorized task artifacts before optional graph enhancement. A proposal may explicitly declare `--memory-dependency independent` only when its outcome does not depend on graph results; the first declaration requires human review. Legacy/unspecified dependencies remain conservative. This changes conflict/freshness projection only: it does not settle memory debt, transfer authority, permit retries, or cover external/destructive/control-plane work. Recover unknown annotations by `reconcile-verifications`, never by blindly retrying through CLI after an MCP failure.
- After an MCP write, independently read the changed object, diff it, or capture equivalent evidence. A successful tool response alone is not acceptance evidence.
- Preserve the `intent_id` through Skill → MCP/tool → result. Do not repeat a completed action through another route.

## Handle correction without context pollution

When the user says the result is wrong or drifting:

1. Stop material writes.
2. Report four short lists: confirmed, rejected, current misunderstanding, next decision.
3. Preserve the most recent accepted artifact or checkpoint.
4. Revise the contract instead of appending another competing instruction.
5. If the same dimension is corrected twice, keep the contract paused and ask one differentiating question. Do not attempt a third blind rewrite.

Resume after the user confirms the revised mirror. The user retains final control over subjective choices, scope expansion, public audience, destructive work, costs, secrets, and unresolved external facts; the Agent executes already-declared reversible effects under supervision.

## Finish

Verify each acceptance criterion with observable evidence. Report any unverified external write, shadow-only finding, unresolved decision, or contract exception. Never convert an inconclusive observation into a success claim.

When the current repository task branch has been merged into `dev`, its exact HEAD is an
ancestor of the current `dev` HEAD, the task worktree is clean, and all material evidence is
settled, the Agent must finish the temporary-resource lifecycle in the same session:

1. End active Skill frames, then run `release-completed-workspace` against the registered
   `dev` worktree. This is an authority-reducing Agent transition: it creates a session-unique,
   read-only completion anchor and never performs a Git mutation or inherits task authority.
2. From the `dev` worktree, use ordinary Git passthrough to remove the task worktree and its
   local task branch. Guardian does not approve, deny, or execute those Git operations.
3. Run `finalize-workspace-cleanup` against the returned completion contract and read back its
   `complete` receipt. If interrupted, `doctor` and the next hook context expose
   `WORKTREE_CLEANUP_PENDING`; the next Agent resumes these mechanical steps.

Do not defer this cleanup until the user closes the conversation, ask the user to copy a command,
or reuse another session's `dev` contract. A dirty/unmerged task, another Git common-dir, a
protected branch, an active Skill, a pending proposal/event/verification, or real effect debt must
fail closed and remain available for explicit repair.
