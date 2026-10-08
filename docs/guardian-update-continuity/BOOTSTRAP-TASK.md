# First bootstrap: independent host design and isolated verification

Date: 2026-10-06. capability_tier: deep. Provider: Codex.
Baseline: `9c9f8a81c34df01f842f7a0e311dda9917a66d8b`.
Intent: completion:6514aef628e75bf2049c2c4e revision 15.
Native scope receipt: 319eaea2e106bf5398fc5845bfd238457fc09f7ec40565d8bc9819a49f4afe6c.

Deliver a precise first-bootstrap boundary and verify its native protocol in a
separate fixture-owned Codex home. This amends r14's architecture stop only for
tests/design; product source, production homes/config, live user processes,
installation, dev/main, push and paid/external models remain excluded.

Expected changes: one tests-only native-host fixture, a backward-compatible
command injection seam in M1's fixture, evidence runner and task documentation.
Because that seam is shared, rerun M1/M2; no product-wide full suite.

Normal control: actual CLI app-server, unified exec, on-request/read-only policy,
no Sulde plugin or inherited contract. Synthetic local provider asks for one
digest-bound fixture worker command. Capture a real request before any effect;
test client accept results in one local marker. This is NOT a human Allow.
Negative cases: decline; second invocation requests again; post-prompt plan drift
causes worker refusal; disconnect pending causes no execution. No arbitrary code,
network, process signalling or installation exists in the worker.

Document the missing production seam honestly: an independently supervised host
requires its own real human UI/decision for the exact operation. An Agent replying
to app-server requests in a test is not a way to authorize production. A host tool
approval binds a command, not arbitrary future file contents; a real worker must
verify immutable content, old CAS, cohort, deadline and one-use state itself.

Continue fixture repair, normal/injection checks, actual host and affected tests
through one consolidated independent review. Same baseline host executable and
configuration for controls and negative cases; these are capability tests, not
claims of an old product bug fixed. Forty-five active minutes, zero paid models;
two failures without new facts change method. Stop on authority/scope expansion,
unavailable genuine human bridge or unsupported host behavior, not each test.

Evidence: unique local `.codex-agent/s3c-bootstrap-evidence` run, then Optimus
`Sulde/tasks/guardian-unified-plan-20261004/S3-C-repair/` unique archive with hashes.
Preserve failures; no raw business sessions or secrets. Rollback task changes only,
retain evidence and close only fixture-owned process groups.

Official protocol source (read 2026-10-06):
[App Server approvals](https://learn.chatgpt.com/docs/app-server#approvals).
Native request identity carries thread/turn/item; client replies accept/decline.
Neither documentation nor this test proves an installed Sulde bootstrap adapter.
KB ap-0247 read in full: exact one-shot authority is not a generic Allow flag.
