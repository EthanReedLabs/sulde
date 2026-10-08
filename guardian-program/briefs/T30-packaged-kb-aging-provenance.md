# T30 packaged KB aging provenance

Implement only the source and test portion of the frozen T30 task. The
coordinator owns integration, production installation, scheduler reconciliation,
live session acceptance and control-plane events.

## Required implementation

1. Add a small shared history-provenance module under `tools/kb-index/`.
   - Build from the verified corpus manifest and each document's last Git commit.
   - Render deterministically with POSIX/NFC-safe unique paths, exact document
     hashes, timezone-aware ISO timestamps, corpus SHA and a canonical self digest.
   - Load with strict schema/type/count/order/digest/corpus/file verification.
2. Update `kb-aging.py`.
   - Source checkout: preserve authoritative Git history behavior.
   - No-`.git` runtime: require and consume validated packaged history.
   - Never fall back to mtime or an external checkout.
3. Update official staging and installation validation.
   - Generate the history file inside each staged runtime before generation seal.
   - Require and validate it before accepting the artifact.
4. Add focused tests for deterministic generation, no-`.git` success, missing,
   malformed/tampered, duplicate/incomplete, timezone and corpus/content mismatch.
   Include a real staged Codex runtime invocation of `kb-aging --dry-run`.
5. Update the Codex cachebuster only after the implementation tests pass.
6. Write the task report with exact commands/results, findings, resolved problems,
   remaining coordinator-only gates and a Layer1 `沉淀候选`.

## Constraints

- Modify only the ten owned paths in the task definition.
- Do not commit, install, load or kickstart schedulers, write production state,
  edit control events, use external projects, or access the network.
- Do not add another task or broaden the design.
- If an owned-path correction cannot meet an acceptance clause, stop and report
  the exact blocker rather than weakening fail-closed behavior.
