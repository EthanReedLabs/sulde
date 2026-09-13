# Contributing to Sulde

Sulde shares its framework under [PolyForm Noncommercial 1.0.0](LICENSE).
Read the [licensing guide](docs/LICENSING.md) before contributing. Contributions should improve
the reusable framework while keeping project knowledge, session memory and operational data
outside the source distribution; see the [public data boundary](docs/PUBLIC-DATA-BOUNDARY.md).

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

## Contribution licensing

By opening a pull request you assert that you authored the contribution, or have the necessary
rights to submit it, and offer it under PolyForm Noncommercial 1.0.0. You retain copyright in
your contribution. No copyright assignment or additional relicensing permission is implied.
Identify third-party material and preserve its original license and attribution; do not submit
material whose terms are incompatible with this distribution.

This policy applies to new contributions submitted under these terms. Historical contributions
and releases retain their existing grants; see [license history](docs/LICENSING.md#license-history).

## Code of conduct

Be kind, provide reproducible evidence, and assume good faith.
