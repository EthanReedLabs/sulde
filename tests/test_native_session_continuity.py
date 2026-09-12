"""Real candidate CLI/Hook/unified-exec; deterministic loopback model only."""
import json
import http.server
import io
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/release"))
import candidate_codex_plugin as candidate
from native_pretool_canary import NativeCanary


@unittest.skipIf(os.name == "nt", "Windows host acceptance is Windows-owned")
@unittest.skipUnless(shutil.which("codex"), "actual Codex CLI required")
class NativeSessionContinuityTests(unittest.TestCase):
    def test_denied_call_does_not_lock_the_following_ordinary_call(self):
        self.run_scenario(historical_release=False)

    def test_completed_historical_release_and_new_handoff_preserve_real_start(self):
        self.run_scenario(historical_release=True)

    def run_scenario(self, *, historical_release):
        with tempfile.TemporaryDirectory(prefix="sulde-native-continuity-") as temporary:
            slot = Path(temporary).resolve()
            installer, codex = candidate.installer, shutil.which("codex")
            prepared = installer._stage_artifact(slot / "artifact", platform="posix", runner=installer.run_command)
            generation = prepared.descriptor["delivery_generation"]["generation"]
            env = candidate._candidate_environment(slot, codex, candidate._python_identity(Path(sys.executable)))
            runner = candidate._bound_runner(env)
            externally_isolated = bool(os.environ.get("SULDE_ISOLATED_TEST_RUN_ID"))
            with candidate._process_environment(env):
                installed = installer._registry_add(codex, prepared.marketplace, runner,
                    expected_version=prepared.descriptor["delivery_generation"]["plugin_version"])
                kb = Path(env["SULDE_KB_HOME"])
                installer._install_launchers(installed, kb, runner, platform="posix")
                installer._smoke_installed(installed, kb, codex=codex,
                    expected_tree_sha256=prepared.plugin_tree_sha256, runner=runner)
                workspace = Path(env["SULDE_HOME"]) / "continuity-canary"
                workspace.mkdir()
                for arguments in (("init", "-b", "dev"), ("-c", "user.name=Canary", "-c", "user.email=canary@example.invalid", "commit", "--allow-empty", "-m", "fixture")):
                    result = runner(["git", "-C", str(workspace), *arguments], environment=env, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                target_workspace = workspace.parent / "continuity-task"
                result = runner(["git", "-C", str(workspace), "worktree", "add", "-b", "task/continuity", str(target_workspace)], environment=env, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                dev_workspace = workspace
                if historical_release:
                    workspace = dev_workspace.parent / "historical-task"
                    result = runner(["git", "-C", str(dev_workspace), "worktree", "add", "-b", "task/historical", str(workspace)], environment=env, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                preserved = dev_workspace / "must-survive.txt"
                initial_workspace_id = "sha256:" + hashlib.sha256(str(workspace).encode()).hexdigest()[:24]
                preserved.write_text("keep")
                guardian = Path(env["SULDE_HOME"]) / "bin/intent-guardian"
                fixture_results = []
                checkpoints = {}
                callbacks = {}
                original_server = http.server.ThreadingHTTPServer
                original_popen = subprocess.Popen
                def persistent_host_process(command, *arguments, **kwargs):
                    if historical_release and command[0] == codex and command[-1] == "app-server":
                        # The real host process is owned by the persistent repo;
                        # thread/start still selects the disposable task root.
                        # Never delete the operating-system cwd of a live host.
                        kwargs["cwd"] = dev_workspace
                    return original_popen(command, *arguments, **kwargs)
                def capture_server(address, handler):
                    original_post = handler.do_POST
                    def post(instance):
                        raw = instance.rfile.read(int(instance.headers.get("Content-Length", "0")))
                        body = json.loads(raw)
                        for item in body.get("input", []):
                            if (isinstance(item, dict) and item.get("type") == "function_call_output"
                                    and not any(old["call_id"] == item.get("call_id") for old in fixture_results)):
                                fixture_results.append({"call_id": item.get("call_id"),
                                                        "output": str(item.get("output", ""))[:1500]})
                        instance.rfile = io.BytesIO(raw)
                        callback = callbacks.pop(len(host.calls), None)
                        if callback is not None:
                            callback()
                        return original_post(instance)
                    handler.do_POST = post
                    return original_server(address, handler)
                with mock.patch.object(subprocess, "Popen", side_effect=persistent_host_process), \
                     mock.patch.object(http.server, "ThreadingHTTPServer", side_effect=capture_server), \
                     NativeCanary(codex, workspace, env,
                        externally_isolated=externally_isolated).start() as host:
                    contract, activation = candidate._activate_candidate_enforce_contract(
                        guardian, kb_home=kb, workspace=workspace, session=host.session,
                        environment=env, runner=runner)
                    control_env = {**env, "CODEX_THREAD_ID": host.session}
                    def control(action, *arguments):
                        return candidate._parse_json_result(runner(
                            [sys.executable, str(guardian), action, *arguments, "--provider", "codex",
                             "--session-id", host.session, "--contract", str(contract)],
                            environment=control_env, timeout=30), label=action)
                    probe = {}
                    source_contract = contract
                    def after_first_call():
                        nonlocal contract, source_contract, workspace
                        # Age real native observations out of the global tail,
                        # then emulate a legacy missing derived index only.
                        from host_observation_index import index_path
                        log = kb / "host-capabilities.jsonl"
                        with log.open("ab") as output:
                            padding = json.dumps({"provider": "codex", "session_id": "unrelated", "padding": "x" * 8192}).encode() + b"\n"
                            for _ in range(600):
                                output.write(padding)
                        before = hashlib.sha256(log.read_bytes()).hexdigest()
                        index_path(kb, "codex", host.session).unlink(missing_ok=True)
                        rebuilt = candidate._parse_json_result(runner([
                            sys.executable, "-B", str(guardian), "rebuild-host-observations",
                            "--provider", "codex", "--session-id", host.session,
                        ], environment=control_env, timeout=30), label="native observation migration")
                        self.assertEqual(rebuilt["status"], "complete")
                        self.assertGreaterEqual(rebuilt["retained_rows"], 4, rebuilt)
                        self.assertEqual(hashlib.sha256(log.read_bytes()).hexdigest(), before)
                        original_sources = {}
                        if historical_release:
                            # Produce the historical pair through the actual
                            # control CLI and Git readback, not fabricated proof.
                            old_workspace = workspace
                            for root, arguments in (
                                (old_workspace, ["add", "probe.py"]),
                                (old_workspace, ["-c", "user.name=Canary", "-c", "user.email=canary@example.invalid", "commit", "-m", "fixture data"]),
                                (dev_workspace, ["merge", "--ff-only", "task/historical"]),
                            ):
                                result = runner(["git", "-C", str(root), *arguments], environment=env, timeout=10)
                                self.assertEqual(result.returncode, 0, result.stderr)
                            released = control("release-completed-workspace", str(dev_workspace))
                            self.assertFalse(released["authority_transferred"])
                            closed_source = source_contract
                            source_contract = contract = Path(released["completion_contract"])
                            host.workspace = workspace = dev_workspace
                            for arguments in (["worktree", "remove", str(old_workspace)], ["branch", "-d", "task/historical"]):
                                result = runner(["git", "-C", str(dev_workspace), *arguments], environment=env, timeout=10)
                                self.assertEqual(result.returncode, 0, result.stderr)
                            finalized = control("finalize-workspace-cleanup")
                            self.assertEqual(finalized["status"], "complete")
                            from session_lifecycle_lineage import lineage_path
                            # Only a disposable derived projection is removed.
                            # Closed source and completed anchor remain intact.
                            lineage_path(kb, "codex", host.session).unlink()
                            original_sources[closed_source] = closed_source.read_bytes()
                        # Explicit target contract: generic prepare-proposal is
                        # intentionally routed to the current session contract.
                        # Do not accidentally revise the source while claiming
                        # an independently approved target.
                        from intent_guardian_parts.state import active_contract_path
                        contract = active_contract_path(kb, target_workspace)
                        created = runner([sys.executable, str(guardian), "create",
                            "--intent-id", "candidate-target", "--objective", "isolated local continuation",
                            "--accept", "preserve every production resource", "--workspace", str(target_workspace),
                            "--output", str(contract)], environment=control_env, timeout=30)
                        self.assertEqual(created.returncode, 0, created.stderr)
                        revised = runner([sys.executable, str(guardian), "propose-revision", str(contract),
                            "--objective", "isolated local continuation", "--accept", "preserve every production resource",
                            "--allow-path", "allowed.txt", "--reject", "no production write",
                            "--decision-route", "agent", "--intent-kind", "deterministic", "--risk", "low",
                            "--effect", "local_write", "--reversibility", "reversible", "--cost", "none",
                            "--rollback", "discard isolated candidate", "--provider", "codex", "--session-id", host.session,
                            "--apply-agent-eligible", "--agent-rationale", "bounded isolated local-write verification",
                            "--agent-evidence", "all targets belong to the disposable candidate fixture",
                        ], environment=control_env, timeout=30)
                        self.assertEqual(revised.returncode, 0, revised.stderr)
                        handoff = candidate._parse_json_result(runner([
                            sys.executable, str(guardian), "prepare-workspace-handoff", str(target_workspace),
                            "--contract", str(source_contract), "--home", str(kb),
                            "--provider", "codex", "--session-id", host.session,
                        ], environment=control_env, timeout=30), label="same-host workspace handoff")
                        self.assertEqual(handoff["status"], "bound", handoff)
                        self.assertFalse(handoff["authority_transferred"])
                        if historical_release:
                            original_sources[source_contract] = source_contract.read_bytes()
                            recovered = candidate._parse_json_result(runner([
                                sys.executable, "-B", str(guardian), "rebuild-host-observations",
                                "--provider", "codex", "--session-id", host.session, "--recover-history",
                            ], environment=control_env, timeout=30), label="native historical release migration")
                            self.assertEqual(recovered["historical_lineage"]["added_edges"], 1, recovered)
                            self.assertEqual(recovered["status"], "complete", recovered)
                            self.assertEqual({p: p.read_bytes() for p in original_sources}, original_sources)
                            checkpoints["historical_release"] = recovered["historical_lineage"]
                            checkpoints["historical_sources_unchanged"] = True
                        host.workspace = target_workspace
                        probe.update(control("pre-execution-proof-prepare"))
                        host.commands[-1] = probe["command"]
                        checkpoints["migration"] = rebuilt
                        checkpoints["handoff_authority_transferred"] = handoff["authority_transferred"]
                    def after_target_roundtrip():
                        source = "import json; from pathlib import Path; from host_capabilities import readiness_projection; print(json.dumps(readiness_projection(Path(" + repr(str(kb)) + "), provider='codex', session_id=" + repr(host.session) + ", workspace=" + repr(str(target_workspace)) + ")))"
                        result = runner([sys.executable, "-B", "-c", "import sys; sys.path.insert(0, " + repr(str(installed / "runtime/scripts/kb")) + "); " + source], environment=control_env, timeout=30)
                        projection = candidate._parse_json_result(result, label="fresh candidate lifecycle projection")
                        if projection["capabilities"]["session_context"]["status"] != "live_verified":
                            print("NATIVE_HISTORY_DIAGNOSTIC=" + json.dumps({"checkpoints": checkpoints,
                                "hooks": [{key: row["params"]["run"].get(key) for key in ("eventName", "status", "durationMs")}
                                          for row in host.notifications if row.get("method") == "hook/completed"]}, default=str), flush=True)
                        self.assertEqual(projection["capabilities"]["session_context"]["status"], "live_verified", projection)
                        self.assertEqual(projection["capabilities"]["session_context"]["runtime_binding"], "verified_workspace_continuity")
                        self.assertNotEqual(projection["capabilities"]["host_approval"]["status"], "live_verified")
                        checkpoints["workspace_lifecycle"] = projection["workspace_continuity"]
                        if historical_release:
                            self.assertEqual(projection["capabilities"]["session_context"]["carried_from_workspace_id"], initial_workspace_id, projection)
                    source = "from pathlib import Path; text='before'; Path('probe.py').write_text(text.replace('before', 'after'))"
                    commands = [
                        shlex.join([sys.executable, "-B", "-c", source]),
                        # rm -f is rejected by Codex before the Hook can run;
                        # non-recursive exact file cleanup is Agent-owned. Use
                        # explicit recursive semantics for a Guardian negative.
                        shlex.quote(str(guardian)) + " doctor --workspace . ; rm -r -- " + shlex.quote(str(preserved)),
                        "touch after-composition.txt",
                        shlex.join([sys.executable, "-B", "-c", "receiver.remove('unproved')"]),
                        "touch after-uncertainty.txt",
                        "false",  # replaced only after the real committed handoff
                    ]
                    if historical_release:
                        # Complete the real old turn first. Deleting the native
                        # turn's cwd mid-turn makes the host unable to spawn its
                        # Hooks, independently of Guardian's committed route.
                        host.execute(commands[:1])
                        after_first_call()
                        original_rpc = host.rpc
                        def target_turn_rpc(method, params):
                            if method == "turn/start":
                                params = {**params, "cwd": str(host.workspace)}
                            return original_rpc(method, params)
                        host.rpc = target_turn_rpc
                        callbacks[4] = after_target_roundtrip
                        commands[-1] = probe["command"]
                        # Preserve unique native call IDs across the two turns;
                        # the loopback server indexes by all prior responses.
                        items = host.execute(["already consumed"] * len(host.calls) + commands[1:])
                    else:
                        callbacks[1] = after_first_call
                        callbacks[3] = after_target_roundtrip
                        items = host.execute(commands)
                    self.assertTrue((workspace / "probe.py").is_file(), json.dumps({
                        "items": [row.get("params", {}).get("item") for row in host.notifications
                                  if row.get("method") == "item/completed"],
                        "methods": sorted({row.get("method") for row in host.notifications}),
                        "fixture_results": fixture_results,
                        "hooks": [{key: row["params"]["run"].get(key)
                                   for key in ("eventName", "status", "durationMs")}
                                  for row in host.notifications if row.get("method") == "hook/completed"],
                    }, default=str)[-18000:])
                    self.assertEqual((workspace / "probe.py").read_text(), "after")
                    self.assertEqual(preserved.read_text(), "keep")
                    self.assertTrue((target_workspace / "after-composition.txt").is_file())
                    self.assertTrue((target_workspace / "after-uncertainty.txt").is_file())
                    self.assertIn("workspace_lifecycle", checkpoints)
                    self.assertEqual(sum(item.get("exitCode") == 0 for item in items), 3)
                    denials = [row["params"]["run"] for row in host.notifications
                               if row.get("method") == "hook/completed"
                               and row["params"]["run"].get("eventName") == "preToolUse"
                               and row["params"]["run"].get("status") == "blocked"]
                    offset = 1 if historical_release else 0
                    # Diagnose exact host calls; a nonzero shell result is not
                    # evidence that PreToolUse denied it before execution.
                    self.assertEqual(
                        {row["id"].rsplit(":", 1)[-1] for row in denials},
                        {f"candidate_native_{i + offset}" for i in (1, 3, 5)},
                    )
                    proof = control("pre-execution-proof-finalize", "--probe-id", probe["probe_id"])
                    self.assertEqual(proof["artifact_generation"], generation)
                    self.assertEqual(proof["loaded_module_generation"], probe["loaded_module_generation"])
                    self.assertEqual(proof["started_call_id"], "candidate_native_6" if historical_release else "candidate_native_5")
                    self.assertFalse(os.path.lexists(probe["target"]))
                    print("NATIVE_CONTINUITY_EVIDENCE=" + json.dumps({
                        "transport": "codex-cli-app-server", "executor": "unified_exec",
                        "artifact_generation": generation, "loaded_module_generation": proof["loaded_module_generation"],
                        "proof_id": proof["proof_id"], "started_event_id": proof["started_event_id"],
                        "session_id": host.session, "data_write_succeeded": True,
                        "composition_denied_then_write_succeeded": True,
                        "uncertainty_denied_then_write_succeeded": True,
                        "destructive_pre_denied": True, "external_model_requests": 0,
                        "legacy_migration_and_same_session_handoff": checkpoints,
                    }, sort_keys=True), flush=True)
