# design-truth — canonical UI truth per page

Each `.md` here describes **one screen / page** of your app. Each accompanying `.png` is the visual reference. Together they are the **single source of truth** that wins over scaffold defaults, PRD text, and existing code when the four disagree.

## File-naming convention

```
design-truth/
├── <page-id>.md            # truth doc
├── <page-id>.png           # visual reference (2x scale recommended)
├── <page-id>.png.meta.json # optional: page node-id, design-source file, last sync timestamp
└── _example.md.template    # format example
```

`<page-id>` is whatever your project uses to label pages. Common patterns:
- Numeric: `01`, `02A`, `02B`, `03A1`
- Slug: `home`, `discover`, `me-credit-history`

Keep it stable across the project — task-mds reference these ids verbatim.

## How docs get generated

If your project uses a design tool with MCP support (Pencil / Figma), run `/update-design` — the skill reads `.sulde-config.yaml: design_source`, walks the page node tree, and writes truth docs + screenshots automatically.

Otherwise, write by hand following `_example.md.template`.

## What goes in a truth doc

See `_example.md.template`. Key sections every doc should have:

1. **Node tree** — the design source's structural breakdown (component nesting + props)
2. **Visual key attributes** — fill / stroke / corner radius / font / icon name, with concrete values from the design source
3. **Asset reference list** — every image / icon used, mapped to the file path the dev should copy from
4. **Implementation hard constraints** — non-negotiable rules (e.g. "must use the project's TopBar scaffold, not a one-off bar")

## What does NOT go here

- **Backend API specs** → that belongs in your API documentation system, not in design-truth.
- **General PRD text** → that belongs in your product spec system.
- **Stack-specific implementation notes** → those go in each frontend's `CLAUDE.md` or `<docs-hub>/00_shared-rules/`.

## Priority when sources disagree

```
user explicit instruction > design-truth > scaffold contract > existing implementation
```

If a coordinator-drafted task-md cites design-truth that conflicts with the scaffold's default values, the task-md must include a "数据源冲突段" (data-source conflict section) per `skills/coordinator/writing-task-md/SKILL.md §0.5.4`.
