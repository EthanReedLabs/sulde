# Recovery routing repair: installed release evidence

Date: 2026-09-07. Intent: completion:267ee3915da180f817ed2ddd, revision 20.

## Result and boundaries

The input-shape repair is implemented, merged into local dev, installed and verified by a real PreTool denial in the existing Codex session. This is not a claim that every recovery capability or a full injected-fault/native-repair journey has been accepted. No production fault was injected. No push was performed during these checks.

- Repair commit: e9d66610180d02e87191b85a3299f3cf97c3dfeb.
- Installed source commit: 4929a85445b399ffc17eccc0841368a9f0548bcd; the difference is the official cachebuster field only.
- Version: 0.2.5+codex.20260907050036-0fc70680ae.
- Runtime generation: 0.2.5+codex.20260907050036-0fc70680ae:b54d7c1e3fb28aa8988b765e334d7e3792a15f526d13ee7d59ad1d1646daa249.
- Artifact root: /Users/eric/.sulde/artifacts/sulde-0.8.4-0.2.5-codex.20260907050036-0fc70680ae/codex.
- Source staging, installed runtime, deployment, runtime owner and launcher refer to that generation. Deployment and owner operational_ready=true; independent doctor status and operational_readiness.status are ready.
- Scheduler: 16/16 loaded, failed_labels={}, no missing or retired labels. Deployment, owner and launcher share activation d9a627ab37074e629ecb37ad00d2461e and runner SHA256 6d4076f6e35f4327972d84ca1edf1f3f72323c18369c39d6ce6358cd23158d50.
- Six required Sulde Hooks were unique, enabled and trusted. Current lane Hook failure projection is clear; current session Pre/Post observations bind the new runtime. Static skill catalog pickup is distinct from live Hook verification.

## Tests and retained evidence

- Red tests reproduced the original string/dictionary mismatch before the five-line route fix.
- Scoped combined run: 68 tests OK, 9.292 seconds; see r18 report. No repeated full-suite run.
- Exact repair HEAD run: 14 tests OK, unittest 4.194 seconds, harness 4.657 seconds. Evidence run 20260907T045644.545351-e5a091af5856 under .sulde/data/test-evidence; log SHA256 a8d8d99023ae547c2064f14cdf984383fc671b2e130a771c0a7ea50a83d213f5. Record contains source, environment, scope and expiry; no source bytecode cleanup was needed.
- Candidate recovery-r20: prepared 1.693 seconds, verified 13.069 seconds. Receipt eb7f39c313c802d1750514f0a6e5c80d55616600b2e3dc2d3856800c55db64f3, retained in /private/tmp/sulde-recovery-candidates-r20/recovery-r20/verification-receipt.json.
- Candidate CLI/Hook subprocess proof is separate from the real host proof below. Candidate native permission UI and production scheduler activation were explicitly unobserved before promotion.
- Transaction install: 31.509 seconds, snapshot/prepare 12.766 seconds (largest phase); promotion wrapper 31.682 seconds. No rollback triggered. These measurements exclude human approval wait time.
- Plugin structure validation and diff check passed. r17 failed candidate is retained as failure evidence, not reused.

## Current-session live proof and effect settlement

Session: 01a04634-318f-7203-ba2d-26fa6ac442b0; no restart was used for this check.

The prepared exact rm canary was submitted through the actual tool and denied by PreToolUse before execution. The marker path did not exist on independent readback. No synthetic hook invocation was used as this live proof.

- Probe: 80df30ac80991709c4036e239b67aa35.
- Proof: 4434dc5db8faa42f73ea07802d4703edd9f75b4759a3273e30a4fd19f60d1114.
- Started event: d7113f46d886c24a040805e1.
- Call: exec-46e70f39-af17-4e20-bb95-83c3c620dbf9.
- loaded_module_generation: 30ebc8b8871c4bc43671215922d2e24be5221259c9289299a619b2cd98831f71.
- artifact_generation: the installed generation above. finalize validated both bindings; gaps_cleared=0.
- Cachebuster attempt att-490ffdac51be14947cca0a22 and install attempt att-8fb581bf79f8725eda271cf6 both system_verified by their registered independent verifiers.
- Reconciliation returned pending_verifications=0; doctor reports all nine historical/current attempts system_verified, no open intervention, no effect debt and no current lane blocker. An older inconclusive event remains inconclusive, not fabricated as successful.

## Additional execution observations

- r19 became stale when the external official helper changed from digest 97c5ecab... to 6a630dfb... between approval and execution. It was refused before execution, with grants unused. r20 rebound the observed bytes; no tests were rerun for this external change.
- A promotion invocation with -B selected a different profile than the approved v1 call. The corrected relative call still met the old Hook's cwd routing defect. Read-only binding inspection showed the exact candidate and grant match; using the same script's absolute worktree path enabled the approved v1 call without bypassing Guardian.
- A sandbox Git index-lock denial was handled by normal host escalation. Candidate prepare refused the dirty tree until the version commit succeeded. Production state was not altered by these failed preflight commands.
- The host reported saving exact approval prefixes despite no prefix_rule parameter being requested. They were not reused for new decisions.
- Knowledge search did not return a relevant existing input-shape case; unrelated hits were not adopted. Root-cause and repair evidence remain in the r17/r18 reports as sedimentation candidates.

## Remaining separate acceptance

Still unverified: a real same-session controlled fault, native recovery Allow/Deny, exact file repair, independent recovery verifier and continuation of the original task. The successful installation, ordinary denial canary and fixture recovery tests do not replace that journey. Windows native acceptance remains delegated to Windows.

Any later commit containing only this report does not change the installed source identity recorded above; do not claim that a documentation-only HEAD was rebuilt or reinstalled.
