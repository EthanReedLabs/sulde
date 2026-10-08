# Candidate generation deployment acceptance

Status: implementation verified; live promotion pending a separately sealed external-write revision.

## Failure boundary

The former installer staged an artifact, removed and re-added the live Codex
registry, published launchers, and only then ran the expensive Hook/MCP/intent
smoke. A defect in those post-switch checks therefore interrupted ordinary
sessions even though the artifact could have been rejected without touching the
live generation.

The candidate controller now separates the workflow into these states:

1. `prepare` stages and seals an immutable artifact without live registration.
2. `verify` uses isolated `CODEX_HOME`, `SULDE_HOME`, KB, workspace, launcher,
   cache, and LaunchAgent roots. It invokes the production Hook, MCP, doctor, and
   scheduler entrypoints. Host UI and daemon observations that cannot safely run
   in the isolated slot remain nonzero `unobserved` evidence.
3. `promote` consumes one receipt bound to the exact source commit/tree,
   artifact/runtime digests, audited Codex executable/version/help observation,
   verification matrix, and live prestate.
4. The installer repeats the prestate CAS inside its deployment lock and again
   at the transaction boundary. It reuses the verified artifact and performs a
   minimal live Hook/MCP/registry canary instead of rerunning the whole matrix.
5. `install_codex_plugin.py --recover-only` can reconcile a durable transaction
   without entering the candidate controller, Guardian, or a plugin Hook.

`discard` accepts only one canonical candidate slot and never targets the
candidate home itself. A failed or consumed receipt cannot be promoted again.

## Implementation evidence

- Scoped installer/candidate regression: 58 passed, 67 subtests passed.
- Combined Guardian/release regression: 316 passed, 18 skipped, 177 subtests passed.
- Exact worktree full suite: 1685 passed, 23 skipped, 1531 subtests passed.
- Failure injection covers invalid Hook output, null decision projection,
  generation mismatch, missing MCP server, and scheduler backend failure. Every
  verification failure records an exact live pre/post projection and requires
  equality before reporting `live_preserved=true`.
- The first full run found one text-subprocess encoding violation in the new
  test. It was corrected; the dedicated guard and candidate suite then passed
  before the final full-suite run.
- The first real `prepare` attempt exposed a restricted-host observation bug:
  the stable promotion CAS incorrectly depended on `launchctl list`, and a
  failed prepare left an unsealed slot that `discard` could not consume. The
  CAS now binds deployment/launcher/scheduler-owner files while promotion's
  locked actor preflight owns process state; prepare persists `prepare_failed`,
  and orphan discard accepts only exact `artifact`/`isolated` contents.
- The first real `verify` then reached the isolated MCP manifest route and
  failed because the fresh KB root correctly had no production venv. Candidate
  setup initially used a regular executable wrapper bound to the current
  audited Python, but a real launcher probe proved that the wrapper changes
  `sys.executable` after exec and triggers the launcher's identity rebind loop.
  The final design asks the selected interpreter to create a copied,
  system-site-enabled isolated venv, then resolves it through the canonical
  `kb_cli.resolve_venv_python` authority and verifies exact interpreter bytes.
  It neither aliases nor copies the live KB home and requires no network
  dependency installation.
- Real isolated candidate `r176-real4` passed on commit
  `7215036b22f788f380994b980847e7aa2d0854a6`. Receipt
  `8814e66af47ba754655bddba6463fba80aeae7a9ea79397998d0db593fe6f124`
  binds plugin tree `6e6b08bb4277c4d2682968194841224698855c26a14bbb074f162ac35930e726`,
  runtime tree `5058d662cbee76297411178a043fae58fe4663c921d8eb731ac45368827fd84f`,
  and live prestate `aabf64661f1394af917d32fff4b425af83ddbdef81fe27f51d94708533a11482`.
  Isolated registry, real Hook entrypoints, packaged/manifest MCP, doctor, and
  all 16 scheduler entries passed. Native UI and launchd remained explicit
  nonzero `unobserved` (78/79), while isolated Hook discovery correctly reported
  `review_required` because the disposable CODEX_HOME did not grant trust.
- Five real isolated negative candidates on commit `fc31c0e` were rejected
  before promotion: `hook_invalid_json`, `decision_null`,
  `generation_mismatch`, `mcp_missing`, and `scheduler_failure`. Each persisted
  `verification_failed` with `live_preserved=true`; each exact slot was then
  discarded before preparing the next candidate.
- After the canonical venv-resolver correction, final real candidate
  `r176-final` passed again on code commit
  `a2d054bfb7fef43be336eb2a4dac810d3c175d97`, producing receipt
  `fb04d7e2f2a86e6669f5d60a3ef8996e38fc690aeaa95f6302cd0b1ff7dfc844`.
  Its live prestate remained
  `aabf64661f1394af917d32fff4b425af83ddbdef81fe27f51d94708533a11482`;
  native UI and launchd remained explicit 78/79 `unobserved`.

## Remaining acceptance

This report does not claim a production promotion. The current revision forbids
merge, push, and live install. After the implementation commit is clean, a real
isolated candidate must be prepared and verified, then a separate external-write
revision must authorize fast-forward merge/push and one receipt-bound promotion.
The final section must record candidate ID, receipt digest, exact dev commit,
promotion timings, live canary, scheduler readiness, and rollback/recovery result.

## Sedimentation candidate

Evidence status: conclusive.

- Problem context: post-switch validation coupled long test work and potential
  defects to the currently serving plugin generation.
- Routing positive: immutable candidate verification in isolated state roots;
  only a complete exact receipt may enter promotion.
- Routing negative: uninstall-first, live-home candidate tests, dry-run-only
  success, or reuse of a receipt after source/live drift.
- Execution positive: double locked CAS, artifact reuse, minimal live canary,
  and a Guardian-independent durable recovery entrypoint.
- Execution negative: rebuild during promotion, synthetic authority, zero-exit
  `unobserved` evidence, production scheduler labels in a candidate slot, or a
  recovery command routed through the failed Hook/control path.
