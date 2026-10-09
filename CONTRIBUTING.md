# Contributing to Sulde

Thank you for considering a contribution. Sulde is a small framework with a deliberately narrow scope, so PRs are accepted in specific areas only.

## Where contributions are welcome

### Knowledge base (`knowledge/`) — cross-project sedimentation

The `knowledge/` tree (anti-patterns / platform-kb / tech-docs / 案例研究 / work-model) accumulates **de-identified, project-agnostic** learnings contributed by real Sulde deployments. If you are sedimenting from a working project, follow [`knowledge/SEDIMENTATION-STANDARD.md`](knowledge/SEDIMENTATION-STANDARD.md) — it defines the two-layer model, the de-identification law, global anti-pattern numbering, the platform controlled vocabulary, `dedup-before-add`, the `curate-to-kb` gates for case studies, and per-project backup mirrors. The single-project origin guide (`knowledge/ABSTRACTION-GUIDE.md`) is retained as the first-source-project example; the STANDARD supersedes it.

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
- **`plugin.json` / version bumps / `LICENSE`**. Release management is centralized. License-change proposals require maintainer sign-off.

If you have a strong argument for changing one of these, open an issue with the rationale before writing code.

## PR mechanics

1. Fork → branch named `contrib/{kebab-slug}`
2. One PR per logical change. ADR additions, examples, and doc fixes should be separate PRs.
3. Title in imperative mood, ≤72 chars.
4. Body explains *why* (not just *what* — the diff shows what)
5. If your change has a "this would have caused X before" story, include it; concrete pain motivates merges

### Contribution licensing

By opening a pull request, you assert that you authored the contribution or have the rights
needed to submit it, and offer it under the project's [MIT License](LICENSE). You retain your
copyright. No copyright assignment or additional relicensing agreement is required.

Identify third-party material and preserve its original license and attribution. Historical
contributions and releases retain their existing grants; see the
[licensing guide](docs/LICENSING.md#license-history).

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
