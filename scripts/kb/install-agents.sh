#!/usr/bin/env bash
# Install the desired Sulde LaunchAgent set from one immutable runtime generation.

set -eu

PLATFORM_NAME=${SULDE_PLATFORM_NAME:-$(uname -s)}
if [ "$PLATFORM_NAME" != "Darwin" ]; then
  echo "Sulde LaunchAgents are macOS-only; nothing to do."
  exit 0
fi

DRY_RUN=false
UNINSTALL=false
ACCEPT_LLM_DATA_EGRESS=false
PROVIDER=${SULDE_HOST_PROVIDER:-${SULDE_LLM_PROVIDER:-auto}}
RUNTIME_ROOT=${SULDE_PLUGIN_ROOT:-}
PARENT_DEPLOYMENT_LOCK_TOKEN=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --help|-h)
      if [ "$#" -eq 1 ]; then
        echo "usage: install-agents.sh [--dry-run] [--uninstall] [--provider claude|codex|auto] [--runtime-root PATH]"
        exit 0
      fi
      exit 2 ;;
    --dry-run) DRY_RUN=true ;;
    --uninstall) UNINSTALL=true ;;
    --accept-llm-data-egress) ACCEPT_LLM_DATA_EGRESS=true ;;
    --provider)
      [ -n "${2:-}" ] || { echo "install-agents failed: --provider needs a value" >&2; exit 2; }
      PROVIDER=$2
      shift
      ;;
    --provider=*) PROVIDER=${1#*=} ;;
    --runtime-root)
      [ -n "${2:-}" ] || { echo "install-agents failed: --runtime-root needs a value" >&2; exit 2; }
      RUNTIME_ROOT=$2
      shift
      ;;
    --runtime-root=*) RUNTIME_ROOT=${1#*=} ;;
    --parent-deployment-lock-token)
      [ -n "${2:-}" ] || { echo "install-agents failed: --parent-deployment-lock-token needs a value" >&2; exit 2; }
      PARENT_DEPLOYMENT_LOCK_TOKEN=$2
      shift
      ;;
    --parent-deployment-lock-token=*) PARENT_DEPLOYMENT_LOCK_TOKEN=${1#*=} ;;
    *)
      echo "usage: install-agents.sh [--dry-run] [--uninstall] [--provider claude|codex|auto] [--runtime-root PATH] [--accept-llm-data-egress] [--parent-deployment-lock-token TOKEN]" >&2
      exit 2
      ;;
  esac
  shift
done

resolve_executable() {
  runtime=$1
  if [ "$runtime" = claude ]; then
    override=${SULDE_CLAUDE_EXE:-}
  else
    override=${SULDE_CODEX_EXE:-}
  fi
  if [ -n "$override" ] && [ -x "$override" ]; then
    printf '%s\n' "$override"
  elif [ -n "$override" ] && command -v "$override" >/dev/null 2>&1; then
    command -v "$override"
  else
    command -v "$runtime" 2>/dev/null || return 1
  fi
}

case "$PROVIDER" in
  claude|codex) ;;
  auto)
    if [ -n "${CODEX_THREAD_ID:-}${CODEX_CI:-}" ] && [ -z "${CLAUDECODE:-}${CLAUDE_CODE_ENTRYPOINT:-}${CLAUDE_SESSION_ID:-}" ]; then
      PROVIDER=codex
    elif [ -n "${CLAUDECODE:-}${CLAUDE_CODE_ENTRYPOINT:-}${CLAUDE_SESSION_ID:-}" ] && [ -z "${CODEX_THREAD_ID:-}${CODEX_CI:-}" ]; then
      PROVIDER=claude
    else
      claude_exe=$(resolve_executable claude || true)
      codex_exe=$(resolve_executable codex || true)
      if [ -n "$claude_exe" ] && [ -z "$codex_exe" ]; then
        PROVIDER=claude
      elif [ -n "$codex_exe" ] && [ -z "$claude_exe" ]; then
        PROVIDER=codex
      else
        echo "install-agents failed: auto provider is ambiguous; pass --provider claude or --provider codex" >&2
        exit 2
      fi
    fi
    ;;
  *)
    echo "install-agents failed: provider must be claude, codex, or auto" >&2
    exit 2
    ;;
esac

PROVIDER_EXE=$(resolve_executable "$PROVIDER" || true)
if [ -z "$PROVIDER_EXE" ]; then
  echo "install-agents failed: selected provider '$PROVIDER' is unavailable; no cross-provider fallback" >&2
  exit 2
fi
if [ "$DRY_RUN" = false ] && [ "$UNINSTALL" = false ] && [ "$ACCEPT_LLM_DATA_EGRESS" = false ]; then
  echo "install-agents failed: scheduled cognition can send redacted local context to $PROVIDER; review the dry-run, then pass --accept-llm-data-egress" >&2
  exit 2
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -z "$RUNTIME_ROOT" ]; then
  RUNTIME_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
else
  if [ -L "$RUNTIME_ROOT" ]; then
    echo "install-agents failed: runtime root must not be a symbolic link: $RUNTIME_ROOT" >&2
    exit 2
  fi
  RUNTIME_ROOT=$(CDPATH= cd -- "$RUNTIME_ROOT" && pwd)
fi
TEMPLATE_DIR="$RUNTIME_ROOT/templates/launchagents"
SULDE_ROOT=${SULDE_HOME:-"$HOME/.sulde"}
KB_HOME=${SULDE_KB_HOME:-"$SULDE_ROOT/data/kb"}
if [ -n "${SULDE_LAUNCHER_HOME:-}" ]; then
  LAUNCHER_HOME=$SULDE_LAUNCHER_HOME
elif [ "$KB_HOME" = "$SULDE_ROOT/data/kb" ]; then
  LAUNCHER_HOME=$SULDE_ROOT
else
  # Explicit legacy/custom KB homes remain self-contained.
  LAUNCHER_HOME=$KB_HOME
fi
LAUNCHER_AUTHORITY="$LAUNCHER_HOME/bin/.sulde-launchers.json"
DEST_DIR=${SULDE_LAUNCHAGENTS_DIR:-"$HOME/Library/LaunchAgents"}
LAUNCHCTL=${SULDE_LAUNCHCTL:-launchctl}
SCHEDULER_PYTHON=${SULDE_SCHEDULER_PYTHON:-/usr/bin/python3}
if [ -n "${SULDE_DEPLOYMENT_LOCK_DIR:-}" ]; then
  LOCK_DIR=$SULDE_DEPLOYMENT_LOCK_DIR
