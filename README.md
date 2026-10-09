<h1 align="center">
  <strong>Sulde</strong>
</h1>

<p align="center">
  <a href="https://github.com/EthanReedLabs/sulde"><img src="https://img.shields.io/github/stars/EthanReedLabs/sulde?style=flat&amp;label=%E2%98%85&amp;color=08C" alt="GitHub stars" /></a>
  <img src="https://img.shields.io/badge/license-BSL_1.1-08C?style=flat" alt="License: BSL 1.1" />
  <img src="https://img.shields.io/badge/macOS%20%7C%20Windows%20%7C%20Linux-4493F8?style=flat-square" alt="macOS, Windows, Linux" />
</p>

<p align="center">
  <strong>Intent-supervised AI coding agent execution.</strong><br/>
  Run Claude Code and Codex side-by-side with versioned intent contracts,<br/>
  per-action effect classification, and experience-driven verification.
</p>

---

## Features

<table>
<tr><td width="50%" valign="middle">

### Intent Contracts

Every task starts with a versioned, auditable contract binding task, run, session, and source identity. Feedback can never retroactively alter the original prediction.

</td><td width="50%" valign="middle">

### Effect Classification

Per-action safety invariants — external writes, destructive operations, and unresolved outcomes each get their own verification path. No blanket Allow/Deny.

</td>
</tr>
<tr><td width="50%" valign="middle">

### Correction Lifecycle

Feedback isn't just "rejected" or "approved" — it flows through proposed → delivered → acknowledged → verified → closed, with the executor unable to self-settle.

</td><td width="50%" valign="middle">

### Experience Feedback

Verified experience is recalled through formal entry points and changes future verification strategy. Expired experience loses authority — stale knowledge never silently drives decisions.

</td>
</tr>
<tr><td width="50%" valign="middle">

### Dual-Host Supervision

Claude Code and Codex run side-by-side under the same intent contract, each with independent worktrees, session binding, and generation fencing.

</td><td width="50%" valign="middle">

### Zero-Token Supervision

All supervision — effect classification, identity binding, drift detection, feedback consumption — runs as deterministic local scripts. Zero added model calls.

</td>
</tr>
<tr><td width="50%" valign="middle">

### Formal Retry &amp; Continuation

Failed attempts are retried through a formal retry channel bound to a stable operation identity. Continuations inherit intent contracts, not execution authority — and feedback artifacts survive across attempt boundaries.

</td><td width="50%" valign="middle">

### Evidence Archive

Every run produces a SHA256-hashed evidence manifest: source identities, prompt captures, consumption records, probe outputs, and prediction checks — independently readable, never overwritten.

</td>
</tr>
</table>

## Supported Agents

