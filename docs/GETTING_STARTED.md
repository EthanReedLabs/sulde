# Getting Started (Community 0.3.0)

This walkthrough takes a clean Claude Code install to the first verified task/handoff loop.

## 1. Check prerequisites

- Claude Code with plugin support
- Python 3.10 or newer
- PyYAML 6.0 or newer
- Git
- Git Bash or WSL2 when using Claude Code hooks on Windows

Install and diagnose:

```text
/plugin marketplace add EthanReedLabs/sulde
/plugin install sulde@sulde
```

The repository and current plugin ID are `sulde` (previously `sulde-cc`). Existing
plugin installations keep their old identity until migrated. When switching to
`sulde@sulde`, disable the old plugin entry to avoid loading both sets of hooks.
Existing knowledge and memory data should be reused through the configured data
root; renaming the repository does not require moving it.

```sh
python3 -m pip install -r "${CLAUDE_PLUGIN_ROOT}/hooks/requirements.txt"
"${CLAUDE_PLUGIN_ROOT}/scripts/sulde" doctor
```

The doctor result must have zero errors. A warning that a project has not opted in is expected
until initialization.

## 2. Initialize a project

Open Claude Code at the project root and run:

```text
/sulde-init
```

The guided flow asks for the project name, role, mobile stacks, optional design source, team,
enforcement level, grace period, language, and primary OS. It then creates:

- `.sulde-config.yaml`
- the `docs-hub/` and root script skeleton
- selected stack directories and `.ai-workspace/` skeletons
- an empty project-owned `knowledge/` kit
- a local grace-period marker
- project pre-commit hooks where selected

The copier must preserve files that already exist. Review the generated files before committing.

Verify the initialized project:

```sh
"${CLAUDE_PLUGIN_ROOT}/scripts/sulde" doctor --project "$PWD"
"${CLAUDE_PLUGIN_ROOT}/scripts/sulde" kb lint --root "$PWD"
```

## 3. Add team identities if needed

For a multi-person project:

```text
/sulde-add-team-member as-a Alice alice@example.invalid android
```

This stores a repository-local Git alias. Use `git as-a commit ...` so handoffs and commits retain
the configured identity. A solo project can leave `team: []`, which disables the alias gate.

## 4. Establish project truth

Before dispatching work, replace template placeholders and record the facts the task will depend
on:

- actual frontend paths and stack commands;
- design source or the explicit absence of one;
- build/install/launch/log/screenshot verification commands;
- sensitive paths and scaffolds;
- integration branch and ownership.

Do not copy project names, classes, paths, or tool output from example documents as if they were
current truth. Verify them in the adopting repository.

## 5. Dispatch the first task

In the coordinator session, describe one bounded outcome. The skill-trigger reminder points to
`coordinator/writing-task-md`. The task contract should include:

- verified baseline evidence;
- allowed and rejected scope;
- acceptance checks;
- target branch and assignee;
- exact handoff expectations.

Write it below the selected frontend's `.ai-workspace/tasks/` directory.

## 6. Execute and hand off

In a separate Dev session rooted at that frontend, invoke `dev/assign` with the task path. The
workflow rechecks the baseline, performs the task, verifies it, and creates a five-section handoff.
It does not auto-commit or auto-push.

The coordinator reviews objective evidence and either accepts the result or dispatches a bounded
follow-up. A user correction should update the task contract rather than accumulate contradictory
instructions.

## 7. Grow local knowledge after a reusable incident

If a verified fix is reusable across tasks, prepare a de-identified source file and run:

```sh
"${CLAUDE_PLUGIN_ROOT}/scripts/sulde" kb dedup --root "$PWD" "symptom description"
"${CLAUDE_PLUGIN_ROOT}/scripts/sulde" kb redact --root "$PWD" incident.md --output safe.md
"${CLAUDE_PLUGIN_ROOT}/scripts/sulde" kb sediment --root "$PWD" \
  --source safe.md --container anti-patterns \
  --title "Reusable title" --summary "Reusable lesson"
```

Review the draft, replace every TODO with evidence, run `kb lint`, and rebuild `kb index`. The tool
never publishes or commits knowledge for you.

## 8. Extend only when the base loop is stable

A fork can generate a project-specific skill, hook, check, or knowledge container. Generated files
are intentionally small and unpopulated. See [EXTENDING.md](EXTENDING.md).

## Troubleshooting

Run:

```sh
"${CLAUDE_PLUGIN_ROOT}/scripts/sulde" doctor --project "$PWD" --json
```

Common results:

- `PyYAML is not installed`: install `hooks/requirements.txt` in the Python used by the hook.
- `project has not opted in`: create or locate `.sulde-config.yaml` in the current ancestor chain.
- `VERSION and plugin.json differ`: the plugin package is incomplete or mixed-version.
- `hook launcher is not used`: reinstall from a clean release rather than a partial directory copy.
- Windows mojibake: use the bundled launchers; they force `PYTHONIOENCODING=utf-8` and
  `PYTHONUTF8=1` before Python starts.
