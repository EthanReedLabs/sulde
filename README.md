<p align="center">
  <img src="docs/assets/sulde-readme-banner.svg" alt="Sulde — plan, build, verify" width="100%" />
</p>

<h1 align="center">From AI coding tasks to verifiable delivery.</h1>

<p align="center">
  Give your coding agents a shared workflow for tasks, project context, and review.<br/>
  Define the work. Carry forward what you learn. Check what was delivered.
</p>

<p align="center">
  <a href="#quick-start"><strong>Get started</strong></a> ·
  <a href="#a-task-from-brief-to-review">See the workflow</a> ·
  <a href="#supported-agents">Supported Agents</a> ·
  <a href="#documentation">Documentation</a> ·
  <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <a href="docs/DEVELOPMENT.md">Claude Code + Codex adapters</a> &nbsp;·&nbsp;
  <a href="docs/MCP.md">MCP / CLI interfaces</a> &nbsp;·&nbsp;
  <a href="LICENSE">MIT License</a>
</p>

## Why Sulde?

A coding task carries more than a prompt: its scope, project history, decisions, and definition of done.
Sulde brings that context into a workflow you and your coding agents can inspect.

- **Keep the task clear.** Record the owner, dependencies, allowed changes, and acceptance criteria before execution.
- **Bring useful experience forward.** Find relevant project knowledge and recorded session context, with sources you can check.
- **Review the work with evidence.** Connect changes to their checks and reports, and send incomplete work back for a focused revision.

Sulde is independently developed. This repository contains the framework source and a CLI toolkit
you can call from your existing agent workflow.

## Supported Agents

Works with **any agent or tool that can run CLI commands**. Call Sulde directly from the workflow you already use.

<p>
  <a href="https://code.claude.com/docs/en/overview"><kbd><img src="https://www.google.com/s2/favicons?domain=claude.ai&amp;sz=64" alt="Claude Code logo" width="16" height="16" valign="middle" /> Claude Code</kbd></a> &nbsp;
  <a href="https://github.com/openai/codex"><kbd><img src="https://www.google.com/s2/favicons?domain=openai.com&amp;sz=64" alt="Codex logo" width="16" height="16" valign="middle" /> Codex</kbd></a> &nbsp;
  <a href="https://cursor.com/docs/cli/overview"><kbd><img src="https://www.google.com/s2/favicons?domain=cursor.com&amp;sz=64" alt="Cursor logo" width="16" height="16" valign="middle" /> Cursor</kbd></a> &nbsp;
  <a href="https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli"><kbd><img src="https://www.google.com/s2/favicons?domain=github.com&amp;sz=64" alt="GitHub Copilot logo" width="16" height="16" valign="middle" /> GitHub Copilot</kbd></a> &nbsp;
  <a href="https://opencode.ai/docs/cli/"><kbd><img src="https://www.google.com/s2/favicons?domain=opencode.ai&amp;sz=64" alt="OpenCode logo" width="16" height="16" valign="middle" /> OpenCode</kbd></a> &nbsp;
  <a href="https://geminicli.com/docs/"><kbd><img src="https://www.google.com/s2/favicons?domain=gemini.google.com&amp;sz=64" alt="Gemini CLI logo" width="16" height="16" valign="middle" /> Gemini CLI</kbd></a> &nbsp;
  <a href="https://docs.cline.bot/usage/cli-overview"><kbd><img src="https://www.google.com/s2/favicons?domain=cline.bot&amp;sz=64" alt="Cline logo" width="16" height="16" valign="middle" /> Cline</kbd></a> &nbsp;
  <a href="https://github.com/continuedev/continue/tree/main/extensions/cli"><kbd><img src="https://www.google.com/s2/favicons?domain=continue.dev&amp;sz=64" alt="Continue logo" width="16" height="16" valign="middle" /> Continue</kbd></a> &nbsp;
  <a href="https://kiro.dev/docs/cli/"><kbd><img src="https://www.google.com/s2/favicons?domain=kiro.dev&amp;sz=64" alt="Kiro logo" width="16" height="16" valign="middle" /> Kiro</kbd></a> &nbsp;
  <a href="https://qwenlm.github.io/qwen-code-docs/"><kbd><img src="https://www.google.com/s2/favicons?domain=qwenlm.github.io&amp;sz=64" alt="Qwen Code logo" width="16" height="16" valign="middle" /> Qwen Code</kbd></a> &nbsp;
  <kbd>+ any CLI-capable tool</kbd>
</p>

Claude Code and Codex also include host adapters for skills, hooks, and managed task execution.
Knowledge and memory tools are additionally available through MCP.

