# Changelog

All notable changes to sulde-cc (Community Edition) are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) loosely; versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Changed

- Include an English and Chinese third-party dependency/model inventory in plugin
  packages. Staging now fails before creating output if a required license or
  notice file is untracked, missing, empty, or not a regular file.
- Publish the project overview, development guide, and licensing guide in English
  and Simplified Chinese, with reciprocal language navigation. English is the
  default documentation entry; plugin packages retain the translated guides.
- Current source licensing changes to PolyForm Noncommercial 1.0.0. Commercial
  use is not granted, including internal commercial development and paid client
  work; the standard license's express organizational permissions remain intact.
- README, contribution terms and host plugin metadata identify the noncommercial
  license. `docs/LICENSING.md` explains usage, redistribution and historical rights.
- Remove historical MIT and BSL license files from the current source tree and
  plugin packages; retain pinned Git history links in both licensing guides.
  Prior grants and BSL change-license rights remain effective for
  previously licensed material; the new license has no automatic MIT conversion.

## [0.3.0] — 2026-08-12 — Public skeleton completion (P0 + P1)

### Added

- `sulde doctor` validates Python/PyYAML, UTF-8, plugin layout, manifest registration, hook launcher,
  extensions, the empty knowledge schema, and an optional adopting project.
- Cross-platform CLI and hook launchers with an explicit Python 3.10+ and UTF-8 contract.
- Extension SDK generators for a project skill, hook, doctor check, and knowledge container. They
  update one registry and refuse to overwrite existing files.
- Empty project knowledge kit with add, dedup, redact, lint, deterministic index/search, and a
  human-reviewed sediment-draft flow.
- Clean-install and generator/knowledge integration tests.

### Changed

- Removed explicit `hooks` from `plugin.json`; `hooks/hooks.json` is the single conventional
  discovery path.
- Corrected public documentation to the actual 0.3.0 / Python 3.10+ / five-skill product state.
- Defined Community as an extensible skeleton. L2/L3/L4, memory, MCP, autonomous governance, remote
  model calls, and private corpus remain outside the public scope.

### Security

- Private-to-public release uses a digest-pinned allowlist manifest, temporary staging, content
  scanning, staged-tree verification, and managed-path replacement. Directory-wide `rsync` is no
  longer a release path.

## [0.2.2-community] — 2026-07-05 — Community / Pro Edition split

This public repository now hosts the **Community Edition**: the complete framework mechanism (hooks / template / commands / 5 core skills / methodology docs) under BSL 1.1, with a clean history.

- Community Edition contents: 11 enforcement hooks, 4-stack template + docs-hub skeleton, 8 commands, 5 skills (`coordinator/writing-task-md`, `coordinator/configure-sulde`, `coordinator/multi-source-review`, `dev/assign`, `dev/handoff`), 3 mobile-generic example ADRs, `docs/METHODOLOGY.md` + `docs/GETTING_STARTED.md` + `docs/ONBOARDING.md`.
- A separate private development repository retained accumulated project content and advanced
  runtime work; none of that corpus was published here.
- Nothing was removed from this repository — the Pro content was never published here.
- License unchanged: BSL 1.1, Change Date 2030-05-25 → MIT. v0.1.x remains MIT (`LICENSE-v0.1.0-MIT-archive`).

### Earlier history

- **0.2.x** — mobile-first narrowing: 4-stack template (android / ios / flutter / harmony), Python enforcement hooks, task-md / handoff contracts, skill-trigger system, BSL 1.1 relicense.
- **0.1.x** — initial MIT releases, generic N-end coordination skills.

Detailed pre-split history lives in the private development repository.