elif [ -n "${SULDE_HOME:-}" ] || [ -z "${SULDE_KB_HOME:-}" ]; then
  LOCK_DIR="$SULDE_ROOT/control/deployment.lock"
else
  # An explicit legacy/custom KB home remains a self-contained deployment
  # boundary.  This preserves the old lock authority while the default layout
  # moves control state to the provider-neutral Sulde home.
  LOCK_DIR="$KB_HOME/.deployment.lock"
fi
STAGING_DIR=$(mktemp -d "${TMPDIR:-/tmp}/sulde-launchagents.XXXXXX")
LOCK_HELD=false
LOCK_TOKEN=""
TRANSACTION_STARTED=false
TRANSACTION_COMMITTED=false
PRESTATE_DIR="$STAGING_DIR/prestate"

cleanup() {
  exit_status=${1:-1}
  trap - EXIT HUP INT TERM
  if [ "$TRANSACTION_STARTED" = true ] && [ "$TRANSACTION_COMMITTED" = false ]; then
    "$SCHEDULER_PYTHON" - "$PRESTATE_DIR" "$KB_HOME" "$LAUNCHER_HOME" "$DEST_DIR" <<'PY' || exit_status=1
import json
from pathlib import Path
import shutil
import sys

snapshot = Path(sys.argv[1])
kb_home = Path(sys.argv[2])
launcher_home = Path(sys.argv[3])
destination = Path(sys.argv[4])
manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
for name, target in {
    "owner": kb_home / "runtime-owner.json",
    "runner": kb_home / "bin/sulde-scheduled-run",
    "deployment": kb_home / "deployment-generation.json",
    "launcher": launcher_home / "bin/.sulde-launchers.json",
}.items():
    saved = snapshot / f"{name}.snapshot"
    if target.exists() or target.is_symlink():
        target.unlink()
    if manifest["files"][name]:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(saved, target)
for path in destination.glob("com.sulde.*.plist"):
    path.unlink()
for saved in (snapshot / "plists").glob("*.plist"):
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(saved, destination / saved.name)
retired = destination / ".sulde-retired"
if retired.exists():
    shutil.rmtree(retired)
if manifest["retired_tree"]:
    shutil.copytree(snapshot / "retired-tree", retired)
PY
    while IFS= read -r label; do
      [ -n "$label" ] || continue
      "$LAUNCHCTL" remove "$label" >/dev/null 2>&1 || true
    done < "$MANAGED_LABELS"
    while IFS= read -r label; do
      [ -n "$label" ] || continue
      restored_plist="$DEST_DIR/$label.plist"
      if [ -f "$restored_plist" ]; then
        "$LAUNCHCTL" load "$restored_plist" >/dev/null 2>&1 || exit_status=1
      fi
    done < "$PRESTATE_DIR/loaded-labels.txt"
  fi
  if [ "$LOCK_HELD" = true ]; then
    rm -f "$LOCK_DIR/owner.json"
    rmdir "$LOCK_DIR" >/dev/null 2>&1 || true
  fi
  rm -rf "$STAGING_DIR"
  exit "$exit_status"
}
trap 'cleanup $?' EXIT
trap 'exit 130' HUP INT TERM

if [ ! -x "$SCHEDULER_PYTHON" ]; then
  echo "install-agents failed: scheduler Python is not executable: $SCHEDULER_PYTHON" >&2
  exit 2
fi
if ! command -v "$LAUNCHCTL" >/dev/null 2>&1 && [ ! -x "$LAUNCHCTL" ]; then
  echo "install-agents failed: launchctl is unavailable: $LAUNCHCTL" >&2
  exit 2
fi

mkdir -p "$SULDE_ROOT/bin" "$SULDE_ROOT/control" "$SULDE_ROOT/state" \
  "$SULDE_ROOT/data" "$SULDE_ROOT/cache" "$SULDE_ROOT/logs" \
  "$SULDE_ROOT/venv" "$SULDE_ROOT/artifacts" "$KB_HOME"
if [ "$DRY_RUN" = false ]; then
  if [ -n "$PARENT_DEPLOYMENT_LOCK_TOKEN" ]; then
    "$SCHEDULER_PYTHON" - "$LOCK_DIR" "$PARENT_DEPLOYMENT_LOCK_TOKEN" "$PPID" <<'PY'
import json
from pathlib import Path
import sys

lock = Path(sys.argv[1])
expected_token = sys.argv[2]
expected_pid = int(sys.argv[3])
try:
    owner = json.loads((lock / "owner.json").read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError) as error:
    raise SystemExit(f"install-agents failed: parent deployment lock is unavailable: {error}")
if (
    owner.get("schema_version") != 1
    or owner.get("operation") != "codex-plugin-install"
    or owner.get("token") != expected_token
    or owner.get("pid") != expected_pid
):
    raise SystemExit("install-agents failed: parent deployment lock authority differs")
