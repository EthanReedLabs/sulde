#!/usr/bin/env bash
#
# Sulde skill-trigger.sh
#
# Reads the user's prompt from stdin (UserPromptSubmit hook contract — JSON with `prompt` field).
# Scans for trigger keywords. When a Sulde skill should apply, prints a reminder to stdout —
# Claude Code surfaces this as a system-reminder before processing the prompt.
#
# Project-config-aware: reads `.sulde-config.yaml` from the current working directory
# (or the closest ancestor) to learn the project's role (coordinator vs dev vs both)
# and the configured frontends. Trigger keywords are merged from a built-in list
# plus any overrides in `.sulde-config.yaml` under `skill_triggers:`.
#
# Exit code 0 always — this hook is advisory, never blocking.

set -u

input="$(cat)"

# Extract the user prompt (UserPromptSubmit hook payload is JSON: {"prompt": "..."}).
# Use a tolerant grep-and-sed approach so the hook works without jq installed.
prompt="$(printf '%s' "$input" | sed -n 's/.*"prompt"[[:space:]]*:[[:space:]]*"\(.*\)".*/\1/p' | head -c 2000)"

if [ -z "$prompt" ]; then
  exit 0
fi

# Find the nearest .sulde-config.yaml by walking up from CWD.
#
# Opt-in by design: if no .sulde-config.yaml is found in the current project
# tree (walk-up from CWD up to /), the plugin stays SILENT — no reminders,
# no log output, nothing. This means installing the plugin is harmless to
# projects that did not opt in. Only projects with .sulde-config.yaml in
# their root will see Sulde's trigger reminders.
config_path=""
dir="$(pwd)"
while [ "$dir" != "/" ]; do
  if [ -f "$dir/.sulde-config.yaml" ]; then
    config_path="$dir/.sulde-config.yaml"
    break
  fi
  dir="$(dirname "$dir")"
done

# No config = not a Sulde-managed project = exit silently.
if [ -z "$config_path" ]; then
  exit 0
fi

# Optional kill switch: `enabled: false` in config also yields silent exit.
# Useful for temporarily turning Sulde off in a Sulde-aware project without
# uninstalling the plugin.
enabled_flag="$(sed -n 's/^enabled:[[:space:]]*//p' "$config_path" | head -1 | tr -d ' "')"
if [ "$enabled_flag" = "false" ]; then
  exit 0
fi

# Parse role from config (default: coordinator). Tolerant single-line extraction.
role="coordinator"
cfg_role="$(sed -n 's/^role:[[:space:]]*//p' "$config_path" | head -1 | tr -d ' "')"
if [ -n "$cfg_role" ]; then
  role="$cfg_role"
fi

# Built-in trigger map: keyword regex -> reminder text.
# Each line: `<regex>::<skill-id>::<role-filter>::<reminder>`
# role-filter is one of: coordinator, dev, any
triggers=(
  '(派活|派单|派任务|写.{0,3}task|dispatch.{0,3}task|assign.{0,3}task)::writing-task-md::coordinator::Before writing the task-md, invoke the writing-task-md skill — it enforces §0 baseline / §1 design-truth / §3 scope / §5 verify / §6 git completion / §7 host-neutral capability selection.'
  '(/assign|执行.{0,3}task|跑.{0,3}task)::assign::dev::You are about to run a task-md. Invoke the assign skill — it gates on §0 baseline drift, §1 design-truth staleness, and §3 scope.'
  '(设计稿|design.{0,3}truth|figma.{0,3}export|new.{0,3}design|update.{0,3}design|refresh.{0,3}design)::update-design::coordinator::Design-truth refresh requested. Invoke the update-design skill — it extracts node tree + visual + asset-reference list from the configured design-source MCP.'
)

# Merge any per-project overrides (lines under `skill_triggers:` in config).
# Schema: `skill_triggers: [{regex: "...", skill: "...", role: "...", reminder: "..."}, ...]`
# Not parsed here in v0.1 — placeholder for v0.2 when we add a proper YAML parser.

matched=""
for entry in "${triggers[@]}"; do
  regex="${entry%%::*}"
  rest="${entry#*::}"
  skill="${rest%%::*}"
  rest="${rest#*::}"
  filter="${rest%%::*}"
  reminder="${rest#*::}"

  if [ "$filter" != "any" ] && [ "$filter" != "$role" ]; then
    continue
  fi

  if echo "$prompt" | grep -Eqi -- "$regex"; then
    matched="${matched}- [sulde:${skill}] ${reminder}\n"
  fi
done

if [ -n "$matched" ]; then
  printf 'Sulde skill triggers matched this prompt:\n%b' "$matched"
fi

exit 0
