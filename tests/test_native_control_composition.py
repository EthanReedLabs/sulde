"""Real candidate artifact, Codex CLI/unified exec, Hook decisions and readback."""
import json
import http.server
import io
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/release"))
import candidate_codex_plugin as candidate
from native_pretool_canary import NativeCanary


@unittest.skipIf(os.name == "nt", "Windows native acceptance remains Windows-owned")
@unittest.skipUnless(shutil.which("codex"), "actual Codex CLI required")
class NativeControlCompositionTests(unittest.TestCase):
    def test_real_safe_batches_negative_and_partial_failure(self):
        with tempfile.TemporaryDirectory(prefix="sulde-native-composition-") as temporary:
            slot = Path(temporary).resolve()
            installer, codex = candidate.installer, shutil.which("codex")
            prepared = installer._stage_artifact(slot / "artifact", platform="posix", runner=installer.run_command)
            generation = prepared.descriptor["delivery_generation"]
            env = candidate._candidate_environment(slot, codex, candidate._python_identity(Path(sys.executable)))
            runner = candidate._bound_runner(env)
            # Capture the outer OS guard before the candidate replaces the
            # environment; otherwise the fixture accidentally nests Seatbelt.
            externally_isolated = bool(os.environ.get("SULDE_ISOLATED_TEST_RUN_ID"))
            with candidate._process_environment(env):
                installed = installer._registry_add(codex, prepared.marketplace, runner,
                    expected_version=generation["plugin_version"])
                kb = Path(env["SULDE_KB_HOME"])
                installer._install_launchers(installed, kb, runner, platform="posix")
                installer._smoke_installed(installed, kb, codex=codex,
                    expected_tree_sha256=prepared.plugin_tree_sha256, runner=runner)
                workspace = Path(env["SULDE_HOME"]) / "composition-canary"
                workspace.mkdir()
                self.assertEqual(runner(["git", "init", str(workspace)], environment=env, timeout=10).returncode, 0)
                preserved = workspace / "preserved"
                preserved.mkdir()
                guardian = Path(env["SULDE_HOME"]) / "bin/intent-guardian"
                quoted = shlex.quote(str(guardian))
                outputs = {}
                original_server = http.server.ThreadingHTTPServer

                def capture_server(address, handler):
                    original_post = handler.do_POST
                    def post(instance):
                        raw = instance.rfile.read(int(instance.headers.get("Content-Length", "0")))
                        body = json.loads(raw)
                        for item in body.get("input", []):
                            if isinstance(item, dict) and item.get("type") == "function_call_output":
                                outputs[item.get("call_id")] = str(item.get("output", ""))[:2500]
                        instance.rfile = io.BytesIO(raw)
                        return original_post(instance)
                    handler.do_POST = post
                    return original_server(address, handler)

                with mock.patch.object(http.server, "ThreadingHTTPServer", side_effect=capture_server), \
                     NativeCanary(codex, workspace, env, externally_isolated=externally_isolated).start() as host:
                    contract, _ = candidate._activate_candidate_enforce_contract(
                        guardian, kb_home=kb, workspace=workspace, session=host.session,
                        environment=env, runner=runner)
                    scope = shlex.join([
                        "sulde:intent-guardian", "--skill-path", str(installed / "skills/intent-guardian/SKILL.md"),
                        "--contract", str(contract), "--provider", "codex", "--session-id", host.session,
                    ])
                    commands = [
                        f"{quoted} skill-start {scope} && {quoted} skill-end {scope}",
                        f"{quoted} show --contract {shlex.quote(str(contract))} | python3 -c 'import json,sys; print(json.load(sys.stdin).get(\"status\"))'",
                        f"{quoted} --help ; rm -r -- {shlex.quote(str(preserved))}",
                        f"{quoted} --help && touch after-negative.txt",
                        f"{quoted} show --contract missing.json && touch must-not-run.txt ; {quoted} show --contract {shlex.quote(str(contract))} > observed.json",
                    ]
                    items = host.execute(commands)
                    if not (workspace / "after-negative.txt").is_file():
                        print("NATIVE_COMPOSITION_DIAGNOSTIC=" + json.dumps({
                            "outputs": outputs,
                            "hooks": [{key: row["params"]["run"].get(key) for key in ("eventName", "status", "entries")}
                                      for row in host.notifications if row.get("method") == "hook/completed"
                                      and row["params"]["run"].get("eventName") == "preToolUse"],
                        }, default=str)[-18000:], flush=True)
                    self.assertTrue(preserved.is_dir())
                    self.assertTrue((workspace / "after-negative.txt").is_file())
                    self.assertFalse((workspace / "must-not-run.txt").exists())
                    self.assertEqual(json.loads((workspace / "observed.json").read_text())["status"], "active")
                    denials = [row for row in host.notifications if row.get("method") == "hook/completed"
                               and row["params"]["run"].get("eventName") == "preToolUse"
                               and row["params"]["run"].get("status") == "blocked"]
                    self.assertEqual(len(denials), 1)
                    self.assertEqual(sum(item.get("exitCode") == 0 for item in items), 4, items)
                    # A fresh candidate process, not in-memory proof assembly,
                    # reads the actual records emitted by this native host.
                    source = (
                        "import sys,json; from pathlib import Path; "
                        f"sys.path.insert(0, {str(installed / 'runtime/scripts/kb')!r}); "
                        "from intent_guardian import audit_path,load_contract; "
                        f"p=Path({str(contract)!r}); c=load_contract(p); "
                        "rows=[json.loads(s) for s in audit_path(p).read_text().splitlines()]; "
                        f"rows=[r for r in rows if r.get('event',{{}}).get('session_id')=={host.session!r} "
                        "and r.get('event',{}).get('composition')]; "
                        "print(json.dumps({'rows':rows,'open_events':c['runtime']['open_events'],"
                        "'pending':c['runtime']['pending_verifications'],'frames':c['runtime']['active_skill_frames'],"
                        "'grants':c.get('continuation',{}).get('grants',[]),'status':c['status']}))"
                    )
                    readback = candidate._parse_json_result(runner([sys.executable, "-B", "-c", source],
                        environment=env, timeout=20), label="fresh candidate composition reader")
                    self.assertEqual(readback["open_events"], [])
                    self.assertEqual(readback["pending"], [])
                    self.assertEqual(readback["frames"], [])
                    self.assertEqual(readback["grants"], [])
                    rows = readback["rows"]
                    pre = [row for row in rows if row["event"]["phase"] == "started"]
                    self.assertEqual(len(pre), 5, rows)
                    refused = [row for row in pre if row["decision"]["action"] == "deny"]
                    self.assertEqual(len(refused), 1)
                    self.assertEqual(refused[0]["event"]["call_id"], "candidate_native_2")
                    for row in rows:
                        event = row["event"]
                        self.assertEqual(event["artifact_generation"], generation["generation"])
                        self.assertEqual(event["loaded_module_generation"], refused[0]["event"]["loaded_module_generation"])
                        self.assertFalse(event["composition"]["authority_transferred"])
                        for step in event["composition"]["steps"]:
                            self.assertEqual(step["outcome"], "not_observed")
                            self.assertIsNone(step["event"]["success"])
                    print("NATIVE_COMPOSITION_EVIDENCE=" + json.dumps({
                        "transport": "codex-cli-app-server", "executor": "unified_exec",
                        "artifact_generation": generation["generation"],
                        "loaded_module_generation": refused[0]["event"]["loaded_module_generation"],
                        "denied_call_id": refused[0]["event"]["call_id"],
                        "safe_batches_completed": 4, "destructive_pre_denials": 1,
                        "post_denial_write_succeeded": True, "short_circuit_preserved": True,
                        "per_step_success_inferred": False, "external_model_requests": 0,
                    }, sort_keys=True), flush=True)
