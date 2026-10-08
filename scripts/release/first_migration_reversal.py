"""One exact inverse of the active first legacy-to-stable migration.

Not a force downgrade or an approval API. Initial execution belongs to the
independent native maintenance worker. An active typed journal permits only
mechanical resumption toward its already approved old destination.
"""
from __future__ import annotations

import hashlib
import argparse
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

import install_transaction_journal as journal
import legacy_maintenance as maintenance

SCHEMA = "sulde-first-migration-reversal-plan-v1"
ROOT_FIELDS = {"kb_home", "codex_home", "launcher_home", "user_home", "launchagents_dir"}
FIELDS = ROOT_FIELDS | {"schema", "operation_id", "created_at", "expires_at", "codex",
    "codex_sha256", "python", "python_sha256", "origin", "target_snapshot_sha256",
    "cohort", "maintenance_host", "source_files", "lease_scopes", "current_state", "target_prestate"}


def _sha(path):
    return hashlib.sha256(maintenance.secure_bytes(Path(path))).hexdigest()


class ReversalContext:
    def __init__(self, raw, digest):
        if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != digest:
            raise maintenance.MaintenanceError("reversal plan digest differs")
        plan = json.loads(raw)
        if not isinstance(plan, dict) or set(plan) != FIELDS or plan["schema"] != SCHEMA:
            raise maintenance.MaintenanceError("reversal plan schema differs")
        if not re.fullmatch(r"[0-9a-f]{32}", str(plan["operation_id"])):
            raise maintenance.MaintenanceError("reversal operation identity invalid")
        if (any(type(plan[k]) is not int for k in ("created_at", "expires_at"))
                or not 0 < plan["expires_at"] - plan["created_at"] <= 3600):
            raise maintenance.MaintenanceError("reversal deadline must be bounded")
        for key in ROOT_FIELDS | {"codex", "python"}:
            path = Path(plan[key])
            if not path.is_absolute() or path.resolve() != path:
                raise maintenance.MaintenanceError("noncanonical reversal root: " + key)
        for key in ("codex_sha256", "python_sha256", "target_snapshot_sha256"):
            if not isinstance(plan[key], str) or not maintenance.SHA.fullmatch(plan[key]):
                raise maintenance.MaintenanceError("unproven reversal identity: " + key)
        origin = plan["origin"]
        if (not isinstance(origin, dict) or set(origin) != {"transaction_id", "descriptor_sha256"}
                or not re.fullmatch(r"[0-9a-f]{32,64}", str(origin["transaction_id"]))
                or not maintenance.SHA.fullmatch(str(origin["descriptor_sha256"]))):
            raise maintenance.MaintenanceError("unproven reversal origin")
        if not isinstance(plan["cohort"], list):
            raise maintenance.MaintenanceError("invalid reversal cohort")
        for row in [plan["maintenance_host"], *plan["cohort"]]:
            maintenance.validate_identity(row)
        pids = [row["pid"] for row in [plan["maintenance_host"], *plan["cohort"]]]
        if len(pids) != len(set(pids)):
            raise maintenance.MaintenanceError("duplicate reversal process identity")
        for field in ("current_state", "target_prestate", "source_files"):
            if not isinstance(plan[field], dict) or not plan[field]:
                raise maintenance.MaintenanceError("missing reversal binding: " + field)
        dirs = plan["lease_scopes"]
        if not isinstance(dirs, list) or not dirs:
            raise maintenance.MaintenanceError("explicit lease scope coverage is required")
        seen = set()
        for scope in dirs:
            if (not isinstance(scope, dict) or set(scope) != {"path", "device", "inode"}
                    or not isinstance(scope["path"], str)
                    or type(scope["device"]) is not int or scope["device"] < 0
                    or type(scope["inode"]) is not int or scope["inode"] <= 0
                    or scope["path"] in seen):
                raise maintenance.MaintenanceError("lease scope identity is invalid")
            seen.add(scope["path"])
            path = Path(scope["path"])
            if not path.is_absolute() or path.resolve() != path:
                raise maintenance.MaintenanceError("lease scope is aliased or relative")
        self.raw, self.digest = bytes(raw), digest

    @property
    def plan(self):
        return json.loads(self.raw)

    @property
    def operation_id(self):
        return self.plan["operation_id"]

    check_sources = maintenance.MaintenanceContext.check_sources
    check_processes = maintenance.MaintenanceContext.check_processes
    wait_for_cohort = maintenance.MaintenanceContext.wait_for_cohort

    def check_roots(self, installer, kb_home, codex):
        plan = self.plan
        actual = {"kb_home": Path(kb_home), "codex_home": installer.default_codex_home(),
                  "launcher_home": installer.launcher_home(kb_home), "user_home": Path.home(),
                  "launchagents_dir": installer._launchagents_dir(), "codex": Path(codex),
                  "python": Path(sys.executable)}
        if any(str(value.resolve()) != plan[key] for key, value in actual.items()):
            raise maintenance.MaintenanceError("reversal installation roots differ")
        if _sha(plan["codex"]) != plan["codex_sha256"] or _sha(plan["python"]) != plan["python_sha256"]:
            raise maintenance.MaintenanceError("reversal interpreter or Codex bytes drifted")

    def check_recovery_processes(self):
        rows = maintenance.process_inventory()
        host = self.plan["maintenance_host"]
        if any(row["pid"] == host["pid"] for row in rows):
            self.check_processes(rows)
        elif any("codex" in Path(row["executable"]).name.lower() for row in rows):
            raise maintenance.MaintenanceError("recovery waits for Codex callers to exit")
        # If the approved host ended, the durable operation can resume from a
        # non-Codex worker with no live callers. No expiry or renewed decision.


