# Sulde Methodology — The 7-Layer Pyramid

> The reasoning behind Sulde's structure. Read once before adopting the framework; revisit when you are tempted to bypass a layer.
>
> **v0.2.0 scope note**: v0.2.0 narrows the framework's officially-supported scope to **mobile multi-end projects** (Android / iOS / Flutter / HarmonyOS NEXT). The 7-layer pyramid below is stack-neutral; the v0.2.0 templates / hooks / examples assume mobile. Non-mobile users should stay on v0.1.x or wait for v0.3+.

---

## Why mobile-first

Three observations from the original multi-end project that birthed sulde-cc:

- **Mobile teams suffer the multi-end coordination problem most acutely** — every product feature ships twice (or thrice with HarmonyOS), and each platform has different scaffolds / different conventions / different verify recipes. The artifacts-over-memory principle pays off the fastest here.
- **Mobile frontends are well-isolated** — each frontend lives in its own directory with its own build system, so the per-frontend workspace layer (L2) maps cleanly to existing project structure without invention.
- **Mobile design-truth tooling is mature** — Pencil / Figma / Sketch all have MCPs, making the design-truth layer (L4) implementable today rather than aspirational.

For web/backend/N-end projects the 7-layer pyramid still applies, but the templates and per-stack defaults that ship in v0.2.0 are mobile-specific. The pyramid translates; the boilerplate does not.

---

## The problem

A single Claude Code session handling a multi-end project (web + mobile, frontend + backend, iOS + Android + HarmonyOS) fails in predictable ways:

- The context window fills with file content from every end at once
- The session loses track of who-changed-what after a few `/clear` cycles
- Cross-end consistency drifts because no single source of truth survives session restarts
- Fix-this-bug requests bleed into adjacent files, and no one notices until something breaks
- The same anti-patterns recur every few weeks because the memory of past incidents fades

The instinctive response — "I'll just use a bigger model" or "I'll be more careful next time" — does not work. Bigger models still have finite context. "More careful" is not a process.

## The shape of a solution

Split one big session into **roles**, give each role a **scope**, and let **artifacts** (not session memory) carry information between them:

- **One coordinator session** at the project root. Owns design truth, dispatches work, audits handoffs.
- **N Dev sessions**, one per frontend. Each runs inside its own subdirectory. Each only touches its own files.
- **Task-mds** carry work intent from coordinator → Dev.
- **Handoffs** carry work results from Dev → coordinator.
- **ADRs** carry pattern memory across all sessions and across time.

This is the shape. Everything else in Sulde is a refinement of how to make it concrete.

---

## The 7 layers, bottom-up

The layers stack from "things that change rarely" at the bottom to "things that change every day" at the top. When a layer is missing, the layers above it have nowhere to anchor and collapse into ad-hoc behavior.

```
┌─────────────────────────────────────────────────┐
│  L7  Cross-session memory  (ADRs, session-resume)│  rare → daily
├─────────────────────────────────────────────────┤
│  L6  Handoff                                    │
├─────────────────────────────────────────────────┤
│  L5  Task-md                                    │
├─────────────────────────────────────────────────┤
│  L4  Design truth / contract truth              │
├─────────────────────────────────────────────────┤
│  L3  Project documentation hub                  │
├─────────────────────────────────────────────────┤
│  L2  Per-frontend workspace                     │
├─────────────────────────────────────────────────┤
│  L1  Project meta (roles, config, identities)   │  → rare
└─────────────────────────────────────────────────┘
```

### L1 — Project meta

The smallest, slowest-changing layer. Declares **what the project is** for Sulde's purposes:
- Which directories are frontends?
- Who is the coordinator? Who plays each Dev role?
- Which design tool / MCP provides truth?
- What identities are used for commits?

Lives in `.sulde-config.yaml` at project root. Read by the plugin's hook on every prompt; rarely edited.

**When this layer is broken**: the hook cannot tell `coordinator` from `dev`, sessions trigger the wrong skills, the wrong author name lands on commits.

### L2 — Per-frontend workspace

Each Dev session needs a dedicated subdirectory with `.ai-workspace/` for tasks, handoffs, resume notes, baselines. The directory's `CLAUDE.md` declares the stack, the identity, the read-on-start contract.

**When this layer is broken**: Devs touch each other's files, handoffs from one frontend leak into another's workflow, commit identities mix.

### L3 — Project documentation hub

The shared knowledge base — methodology, shared rules, ADR registry, audit reports, postmortems. One per project, lived in `<docs-hub>/` (or your preferred name).

This is the layer with the highest variance across projects. Sulde ships only a directory skeleton; you fill it.

**When this layer is broken**: the same lesson must be relearned every quarter; Dev sessions diverge in their reading of "the rules."

### L4 — Design / contract truth

For UI work, the design source-of-truth (Pencil file, Figma file, custom MCP). For API work, the spec document. For library work, the public-API contract.

The coordinator extracts a **normalized, machine-readable** representation (`<docs-hub>/design-truth/{page-id}.md` + a rendered PNG) so every Dev reads the same thing regardless of design tool.

**When this layer is broken**: Devs squint at screenshots and guess at corner radii; cross-frontend implementations of "the same page" diverge visibly.

### L5 — Task-md

