# Contributing to Sulde Community

Sulde Community deliberately stays a small framework. Contributions should improve the generic
mechanism without importing a project's private knowledge or turning the public skeleton into the
private runtime.

## Welcome contributions

- Documentation corrections and translations.
- Cross-platform launcher, UTF-8, clean-install, and diagnostics fixes.
- Tests that reproduce a generic hook, template, generator, or knowledge-kit failure.
- Generic schema/tooling improvements for the empty project knowledge kit.
- Brief, de-identified stack setup examples after a design discussion.

For an anti-pattern or case-study example, open an issue before adding it. The maintainer will check
that the material describes a recurring pattern, has a verified cause and prevention mechanism, and
contains no project, customer, credential, session, or commercial detail. Project incident libraries
belong in the downstream project's `knowledge/` directory.

## Maintainer-controlled areas

Open an issue before changing:

- the five core skills;
- production hook protocol or registration;
- template top-level layout or supported stack list;
- extension registry schema;
- `plugin.json`, versioning, license, or private-to-public release manifest.

Generated content below `skills/community/` or `extensions/` normally belongs in a downstream fork.
It is suitable upstream only when it solves a generic framework problem.

## Pull request mechanics

1. Use a `contrib/{kebab-slug}` branch.
2. Keep one logical change per pull request.
3. Use an imperative title of at most 72 characters.
4. Explain the user-visible failure, root cause, boundary, and verification evidence.
5. Redact `.sulde-config.yaml`, logs, paths, and screenshots before attaching them.

## Verification

Use Python 3.10+ with PyYAML 6.0+:

```sh
python3 -m unittest discover -s tests -v
./bin/sulde doctor --strict
git diff --check
```

For packaging changes, also copy the tracked tree without `.git`, caches, or local configuration and
run doctor from that clean artifact. Passing only inside the development checkout is insufficient.

## Contributor License Agreement

By opening a pull request you assert that you authored the contribution and may submit it. You
license it under the repository's Business Source License 1.1 terms and grant the Licensor a
perpetual, irrevocable right to re-license it under an OSI-approved license so the stated Change Date
and Change License can apply consistently. You retain copyright in your contribution.

The `0.1.x` line remains under its archived MIT license.

## Code of conduct

Be kind, provide reproducible evidence, and assume good faith.