def _load_origin(plan):
    root = Path(plan["kb_home"]) / ".install-recovery"
    origin = journal.load_transaction(root, plan["origin"]["transaction_id"],
                                     expected_descriptor_sha256=plan["origin"]["descriptor_sha256"])
    if (isinstance(origin, journal.ReverseTransaction) or origin.stage != "committed"
            or origin.snapshot_sha256 != plan["target_snapshot_sha256"]):
        raise maintenance.MaintenanceError("reversal target is not the original committed snapshot")
    return origin


def _target_prestate(origin):
    """CAS all managed snapshot targets, including mutable rules files.

    Known retirement aliases are identity records, not followed paths. Any other
    symlink is rejected by the existing snapshot reader. No snapshot is persisted.
    """
    aliases = {row["alias"]: row["target"] for row in
               origin.descriptor["expected_postconditions"].get("retirements", [])}
    linked, paths = {}, []
    for row in origin.snapshot["targets"]:
        path = Path(row["path"])
        if path.is_symlink():
            if str(path) not in aliases or str(path.resolve()) != aliases[str(path)]:
                raise maintenance.MaintenanceError("managed reversal target is unexpectedly aliased")
            linked[str(path)] = os.readlink(path)
        else:
            paths.append(path)
    raw, _ = journal._capture_snapshot(origin.recovery_root, paths)
    return {"files_sha256": hashlib.sha256(raw).hexdigest(), "aliases": linked}


def _bind_scope(value):
    path = Path(value)
    if not path.is_absolute() or path.resolve() != path or not path.is_dir():
        raise maintenance.MaintenanceError("lease scope must be an existing canonical directory")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    try:
        metadata = os.fstat(descriptor)
        os.listdir(descriptor)
        return {"path": str(path), "device": metadata.st_dev, "inode": metadata.st_ino}
    finally:
        os.close(descriptor)


def _check_leases(plan, target_generation):
    from generation_guard import assert_switch_allowed, GenerationGuardError
    for scope in plan["lease_scopes"]:
        path = Path(scope["path"])
        if path.is_symlink() or path.resolve() != path or not path.is_dir():
            raise maintenance.MaintenanceError("reversal lease scope unavailable")
        # An empty glob from an unreadable/disappearing scope is not proof.
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
        try:
            identity = os.fstat(descriptor)
            if (identity.st_dev, identity.st_ino) != (scope["device"], scope["inode"]):
                raise maintenance.MaintenanceError("approved lease scope identity drifted")
            before = sorted(os.listdir(descriptor))
            try:
                report = assert_switch_allowed(path, target_generation=target_generation, policy="block")
            except GenerationGuardError as error:
                raise maintenance.MaintenanceError(str(error)) from error
            current = path.stat(follow_symlinks=False)
            if (path.is_symlink() or (identity.st_dev, identity.st_ino) != (current.st_dev, current.st_ino)
                    or sorted(os.listdir(descriptor)) != before):
                raise maintenance.MaintenanceError("reversal lease scope changed during observation")
        finally:
            os.close(descriptor)
        if report.get("compatible") is not True:
            raise maintenance.MaintenanceError("reversal lease compatibility is unknown")


