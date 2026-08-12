# Project-owned Knowledge Kit

The Community knowledge kit is an empty local skeleton. Markdown and Git are the source of truth;
`INDEX.md` is derived. The CLI uses lexical similarity only and makes no model, network, MCP, or
background-process call.

## Containers

- `anti-patterns`: recurring failures with verified causes and prevention
- `case-studies`: evidence-backed investigations
- `platform-kb`: platform-specific facts and procedures
- `tech-docs`: reusable designs and contracts
- `work-model`: reusable human–Agent and team methods
- `containers/*`: categories created by a downstream fork

## Document contract

Every document requires:

```yaml
---
doc_id: "anti-patterns/example"
container: "anti-patterns"
platform: "cross"
title: "Example"
summary: "One reusable sentence."
status: "draft"
---
```

Allowed status values are `draft`, `active`, and `deprecated`. The project may extend controlled
vocabularies deliberately, but schema and tests must change together.

## Light sediment loop

1. Verify the incident and root cause in the source project.
2. Search with the symptom, not only an internal term:

   ```sh
   sulde kb dedup --root . "symptom description"
   ```

3. Create a new de-identified copy:

   ```sh
   sulde kb redact --root . raw.md --output safe.md
   ```

   The scanner reports finding categories and irreversible short digests, not matched secrets.
   It never overwrites the source file.

4. Create a draft:

   ```sh
   sulde kb sediment --root . --source safe.md \
     --container anti-patterns --title "Title" --summary "Reusable lesson"
   ```

5. Replace all TODO fields with evidence. Remove incident-specific names and paths.
6. Run `kb lint`, then `kb index`.
7. Review the diff. Promotion to `active`, commit, push, and publication remain human/project actions.

## Direct add

Use `kb add` when the body is already generalized and reviewed. It still fails on likely duplicate
content or deterministic redaction findings.

## Search limitations

Search is deliberately small: token overlap plus normalized sequence similarity. It works offline
and is reproducible, but it is not semantic/vector retrieval. If a downstream project adds another
index, Markdown remains the truth and the index must be rebuildable.

## Redaction limitations

Static scanning catches common credential assignments, private keys, home paths, email addresses,
UUIDs, and IP addresses. It cannot prove a document is safe or generalized. Human review must still
look for product names, business facts, customer data, internal URLs, screenshots, stack traces,
and distinctive incident details.
