#!/usr/bin/env python3
"""Synchronize allow-listed memory.db project partitions through a private git repo."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
import re
import runpy
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
_paths = SimpleNamespace(**runpy.run_path(str(Path(__file__).with_name("sulde_paths.py"))))
canonical_kb_home = _paths.kb_home
sync_repository_path = _paths.sync_repository_path
SuldePathError = _paths.SuldePathError
_HOOK_LIB = REPO_ROOT / "hooks" / "lib"
kb_cli = SimpleNamespace(**runpy.run_path(str(_HOOK_LIB / "kb_cli.py")))
CONFIG_NAME = "mem-sync.json"
STATE_NAME = "mem-sync-state.json"
PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
GIT_OID_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
KEY_FILE_ENV = "SULDE_MEM_SYNC_KEY_FILE"
LEGACY_HOME_ENV = "SULDE_MEM_SYNC_LEGACY_HOME"
MIGRATION_NAME = "mem-sync-legacy-migration.json"
EXPORT_JOURNAL_NAME = "mem-sync-export-transaction.json"
SYNC_LOCK_NAME = "sulde-mem-sync.lock"
SCHEDULED_EXIT_TEMPORARY_FAILURE = 75
SCHEDULED_MAX_ATTEMPTS = 3
SCHEDULED_BACKOFF_SECONDS = 0.1

_file_lock = SimpleNamespace(
    **runpy.run_path(str(Path(__file__).resolve().with_name("file_lock.py")))
)
lock_exclusive_nonblocking = _file_lock.lock_exclusive_nonblocking
unlock = _file_lock.unlock


class SyncError(RuntimeError):
    """Expected operational/configuration error (exit code 2)."""


class GateBlocked(RuntimeError):
    """At least one project contained a secret (exit code 1)."""


class TransientSyncError(SyncError):
    """A retryable lock, network, or remote Git failure."""


def kb_home() -> Path:
    return canonical_kb_home()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, *, required: bool, default: Any) -> Any:
    if not path.is_file():
        if required:
            raise SyncError(f"configuration file does not exist: {path}")
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SyncError(f"cannot read valid JSON from {path}: {error}") from error


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
    except (OSError, UnicodeError) as error:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass
        raise SyncError(f"cannot write {path}: {error}") from error



def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
    except OSError as error:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass
        raise SyncError(f"cannot write {path}: {error}") from error


def legacy_kb_home() -> Path:
    configured = os.environ.get(LEGACY_HOME_ENV)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".claude" / "plugins" / "data" / "sulde-cc" / "kb"


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise SyncError(f"legacy sync repository contains a symlink: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _migration_artifact_sha256(path: Path) -> str:
    if path.is_dir() and not path.is_symlink():
        return _tree_sha256(path)
    if path.is_file() and not path.is_symlink():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    raise SyncError(f"migration artifact is unavailable: {path}")


def _validated_migration_receipt(destination: Path) -> dict[str, Any]:
    receipt_path = destination / MIGRATION_NAME
    receipt = load_json(receipt_path, required=True, default=None)
    if not isinstance(receipt, dict) or receipt.get("schema") != "sulde-mem-sync-migration-v1":
        raise SyncError("mem-sync migration receipt is invalid")
    if receipt.get("destination") != str(destination.resolve(strict=False)):
        raise SyncError("mem-sync migration destination binding changed")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise SyncError("mem-sync migration artifacts are invalid")
    for name, expected in artifacts.items():
        if name not in {CONFIG_NAME, STATE_NAME, "mem-sync-repo"} or not isinstance(expected, str):
            raise SyncError("mem-sync migration artifact receipt is invalid")
        if _migration_artifact_sha256(destination / name) != expected:
            raise SyncError(f"mem-sync migration artifact drifted: {name}")
    return receipt


def migrate_legacy(source: Path | None = None) -> dict[str, Any]:
    source_root = (source or legacy_kb_home()).expanduser().resolve(strict=True)
    destination = kb_home().expanduser().resolve(strict=False)
    if source_root == destination:
        raise SyncError("legacy and Sulde mem-sync roots must differ")
    receipt_path = destination / MIGRATION_NAME
    if receipt_path.is_file():
        receipt = _validated_migration_receipt(destination)
        if receipt.get("source") != str(source_root):
            raise SyncError("mem-sync migration source binding changed")
        return {**receipt, "idempotent": True}
    if destination.is_symlink():
        raise SyncError("Sulde mem-sync data root must not be a symlink")
    legacy_config = validate_config(
        load_json(source_root / CONFIG_NAME, required=True, default=None)
    )
    source_repo = Path(legacy_config["repo_path"]).expanduser().resolve(strict=True)
    try:
        source_repo.relative_to(source_root)
    except ValueError as error:
        raise SyncError("legacy sync repository is outside the legacy data root") from error
    if source_repo.name != "mem-sync-repo" or not source_repo.is_dir() or source_repo.is_symlink():
        raise SyncError("legacy sync repository must be a real mem-sync-repo directory")
    if (
        git(source_repo, "rev-parse", "--is-inside-work-tree", capture=True)
        != "true"
        or git(source_repo, "rev-parse", "--show-toplevel", capture=True)
        != str(source_repo)
    ):
        raise SyncError("legacy sync repository is not its own Git working tree root")
    targets = [destination / CONFIG_NAME, destination / "mem-sync-repo"]
    legacy_state = source_root / STATE_NAME
    if legacy_state.is_file():
        targets.append(destination / STATE_NAME)
    if any(os.path.lexists(path) for path in targets):
        raise SyncError("Sulde mem-sync migration target already exists without a receipt")
    source_repo_sha256 = _tree_sha256(source_repo)
    destination.mkdir(parents=True, exist_ok=True)
    destination_repo = destination / "mem-sync-repo"
    created: list[Path] = []
    try:
        shutil.copytree(source_repo, destination_repo, symlinks=False)
        created.append(destination_repo)
        migrated_config = dict(legacy_config)
        migrated_config["repo_path"] = str(destination_repo)
        atomic_json(destination / CONFIG_NAME, migrated_config)
        created.append(destination / CONFIG_NAME)
        if legacy_state.is_file():
            atomic_bytes(destination / STATE_NAME, legacy_state.read_bytes())
            created.append(destination / STATE_NAME)
        artifacts = {
            path.name: _migration_artifact_sha256(path)
            for path in targets
        }
        receipt = {
            "schema": "sulde-mem-sync-migration-v1",
            "source": str(source_root),
            "destination": str(destination),
            "source_preserved": True,
            "source_repo_sha256": source_repo_sha256,
            "created_at": utc_now(),
            "artifacts": artifacts,
        }
        atomic_json(receipt_path, receipt)
    except BaseException:
        for path in reversed(created):
            try:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                elif os.path.lexists(path):
                    path.unlink()
            except OSError:
                pass
        raise
    return {**receipt, "idempotent": False}


def rollback_legacy_migration() -> dict[str, Any]:
    destination = kb_home().expanduser().resolve(strict=False)
    receipt = _validated_migration_receipt(destination)
    artifacts = receipt["artifacts"]
    for name in sorted(artifacts, reverse=True):
        path = destination / name
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    (destination / MIGRATION_NAME).unlink()
    return {
        "schema": "sulde-mem-sync-migration-rollback-v1",
        "source": receipt["source"],
        "destination": receipt["destination"],
        "source_preserved": True,
        "removed": sorted(artifacts),
    }


def config_path() -> Path:
    return kb_home() / CONFIG_NAME


def state_path() -> Path:
    return kb_home() / STATE_NAME


def validate_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SyncError("mem-sync.json must contain a JSON object")
    repo_path = value.get("repo_path")
    device_id = value.get("device_id")
    projects = value.get("sync_projects")
    if not isinstance(repo_path, str) or not repo_path.strip():
        raise SyncError("mem-sync.json repo_path must be a non-empty string")
    if not isinstance(device_id, str) or not DEVICE_ID_RE.fullmatch(device_id):
        raise SyncError("mem-sync.json device_id must use only letters, digits, ._- (max 64)")
    if not isinstance(projects, dict):
        raise SyncError("mem-sync.json sync_projects must be an object")
    encrypt = value.get("encrypt", False)
    if not isinstance(encrypt, bool):
        raise SyncError("mem-sync.json encrypt must be true or false")
    value["encrypt"] = encrypt
    seen: dict[str, str] = {}
    for name, settings in projects.items():
        if not isinstance(name, str) or not name or not isinstance(settings, dict):
            raise SyncError("each sync_projects entry must map a project name to an object")
        project_id = settings.get("project_id")
        if not isinstance(project_id, str) or not PROJECT_ID_RE.fullmatch(project_id):
            raise SyncError(f"invalid project_id for project {name!r}")
        if project_id in seen and seen[project_id] != name:
            raise SyncError(
                f"project_id {project_id!r} is assigned to both {seen[project_id]!r} and {name!r}"
            )
        seen[project_id] = name
    return value


def read_config() -> dict[str, Any]:
    return validate_config(load_json(config_path(), required=True, default=None))


def read_state() -> dict[str, Any]:
    value = load_json(state_path(), required=False, default={"projects": {}})
    if not isinstance(value, dict) or not isinstance(value.get("projects", {}), dict):
        raise SyncError("mem-sync-state.json must contain a projects object")
    value.setdefault("projects", {})
    return value


def git(repo: Path, *args: str, capture: bool = False) -> str:
    command = ["git", "-C", str(repo), *args]
    try:
        result = subprocess.run(
            command,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise SyncError(f"cannot run git: {error}") from error
    if result.returncode != 0:
        detail = " ".join(result.stderr.strip().splitlines())[:500]
        raise SyncError(f"git {' '.join(args)} failed ({result.returncode}): {detail}")
    return result.stdout.strip() if capture and result.stdout else ""


def require_repo(config: dict[str, Any]) -> Path:
    home = kb_home().expanduser().resolve(strict=False)
    try:
        repo = sync_repository_path(config["repo_path"], home=home)
    except SuldePathError as error:
        raise SyncError(str(error)) from error
    if repo.name != "mem-sync-repo" or not repo.is_dir() or repo.is_symlink():
        raise SyncError(f"sync repository is not a real mem-sync-repo directory: {repo}")
    if git(repo, "rev-parse", "--is-inside-work-tree", capture=True) != "true":
        raise SyncError(f"sync repository is not a git working tree: {repo}")
    if git(repo, "rev-parse", "--show-toplevel", capture=True) != str(repo):
        raise SyncError("sync repository must be its own Git working tree root")
    return repo


def _sync_git_common_dir(repo: Path) -> Path:
    raw = git(repo, "rev-parse", "--git-common-dir", capture=True)
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = repo / candidate
    if candidate.is_symlink():
        raise SyncError("sync repository Git common directory must not be a symlink")
    common = candidate.resolve(strict=True)
    if not common.is_dir() or common.is_symlink():
        raise SyncError("sync repository Git common directory is unavailable")
    return common


@contextmanager
def sync_transaction_lock(repo: Path):
    lock_path = _sync_git_common_dir(repo) / SYNC_LOCK_NAME
    if lock_path.is_symlink():
        raise SyncError("mem-sync transaction lock must not be a symlink")
    descriptor = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    handle = os.fdopen(descriptor, "a+", encoding="utf-8")
    metadata = os.fstat(handle.fileno())
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or (hasattr(os, "geteuid") and metadata.st_uid != os.geteuid())
    ):
        handle.close()
        raise SyncError("mem-sync transaction lock identity is unsafe")
    if hasattr(os, "fchmod"):
        os.fchmod(handle.fileno(), 0o600)
    locked = False
    try:
        try:
            lock_exclusive_nonblocking(handle)
            locked = True
        except BlockingIOError as error:
            raise TransientSyncError("mem-sync transaction lock is busy") from error
        yield
    finally:
        try:
            if locked:
                unlock(handle)
        finally:
            handle.close()


def scheduled_retry(args: argparse.Namespace, operation):
    attempts = SCHEDULED_MAX_ATTEMPTS if getattr(args, "scheduled", False) else 1
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except TransientSyncError:
            if attempt >= attempts:
                raise
            delay = SCHEDULED_BACKOFF_SECONDS * (2 ** (attempt - 1))
            print(
                f"mem-sync scheduled retry attempt={attempt + 1}/{attempts} backoff={delay:.3f}s",
                file=sys.stderr,
            )
            time.sleep(delay)
    raise AssertionError("unreachable mem-sync retry state")


def require_db() -> Path:
    path = kb_home() / "memory.db"
    if not path.is_file():
        raise SyncError(f"memory database does not exist: {path}")
    return path


def connect_db(path: Path) -> sqlite3.Connection:
    try:
        connection = memory_module().connect(path)
        required = {"mem_entries", "mem_fts", "mem_edges", "mem_entities"}
        found = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE name IN (?,?,?,?)", tuple(required)
            )
        }
        if found != required:
            connection.close()
            raise SyncError("memory database is missing required memory tables")
        return connection
    except sqlite3.Error as error:
        raise SyncError(f"cannot open memory database {path}: {error}") from error


def selected_projects(config: dict[str, Any], requested: str | None) -> list[tuple[str, str]]:
    projects = config["sync_projects"]
    if requested is not None:
        if requested not in projects:
            raise SyncError(f"project is not enabled for sync: {requested}")
        return [(requested, str(projects[requested]["project_id"]))]
    return [(name, str(settings["project_id"])) for name, settings in sorted(projects.items())]


def load_secret_module():
    path = Path(__file__).with_name("mem-secret-scan.py")
    spec = importlib.util.spec_from_file_location("sulde_mem_secret_scan", path)
    if spec is None or spec.loader is None:
        raise SyncError(f"cannot load secret scanner: {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (OSError, ImportError) as error:
        raise SyncError(f"cannot load secret scanner: {error}") from error
    return module


def encryption_key_path() -> Path:
    configured = os.environ.get(KEY_FILE_ENV)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".config" / "sulde" / "mem-sync.key"


def require_encryption_key_file(config: dict[str, Any]) -> None:
    if config["encrypt"] and not encryption_key_path().is_file():
        raise SyncError(f"mem-sync encryption key does not exist: {encryption_key_path()}")


def ensure_interpreter(required_modules: tuple[str, ...], operation: str) -> None:
    missing = [name for name in required_modules if importlib.util.find_spec(name) is None]
    if not missing:
        return
    venv_python = kb_cli.resolve_venv_python(
        kb_home(), require_executable=True
    )
    if venv_python is None:
        raise SyncError(
            f"{operation} requires {', '.join(missing)}; kb venv python not found under: {kb_home() / 'venv'}"
        )
    # 不能用路径 resolve 比较:venv/bin/python 是基解释器符号链接,pyenv 场景下
    # 与外部解释器同真身。改用"当前是否已在 venv 内"本质检测
    if sys.prefix != sys.base_prefix and Path(sys.prefix) == venv_python.parent.parent:
        raise SyncError(f"{operation} requires missing kb venv modules: {', '.join(missing)}")
    try:
        os.execv(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]])
    except OSError as error:
        raise SyncError(f"failed to re-exec kb venv python {venv_python}: {error}") from error


def load_cipher(config: dict[str, Any]) -> Any | None:
    if not config["encrypt"]:
        return None
    path = encryption_key_path()
    try:
        key = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise SyncError(f"cannot read mem-sync encryption key {path}: {error}") from error
    if not key:
        raise SyncError(f"mem-sync encryption key is empty: {path}")
    try:
        from cryptography.fernet import Fernet

        return Fernet(key.encode("ascii"))
    except (ImportError, UnicodeEncodeError, ValueError) as error:
        raise SyncError(f"invalid mem-sync Fernet key {path}: {error}") from error


def key_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def encrypted_payload(cipher: Any, value: str) -> str:
    return cipher.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_payload(cipher: Any | None, record: dict[str, Any], path: Path) -> str:
    required_fields(record, ("payload",), path)
    if cipher is None:
        raise SyncError(f"encrypted record in {path} requires mem-sync.json encrypt=true")
    try:
        return cipher.decrypt(str(record["payload"]).encode("ascii")).decode("utf-8")
    except Exception as error:  # Fernet rejects malformed/tampered tokens with InvalidToken.
        raise SyncError(f"cannot decrypt record in {path}: {error.__class__.__name__}") from error


def memory_module():
    sys.path.insert(0, str(REPO_ROOT / "tools" / "kb-index"))
    try:
        import memory  # type: ignore  # pylint: disable=import-error,import-outside-toplevel
    except ImportError as error:
        raise SyncError(f"cannot load memory module: {error}") from error
    return memory


def append_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    materialized = list(records)
    if not materialized:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("a", encoding="utf-8") as handle:
            for record in materialized:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except (OSError, UnicodeError) as error:
        raise SyncError(f"cannot append sync data to {path}: {error}") from error
    return len(materialized)


def existing_keys(path: Path, fields: tuple[str, ...]) -> set[tuple[Any, ...]]:
    keys: set[tuple[Any, ...]] = set()
    if not path.is_file():
        return keys
    for record in read_jsonl(path):
        keys.add(tuple(record.get(field) for field in fields))
    return keys


def existing_hashes(path: Path, kind: str) -> set[str]:
    hashes: set[str] = set()
    if not path.is_file():
        return hashes
    for record in read_jsonl(path):
        digest = record.get("key_hash")
        if isinstance(digest, str):
            hashes.add(digest)
        elif kind == "edge" and all(field in record for field in ("src", "rel", "dst")):
            hashes.add(key_hash(f"{record['src']}|{record['rel']}|{record['dst']}"))
        elif kind == "entity" and "name" in record:
            hashes.add(key_hash(str(record["name"])))
    return hashes


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    raise SyncError(f"invalid JSONL in {path} line {line_number}: {error}") from error
                if not isinstance(value, dict):
                    raise SyncError(f"invalid JSONL object in {path} line {line_number}")
                yield value
    except (OSError, UnicodeError) as error:
        raise SyncError(f"cannot read {path}: {error}") from error


def fetch_export_rows(
    connection: sqlite3.Connection, project: str, watermarks: dict[str, Any]
) -> tuple[list[sqlite3.Row], list[sqlite3.Row], list[sqlite3.Row]]:
    entries = connection.execute(
        """SELECT id,session_id,source_host,role,content,content_hash,ts FROM mem_entries
           WHERE project=? AND id>? ORDER BY id""",
        (project, int(watermarks.get("last_entry_id", 0))),
    ).fetchall()
    edges = connection.execute(
        """SELECT g.id,g.src,g.rel,g.dst,g.extracted_by,g.confidence,g.ts,
                  e.session_id,e.source_host,e.content_hash
           FROM mem_edges g JOIN mem_entries e ON e.id=g.entry_id
           WHERE e.project=? AND g.id>? ORDER BY g.id""",
        (project, int(watermarks.get("last_edge_id", 0))),
    ).fetchall()
    # Entity rows carry no project column. Re-evaluate all endpoints currently
    # referenced by this project's edges; file-level business-key dedupe keeps
    # this append-only while allowing an old entity to become associated later.
    entities = connection.execute(
        """SELECT x.rowid AS entity_id,x.name,x.type,x.first_seen
           FROM mem_entities x
           WHERE EXISTS (
             SELECT 1 FROM mem_edges g JOIN mem_entries e ON e.id=g.entry_id
             WHERE e.project=? AND (g.src=x.name OR g.dst=x.name))
           ORDER BY x.rowid""",
        (project,),
    ).fetchall()
    return entries, edges, entities


def gate_entries(project: str, entries: list[sqlite3.Row], scanner: Any) -> bool:
    blocked = False
    for row in entries:
        for pattern_name, pattern in scanner.PATTERNS:
            match = pattern.search(str(row["content"]))
            if match:
                print(
                    f"gate blocked project={project} entry_id={row['id']} "
                    f"pattern={pattern_name} sample={scanner.safe_sample(match.group(0))}",
                    file=sys.stderr,
                )
                blocked = True
    if blocked:
        print("先用 mem-secret-scan --redact 处置", file=sys.stderr)
    return not blocked


def update_manifest(directory: Path, project_id: str, project: str, device: str, count: int) -> None:
    path = directory / "manifest.json"
    manifest = load_json(path, required=False, default={})
    if not isinstance(manifest, dict):
        raise SyncError(f"invalid manifest object: {path}")
    if manifest.get("project_id", project_id) != project_id:
        raise SyncError(f"manifest project_id mismatch: {path}")
    manifest["project_id"] = project_id
    manifest["display_name"] = project
    devices = manifest.setdefault("devices", {})
    if not isinstance(devices, dict):
        raise SyncError(f"manifest devices must be an object: {path}")
    info = devices.setdefault(device, {})
    if not isinstance(info, dict):
        info = {}
        devices[device] = info
    info["last_export_ts"] = utc_now()
    info["entry_count"] = count
    atomic_json(path, manifest)


def _single_branch_config(repo: Path, key: str) -> str:
    try:
        output = git(repo, "config", "--get-all", key, capture=True)
    except SyncError as error:
        raise SyncError(f"sync branch upstream is missing {key}") from error
    values = [value.strip() for value in output.splitlines() if value.strip()]
    if len(values) != 1:
        qualifier = "missing" if not values else "multi-valued"
        raise SyncError(f"sync branch upstream {key} is {qualifier}")
    return values[0]


def pull_upstream(repo: Path) -> tuple[str, str, str]:
    """Resolve and validate one explicit upstream without network access."""
    try:
        branch = git(
            repo, "symbolic-ref", "--quiet", "--short", "HEAD", capture=True
        )
    except SyncError as error:
        raise SyncError(
            "sync repository HEAD must be attached to a symbolic branch"
        ) from error
    if not branch or len(branch.splitlines()) != 1:
        raise SyncError(
            "sync repository HEAD must be attached to one symbolic branch"
        )
    git(repo, "check-ref-format", "--branch", branch)
    remote_key = f"branch.{branch}.remote"
    merge_key = f"branch.{branch}.merge"
    remote = _single_branch_config(repo, remote_key)
    merge_ref = _single_branch_config(repo, merge_key)
    if remote.startswith("-"):
        raise SyncError(f"sync branch upstream {remote_key} is invalid")
    try:
        fetch_urls = [
            value.strip()
            for value in git(
                repo, "remote", "get-url", "--all", remote, capture=True
            ).splitlines()
            if value.strip()
        ]
        push_urls = [
            value.strip()
            for value in git(
                repo,
                "remote",
                "get-url",
                "--push",
                "--all",
                remote,
                capture=True,
            ).splitlines()
            if value.strip()
        ]
    except SyncError as error:
        raise SyncError(f"sync branch upstream {remote_key} is invalid") from error
    if len(fetch_urls) != 1 or push_urls != fetch_urls:
        raise SyncError(
            f"sync branch upstream {remote_key} must resolve to one fetch/push URL"
        )
    if not merge_ref.startswith("refs/heads/"):
        raise SyncError(f"sync branch upstream {merge_key} is invalid")
    try:
        git(repo, "check-ref-format", merge_ref)
    except SyncError as error:
        raise SyncError(f"sync branch upstream {merge_key} is invalid") from error
    return branch, remote, merge_ref


def pull(repo: Path, upstream: tuple[str, str, str] | None = None) -> None:
    _branch, remote, merge_ref = upstream or pull_upstream(repo)
    try:
        git(repo, "pull", "--rebase", remote, merge_ref)
    except SyncError as error:
        raise TransientSyncError(str(error)) from error


def commit_push(
    repo: Path,
    device: str,
    counts: tuple[int, int, int],
    upstream: tuple[str, str, str],
    changed_paths: list[str],
) -> None:
    _branch, remote, merge_ref = upstream
    if changed_paths:
        git(repo, "add", "--", *changed_paths)
    changed = git(repo, "status", "--porcelain", capture=True)
    if changed:
        total = sum(counts)
        git(
            repo,
            "-c", "user.name=mem-sync", "-c", "user.email=mem-sync@local",
            "commit", "-m", f"mem-sync {device}: {total} records",
        )
    try:
        git(repo, "push", remote, f"HEAD:{merge_ref}")
    except SyncError as error:
        raise TransientSyncError(str(error)) from error


def command_enable(args: argparse.Namespace) -> int:
    config = read_config()
    path = args.path.expanduser().resolve()
    if not path.is_dir():
        raise SyncError(f"project path does not exist: {path}")
    project_id = args.project_id
    if project_id is None:
        try:
            origin = git(path, "remote", "get-url", "origin", capture=True)
        except SyncError as error:
            raise SyncError("project has no git origin; pass --project-id explicitly") from error
        if not origin:
            raise SyncError("project has no git origin; pass --project-id explicitly")
        project_id = hashlib.sha256(origin.encode("utf-8")).hexdigest()[:12]
    if not PROJECT_ID_RE.fullmatch(project_id):
        raise SyncError("--project-id must use only letters, digits, ._- (max 64)")
    config["sync_projects"][args.project] = {"project_id": project_id}
    validate_config(config)
    atomic_json(config_path(), config)
    print(f"enabled project={args.project} project_id={project_id}")
    return 0


def command_disable(args: argparse.Namespace) -> int:
    config = read_config()
    existed = config["sync_projects"].pop(args.project, None) is not None
    atomic_json(config_path(), config)
    print(f"disabled project={args.project} existed={str(existed).lower()}")
    return 0



def _export_journal_path() -> Path:
    return kb_home() / EXPORT_JOURNAL_NAME


def _write_export_journal(
    repo: Path,
    originals: dict[Path, bytes | None],
    start_head: str,
) -> None:
    artifacts = {
        path.relative_to(repo).as_posix(): raw is not None
        for path, raw in sorted(originals.items(), key=lambda item: str(item[0]))
    }
    atomic_json(
        _export_journal_path(),
        {
            "schema": "sulde-mem-sync-export-transaction-v1",
            "repo": str(repo),
            "start_head": start_head,
            "artifacts": artifacts,
        },
    )


def _clear_export_journal() -> None:
    path = _export_journal_path()
    if path.is_symlink():
        raise SyncError("mem-sync export recovery journal must not be a symlink")
    if path.is_file():
        path.unlink()


def _recover_export_transaction(repo: Path) -> bool:
    path = _export_journal_path()
    if path.is_symlink():
        raise SyncError("mem-sync export recovery journal must not be a symlink")
    if not path.is_file():
        return False
    journal = load_json(path, required=True, default=None)
    if (
        not isinstance(journal, dict)
        or journal.get("schema") != "sulde-mem-sync-export-transaction-v1"
        or journal.get("repo") != str(repo)
        or not GIT_OID_RE.fullmatch(str(journal.get("start_head", "")))
        or not isinstance(journal.get("artifacts"), dict)
    ):
        raise SyncError("mem-sync export recovery journal is invalid")
    artifacts = journal["artifacts"]
    resolved_repo = repo.resolve(strict=True)
    tracked: list[str] = []
    untracked: list[str] = []
    for relative, existed in artifacts.items():
        if (
            not isinstance(relative, str)
            or not relative
            or relative.startswith(("/", "-"))
            or any(part in {"", ".", "..", ".git"} for part in relative.split("/"))
            or type(existed) is not bool
        ):
            raise SyncError("mem-sync export recovery path is invalid")
        target = repo / relative
        try:
            target.resolve(strict=False).relative_to(resolved_repo)
        except ValueError as error:
            raise SyncError("mem-sync export recovery path escaped the repository") from error
        current = repo
        for part in Path(relative).parts[:-1]:
            current = current / part
            if os.path.lexists(current) and current.is_symlink():
                raise SyncError("mem-sync export recovery path crosses a symlink")
        if existed and target.is_symlink():
            raise SyncError("mem-sync export tracked recovery path is a symlink")
        (tracked if existed else untracked).append(relative)
    start_head = str(journal["start_head"])
    current_head = git(repo, "rev-parse", "HEAD", capture=True)
    if current_head == start_head:
        relatives = sorted(artifacts)
        if relatives:
            git(repo, "reset", "-q", "HEAD", "--", *relatives)
        if tracked:
            git(
                repo,
                "restore",
                "--source",
                start_head,
                "--worktree",
                "--",
                *sorted(tracked),
            )
        for relative in sorted(untracked, reverse=True):
            target = repo / relative
            if target.is_file() or target.is_symlink():
                target.unlink()
            parent = target.parent
            while parent != repo and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
    _clear_export_journal()
    return True


def _remember_original(
    originals: dict[Path, bytes | None],
    path: Path,
    *,
    repo: Path,
) -> None:
    try:
        relative = path.relative_to(repo)
    except ValueError as error:
        raise SyncError("mem-sync generated path escaped the repository") from error
    current = repo
    for part in relative.parts[:-1]:
        current = current / part
        if os.path.lexists(current) and current.is_symlink():
            raise SyncError(f"mem-sync generated path crosses a symlink: {relative}")
    if path.is_symlink():
        raise SyncError(f"mem-sync generated path must not be a symlink: {relative}")
    if path.is_file() and path.stat().st_nlink != 1:
        raise SyncError(f"mem-sync generated path must have one link: {relative}")
    if path not in originals:
        originals[path] = path.read_bytes() if path.is_file() else None


def _rollback_export_files(
    repo: Path,
    originals: dict[Path, bytes | None],
    start_head: str,
) -> None:
    if not originals or git(repo, "rev-parse", "HEAD", capture=True) != start_head:
        return
    relatives = sorted(path.relative_to(repo).as_posix() for path in originals)
    try:
        git(repo, "reset", "-q", "HEAD", "--", *relatives)
        for path, raw in originals.items():
            if raw is None:
                if path.is_file() or path.is_symlink():
                    path.unlink()
            else:
                atomic_bytes(path, raw)
        for directory in sorted(
            {path.parent for path, raw in originals.items() if raw is None},
            key=lambda value: len(value.parts),
            reverse=True,
        ):
            if directory != repo and directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
    except (OSError, SyncError) as error:
        raise SyncError(f"cannot roll back uncommitted mem-sync generation: {error}") from error


def _command_export_once(args: argparse.Namespace) -> int:
    config = read_config()
    projects = selected_projects(config, args.project)
    if not projects:
        print("sync allow-list is empty; nothing to export")
        return 0
    require_encryption_key_file(config)
    ensure_interpreter(("cryptography",) if config["encrypt"] else (), "export")
    cipher = load_cipher(config)
    repo = require_repo(config)
    db = require_db()
    scanner = load_secret_module()
    with sync_transaction_lock(repo):
        _recover_export_transaction(repo)
        if git(repo, "status", "--porcelain", capture=True):
            raise SyncError("sync repository has uncommitted state")
        upstream = pull_upstream(repo)
        pull(repo, upstream)
        start_head = git(repo, "rev-parse", "HEAD", capture=True)
        state = read_state()
        next_watermarks: dict[str, dict[str, int]] = {}
        originals: dict[Path, bytes | None] = {}
        for _project, project_id in projects:
            directory = repo / project_id
            for name in (
                f"{config['device_id']}.jsonl",
                f"{config['device_id']}.edges.jsonl",
                f"{config['device_id']}.entities.jsonl",
                "manifest.json",
            ):
                _remember_original(originals, directory / name, repo=repo)
        _write_export_journal(repo, originals, start_head)
        project_results: list[tuple[str, tuple[int, int, int]]] = []
        blocked = False
        connection = connect_db(db)
        try:
            for project, project_id in projects:
                watermarks = state["projects"].get(project_id, {})
                entries, edges, entities = fetch_export_rows(connection, project, watermarks)
                if not gate_entries(project, entries, scanner):
                    blocked = True
                    continue
                directory = repo / project_id
                entry_path = directory / f"{config['device_id']}.jsonl"
                edge_path = directory / f"{config['device_id']}.edges.jsonl"
                entity_path = directory / f"{config['device_id']}.entities.jsonl"
                manifest_path = directory / "manifest.json"
                for path in (entry_path, edge_path, entity_path, manifest_path):
                    _remember_original(originals, path, repo=repo)
                known_entries = existing_keys(entry_path, ("session_id", "content_hash"))
                known_edges = existing_hashes(edge_path, "edge")
                known_entities = existing_hashes(entity_path, "entity")
                entry_records = []
                for row in entries:
                    if (row["session_id"], row["content_hash"]) in known_entries:
                        continue
                    record = {
                        key: row[key]
                        for key in (
                            "session_id", "source_host", "role", "content_hash", "ts"
                        )
                    }
                    if cipher is None:
                        record["content"] = row["content"]
                    else:
                        record.update(
                            enc="fernet",
                            payload=encrypted_payload(cipher, str(row["content"])),
                        )
                    entry_records.append(record)
                edge_records = []
                for row in edges:
                    digest = key_hash(f"{row['src']}|{row['rel']}|{row['dst']}")
                    if digest in known_edges:
                        continue
                    record = {
                        key: row[key]
                        for key in (
                            "confidence", "ts", "session_id", "source_host", "content_hash"
                        )
                    }
                    record["key_hash"] = digest
                    sensitive = {key: row[key] for key in ("src", "rel", "dst", "extracted_by")}
                    if cipher is None:
                        record.update(sensitive)
                    else:
                        record.update(
                            enc="fernet",
                            payload=encrypted_payload(
                                cipher,
                                json.dumps(sensitive, ensure_ascii=False, sort_keys=True),
                            ),
                        )
                    edge_records.append(record)
                entity_records = []
                for row in entities:
                    digest = key_hash(str(row["name"]))
                    if digest in known_entities:
                        continue
                    record = {"key_hash": digest, "first_seen": row["first_seen"]}
                    sensitive = {key: row[key] for key in ("name", "type")}
                    if cipher is None:
                        record.update(sensitive)
                    else:
                        record.update(
                            enc="fernet",
                            payload=encrypted_payload(
                                cipher,
                                json.dumps(sensitive, ensure_ascii=False, sort_keys=True),
                            ),
                        )
                    entity_records.append(record)
                counts = (
                    append_jsonl(entry_path, entry_records),
                    append_jsonl(edge_path, edge_records),
                    append_jsonl(entity_path, entity_records),
                )
                total_entries = len(existing_keys(entry_path, ("session_id", "content_hash")))
                update_manifest(directory, project_id, project, config['device_id'], total_entries)
                next_watermarks[project_id] = {
                    "last_entry_id": max(
                        [int(row["id"]) for row in entries],
                        default=int(watermarks.get("last_entry_id", 0)),
                    ),
                    "last_edge_id": max(
                        [int(row["id"]) for row in edges],
                        default=int(watermarks.get("last_edge_id", 0)),
                    ),
                    "last_entity_id": max(
                        [int(row["entity_id"]) for row in entities],
                        default=int(watermarks.get("last_entity_id", 0)),
                    ),
                }
                project_results.append((project, counts))
            total_counts = tuple(
                sum(counts[index] for _project, counts in project_results)
                for index in range(3)
            )
            changed_paths = sorted(
                path.relative_to(repo).as_posix() for path in originals
                if path.is_file() or originals[path] is not None
            )
            commit_push(repo, config['device_id'], total_counts, upstream, changed_paths)
            for project_id, watermarks in next_watermarks.items():
                state["projects"][project_id] = watermarks
            atomic_json(state_path(), state)
            _clear_export_journal()
        except BaseException:
            _rollback_export_files(repo, originals, start_head)
            _clear_export_journal()
            raise
        finally:
            connection.close()
        for project, counts in project_results:
            print(
                f"export project={project} entries={counts[0]} "
                f"edges={counts[1]} entities={counts[2]}"
            )
        return 1 if blocked else 0


def command_export(args: argparse.Namespace) -> int:
    return scheduled_retry(args, lambda: _command_export_once(args))


def required_fields(record: dict[str, Any], fields: tuple[str, ...], path: Path) -> None:
    missing = [field for field in fields if field not in record]
    if missing:
        raise SyncError(f"record in {path} is missing fields: {','.join(missing)}")


def import_project(
    connection: sqlite3.Connection,
    memory: Any,
    directory: Path,
    project: str,
    device: str,
    cipher: Any | None,
) -> dict[str, int]:
    counts = {"entries": 0, "entry_skipped": 0, "edges": 0, "edge_skipped": 0, "entities": 0, "entity_skipped": 0}
    entry_files = sorted(
        path for path in directory.glob("*.jsonl")
        if not path.name.endswith((".edges.jsonl", ".entities.jsonl")) and path.name != f"{device}.jsonl"
    )
    edge_files = sorted(path for path in directory.glob("*.edges.jsonl") if path.name != f"{device}.edges.jsonl")
    entity_files = sorted(path for path in directory.glob("*.entities.jsonl") if path.name != f"{device}.entities.jsonl")
    with connection:
        for path in entry_files:
            for record in read_jsonl(path):
                if record.get("enc") == "fernet":
                    record = {**record, "content": decrypt_payload(cipher, record, path)}
                fields = ("session_id", "role", "content", "content_hash", "ts")
                required_fields(record, fields, path)
                canonical_session_id, source_host = memory.normalize_session_identity(
                    record["session_id"], record.get("source_host", "unknown")
                )
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO mem_entries(
                           project,session_id,source_host,role,content,content_hash,ts,embedded
                       ) VALUES (?,?,?,?,?,?,?,0)""",
                    (
                        project,
                        canonical_session_id,
                        source_host,
                        record["role"],
                        record["content"],
                        record["content_hash"],
                        record["ts"],
                    ),
                )
                if cursor.rowcount == 1:
                    entry_id = int(cursor.lastrowid)
                    connection.execute(
                        "INSERT INTO mem_fts(rowid,seg_text) VALUES (?,?)",
                        (entry_id, memory.segmented(str(record["content"]))),
                    )
                    counts['entries'] += 1
                else:
                    counts['entry_skipped'] += 1
        for path in entity_files:
            for record in read_jsonl(path):
                if record.get("enc") == "fernet":
                    try:
                        sensitive = json.loads(decrypt_payload(cipher, record, path))
                    except json.JSONDecodeError as error:
                        raise SyncError(f"invalid decrypted entity payload in {path}: {error}") from error
                    if not isinstance(sensitive, dict):
                        raise SyncError(f"invalid decrypted entity payload in {path}")
                    record = {**record, **sensitive}
                fields = ("name", "type", "first_seen")
                required_fields(record, fields, path)
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO mem_entities(name,type,first_seen) VALUES (?,?,?)",
                    tuple(record[field] for field in fields),
                )
                key = "entities" if cursor.rowcount == 1 else "entity_skipped"
                counts[key] += 1
        entry_notnull = any(
            int(row[3]) for row in connection.execute("PRAGMA table_info(mem_edges)") if row[1] == "entry_id"
        )
        for path in edge_files:
            for record in read_jsonl(path):
                if record.get("enc") == "fernet":
                    try:
                        sensitive = json.loads(decrypt_payload(cipher, record, path))
                    except json.JSONDecodeError as error:
                        raise SyncError(f"invalid decrypted edge payload in {path}: {error}") from error
                    if not isinstance(sensitive, dict):
                        raise SyncError(f"invalid decrypted edge payload in {path}")
                    record = {**record, **sensitive}
                fields = ("src", "rel", "dst", "extracted_by", "confidence", "ts", "session_id", "content_hash")
                required_fields(record, fields, path)
                canonical_session_id, _source_host = memory.normalize_session_identity(
                    record["session_id"], record.get("source_host", "unknown")
                )
                entry = connection.execute(
                    "SELECT id FROM mem_entries WHERE session_id=? AND content_hash=?",
                    (canonical_session_id, record["content_hash"]),
                ).fetchone()
                if entry is None and entry_notnull:
                    counts['edge_skipped'] += 1
                    continue
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO mem_edges(src,rel,dst,entry_id,extracted_by,confidence,ts)
                       VALUES (?,?,?,?,?,?,?)""",
                    (record['src'], record['rel'], record['dst'], int(entry[0]) if entry else None,
                     record["extracted_by"], record["confidence"], record["ts"]),
                )
                key = "edges" if cursor.rowcount == 1 else "edge_skipped"
                counts[key] += 1
    return counts


def _command_import_once(args: argparse.Namespace) -> int:
    config = read_config()
    projects = selected_projects(config, args.project)
    if not projects:
        print("sync allow-list is empty; nothing to import")
        return 0
    require_encryption_key_file(config)
    required_modules = ("jieba", "cryptography") if config["encrypt"] else ("jieba",)
    ensure_interpreter(required_modules, "import")
    cipher = load_cipher(config)
    repo = require_repo(config)
    db = require_db()
    with sync_transaction_lock(repo):
        _recover_export_transaction(repo)
        if git(repo, "status", "--porcelain", capture=True):
            raise SyncError("sync repository has uncommitted state")
        upstream = pull_upstream(repo)
        pull(repo, upstream)
        memory = memory_module()
        connection = connect_db(db)
        try:
            for project, project_id in projects:
                directory = repo / project_id
                if not directory.is_dir():
                    print(
                        f"import project={project} entries=0 skipped=0 edges=0 "
                        "edge_skipped=0 entities=0 entity_skipped=0"
                    )
                    continue
                counts = import_project(
                    connection, memory, directory, project, config['device_id'], cipher
                )
                print(
                    f"import project={project} entries={counts['entries']} "
                    f"skipped={counts['entry_skipped']} edges={counts['edges']} "
                    f"edge_skipped={counts['edge_skipped']} "
                    f"entities={counts['entities']} "
                    f"entity_skipped={counts['entity_skipped']}"
                )
        finally:
            connection.close()
    return 0


def command_import(args: argparse.Namespace) -> int:
    return scheduled_retry(args, lambda: _command_import_once(args))


def line_count(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        with path.open(encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except (OSError, UnicodeError) as error:
        raise SyncError(f"cannot count {path}: {error}") from error


def command_status(_args: argparse.Namespace) -> int:
    config = read_config()
    repo = require_repo(config)
    db = require_db()
    state = read_state()
    projects = selected_projects(config, None)
    if not projects:
        print("sync allow-list is empty")
        return 0
    connection = connect_db(db)
    try:
        for project, project_id in projects:
            local = int(connection.execute("SELECT count(*) FROM mem_entries WHERE project=?", (project,)).fetchone()[0])
            watermark = int(state["projects"].get(project_id, {}).get("last_entry_id", 0))
            print(f"project={project} project_id={project_id} local_entries={local} last_entry_id={watermark}")
            directory = repo / project_id
            for path in sorted(directory.glob("*.jsonl")) if directory.is_dir() else []:
                print(f"  file={path.name} lines={line_count(path)}")
    finally:
        connection.close()
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    enable = subparsers.add_parser("enable", help="add a project to the allow-list")
    enable.add_argument("project")
    enable.add_argument("--path", type=Path, required=True)
    enable.add_argument("--project-id")
    disable = subparsers.add_parser("disable", help="remove a project from the allow-list")
    disable.add_argument("project")
    export = subparsers.add_parser("export", help="export allow-listed project memories")
    export.add_argument("--project")
    export.add_argument("--scheduled", action="store_true")
    import_parser = subparsers.add_parser("import", help="import other devices memories")
    import_parser.add_argument("--project")
    import_parser.add_argument("--scheduled", action="store_true")
    migrate = subparsers.add_parser(
        "migrate-legacy", help="copy legacy Claude mem-sync state into Sulde data"
    )
    migrate.add_argument("--legacy-home", type=Path)
    subparsers.add_parser(
        "rollback-legacy", help="remove an exact verified legacy migration copy"
    )
    subparsers.add_parser("status", help="show local and repository sync status")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "enable":
            return command_enable(args)
        if args.command == "disable":
            return command_disable(args)
        if args.command == "export":
            return command_export(args)
        if args.command == "import":
            return command_import(args)
        if args.command == "migrate-legacy":
            print(json.dumps(migrate_legacy(args.legacy_home), sort_keys=True))
            return 0
        if args.command == "rollback-legacy":
            print(json.dumps(rollback_legacy_migration(), sort_keys=True))
            return 0
        return command_status(args)
    except GateBlocked as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except TransientSyncError as error:
        print(f"error: {error}", file=sys.stderr)
        return (
            SCHEDULED_EXIT_TEMPORARY_FAILURE
            if getattr(args, "scheduled", False)
            else 2
        )
    except (SyncError, OSError, sqlite3.Error, UnicodeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