[Get started with the CLI →](#quick-start) · [Host adapters →](docs/DEVELOPMENT.md) · [MCP tools →](docs/MCP.md)

## A task from brief to review

**Example: fix a cache refresh that overwrites newer data.**

| Step | What you do with Sulde | What you can review |
| --- | --- | --- |
| Define | Set the goal, affected files, owner, and regression checks. | A task brief with a clear definition of done. |
| Prepare | Retrieve related lessons and check their original sources. | Relevant context and the reasons for applying it. |
| Execute | Dispatch to Claude Code or Codex; use an isolated worktree for a managed task. | Changes and recorded execution events. |
| Verify | Run the selected checks and review the report against the task. | Results tied to the work that was tested. |
| Improve | Return unmet criteria for revision and record a verified lesson for later use. | A focused follow-up and reusable project knowledge. |

This is an example of a configured workflow. You and the coordinating agent choose the task,
checks, and acceptance decision. See the [task guide](spec/task-authoring.md) for the underlying contract.

## Quick start

**Try a small local workflow first.** You need Git and Python 3.10+.
This example exercises the knowledge toolkit without an agent account, a model, or an MCP server.

**1. Set up the source toolkit**

```sh
git clone https://github.com/EthanReedLabs/sulde.git
cd sulde
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r hooks/requirements.txt
python -B scripts/sulde.py doctor --strict
```

<details>
<summary>Windows / PowerShell</summary>

After cloning the repository, create the environment with `py -3 -m venv .venv`.
Install dependencies with `.venv\Scripts\python.exe -m pip install -r hooks/requirements.txt`,
and replace `python` below with `.venv\Scripts\python.exe`.

</details>

**2. Save and find one lesson**

Run from the repository root, using a fresh `.tmp/sulde-demo` directory:

```sh
python -B scripts/sulde.py kb init --root .tmp/sulde-demo
python -c "from pathlib import Path; Path('.tmp/sulde-demo/lesson.md').write_text('Ignore an older cache refresh response after a newer request has completed.', encoding='utf-8')"
python -B scripts/sulde.py kb add --root .tmp/sulde-demo --container anti-patterns --title "Stale cache refresh" --summary "Keep newer cache results from being overwritten." --body .tmp/sulde-demo/lesson.md
python -B scripts/sulde.py kb lint --root .tmp/sulde-demo
python -B scripts/sulde.py kb search --root .tmp/sulde-demo "stale cache refresh"
```

The lint result should report `"documents": 1` and `"errors": []`. Search should return
**Stale cache refresh** with the document ID `anti-patterns/stale-cache-refresh`.
The generated document starts as a draft. Review it before treating it as project guidance.

This toolkit uses local lexical search. The full knowledge and memory runtime has its own dependencies
and initialization; see the [Knowledge Kit](docs/KNOWLEDGE-KIT.md) and [MCP guide](docs/MCP.md).

**3. Connect the capabilities you need**

| Your next step | Guide |
| --- | --- |
| Add Sulde to Claude Code or Codex | [Build and configure a host adapter](docs/DEVELOPMENT.md) |
| Use knowledge and memory from a compatible MCP client | [Set up the local MCP server](docs/MCP.md) |
| Define and dispatch an engineering task | [Write your first task brief](spec/task-authoring.md) |

Host adapters are delivered as source candidates. Check the selected revision's CLI compatibility
and installation instructions before enabling a full workflow.

## What you can build on

| Capability | How it helps |
| --- | --- |
| **Task orchestration** | Organize owners, dependencies, scope, dispatch, and acceptance around explicit tasks. |
| **Knowledge & memory** | Retrieve engineering lessons and recorded context across projects and sessions. |
| **Execution visibility** | Observe host events, tool operations, and outcomes through configured adapters. |
| **Verification & rework** | Keep checks and delivery reports attached to the task, with a path back to revision. |
| **Project extensions** | Add skills, hooks, checks, knowledge containers, and project-specific conventions. |
| **Project templates** | Start from Android, iOS, Flutter, and HarmonyOS templates; reuse the shared tooling elsewhere. |

## Architecture

```text
Task brief → Host adapter → Execution → Checks & evidence → Review / revision
                  ↕                         ↕
          Project knowledge and recorded session context
```

The host adapter connects Claude Code or Codex to the shared runtime. Skills guide the workflow;
CLI and MCP interfaces expose individual capabilities. Managed execution adds an isolated worktree
and task-bound reports. [Explore the host contract →](docs/dual-runtime-contract.md)

## A few practical questions

**Can I use only the knowledge tools?**

Yes. The local toolkit runs independently. The MCP server exposes a separate set of knowledge,
memory, status, and event tools; connecting it does not enable the entire task workflow.

**Will it remember every conversation automatically?**

Memory search needs recorded data. Session ingestion and background maintenance require their own
configuration; a new MCP connection alone does not collect the client's conversation history.

**Where does my data live?**

Knowledge and memory use the configured local data directory. Data sent to a connected client,
model, or external service depends on your configuration. See the [data boundary](docs/PUBLIC-DATA-BOUNDARY.md).

## Documentation

| Start using Sulde | Go deeper |
| --- | --- |
| [Host setup & packaging](docs/DEVELOPMENT.md) | [Host runtime contract](docs/dual-runtime-contract.md) |
| [Knowledge Kit](docs/KNOWLEDGE-KIT.md) | [Task contract](spec/task-contract.md) |
| [MCP setup & tools](docs/MCP.md) | [Event observation](docs/event-observability.md) |
| [Task authoring](spec/task-authoring.md) | [Extension guide](docs/EXTENDING.md) |

## Contribute

Share a reproducible issue, improve a confusing instruction, or contribute a reusable engineering example.
Read the [contribution guide](CONTRIBUTING.md), or [open an issue](https://github.com/EthanReedLabs/sulde/issues).
If Sulde is useful to you, a star helps other developers find it.

## License

Open source under the [MIT License](LICENSE). Commercial use is permitted; retain the copyright
and permission notices. See the [licensing guide](docs/LICENSING.md) for scope and historical releases.

---

**Start with one task you can verify.** [Get started ↑](#quick-start)
