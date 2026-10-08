# T28 cleanup quarantine consumer correction

Implement only the registered T28 task definition from base
`f8c830b02a814cf40c541ef861569882062174c0`.

## Required implementation

1. In `self-repair.py`, stop using the authoritative same-resource
   `blocking_attempts()` projection as a global worktree-cleanup gate. Consume
   the T27 readiness/quarantine projection that still blocks open,
   acknowledged, retry-authorized, reprobe-authorized and unhandled unknown
   attempts but permits terminal abort quarantine to be archived before local
   worktree removal.
2. Preserve the archive-before-remove ordering. Archived abort debt must still
   replay in `blocking_attempts()` for future matching of the same external
   resource and must not be described as externally settled.
3. Extend `tests/test_self_repair.py` with explicit positive and negative
   assertions for the two projections. Do not weaken the existing unresolved
   intervention refusal.
4. Write the T28 report with a `沉淀候选` section. Do not edit any other source,
   production contract/ledger, installed cache, LaunchAgent state or remote.

## Required tests

- the self-repair cleanup module;
- the T27 intervention/readiness/statusline/scheduler modules;
- focused failure injection proving terminal abort archives while every
  nonterminal unknown state still refuses cleanup.

Do not run installation or live scheduler/session operations. The coordinator
owns the complete isolated suite and production release gates.
