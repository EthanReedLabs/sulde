# M1 isolated host migration feasibility

Intent completion:6514aef628e75bf2049c2c4e, revision 12 applied 2026-10-06.
Native receipt 63549e8e01ee2d9e7f1a86ad866027415c56f2e7e4768dece99bd7360a676439.
Baseline ab8b41948bfc78a0ea2889956c5db9c7b79b3e46; capability_tier deep.

One bounded outcome: determine whether the installed Codex 0.160.0 can move old
loaded Hook callers from a legacy cached command to a cache-external command.
This is a host-mechanism experiment, not a Sulde production migration or new grant.

Use a synthetic six-event plugin, two real app-server processes sharing one
isolated home and a third new process at the post-registry/pre-old-reload boundary.
Local deterministic Responses fixture only; fixed printf tool, no credentials,
SSH, business files or external model calls. Establish both old callers' normal
callback controls before official CLI refresh; observe actual callback script
identity and host notifications after refresh, reconcile and config reload.
Trust only exact synthetic Hook hashes through the isolated host config API.

Record each boundary and RPC outcome, cache existence, Hook identity and failures.
A successful registry/config response is not migration proof. A new caller at the
post-registry boundary is not evidence of safety at every instant during prune.
Keep conclusions local to observed processes; no all-host drain claim from ps,
heartbeats or thread/loaded/list. The existing migration gate remains unchanged.

Budget: 30 minutes active experiment work; at most two attempts without new
evidence per hypothesis. Stop on missing host capability, scope/authority expansion
or budget; ordinary fixture repair continues without another user prompt.
Evidence is retained uniquely under .codex-agent/s3c-m1-evidence, then archived to
the already-authorized Optimus S3-C-repair directory. One independent final review.
No dev/main merge, push, installation, cachebuster, user-session stop or production
cache/config/ledger change. Only self-created fixture process groups are stopped.

Native approval transport reported a persisted command prefix although this call
requested no prefix_rule. This is retained as an independent host observation;
the prefix is not reused as authority and is not modified in this experiment.