def _check_old_material(origin, installer):
    descriptor = origin.descriptor
    maintenance.verify_origin(Path(descriptor["expected_postconditions"]["deployment"]).parent,
        descriptor["expected_postconditions"].get("stable_hook_entry", {}),
        {"transaction_id": origin.transaction_id, "descriptor_sha256": origin.descriptor_sha256})
    # Stable updates retain maintenance lineage too. Their immediate old
    # snapshot is stable, NOT the first migration's legacy destination.
    rows = [row for row in origin.snapshot["targets"]
            if Path(row["path"]).resolve() == Path(descriptor["expected_postconditions"]["deployment"]).resolve()]
    if len(rows) != 1 or rows[0]["state"] != "file":
        raise maintenance.MaintenanceError("original legacy deployment snapshot is missing")
    old = json.loads(journal._read_secure(origin.snapshot_root / "blobs" / rows[0]["sha256"]))
    if (old.get("stable_hook_entry") is not None or old.get("maintenance_origin_transaction") is not None
            or old.get("generation") != descriptor["old_generation"]):
        raise maintenance.MaintenanceError("only the first migration has an eligible legacy destination")
    registry = origin.descriptor["registry"]
    marketplace = registry.get("old_marketplace")
    if (not isinstance(marketplace, str) or not registry.get("old_version")
            or installer.tree_digest(Path(marketplace)) != registry.get("old_marketplace_tree_sha256")):
        raise maintenance.MaintenanceError("original old marketplace is missing or drifted")
    origin.verify_snapshot()


def _check_current(context, origin, installer, runner):
    plan = context.plan
    kb = Path(plan["kb_home"])
    if any(origin.descriptor["registry"].get(key) != value
           for key, value in installer._codex_command_identity(plan["codex"]).items()):
        raise maintenance.MaintenanceError("reversal CLI differs from the original committed installer")
    deployment = installer._read_json(kb / installer.DEPLOYMENT_GENERATION_NAME)
    if deployment.get("maintenance_origin_transaction") != plan["origin"]:
        raise maintenance.MaintenanceError("active maintenance origin differs")
    maintenance.verify_origin(kb, deployment.get("stable_hook_entry", {}), plan["origin"])
    installer._verify_new_postconditions(origin.descriptor, runner=runner)
    installer._assert_deployment_cas(plan["current_state"], kb_home=kb, codex=plan["codex"], runner=runner)
    if _target_prestate(origin) != plan["target_prestate"]:
        raise maintenance.MaintenanceError("managed old-destination paths changed since approval")


def _verify_old(transaction, installer, runner):
    origin = transaction.origin_transaction()
    trust = origin.descriptor["expected_postconditions"].get("hook_trust")
    if trust is not None:
        from codex_hook_trust import verify_previous
        verify_previous(trust, codex=origin.descriptor["registry"]["codex_command"], cwd=installer.ROOT)
    if not origin.verify_restored_snapshot() or not installer._verify_old_registry(origin.descriptor, runner=runner):
        raise maintenance.MaintenanceError("exact old snapshot or registry did not verify")
    expected = origin.descriptor["expected_postconditions"]["scheduler"]["old_loaded_labels"]
    observed = installer._loaded_sulde_labels(runner)
    if observed is None or set(observed) != set(expected):
        raise maintenance.MaintenanceError("old scheduler labels did not verify")
    deployment = installer._read_json(Path(origin.descriptor["expected_postconditions"]["deployment"]))
    if deployment.get("stable_hook_entry") is not None or deployment.get("generation") != transaction.descriptor["new_generation"]:
        raise maintenance.MaintenanceError("restored deployment is not the exact old legacy generation")


