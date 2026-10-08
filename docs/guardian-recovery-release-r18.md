# Recovery routing input-shape repair

Date: 2026-09-07. capability_tier: deep.
Intent: completion:267ee3915da180f817ed2ddd, revision 18.

The native proposal approved only the recovery route, its regression tests, and release reports. No r17 install grant was reused.

## Change and evidence

- Added a dictionary check before native recovery command field access. A non-dictionary tool input returns no recovery route; ordinary normalization/enforcement remains responsible for the call. No catch-all exception or recovery allow decision was added.
- New regression uses both tool_input/toolInput and strings, lists, integers, booleans, null and empty input across PreToolUse, PermissionRequest and PostToolUse. Recovery state remains unchanged.
- Actual adapter subprocess regression verifies string functions.exec input reaches observable ordinary PreTool denial and PostTool audit fixtures. It tests the routing boundary, not the full policy implementation or native UI.
- Before repair: two new tests reproduced the bug (24 subcase errors, one adapter subprocess failure). After repair: 68 tests OK in 9.292 seconds through scripts/kb/run-isolated-tests.py.
- Modules: test_production_recovery_control, test_production_recovery_readiness, test_launcher_split_recovery, test_codex_hook_bridge, test_recovery_lane. Interpreter: installed KB venv Python. Completion tool chunk fa8af2, process session 56082.
- Existing exact native command, foreign identity, expiry, composed-command and independent-verifier tests remain passing.

This file records the tested working-tree change included with it, not a completed installation. Exact committed evidence and the fresh candidate receipt must be read separately. Earlier 137-test evidence covers the predecessor only; counts are not summed.

## Release boundary

r17 remains verification_failed and preserved. A new version and source-bound candidate are required. Production installation and same-session live recovery are not proven by these tests. Main, production runtime, other sessions and authority logs were not modified by this repair.

## Sedimentation candidate update

The r17 root cause is confirmed and has a scoped tested repair. Routing positive: early adapters consume host fields before common normalization. Routing negative: exact native shell dictionary already has valid typed handling. Execution positive: non-recovery string routes to ordinary policy/audit without recording recovery authority. Execution negative: blanket exception swallowing or coercing arbitrary wrapper source into an authorized recovery command. Native candidate and production evidence remain separate; no direct knowledge-base write performed.
