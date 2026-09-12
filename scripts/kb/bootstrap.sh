#!/usr/bin/env bash
# Bootstrap the stable, version-independent Sulde KB runtime home.

set -u

# Runtime trees are generation-sealed.  Bootstrap and every Python child it
# launches must not mutate them by materializing import caches.
PYTHONDONTWRITEBYTECODE=1
export PYTHONDONTWRITEBYTECODE

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SULDE_ROOT=${SULDE_HOME:-"$HOME/.sulde"}
KB_HOME=${SULDE_KB_HOME:-"$SULDE_ROOT/data/kb"}
if [ -n "${SULDE_LAUNCHER_HOME:-}" ]; then
  LAUNCHER_HOME=$SULDE_LAUNCHER_HOME
elif [ "$KB_HOME" = "$SULDE_ROOT/data/kb" ]; then
  LAUNCHER_HOME=$SULDE_ROOT
else
  # Explicit portable/test homes remain self-contained.
  LAUNCHER_HOME=$KB_HOME
fi
resolve_venv_python() {
  if [ -x "$KB_HOME/venv/bin/python" ]; then
    printf '%s\n' "$KB_HOME/venv/bin/python"
  elif [ -x "$KB_HOME/venv/Scripts/python.exe" ]; then
    printf '%s\n' "$KB_HOME/venv/Scripts/python.exe"
  else
    return 1
  fi
}
VENV_PYTHON=""  # 由 resolve_venv_python 在 venv 创建后解析
DRY_RUN=false
LAUNCHERS_ONLY=false
REPAIR_GENERATED_BYTECODE=false
HOST_PROVIDER=${SULDE_HOST_PROVIDER:-auto}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --help|-h)
      if [ "$#" -eq 1 ]; then
        echo "usage: bootstrap.sh [--dry-run] [--launchers-only] [--repair-generated-bytecode] [--host claude|codex|auto]"
        exit 0
      fi
      exit 2 ;;
    --dry-run) DRY_RUN=true ;;
    --launchers-only) LAUNCHERS_ONLY=true ;;
    --repair-generated-bytecode) REPAIR_GENERATED_BYTECODE=true ;;
    --host)
      [ -n "${2:-}" ] || { echo "bootstrap failed: --host needs a value" >&2; exit 2; }
      HOST_PROVIDER=$2
      shift
      ;;
    --host=*) HOST_PROVIDER=${1#*=} ;;
    *)
      echo "usage: bootstrap.sh [--dry-run] [--launchers-only] [--repair-generated-bytecode] [--host claude|codex|auto]" >&2
      exit 2
      ;;
  esac
  shift
done

if [ "$REPAIR_GENERATED_BYTECODE" = true ] && [ "$LAUNCHERS_ONLY" != true ]; then
  echo "bootstrap failed: --repair-generated-bytecode requires --launchers-only" >&2
  exit 2
fi

