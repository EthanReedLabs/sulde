# Legacy first-migration: evidence and bounded next task

2026-10-06; source-only r11 assessment, not migration approval or a drain receipt.

Update after revision-12 M1: per-host reload is now experimentally demonstrated
on the same existing PID/thread; all-caller transition is not. Official registration
removed the old fixture cache, after which both old hosts ran commands without
callbacks until individually reloaded. See M1-REPORT.md for raw evidence and limits.
The proposed M1 experiment below is completed; product transition remains unapproved.

## What was actually observed

1. Installed executable reports `codex-cli 0.160.0`. `codex plugin add --help`
   exposes no preserve-cache/no-prune option. This is a CLI surface observation,
   not proof that every internal host mechanism lacks such a capability.
2. Generated schema (including experimental fields) from that exact CLI:
   - `PluginReconcileResponse` explicitly describes bundle/state changes, NOT a
     runtime-readiness acknowledgement or cumulative per-client change receipt.
   - `HooksListParams` accepts `cwds`, not a thread identity or acknowledged epoch.
   - `thread/loaded/list` describes loaded thread ids, not every independent host
     process using the same cache. Absence from one server is not global drain.
   - `config/batchWrite.reloadUserConfig` promises runtime-setting reload, but
     does not specify an atomic Hook-command replacement and all-caller barrier.
     No production reconcile, config reload or daemon shutdown was attempted.
3. The known current production cache's six Hook commands still reference
   `${PLUGIN_ROOT}/scripts/run-hook.sh`. `/Users/eric/.sulde/bin/sulde-codex-hook`
   is absent. These are local file observations, not a complete live host inventory.
4. Source `_stable_entry_migration_gate` in install_codex_plugin.py:1894 accepts
   fresh-cache-root or verified stable lineage and rejects remaining legacy Hook
   documents. It has no first-migration apply path. Reopening a session would not
   change these on-disk predicates.

Schema evidence: `.codex-agent/s3c-dev-integration-evidence/host-schema/`.
SHA256:

| Generated file | SHA256 |
| --- | --- |
| ClientRequest.json | 4a6fc883c2e84c4721bfabd6756ca5bb6e99675a8938768d8bc9cc67ff984700 |
| v2/PluginReconcileResponse.json | ba2a8e317c9098beed39d4decc433d9dc29ba0c8164e8d4c229481b9243c5ec8 |
| v2/HooksListParams.json | 07638c3a8a3690cf368fa92c7ff697fdd0132865e8c59d53f6e5789e5a260053 |
| v2/ThreadLoadedListResponse.json | 1ea02c4710083e552b2a3a89b931b9049d5bf05b7db46278b8352cf9fd80cd52 |

Official documentation consulted: [plugin packaging](https://developers.openai.com/plugins/build/plugins)
and [Hooks](https://learn.chatgpt.com/docs/hooks). They describe Hook trust and local
plugin discovery/update, but do not establish an all-existing-session migration
barrier for this installed CLI version. Documentation guidance to restart a local
desktop plugin is not such a proof. Local protocol evidence governs this assessment;
no claim is made that a hot-reload facility definitely does not exist.

## Next bounded outcome: M1 migration feasibility and transition contract

The previous "prove exit/reload, then install" wording was incomplete: an explicit
first-migration state transition must also exist. Do not bypass the existing gate.

Proposed sequence, requiring an explicit scope amendment before implementation:

1. In isolated homes only, test two already-loaded real host processes sharing a
   legacy cache. Use local deterministic provider, zero paid calls, normal control
   first. Measure actual Hook callbacks before/during/after official refresh or
   runtime-config reload. Include a caller starting at the transition boundary.
   A refresh response without callback identity evidence is not success.
2. Select the smallest supported transition: a host-supported non-pruning update,
   or verified replacement of all old registrations with an admission barrier.
   If neither is demonstrated, preserve production and report the exact missing
   host capability; do not invent a force flag, infer drain from ps/heartbeats,
   disable protection or introduce a second permissions control plane.
3. Only after the necessary host behavior is proven, extend the existing installer
   transaction with a first-migration prepare/commit/rollback state. Bind old cache
   identity, old/new registration, candidate identity and verified transition
   evidence. Preserve old static bytes and original unknown effects. Failure must
   leave the old usable entry and registration, not fabricate fresh provenance.
4. Isolated normal/injection/entry/affected-module checks and one independent
   review precede any production-install authorization. Keep Windows separate.

Suggested discovery budget: one isolated experiment matrix, at most two diagnostic
attempts per hypothesis, 30 minutes wall-clock, zero external models/SSH. Stop on
missing host capability or required production authority, not after each test.
This plan does not itself authorize new migration code, production changes,
terminating user sessions, deleting caches, pushing or merging dev/main.
