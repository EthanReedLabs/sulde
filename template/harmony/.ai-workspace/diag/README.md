# diag/ — diagnostic artefacts (logs, traces, profiler output)

This directory holds raw diagnostic outputs that handoffs reference. Keep raw files small — large traces should be summarised in the handoff and the raw files kept here only if essential.

## What goes here

- `adb logcat` capture (per task / per incident)
- Perfetto / Systrace `.perfetto-trace` files
- GPU profiler dumps (`dumpsys gfxinfo`)
- Network capture logs from Charles / mitmproxy summary
- Memory dumps (hprof) → ⚠️ size-check before committing; usually keep outside git

## Naming

```
{YYYY-MM-DD}-{task-slug}-{purpose}.{ext}
```

Examples:
- `2026-05-25-feature-foo-launch-log.txt`
- `2026-05-25-feature-foo-trace.perfetto-trace`
- `2026-05-25-feature-foo-gfxinfo.txt`

## What does NOT go here

- Screenshots → `../screenshots/`
- Build output → don't commit (`build/` is `.gitignore`d)
- Handoff docs → `../handoff/`