case "$HOST_PROVIDER" in
  claude|codex) ;;
  auto)
    case "$SCRIPT_DIR" in
      */.codex/*) HOST_PROVIDER=codex ;;
      */.claude/*) HOST_PROVIDER=claude ;;
      *)
        if [ -n "${CODEX_THREAD_ID:-}${CODEX_CI:-}" ] && [ -z "${CLAUDECODE:-}${CLAUDE_CODE_ENTRYPOINT:-}${CLAUDE_SESSION_ID:-}" ]; then
          HOST_PROVIDER=codex
        elif [ -n "${CLAUDECODE:-}${CLAUDE_CODE_ENTRYPOINT:-}${CLAUDE_SESSION_ID:-}" ] && [ -z "${CODEX_THREAD_ID:-}${CODEX_CI:-}" ]; then
          HOST_PROVIDER=claude
        elif command -v claude >/dev/null 2>&1 && ! command -v codex >/dev/null 2>&1; then
          HOST_PROVIDER=claude
        elif command -v codex >/dev/null 2>&1 && ! command -v claude >/dev/null 2>&1; then
          HOST_PROVIDER=codex
        else
          echo "bootstrap failed: auto host is ambiguous; pass --host claude or --host codex" >&2
          exit 2
        fi
        ;;
    esac
    ;;
  *)
    echo "bootstrap failed: host must be claude, codex, or auto" >&2
    exit 2
    ;;
esac

if [ "$DRY_RUN" = true ]; then
  if [ "$LAUNCHERS_ONLY" = true ]; then
    cat <<EOF
Sulde launcher refresh plan
KB home: $KB_HOME
Host provider: $HOST_PROVIDER
1. Regenerate six host-neutral launchers under $LAUNCHER_HOME/bin
2. Record launcher spec, entrypoint, runtime and generated-file digests
3. Verify every launcher resolves the current runtime before reporting ready
4. Preserve a scheduler seal only when deployment, owner, generation and runner bytes all still match
5. If requested, remove generated Python bytecode only after the remaining staged tree matches its sealed generation
No venv, package, model, index, memory, host-settings or plugin-registry write executed in dry-run mode.
EOF
    exit 0
  fi
  cat <<EOF
Sulde KB bootstrap plan
KB home: $KB_HOME
Host provider: $HOST_PROVIDER
1. Create stable data directory: $KB_HOME
2. Create venv if missing: python3 -m venv $KB_HOME/venv
3. Install missing packages into venv: fastembed jieba cryptography pyyaml
4. Verify or preload models into $KB_HOME/fastembed_cache (HF_ENDPOINT is preserved):
   BAAI/bge-small-zh-v1.5 and BAAI/bge-reranker-base
5. Build first index if missing: SULDE_KB_HOME=$KB_HOME scripts/kb/kb-index build
6. Create session memory database if missing: SULDE_KB_HOME=$KB_HOME scripts/kb/kb-index mem-init
7. Create host-neutral stable launchers for Claude Code and Codex caches
8. Merge Sulde statusLine into Claude Code settings only when --host claude is selected
No pip install, model download, index build, launcher, or host settings write executed in dry-run mode.
EOF
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "bootstrap failed: python3 is required; install Python 3.10+ and retry." >&2
  exit 1
fi

SOURCE_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && { pwd -W 2>/dev/null || pwd; })
if [ "$LAUNCHERS_ONLY" = true ]; then
  mkdir -p "$KB_HOME"
  SCHEDULER_SEAL_ARGS=()
  if [ "$HOST_PROVIDER" = codex ]; then
    SCHEDULER_SEAL_ARGS=(--require-scheduler-seal)
  fi
  if [ "$REPAIR_GENERATED_BYTECODE" = true ]; then
    if ! python3 "$SCRIPT_DIR/launcher_contract.py" repair-bytecode \
      --source-root "$SOURCE_ROOT"
    then
      echo "bootstrap failed: runtime contains drift beyond generated bytecode." >&2
      exit 1
    fi
  fi
  if ! python3 "$SCRIPT_DIR/launcher_contract.py" install \
    --home "$LAUNCHER_HOME" --data-home "$KB_HOME" --interpreter-home "$KB_HOME" \
    --source-root "$SOURCE_ROOT" "${SCHEDULER_SEAL_ARGS[@]}"
  then
    echo "bootstrap failed: stable launcher refresh did not verify." >&2
    exit 1
  fi
  echo "Sulde launcher refresh complete: $LAUNCHER_HOME/bin"
  echo "  host provider:     $HOST_PROVIDER"
  echo "  model dispatch:    $LAUNCHER_HOME/bin/model-dispatch"
  echo "  intent guardian:   $LAUNCHER_HOME/bin/intent-guardian"
  exit 0
fi

mkdir -p "$KB_HOME"
if VENV_PYTHON=$(resolve_venv_python); then
  echo "KB venv already exists; skipping."
else
  echo "Creating KB venv at $KB_HOME/venv"
  if ! python3 -m venv "$KB_HOME/venv"; then
    echo "bootstrap failed: could not create venv; verify python3-venv support and permissions." >&2
    exit 1
  fi
  VENV_PYTHON=$(resolve_venv_python) || {
    echo "bootstrap failed: venv created but no interpreter found (tried bin/python, Scripts/python.exe)." >&2
    exit 1
  }
fi

if "$VENV_PYTHON" -c 'import fastembed, jieba, cryptography, yaml' >/dev/null 2>&1; then
  echo "fastembed, jieba, cryptography, and pyyaml already installed; skipping."
else
  echo "Installing fastembed, jieba, cryptography, and pyyaml into KB venv"
  if ! "$VENV_PYTHON" -m pip install fastembed jieba cryptography pyyaml; then
    echo "bootstrap failed: pip install failed; check network/HF_ENDPOINT and retry." >&2
    exit 1
  fi
fi

if "$VENV_PYTHON" - "$KB_HOME/fastembed_cache" <<'PY' >/dev/null 2>&1
from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder
import sys

cache = sys.argv[1]
TextEmbedding(model_name="BAAI/bge-small-zh-v1.5", cache_dir=cache, local_files_only=True)
TextCrossEncoder(model_name="BAAI/bge-reranker-base", cache_dir=cache, local_files_only=True)
PY
then
  echo "Embedding and reranker models already available; skipping."
else
  echo "Preloading BAAI/bge-small-zh-v1.5 and BAAI/bge-reranker-base"
  if ! "$VENV_PYTHON" - "$KB_HOME/fastembed_cache" <<'PY'
from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder
import sys

cache = sys.argv[1]
TextEmbedding(model_name="BAAI/bge-small-zh-v1.5", cache_dir=cache)
TextCrossEncoder(model_name="BAAI/bge-reranker-base", cache_dir=cache)
PY
  then
    echo "bootstrap failed: model preload failed; check network/HF_ENDPOINT and retry." >&2
    exit 1
  fi
fi

if [ -f "$KB_HOME/kb.db" ]; then
  echo "KB index already exists; skipping first build."
else
  echo "Building first KB index"
  if ! SULDE_KB_HOME="$KB_HOME" "$VENV_PYTHON" "$SCRIPT_DIR/kb-index" build; then
    echo "bootstrap failed: initial index build failed; inspect the output above and retry." >&2
    exit 1
  fi
fi

if [ -f "$KB_HOME/memory.db" ]; then
  echo "Session memory database already exists; skipping."
else
  echo "Creating session memory database"
  if ! SULDE_KB_HOME="$KB_HOME" "$VENV_PYTHON" "$SCRIPT_DIR/kb-index" mem-init; then
    echo "bootstrap failed: memory database initialization failed." >&2
    exit 1
  fi
fi

# 生成并验证稳定路径启动器(外部接线指向 bin,插件升级后可检测陈旧派生产物)
if ! "$VENV_PYTHON" "$SCRIPT_DIR/launcher_contract.py" install \
  --home "$LAUNCHER_HOME" --data-home "$KB_HOME" --interpreter-home "$KB_HOME" --source-root "$SOURCE_ROOT"
then
  echo "bootstrap failed: stable launchers did not verify." >&2
  exit 1
fi

STATUSLINE_CONFIGURED=false
STATUSLINE_CONFIG_REASON=""
if [ "$HOST_PROVIDER" = claude ]; then
  if "$VENV_PYTHON" "$SCRIPT_DIR/configure-statusline.py" --install --kb-home "$KB_HOME"; then
    STATUSLINE_CONFIGURED=true
  else
    configure_exit=$?
    STATUSLINE_CONFIG_REASON="配置器退出码 ${configure_exit}（现有非 Sulde 配置会被保留）"
    echo "warning: statusLine 自动接线失败: $STATUSLINE_CONFIG_REASON" >&2
  fi
else
  STATUSLINE_CONFIG_REASON="Codex 宿主不使用 Claude Code settings.json"
fi

echo "Sulde KB bootstrap complete: $KB_HOME"
echo "  host provider:     $HOST_PROVIDER"
if [ "$STATUSLINE_CONFIGURED" = true ]; then
  echo "  statusLine:        已自动接线"
elif [ "$HOST_PROVIDER" = claude ]; then
  echo "  statusLine:        需手工处理: $STATUSLINE_CONFIG_REASON"
else
  echo "  statusLine:        未接线: $STATUSLINE_CONFIG_REASON"
fi
echo "  kb-index:          $LAUNCHER_HOME/bin/kb-index"
echo "  KB MCP:            $LAUNCHER_HOME/bin/sulde-kb-mcp"
echo "  mem-sync:          $LAUNCHER_HOME/bin/mem-sync"
echo "  model dispatch:     $LAUNCHER_HOME/bin/model-dispatch"
echo "  intent guardian:   $LAUNCHER_HOME/bin/intent-guardian"
echo "  全局纪律接线:      $VENV_PYTHON $SCRIPT_DIR/configure-global.py --install --target $HOST_PROVIDER"
