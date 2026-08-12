# Extending Sulde Community

The extension SDK helps a fork create its own content without importing Sulde's private runtime or
corpus. It has four generators and one explicit registry.

## Principles

- Generate the smallest useful file.
- Put skill trigger context in YAML `description`; keep the body procedural and concise.
- Register an executable module once. Do not also add a second manifest/autodiscovery path.
- Refuse overwrites and path traversal.
- Treat generated skill and hook code as reviewed project code, not as new Agent authority.
- Keep diagnostics free of credentials, complete payloads, user-home paths, and session content.

## Add a skill

```sh
sulde add-skill release-review --description "Review release evidence"
```

This creates `skills/community/release-review/SKILL.md`. Replace generic inputs, procedure, and
acceptance placeholders with project-specific facts. Keep detailed references one level below the
skill only when they are actually needed.

## Add a hook

```sh
sulde add-hook ticket-gate \
  --event PreToolUse --matcher "Write|Edit" \
  --description "Require an approved ticket for scoped writes"
```

The module exposes `run(config, payload)`. The existing Community entrypoint loads it through
`extensions/registry.json`; do not modify `hooks/hooks.json` to register the same extension again.

Hook extensions should stay deterministic, fast, local, and quiet when they have nothing useful to
say. A failure is disclosed by extension name and exception type without dumping the payload.

## Add a doctor check

```sh
sulde add-check repo-policy --description "Check repository policy files"
```

The check exposes `run(context)` and returns:

```python
{"status": "pass", "message": "policy files are present", "detail": ""}
```

Allowed statuses are `pass`, `warn`, and `error`. Run it from a copy that has no `.git` directory to
prove the check does not accidentally depend on source-checkout metadata.

## Add a knowledge container

```sh
sulde add-knowledge-container domain-notes
```

The generator creates a template README and updates both extension and knowledge container
registries. New projects receive the empty container when initialized. Documents inside it still
pass the same dedup, redaction, lint, and index gates.

## Validate a fork

```sh
./bin/sulde doctor --strict
python3 -m unittest discover -s tests -v
git diff --check
```

Then stage a clean copy without `.git`, caches, or local configuration and run doctor from that
copy. Passing only from the development checkout is insufficient release evidence.
