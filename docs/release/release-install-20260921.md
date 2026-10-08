# release-2026-09-21 — local Codex installation record

> Corrected 2026-09-23: installation completed; end-to-end acceptance remains
> incomplete in the available evidence. This historical snapshot is not a
> current health check. See [corrections and open gates](release-evidence-corrections-20260923.md).

## Scope

- Release: `release-2026-09-21`, dev `7eb0592eaf1db1bb4391de65ef8b6bc445c69166`,
  main `31be07411947edc07951f293c23403011c72565b` (identical trees).
- Deltas: `17b1c31` fix(distill) rejected-annotation resilience + type enum prompt;
  `ce62ec9` fix(mem-sync) retry envelope 6×2s; blockers doc `5c319cc`;
  cachebuster `7eb0592`.
- New version: `0.2.5+codex.20260922005243-95a8cf2d92`.
- Installation was executed from a Claude Code session. The session reported
  that no Codex-native approval pair was consumed and that the trusted-command
  route allowed the installer. Execution success is not an independent audit of
  that authority route, nor proof that every host/provider combination is supported.

## Recorded installation course (3 attempts)

1. First run rejected at staging: artifact path collision — the repo manifest
   still carried the 2026-09-16 version. Fixed by the `7eb0592` cachebuster.
2. Second run rejected post-staging, rolled back: installed codex-cli 0.155.1
   (self-updated) ≠ audited `codex-cli 0.154.0`. Fixed by pinning
   `@openai/codex@0.154.0` globally; no override was used or available.
3. Third run: `"status": "generation_verified"`.

## Historical installation observations (not full acceptance)

| Gate | Result |
| --- | --- |
| Installer status | `generation_verified`, `scheduler_ready_live_host_unverified` |
| Runtime owner | `operational_ready: true`, provider codex, launchd |
| Scheduler | 16/16 labels loaded and `failed_labels: {}` at the recorded post-install readback. Later in the same session self-repair had exit 1; sustained health and a first-ever clean state are not established. |
| Launcher contract | Both homes were reported healthy after a separate Claude-side launcher refresh; this does not establish that the installer alone updated both homes. |
| Live statusline | new format rendered through the Claude-side launcher: `kb:388·边220 mem:48.4k 待嵌:0 收割:9m前 L2:r/L3:r/L4:r/E:r` |
| Previous generation | marketplace preserved; legacy caches retired as controlled aliases with restored tree digests |

## Boundaries

- The original readback reported `ok=false`, debt counts of 270 open
  interventions / 289 blocking effects / 370 event-contract violations, and
  `host_readiness: unobserved`. These are historical observations, not freshly
  verified counts or proof that no other failure exists.
- Live interactive supervision, native pairing settlement, and the negative
  canary were NOT verified by this installation record. Close these gates with
  actual host evidence bound to the installed generation. This record does not
  prove that restarting Codex is the only way to obtain that evidence.
- A separate minimal Codex call reported a usage limit and a retry time of
  2026-09-22 18:12. That is not proof that quota subsequently recovered, that
  every organ failed for that cause, or that a scheduled run later passed.
- Advancing the distill watermark from 49913 to 50147 bypassed the previous
  incremental range. The later `no work` result does not prove extraction or
  recovery of that range. Coverage and any compensating backfill remain unverified.
- The new distill conflict path and mem-sync retry envelope need corresponding
  installed-generation live evidence; increasing backoff alone does not prove
  permanent collision elimination.
- The [three suite failures](release-blockers-20260921.md) remain open. Neither
  installation success nor a momentarily clean scheduler closes those gates.