The unit of work-dispatch. Coordinator writes a `{date}-{slug}.md` file with §0 baseline, §1 design-truth citation, §3 scope, §4 implementation contract, §5 verify, §6 git completion, §7 model. Dev reads, executes, refuses if a required section is missing.

**When this layer is broken**: work is dispatched as inline chat with no contract, scope creep is the norm, audits are impossible because there is no contract to compare actual results against.

### L6 — Handoff

The unit of work-result. Dev writes a `{date}-{slug}-result.md` (or `{date}-{slug}.md` for blockers) reporting what shipped, what verifies passed, what escalation candidates were noticed.

The coordinator's session startup reads recent handoffs to know what has happened while they were away.

**When this layer is broken**: the coordinator restarts a session and has no idea what Devs accomplished in their absence; work is re-dispatched or lost.

### L7 — Cross-session memory

Two artifact types:

- **ADRs**: pattern memory. "We hit this. Here's why. Here's how to prevent recurrence."
- **session-resume docs**: continuity memory. "I was in the middle of X; here's where to pick up."

ADRs live in `<docs-hub>/ADR/`. session-resume lives in each frontend's `.ai-workspace/session-resume/`.

**When this layer is broken**: the same anti-pattern recurs every quarter; sessions can never run longer than the context window allows.

---

## Why this works (the principles)

Three principles support the structure:

### 1. Artifacts over session memory

Anything important must exist as a file, not as session state. Sessions die; files persist. If a fact only lives in this conversation's context, it is one `/clear` away from oblivion.

Concretely: the coordinator's todo list is a file (`coordinator-todos.md`), not the Claude task tool. The Dev's session checkpoint is a file (`session-resume/...`), not what's in context. The pattern memory is a file (`ADR/...`), not "I remember this came up before."

### 2. Roles enforce scope

A coordinator session does not touch frontend source files. A Dev session does not touch the design truth. This is not bureaucratic discipline — it is **how each role's tools and skills are configured**. The coordinator's working directory is the project root; the Dev's is a single frontend subdirectory. Cross-role work must travel via task-md or handoff.

The benefit: when something goes wrong, the audit question "who did this and why" has a clear answer.

### 3. Contracts before code

A task-md is a contract. It declares scope, expected outcome, verification steps. The Dev cannot start work until the contract is complete (the `assign` skill refuses). The coordinator cannot dispatch until they have read baseline, cited design truth, listed in/out scope (the `writing-task-md` skill prompts for these).

The contract is more boring than the implementation, but it is what makes the implementation predictable.

---

## When to depart from the methodology

This is not religion. The framework optimizes for **multi-end projects running for months with the same team**. If your project is smaller, you can collapse it:

- **Solo developer, one frontend**: skip the coordinator/Dev split. You play both roles in one session. The task-md layer becomes optional (use it when starting non-trivial work, skip for typing fixes). Most other layers remain useful.
- **One-shot project, ≤2 weeks**: skip ADRs. Skip session-resume (you will not run long enough for context exhaustion to matter). Keep the task-md/handoff loop if you have a collaborator.
- **Two developers, one repo, simple stack**: keep ADRs (cheap insurance against pattern recurrence) but skip the layered docs-hub structure — a flat `docs/` folder is fine.

The cost of running the full framework is overhead. The cost of not running it on a long multi-end project is rediscovering the same lessons every month. Pick the level of structure that matches your project's lifetime and complexity.

---

## Further reading

- [`docs/GETTING_STARTED.md`](GETTING_STARTED.md) — concrete 5-minute setup walkthrough
- [`template/_project/docs-hub/ADR/0000-example.md`](../template/_project/docs-hub/ADR/0000-example.md) — example ADR demonstrating the format (mobile-generic examples in `0001`-`0003`)
- The five Sulde skills' `SKILL.md` files — `coordinator/writing-task-md`, `coordinator/configure-sulde`, `coordinator/multi-source-review`, `dev/assign`, `dev/handoff` — read these to understand the day-to-day workflow contracts
- [`docs/V0.2.0-DESIGN-v2.md`](V0.2.0-DESIGN-v2.md) — the v0.2.0 design spec (hook protocol details, grace-period mechanics, schema schema)
- [`CHANGELOG.md`](../CHANGELOG.md) — v0.2.0 breaking-change list + migration notes

## Cross-OS notes

- **macOS** is the only OS supporting all 4 stacks (iOS requires Xcode, macOS-only).
- **Linux / Windows** support 3 of 4 stacks (no iOS). HarmonyOS works on all three.
- The Python enforcement hooks run identically across all 3 OSes; the bash git-pre-commit hooks need Git Bash or WSL2 on Windows.

## Cost / benefit pivot

The cost of running the full framework is overhead. The cost of not running it on a long multi-end mobile project is rediscovering the same lessons every month. Pick the level of structure that matches your project's lifetime and complexity:

- **One-week prototype, single dev**: skip the framework entirely; you will not run long enough for any layer to pay back its cost.
- **Multi-month single-platform project**: keep L1-L3 + L7. Skip the L5/L6 contract dance (use inline chat); skip the L2 workspace if you only have one Dev.
- **Multi-platform, multi-month, ≥2 Devs**: full framework. This is where sulde-cc was designed.
