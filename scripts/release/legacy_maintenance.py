"""Exact first-migration input, not an approval service or a force switch.

Only the independently approved worker consumes this input. A digest proves
identity, not human authority. No signals, inferred global drain or debt repair.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import shlex
import sys
import time

SCHEMA = "sulde-legacy-maintenance-v1"
ORIGIN = "maintenance-window"
LIVE_SCHEMA = "sulde-live-cache-handoff-v1"
TRUST_SCHEMA = "sulde-live-cache-handoff-v2"
LIVE_ORIGIN = "atomic-cache-handoff"
SHA = re.compile(r"[0-9a-f]{64}")
FIELDS = {"schema", "operation_id", "created_at", "expires_at", "kb_home",
          "codex_home", "codex", "candidate_home", "candidate_id", "receipt_sha256",
          "artifact_tree_sha256", "old_state", "cache_bindings", "cohort",
          "maintenance_host", "source_files", "user_home", "launcher_home", "launchagents_dir"}


class MaintenanceError(ValueError):
    pass


class CohortAlive(MaintenanceError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def secure_bytes(path: Path) -> bytes:
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise MaintenanceError("maintenance input path is not canonical")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        meta = os.fstat(fd)
        if (not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1
                or meta.st_uid != os.getuid() or meta.st_mode & 0o022):
            raise MaintenanceError("maintenance input ownership/mode is unsafe")
        with os.fdopen(os.dup(fd), "rb") as stream:
            return stream.read()
    finally:
        os.close(fd)


def process_inventory():
    """POSIX observation, not proof against future or unrecognised callers.

    Keep command *names*, never argument text or secrets. All same-user Codex
    processes are conservative blockers except the exact approved maintenance
    host. No user-supplied ps executable or environment override.
    """
    result = subprocess.run(["/bin/ps", "-ww", "-U", str(os.getuid()),
                             "-o", "pid=,ppid=,lstart=,comm="], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=10,
                            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    if result.returncode:
        raise MaintenanceError("process inventory unavailable")
    rows = []
    for line in result.stdout.splitlines():
        if "\ufffd" in line:
            raise MaintenanceError("process inventory encoding is unknown")
        fields = line.split(None, 7)
        if len(fields) != 8:
            raise MaintenanceError("process inventory malformed")
        pid, parent = int(fields[0]), int(fields[1])
        rows.append({"pid": pid, "parent_pid": parent,
                     "started": " ".join(fields[2:7]), "executable": fields[7]})
    return rows


def process_identity(row):
    return {key: row[key] for key in ("pid", "started", "executable")}


def validate_identity(value):
    if (not isinstance(value, dict) or set(value) != {"pid", "started", "executable"}
            or type(value["pid"]) is not int or value["pid"] <= 1
            or not isinstance(value["started"], str) or not value["started"]
            or not isinstance(value["executable"], str) or not value["executable"].startswith("/")):
        raise MaintenanceError("invalid process identity")


@dataclass(frozen=True)
class MaintenanceContext:
    schema = SCHEMA
    fields = FIELDS
    origin = ORIGIN
    coverage = "approved-cohort-only-not-global-admission"
    raw: bytes
    digest: str
    def __init__(self, raw: bytes, digest: str):
        if not SHA.fullmatch(digest) or hashlib.sha256(raw).hexdigest() != digest:
            raise MaintenanceError("maintenance plan digest differs")
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != self.fields or value["schema"] != self.schema:
            raise MaintenanceError("maintenance plan fields differ")
        if not re.fullmatch(r"[0-9a-f]{32}", str(value["operation_id"])):
            raise MaintenanceError("invalid one-use operation identity")
        for key in ("created_at", "expires_at"):
            if type(value[key]) not in (float, int) or not math.isfinite(value[key]):
                raise MaintenanceError("invalid maintenance deadline")
        if not 0 < value["expires_at"] - value["created_at"] <= 3600:
            raise MaintenanceError("maintenance window must be bounded to one hour")
        for key in ("receipt_sha256", "artifact_tree_sha256"):
            if not isinstance(value[key], str) or not SHA.fullmatch(value[key]):
                raise MaintenanceError("missing candidate identity")
        for key in ("kb_home", "codex_home", "candidate_home", "codex", "user_home", "launcher_home", "launchagents_dir"):
            path = Path(value[key])
            if not path.is_absolute() or path.resolve() != path:
                raise MaintenanceError("noncanonical maintenance target: " + key)
        if not isinstance(value["candidate_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value["candidate_id"]):
            raise MaintenanceError("invalid candidate id")
        if not isinstance(value["old_state"], dict) or not isinstance(value["cache_bindings"], list):
            raise MaintenanceError("missing old installation identity")
        if not value["cache_bindings"] or not value["old_state"].get("plugin", {}).get("path"):
            raise MaintenanceError("maintenance requires an existing installation")
        if not isinstance(value["cohort"], list):
            raise MaintenanceError("invalid cohort")
        for row in [value["maintenance_host"], *value["cohort"]]:
            validate_identity(row)
        pids = [row["pid"] for row in [value["maintenance_host"], *value["cohort"]]]
        if len(pids) != len(set(pids)):
            raise MaintenanceError("duplicate cohort or maintenance identity")
        sources = value["source_files"]
        if not isinstance(sources, dict) or not sources:
            raise MaintenanceError("missing executable source identities")
        for path, sha in sources.items():
            if not Path(path).is_absolute() or not isinstance(sha, str) or not SHA.fullmatch(sha):
                raise MaintenanceError("invalid source binding")
        # Keep immutable raw input; never retain the caller's mutable dict.
        object.__setattr__(self, "raw", bytes(raw))
        object.__setattr__(self, "digest", digest)

    @property
    def plan(self):
        return json.loads(self.raw)

    @property
    def operation_id(self):
        return self.plan["operation_id"]

    def check_processes(self, rows=None):
        plan = self.plan
        rows = process_inventory() if rows is None else rows
        by_pid = {row["pid"]: row for row in rows}
        if len(by_pid) != len(rows):
            raise MaintenanceError("ambiguous process observation")
        host = plan["maintenance_host"]
        if host["pid"] not in by_pid or process_identity(by_pid[host["pid"]]) != host:
            raise MaintenanceError("approved maintenance host is not alive")
        # The worker must actually descend from that exact independent host.
        parent, seen = os.getpid(), set()
        while parent in by_pid and parent not in seen and parent != host["pid"]:
            seen.add(parent)
            parent = by_pid[parent]["parent_pid"]
        if parent != host["pid"]:
            raise MaintenanceError("worker is not owned by the approved maintenance host")
        cohort = {row["pid"]: row for row in plan["cohort"]}
        for pid, expected in cohort.items():
            if pid in by_pid:
                if process_identity(by_pid[pid]) != expected:
                    raise MaintenanceError("cohort PID identity drifted")
        for row in rows:
            if "codex" in Path(row["executable"]).name.lower() and row["pid"] != host["pid"] and row["pid"] not in cohort:
                raise MaintenanceError("new or unknown Codex caller observed")
        if any(pid in by_pid for pid in cohort):
            raise CohortAlive("approved cohort still alive")

    def wait_for_cohort(self):
        while True:
            if not self.plan["created_at"] <= time.time() < self.plan["expires_at"]:
                raise MaintenanceError("maintenance window expired while waiting for cohort")
            try:
                self.check_processes()
                return
            except CohortAlive:
                time.sleep(0.25)

    def check_sources(self, root):
        sources = self.plan["source_files"]
        if set(sources) != {str(path) for path in source_paths(root)}:
            raise MaintenanceError("maintenance requires the complete executable source catalog")
        for path, digest in sources.items():
            if hashlib.sha256(secure_bytes(Path(path))).hexdigest() != digest:
                raise MaintenanceError("maintenance executable source changed")

    def check(self, *, candidate, kb_home, codex, runner, claimed=False):
        import install_codex_plugin as installer
        kb_home = Path(kb_home).resolve()
        plan = self.plan
        if not plan["created_at"] <= time.time() < plan["expires_at"]:
            raise MaintenanceError("maintenance window expired or not started")
        if (str(kb_home.resolve()) != plan["kb_home"]
                or str(installer.default_codex_home().resolve()) != plan["codex_home"]
                or str(installer.launcher_home(kb_home).resolve()) != plan["launcher_home"]
                or str(installer._launchagents_dir().resolve()) != plan["launchagents_dir"]
                or str(Path.home().resolve()) != plan["user_home"]
                or str(Path(codex).resolve()) != plan["codex"]):
            raise MaintenanceError("maintenance installation target differs")
        if installer.tree_digest(candidate) != plan["artifact_tree_sha256"]:
            raise MaintenanceError("maintenance artifact bytes changed")
        self.check_sources(installer.ROOT)
        self.check_processes()
        installer._assert_deployment_cas(plan["old_state"], kb_home=kb_home, codex=codex, runner=runner)
        cache = installer._canonical_cache_root()
        if cache.is_symlink() or installer._stable_cache_bindings(sorted(cache.iterdir())) != plan["cache_bindings"]:
            raise MaintenanceError("maintenance cache inventory changed")
        claim = kb_home / installer.INSTALL_RECOVERY_NAME / "maintenance-claims" / (self.operation_id + ".json")
        if claim.parent.resolve() != claim.parent:
            raise MaintenanceError("maintenance consumption directory is aliased")
        if claimed:
            if json.loads(secure_bytes(claim)) != self.claim_record():
                raise MaintenanceError("maintenance consumption identity differs")
        elif claim.exists() or claim.is_symlink():
            raise MaintenanceError("maintenance operation already consumed; use exact recovery")
        require_legacy_prestate(kb_home, codex, runner, expected_plugin=plan["old_state"]["plugin"])
        return {"status": "legacy_maintenance", "lineage_origin": self.origin,
                "coverage": self.coverage,
                "operation_id": self.operation_id, "plan_sha256": self.digest,
                "cache_bindings": plan["cache_bindings"],
                "registry_installation": None}

    def claim_record(self):
        return {"schema": self.schema, "operation_id": self.operation_id, "plan_sha256": self.digest}

    def claim(self, kb_home):
        """Called only while the existing deployment lock is held. Never retry."""
        import install_transaction_journal as journal
        root = Path(kb_home).resolve() / ".install-recovery" / "maintenance-claims"
        if root.resolve() != root:
            raise MaintenanceError("maintenance consumption directory is aliased")
        journal._ensure_directory(root)
        path = root / (self.operation_id + ".json")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            raw = canonical(self.claim_record())
            with os.fdopen(os.dup(fd), "wb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
        finally:
            os.close(fd)
        journal._fsync_directory(root)


class LiveHandoffContext(MaintenanceContext):
    """Exact native-approved cache handoff, explicitly NOT process drain.

    The retained host identity binds the executing child, not an exclusion of
    other sessions. Safety comes from the installer's atomic path protocol.
    """
    schema = LIVE_SCHEMA
    origin = LIVE_ORIGIN
    coverage = "atomic-cache-paths-not-session-drain"

    def __init__(self, raw, digest):
        super().__init__(raw, digest)
        if self.plan["cohort"]:
            raise MaintenanceError("live handoff must not claim a drained cohort")

    def check_processes(self, rows=None):
        rows = process_inventory() if rows is None else rows
        by_pid = {row["pid"]: row for row in rows}
        host = self.plan["maintenance_host"]
        if len(by_pid) != len(rows) or host["pid"] not in by_pid:
            raise MaintenanceError("live handoff host observation unavailable")
        if process_identity(by_pid[host["pid"]]) != host:
            raise MaintenanceError("live handoff host identity drifted")
        parent, seen = os.getpid(), set()
        while parent in by_pid and parent not in seen and parent != host["pid"]:
            seen.add(parent)
            parent = by_pid[parent]["parent_pid"]
        if parent != host["pid"]:
            raise MaintenanceError("worker is not owned by approved live host")

    def check(self, **kwargs):
        result = super().check(**kwargs)
        import install_codex_plugin as installer
        if self.plan["old_state"]["plugin"]["version"] == installer.plugin_version():
            raise MaintenanceError("live handoff requires a distinct candidate version")
        # Prove filesystem support before claiming or mutating production.
        # The probe has no registry, launcher, cache or authorization effects.
        from atomic_cache_handoff import probe
        probe(Path(self.plan["codex_home"]) / "plugins")
        return result


class TrustedLiveHandoffContext(LiveHandoffContext):
    """Same path-continuity protocol, with exact additional human-reviewed edits."""
    schema = TRUST_SCHEMA
    fields = FIELDS | {"hook_trust"}

    def __init__(self, raw, digest):
        super().__init__(raw, digest)
        from codex_hook_trust import validate_plan
        plan = self.plan
        trust = validate_plan(plan["hook_trust"])
        if (trust["config_file"] != str(Path(plan["codex_home"]) / "config.toml")
                or trust["artifact_tree_sha256"] != plan["artifact_tree_sha256"]):
            raise MaintenanceError("Hook trust belongs to another target or artifact")


def load(path, digest):
    return MaintenanceContext(secure_bytes(Path(path)), digest)


def operation_context(raw, digest):
    """Closed operation dispatch for the held-source native worker."""
    if json.loads(raw).get("schema") == SCHEMA:
        return MaintenanceContext(raw, digest)
    if json.loads(raw).get("schema") == LIVE_SCHEMA:
        return LiveHandoffContext(raw, digest)
    if json.loads(raw).get("schema") == TRUST_SCHEMA:
        return TrustedLiveHandoffContext(raw, digest)
    from first_migration_reversal import ReversalContext
    return ReversalContext(raw, digest)


def execute_operation(context):
    if isinstance(context, MaintenanceContext):
        from candidate_codex_plugin import maintenance_promote
        return maintenance_promote(context)
    from first_migration_reversal import ReversalContext, execute
    if isinstance(context, ReversalContext):
        return execute(context)
    raise MaintenanceError("unsupported maintenance operation")


def verify_origin(kb_home, entry, proof):
    """An already migrated lineage must retain the original committed journal."""
    from install_transaction_journal import load_transaction
    kb_home = Path(kb_home).resolve()
    origin = entry.get("maintenance_origin")
    if (not isinstance(origin, dict) or set(origin) != {"schema", "operation_id", "plan_sha256"}
            or origin.get("schema") not in {ORIGIN: {SCHEMA}, LIVE_ORIGIN: {LIVE_SCHEMA, TRUST_SCHEMA}}.get(entry.get("lineage_origin"), set())
            or not re.fullmatch(r"[0-9a-f]{32}", str(origin.get("operation_id")))
            or not SHA.fullmatch(str(origin.get("plan_sha256")))
            or not isinstance(proof, dict) or set(proof) != {"transaction_id", "descriptor_sha256"}):
        raise MaintenanceError("maintenance lineage proof is missing")
    claim = kb_home / ".install-recovery/maintenance-claims" / (str(origin.get("operation_id")) + ".json")
    if json.loads(secure_bytes(claim)) != origin:
        raise MaintenanceError("maintenance lineage consumption differs")
    transaction = load_transaction(kb_home / ".install-recovery",
        transaction_id=proof["transaction_id"], expected_descriptor_sha256=proof.get("descriptor_sha256"))
    expected = transaction.descriptor["expected_postconditions"].get("stable_hook_entry", {})
    if (expected != entry
            or "committed" not in {row["stage"] for row in transaction.read_records()}):
        raise MaintenanceError("maintenance lineage transaction is not committed")
    return transaction.descriptor


def source_paths(root):
    paths = []
    for relative in ("scripts/release", "scripts/kb", "tools/kb-index"):
        paths.extend(sorted((root / relative).rglob("*.py")))
    # candidate_codex_plugin imports this helper; never permit an unsealed
    # repository import or broaden the catalog to unrelated Hook modules.
    paths.append(root / "hooks/lib/kb_cli.py")
    return paths


def require_legacy_prestate(kb_home, codex, runner, *, expected_plugin):
    """An exact migration action is not permission to rewrite stable lineage."""
    import install_codex_plugin as installer
    from codex_hook_registration import validate_registration
    deployment = json.loads(secure_bytes(Path(kb_home) / installer.DEPLOYMENT_GENERATION_NAME))
    if not isinstance(deployment, dict) or deployment.get("stable_hook_entry") is not None:
        raise MaintenanceError("maintenance is limited to the first legacy Hook migration")
    installation = installer._stable_registry_installation(codex, runner)
    if installation is None:
        raise MaintenanceError("first legacy Hook migration requires an active registry")
    installed = installer._canonical_cache_path(installation[0])
    if (expected_plugin.get("version") != installation[0]
            or expected_plugin.get("path") != str(installation[1].resolve())
            or validate_registration(installed).get("protocol") != "legacy"):
        raise MaintenanceError("first legacy Hook migration requires a proven legacy active registry")


def target_environment(plan):
    environment = {key: value for key, value in os.environ.items()
                   if key in {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR"}}
    environment.update({"HOME": plan["user_home"], "CODEX_HOME": plan["codex_home"],
                        "SULDE_KB_HOME": plan["kb_home"], "SULDE_HOME": plan["launcher_home"],
                        "SULDE_LAUNCHER_HOME": plan["launcher_home"],
                        "SULDE_LAUNCHAGENTS_DIR": plan["launchagents_dir"],
                        "SULDE_HOST_PROVIDER": "codex", "PYTHONDONTWRITEBYTECODE": "1"})
    return environment


def prepare_draft(*, candidate_home, candidate_id, kb_home, codex_home,
                  launcher_home, user_home, launchagents_dir, output, seconds=600,
                  profile="maintenance-window"):
    """Read current facts and create an exclusive local draft, never approve it.

    Caller supplies all affected roots; none is inferred from an independent
    host's temporary HOME. Cohort inventory is an observation, not global drain.
    """
    import uuid
    import candidate_codex_plugin as candidate
    if profile not in {ORIGIN, LIVE_ORIGIN, TRUST_SCHEMA}:
        raise MaintenanceError("unknown migration profile")
    installer = candidate.installer
    roots = {key: str(Path(value).resolve()) for key, value in {
        "candidate_home": candidate_home, "kb_home": kb_home, "codex_home": codex_home,
        "launcher_home": launcher_home, "user_home": user_home, "launchagents_dir": launchagents_dir}.items()}
    if type(seconds) is not int or not 0 < seconds <= 3600:
        raise MaintenanceError("maintenance window must be bounded")
    slot = candidate._slot(Path(roots["candidate_home"]), candidate_id)
    state = candidate._load_state(slot)
    if state.get("status") != "verified" or state.get("promotion_consumed") is True:
        raise MaintenanceError("maintenance requires an unused verified candidate")
    receipt = candidate._load_sealed(candidate._receipt_path(slot),
        schema=candidate.RECEIPT_SCHEMA, field="receipt_sha256")
    if state.get("receipt_sha256") != receipt.get("receipt_sha256"):
        raise MaintenanceError("candidate receipt identity differs")
    codex = str(Path(state["codex"]["executable"]).resolve())
    artifact = Path(state["artifact"]["path"])
    with candidate._process_environment(target_environment(roots)):
        # Refuse pending data migrations before freezing a window or consuming
        # a promotion receipt; install() independently rechecks before writes.
        installer._maintenance_migration_preflight(Path(roots["kb_home"]))
        prepared = installer.PreparedArtifact(artifact.resolve(),
            installer.validate_staged_marketplace(artifact, expected_version=installer.plugin_version()),
            installer.tree_digest(artifact / "plugins/sulde"))
        live = installer.deployment_cas_snapshot(Path(roots["kb_home"]), codex)
        installer._validated_candidate_receipt(receipt, prepared=prepared,
            expected_live_state=live, codex=codex, runner=installer.run_command)
        require_legacy_prestate(Path(roots["kb_home"]), codex, installer.run_command,
                               expected_plugin=live["plugin"])
        cache_bindings = installer._stable_cache_bindings(sorted(installer._canonical_cache_root().iterdir()))
    now = time.time()
    plan = {"schema": TRUST_SCHEMA if profile == TRUST_SCHEMA else LIVE_SCHEMA if profile == LIVE_ORIGIN else SCHEMA, "operation_id": uuid.uuid4().hex,
            "created_at": now, "expires_at": now + seconds,
            **roots, "codex": codex, "candidate_id": candidate_id,
            "receipt_sha256": receipt["receipt_sha256"], "artifact_tree_sha256": prepared.plugin_tree_sha256,
            "old_state": live, "cache_bindings": cache_bindings,
            "cohort": [process_identity(row) for row in process_inventory()
                       if "codex" in Path(row["executable"]).name.lower()] if profile == ORIGIN else [],
            "maintenance_host": None,
            "source_files": {str(path): hashlib.sha256(secure_bytes(path)).hexdigest()
                             for path in source_paths(installer.ROOT)}}
    if profile == TRUST_SCHEMA:
        from codex_hook_trust import prepare_plan
        environment = candidate._candidate_environment(slot, codex, state["python"])
        plan["hook_trust"] = prepare_plan(codex=codex,
            config_file=Path(roots["codex_home"]) / "config.toml",
            artifact_tree_sha256=prepared.plugin_tree_sha256,
            candidate_environment=environment,
            candidate_root=Path(receipt["verifications"]["isolated_registry"]["installed_path"]),
            candidate_cwd=slot / "isolated/workspace", production_cwd=installer.ROOT,
            production_environment=target_environment(roots))
    output = Path(output)
    if not output.is_absolute() or output.resolve() != output:
        raise MaintenanceError("draft output must be canonical")
    raw = canonical(plan)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"draft": str(output), "draft_sha256": hashlib.sha256(raw).hexdigest(),
            "authority": "none-preparation-only", "operation_id": plan["operation_id"]}


# The actual native command embeds this bootstrap, the bundle digest and the
# exact bundle path. Read once, hash held bytes, execute held bytes. Python
# imports under the approved source roots use the same held module content;
# mutating/replacing those files cannot substitute executable code after Allow.
BOOTSTRAP = '''import hashlib,importlib.abc,importlib.machinery,importlib.util,json,os,pathlib,stat,sys
p=pathlib.Path(sys.argv[1])
if not p.is_absolute() or p.resolve()!=p: raise SystemExit("noncanonical bundle")
fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
with os.fdopen(fd,"rb") as f:
 m=os.fstat(f.fileno())
 if not stat.S_ISREG(m.st_mode) or m.st_nlink!=1 or m.st_uid!=os.getuid() or m.st_mode&0o022: raise SystemExit("unsafe bundle")
 raw=f.read()
if hashlib.sha256(raw).hexdigest()!=sys.argv[2]: raise SystemExit("bundle digest differs")
b=json.loads(raw); root=pathlib.Path(b["source_root"]); sources=b["sources"]
class Held(importlib.abc.MetaPathFinder,importlib.abc.Loader):
 def find_spec(self,name,path=None,target=None):
  spec=importlib.machinery.PathFinder.find_spec(name,path)
  if spec is None or spec.origin is None: return None
  if spec.origin not in sources:
   if pathlib.Path(spec.origin).is_relative_to(root): raise ImportError("unsealed source module")
   return None
  out=importlib.util.spec_from_loader(name,self,origin=spec.origin,is_package=spec.submodule_search_locations is not None)
  out.has_location=True
  if spec.submodule_search_locations is not None: out.submodule_search_locations=list(spec.submodule_search_locations)
  return out
 def create_module(self,spec): return None
 def exec_module(self,module): exec(compile(sources[module.__spec__.origin],module.__spec__.origin,"exec"),module.__dict__)
sys.meta_path.insert(0,Held())
sys.path[:0]=[str(root/x) for x in ("scripts/release","scripts/kb","tools/kb-index")]
from legacy_maintenance import operation_context,execute_operation
context=operation_context(b["plan"].encode(),b["plan_sha256"])
if {p:hashlib.sha256(v.encode()).hexdigest() for p,v in sources.items()}!=context.plan["source_files"]: raise SystemExit("source identities differ")
print(json.dumps(execute_operation(context),sort_keys=True))
'''


def prepare_bundle(plan_path, plan_sha256, output, *, root):
    """Prepare only. A returned command is NOT permission to execute it."""
    context = operation_context(secure_bytes(Path(plan_path)), plan_sha256)
    root, output = Path(root).resolve(), Path(output)
    if not output.is_absolute() or output.resolve() != output:
        raise MaintenanceError("bundle output must be canonical")
    sources = {str(path): secure_bytes(path).decode("utf-8") for path in source_paths(root)}
    if {path: hashlib.sha256(raw.encode()).hexdigest() for path, raw in sources.items()} != context.plan["source_files"]:
        raise MaintenanceError("plan must bind the complete executable source catalog")
    bundle = canonical({"source_root": str(root), "sources": sources,
                        "plan": context.raw.decode(), "plan_sha256": context.digest})
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(bundle)
        stream.flush()
        os.fsync(stream.fileno())
    digest = hashlib.sha256(bundle).hexdigest()
    return {"bundle_sha256": digest, "command": shlex.join([
        sys.executable, "-B", "-I", "-c", BOOTSTRAP, str(output), digest]),
        "authority": "none-preparation-only", "operation_id": context.operation_id}
