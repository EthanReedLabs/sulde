# Development and packaging

**English** | [简体中文](DEVELOPMENT.zh-CN.md)

This guide is for maintainers and host integration developers. Start with the
[project overview](../README.md) for user-facing entry points.

## Environment and artifacts

Build self-contained plugin packages from a clean Git checkout with all intended source files
committed and no machine-specific data. Each output directory must be new:

```sh
python3 -B scripts/release/stage_plugin.py --target claude --output ../sulde-claude-candidate
python3 -B scripts/release/stage_plugin.py --target codex --platform posix --output ../sulde-codex-candidate
python3 -B scripts/release/stage_plugin.py --target codex --platform windows --output ../sulde-codex-windows-candidate
```

Packages include license files and the runtime code required by the host. The raw Codex directory
at `integrations/codex/plugins/sulde` is for adapter development; use a complete staged package
for integration.

Staging requires every license and notice file in `LICENSE_FILES` to be tracked, present, and
a nonempty regular file before creating output. The set includes the current license, notices,
contribution terms, and both languages of the licensing guide and [third-party inventory](../THIRD_PARTY_NOTICES.md).
Historical license texts remain accessible through the licensing guide's pinned Git links.
Claude packages carry them at the root; Codex packages carry them at both the plugin and runtime roots.

For each release candidate, record the clean source commit (`git rev-parse HEAD`), target platform,
and SHA-256 of the final archive. Keep that archive and its checksum together with the source
revision and validation results. A checksum identifies bytes; it is not a trusted publication
timestamp or a legal determination. Plugin version numbers alone do not identify licensing changes.

Hook dependencies are listed in `hooks/requirements.txt`. KB bootstrap declares `fastembed`,
`jieba`, `cryptography`, and `pyyaml`; FastEmbed supplies its numerical and model dependencies.
There is no separate KB requirements file. Use a separate data root for testing and keep it away
from existing production data.

The Codex installer is `scripts/release/install_codex_plugin.py`. Its `--codex` input selects an
executable and binds its absolute path, version, file digest, and observed protocol. This source
revision audits `codex-cli 0.154.0`. Changing the executable requires a new verified installation.
Managed tasks do not reselect the CLI through PATH or `SULDE_CODEX_EXE`, and do not silently upgrade
a v1 deployment identity to v2.

Real CLI regression gates require `SULDE_TEST_CODEX_EXECUTABLE` to be set to an explicit absolute
path. Without that input, the gates remain unverified. This test parameter cannot select the
executable used for production tasks.

Packaging checks do not replace on-host verification of installation, native permission handling,
hook execution, or scheduling. Building a Windows package is not evidence of execution on Windows.

Historical baseline cases in `tests/test_control_composition_architecture.py` and
`tests/test_control_composition_performance.py` depend on private commits or reports. They are not
portable public regression gates. Missing inputs must not be reported as a pass, and private
history must not be imported to run them. The SELF template carries no operator objectives,
historical approvals, or verified local capability state.

## Local checks

```sh
python3 -B scripts/sulde.py doctor --strict
git diff --check
```

Run regression checks for the modules affected by a change. Packaging changes also require
verification of actual artifacts from a clean source copy, including license files, entry points,
and runtime dependencies. See the [contribution guidelines](../CONTRIBUTING.md).

## Adding a compatible host

Sulde exposes several integration surfaces. `tools/kb-mcp/server.py` implements stdio JSON-RPC
initialization, tool discovery, and tool calls. The project toolkit exposes CLI commands through
`scripts/sulde.py`. A tool implementing the matching interface can reuse those capabilities.

Full host integration also needs mappings for lifecycle events, human permission decisions, and
managed execution. Use `scripts/kb/host_capabilities.py` as the capability contract and the existing
adapters as concrete examples. Current provider selectors and package targets accept `claude` and
`codex`; another provider needs explicit adapter, registration, and packaging support.

Validate the selected interface first, then session identity, tool/result correlation, permission
decisions, and process completion where applicable. Distinguish packaged entry points, synthetic
adapter checks, and observations from the actual host. Only claim the capabilities demonstrated
in that environment. The [existing host contract](dual-runtime-contract.md) documents the shipped
Claude Code and Codex adapters and their shared core boundaries.