def recover(transaction, *, installer, codex, runner, detached=False):
    """Caller holds the deployment lock; pending inverse never becomes install."""
    raw = transaction.descriptor["authority_json"].encode()
    context = ReversalContext(raw, hashlib.sha256(raw).hexdigest())
    plan = context.plan
    kb = Path(plan["kb_home"])
    if transaction.recovery_root.resolve() != (kb / installer.INSTALL_RECOVERY_NAME).resolve():
        raise maintenance.MaintenanceError("reversal journal belongs to another installation root")
    context.check_roots(installer, kb, codex)
    origin = transaction.origin_transaction()
    if (plan["origin"] != transaction.descriptor["origin"] or context.operation_id != transaction.transaction_id
            or plan["target_snapshot_sha256"] != transaction.snapshot_sha256
            or any(origin.descriptor["registry"].get(key) != value
                   for key, value in installer._codex_command_identity(codex).items())):
        raise maintenance.MaintenanceError("active reversal authority binding differs")
    _check_old_material(origin, installer)
    if (os.path.lexists(installer._generation_fence_path(kb))
            and installer._bound_transaction_fence(kb, transaction) is None):
        raise maintenance.MaintenanceError("foreign or damaged reversal fence retained")
    if detached and transaction.stage != "committed":
        raise maintenance.MaintenanceError("detached inverse is not terminal")
    if transaction.stage != "committed":
        context.check_recovery_processes()
        from generation_fence import fence_lock
        with fence_lock(kb):
            fence = installer._bound_transaction_fence(kb, transaction)
            if fence is None:
                if os.path.lexists(installer._generation_fence_path(kb)) or transaction.stage not in {None, "prepared"}:
                    raise maintenance.MaintenanceError("reversal fence is missing, damaged or foreign")
                _check_leases(plan, transaction.descriptor["new_generation"])
                installer._write_generation_fence(kb, from_generation=transaction.descriptor["old_generation"],
                    to_generation=transaction.descriptor["new_generation"], transaction_id=transaction.transaction_id,
                    transaction_descriptor_sha256=transaction.descriptor_sha256)
            _check_leases(plan, transaction.descriptor["new_generation"])
        if transaction.stage is None:
            transaction.append("prepared")
        if transaction.stage == "prepared":
            transaction.append("fenced")
        if transaction.stage == "fenced":
            # No live write preceded restore_started, even across a crash.
            _check_current(context, origin, installer, runner)
            context.check_recovery_processes()
            transaction.append("restore_started")
        if transaction.stage == "restore_started":
            context.check_recovery_processes()
            installer._failure_boundary("reversal.before_restore")
            # The separately approved inverse binds the original descriptor,
            # including its six exact trust values. Preserve all other config.
            from codex_hook_trust import restore as restore_hook_trust
            restore_hook_trust(origin, codex=codex, cwd=installer.ROOT, audit_transaction=transaction)
            descriptor = origin.descriptor
            registry = descriptor["registry"]
            if not installer._verify_old_registry(descriptor, runner=runner):
                installer._registry_remove(codex, runner)
                installer._restore_registry(codex, Path(registry["old_marketplace"]), registry["old_version"], runner)
            installer._remove_transaction_aliases(descriptor)
            origin.restore_snapshot()
            installer._restore_scheduler_process_state(descriptor, runner=runner)
            installer._restore_preexisting_retirement_aliases(descriptor)
            installer._failure_boundary("reversal.after_restore")
            _verify_old(transaction, installer, runner)
            transaction.append("restored")
        _verify_old(transaction, installer, runner)
        if transaction.stage == "restored":
            transaction.append("committed")
    _verify_old(transaction, installer, runner)
    return {"status": "reversed_first_migration", "generation": transaction.descriptor["new_generation"],
            "transaction_id": transaction.transaction_id, "origin": transaction.descriptor["origin"],
            "operational_ready": False, "operational_status": "old_files_verified_live_host_unverified"}


