# Coordinator baseline (before runtime glue)

Input source: aa9ffc147c189a5a18c9209c2edec2e8e538d2e1 plus frozen TASK
4b047c8. No production runtime or model invocation.

Command: venv Python -B -m unittest discover -s tests
-p test_guardian_s2_runtime.py -v. Actual managed CLI, temporary real Git
repository, fake provider captures stdin, independent consumer probe.

Observed: 2 tests in 2.022s; normal control passed; execution-method input
assertion failed (exit 1). Exact missing substring:
`--- Sulde 有界执行方法（不新增权限） ---`.
Provider still completed successfully and consumer returned `ok 2`; failure
is missing input wiring, not task execution infrastructure. Same test assertions
will be retained for candidate verification. Full failure output remains in the
coordinator session; this file records bounded results, not a recreated raw log.
