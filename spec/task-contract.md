# Managed program task contract

The executable parser is `_validate_task` in `scripts/kb/guardian_program.py`.
This public specification describes its input, not an approved task instance.

Required fields are `schema`, `task_id`, `title`, `owner`, `capability_tier`,
`base_commit`, `depends_on`, `owned_paths`, `requirements`, `acceptance` and
`evidence_gates`. `supersedes` is optional; other fields are rejected.
`capability_tier` is `light`, `balanced` or `deep`.

Identifiers must satisfy the parser's identifier contract. `owned_paths` is a
nonempty list of canonical relative POSIX paths or terminal `/**` subtrees.
Absolute paths, dot segments, backslashes and arbitrary glob syntax are invalid.
Acceptance is nonempty. A task cannot both depend on and supersede the same task.

Each of `implemented`, `task_verified`, `integrated` and `system_verified`
requires a nonempty list of evidence kinds. Defining those names does not prove
the corresponding state; the execution and verification machinery supplies it.

The following is a synthetic parsing example. Replace its base and scope with
verified task facts before proposal; it carries no approval or execution grant.

```json
{
  "schema": "sulde-guardian-program-task-v1",
  "task_id": "synthetic-example",
  "title": "Validate a synthetic bounded change",
  "owner": "example-agent",
  "capability_tier": "balanced",
  "base_commit": "0000000000000000000000000000000000000000",
  "depends_on": [],
  "supersedes": [],
  "owned_paths": ["src/example.py", "tests/test_example.py"],
  "requirements": [],
  "acceptance": ["The changed behavior and its negative case are verified"],
  "evidence_gates": {
    "implemented": ["changed_files"],
    "task_verified": ["targeted_tests"],
    "integrated": ["integration_tests"],
    "system_verified": ["system_tests"]
  }
}
```
