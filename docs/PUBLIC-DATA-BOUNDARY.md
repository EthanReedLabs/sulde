# Public data boundary

The Harness implementation includes Guardian, LIFE, knowledge and memory engines,
host adapters, schemas and installation tooling. It does not include any operator's
formal corpus, project/session memory, vectors, production ledgers, receipts,
internal task reports, credentials or private Git history.

Runtime state belongs in each user's local data directory. Tests must construct
synthetic data. Do not import production exports as test fixtures.

This is a review candidate, not an accepted release or installation receipt.
