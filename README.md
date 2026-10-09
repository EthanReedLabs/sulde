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
  <a href="https://claude.ai/claude-code"><kbd><img src="https://img.shields.io/badge/Claude_Code-08C?style=flat-square" alt="Claude Code" /></kbd></a>
  &nbsp;
  <a href="https://openai.com/codex"><kbd><img src="https://img.shields.io/badge/Codex-000000?style=flat-square" alt="Codex" /></kbd></a>
  &nbsp;
  <kbd>+ any CLI agent</kbd>
</p>

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