PY
  else
  LOCK_TOKEN=$("$SCHEDULER_PYTHON" - "$LOCK_DIR" "$$" <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import uuid

lock = Path(sys.argv[1])
pid = int(sys.argv[2])

def alive(candidate: object) -> bool:
    if not isinstance(candidate, int) or candidate <= 0:
        return False
    try:
        os.kill(candidate, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True

for attempt in range(2):
    try:
        lock.mkdir(mode=0o700)
        break
    except FileExistsError:
        try:
            owner = json.loads((lock / "owner.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            owner = None
        if owner is not None and alive(owner.get("pid")):
            raise SystemExit(
                f"install-agents failed: another plugin or scheduler deployment owns {lock}"
            )
        if owner is None:
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                age = 0
            if age < 300:
                raise SystemExit(
                    f"install-agents failed: another plugin or scheduler deployment owns {lock}"
                )
        try:
            marker = lock / "owner.json"
            if marker.exists() or marker.is_symlink():
                marker.unlink()
            lock.rmdir()
        except OSError as error:
            raise SystemExit(f"install-agents failed: cannot reclaim stale deployment lock: {error}")
else:
    raise SystemExit(f"install-agents failed: cannot acquire deployment lock: {lock}")

token = uuid.uuid4().hex
marker = lock / "owner.json"
marker.write_text(json.dumps({
    "schema_version": 1,
    "pid": pid,
    "token": token,
    "operation": "launchagent-reconcile",
}, sort_keys=True) + "\n", encoding="utf-8")
os.chmod(marker, 0o600)
print(token)
PY
) || exit $?
  LOCK_HELD=true
  fi
fi

RUNTIME_META="$STAGING_DIR/runtime-meta.json"
"$SCHEDULER_PYTHON" - "$RUNTIME_ROOT" "$TEMPLATE_DIR" "$DRY_RUN" "$UNINSTALL" "$RUNTIME_META" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

runtime = Path(sys.argv[1]).expanduser().resolve()
templates = Path(sys.argv[2]).expanduser().resolve()
dry_run = sys.argv[3] == "true"
uninstall = sys.argv[4] == "true"
output = Path(sys.argv[5])

if not runtime.is_dir() or not templates.is_dir():
    raise SystemExit(f"install-agents failed: incomplete runtime root: {runtime}")
if not (runtime / "scripts/kb/install-agents.sh").is_file():
    raise SystemExit(f"install-agents failed: runtime has no scheduler installer: {runtime}")
if any(path.is_symlink() for path in runtime.rglob("*")):
    raise SystemExit(f"install-agents failed: runtime tree contains symlinks: {runtime}")
if any(path.name == ".git" for path in runtime.rglob(".git")) and not (dry_run or uninstall):
    raise SystemExit(
        "install-agents failed: mutable repository roots cannot own background actors; "
        "run the installer from a versioned artifact/runtime"
    )

descriptor_path = runtime / ".claude-plugin/plugin.json"
if not descriptor_path.is_file():
    descriptor_path = runtime.parent / ".codex-plugin/plugin.json"
if not descriptor_path.is_file():
    if not dry_run:
        raise SystemExit(
            "install-agents failed: scheduler runtime must be a versioned installed artifact; "
            "mutable repository roots are not accepted"
        )
    descriptor = {"name": "sulde", "version": "dry-run-source"}
else:
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
if descriptor.get("name") not in {"sulde", "sulde-cc"}:
    raise SystemExit(f"install-agents failed: foreign runtime descriptor: {descriptor_path}")
version = descriptor.get("version")
if not isinstance(version, str) or not version:
    raise SystemExit(f"install-agents failed: runtime version is missing: {descriptor_path}")

digest = hashlib.sha256()
for path in sorted(runtime.rglob("*")):
    relative_parts = path.relative_to(runtime).parts
    if "__pycache__" in relative_parts or path.suffix.casefold() == ".pyc":
        raise SystemExit(
            f"install-agents failed: runtime contains executable Python bytecode: {path}"
        )
    if not path.is_file():
        continue
    relative = path.relative_to(runtime).as_posix().encode("utf-8")
    digest.update(len(relative).to_bytes(8, "big"))
    digest.update(relative)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
tree_sha256 = digest.hexdigest()
generation = f"{version}:{tree_sha256}"

labels = []
for template in sorted(templates.glob("*.plist")):
    import plistlib
    with template.open("rb") as handle:
        payload = plistlib.load(handle)
    label = payload.get("Label")
    if not isinstance(label, str) or not label.startswith("com.sulde."):
        raise SystemExit(f"install-agents failed: invalid managed label in {template}")
    if template.name != f"{label}.plist":
        raise SystemExit(f"install-agents failed: plist filename/label mismatch: {template}")
    labels.append(label)
if not labels or len(labels) != len(set(labels)):
    raise SystemExit("install-agents failed: managed LaunchAgent labels are empty or duplicated")

output.write_text(json.dumps({
    "runtime_root": str(runtime),
    "runtime_version": version,
    "runtime_tree_sha256": tree_sha256,
    "generation": generation,
    "managed_labels": labels,
}, sort_keys=True), encoding="utf-8")
PY

RUNTIME_ROOT=$("$SCHEDULER_PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["runtime_root"])' "$RUNTIME_META")
GENERATION=$("$SCHEDULER_PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["generation"])' "$RUNTIME_META")
RUNTIME_TREE_SHA256=$("$SCHEDULER_PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["runtime_tree_sha256"])' "$RUNTIME_META")
RUNTIME_VERSION=$("$SCHEDULER_PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["runtime_version"])' "$RUNTIME_META")
SCHEDULER_ACTIVATION_ID=$("$SCHEDULER_PYTHON" -c 'import uuid; print(uuid.uuid4().hex)')
MANAGED_LABELS="$STAGING_DIR/managed-labels.txt"
"$SCHEDULER_PYTHON" -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1], encoding="utf-8"))["managed_labels"]))' "$RUNTIME_META" > "$MANAGED_LABELS"

if [ "$DRY_RUN" = false ] && [ "$UNINSTALL" = false ]; then
  DESIRED_GENERATION="$KB_HOME/deployment-generation.json"
  if [ ! -f "$DESIRED_GENERATION" ] || [ ! -f "$LAUNCHER_AUTHORITY" ]; then
    echo "install-agents failed: provider-neutral deployment and launcher authority are required before scheduler mutation" >&2
    exit 2
  fi
  if [ -f "$DESIRED_GENERATION" ]; then
    "$SCHEDULER_PYTHON" - "$DESIRED_GENERATION" "$LAUNCHER_AUTHORITY" "$RUNTIME_ROOT" "$RUNTIME_TREE_SHA256" "$GENERATION" <<'PY'
import json
import sys
from pathlib import Path

descriptor = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
launcher = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
expected = {
    "runtime_root": str(Path(sys.argv[3]).resolve()),
    "runtime_tree_sha256": sys.argv[4],
    "generation": sys.argv[5],
}
for key, value in expected.items():
    if descriptor.get(key) != value:
        raise SystemExit(
            f"install-agents failed: deployment generation mismatch for {key}: "
            f"{descriptor.get(key)!r} != {value!r}"
        )
launcher_expected = {
    "source_root": expected["runtime_root"],
    "runtime_tree_sha256": expected["runtime_tree_sha256"],
    "generation": expected["generation"],
}
for key, value in launcher_expected.items():
    if launcher.get(key) != value:
        raise SystemExit(
            f"install-agents failed: stable launcher generation mismatch for {key}: "
            f"{launcher.get(key)!r} != {value!r}"
        )
PY
  fi
fi

if [ "$DRY_RUN" = false ] && [ "$UNINSTALL" = false ]; then
  "$SCHEDULER_PYTHON" - "$RUNTIME_ROOT" "$KB_HOME" <<'PY'
from pathlib import Path
import sys

runtime = Path(sys.argv[1]).expanduser().resolve()
kb_home = Path(sys.argv[2]).expanduser()
sys.path.insert(0, str(runtime / "scripts" / "kb"))
from production_recovery_readiness import provision_recovery_key

provision_recovery_key(kb_home)
PY
fi

WRAPPER="$STAGING_DIR/sulde-scheduled-run"
"$SCHEDULER_PYTHON" - "$WRAPPER" <<'PY'
from pathlib import Path
import sys

target = Path(sys.argv[1])
source = '''#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

parser = argparse.ArgumentParser()
parser.add_argument("--owner", type=Path, required=True)
parser.add_argument("--descriptor", type=Path, required=True)
parser.add_argument("--launcher-manifest", type=Path, required=True)
parser.add_argument("--generation", required=True)
parser.add_argument("--activation-id", required=True)
parser.add_argument("--activation-wait-seconds", type=float, default=30.0)
parser.add_argument("--runner-sha256", required=True)
parser.add_argument("--runtime-root", type=Path, required=True)
parser.add_argument("--python", required=True)
parser.add_argument("--target", required=True)
parser.add_argument("arguments", nargs=argparse.REMAINDER)
args = parser.parse_args()
if not 0.0 < args.activation_wait_seconds <= 30.0:
    raise SystemExit("Sulde scheduler fence: invalid activation wait bound")
runtime_argument = args.runtime_root.expanduser()
if runtime_argument.is_symlink():
    raise SystemExit("Sulde scheduler fence: runtime root is a symbolic link")
runtime = runtime_argument.resolve()
runner_path = Path(__file__)
if runner_path.is_symlink():
    raise SystemExit("Sulde scheduler fence: stable runner is a symbolic link")
actual_runner_sha256 = hashlib.sha256(runner_path.read_bytes()).hexdigest()

def read_authorities():
    try:
        if (
            args.owner.is_symlink()
            or args.descriptor.is_symlink()
            or args.launcher_manifest.is_symlink()
        ):
            raise OSError("generation authority path is a symbolic link")
        return (
            json.loads(args.owner.read_text(encoding="utf-8")),
            json.loads(args.descriptor.read_text(encoding="utf-8")),
            json.loads(args.launcher_manifest.read_text(encoding="utf-8")),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"Sulde scheduler fence: owner unavailable: {error}")

def identity_matches(owner, descriptor, launcher):
    expected_tree_sha256 = owner.get("runtime_tree_sha256")
    return (
        owner.get("generation") == args.generation
        and owner.get("scheduler_activation_id") == args.activation_id
        and owner.get("scheduler_runner_sha256") == args.runner_sha256
        and Path(str(owner.get("runtime_root", ""))).expanduser().resolve() == runtime
        and descriptor.get("generation") == args.generation
        and descriptor.get("scheduler_activation_id") == args.activation_id
        and descriptor.get("runtime_root") == str(runtime)
        and descriptor.get("runtime_tree_sha256") == expected_tree_sha256
        and descriptor.get("scheduler_runner_sha256") == args.runner_sha256
        and launcher.get("generation") == args.generation
        and launcher.get("scheduler_activation_id") == args.activation_id
        and launcher.get("source_root") == str(runtime)
        and launcher.get("runtime_tree_sha256") == expected_tree_sha256
        and launcher.get("scheduler_runner_sha256") == args.runner_sha256
    )

def is_active(owner, descriptor):
    return (
        owner.get("status") == "active"
        and owner.get("installation_status") == "generation_verified"
        and owner.get("operational_ready") is True
        and descriptor.get("status") == "generation_verified"
        and descriptor.get("operational_ready") is True
    )

def is_activation_transition(owner, descriptor):
    return (
        owner.get("status") == "activating"
        and owner.get("installation_status") == "installed_degraded"
        and owner.get("operational_ready") is False
        and (
            (
                descriptor.get("status") == "installed_live_unverified"
                and descriptor.get("operational_ready") is False
            )
            or (
                descriptor.get("status") == "generation_verified"
                and descriptor.get("operational_ready") is True
            )
        )
    )

# The activation ID distinguishes a retry of the same immutable generation from
# the transaction that launched this process. A restored prestate must not wake it.
activation_deadline = time.monotonic() + args.activation_wait_seconds
while True:
    owner, descriptor, launcher = read_authorities()
    if not identity_matches(owner, descriptor, launcher):
        raise SystemExit("Sulde scheduler fence: stale or inactive runtime generation")
    if is_active(owner, descriptor):
        break
    if not is_activation_transition(owner, descriptor):
        raise SystemExit("Sulde scheduler fence: stale or inactive runtime generation")
    if time.monotonic() >= activation_deadline:
        raise SystemExit("Sulde scheduler fence: activation transaction did not commit")
    time.sleep(0.05)

if any(path.name == ".git" for path in runtime.rglob(".git")):
    raise SystemExit("Sulde scheduler fence: mutable repository runtime is forbidden")
tree_digest = hashlib.sha256()
for path in sorted(runtime.rglob("*")):
    if path.is_symlink():
        raise SystemExit(f"Sulde scheduler fence: runtime tree contains a symbolic link: {path}")
    relative_parts = path.relative_to(runtime).parts
    if ".git" in relative_parts:
        raise SystemExit(f"Sulde scheduler fence: runtime contains repository metadata: {path}")
    if "__pycache__" in relative_parts or path.suffix.casefold() == ".pyc":
        raise SystemExit(f"Sulde scheduler fence: runtime contains executable Python bytecode: {path}")
    if not path.is_file():
        continue
    relative = path.relative_to(runtime).as_posix().encode("utf-8")
    tree_digest.update(len(relative).to_bytes(8, "big"))
    tree_digest.update(relative)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            tree_digest.update(chunk)
actual_tree_sha256 = tree_digest.hexdigest()
owner, descriptor, launcher = read_authorities()
if (
    not identity_matches(owner, descriptor, launcher)
    or not is_active(owner, descriptor)
    or owner.get("runtime_tree_sha256") != actual_tree_sha256
    or descriptor.get("runtime_root") != str(runtime)
    or descriptor.get("runtime_tree_sha256") != actual_tree_sha256
    or descriptor.get("generation") != args.generation
    or descriptor.get("scheduler_runner_sha256") != args.runner_sha256
    or launcher.get("source_root") != str(runtime)
    or launcher.get("runtime_tree_sha256") != actual_tree_sha256
    or launcher.get("generation") != args.generation
    or launcher.get("scheduler_runner_sha256") != args.runner_sha256
    or actual_runner_sha256 != args.runner_sha256
):
    raise SystemExit("Sulde scheduler fence: immutable runtime tree digest drifted")
target = (runtime / args.target).resolve()
try:
    target.relative_to(runtime)
except ValueError:
    raise SystemExit("Sulde scheduler fence: target escapes runtime root")
if not target.is_file() or target.is_symlink():
    raise SystemExit(f"Sulde scheduler fence: target unavailable: {target}")
tail = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
allowed_environment = {
    "HOME",
    "LANG",
    "LC_ALL",
    "LOGNAME",
    "PATH",
    "SULDE_AGENT_PROVIDER",
    "SULDE_CLAUDE_EXE",
    "SULDE_CODEX_EXE",
    "SULDE_HOST_PROVIDER",
    "SULDE_HOME",
    "SULDE_KB_HOME",
    "SULDE_LLM_PROVIDER",
    "SULDE_RUNTIME_GENERATION",
    "SULDE_RUNTIME_ROOT",
    "SULDE_SCHEDULER_OWNER",
    "SULDE_SELF_REPAIR_AUTO",
    "TMPDIR",
    "TZ",
    "USER",
}
child_environment = {
    key: value for key, value in os.environ.items() if key in allowed_environment
}
child_environment.update({
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUTF8": "1",
})
os.execve(args.python, [args.python, str(target), *tail], child_environment)
'''
target.write_text(source, encoding="utf-8")
target.chmod(0o755)
PY

RUNNER_SHA256=$(
  "$SCHEDULER_PYTHON" -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$WRAPPER"
)

echo "调度宿主: $PROVIDER ($PROVIDER_EXE)"
echo "不可变运行代际: $GENERATION"
"$SCHEDULER_PYTHON" - "$TEMPLATE_DIR" "$STAGING_DIR" "$RUNTIME_ROOT" "$KB_HOME" "$LAUNCHER_HOME" "$HOME" "$PROVIDER" "$PROVIDER_EXE" "$GENERATION" "$SCHEDULER_PYTHON" "$RUNNER_SHA256" "$SCHEDULER_ACTIVATION_ID" <<'PY'
from __future__ import annotations

import plistlib
import sys
from pathlib import Path

template_dir = Path(sys.argv[1])
staging_dir = Path(sys.argv[2])
runtime_root = Path(sys.argv[3]).resolve()
kb_home = Path(sys.argv[4]).resolve()
launcher_home = Path(sys.argv[5]).resolve()
user_home = Path(sys.argv[6]).resolve()
provider = sys.argv[7]
provider_executable = sys.argv[8]
generation = sys.argv[9]
python = sys.argv[10]
runner_sha256 = sys.argv[11]
activation_id = sys.argv[12]
wrapper = kb_home / "bin/sulde-scheduled-run"
owner = kb_home / "runtime-owner.json"
descriptor = kb_home / "deployment-generation.json"
launcher_manifest = launcher_home / "bin/.sulde-launchers.json"

targets = {
    "com.sulde.auto-sediment": "scripts/kb/auto-sediment.py",
    "com.sulde.codex-harvest": "scripts/kb/codex-harvest.py",
    "com.sulde.daily-distill": "scripts/kb/auto-distill.py",
    "com.sulde.golden-expand": "scripts/kb/golden-expand.py",
    "com.sulde.governance-weekly": "scripts/kb/governance-report.py",
    "com.sulde.graph-audit": "scripts/kb/graph-audit.py",
    "com.sulde.heartbeat": "scripts/kb/heartbeat.py",
    "com.sulde.kb-aging": "scripts/kb/kb-aging.py",
    "com.sulde.kb-dedup": "scripts/kb/kb-dedup.py",
    "com.sulde.life-cycle": "scripts/kb/life-cycle.py",
    "com.sulde.mem-backup": "scripts/kb/mem-backup.py",
    "com.sulde.memory-embed": "scripts/kb/memory-embed-worker.py",
    "com.sulde.mem-sync-export": "scripts/kb/mem-sync.py",
    "com.sulde.mem-sync-import": "scripts/kb/mem-sync.py",
    "com.sulde.self-repair": "scripts/kb/self-repair.py",
    "com.sulde.status-notify": "scripts/kb/sulde-status.py",
}

def replace_machine_path(value: str) -> str:
    replacements = {
        "__SULDE_SOURCE_ROOT__": str(runtime_root),
        "__SULDE_KB_HOME__": str(kb_home),
        "__SULDE_CODEX_SESSIONS__": str(user_home / ".codex/sessions"),
        "__SULDE_USER_BIN__": str(user_home / ".local/bin"),
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return value

for template in sorted(template_dir.glob("*.plist")):
    with template.open("rb") as handle:
        payload = plistlib.load(handle)
    label = payload["Label"]
    relative_target = targets.get(label)
    if relative_target is None:
        raise SystemExit(f"install-agents failed: no immutable target mapping for {label}")
    target = runtime_root / relative_target
    if not target.is_file() or target.is_symlink():
        raise SystemExit(f"install-agents failed: unsafe scheduled target: {target}")
    original = [replace_machine_path(str(item)) for item in payload["ProgramArguments"]]
    tail = original[2:]
    payload["Program"] = python
    payload["ProgramArguments"] = [
        python,
        str(wrapper),
        "--owner", str(owner),
        "--descriptor", str(descriptor),
        "--launcher-manifest", str(launcher_manifest),
        "--generation", generation,
        "--activation-id", activation_id,
        "--runner-sha256", runner_sha256,
        "--runtime-root", str(runtime_root),
        "--python", python,
        "--target", relative_target,
        "--",
        *tail,
    ]
    environment = payload.get("EnvironmentVariables")
    safe_template_environment = {"PATH", "SULDE_KB_HOME", "SULDE_SELF_REPAIR_AUTO"}
    rendered_environment = {
        key: replace_machine_path(str(value))
        for key, value in (environment.items() if isinstance(environment, dict) else [])
        if key in safe_template_environment
    }
    rendered_environment.update({
        "SULDE_HOST_PROVIDER": provider,
        "SULDE_LLM_PROVIDER": provider,
        "SULDE_AGENT_PROVIDER": provider,
        "SULDE_SCHEDULER_OWNER": provider,
        "SULDE_RUNTIME_ROOT": str(runtime_root),
        "SULDE_RUNTIME_GENERATION": generation,
        "SULDE_CLAUDE_EXE" if provider == "claude" else "SULDE_CODEX_EXE": provider_executable,
    })
    payload["EnvironmentVariables"] = rendered_environment
    for key in ("StandardOutPath", "StandardErrorPath"):
        if key in payload:
            payload[key] = replace_machine_path(str(payload[key]))
    if "WatchPaths" in payload:
        payload["WatchPaths"] = [replace_machine_path(str(item)) for item in payload["WatchPaths"]]
    with (staging_dir / template.name).open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=False)
PY

QUIESCENT_DIR="$STAGING_DIR/quiescent"
mkdir -p "$QUIESCENT_DIR"
"$SCHEDULER_PYTHON" - "$STAGING_DIR" "$QUIESCENT_DIR" <<'PY'
from pathlib import Path
import plistlib
import sys

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
activation_keys = {
    "KeepAlive",
    "LaunchEvents",
    "MachServices",
    "QueueDirectories",
    "RunAtLoad",
    "Sockets",
    "StartCalendarInterval",
    "StartInterval",
    "StartOnMount",
    "WatchPaths",
}
for path in sorted(source.glob("com.sulde.*.plist")):
    with path.open("rb") as handle:
        payload = plistlib.load(handle)
    for key in activation_keys:
        payload.pop(key, None)
    with (destination / path.name).open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=False)
PY

LOADED_LABELS="$STAGING_DIR/loaded-labels.txt"
if ! "$LAUNCHCTL" list > "$STAGING_DIR/launchctl-list.txt" 2> "$STAGING_DIR/launchctl-list.err"; then
  echo "install-agents failed: cannot enumerate loaded LaunchAgents" >&2
  exit 2
fi
"$SCHEDULER_PYTHON" - "$STAGING_DIR/launchctl-list.txt" "$LOADED_LABELS" <<'PY'
from pathlib import Path
import sys

labels = set()
for line in Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace").splitlines():
    fields = line.split()
    if fields and fields[-1].startswith("com.sulde."):
        labels.add(fields[-1])
Path(sys.argv[2]).write_text("\n".join(sorted(labels)) + ("\n" if labels else ""), encoding="utf-8")
PY

RETIRED_LABELS="$STAGING_DIR/retired-labels.txt"
"$SCHEDULER_PYTHON" - "$DEST_DIR" "$MANAGED_LABELS" "$LOADED_LABELS" "$RETIRED_LABELS" <<'PY'
from pathlib import Path
import plistlib
import sys

destination = Path(sys.argv[1])
desired = {line for line in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines() if line}
loaded = {line for line in Path(sys.argv[3]).read_text(encoding="utf-8").splitlines() if line}
installed = set()
if destination.is_dir():
    for path in destination.glob("com.sulde.*.plist"):
        try:
            with path.open("rb") as handle:
                label = plistlib.load(handle).get("Label")
        except Exception:
            label = path.stem
        if isinstance(label, str) and label.startswith("com.sulde."):
            installed.add(label)
known_retired = {
    "com.sulde.codex-cache-repair",
    "com.sulde.kb-weekly-calibrate",
}
outside_desired = (loaded | installed) - desired
unknown = sorted(outside_desired - known_retired)
if unknown:
    raise SystemExit(
        "install-agents failed: unknown Sulde actors block reconciliation: "
        + ", ".join(unknown)
    )
retired = sorted(outside_desired & known_retired)
Path(sys.argv[4]).write_text("\n".join(retired) + ("\n" if retired else ""), encoding="utf-8")
PY

if [ "$DRY_RUN" = true ]; then
  echo "dry-run: generation=$GENERATION runtime=$RUNTIME_ROOT"
  echo "dry-run: launcher authority=$LAUNCHER_AUTHORITY"
  echo "dry-run: managed labels:"
  sed 's/^/  /' "$MANAGED_LABELS"
  if [ -s "$RETIRED_LABELS" ]; then
    echo "dry-run: retired labels to unload/archive:"
    sed 's/^/  /' "$RETIRED_LABELS"
  fi
  for rendered in "$STAGING_DIR"/*.plist; do
    echo "dry-run: $rendered -> $DEST_DIR/$(basename "$rendered")"
  done
  exit 0
fi

if [ "$UNINSTALL" = false ]; then
"$SCHEDULER_PYTHON" - "$PRESTATE_DIR" "$KB_HOME" "$LAUNCHER_HOME" "$DEST_DIR" "$LOADED_LABELS" <<'PY'
import json
from pathlib import Path
import shutil
import sys

snapshot = Path(sys.argv[1])
kb_home = Path(sys.argv[2])
launcher_home = Path(sys.argv[3])
destination = Path(sys.argv[4])
loaded = Path(sys.argv[5])
snapshot.mkdir(parents=True)
files = {
    "owner": kb_home / "runtime-owner.json",
    "runner": kb_home / "bin/sulde-scheduled-run",
    "deployment": kb_home / "deployment-generation.json",
    "launcher": launcher_home / "bin/.sulde-launchers.json",
}
presence = {}
for name, source in files.items():
    if source.is_symlink():
        raise SystemExit(f"install-agents failed: transaction authority is a symlink: {source}")
    presence[name] = source.is_file()
    if presence[name]:
        shutil.copy2(source, snapshot / f"{name}.snapshot")
plists = snapshot / "plists"
plists.mkdir()
for source in destination.glob("com.sulde.*.plist") if destination.is_dir() else ():
    if source.is_symlink() or not source.is_file():
        raise SystemExit(f"install-agents failed: transaction plist is unsafe: {source}")
    shutil.copy2(source, plists / source.name)
retired = destination / ".sulde-retired"
if retired.is_symlink():
    raise SystemExit(f"install-agents failed: retired actor archive is a symlink: {retired}")
retired_present = retired.is_dir() and not retired.is_symlink()
if retired_present:
    shutil.copytree(retired, snapshot / "retired-tree")
shutil.copy2(loaded, snapshot / "loaded-labels.txt")
(snapshot / "manifest.json").write_text(
    json.dumps({"files": presence, "retired_tree": retired_present}, sort_keys=True),
    encoding="utf-8",
)
PY
TRANSACTION_STARTED=true

"$SCHEDULER_PYTHON" - "$DESIRED_GENERATION" "$LAUNCHER_AUTHORITY" "$KB_HOME/bin/sulde-scheduled-run" "$RUNNER_SHA256" "$SCHEDULER_ACTIVATION_ID" <<'PY'
import json
import os
from pathlib import Path
import sys
import tempfile

for raw in sys.argv[1:3]:
    target = Path(raw)
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["scheduler_runner"] = sys.argv[3]
    payload["scheduler_runner_sha256"] = sys.argv[4]
    payload["scheduler_activation_id"] = sys.argv[5]
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
PY
fi

write_owner() {
  owner_status=$1
  "$SCHEDULER_PYTHON" - "$KB_HOME/runtime-owner.json" "$PROVIDER" "$PROVIDER_EXE" "$RUNTIME_ROOT" "$RUNTIME_VERSION" "$RUNTIME_TREE_SHA256" "$GENERATION" "$MANAGED_LABELS" "$RETIRED_LABELS" "$owner_status" "$RUNNER_SHA256" "$SCHEDULER_ACTIVATION_ID" <<'PY'
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

target = Path(sys.argv[1])
read_lines = lambda path: [line for line in Path(path).read_text(encoding="utf-8").splitlines() if line]
payload = {
    "schema_version": 2,
    "status": sys.argv[10],
    "installation_status": (
        "generation_verified" if sys.argv[10] == "active" else "installed_degraded"
    ),
    "operational_ready": sys.argv[10] == "active",
    "provider": sys.argv[2],
    "executable": sys.argv[3],
    "source_root": sys.argv[4],
    "runtime_root": sys.argv[4],
    "runtime_version": sys.argv[5],
    "runtime_tree_sha256": sys.argv[6],
    "generation": sys.argv[7],
    "scheduler_runner_sha256": sys.argv[11],
    "scheduler_activation_id": sys.argv[12],
    "managed_labels": read_lines(sys.argv[8]),
    "retired_labels": read_lines(sys.argv[9]),
    "scheduler": "launchd",
    "installed_at": datetime.now(timezone.utc).isoformat(),
}
target.parent.mkdir(parents=True, exist_ok=True)
descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.replace(temporary, target)
os.chmod(target, 0o600)
PY
}

mark_deployment_live_unverified() {
  "$SCHEDULER_PYTHON" - "$DESIRED_GENERATION" "$PROVIDER" "$RUNTIME_ROOT" "$RUNTIME_TREE_SHA256" "$GENERATION" "$MANAGED_LABELS" <<'PY'
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

target = Path(sys.argv[1])
if target.is_symlink():
    raise SystemExit("install-agents failed: deployment authority is a symbolic link")
payload = json.loads(target.read_text(encoding="utf-8"))
managed_labels = [
    line
    for line in Path(sys.argv[6]).read_text(encoding="utf-8").splitlines()
    if line
]
expected = {
    "schema": "sulde-installed-deployment-generation-v1",
    "schema_version": 1,
    "provider": sys.argv[2],
    "runtime_root": str(Path(sys.argv[3]).resolve()),
    "runtime_tree_sha256": sys.argv[4],
    "generation": sys.argv[5],
    "managed_labels": managed_labels,
}
for key, value in expected.items():
    if payload.get(key) != value:
        raise SystemExit(
            f"install-agents failed: deployment transition mismatch for {key}: "
            f"{payload.get(key)!r} != {value!r}"
        )
allowed_prestates = {
    "installed_degraded": False,
    "installed_live_unverified": False,
    "generation_verified": True,
}
if payload.get("status") not in allowed_prestates:
    raise SystemExit(
        "install-agents failed: deployment transition rejected prestate: "
        f"{payload.get('status')!r}"
    )
expected_ready = allowed_prestates[payload["status"]]
if payload.get("operational_ready") is not expected_ready:
    raise SystemExit(
        "install-agents failed: deployment transition readiness mismatch: "
        f"{payload.get('operational_ready')!r} != {expected_ready!r}"
    )

payload["status"] = "installed_live_unverified"
payload["operational_ready"] = False
descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
except Exception:
    try:
        os.unlink(temporary)
    except OSError:
        pass
    raise
PY
}

mark_deployment_generation_verified() {
  "$SCHEDULER_PYTHON" - "$DESIRED_GENERATION" "$PROVIDER" "$RUNTIME_ROOT" "$RUNTIME_TREE_SHA256" "$GENERATION" "$MANAGED_LABELS" <<'PY'
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

target = Path(sys.argv[1])
payload = json.loads(target.read_text(encoding="utf-8"))
managed_labels = [
    line for line in Path(sys.argv[6]).read_text(encoding="utf-8").splitlines()
    if line
]
expected = {
    "provider": sys.argv[2],
    "runtime_root": str(Path(sys.argv[3]).resolve()),
    "runtime_tree_sha256": sys.argv[4],
    "generation": sys.argv[5],
    "managed_labels": managed_labels,
    "status": "installed_live_unverified",
    "operational_ready": False,
}
for key, value in expected.items():
    if payload.get(key) != value:
        raise SystemExit(
            f"install-agents failed: final deployment transition mismatch for {key}: "
            f"{payload.get(key)!r} != {value!r}"
        )
payload["status"] = "generation_verified"
payload["operational_ready"] = True
descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
except Exception:
    try:
        os.unlink(temporary)
    except OSError:
        pass
    raise
PY
}

mkdir -p "$DEST_DIR" "$KB_HOME/bin"
if [ "$UNINSTALL" = true ]; then
  rm -f "$KB_HOME/runtime-owner.json"
else
  write_owner reconciling
fi
ARCHIVE_DIR="$DEST_DIR/.sulde-retired/archive"
retired_count=0
while IFS= read -r label; do
  [ -n "$label" ] || continue
  retired_count=$((retired_count + 1))
  plist="$DEST_DIR/$label.plist"
  if [ -f "$plist" ]; then
    "$LAUNCHCTL" unload "$plist" >/dev/null 2>&1 || true
  fi
  "$LAUNCHCTL" remove "$label" >/dev/null 2>&1 || true
  if [ -f "$plist" ]; then
    mkdir -p "$ARCHIVE_DIR"
    archive="$ARCHIVE_DIR/$(basename "$plist")"
    if [ -f "$archive" ]; then
      cmp -s "$plist" "$archive" || { echo "install-agents failed: retired actor archive conflicts: $archive" >&2; exit 2; }
      rm -f "$plist"
    else
      mv "$plist" "$archive"
    fi
  fi
  echo "已退役: $label"
done < "$RETIRED_LABELS"

"$SCHEDULER_PYTHON" - "$DEST_DIR/.sulde-retired/tombstones" "$RETIRED_LABELS" <<'PY'
import json
import os
from pathlib import Path
import sys
import tempfile

root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
for label in (line for line in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines() if line):
    target = root / f"{label}.json"
    payload = {
        "schema": "sulde-retired-scheduler-actor-v1",
        "schema_version": 1,
        "label": label,
        "status": "retired",
        "replacement": "immutable-generation-owner",
    }
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if target.is_file():
        if target.is_symlink() or target.read_bytes() != encoded:
            raise SystemExit(f"install-agents failed: retired actor tombstone conflict: {target}")
        continue
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=root)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
PY

if [ "$UNINSTALL" = true ]; then
  while IFS= read -r label; do
    [ -n "$label" ] || continue
    plist="$DEST_DIR/$label.plist"
    "$LAUNCHCTL" unload "$plist" >/dev/null 2>&1 || true
    "$LAUNCHCTL" remove "$label" >/dev/null 2>&1 || true
    if [ -f "$plist" ]; then
      mkdir -p "$ARCHIVE_DIR"
      mv "$plist" "$ARCHIVE_DIR/$(basename "$plist")"
    fi
  done < "$MANAGED_LABELS"
  rm -f "$KB_HOME/bin/sulde-scheduled-run"
  TRANSACTION_COMMITTED=true
  echo "Sulde LaunchAgents 已卸载并归档。"
  exit 0
fi

install -m 755 "$WRAPPER" "$KB_HOME/bin/sulde-scheduled-run"
for rendered in "$STAGING_DIR"/*.plist; do
  destination="$DEST_DIR/$(basename "$rendered")"
  install -m 644 "$rendered" "$destination"
done

write_owner activating
load_failed=false
for rendered in "$QUIESCENT_DIR"/*.plist; do
  destination="$DEST_DIR/$(basename "$rendered")"
  "$LAUNCHCTL" unload "$destination" >/dev/null 2>&1 || true
  if "$LAUNCHCTL" load "$rendered"; then
    echo "已静默装载待验收定义: $destination"
  else
    echo "install-agents failed: could not load quiescent definition $rendered" >&2
    load_failed=true
  fi
done
if [ "$load_failed" = true ]; then
  write_owner degraded
  exit 1
fi
if ! "$LAUNCHCTL" list > "$STAGING_DIR/launchctl-post-list.txt" 2> "$STAGING_DIR/launchctl-post-list.err"; then
  write_owner degraded
  echo "install-agents failed: cannot verify loaded generation after reconciliation" >&2
  exit 1
fi
if ! "$SCHEDULER_PYTHON" - "$STAGING_DIR/launchctl-post-list.txt" "$MANAGED_LABELS" <<'PY'
from pathlib import Path
import sys

loaded = {
    fields[-1]
    for line in Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace").splitlines()
    if (fields := line.split()) and fields[-1].startswith("com.sulde.")
}
desired = {line for line in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines() if line}
if loaded != desired:
    raise SystemExit(
        "loaded actor inventory mismatch: missing="
        + ",".join(sorted(desired - loaded))
        + " unknown="
        + ",".join(sorted(loaded - desired))
    )
PY
then
  write_owner degraded
  echo "install-agents failed: loaded actor inventory does not match owner generation" >&2
  exit 1
fi
mark_deployment_live_unverified
write_owner activating
activation_failed=false
for rendered in "$STAGING_DIR"/*.plist; do
  destination="$DEST_DIR/$(basename "$rendered")"
  quiescent="$QUIESCENT_DIR/$(basename "$rendered")"
  "$LAUNCHCTL" unload "$quiescent" >/dev/null 2>&1 || true
  if "$LAUNCHCTL" load "$destination"; then
    echo "已激活正式调度定义: $destination"
  else
    echo "install-agents failed: could not activate $destination" >&2
    activation_failed=true
  fi
done
if [ "$activation_failed" = true ]; then
  write_owner degraded
  exit 1
fi
if ! "$LAUNCHCTL" list > "$STAGING_DIR/launchctl-active-list.txt" 2> "$STAGING_DIR/launchctl-active-list.err"; then
  write_owner degraded
  echo "install-agents failed: cannot verify active scheduler generation" >&2
  exit 1
fi
if ! "$SCHEDULER_PYTHON" - "$STAGING_DIR/launchctl-active-list.txt" "$MANAGED_LABELS" <<'PY'
from pathlib import Path
import sys

loaded = {
    fields[-1]
    for line in Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace").splitlines()
    if (fields := line.split()) and fields[-1].startswith("com.sulde.")
}
desired = {line for line in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines() if line}
if loaded != desired:
    raise SystemExit(
        "active actor inventory mismatch: missing="
        + ",".join(sorted(desired - loaded))
        + " unknown="
        + ",".join(sorted(loaded - desired))
    )
PY
then
  write_owner degraded
  echo "install-agents failed: active actor inventory does not match owner generation" >&2
  exit 1
fi
mark_deployment_generation_verified
write_owner active
TRANSACTION_COMMITTED=true
echo "调度所有权已记录: $KB_HOME/runtime-owner.json generation=$GENERATION retired=$retired_count"
