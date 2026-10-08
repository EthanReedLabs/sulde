# release-2026-09-16 — local Codex installation acceptance

## Frozen scope

- Release: `release-2026-09-16`, main `f4d77551162797f7c384a8a3e1b48342ac5a1e0a`.
- Dev base: `128ccbaa60db84e11b4d356668501c890953044a` (identical release tree).
- Installed source: `29e62536cb9d10530cf0902913a1c1ac0902943d`.
- Only executable-delivery source delta is the Codex manifest version field, produced by the
  official plugin-creator helper. No application, Guardian or installer logic changed.
- New version: `0.2.5+codex.20260916062947-c68dd312d0`.
- Native-reviewed sealed cachebuster/install receipt:
  `b3ab43ef73bab76dcbcf7fe4c42c27ae0bbb251d6ba2a5d3b944acc3d15a9f44`.
- Install only Codex using the official transactional installer. Preserve user data, knowledge,
  memory, history and rollback artifacts. No new scheduler scope, log upload or extra model calls.
- Integrate accepted metadata/report into dev only. Do not change main/tag or push this task.

## Acceptance

| Gate | Result |
| --- | --- |
| Source equality | All files except manifest version match the release before installation |
| Plugin manifest validation | Passed |
| Isolated packaging/validation tests | 17 tests, 0 failures/errors, 1 original native-Windows skip, 16.978 s |
| Official installation | Exit 0, `generation_verified`, 53.443 s |
| Durable transaction | `79278dec07db47fa8114d6f8dd0190ac`, postconditions verified at seq12, committed at seq13 |
| Generation | Installed runtime, stable launchers and scheduler match the new version and runtime digest below |
| Scheduler | 16/16 original managed labels loaded, no missing or failed labels |
| Current-session doctor | `ready`, operational readiness `ready`, all interactive gates true |
| Pairing | settled=true, status=not_required, no open decision or CAS mismatch |
| Effects | Two one-shot actions system_verified; no intervention or pending verification |
| Real pre-execution denial | Current-generation negative canary verified, file not deleted; not a synthetic hook invocation |

Runtime tree SHA256: `ea640329c3c54cf87982ab64c9ceb44f4108d7c47e3a00c0bbee97fe0efb4913`.
Plugin tree SHA256: `35f1db09ec0f4f50f0584d0131716454b373ecd05a7a5a84486ab411007aa899`.
Live negative-proof ID: `85c3bf369e0b2f7224a5b39ad4c304dd20832b5a33482d0e6a968a1a7054ec21`.

The installer correctly returned live-unverified immediately after switching. Subsequent genuine
current-session tool hooks and verified continuity established operational readiness, followed by
the real negative canary. This is not a claim that synthetic installation probes prove live safety.
No restart was required for this session's verified hook runtime. Static Skill/MCP discovery should
be checked in a new thread; no new-thread discovery, native Windows execution, or a fresh human
approval under the new generation is claimed. Current pairing requires no further human decision.

## Evidence and boundaries

Local evidence is archived in dev worktree `.sulde/public-export/release-install-20260916/`.
Raw evidence is not committed or uploaded. Source release acceptance remains the existing 2401-test
verification with 27 original skips; this metadata-only installation did not rerun that full suite.

- `doctor-final.json`: `55abac2de1c9fc5b382c8a8adcff180fb6f785bd6128075b5c0b2a84635f2970`.
- `live-negative-proof.json`: `03e1c77f949c1c36e28e242807958b4ad68b24c47df2a09f58406735380476cc`.
- `scoped-tests.log`: `3cc832dd82e51fd317d1a2ec844d3d95c35510fbe396e54baa3df98616798aec`.
- Durable installer descriptor SHA256:
  `d994da81f8cbce1e4f249be11193b08b5bfe17b2d471922886b13e564adcfad2`.
- Durable installer journal SHA256:
  `9805a0bdc6021fcd1ffc7e9d28eddcf8b5e2463c8e19bcb64bc67bd394e0691f`.
- The captured installer stdout exceeded the tool output cap and is explicitly retained as
  `installer-stdout.truncated.txt`, not represented as a complete raw log. Durable transaction
  commit readback, deployment manifest, stable launcher manifest and independent doctor provide
  the installation acceptance evidence.

## Findings during execution

- Initial dry-run before task binding was denied without production mutation; new native-reviewed
  task scope and explicit worktree handoff established the correct lane.
- The helper's default timestamp invocation was denied before writing. The Guardian requires a
  proposal-bound token, while the generic plugin skill recommends a default token. Reading the
  registered maintenance profiles led to an explicitly reviewed one-shot cachebuster/install
  pair. No alternate executor or manual cache edit was used.
- Marketplace listing hit a sandbox network restriction; the approved read-only retry succeeded.
- These are recorded workflow observations, not new implementation tasks. No scope expansion or
  changes to the Guardian authorization mechanism were made.
- Final dev integration and exact worktree/branch cleanup are verified through ordinary Git and
  the official lifecycle completion receipt; production data and previous artifacts remain.
