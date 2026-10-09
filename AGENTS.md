# Repository instructions

## Branch and worktree discipline

- Keep the main working checkout on local `dev`, the latest integrated development branch.
- The upstream repository exposes only `main`. Keep `dev` and task branches local.
- Start each task branch from local `dev` in a repository-local `.worktrees/<task>` worktree.
- Commit task changes in that worktree. Run the scoped checks and merge the completed task into `dev`.
- Do not merge failed, experimental, interrupted, or superseded candidates.
- Verify the integrated `dev` tree before advancing `main`. Both the task and integration worktrees must be clean before merging.
- `main` is the publication branch. Feature and repair changes reach it through `dev`; do not commit them directly to `main`.
- Push only `main` to the upstream repository. Remove an old upstream task branch after its required commits are included in published `main`.
- Resolve branch divergence on `dev`, verify the result, then advance `main`.

See [CONTRIBUTING.md](CONTRIBUTING.md#maintainer-branch-workflow) for the commands and fork contribution workflow.
