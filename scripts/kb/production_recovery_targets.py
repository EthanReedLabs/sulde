"""Fixed production repair targets; no shell, arbitrary patch, or ledger erasure.

The install manifest is evidence for reconstruction, never an instruction to
execute. Recovery freezes its digest and checks the staged source generation.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

import launcher_contract as launchers
from recovery_lane import (
    RecoveryLaneError, ADAPTER_RESULT_SCHEMA, VERIFIER_RECEIPT_SCHEMA,
    _plain_digest,
)

SUPPORTED_ACTIONS = frozenset({"repair_launcher", "repair_generated_bytecode"})


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def regular(path: Path) -> bytes:
    """Reject aliases and concurrent changes before using repair input."""
    if path != path.resolve(strict=True):
        raise RecoveryLaneError("repair input has a path alias")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.geteuid() or before.st_mode & 0o022):
            raise RecoveryLaneError("repair input identity or permissions are unsafe")
        with os.fdopen(os.dup(fd), "rb") as handle:
            raw = handle.read()
        after = os.fstat(fd)
        named = path.stat(follow_symlinks=False)
        def identity(metadata):
            return (metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_uid,
                    metadata.st_nlink, metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)
        if identity(before) != identity(after) or identity(after) != identity(named):
            raise RecoveryLaneError("repair input changed while reading")
        return raw
    finally:
        os.close(fd)


def file_state(path: Path) -> dict:
    raw = regular(path)
    metadata = path.stat()
    return {"sha256": digest(raw), "mode": stat.S_IMODE(metadata.st_mode)}


class RepairTarget:
    def __init__(self, home: Path, runtime: Path, action: str, target: str):
        if action not in SUPPORTED_ACTIONS:
            raise RecoveryLaneError("action has no production adapter; debt remains unresolved")
        self.home = home.resolve(strict=True)
        self.runtime = runtime.resolve(strict=True)
        self.action, self.target = action, target
        if action == "repair_launcher":
            if target not in {spec.name for spec in launchers.LAUNCHERS}:
                raise RecoveryLaneError("target is not a registered launcher")
        elif target != "runtime-bytecode":
            raise RecoveryLaneError("bytecode repair target must be runtime-bytecode")

    def desired(self) -> tuple[dict, dict[str, bytes]]:
        descriptor_path = self.runtime.parent / ".codex-plugin" / "generation.json"
        descriptor_raw = regular(descriptor_path)
        descriptor = launchers._delivery_generation_payload(self.runtime)
        if descriptor is None or launchers._runtime_tree_digest(
            self.runtime, ignore_bytecode=True
        ) != descriptor["runtime_tree_sha256"]:
            raise RecoveryLaneError("staged source generation drifted; repair refused")
        fixed = {
            "runtime": str(self.runtime), "home": str(self.home),
            "generation": descriptor["generation"],
            "descriptor_sha256": digest(descriptor_raw),
            "runtime_tree_sha256": descriptor["runtime_tree_sha256"],
        }
        if self.action == "repair_generated_bytecode":
            return fixed, {}
        manifest_raw = regular(self.home / "bin" / launchers.MANIFEST_NAME)
        manifest = json.loads(manifest_raw)
        if (manifest.get("schema") != launchers.SCHEMA
                or manifest.get("spec_version") != launchers.SPEC_VERSION
                or manifest.get("source_root") != str(self.runtime)
                or manifest.get("generation") != descriptor["generation"]
                or manifest.get("runtime_tree_sha256") != descriptor["runtime_tree_sha256"]
                or manifest.get("runtime_sha256") != launchers.runtime_digest(self.runtime)):
            raise RecoveryLaneError("launcher manifest does not bind this source generation")
        interpreter = Path(manifest["interpreter"])
        # Managed interpreters may be symlinks. Their resolved bytes, not the
        # spelling of the symlink, are the manifest's execution identity.
        if digest(interpreter.resolve(strict=True).read_bytes()) != manifest["interpreter_sha256"]:
            raise RecoveryLaneError("launcher interpreter drifted")
        spec = next(spec for spec in launchers.LAUNCHERS if spec.name == self.target)
        entry = regular(self.runtime / spec.target_relative)
        record = manifest["launchers"][self.target]
        if digest(entry) != record["target_sha256"]:
            raise RecoveryLaneError("launcher entrypoint drifted")
        source = launchers.render_launcher(
            spec, self.runtime, target_sha256=record["target_sha256"],
            runtime_sha256=manifest["runtime_sha256"],
            runtime_tree_sha256=manifest["runtime_tree_sha256"],
            generation=manifest["generation"], interpreter=interpreter,
            interpreter_sha256=manifest["interpreter_sha256"],
            interpreter_prefix=Path(manifest["interpreter_prefix"]),
        ).encode()
        if digest(source) != record["launcher_sha256"]:
            raise RecoveryLaneError("launcher reconstruction differs from installed manifest")
        fixed["manifest_sha256"] = digest(manifest_raw)
        return fixed, {str(self.home / "bin" / self.target): source}

    def snapshot(self) -> dict:
        fixed, desired = self.desired()
        directories = {}
        if self.action == "repair_launcher":
            files = {path: file_state(Path(path)) for path in desired}
        else:
            files = {}
            for path in sorted(self.runtime.rglob("*")):
                in_cache = "__pycache__" in path.relative_to(self.runtime).parts
                if path.is_dir():
                    if in_cache and path.name != "__pycache__":
                        raise RecoveryLaneError("unexpected directory in bytecode cache")
                    if in_cache:
                        metadata = path.stat()
                        if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022:
                            raise RecoveryLaneError("bytecode directory permissions are unsafe")
                        directories[str(path)] = stat.S_IMODE(metadata.st_mode)
                    continue
                if in_cache and path.suffix != ".pyc":
                    raise RecoveryLaneError("non-bytecode file in cache; preserve it")
                if in_cache or path.suffix == ".pyc":
                    files[str(path)] = file_state(path)
        return {**fixed, "action": self.action, "target": self.target,
                "files": files, "cache_directories": directories}

    def passed(self, before: dict) -> bool:
        after = self.snapshot()
        if {k: v for k, v in after.items() if k not in {"files", "cache_directories"}} != {
            k: v for k, v in before.items() if k not in {"files", "cache_directories"}
        }:
            return False
        if self.action == "repair_generated_bytecode":
            return not after["files"] and not after["cache_directories"] and launchers.runtime_tree_digest(
                self.runtime) == before["runtime_tree_sha256"]
        _, desired = self.desired()
        return all(after["files"][path] == {"sha256": digest(raw), "mode": 0o755}
                   for path, raw in desired.items())


def atomic_bytes(path: Path, raw: bytes, mode: int) -> None:
    if path.parent != path.parent.resolve(strict=True):
        raise RecoveryLaneError("repair destination parent is aliased")
    fd, temporary = tempfile.mkstemp(prefix=".recovery-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        parent_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ProductionRepairAdapter:
    identity = "sha256:" + digest(Path(__file__).read_bytes())

    def __init__(self, target: RepairTarget):
        self.target = target

    def _result(self, request, status, detail):
        return {"schema": ADAPTER_RESULT_SCHEMA,
                **{k: request[k] for k in ("run_id", "effect_id", "action", "target_identity")},
                "adapter_identity": self.identity, "status": status,
                "observed_post_state": {}, "detail": detail}

    def _apply(self, request):
        before = request["expected_pre_state"]
        if self.target.snapshot() != before:
            raise RecoveryLaneError("repair pre-state drifted at execution")
        backups = self.target.home / "state" / "recovery-backups" / request["effect_id"].split(":")[1]
        backups.parent.mkdir(mode=0o700, exist_ok=True)
        if (backups.parent.resolve(strict=True) != backups.parent
                or backups.parent.stat().st_uid != os.geteuid()
                or backups.parent.stat().st_mode & 0o077):
            raise RecoveryLaneError("recovery backup directory is unsafe")
        backups.mkdir(mode=0o700, exist_ok=False)
        originals = {}
        for index, (name, expected) in enumerate(before["files"].items()):
            raw = regular(Path(name))
            if digest(raw) != expected["sha256"]:
                raise RecoveryLaneError("backup source drifted")
            backup = backups / str(index)
            atomic_bytes(backup, raw, 0o600)
            originals[name] = backup
        atomic_bytes(backups / "manifest.json", json.dumps(before, sort_keys=True).encode(), 0o600)
        changed = []
        removed_directories = []
        try:
            if self.target.snapshot() != before:
                raise RecoveryLaneError("repair source changed after backup")
            _, desired = self.target.desired()
            for name, expected in before["files"].items():
                path = Path(name)
                if file_state(path) != expected:
                    raise RecoveryLaneError("repair target drifted before mutation")
                if self.target.action == "repair_launcher":
                    atomic_bytes(path, desired[name], 0o755)
                else:
                    path.unlink()
                changed.append(name)
            if self.target.action == "repair_generated_bytecode":
                for name in sorted(before["cache_directories"], reverse=True):
                    directory = Path(name)
                    directory.rmdir()
                    removed_directories.append(directory)
            # The independent verifier also runs after the adapter returns.
            if not self.target.passed(before):
                raise RecoveryLaneError("repair postcondition failed")
            return self._result(request, "completed", {"backups": str(backups)})
        except Exception:
            rollback = True
            for directory in reversed(removed_directories):
                try:
                    directory.mkdir(mode=before["cache_directories"][str(directory)], exist_ok=False)
                    directory.chmod(before["cache_directories"][str(directory)])
                except OSError:
                    rollback = False
            for name in reversed(changed):
                path = Path(name)
                try:
                    # Never overwrite a third party change during rollback.
                    if self.target.action == "repair_launcher":
                        if file_state(path) != {"sha256": digest(desired[name]), "mode": 0o755}:
                            raise RecoveryLaneError("rollback target changed")
                    elif path.exists() or path.is_symlink():
                        raise RecoveryLaneError("rollback bytecode path was replaced")
                    atomic_bytes(path, regular(originals[name]), before["files"][name]["mode"])
                except (OSError, RuntimeError):
                    rollback = False
            return self._result(request, "failed" if rollback else "unknown",
                                {"rollback": "restored" if rollback else "unknown",
                                 "backups": str(backups)})

    repair_launcher = _apply
    repair_generated_bytecode = _apply

    def reprobe(self, request):
        # A crash after dispatch never grants a second material write.
        status = "completed" if self.target.passed(request["expected_pre_state"]) else "unknown"
        return self._result(request, status, {"read_only_reprobe": True})


class ProductionRepairVerifier:
    identity = _plain_digest("production-repair-independent-readback", {
        "source": digest(Path(__file__).read_bytes()), "version": 1,
    })

    def __init__(self, target: RepairTarget):
        self.target = target

    def verify(self, request):
        try:
            restored = self.target.snapshot() == request["expected_pre_state"]
            passed = self.target.passed(request["expected_pre_state"])
            failed = request["adapter_result"]["status"] == "failed"
            status = "passed" if (restored if failed else passed) else "unknown"
            evidence = {"target_readback": passed, "original_restored": restored}
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            status, evidence = "unknown", {"readback_error": type(error).__name__}
        receipt = {"schema": VERIFIER_RECEIPT_SCHEMA,
                   **{k: request[k] for k in ("run_id", "effect_id", "action", "target_identity", "result_identity")},
                   "verifier_identity": self.identity, "status": status, "evidence": evidence}
        receipt["receipt_id"] = _plain_digest("production-repair-verification", receipt)
        return receipt
