"""The one known external source binding, not a general config migration engine."""
from __future__ import annotations

from .relocation_storage import _canonical, _store_snapshot
from .relocation_storage import _git

import hashlib
import json
import os
from pathlib import Path
import stat

from .decision_types import IntentGuardianError

SCHEMA = "sulde-repository-relocation-consumers-v1"
FILENAME = "auto-sediment-source.json"
MAX_BYTES = 64 * 1024


def _after(document, repository):
    if (not isinstance(document, dict)
            or set(document) != {"schema", "source_root", "git_common_dir"}
            or document["schema"] != "sulde-auto-sediment-source-v1"
            or any(not isinstance(document[key], str) for key in ("source_root", "git_common_dir"))):
        raise IntentGuardianError("relocation source consumer has an unsupported binding")
    source = Path(repository["source"])
    root, common = Path(document["source_root"]), Path(document["git_common_dir"])
    if not root.is_absolute() or not common.is_absolute() or ".." in root.parts or ".." in common.parts:
        raise IntentGuardianError("relocation source consumer requires absolute canonical paths")
    if not root.is_relative_to(source) and not common.is_relative_to(source):
        return None  # Another repository: preserve its bytes, not its authority.
    if not root.is_relative_to(source) or common != source / ".git" or str(root.relative_to(source)) not in {
        row["relative_path"] for row in repository["worktrees"]
    }:
        raise IntentGuardianError("relocation source consumer is not a registered worktree")
    destination = Path(repository["destination"])
    return {**document, "source_root": str(destination / root.relative_to(source)),
            "git_common_dir": str(destination / ".git")}


def freeze(home, repository):
    path = _canonical(home / FILENAME)
    if not path.exists():
        return {"schema": SCHEMA, "path": str(path), "sha256": "", "mode": None,
                "before_text": None, "after": None}
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > MAX_BYTES):
        raise IntentGuardianError("relocation source consumer must be bounded and owner-only")
    before = _store_snapshot(path)
    try:
        payload = path.read_bytes()
        text = payload.decode("utf-8")
        after = _after(json.loads(text), repository)
    except (UnicodeError, ValueError) as error:
        raise IntentGuardianError("relocation source consumer is unreadable") from error
    if len(payload) > MAX_BYTES or hashlib.sha256(payload).hexdigest() != before["sha256"] or _store_snapshot(path) != before:
        raise IntentGuardianError("relocation source consumer changed during observation")
    if after is not None:
        knowledge = Path(json.loads(text)["source_root"]) / "knowledge"
        if not knowledge.is_dir() or knowledge.is_symlink():
            raise IntentGuardianError("relocation source consumer has no physical knowledge directory")
    return {"schema": SCHEMA, "path": str(path), "sha256": before["sha256"],
            "mode": before["mode"], "before_text": text, "after": after}


def frozen(home, preflight):
    """Validate the frozen desired state without reading a moved source path."""
    value = preflight.get("consumers")
    if value is None:
        return None  # Old plans have no new implicit configuration authority.
    if (not isinstance(value, dict) or set(value) != {"schema", "path", "sha256", "mode", "before_text", "after"}
            or value["schema"] != SCHEMA or value["path"] != str(home / FILENAME)):
        raise IntentGuardianError("relocation consumer plan is invalid")
    text = value["before_text"]
    if text is None:
        if value["sha256"] != "" or value["mode"] is not None or value["after"] is not None:
            raise IntentGuardianError("relocation absent consumer plan is invalid")
    else:
        if (not isinstance(text, str) or len(text.encode()) > MAX_BYTES or value["mode"] != 0o600
                or hashlib.sha256(text.encode()).hexdigest() != value["sha256"]
                or _after(json.loads(text), preflight["repository"]) != value["after"]):
            raise IntentGuardianError("relocation consumer desired state differs")
    return value


def verify_published(home, preflight):
    value = frozen(home, preflight)
    if not value or value["after"] is None:
        return
    root = Path(value["after"]["source_root"])
    common = Path(value["after"]["git_common_dir"])
    if (Path(_git(root, "rev-parse", "--show-toplevel").decode().strip()) != root
            or Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip()) != common
            or not (root / "knowledge").is_dir() or (root / "knowledge").is_symlink()):
        raise IntentGuardianError("relocation published source consumer failed independent Git readback")
    _git(root, "rev-parse", "--verify", "HEAD^{commit}")
