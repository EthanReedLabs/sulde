"""Normal controls before injected config/process faults; no production state."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/release"))
import codex_hook_trust as trust
import install_transaction_journal as journal
import legacy_maintenance as maintenance
import install_codex_plugin as installer
from tests.test_install_transaction_journal import InstallTransactionJournalTests
from tests.test_legacy_maintenance import fixture_plan


class Crash(BaseException):
    pass


def inventory(cwd, plugin):
    hooks = []
    names = ("pre_tool_use", "permission_request", "post_tool_use", "session_start", "user_prompt_submit", "stop")
    for event, name in zip(trust.EVENTS, names):
        hooks.append({"key": trust.PLUGIN + ":hooks/hooks.json:" + name + ":0:0",
            "eventName": event, "currentHash": "sha256:" + hashlib.sha256(event.encode()).hexdigest(),
            "command": "echo " + name, "matcher": None, "timeoutSec": 10,
            "async": False, "additionalContextLimit": None, "enabled": True,
            "isManaged": False, "handlerType": "command", "source": "plugin",
            "sourcePath": str(plugin / "hooks/hooks.json"), "pluginId": trust.PLUGIN,
            "trustStatus": "untrusted"})
    return {"data": [{"cwd": str(cwd), "hooks": hooks, "errors": [], "warnings": []}]}


class ConfigBoundary:
    """Substitute only the host RPC boundary, production callbacks remain real."""
    def __init__(self, plan, payload):
        self.plan, self.payload = plan, payload
        self.values = dict(plan["previous"])
        self.version, self.writes, self.fault = 1, 0, None
        self.unrelated = "preserve"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def call(self, method, params):
        if method == "hooks/list":
            result = copy.deepcopy(self.payload)
            for h in result["data"][0]["hooks"]:
                h["trustStatus"] = "trusted" if self.values.get(h["key"]) == h["currentHash"] else "untrusted"
            return result
        if method == "config/read":
            return {"layers": [{"name": {"type": "user", "file": self.plan["config_file"]},
                "version": str(self.version), "config": {"unrelated": self.unrelated,
                    "hooks": {"state": {k: {"trusted_hash": v} for k, v in self.values.items()}}}}]}
        if method != "config/batchWrite":
            raise AssertionError(method)
        if self.fault == "conflict-matching":
            self.values = trust.desired(self.plan)
            self.version += 1
        if self.fault == "conflict":
            self.version += 1
        if params["expectedVersion"] != str(self.version):
            raise trust.NativeRejected("CAS conflict", "configVersionConflict")
        if self.fault == "api-failure":
            raise trust.NativeRejected("native failure before write", "fixture-rejection")
        self.writes += 1
        for row in params["edits"]:
            key = json.loads(row["keyPath"][len("hooks.state."):-len(".trusted_hash")])
            self.values[key] = row["value"]
        self.version += 1
        if self.fault == "lost-response":
            self.fault = None
            raise trust.TrustError("response lost after write")
        if self.fault == "crash-after-write":
            self.fault = None
            raise Crash()
        return {"status": "ok", "version": str(self.version), "filePath": self.plan["config_file"]}


class HookTrustTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.plugin = self.root / "plugin"
        self.payload = inventory(self.root, self.plugin)
        rows = trust.definitions(self.payload, cwd=self.root, plugin_root=self.plugin)
        self.plan = {"schema": trust.SCHEMA, "config_file": str(self.root / "codex/config.toml"),
            "artifact_tree_sha256": "c" * 64, "definitions": rows,
            "previous": {row["key"]: "sha256:" + "0" * 64 for row in rows}}
        self.boundary = ConfigBoundary(self.plan, self.payload)
        self.old_tree, self.launcher = self.root / "old", self.root / "launcher"

    def transaction(self, failpoint=None):
        descriptor = InstallTransactionJournalTests.descriptor(self)
        descriptor["expected_postconditions"]["hook_trust"] = self.plan
        transaction = journal.begin_transaction(self.root / "recovery", descriptor,
            snapshot_paths=(), failpoint=failpoint)
        transaction.append("prepared")
        transaction.append("launcher_published")
        return transaction

    def apply(self, tx):
        trust.apply(tx, codex="fixture", cwd=self.root, plugin_root=self.plugin,
                    client_factory=lambda _: self.boundary)

    def restore(self, tx):
        trust.restore(tx, codex="fixture", cwd=self.root, client_factory=lambda _: self.boundary)

    def test_normal_exact_write_readback_and_per_key_rollback(self):
        tx = self.transaction()
        self.apply(tx)
        self.assertEqual(tx.stage, "hook_trust_written")
        self.assertEqual(self.boundary.values, trust.desired(self.plan))
        self.boundary.unrelated, self.boundary.version = "concurrent edit", 12
        self.restore(tx)
        self.restore(tx)
        self.assertEqual(self.boundary.values, self.plan["previous"])
        self.assertEqual(self.boundary.unrelated, "concurrent edit")
        self.assertEqual(self.boundary.writes, 2)

    def test_typed_authority_old_profiles_reject_extra_trust(self):
        plan = fixture_plan(self.root)
        plan.update(cohort=[], schema=maintenance.LIVE_SCHEMA, hook_trust=self.plan)
        def context():
            raw = maintenance.canonical(plan)
            return maintenance.operation_context(raw, hashlib.sha256(raw).hexdigest())
        with self.assertRaises(maintenance.MaintenanceError):
            context()
        plan["schema"] = maintenance.TRUST_SCHEMA
        self.assertIsInstance(context(), maintenance.TrustedLiveHandoffContext)
        plan["hook_trust"]["artifact_tree_sha256"] = "a" * 64
        with self.assertRaises(maintenance.MaintenanceError):
            context()

    def test_stale_definition_refused_before_write_and_discovery_retained(self):
        tx = self.transaction()
        self.payload["data"][0]["hooks"][0]["command"] = "echo unreviewed"
        with self.assertRaisesRegex(trust.TrustError, "differs"):
            self.apply(tx)
        self.assertEqual(self.boundary.writes, 0)
        self.assertEqual(tx.stage, "launcher_published")
        self.assertEqual(len(list(tx.transaction_root.glob("hook-trust-discovery-*.json"))), 1)

    def test_cas_conflict_preserves_user_values_and_old_generation(self):
        tx = self.transaction()
        self.boundary.fault = "conflict"
        with self.assertRaisesRegex(trust.TrustError, "CAS"):
            self.apply(tx)
        self.boundary.fault = None
        self.restore(tx)
        self.assertEqual(self.boundary.writes, 0)
        self.assertEqual(self.boundary.values, self.plan["previous"])

    def test_api_failure_is_not_success(self):
        tx = self.transaction()
        self.boundary.fault = "api-failure"
        with self.assertRaisesRegex(trust.TrustError, "before write"):
            self.apply(tx)
        self.restore(tx)
        self.assertEqual(self.boundary.writes, 0)
        outcome = json.loads(next(tx.transaction_root.glob("hook-trust-write-outcome-*.json")).read_text(encoding="utf-8"))
        self.assertEqual(outcome["value"]["outcome"], "rejected")
        self.assertFalse(list(tx.transaction_root.glob("hook-trust-write-ack-*.json")))

    def test_lost_response_retains_unknown_ownership_despite_matching_readback(self):
        tx = self.transaction()
        self.boundary.fault = "lost-response"
        with self.assertRaisesRegex(trust.TrustError, "response lost"):
            self.apply(tx)
        self.assertEqual(tx.stage, "hook_trust_write_started")
        with self.assertRaisesRegex(trust.TrustError, "conflict"):
            self.restore(journal.load_active_transaction(tx.recovery_root))
        self.assertEqual(self.boundary.values, trust.desired(self.plan))
        self.assertEqual(self.boundary.writes, 1)
        self.assertTrue(tx.active_path.exists())

    def test_crash_after_write_without_ack_retains_unknown_ownership(self):
        tx = self.transaction()
        self.boundary.fault = "crash-after-write"
        with self.assertRaises(Crash):
            self.apply(tx)
        with self.assertRaisesRegex(trust.TrustError, "conflict"):
            self.restore(journal.load_active_transaction(tx.recovery_root))
        self.assertEqual(self.boundary.values, trust.desired(self.plan))
        self.assertEqual(self.boundary.writes, 1)
        self.assertTrue(tx.active_path.exists())

    def test_crash_before_api_write_does_not_infer_success(self):
        def crash(name):
            if name == "journal.after.hook_trust_write_started":
                raise Crash()
        tx = self.transaction(failpoint=crash)
        with self.assertRaises(Crash):
            self.apply(tx)
        self.restore(journal.load_active_transaction(tx.recovery_root))
        self.assertEqual(self.boundary.writes, 0)

    def test_acknowledged_write_crash_before_verified_stage_can_compensate(self):
        def crash(name):
            if name == "journal.before.hook_trust_written":
                raise Crash()
        tx = self.transaction(failpoint=crash)
        with self.assertRaises(Crash):
            self.apply(tx)
        self.assertEqual(tx.stage, "hook_trust_write_started")
        self.restore(journal.load_active_transaction(tx.recovery_root))
        self.assertEqual(self.boundary.values, self.plan["previous"])
        self.assertEqual(self.boundary.writes, 2)

    def test_corrupted_ack_cannot_authorize_compensation(self):
        tx = self.transaction()
        self.apply(tx)
        path = next(tx.transaction_root.glob("hook-trust-write-ack-*.json"))
        original = path.read_text(encoding="utf-8")
        for kind in ("transaction", "descriptor", "target", "status", "request", "version"):
            row = json.loads(original)
            if kind == "transaction": row["transaction_id"] = "foreign"
            if kind == "descriptor": row["descriptor_sha256"] = "0" * 64
            if kind == "target": row["value"]["reply"]["filePath"] = "/foreign/config.toml"
            if kind == "status": row["value"]["reply"]["status"] = "failed"
            if kind == "request": row["value"]["values"] = self.plan["previous"]
            if kind == "version": row["value"]["reply"]["version"] = None
            path.write_text(json.dumps(row), encoding="utf-8")
            with self.subTest(kind=kind), self.assertRaises(trust.TrustError):
                self.restore(tx)
            self.assertEqual(self.boundary.writes, 1)
        path.write_text(original, encoding="utf-8")
        self.restore(tx)
        self.assertEqual(self.boundary.values, self.plan["previous"])

    def test_rollback_conflict_retains_audit_and_never_overwrites(self):
        tx = self.transaction()
        self.apply(tx)
        key = next(iter(self.boundary.values))
        self.boundary.values[key] = "sha256:" + "f" * 64
        before = copy.deepcopy(self.boundary.values)
        with self.assertRaisesRegex(trust.TrustError, "conflict"):
            self.restore(tx)
        self.assertEqual(self.boundary.values, before)
        self.assertTrue(tx.active_path.is_file())

    def test_changed_prestate_refused_without_write(self):
        tx = self.transaction()
        self.boundary.values[next(iter(self.boundary.values))] = "sha256:" + "a" * 64
        with self.assertRaisesRegex(trust.TrustError, "prestate"):
            self.apply(tx)
        self.assertEqual(self.boundary.writes, 0)

    def test_no_write_intent_never_compensates_foreign_matching_values(self):
        tx = self.transaction()
        self.boundary.values = trust.desired(self.plan)
        with self.assertRaisesRegex(trust.TrustError, "conflict"):
            self.restore(tx)
        self.assertEqual(self.boundary.writes, 0)

    def test_cas_rejection_cannot_compensate_another_writers_matching_values(self):
        tx = self.transaction()
        self.boundary.fault = "conflict-matching"
        with self.assertRaisesRegex(trust.TrustError,"CAS"):
            self.apply(tx)
        self.assertEqual(self.boundary.writes,0)
        self.boundary.fault = None
        with self.assertRaises(trust.TrustError):
            self.restore(tx)
        self.assertEqual(self.boundary.writes,0)
        self.assertEqual(self.boundary.values,trust.desired(self.plan))

    def recover(self, tx, *, after_restore=None):
        # Substitute only external CLI/config/scheduler observations; the
        # actual recovery branch, journal and snapshot verification execute.
        with mock.patch.object(trust.NativeClient,"__init__",return_value=None), \
             mock.patch.object(trust.NativeClient,"call",side_effect=self.boundary.call), \
             mock.patch.object(trust.NativeClient,"close",return_value=None), \
             mock.patch.object(installer,"_codex_command_identity",return_value={"codex_command":tx.descriptor["registry"]["codex_command"]}), \
             mock.patch.object(installer,"_verify_old_registry",return_value=True), \
             mock.patch.object(installer,"_restore_scheduler_process_state",side_effect=after_restore):
            return installer._recover_transaction(tx,codex="fixture",runner=lambda *_a,**_k: None)

    def test_terminal_rollback_is_read_only_after_user_retrust(self):
        tx = self.transaction()
        self.apply(tx)
        self.restore(tx)
        tx.append("rollback_started")
        tx.append("rolled_back")
        self.boundary.values = trust.desired(self.plan)
        writes = self.boundary.writes
        with self.assertRaises(trust.TrustError):
            self.recover(tx)
        self.assertEqual(self.boundary.writes,writes)
        self.assertEqual(self.boundary.values,trust.desired(self.plan))

    def test_drift_after_compensation_cannot_mark_rollback_complete(self):
        tx = self.transaction()
        self.apply(tx)
        def drift(*_a,**_kw):
            self.boundary.values = trust.desired(self.plan)
        with self.assertRaises(trust.TrustError):
            self.recover(tx,after_restore=drift)
        self.assertNotEqual(tx.stage,"rolled_back")
        self.assertTrue(tx.active_path.exists())

    def test_independent_rollback_readback_detects_late_trust_drift(self):
        def drift(name):
            if name == "journal.after.rolled_back":
                self.boundary.values = trust.desired(self.plan)
        tx = self.transaction(failpoint=drift)
        self.apply(tx)
        with self.assertRaises(trust.TrustError):
            self.recover(tx)
        self.assertTrue(tx.active_path.exists())
        self.assertEqual(self.boundary.values, trust.desired(self.plan))
        writes = self.boundary.writes
        with self.assertRaises(trust.TrustError):
            self.recover(journal.load_active_transaction(tx.recovery_root))
        self.assertEqual(self.boundary.writes, writes)

    def test_discovery_errors_duplicates_and_managed_hooks_are_not_approved(self):
        for kind in ("error", "duplicate", "missing", "managed", "disabled"):
            payload = copy.deepcopy(self.payload)
            row = payload["data"][0]
            if kind == "error": row["errors"] = [{"message": "broken"}]
            if kind == "duplicate": row["hooks"].append(row["hooks"][0])
            if kind == "missing": row["hooks"].pop()
            if kind == "managed": row["hooks"][0]["isManaged"] = True
            if kind == "disabled": row["hooks"][0]["enabled"] = False
            with self.subTest(kind=kind), self.assertRaises(trust.TrustError):
                trust.definitions(payload, cwd=self.root, plugin_root=self.plugin)


@unittest.skipUnless(os.environ.get("LIVE_HANDOFF_TEST_CODEX"), "requires explicit official CLI")
class NativeHookTrustTests(HookTrustTests):
    """Additional real RPC normal/CAS control. Inherited cases stay fault injections."""
    def test_native_atomic_api_trust_readback_cas_and_restore(self):
        cli = os.environ["LIVE_HANDOFF_TEST_CODEX"]
        print("OFFICIAL_REGISTRY_CLI=" + cli, flush=True)
        home = self.root / "codex"
        home.mkdir()
        config = home / "config.toml"
        config.write_text('personality = "friendly"\n', encoding="utf-8")
        env = {k:v for k,v in os.environ.items() if k in ("PATH", "LANG", "TMPDIR")}
        env.update(HOME=str(self.root), CODEX_HOME=str(home))
        with trust.NativeClient(cli, environment=env) as client:
            first = trust.read_values(client, self.plan, cwd=self.root)
            trust.write_values(client, self.plan, first, self.plan["previous"])
            before = trust.read_values(client, self.plan, cwd=self.root)
            trust.write_values(client, self.plan, before, trust.desired(self.plan))
            with self.assertRaisesRegex(trust.TrustError, "configVersionConflict"):
                trust.write_values(client, self.plan, before, self.plan["previous"])
            after = trust.read_values(client, self.plan, cwd=self.root)
            self.assertEqual(after["values"], trust.desired(self.plan))
            trust.write_values(client, self.plan, after, self.plan["previous"])
            self.assertEqual(trust.read_values(client, self.plan, cwd=self.root)["values"], self.plan["previous"])
            self.assertIn('personality = "friendly"', config.read_text(encoding="utf-8"))

    def native_installed(self):
        cli = os.environ["LIVE_HANDOFF_TEST_CODEX"]
        print("OFFICIAL_REGISTRY_CLI=" + cli, flush=True)
        home = self.root / "codex"
        home.mkdir()
        (home / "config.toml").write_text('personality = "friendly"\n', encoding="utf-8")
        environment = {k:v for k,v in os.environ.items() if k in ("PATH", "LANG", "TMPDIR")}
        environment.update(HOME=str(self.root), CODEX_HOME=str(home))
        market = self.root / "market"
        plugin = market / "plugins/sulde"
        (market / ".agents/plugins").mkdir(parents=True)
        (plugin / ".codex-plugin").mkdir(parents=True)
        (plugin / "hooks").mkdir()
        (plugin / ".codex-plugin/plugin.json").write_text(json.dumps({"name":"sulde", "version":"9.34.0",
            "description":"Isolated trust test", "hooks":"./hooks/hooks.json"}), encoding="utf-8")
        (market / ".agents/plugins/marketplace.json").write_bytes(
            (ROOT / "integrations/codex/.agents/plugins/marketplace.json").read_bytes())
        hook_config = {event[0].upper()+event[1:]: [{"hooks":[{"type":"command", "command":"echo "+event}]}]
            for event in trust.EVENTS}
        (plugin / "hooks/hooks.json").write_text(json.dumps({"hooks":hook_config}), encoding="utf-8")
        for args in (["plugin", "marketplace", "add", str(market)], ["plugin", "add", trust.PLUGIN, "--json"]):
            result = subprocess.run([cli,*args], env=environment, cwd=self.root, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
        installed = Path(json.loads(result.stdout)["installedPath"])
        with trust.NativeClient(cli, environment=environment) as client:
            payload = client.call("hooks/list", {"cwds":[str(self.root)]})
            rows = trust.definitions(payload, cwd=self.root, plugin_root=installed)
            self.plan.update(definitions=rows, previous={r["key"]:"sha256:"+"0"*64 for r in rows})
            before = trust.read_values(client, self.plan, cwd=self.root)
            trust.write_values(client, self.plan, before, self.plan["previous"])
        return cli, environment, installed

    def test_real_discovery_apply_and_recovery_through_official_host(self):
        cli, environment, installed = self.native_installed()
        tx = self.transaction()
        factory = lambda _: trust.NativeClient(cli, environment=environment)
        trust.apply(tx, codex=cli, cwd=self.root, plugin_root=installed, client_factory=factory)
        self.assertEqual(tx.stage, "hook_trust_written")
        trust.restore(tx, codex=cli, cwd=self.root, client_factory=factory)
        with factory(cli) as client:
            self.assertEqual(trust.read_values(client,self.plan,cwd=self.root)["values"],self.plan["previous"])
            payload = client.call("hooks/list", {"cwds":[str(self.root)]})
            self.assertTrue(all(h["trustStatus"] != "trusted" for h in payload["data"][0]["hooks"]))

    def test_real_api_lost_response_retains_unproven_write_ownership(self):
        cli, environment, installed = self.native_installed()
        tx = self.transaction()
        class LostReply(trust.NativeClient):
            def call(self, method, params):
                result = super().call(method, params)
                if method == "config/batchWrite":
                    raise trust.TrustError("injected loss of actual native reply")
                return result
        with self.assertRaisesRegex(trust.TrustError,"injected loss"):
            trust.apply(tx,codex=cli,cwd=self.root,plugin_root=installed,
                client_factory=lambda _: LostReply(cli,environment=environment))
        with self.assertRaisesRegex(trust.TrustError,"conflict"):
            trust.restore(journal.load_active_transaction(tx.recovery_root),codex=cli,cwd=self.root,
                client_factory=lambda _: trust.NativeClient(cli,environment=environment))
        with trust.NativeClient(cli,environment=environment) as client:
            self.assertEqual(trust.read_values(client,self.plan,cwd=self.root)["values"],trust.desired(self.plan))
        self.assertTrue(tx.active_path.exists())


if __name__ == "__main__":
    unittest.main()
