# Knowledge contribution standard

This is a public workflow specification, not a copy of an operator's formal
knowledge corpus. A fresh distribution has zero knowledge documents. Project
memory and internal reports remain in the originating project's private store.

## Evidence and ownership

The originating Agent records a Layer1 problem card using
`templates/knowledge/problem-card.md`. Keep task context, symptoms, evidence,
applicability and routing/execution positive and negative examples. Label
constructed tests as constructed; do not describe them as observed incidents.
Use `inconclusive` for insufficient evidence, not an invented conclusion.

Only the designated knowledge writer curates Layer2. Search for duplicates
before adding a document; merge compatible material into an existing entry.
Knowledge or memory transport does not authorize publication. The human retains
the decision on a new public audience, private data, cost or expanded scope.

## Structure

Use `templates/knowledge/schema.json` and the matching template for
anti-patterns, platform-kb, tech-docs, case-studies or work-model. See
`docs/kb-retrieval-contract.md` for identifiers and retrieval semantics.
Include stable doc_id, container, platform, summary, sedimentation_schema,
problem_type and evidence_status. Preserve routing apply/skip and execution
pass/fail examples, their reasons, sources and applicability limits.

Assign anti-pattern numbers from this corpus's own highest existing number;
an empty corpus starts at 0001. Do not import another corpus's numbering or
document inventory. Existing identifiers must remain stable.

## Privacy and validation

Remove private project names, machine paths, people, session identifiers,
credentials, raw logs, commit/branch identities, business-specific content and
unapproved external links. Publishing generalized methods requires its own
review; a document being in a local knowledge base is not publication consent.

Run the repository's frontmatter and sedimentation linters and regenerate the
index/manifest after an approved contribution. Validate references against the
current corpus. Use synthetic fixtures for regressions, never production
memory, receipts or ledgers. Empty-data startup must not load another user's
corpus or model cache to conceal a missing dependency.
