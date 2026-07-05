# Contributing to Sulde

Thank you for considering a contribution. Sulde is a small framework with a deliberately narrow scope, so PRs are accepted in specific areas only.

## Where contributions are welcome

### Anti-pattern ADRs (highest value)

If your project has hit a multi-end coordination problem that other teams will likely also hit, a generic ADR contribution is valuable. Open a PR adding the ADR under a new `examples/adr/` directory in the repo (not in `template/_project/docs-hub/ADR/` — that ships only the 3 mobile-generic examples; project-specific ADRs accumulate per-deployment).

A good ADR contribution:

- Describes a **pattern**, not a single incident — must be plausibly recurring across projects
- Has a clear **root cause** beyond "human error"
- Suggests **concrete mitigation** (rule, lint, workflow change)
- Conforms to `template/_project/docs-hub/ADR/_frontmatter.schema.yaml`
- `platforms:` entries must come from the v0.2.0 enum (`android` / `ios` / `flutter` / `harmony` / `coordinator` / `any`); patterns that need a new platform should extend the enum locally + propose adding it upstream in a separate issue
- Stack-neutral writing preferred; mobile-specific examples are fine but the principle should be recognisable across stacks

### More examples

If you have a working Sulde deployment in a specific stack combination (e.g. Next.js + React Native + Supabase), open a PR adding a brief `examples/{stack}/README.md` describing the setup. We do not accept full example projects (too high a maintenance burden), but a description + diff against the template is welcome.

### Docs corrections

Typos, broken links, wrong commands, outdated screenshots. Open a PR with the fix. No discussion needed if the change is mechanical.

### Translations (i18n)

`docs/METHODOLOGY.md`, `docs/GETTING_STARTED.md`, and `README.md` translations into other languages are welcome. Place under `docs/i18n/{lang}/`. Prioritize Chinese, given the framework's origin, but other languages are fine.

## Where contributions are NOT welcome

These areas are maintainer-controlled and PRs touching them will be redirected:

- **Skill internals** (`skills/*/SKILL.md`). The structure of the five skills is part of the framework's design. If you think a skill is missing something, open an **issue** describing the problem; a maintainer will evaluate.
- **Hook logic** (`hooks/*.py`, `hooks/lib/*.py`, `hooks/git-precommit/*.sh`, `hooks/hooks.json`). Same reason. Includes the protocol-compliance details (exit-code semantics, JSON `permissionDecision`, marker-file grace mechanics).
- **Template top-level layout** (`template/_project/` and `template/{android,ios,flutter,harmony}/`). Adding new top-level directories or new stacks changes the framework's shape; this needs a design discussion first.
- **`plugin.json` / version bumps / `LICENSE`**. Release management is centralized. License-change proposals require maintainer sign-off given BSL 1.1's Change Date / Change License parameters.

If you have a strong argument for changing one of these, open an issue with the rationale before writing code.

## PR mechanics

1. Fork → branch named `contrib/{kebab-slug}`
2. One PR per logical change. ADR additions, examples, and doc fixes should be separate PRs.
3. Title in imperative mood, ≤72 chars.
4. Body explains *why* (not just *what* — the diff shows what)
5. If your change has a "this would have caused X before" story, include it; concrete pain motivates merges

### Sign-off — Contributor License Agreement (CLA)

By opening a PR against sulde-cc you agree to the following terms:

1. You assert that you authored the contribution and have the right to submit it.
2. You license your contribution to the Licensor (eric.gao.tech / EthanReedLabs) under the same **Business Source License 1.1** that covers the project, with the same Change Date and Change License (MIT) parameters.
3. You grant the Licensor an additional perpetual, irrevocable license to re-license your contribution under any OSI-approved license, including but not limited to MIT, so the Licensor can manage the v0.2.0 → Change Date transition consistently across all parts of the codebase.
4. You retain your copyright on the contribution itself; only the licensing terms are granted.

Why this CLA exists: BSL 1.1 has a Change Date (currently 2030-05-25) at which the licensed work transitions to MIT. The Licensor must hold the right to perform this transition uniformly across the codebase, including contributor code. Without an explicit grant, contributor code would remain BSL after the Change Date in ways that fragment the license.

The CLA does not apply to contributions to the v0.1.x line (MIT, no Change Date) — those continue under MIT in perpetuity per the `LICENSE-v0.1.0-MIT-archive` file.

### CI

There is currently no automated CI. Reviewers will:

- For doc PRs: render-check
- For ADR PRs: confirm frontmatter validates against the schema
- For skill / hook PRs: run the static spike (`bash -n`, JSON validity, manual prompt test)

## Issues

- Bug reports: include your `.sulde-config.yaml` (redacted), the command that failed, and what you expected to happen
- Feature requests: describe the problem the feature solves, not the feature itself. If the problem is real, the maintainer (or you, in a follow-up PR) can decide what shape the fix takes.
- Questions: prefer GitHub Discussions if available; otherwise issues with the `question` label

## Code of conduct

Be kind. Assume good faith. If a maintainer is slow to respond, gentle follow-ups are fine after a week — the project is maintained part-time.
