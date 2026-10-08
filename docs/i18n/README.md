# i18n — Translations

Translations of the user-facing docs (`README.md`, `docs/METHODOLOGY.md`, `docs/GETTING_STARTED.md`) live here under `{lang}/` subdirectories.

```
docs/i18n/
├── README.md       (this file)
├── zh-CN/          (placeholder — Chinese Simplified)
└── (other languages as contributed)
```

## Conventions

- One subdirectory per language code (`zh-CN`, `zh-TW`, `ja`, `ko`, `de`, `es`, `fr`, …)
- Mirror the original filenames inside: `METHODOLOGY.md` → `zh-CN/METHODOLOGY.md`
- Translations are not required to be 1:1 with the English original — adapt examples to local idiom where it helps reading
- Add a top-line note in each translated file linking back to the English original so readers can verify against the source of truth

## Contributing translations

See [`CONTRIBUTING.md`](../../CONTRIBUTING.md) — translations land via PR. Maintainers cannot verify all languages; reviews focus on whether the structure matches and the cross-reference links resolve.

## Current state (v0.1)

No translations yet. The first translation accepted will set the precedent for subsequent ones — early contributors are appreciated.
