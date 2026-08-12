# Project knowledge

This is an empty, Git-tracked growth container. It does not ship Sulde Pro content, a model,
a vector database, background automation, or an external service.

Start with:

```sh
scripts/sulde kb add --root . --container anti-patterns --title "..." --summary "..."
scripts/sulde kb lint --root .
scripts/sulde kb index --root .
scripts/sulde kb search --root . "symptom description"
```

The light sediment flow is explicit: de-identify an incident, check likely duplicates, create a
draft, review the reusable cause/fix/evidence, lint it, then rebuild the index. No step publishes,
commits, or calls a remote model.
