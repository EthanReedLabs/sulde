# Bounded protocol models, not implementation proofs

`SessionContinuity` explores two sessions, two workspaces, one upgrade, a bounded
cache corruption, append/publication separation, and log-tail eviction. Readiness
never grants permission. Weak fairness assumes available index and Hook workers
eventually run; it does not assume a human will approve anything. Its negative
configuration deliberately copies a prior-workspace grant and must fail.

`DenialRecovery` separates a shape-only pre-denial, an ordinary action, independent
verification, and a later high-risk native decision. Existing unknown debt is
never rewritten by recovery. Its negative configuration deliberately pauses after
shape denial and must fail. Liveness does not require native Allow.

`CHECK_DEADLOCK FALSE` permits legitimate quiescent/awaiting-human terminal states.
It does not waive liveness: the explicit progress properties remain enabled in
the positive models. These finite models do not prove arbitrary Python code,
filesystem safety, host implementation, cryptography, or unbounded concurrency.

Run TLC offline with the official `tla2tools.jar`; do not ship it or call it from
Hooks. See https://github.com/tlaplus/tlaplus and
https://docs.tlapl.us/using%3Atlc%3Astart for the upstream runner.
Positive configurations must exit successfully; negative configurations must
report the named invariant violation, not merely any nonzero exit. Real isolated
CLI/unified-exec/Hook tests are a separate required acceptance layer.