def execute(context):
    import candidate_codex_plugin as candidate
    installer = candidate.installer
    plan = context.plan
    with candidate._process_environment(maintenance.target_environment(plan)):
        kb, codex = Path(plan["kb_home"]), plan["codex"]
        context.check_roots(installer, kb, codex)
        context.check_sources(installer.ROOT)
        root = kb / installer.INSTALL_RECOVERY_NAME
        if not (root / "transactions" / context.operation_id).exists():
            context.wait_for_cohort()
        with installer._deployment_lock(kb):
            active = journal.load_active_transaction(root)
            if active is not None:
                if not isinstance(active, journal.ReverseTransaction) or active.transaction_id != context.operation_id:
                    raise maintenance.MaintenanceError("another active transaction owns recovery")
                if json.loads(active.descriptor["authority_json"]) != plan:
                    raise maintenance.MaintenanceError("reversal replay authority differs")
                transaction = active
            else:
                existing = root / "transactions" / context.operation_id / "descriptor.json"
                if existing.exists():
                    # Exact completed replay is read-only; never resurrect an orphan.
                    raw = journal._read_secure(existing)
                    previous = journal.load_transaction(root, context.operation_id,
                        expected_descriptor_sha256=hashlib.sha256(raw).hexdigest())
                    if (not isinstance(previous, journal.ReverseTransaction) or previous.stage != "committed"
                            or json.loads(previous.descriptor["authority_json"]) != plan):
                        raise maintenance.MaintenanceError("orphan or mismatched reversal requires explicit investigation")
                    return recover(previous, installer=installer, codex=codex, runner=installer.run_command, detached=True)
                if not plan["created_at"] <= time.time() < plan["expires_at"]:
                    raise maintenance.MaintenanceError("reversal start approval expired")
                context.check_processes()
                origin = _load_origin(plan)
                _check_old_material(origin, installer)
                _check_current(context, origin, installer, installer.run_command)
                _check_leases(plan, origin.descriptor["old_generation"])
                if os.path.lexists(installer._generation_fence_path(kb)):
                    raise maintenance.MaintenanceError("existing fence requires recovery before reversal")
                transaction = journal.begin_reversal(root, operation_id=context.operation_id, origin=origin,
                    authority_json=journal._canonical(plan).decode(), failpoint=installer._failure_boundary)
            result = recover(transaction, installer=installer, codex=codex, runner=installer.run_command)
            fence = installer._bound_transaction_fence(kb, transaction)
            installer._finish_verified_transaction_cleanup(kb, transaction, fence)
            return result


def prepare_draft(*, roots, codex, leases_dirs, output, seconds=600):
    """Read-only production observations; exclusive local draft is not approval."""
    import candidate_codex_plugin as candidate
    installer = candidate.installer
    if set(roots) != ROOT_FIELDS or type(seconds) is not int or not 0 < seconds <= 3600:
        raise maintenance.MaintenanceError("exact roots and bounded deadline are required")
    roots = {key: str(Path(value).resolve()) for key, value in roots.items()}
    with candidate._process_environment(maintenance.target_environment(roots)):
        kb = Path(roots["kb_home"])
        deployment = installer._read_json(kb / installer.DEPLOYMENT_GENERATION_NAME)
        proof = deployment.get("maintenance_origin_transaction")
        descriptor = maintenance.verify_origin(kb, deployment.get("stable_hook_entry", {}), proof)
        origin = journal.load_transaction(kb / installer.INSTALL_RECOVERY_NAME, proof["transaction_id"],
                                          expected_descriptor_sha256=proof["descriptor_sha256"])
        installer._verify_new_postconditions(descriptor, runner=installer.run_command)
        _check_old_material(origin, installer)
        now = int(time.time())
        plan = {"schema": SCHEMA, "operation_id": uuid.uuid4().hex,
            "created_at": now, "expires_at": now + seconds, **roots,
            "codex": str(Path(codex).resolve()), "codex_sha256": _sha(Path(codex).resolve()),
            "python": str(Path(sys.executable).resolve()), "python_sha256": _sha(Path(sys.executable).resolve()),
            "origin": proof, "target_snapshot_sha256": origin.snapshot_sha256,
            "current_state": installer.deployment_cas_snapshot(kb, codex), "target_prestate": _target_prestate(origin),
            "cohort": [maintenance.process_identity(row) for row in maintenance.process_inventory()
                       if "codex" in Path(row["executable"]).name.lower()], "maintenance_host": None,
            "lease_scopes": [_bind_scope(Path(value).absolute()) for value in leases_dirs],
            "source_files": {str(path): _sha(path) for path in maintenance.source_paths(installer.ROOT)}}
        if not plan["lease_scopes"]:
            raise maintenance.MaintenanceError("explicit lease scope coverage is required")
        _check_leases(plan, origin.descriptor["old_generation"])
    output = Path(output)
    if not output.is_absolute() or output.resolve() != output:
        raise maintenance.MaintenanceError("draft output must be canonical")
    raw = maintenance.canonical(plan)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"draft": str(output), "draft_sha256": hashlib.sha256(raw).hexdigest(), "authority": "none-preparation-only"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare",))
    for field in sorted(ROOT_FIELDS):
        parser.add_argument("--" + field.replace("_", "-"), type=Path, required=True)
    parser.add_argument("--codex", type=Path, required=True)
    parser.add_argument("--leases-dir", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=600)
    args = parser.parse_args()
    result = prepare_draft(roots={key: getattr(args, key) for key in ROOT_FIELDS},
        codex=args.codex, leases_dirs=args.leases_dir, output=args.output, seconds=args.seconds)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