<p align="center">
  <a href="https://claude.ai/claude-code"><kbd><img src="https://www.google.com/s2/favicons?domain=claude.ai&sz=64" alt="Claude Code" width="16" valign="middle" /> Claude Code</kbd></a> &nbsp;
  <a href="https://openai.com/codex"><kbd><img src="https://www.google.com/s2/favicons?domain=openai.com&sz=64" alt="Codex" width="16" valign="middle" /> Codex</kbd></a> &nbsp;
  <a href="https://opencode.ai"><kbd><img src="https://www.google.com/s2/favicons?domain=opencode.ai&sz=64" alt="OpenCode" width="16" valign="middle" /> OpenCode</kbd></a> &nbsp;
  <a href="https://aider.chat"><kbd><img src="https://www.google.com/s2/favicons?domain=aider.chat&sz=64" alt="Aider" width="16" valign="middle" /> Aider</kbd></a> &nbsp;
  <a href="https://www.continue.dev"><kbd><img src="https://www.google.com/s2/favicons?domain=continue.dev&sz=64" alt="Continue" width="16" valign="middle" /> Continue</kbd></a> &nbsp;
  <a href="https://mistral.ai"><kbd><img src="https://www.google.com/s2/favicons?domain=mistral.ai&sz=64" alt="Mistral Vibe" width="16" valign="middle" /> Mistral Vibe</kbd></a> &nbsp;
  <a href="https://qwenlm.github.io/qwen-code/docs/en/kimi-code-cli/getting-started.html"><kbd><img src="https://www.google.com/s2/favicons?domain=qwenlm.github.io&sz=64" alt="Qwen Code" width="16" valign="middle" /> Qwen Code</kbd></a> &nbsp;
  <a href="https://kilocode.ai"><kbd><img src="https://www.google.com/s2/favicons?domain=kilocode.ai&sz=64" alt="Kilocode" width="16" valign="middle" /> Kilocode</kbd></a> &nbsp;
  <a href="https://kiro.dev/docs/cli/"><kbd><img src="https://www.google.com/s2/favicons?domain=kiro.dev&sz=64" alt="Kiro" width="16" valign="middle" /> Kiro</kbd></a> &nbsp;
  <a href="https://windsurf.com"><kbd><img src="https://www.google.com/s2/favicons?domain=windsurf.com&sz=64" alt="Windsurf" width="16" valign="middle" /> Windsurf</kbd></a> &nbsp;
  <a href="https://cursor.com"><kbd><img src="https://www.google.com/s2/favicons?domain=cursor.com&sz=64" alt="Cursor" width="16" valign="middle" /> Cursor</kbd></a> &nbsp;
  <a href="https://gemini.google.com/docs/cli"><kbd><img src="https://www.google.com/s2/favicons?domain=gemini.google.com&sz=64" alt="Gemini CLI" width="16" valign="middle" /> Gemini CLI</kbd></a> &nbsp;
  <a href="https://github.com/block/goose"><kbd><img src="https://www.google.com/s2/favicons?domain=block.github.io&sz=64" alt="Goose" width="16" valign="middle" /> Goose</kbd></a> &nbsp;
  <a href="https://github.com/paul-gauthier/aider"><kbd><img src="https://www.google.com/s2/favicons?domain=aider.chat&sz=64" alt="Aider" width="16" valign="middle" /> Aider</kbd></a> &nbsp;
  <a href="https://codebuddy.ai"><kbd><img src="https://www.google.com/s2/favicons?domain=codebuddy.ai&sz=64" alt="CodeBuddy" width="16" valign="middle" /> CodeBuddy</kbd></a> &nbsp;
  <a href="https://www.codebuff.com"><kbd><img src="https://www.google.com/s2/favicons?domain=codebuff.com&sz=64" alt="Codebuff" width="16" valign="middle" /> Codebuff</kbd></a> &nbsp;
  <a href="https://github.com/anthropics/claude-code"><kbd><img src="https://img.shields.io/badge/Claude_Code_Dev-08C?style=flat-square" alt="Claude Code Dev" /></kbd></a> &nbsp;
  <a href="https://github.com/Cline CLI/cline"><kbd><img src="https://www.google.com/s2/favicons?domain=cline.bot&sz=64" alt="Cline" width="16" valign="middle" /> Cline</kbd></a> &nbsp;
  <a href="https://github.com/All-Hands-AI/openhands"><kbd><img src="https://www.google.com/s2/favicons?domain=all-hands.dev&sz=64" alt="OpenHands" width="16" valign="middle" /> OpenHands</kbd></a> &nbsp;
  <a href="https://github.com/princeton-nlp/SWE-agent"><kbd><img src="https://www.google.com/s2/favicons?domain=swe-agent.com&sz=64" alt="SWE-Agent" width="16" valign="middle" /> SWE-Agent</kbd></a> &nbsp;
  <a href="https://github.com/SWE-bench/SWE-bench"><kbd><img src="https://img.shields.io/badge/SWE_bench-08C?style=flat-square" alt="SWE-bench" /></kbd></a> &nbsp;
  <a href="https://github.com/AgentLess/agentless"><kbd><img src="https://img.shields.io/badge/AgentLess-05C?style=flat-square" alt="AgentLess" /></kbd></a> &nbsp;
  <a href="https://github.com/RVCC-idpv/rvo-dev"><kbd><img src="https://www.google.com/s2/favicons?domain=atlassian.com&sz=64" alt="Rovo Dev" width="16" valign="middle" /> Rovo Dev</kbd></a> &nbsp;
  <kbd>+ any CLI agent</kbd>
</p>

<details>
<summary><strong>架构说明</strong></summary>
<br/>
Sulde 通过 <code>runtime_provider.py</code> 的统一选择链管理多个 CLI Agent 宿主。
新宿主只需实现两个约定：<strong>从 stdin 读取任务简报</strong> + <strong>产出结构化事件流</strong>。
其余（意图合同绑定、效果分类、纠偏生命周期、经验召回）由 Sulde 框架自动提供。
</details>
<summary><strong>架构说明</strong></summary>
<br/>
Sulde 通过 <code>runtime_provider.py</code> 的统一选择链管理多个 CLI Agent 宿主。
新宿主只需实现两个约定：<strong>从 stdin 读取任务简报</strong> + <strong>产出结构化事件流</strong>。
其余（意图合同绑定、效果分类、纠偏生命周期、经验召回）由 Sulde 框架自动提供。
</details>

## How It Works

```
┌─────────────────────────────────────────────────┐
│              Intent Contract (v1)                │
│  task_id · run_id · session_id · source_id      │
│  expected_touch · impact_bounds · invariants    │
├─────────────────────────────────────────────────┤
│           PreToolUse (Effect Classifier)         │
│  in-scope → allow · out-of-scope → deny         │
│  unresolved → intervention → human gate          │
├─────────────────────────────────────────────────┤
│           PostToolUse (Fact Collection)          │
│  drift detection · verdict · evidence            │
├─────────────────────────────────────────────────┤
│         Feedback Artifact (v1)                   │
│  request_id · source run · facts · probe         │
├─────────────────────────────────────────────────┤
│      Experience Recall → Next Prediction         │
└─────────────────────────────────────────────────┘
```

Supervision runs as deterministic local scripts — zero added model calls. The agent sees the intent contract and feedback in its execution input and adjusts accordingly.

## Install

### Claude Code Plugin

```bash
# Via Claude Code plugin marketplace
claude plugin install sulde-cc@sulde
```

### Codex Plugin

```bash
# Via the transactional installer
python3 scripts/release/install_codex_plugin.py --artifact-root <path>
```

### From Source

```bash
git clone https://github.com/EthanReedLabs/sulde.git
cd sulde
claude plugin install .
```

---

## License

Sulde is free to use under the [BSL 1.1 License](LICENSE) (Change Date: 2030-05-25 → MIT). Prior versions (v0.1.x) remain under MIT.
