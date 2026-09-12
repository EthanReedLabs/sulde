from __future__ import annotations

from contextlib import nullcontext
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
import venv
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "release" / "install_codex_plugin.py"
STAGER = ROOT / "scripts" / "release" / "stage_plugin.py"


def load_installer():
    spec = importlib.util.spec_from_file_location("test_codex_installer_module", INSTALLER)
    if spec is None or spec.loader is None:
        raise RuntimeError("install_codex_plugin.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def exercise_audited_codex_native_authority_roundtrip() -> dict[str, object]:
    """Exercise the production staging, sealing, readback, and preflight chain.

    This helper intentionally uses the exact audited executable and therefore is
    reserved for coordinator execution after any temporary worker projection has
    been restored. Every artifact and deployment descriptor stays under one
    temporary directory.
    """
    executable = os.environ.get("SULDE_TEST_CODEX_EXECUTABLE")
    if not executable:
        raise unittest.SkipTest("set SULDE_TEST_CODEX_EXECUTABLE for the real CLI gate")
    if not Path(executable).is_absolute():
        raise AssertionError("real CLI gate requires an explicit absolute executable")
    installer = load_installer()
    stager_spec = importlib.util.spec_from_file_location(
        "test_real_authority_stage_module", STAGER
    )
    if stager_spec is None or stager_spec.loader is None:
        raise RuntimeError("stage_plugin.py cannot be loaded")
    stager = importlib.util.module_from_spec(stager_spec)
    sys.modules[stager_spec.name] = stager
    stager_spec.loader.exec_module(stager)

    with tempfile.TemporaryDirectory(prefix="sulde-real-authority-roundtrip-") as name:
        root = Path(name)
        marketplace = root / "marketplace"
        kb_home = root / "kb-home"
        stager.stage_codex(ROOT, marketplace, "posix")
        installer._complete_staged_native_runtime(marketplace, platform="posix")
        plugin = marketplace / "plugins" / "sulde"
        sealed = installer._delivery_generation(
            plugin,
            expected_version=installer.plugin_version(),
        )
        with mock.patch.dict(os.environ, {"SULDE_TEST_MODE": "0"}, clear=False):
            deployment = installer._deployment_generation(
                plugin,
                marketplace,
                plugin_tree_sha256=installer.tree_digest(plugin),
                codex=executable,
                runner=installer.run_command,
            )
        installer._write_deployment_generation(kb_home, deployment)

        staged_runtime = plugin / "runtime" / "scripts" / "kb" / "agent-runtime.py"
        report = root / "unused-report.md"
        probe_source = "\n".join(
            (
                "import json, runpy, sys",
                "namespace = runpy.run_path(sys.argv[1])",
                "authority = namespace['load_installed_native_authority']()",
                "executable = authority['production_codex_executable']",
                "planned = [executable, 'exec', '--ignore-user-config', "
                "'--ignore-rules', '-C', sys.argv[2], '--sandbox', "
                "'workspace-write', '--ephemeral', '--skip-git-repo-check', "
                "'--json', '--output-last-message', sys.argv[3], '-']",
                "result = namespace['codex_capability_preflight'](",
                "    executable,",
                "    namespace['codex_permission_config'](['scripts/kb/agent-runtime.py']),",
                "    test_mode=False,",
                "    planned_command=planned,",
                "    worktree=namespace['Path'](sys.argv[2]),",
                "    installed_authority=authority,",
                ")",
                "print(json.dumps({'authority': authority, 'result': result}, "
                "sort_keys=True, separators=(',', ':')))",
            )
        )
        environment = os.environ.copy()
        # A real host probe must not export the test-mode sentinel at all.
        # SessionStart hooks intentionally key off its presence, so the string
        # "0" would still select the synthetic path and make app-server exit
        # cleanly before emitting its initialize response.
        environment.pop("SULDE_TEST_MODE", None)
        environment["SULDE_KB_HOME"] = str(kb_home)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        command = [
            sys.executable,
            "-I",
            "-B",
            "-c",
            probe_source,
            str(staged_runtime),
            str(ROOT),
            str(report),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=120,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr or completed.stdout)
        observed = json.loads(completed.stdout)
        authority = observed["authority"]
        if authority != deployment["native_runtime_authority"]:
            raise AssertionError("staged runtime authority readback changed sealed bytes")
        if observed["result"].get("help_observation_sha256") != authority.get(
            "codex_help_observation_sha256"
        ):
            raise AssertionError("runtime preflight did not consume sealed help authority")

        drifted = json.loads(json.dumps(deployment))
        drifted_authority = drifted["native_runtime_authority"]
        drifted_authority["broker_sha256"] = hashlib.sha256(
            b"injected broker authority drift"
        ).hexdigest()
        unsigned = dict(drifted_authority)
        unsigned.pop("authority_sha256")
        drifted_authority["authority_sha256"] = hashlib.sha256(
            installer._canonical_json_bytes(unsigned)
        ).hexdigest()
        drifted["native_runtime_authority_sha256"] = drifted_authority[
            "authority_sha256"
        ]
        installer._write_deployment_generation(kb_home, drifted)
        rejected = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=120,
            check=False,
        )
        if rejected.returncode == 0 or "digest drifted" not in (
            rejected.stdout + rejected.stderr
        ):
            raise AssertionError(
                "re-signed broker authority drift did not fail closed: "
                + rejected.stdout
                + rejected.stderr
            )
        return {
            "authority": authority,
            "preflight": observed["result"],
            "staged_runtime": str(staged_runtime.relative_to(root)),
            "field_drift_rejected": True,
        }


FAKE_CODEX = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import sys

state_path = Path(os.environ["FAKE_CODEX_STATE"])
try:
    state = json.loads(state_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    state = {"marketplace": None, "installed": None, "version": None, "effects": {}}
state.setdefault("effects", {})

def effect(name):
    state["effects"][name] = state["effects"].get(name, 0) + 1

args = sys.argv[1:]
if args == ["plugin", "marketplace", "list"]:
    print("MARKETPLACE          ROOT")
    if state.get("marketplace"):
        print("sulde-local          " + state["marketplace"])
elif args[:3] == ["plugin", "marketplace", "add"]:
    value = str(Path(args[3]).resolve())
    if state.get("marketplace") != value:
        effect("marketplace_add")
    state["marketplace"] = value
    print(json.dumps({"marketplaceName": "sulde-local", "installedRoot": state["marketplace"]}))
elif args[:3] == ["plugin", "marketplace", "remove"]:
    if state.get("marketplace") is not None:
        effect("marketplace_remove")
    state["marketplace"] = None
    print(json.dumps({"marketplaceName": "sulde-local", "installedRoot": None}))
elif args[:2] == ["plugin", "add"]:
    root = Path(state["marketplace"])
    source = root / "plugins" / "sulde"
    descriptor = json.loads((source / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    prune_path = os.environ.get("FAKE_CODEX_PRUNE_PATH")
    if prune_path:
        prune = Path(prune_path)
        if prune.is_symlink():
            prune.unlink()
        elif prune.exists():
            shutil.rmtree(prune)
    cache = Path(os.environ["CODEX_HOME"]) / "plugins/cache/sulde-local/sulde" / descriptor["version"]
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.is_symlink():
        cache.unlink()
    elif cache.exists():
        shutil.rmtree(cache)
    shutil.copytree(source, cache)
    if os.environ.get("FAKE_CODEX_TAMPER") == "1":
        (cache / "scripts" / "pre-tool-use.py").unlink()
    state["installed"] = str(cache)
    state["version"] = descriptor["version"]
    effect("plugin_add")
    print(json.dumps({
        "pluginId": "sulde@sulde-local",
        "version": state["version"],
        "installedPath": state["installed"],
    }))
elif args[:2] == ["plugin", "remove"]:
    if state.get("installed"):
        effect("plugin_remove")
        installed = Path(state["installed"])
        if installed.is_symlink():
            installed.unlink()
        else:
            shutil.rmtree(installed, ignore_errors=True)
    state["installed"] = None
    state["version"] = None
    print(json.dumps({"pluginId": "sulde@sulde-local"}))
elif args == ["plugin", "list"]:
    if state.get("installed"):
        launcher_manifest = (
            Path(os.environ["SULDE_KB_HOME"]) / "bin/.sulde-launchers.json"
        )
        if (
            os.environ.get("FAKE_CODEX_REFRESH_SYSTEM_SKILLS") == "1"
            and launcher_manifest.is_file()
        ):
            system_scripts = (
                Path(os.environ["CODEX_HOME"])
                / "skills/.system/plugin-creator/scripts"
            )
            for name in ("validate_plugin.py", "update_plugin_cachebuster.py"):
                (system_scripts / name).write_text(
                    "# host-refreshed system skill for " + name + "\n",
                    encoding="utf-8",
                )
        print("PLUGIN             STATUS              VERSION                     PATH")
        source = str(Path(state["marketplace"]) / "plugins/sulde") if state.get("marketplace") else state["installed"]
        print("sulde@sulde-local  installed, enabled  " + state["version"] + "  " + source)
elif args == ["app-server", "--listen", "stdio://"]:
    required_events = (
        "preToolUse",
        "permissionRequest",
        "postToolUse",
        "sessionStart",
        "userPromptSubmit",
        "stop",
    )
    for raw_line in sys.stdin:
        request = json.loads(raw_line)
        method = request.get("method")
        if method == "initialize":
            print(json.dumps({"id": request["id"], "result": {}}), flush=True)
        elif method == "hooks/list":
            cwd = request["params"]["cwds"][0]
            hooks = []
            for event_name in required_events:
                if (
                    event_name == "preToolUse"
                    and os.environ.get("FAKE_CODEX_MISSING_PRE_TOOL_USE") == "1"
                ):
                    continue
                trust_status = "trusted"
                if event_name == "preToolUse":
                    trust_status = os.environ.get(
                        "FAKE_CODEX_PRE_TOOL_TRUST_STATUS", "trusted"
                    )
                hooks.append({
                    "key": "plugin:sulde:" + event_name,
                    "eventName": event_name,
                    "handlerType": "command",
                    "async": False,
                    "matcher": ".*",
                    "timeoutSec": 120,
                    "statusMessage": None,
                    "additionalContextLimit": None,
                    "sourcePath": str(Path(state["marketplace"]) / "plugins/sulde/hooks/hooks.json"),
                    "source": "plugin",
                    "pluginId": "sulde@sulde-local",
                    "displayOrder": len(hooks),
                    "enabled": True,
                    "isManaged": False,
                    "currentHash": "sha256:" + event_name,
                    "trustStatus": trust_status,
                })
            print(json.dumps({
                "id": request["id"],
                "result": {"data": [{
                    "cwd": cwd,
                    "hooks": hooks,
                    "warnings": [],
                    "errors": [],
                }]},
            }), flush=True)
    raise SystemExit(0)
elif args == ["mcp", "get", "sulde_kb", "--json"]:
    if not state.get("installed"):
        raise SystemExit(1)
    installed = Path(state["installed"]).resolve()
    manifest = json.loads((installed / ".mcp.json").read_text(encoding="utf-8"))
    server = manifest["mcpServers"]["sulde_kb"]
    projected_cwd = installed
    if os.environ.get("FAKE_CODEX_MCP_CWD_DRIFT") == "1":
        projected_cwd = installed / "literal-placeholder"
    print(json.dumps({
        "name": "sulde_kb",
        "enabled": True,
        "disabled_reason": None,
        "transport": {
            "type": "stdio",
            "command": server["command"],
            "args": server.get("args", []),
            "env": None,
            "env_vars": [],
            "cwd": str(projected_cwd),
        },
    }))
else:
    print("unsupported fake codex command: " + repr(args), file=sys.stderr)
    raise SystemExit(2)
state_path.write_text(json.dumps(state), encoding="utf-8")
'''


FAKE_LAUNCHCTL = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import plistlib
import sys

state_path = Path(os.environ["FAKE_LAUNCHCTL_STATE"])
try:
    labels = json.loads(state_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    labels = json.loads(os.environ.get("FAKE_LAUNCHCTL_LABELS", "[]"))
args = sys.argv[1:]
if args == ["list"]:
    for label in labels:
        print(f"-\t0\t{label}")
elif len(args) == 2 and args[0] == "remove":
    labels = [label for label in labels if label != args[1]]
    state_path.write_text(json.dumps(labels), encoding="utf-8")
elif len(args) == 2 and args[0] in {"load", "unload"}:
    with Path(args[1]).open("rb") as handle:
        label = plistlib.load(handle)["Label"]
    if args[0] == "load" and label not in labels:
        labels.append(label)
    elif args[0] == "unload":
        labels = [value for value in labels if value != label]
    state_path.write_text(json.dumps(sorted(labels)), encoding="utf-8")
else:
    print("unsupported fake launchctl command", file=sys.stderr)
    raise SystemExit(2)
'''


FAKE_PS = r'''#!/usr/bin/env python3
import os
print(os.environ.get("FAKE_PS_OUTPUT", ""), end="")
'''


@unittest.skipIf(os.name == "nt", "fixture uses a POSIX executable shim")
class CodexPluginInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fixture_home = self.root / "home"
        self.fixture_home.mkdir()
        self.fixture_tmp = self.root / "tmp"
        self.fixture_tmp.mkdir()
        self.codex_home = self.root / "codex-home"
        self.environment_patch = mock.patch.dict(
            os.environ,
            {
                "HOME": str(self.fixture_home),
                "CODEX_HOME": str(self.codex_home),
                "SULDE_KB_HOME": str(self.root / "kb-home"),
                "SULDE_LAUNCHAGENTS_DIR": str(
                    self.root / "Library" / "LaunchAgents"
                ),
                "CLAUDE_CONFIG_DIR": str(self.root / "claude-config"),
                "XDG_CACHE_HOME": str(self.root / "xdg-cache"),
                "TMPDIR": str(self.fixture_tmp),
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            clear=True,
        )
        self.environment_patch.start()
        self.fake = self.root / "fake-codex"
        self.fake.write_text(textwrap.dedent(FAKE_CODEX), encoding="utf-8")
        self.fake.chmod(0o755)
        self.fake_launchctl = self.root / "fake-launchctl"
        self.fake_launchctl.write_text(
            textwrap.dedent(FAKE_LAUNCHCTL), encoding="utf-8"
        )
        self.fake_launchctl.chmod(0o755)
        self.fake_ps = self.root / "fake-ps"
        self.fake_ps.write_text(textwrap.dedent(FAKE_PS), encoding="utf-8")
        self.fake_ps.chmod(0o755)
        self.state = self.root / "state.json"
        self.artifact = self.root / "artifact" / "codex"
        self.kb_home = self.root / "kb-home"
        self.artifact_template = self.root / "artifact-template"
        system_scripts = (
            self.codex_home / "skills/.system/plugin-creator/scripts"
        )
        system_scripts.mkdir(parents=True)
        for name in ("validate_plugin.py", "update_plugin_cachebuster.py"):
            (system_scripts / name).write_text(
                f"# trusted installer fixture for {name}\n",
                encoding="utf-8",
            )

    def tearDown(self) -> None:
        self.environment_patch.stop()
        self.temp.cleanup()

    def test_installer_imports_shared_codex_cli_authority(self) -> None:
        installer = load_installer()
        contract = sys.modules[installer.successful_version_identity.__module__]
        self.assertEqual(installer.AUDITED_CODEX_VERSION, "codex-cli 0.154.0")
        self.assertEqual(
            installer.DEFAULT_CODEX_EXECUTABLE,
            "codex",
        )
        self.assertIs(
            installer.successful_version_identity,
            contract.successful_version_identity,
        )
        self.assertIs(
            installer.canonical_codex_help_observation,
            contract.canonical_codex_help_observation,
        )
        self.assertIs(
            installer.codex_probe_environment,
            contract.codex_probe_environment,
        )
        self.assertIs(installer.codex_probe_spec, contract.codex_probe_spec)

    def test_plugin_mcp_route_rejects_unexpanded_or_escaping_commands(self) -> None:
        installer = load_installer()
        source = ROOT / "integrations/codex/plugins/sulde"
        route = installer._plugin_mcp_stdio_route(source, platform="posix")
        self.assertEqual(route["command"], ["./scripts/run-mcp.sh"])
        self.assertEqual(Path(route["cwd"]), source.resolve())

        with tempfile.TemporaryDirectory() as temp_dir:
            plugin = Path(temp_dir) / "sulde"
            shutil.copytree(source, plugin)
            manifest_path = plugin / ".mcp.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["mcpServers"]["sulde_kb"].pop("cwd")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(installer.InstallError, "plugin-relative.*cwd"):
                installer._plugin_mcp_stdio_route(plugin, platform="posix")

        for invalid in (
            "${PLUGIN_ROOT}/scripts/run-mcp.sh",
            "./../scripts/run-mcp.sh",
            "/tmp/run-mcp.sh",
        ):
            with tempfile.TemporaryDirectory() as temp_dir, self.subTest(command=invalid):
                plugin = Path(temp_dir) / "sulde"
                shutil.copytree(source, plugin)
                manifest_path = plugin / ".mcp.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["mcpServers"]["sulde_kb"]["command"] = invalid
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(
                    installer.InstallError,
                    "contained ./scripts/run-mcp.sh.*plugin-relative.*cwd",
                ):
                    installer._plugin_mcp_stdio_route(plugin, platform="posix")

    def test_codex_plugin_mcp_projection_rejects_host_cwd_drift(self) -> None:
        installer = load_installer()
        source = ROOT / "integrations" / "codex" / "plugins" / "sulde"
        declared_route = installer._plugin_mcp_stdio_route(source, platform="posix")

        def projected(cwd: Path):
            payload = {
                "name": "sulde_kb",
                "enabled": True,
                "transport": {
                    "type": "stdio",
                    "command": "./scripts/run-mcp.sh",
                    "args": [],
                    "cwd": str(cwd),
                },
            }
            return installer.CommandResult(
                ("codex", "mcp", "get", "sulde_kb", "--json"),
                0,
                json.dumps(payload),
                "",
            )

        accepted = installer._codex_plugin_mcp_projection(
            "codex",
            source,
            declared_route=declared_route,
            runner=lambda *args, **kwargs: projected(source.resolve()),
        )
        self.assertEqual(Path(accepted["cwd"]), source.resolve())
        with self.assertRaisesRegex(installer.InstallError, "plugin root"):
            installer._codex_plugin_mcp_projection(
                "codex",
                source,
                declared_route=declared_route,
                runner=lambda *args, **kwargs: projected(source / "wrong"),
            )

    def test_codex_hook_trust_projection_requires_every_runnable_hook(self) -> None:
        installer = load_installer()
        cwd = self.root / "workspace"
        cwd.mkdir()

        def payload(*, pre_status: str = "trusted", omit_pre: bool = False):
            hooks = []
            for event_name in installer.REQUIRED_CODEX_HOOK_EVENTS:
                if omit_pre and event_name == "preToolUse":
                    continue
                hooks.append(
                    {
                        "key": f"plugin:sulde:{event_name}",
                        "eventName": event_name,
                        "handlerType": "command",
                        "source": "plugin",
                        "pluginId": installer.PLUGIN_SELECTOR,
                        "enabled": True,
                        "currentHash": f"sha256:{event_name}",
                        "trustStatus": (
                            pre_status if event_name == "preToolUse" else "trusted"
                        ),
                    }
                )
            return {
                "data": [
                    {
                        "cwd": str(cwd),
                        "hooks": hooks,
                        "warnings": [],
                        "errors": [],
                    }
                ]
            }

        ready = installer._codex_hook_trust_projection(payload(), cwd=cwd)
        self.assertEqual(ready["status"], "ready")
        self.assertFalse(ready["trust_write_performed"])
        self.assertEqual(ready["missing_events"], [])
        self.assertEqual(ready["unrunnable_events"], [])
        self.assertEqual(ready["post_tool_hook_owner_count"], 1)

        concurrent = payload()
        concurrent["data"][0]["hooks"].append(
            {
                "key": "plugin:other:postToolUse",
                "eventName": "postToolUse",
                "handlerType": "command",
                "source": "plugin",
                "pluginId": "other@marketplace",
                "enabled": True,
                "currentHash": "sha256:other",
                "trustStatus": "trusted",
            }
        )
        concurrent_projection = installer._codex_hook_trust_projection(
            concurrent, cwd=cwd
        )
        self.assertEqual(concurrent_projection["status"], "ready")
        self.assertEqual(concurrent_projection["post_tool_hook_owner_count"], 2)
        self.assertEqual(
            [
                row["plugin_id"]
                for row in concurrent_projection["post_tool_hook_owners"]
            ],
            [installer.PLUGIN_SELECTOR, "other@marketplace"],
        )

        duplicate = payload()
        duplicate["data"][0]["hooks"].append(
            dict(
                next(
                    row
                    for row in duplicate["data"][0]["hooks"]
                    if row["eventName"] == "postToolUse"
                )
            )
        )
        duplicate_projection = installer._codex_hook_trust_projection(
            duplicate, cwd=cwd
        )
        self.assertEqual(duplicate_projection["status"], "review_required")
        self.assertEqual(duplicate_projection["duplicate_events"], ["postToolUse"])

        untrusted = installer._codex_hook_trust_projection(
            payload(pre_status="untrusted"), cwd=cwd
        )
        self.assertEqual(untrusted["status"], "review_required")
        self.assertEqual(untrusted["unrunnable_events"], ["preToolUse"])

        missing = installer._codex_hook_trust_projection(
            payload(omit_pre=True), cwd=cwd
        )
        self.assertEqual(missing["status"], "review_required")
        self.assertEqual(missing["missing_events"], ["preToolUse"])

        wire_drift = payload()
        wire_drift["data"][0]["hooks"][0]["eventName"] = "pre_tool_use"
        drifted = installer._codex_hook_trust_projection(wire_drift, cwd=cwd)
        self.assertEqual(drifted["status"], "review_required")
        self.assertEqual(drifted["missing_events"], ["preToolUse"])

    def test_installer_cli_smoke_uses_successful_stdout_identity_only(self) -> None:
        installer = load_installer()
        contract = sys.modules[installer.successful_version_identity.__module__]
        probe_calls = []

        def runner(command, **kwargs):
            rendered = tuple(str(value) for value in command)
            arguments = rendered[1:]
            probe_calls.append(kwargs)
            if arguments == ("--version",):
                return installer.CommandResult(
                    rendered,
                    0,
                    installer.AUDITED_CODEX_VERSION + "\n",
                    "non-identity diagnostic\n",
                )
            if arguments == ("--help",):
                return installer.CommandResult(
                    rendered,
                    0,
                    "--config --strict-config\n",
                    contract.CODEX_PATH_ALIAS_PERMISSION_WARNING,
                )
            if arguments == ("exec", "--help"):
                return installer.CommandResult(
                    rendered,
                    0,
                    "--ignore-user-config --ignore-rules "
                    "--dangerously-bypass-hook-trust --config --strict-config\n",
                    "",
                )
            if arguments == ("app-server", "--help"):
                return installer.CommandResult(
                    rendered, 0, "--config --strict-config --listen\n", ""
                )
            return installer.CommandResult(rendered, 0, "", "")

        with mock.patch.object(
            installer,
            "_app_server_initialize_handshake",
            return_value=installer.CommandResult(("codex",), 0, "", ""),
        ):
            observed = installer._codex_cli_installed_smoke(
                self.fake,
                runner,
            )
        self.assertEqual(observed["version"], installer.AUDITED_CODEX_VERSION)
        self.assertEqual(len(probe_calls), 5)
        self.assertTrue(
            all(call.get("environment") is not None for call in probe_calls)
        )
        for call in probe_calls:
            self.assertEqual(call.get("input_text"), "")
            environment = call["environment"]
            self.assertEqual(environment["TERM"], "dumb")
            self.assertEqual(environment["NO_COLOR"], "1")
            self.assertEqual(environment["CLICOLOR_FORCE"], "0")

        canonical, expected_digest = contract.canonical_codex_help_observation(
            (
                (0, "--config --strict-config\n", ""),
                (
                    0,
                    "--ignore-user-config --ignore-rules "
                    "--dangerously-bypass-hook-trust --config --strict-config\n",
                    "",
                ),
                (0, "--config --strict-config --listen\n", ""),
            )
        )
        self.assertEqual(len(canonical), 3)
        self.assertEqual(observed["help_observation_sha256"], expected_digest)

        for returncode, stdout in (
            (0, "codex-cli 0.149.1\n"),
            (0, "codex-cli 0.151.0\n"),
            (0, "codex-cli 0.152.0\n"),
            (0, "codex-cli 0.153.0\n"),
            (0, "codex-cli 0.153.4\n"),
            (0, "codex-cli 0.155.0\n"),
            (0, "wrapper codex-cli 0.154.0\n"),
            (0, "codex-cli 0.154.0 future\n"),
            (0, " codex-cli 0.154.0\n"),
            (0, "codex-cli 0.154.0\n\n"),
            (1, installer.AUDITED_CODEX_VERSION + "\n"),
        ):
            with self.subTest(returncode=returncode, stdout=stdout):
                calls = 0

                def rejected_runner(command, **_kwargs):
                    nonlocal calls
                    calls += 1
                    return installer.CommandResult(
                        tuple(str(value) for value in command),
                        returncode,
                        stdout,
                        "diagnostic\n",
                    )

                with self.assertRaisesRegex(
                    installer.InstallError,
                    "exactly codex-cli 0.154.0",
                ):
                    installer._codex_cli_installed_smoke(
                        self.fake,
                        rejected_runner,
                    )
                self.assertEqual(calls, 1)

    def test_installer_cli_smoke_rejects_noncanonical_help_diagnostics_and_bytes(self) -> None:
        installer = load_installer()
        contract = sys.modules[installer.successful_version_identity.__module__]
        base = {
            ("--version",): installer.CommandResult(
                ("codex", "--version"),
                0,
                installer.AUDITED_CODEX_VERSION + "\n",
                "",
            ),
            ("--help",): installer.CommandResult(
                ("codex", "--help"), 0, "--config --strict-config\n", ""
            ),
            ("exec", "--help"): installer.CommandResult(
                ("codex", "exec", "--help"),
                0,
                "--ignore-user-config --ignore-rules --dangerously-bypass-hook-trust "
                "--config --strict-config\n",
                "",
            ),
            ("app-server", "--help"): installer.CommandResult(
                ("codex", "app-server", "--help"),
                0,
                "--config --strict-config --listen\n",
                "",
            ),
        }
        for label, replacement in (
            (
                "warning-extra-character",
                installer.CommandResult(
                    ("codex", "--help"),
                    0,
                    "--config --strict-config\n",
                    contract.CODEX_PATH_ALIAS_PERMISSION_WARNING + "x",
                ),
            ),
            (
                "second-diagnostic",
                installer.CommandResult(
                    ("codex", "--help"),
                    0,
                    "--config --strict-config\n",
                    contract.CODEX_PATH_ALIAS_PERMISSION_WARNING + "unknown\n",
                ),
            ),
            (
                "unknown-stderr",
                installer.CommandResult(
                    ("codex", "--help"),
                    0,
                    "--config --strict-config\n",
                    "unknown\n",
                ),
            ),
            (
                "ansi-stdout",
                installer.CommandResult(
                    ("codex", "--help"),
                    0,
                    "\x1b[31m--config --strict-config\n",
                    "",
                ),
            ),
            (
                "c1-csi-stdout",
                installer.CommandResult(
                    ("codex", "--help"),
                    0,
                    "\u009b31m--config --strict-config\n",
                    "",
                ),
            ),
            (
                "carriage-return-stdout",
                installer.CommandResult(
                    ("codex", "--help"),
                    0,
                    "--config --strict-config\n\r",
                    "",
                ),
            ),
            (
                "backspace-stdout",
                installer.CommandResult(
                    ("codex", "--help"),
                    0,
                    "--config --strict-config\n\b",
                    "",
                ),
            ),
            (
                "nul-stdout",
                installer.CommandResult(
                    ("codex", "--help"),
                    0,
                    "--config --strict-config\n\x00",
                    "",
                ),
            ),
            (
                "nonzero",
                installer.CommandResult(
                    ("codex", "--help"),
                    3,
                    "--config --strict-config\n",
                    "",
                ),
            ),
        ):
            responses = dict(base)
            responses[("--help",)] = replacement

            def runner(command, **_kwargs):
                return responses[tuple(str(value) for value in command)[1:]]

            with (
                self.subTest(label=label),
                self.assertRaisesRegex(installer.InstallError, "help surface drifted"),
            ):
                installer._codex_cli_installed_smoke(
                    self.fake,
                    runner,
                )

    def run_installer(
        self,
        *,
        tamper: bool = False,
        prune_path: Path | None = None,
        loaded_labels: tuple[str, ...] = (),
        failpoint: str | None = None,
        ps_output: str = "",
        hook_trust_status: str = "trusted",
        prepare_artifact: bool = True,
        initialize_launchctl_state: bool = True,
        refresh_system_skills: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if prepare_artifact:
            self.prepare_artifact()
        environment = {
            "HOME": str(self.fixture_home),
            "CODEX_HOME": str(self.codex_home),
            "SULDE_KB_HOME": str(self.kb_home),
            "SULDE_LAUNCHAGENTS_DIR": str(
                self.root / "Library" / "LaunchAgents"
            ),
            "CLAUDE_CONFIG_DIR": str(self.root / "claude-config"),
            "XDG_CACHE_HOME": str(self.root / "xdg-cache"),
            "TMPDIR": str(self.fixture_tmp),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "FAKE_CODEX_STATE": str(self.state),
            "SULDE_TEST_MODE": "1",
            "SULDE_LAUNCHCTL": str(self.fake_launchctl),
            "SULDE_PS": str(self.fake_ps),
            "FAKE_PS_OUTPUT": ps_output,
            "FAKE_LAUNCHCTL_LABELS": json.dumps(loaded_labels),
            "FAKE_CODEX_PRE_TOOL_TRUST_STATUS": hook_trust_status,
        }
        if prepare_artifact:
            environment["SULDE_TEST_PREPARED_ARTIFACT"] = "1"
        launchctl_state = self.root / "launchctl-state.json"
        if initialize_launchctl_state:
            launchctl_state.write_text(json.dumps(loaded_labels), encoding="utf-8")
        environment["FAKE_LAUNCHCTL_STATE"] = str(launchctl_state)
        if tamper:
            environment["FAKE_CODEX_TAMPER"] = "1"
        if prune_path is not None:
            environment["FAKE_CODEX_PRUNE_PATH"] = str(prune_path)
        if failpoint is not None:
            environment["SULDE_INSTALL_FAILPOINT"] = failpoint
        if refresh_system_skills:
            environment["FAKE_CODEX_REFRESH_SYSTEM_SKILLS"] = "1"
        return subprocess.run(
            [
                sys.executable,
                str(INSTALLER),
                "--artifact-root",
                str(self.artifact),
                "--kb-home",
                str(self.kb_home),
                "--codex",
                str(self.fake),
                "--platform",
                "posix",
                "--json",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=120,
            check=False,
        )

    def prepare_artifact(self) -> None:
        if not (self.kb_home / "venv").is_dir():
            self.kb_home.mkdir(parents=True, exist_ok=True)
            venv.EnvBuilder(with_pip=False, system_site_packages=True).create(self.kb_home / "venv")
        if self.artifact.exists():
            return
        if not self.artifact_template.exists():
            spec = importlib.util.spec_from_file_location(
                "test_stage_codex_fixture", ROOT / "scripts/release/stage_plugin.py"
            )
            if spec is None or spec.loader is None:
                raise RuntimeError("stage_plugin.py cannot be loaded")
            stage = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = stage
            spec.loader.exec_module(stage)
            entries = []
            for source in sorted(ROOT.rglob("*")):
                if not source.is_file() or source.is_symlink():
                    continue
                relative = source.relative_to(ROOT)
                if (
                    relative.parts[0] in {".git", ".codex-agent"}
                    or "__pycache__" in relative.parts
                    or relative.suffix.casefold() == ".pyc"
                ):
                    continue
                mode = 0o100755 if source.stat().st_mode & stat.S_IXUSR else 0o100644
                entries.append(stage.GitEntry(relative, mode))
            with mock.patch.object(stage, "release_entries", return_value=entries):
                stage.stage_codex(ROOT, self.artifact_template, "posix")
            configurator = (
                self.artifact_template
                / "plugins/sulde/runtime/scripts/kb/configure-global.py"
            )
            source = configurator.read_text(encoding="utf-8")
            source = source.replace(
                'cache = Path.home() / ".claude/plugins/cache/sulde/sulde-cc"',
                'cache = Path("/test-fixture/no-claude-cache")',
            )
            configurator.write_text(source, encoding="utf-8")
            installer = load_installer()
            installer._complete_staged_native_runtime(
                self.artifact_template, platform="posix"
            )
        self.artifact.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.artifact_template, self.artifact)

    def test_install_atomically_verifies_scheduler_generation_before_return(self) -> None:
        completed = self.run_installer()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "generation_verified")

        self.assertEqual(
            result["operational_status"],
            "scheduler_ready_live_host_unverified",
        )
        self.assertFalse(result["operational_ready"])
        self.assertTrue(result["launcher_contract"]["healthy"])
        self.assertTrue(result["launcher_contract"]["command_effects"]["healthy"])
        self.assertEqual(
            result["launcher_contract"]["command_effects"]["command_count"],
            3,
        )
        self.assertTrue(result["global_rules"]["dispatch_gate"])
        self.assertTrue(result["smoke"]["intent_context"])
        self.assertTrue(result["smoke"]["live_session_hook_bridge"])
        self.assertTrue(result["smoke"]["codex_dispatch_native"])
        self.assertTrue(result["smoke"]["proposal_control_round_trip"])
        self.assertTrue(result["smoke"]["native_permission_bridge"])
        self.assertTrue(result["smoke"]["native_decision_preview"])
        self.assertTrue(result["smoke"]["fixed_text_authority_rejected"])
        self.assertTrue(result["smoke"]["synthetic_authority_rejected"])
        self.assertIsNone(result["smoke"]["approval_actor"])
        self.assertEqual(result["smoke"]["observation_source"], "synthetic_smoke")
        self.assertEqual(
            result["smoke"]["host_readiness"]["interactive_status"],
            "synthetic_only",
        )
        self.assertEqual(
            result["smoke"]["host_readiness"]["supervision_status"],
            "synthetic_only",
        )
        self.assertEqual(
            result["smoke"]["host_readiness"]["capabilities"]["host_approval"][
                "status"
            ],
            "unobserved",
        )
        self.assertFalse(result["smoke"]["host_readiness"]["approval_required"])
        self.assertFalse(
            result["smoke"]["host_readiness"]["capabilities"]["host_approval"][
                "required_for_interactive"
            ]
        )
        self.assertTrue(result["smoke"]["mcp_write_denied"])
        self.assertEqual(
            result["smoke"]["mcp_initialize"]["packaged_server"]["server_name"],
            "sulde-kb",
        )
        self.assertEqual(
            result["smoke"]["mcp_initialize"]["plugin_manifest"]["server_name"],
            "sulde-kb",
        )
        self.assertEqual(
            result["smoke"]["mcp_initialize"]["plugin_manifest"][
                "host_projection"
            ]["command"],
            ["./scripts/run-mcp.sh"],
        )
        self.assertEqual(
            Path(
                result["smoke"]["mcp_initialize"]["plugin_manifest"][
                    "host_projection"
                ]["cwd"]
            ),
            Path(result["installed_path"]).resolve(),
        )
        self.assertTrue(result["smoke"]["plugin_list_verified"])
        self.assertEqual(result["smoke"]["hook_trust"]["status"], "ready")
        self.assertFalse(
            result["smoke"]["hook_trust"]["trust_write_performed"]
        )
        self.assertEqual(
            result["smoke"]["native_runtime_authority_load"],
            {
                "authority_load_verified": False,
                "module_load_verified": True,
                "authority_sha256": result["deployment_generation"][
                    "native_runtime_authority_sha256"
                ],
                "runtime_tree_sha256": result["deployment_generation"][
                    "runtime_tree_sha256"
                ],
                "bytecode_free": True,
            },
        )
        self.assertEqual(
            result["smoke"]["plugin_tree_sha256"],
            result["staged_plugin_tree_sha256"],
        )
        timings = result["install_timings_seconds"]
        self.assertEqual(
            set(timings),
            {
                "host_preflight",
                "deployment_lock_and_recovery_scan",
                "artifact_stage_and_validation",
                "scheduler_and_home_preflight",
                "snapshot_and_prepare",
                "registry_switch_and_readback",
                "launcher_rules_and_smoke",
                "deployment_and_scheduler",
                "postconditions_and_commit",
                "locked_total",
                "total",
            },
        )
        self.assertTrue(
            all(
                isinstance(value, (int, float)) and value >= 0
                for value in timings.values()
            )
        )
        self.assertTrue(result["restart_required"])
        self.assertTrue(result["hook_restart_required"])
        self.assertFalse(result["hook_hot_rebind_available"])
        self.assertIn("fresh session", result["hook_restart_reason"])
        self.assertTrue(result["skill_catalog_restart_required"])
        self.assertEqual(
            result["ready_scope"],
            "atomic_generation_ready_live_host_unverified",
        )
        self.assertEqual(
            result["host_capabilities"]["artifact"]["status"],
            "artifact_ready",
        )
        self.assertEqual(
            result["host_capabilities"]["synthetic"]["status"],
            "synthetic_only",
        )
        self.assertEqual(
            result["host_capabilities"]["live"]["status"],
            "live_unverified",
        )
        self.assertEqual(result["interactive_supervision"]["status"], "live_unverified")
        self.assertFalse(result["interactive_supervision"]["live_host_hook_verified"])
        self.assertTrue(result["interactive_supervision"]["synthetic_round_trip"])
        self.assertTrue(
            result["interactive_supervision"]["synthetic_authority_rejected"]
        )
        self.assertFalse(result["kb_initialized"])

    def test_install_repins_command_effects_after_codex_refreshes_system_skills(
        self,
    ) -> None:
        completed = self.run_installer(refresh_system_skills=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertTrue(result["launcher_contract"]["healthy"])
        self.assertTrue(
            result["launcher_contract"]["command_effects"]["healthy"]
        )
        snapshot = json.loads(
            (self.kb_home / "bin/.sulde-command-effects.json").read_text(
                encoding="utf-8"
            )
        )
        commands = {
            row["profile_id"]: row
            for row in snapshot["commands"]
            if row["profile_id"].startswith("codex-plugin-")
        }
        for profile_id, filename in (
            ("codex-plugin-validate-v1", "validate_plugin.py"),
            ("codex-plugin-cachebuster-v1", "update_plugin_cachebuster.py"),
        ):
            helper = (
                self.codex_home
                / "skills/.system/plugin-creator/scripts"
                / filename
            )
            self.assertEqual(
                commands[profile_id]["sha256"],
                hashlib.sha256(helper.read_bytes()).hexdigest(),
            )

    def test_install_reports_untrusted_pretool_without_claiming_live_ready(self) -> None:
        completed = self.run_installer(hook_trust_status="untrusted")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "generation_verified")
        self.assertEqual(
            result["operational_status"],
            "scheduler_ready_hook_trust_review_required",
        )
        self.assertFalse(result["operational_ready"])
        self.assertEqual(
            result["ready_scope"],
            "atomic_generation_ready_hook_trust_review_required",
        )
        self.assertEqual(
            result["smoke"]["hook_trust"]["unrunnable_events"],
            ["preToolUse"],
        )
        self.assertEqual(
            result["host_capabilities"]["live"]["status"],
            "hook_trust_review_required",
        )
        self.assertEqual(
            result["interactive_supervision"]["status"],
            "hook_trust_review_required",
        )
        self.assertFalse(
            result["interactive_supervision"]["hook_trust"]
            ["trust_write_performed"]
        )
        self.assertEqual(result["scheduler_actor_preflight"]["status"], "clear")
        scheduler = result["scheduler_generation"]
        self.assertEqual(scheduler["status"], "generation_verified")
        self.assertTrue(scheduler["healthy"])
        self.assertEqual(scheduler["blockers"], [])
        self.assertEqual(scheduler["missing_labels"], [])
        self.assertEqual(scheduler["retired_or_unknown_labels"], [])
        self.assertIsNone(result["scheduler_reconciliation_command"])
        deployment_path = self.kb_home / "deployment-generation.json"
        self.assertTrue(deployment_path.is_file())
        deployment = json.loads(deployment_path.read_text(encoding="utf-8"))
        self.assertEqual(deployment, result["deployment_generation"])
        self.assertEqual(deployment["status"], "generation_verified")
        self.assertTrue(deployment["operational_ready"])
        self.assertEqual(
            deployment["generation"],
            result["launcher_contract"]["generation"],
        )
        self.assertEqual(
            deployment["runtime_tree_sha256"],
            result["launcher_contract"]["runtime_tree_sha256"],
        )
        owner = scheduler["owner"]
        self.assertEqual(owner["status"], "active")
        self.assertEqual(owner["installation_status"], "generation_verified")
        self.assertTrue(owner["operational_ready"])
        self.assertEqual(owner["generation"], deployment["generation"])
        self.assertEqual(
            owner["runtime_tree_sha256"],
            deployment["runtime_tree_sha256"],
        )
        self.assertEqual(owner["runtime_root"], deployment["runtime_root"])
        self.assertEqual(
            sorted(scheduler["loaded_labels"]),
            sorted(deployment["managed_labels"]),
        )
        self.assertEqual(
            sorted(owner["managed_labels"]),
            sorted(deployment["managed_labels"]),
        )
        native = deployment["native_runtime_authority"]
        self.assertEqual(native["schema"], "sulde-installed-native-runtime-authority-v1")
        self.assertEqual(native["spec_version"], 2)
        self.assertEqual(native["codex_version"], "codex-cli 0.154.0")
        self.assertEqual(
            deployment["native_runtime_authority_sha256"],
            native["authority_sha256"],
        )
        unsigned = dict(native)
        unsigned.pop("authority_sha256")
        self.assertEqual(
            native["authority_sha256"],
            hashlib.sha256(
                json.dumps(
                    unsigned,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest(),
        )
        self.assertEqual(native["runtime_generation"], deployment["generation"])
        self.assertEqual(
            native["runtime_tree_sha256"], deployment["runtime_tree_sha256"]
        )
        self.assertEqual(
            hashlib.sha256(Path(native["broker_path"]).read_bytes()).hexdigest(),
            native["broker_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(
                Path(native["codex_cli_contract_path"]).read_bytes()
            ).hexdigest(),
            native["codex_cli_contract_sha256"],
        )
        self.assertEqual(
            deployment["runtime_root"],
            str((Path(result["installed_path"]) / "runtime").resolve()),
        )
        if os.name != "nt":
            self.assertEqual(deployment_path.stat().st_mode & 0o777, 0o600)
        self.assertIn("bootstrap.sh", result["kb_initialization_command"])
        agents_md = self.root / "codex-home" / "AGENTS.md"
        self.assertIn("Codex 派单档位纪律", agents_md.read_text(encoding="utf-8"))
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(Path(state["marketplace"]), self.artifact.resolve())
        installed = Path(state["installed"])
        self.assertTrue(installed.is_dir())
        installed_contract_path = (
            installed / "runtime" / "scripts" / "kb" / "codex_cli_contract.py"
        )
        self.assertTrue(installed_contract_path.is_file())
        contract_spec = importlib.util.spec_from_file_location(
            "test_installed_codex_cli_contract",
            installed_contract_path,
        )
        self.assertIsNotNone(contract_spec)
        self.assertIsNotNone(contract_spec.loader)
        installed_contract = importlib.util.module_from_spec(contract_spec)
        sys.modules[contract_spec.name] = installed_contract
        contract_spec.loader.exec_module(installed_contract)
        self.assertEqual(installed_contract.AUDITED_CODEX_VERSION, "codex-cli 0.154.0")
        self.assertFalse(list((installed / "runtime").rglob("__pycache__")))
        self.assertFalse(list((installed / "runtime").rglob("*.pyc")))
        self.assertTrue((installed / "hooks" / "hooks.json").is_file())
        self.assertTrue((installed / ".mcp.json").is_file())
        installed_descriptor = json.loads(
            (installed / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(installed_descriptor["mcpServers"], "./.mcp.json")
        installed_hooks = json.loads(
            (installed / "hooks" / "hooks.json").read_text(encoding="utf-8")
        )["hooks"]
        self.assertIn("PermissionRequest", installed_hooks)
        self.assertFalse((installed / "hooks.json").exists())
        staged_contract_path = (
            installed / "runtime" / "scripts" / "kb" / "launcher_contract.py"
        )
        staged_spec = importlib.util.spec_from_file_location(
            "test_installed_launcher_contract",
            staged_contract_path,
        )
        self.assertIsNotNone(staged_spec)
        self.assertIsNotNone(staged_spec.loader)
        staged_contract = importlib.util.module_from_spec(staged_spec)
        sys.modules[staged_spec.name] = staged_contract
        staged_spec.loader.exec_module(staged_contract)
        system_validate = (
            self.root
            / "codex-home"
            / "skills/.system/plugin-creator/scripts/validate_plugin.py"
        )
        classification_workspace = self.root / "classification-workspace"
        classification_workspace.mkdir()
        installed_classification = staged_contract.classify_trusted_script_command(
            [sys.executable, str(system_validate), str(installed)],
            kb_home=self.kb_home,
            cwd=classification_workspace,
            environment={**os.environ, "CODEX_HOME": str(self.root / "codex-home")},
        )
        self.assertIsNotNone(installed_classification)
        self.assertEqual(installed_classification["effect"], "read")
        probe = subprocess.run(
            [
                sys.executable,
                str(self.kb_home / "bin" / "intent-guardian"),
                "--sulde-launcher-probe",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertTrue(json.loads(probe.stdout)["healthy"])
        command_snapshot = self.kb_home / "bin" / ".sulde-command-effects.json"
        self.assertTrue(command_snapshot.is_file())
        if os.name != "nt":
            self.assertEqual(command_snapshot.stat().st_mode & 0o777, 0o600)

        repeated = self.run_installer()
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        repeated_result = json.loads(repeated.stdout)
        self.assertEqual(
            repeated_result["staged_plugin_tree_sha256"],
            result["staged_plugin_tree_sha256"],
        )

    def test_stopped_codex_host_blocks_before_any_install_write(self) -> None:
        registry_before = b'{"marketplace":"old","installed":null,"version":"0.0.1"}\n'
        self.state.write_bytes(registry_before)
        descriptor = (
            self.codex_home
            / "plugins/cache/sulde-local/sulde/0.0.1"
            / ".codex-plugin/plugin.json"
        )
        descriptor.parent.mkdir(parents=True)
        descriptor_before = b'{"name":"sulde","version":"0.0.1"}\n'
        descriptor.write_bytes(descriptor_before)
        cache_sentinel = descriptor.parents[1] / "runtime-sentinel.bin"
        cache_before = b"preserve-cache-bytes\x00\x01"
        cache_sentinel.write_bytes(cache_before)
        launcher = self.kb_home / "bin" / "intent-guardian"
        launcher.parent.mkdir(parents=True)
        launcher_before = b"preserve-launcher\n"
        launcher.write_bytes(launcher_before)

        completed = self.run_installer(
            loaded_labels=("com.sulde.codex-cache-repair",),
            ps_output="4242 T    codex /usr/local/bin/codex resume-thread\n",
            prepare_artifact=False,
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIn("stopped Codex host preflight failed", completed.stderr)
        self.assertEqual(self.state.read_bytes(), registry_before)
        self.assertEqual(descriptor.read_bytes(), descriptor_before)
        self.assertEqual(cache_sentinel.read_bytes(), cache_before)
        self.assertEqual(launcher.read_bytes(), launcher_before)
        self.assertFalse(self.artifact.exists())
        self.assertFalse((self.kb_home / ".deployment.lock").exists())
        self.assertFalse((self.kb_home / "deployment-generation.json").exists())

    def test_host_preflight_ignores_codex_mentions_in_user_arguments(self) -> None:
        installer = load_installer()
        self.assertFalse(
            installer._looks_like_codex_host(
                "zsh",
                "zsh -c 'printf stopped-process-mentioned-codex'",
            )
        )
        self.assertTrue(
            installer._looks_like_codex_host(
                "node",
                "node /opt/codex/codex.js resume-thread",
            )
        )

    def test_failed_installed_smoke_rolls_back_registry_and_launchers(self) -> None:
        sentinel = self.kb_home / "bin" / "intent-guardian"
        sentinel.parent.mkdir(parents=True)
        sentinel.write_text("previous launcher\n", encoding="utf-8")
        agents_md = self.root / "codex-home" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True, exist_ok=True)
        agents_md.write_text("# User rules\n", encoding="utf-8")
        completed = self.run_installer(tamper=True)
        self.assertEqual(completed.returncode, 1)
        self.assertIn("was rolled back", completed.stderr)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertIsNone(state["marketplace"])
        self.assertIsNone(state["installed"])
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "previous launcher\n")
        self.assertFalse((self.kb_home / "bin" / ".sulde-launchers.json").exists())
        self.assertFalse(
            (self.kb_home / "bin" / ".sulde-command-effects.json").exists()
        )
        self.assertEqual(agents_md.read_text(encoding="utf-8"), "# User rules\n")

    def test_failed_install_restores_marketplace_without_inventing_plugin(self) -> None:
        self.prepare_artifact()
        self.state.write_text(
            json.dumps(
                {
                    "marketplace": str(self.artifact),
                    "installed": None,
                    "version": None,
                    "effects": {},
                }
            ),
            encoding="utf-8",
        )

        completed = self.run_installer(tamper=True)

        self.assertEqual(completed.returncode, 1)
        self.assertIn("was rolled back", completed.stderr)
        restored = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(Path(restored["marketplace"]).resolve(), self.artifact.resolve())
        self.assertIsNone(restored["installed"])
        self.assertIsNone(restored["version"])
        self.assertEqual(restored["effects"].get("plugin_add"), 1)

    def test_scheduler_rollback_never_removes_absent_desired_actor(self) -> None:
        installer = load_installer()
        calls: list[tuple[str, ...]] = []

        def strict_runner(command, **_kwargs):
            rendered = tuple(str(value) for value in command)
            calls.append(rendered)
            if rendered == ("launchctl", "list"):
                return installer.CommandResult(rendered, 0, "", "")
            return installer.CommandResult(rendered, 3, "", "not loaded")

        descriptor = {
            "expected_postconditions": {
                "scheduler": {
                    "old_loaded_labels": [],
                    "desired_labels": ["com.sulde.auto-sediment"],
                    "launchagents_dir": str(self.root / "Library/LaunchAgents"),
                }
            }
        }
        with mock.patch.object(
            installer,
            "_launchctl_path",
            return_value="launchctl",
        ):
            installer._restore_scheduler_process_state(
                descriptor,
                runner=strict_runner,
            )

        self.assertEqual(
            calls,
            [("launchctl", "list"), ("launchctl", "list")],
        )

    def test_process_death_through_launcher_publish_recovers_coherently(self) -> None:
        forward_stages = (
                "prepared",
                "registry_remove_started",
                "registry_removed",
                "registry_add_started",
                "registry_added",
                "launcher_publish_started",
                "launcher_published",
        )
        boundaries = (
            *(f"journal.{side}.{stage}" for stage in forward_stages for side in ("before", "after")),
            "registry.before_remove",
            "registry.after_remove",
            "registry.before_add",
            "registry.after_add",
            "launcher.before_publish",
            "launcher.after_publish",
            "launcher.final_repin.before_publish",
            "launcher.final_repin.after_publish",
        )
        legacy_files = {
            Path("scripts/run-hook.sh"): "legacy posix bridge\n",
            Path("scripts/run-hook.ps1"): "legacy windows bridge\n",
            Path("runtime/pkg/__pycache__/warm.cpython-313.pyc"): "warm bytecode\n",
        }
        original = (self.state, self.artifact, self.kb_home, self.codex_home)
        try:
            for index, boundary in enumerate(boundaries):
                with self.subTest(boundary=boundary):
                    scenario = self.root / "crash-scenarios" / str(index)
                    self.state = scenario / "state.json"
                    self.artifact = scenario / "artifact" / "codex"
                    self.kb_home = scenario / "kb-home"
                    self.codex_home = scenario / "codex-home"
                    legacy = (
                        self.codex_home
                        / "plugins/cache/sulde-local/sulde/0.0.7-warm"
                    )
                    files = {
                        Path(".codex-plugin/plugin.json"): json.dumps(
                            {"name": "sulde", "version": legacy.name}
                        ),
                        **legacy_files,
                    }
                    for relative, content in files.items():
                        target = legacy / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(content, encoding="utf-8")
                    crashed = self.run_installer(failpoint=boundary)
                    self.assertEqual(crashed.returncode, 86, crashed.stderr)

                    # A crashed installer does not unload launchd actors.  Keep
                    # the process state produced before the failpoint so late
                    # transaction stages can be recovered against real host
                    # state instead of a test-only reset to an empty scheduler.
                    recovered = self.run_installer(
                        initialize_launchctl_state=False
                    )
                    self.assertEqual(recovered.returncode, 0, recovered.stderr)
                    result = json.loads(recovered.stdout)
                    self.assertIn(
                        result["status"],
                        {"recovered_old_generation", "recovered_new_generation"},
                    )
                    state = json.loads(self.state.read_text(encoding="utf-8"))
                    if result["status"] == "recovered_old_generation":
                        self.assertIsNone(state["marketplace"])
                        self.assertIsNone(state["installed"])
                        self.assertFalse(
                            (self.kb_home / "deployment-generation.json").exists()
                        )
                        self.assertFalse(
                            (self.kb_home / "bin/.sulde-launchers.json").exists()
                        )
                    else:
                        installed = Path(state["installed"])
                        self.assertTrue(installed.is_dir())
                        deployment = json.loads(
                            (self.kb_home / "deployment-generation.json").read_text(
                                encoding="utf-8"
                            )
                        )
                        launcher = json.loads(
                            (self.kb_home / "bin/.sulde-launchers.json").read_text(
                                encoding="utf-8"
                            )
                        )
                        self.assertEqual(deployment["generation"], launcher["generation"])
                        self.assertEqual(
                            deployment["runtime_root"],
                            str((installed / "runtime").resolve()),
                        )
                    recovery = self.kb_home / ".install-recovery"
                    self.assertFalse((recovery / "active.json").exists())
                    transactions = list((recovery / "transactions").iterdir())
                    self.assertEqual(len(transactions), 1)
                    records = [
                        json.loads(line)
                        for line in (transactions[0] / "journal.jsonl")
                        .read_text(encoding="utf-8")
                        .splitlines()
                    ]
                    self.assertIn(records[-1]["stage"], {"rolled_back", "committed"})
                    self.assertEqual(
                        [row["sequence"] for row in records],
                        list(range(1, len(records) + 1)),
                    )
                    self.assertTrue((transactions[0] / "descriptor.json").is_file())
                    self.assertTrue((recovery / "snapshots").is_dir())
                    self.assertTrue(all(count == 1 for count in state["effects"].values()))
        finally:
            self.state, self.artifact, self.kb_home, self.codex_home = original

    def test_process_death_after_scheduler_reconcile_restores_exact_old_generation(self) -> None:
        old_label = "com.sulde.codex-cache-repair"
        launchagents = self.root / "Library" / "LaunchAgents"
        launchagents.mkdir(parents=True)
        old_plist = launchagents / f"{old_label}.plist"
        old_plist_bytes = plistlib.dumps(
            {
                "Label": old_label,
                "ProgramArguments": ["/old/sulde-scheduler"],
            }
        )
        old_plist.write_bytes(old_plist_bytes)
        old_owner = self.kb_home / "runtime-owner.json"
        old_owner.parent.mkdir(parents=True)
        old_owner_bytes = b'{"generation":"old-generation","status":"active"}\n'
        old_owner.write_bytes(old_owner_bytes)
        old_runner = self.kb_home / "bin" / "sulde-scheduled-run"
        old_runner.parent.mkdir(parents=True)
        old_runner_bytes = b"#!/bin/sh\necho old-scheduler\n"
        old_runner.write_bytes(old_runner_bytes)
        old_deployment = self.kb_home / "deployment-generation.json"
        old_deployment_bytes = b'{"generation":"old-generation"}\n'
        old_deployment.write_bytes(old_deployment_bytes)

        crashed = self.run_installer(
            loaded_labels=(old_label,),
            failpoint="scheduler.after_reconcile",
        )
        self.assertEqual(crashed.returncode, 86, crashed.stderr)
        self.assertTrue((self.kb_home / ".install-recovery/active.json").is_file())
        self.assertNotEqual(old_owner.read_bytes(), old_owner_bytes)
        self.assertNotEqual(
            json.loads((self.root / "launchctl-state.json").read_text(encoding="utf-8")),
            [old_label],
        )

        recovered = self.run_installer(
            prepare_artifact=False,
            initialize_launchctl_state=False,
        )
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        result = json.loads(recovered.stdout)
        self.assertEqual(result["status"], "recovered_old_generation")
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertIsNone(state["marketplace"])
        self.assertIsNone(state["installed"])
        self.assertEqual(old_owner.read_bytes(), old_owner_bytes)
        self.assertEqual(old_runner.read_bytes(), old_runner_bytes)
        self.assertEqual(old_deployment.read_bytes(), old_deployment_bytes)
        self.assertEqual(old_plist.read_bytes(), old_plist_bytes)
        self.assertEqual(
            sorted(path.name for path in launchagents.glob("com.sulde.*.plist")),
            [old_plist.name],
        )
        self.assertFalse((launchagents / ".sulde-retired").exists())
        self.assertEqual(
            json.loads((self.root / "launchctl-state.json").read_text(encoding="utf-8")),
            [old_label],
        )
        self.assertFalse((self.kb_home / ".install-recovery/active.json").exists())

    def test_process_death_at_warm_retirement_boundaries_restores_exact_prestate(self) -> None:
        boundaries = (
            "normalization.before_publish",
            "retirement.before_publish",
            "retirement.after_publish",
            "normalization.after_publish",
        )
        original = (self.state, self.artifact, self.kb_home, self.codex_home)
        try:
            for index, boundary in enumerate(boundaries):
                with self.subTest(boundary=boundary):
                    scenario = self.root / "retirement-crash-scenarios" / str(index)
                    self.state = scenario / "state.json"
                    self.artifact = scenario / "artifact/codex"
                    self.kb_home = scenario / "kb-home"
                    self.codex_home = scenario / "codex-home"
                    legacy = (
                        self.codex_home
                        / "plugins/cache/sulde-local/sulde/0.0.7-warm"
                    )
                    files = {
                        Path(".codex-plugin/plugin.json"): json.dumps(
                            {"name": "sulde", "version": legacy.name}
                        ),
                        Path("scripts/run-hook.sh"): "legacy posix bridge\n",
                        Path("scripts/run-hook.ps1"): "legacy windows bridge\n",
                        Path(
                            "runtime/pkg/__pycache__/warm.cpython-313.pyc"
                        ): "warm bytecode\n",
                    }
                    for relative, content in files.items():
                        target = legacy / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(content, encoding="utf-8")

                    crashed = self.run_installer(failpoint=boundary)
                    self.assertEqual(crashed.returncode, 86, crashed.stderr)
                    recovered = self.run_installer()
                    self.assertEqual(recovered.returncode, 0, recovered.stderr)
                    result = json.loads(recovered.stdout)
                    self.assertEqual(result["status"], "recovered_old_generation")
                    self.assertTrue(legacy.is_dir())
                    self.assertFalse(legacy.is_symlink())
                    for relative, content in files.items():
                        self.assertEqual(
                            (legacy / relative).read_text(encoding="utf-8"),
                            content,
                        )
                    self.assertFalse(
                        (self.kb_home / ".install-recovery/active.json").exists()
                    )
        finally:
            self.state, self.artifact, self.kb_home, self.codex_home = original

    def test_process_death_during_rollback_journal_replays_same_transaction(self) -> None:
        original = (self.state, self.artifact, self.kb_home, self.codex_home)
        try:
            for index, recovery_boundary in enumerate(
                (
                    "journal.before.rollback_started",
                    "journal.after.rollback_started",
                    "journal.before.rolled_back",
                    "journal.after.rolled_back",
                )
            ):
                with self.subTest(boundary=recovery_boundary):
                    scenario = self.root / "rollback-crash-scenarios" / str(index)
                    self.state = scenario / "state.json"
                    self.artifact = scenario / "artifact" / "codex"
                    self.kb_home = scenario / "kb-home"
                    self.codex_home = scenario / "codex-home"
                    initial = self.run_installer(failpoint="registry.after_add")
                    self.assertEqual(initial.returncode, 86, initial.stderr)
                    interrupted = self.run_installer(failpoint=recovery_boundary)
                    self.assertEqual(interrupted.returncode, 86, interrupted.stderr)
                    recovered = self.run_installer()
                    self.assertEqual(recovered.returncode, 0, recovered.stderr)
                    result = json.loads(recovered.stdout)
                    self.assertEqual(result["status"], "recovered_old_generation")
                    state = json.loads(self.state.read_text(encoding="utf-8"))
                    self.assertIsNone(state["marketplace"])
                    self.assertIsNone(state["installed"])
                    self.assertTrue(all(count == 1 for count in state["effects"].values()))
                    recovery = self.kb_home / ".install-recovery"
                    self.assertFalse((recovery / "active.json").exists())
                    transaction = next((recovery / "transactions").iterdir())
                    records = [
                        json.loads(line)
                        for line in (transaction / "journal.jsonl")
                        .read_text(encoding="utf-8")
                        .splitlines()
                    ]
                    self.assertEqual(records[-1]["stage"], "rolled_back")
                    self.assertEqual(
                        [row["stage"] for row in records].count("rollback_started"), 1
                    )
        finally:
            self.state, self.artifact, self.kb_home, self.codex_home = original

    def test_failed_install_restores_pruned_legacy_cache_tree(self) -> None:
        legacy = (
            self.root
            / "codex-home"
            / "plugins"
            / "cache"
            / "sulde-local"
            / "sulde"
            / "0.0.8"
        )
        files = {
            Path(".codex-plugin/plugin.json"): json.dumps(
                {"name": "sulde", "version": "0.0.8"}
            ),
            Path("scripts/user-prompt-submit.py"): "legacy adapter\n",
            Path("scripts/run-hook.sh"): "legacy posix bridge\n",
            Path("scripts/run-hook.ps1"): "legacy windows bridge\n",
            Path("runtime/static.txt"): "legacy runtime\n",
            Path("skills/intent-guardian/SKILL.md"): "legacy skill\n",
            Path("runtime/pkg/__pycache__/actor.cpython-313.pyc"): "warm bytecode\n",
        }
        for relative, content in files.items():
            path = legacy / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        completed = self.run_installer(tamper=True, prune_path=legacy)
        self.assertEqual(completed.returncode, 1)
        self.assertIn("was rolled back", completed.stderr)
        self.assertTrue(legacy.is_dir())
        self.assertFalse(legacy.is_symlink())
        for relative, content in files.items():
            self.assertEqual(
                (legacy / relative).read_text(encoding="utf-8"),
                content,
            )
        retirement_root = (
            self.codex_home / "plugins/retired/sulde-local/sulde"
        )
        self.assertFalse(
            retirement_root.exists() and any(retirement_root.iterdir())
        )

    def test_marketplace_parser_preserves_paths_with_spaces(self) -> None:
        installer = load_installer()
        output = "MARKETPLACE          ROOT\nsulde-local          /tmp/Sulde Artifacts/codex\n"
        self.assertEqual(
            installer._marketplace_root(output),
            Path("/tmp/Sulde Artifacts/codex"),
        )
        plugin_output = (
            "PLUGIN             STATUS              VERSION       PATH\n"
            "sulde@sulde-local  installed, enabled  0.2.1+test  "
            "/tmp/Sulde Cache/0.2.1+test\n"
        )
        self.assertEqual(
            installer._plugin_installation(plugin_output),
            ("0.2.1+test", Path("/tmp/Sulde Cache/0.2.1+test").resolve()),
        )

    def test_installer_tree_digest_rejects_git_and_python_bytecode(self) -> None:
        installer = load_installer()
        tree = self.root / "digest-tree"
        tree.mkdir()
        (tree / "payload.txt").write_text("immutable payload\n", encoding="utf-8")

        git_dir = tree / ".git"
        git_dir.mkdir()
        with self.assertRaisesRegex(installer.InstallError, "repository metadata"):
            installer.tree_digest(tree)
        git_dir.rmdir()

        cache = tree / "__pycache__"
        cache.mkdir()
        bytecode = cache / "actor.cpython-313.pyc"
        bytecode.write_bytes(b"not executable test bytecode")
        with self.assertRaisesRegex(installer.InstallError, "Python bytecode"):
            installer.tree_digest(tree)

    def test_warm_tree_snapshot_normalizes_only_derived_bytecode(self) -> None:
        installer = load_installer()
        warm = self.root / "warm-tree"
        (warm / "pkg" / "__pycache__").mkdir(parents=True)
        (warm / "payload.txt").write_text("static bytes\n", encoding="utf-8")
        bytecode = warm / "pkg" / "__pycache__" / "actor.cpython-313.pyc"
        bytecode.write_bytes(b"derived bytecode fixture")

        before = installer.warm_tree_state(warm)
        self.assertNotEqual(before.tree_sha256, before.normalized_tree_sha256)
        self.assertEqual(
            [row["path"] for row in before.bytecode_inventory],
            ["pkg/__pycache__/actor.cpython-313.pyc"],
        )
        snapshots = installer._snapshot_plugin_trees(
            (warm,), self.root / "owner-only-recovery" / "snapshots"
        )
        snapshot = snapshots[0][1]
        self.assertEqual(installer.warm_tree_state(snapshot), before)

        removed = installer._remove_derived_bytecode(snapshot)
        after = installer.warm_tree_state(snapshot)
        self.assertEqual(removed, ("pkg/__pycache__/actor.cpython-313.pyc",))
        self.assertFalse(after.bytecode_inventory)
        self.assertEqual(after.tree_sha256, before.normalized_tree_sha256)
        self.assertEqual(
            (snapshot / "payload.txt").read_text(encoding="utf-8"),
            "static bytes\n",
        )

    def test_warm_tree_rejects_unknown_symlink_and_hardlink_entries(self) -> None:
        installer = load_installer()

        unknown = self.root / "warm-unknown"
        (unknown / "__pycache__").mkdir(parents=True)
        (unknown / "__pycache__" / "note.txt").write_text(
            "not derived\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(installer.InstallError, "unknown derived item"):
            installer.warm_tree_state(unknown)

        unscoped = self.root / "warm-unscoped"
        unscoped.mkdir()
        (unscoped / "actor.pyc").write_bytes(b"unscoped")
        with self.assertRaisesRegex(installer.InstallError, "unscoped Python bytecode"):
            installer.warm_tree_state(unscoped)

        linked = self.root / "warm-symlink"
        linked.mkdir()
        (linked / "payload.txt").write_text("payload\n", encoding="utf-8")
        (linked / "alias.txt").symlink_to(linked / "payload.txt")
        with self.assertRaisesRegex(installer.InstallError, "contains a symlink"):
            installer.warm_tree_state(linked)

        hardlinked = self.root / "warm-hardlink"
        hardlinked.mkdir()
        source = hardlinked / "payload.txt"
        source.write_text("payload\n", encoding="utf-8")
        os.link(source, hardlinked / "alias.txt")
        with self.assertRaisesRegex(installer.InstallError, "ambiguous hard link"):
            installer.warm_tree_state(hardlinked)

    def test_retirement_is_digest_bound_outside_enumeration_and_repeatable(self) -> None:
        installer = load_installer()
        cache_root = self.codex_home / "plugins/cache/sulde-local/sulde"
        old = cache_root / "0.1.0+same-precedence"
        current = self.root / "current-plugin"
        for plugin, version, marker in (
            (old, old.name, "old"),
            (current, installer.plugin_version(), "current"),
        ):
            descriptor = plugin / ".codex-plugin/plugin.json"
            descriptor.parent.mkdir(parents=True)
            descriptor.write_text(
                json.dumps({"name": "sulde", "version": version}),
                encoding="utf-8",
            )
            for relative in installer.LIVE_SESSION_BRIDGE_FILES:
                bridge = plugin / relative
                bridge.parent.mkdir(parents=True, exist_ok=True)
                bridge.write_text(f"{marker}:{relative.as_posix()}\n", encoding="utf-8")
        pycache = old / "runtime/pkg/__pycache__"
        pycache.mkdir(parents=True)
        (pycache / "warm.cpython-313.pyc").write_bytes(b"warm")
        snapshot = installer._snapshot_plugin_trees(
            (old,), self.root / "retirement-snapshots"
        )[0][1]
        plans = installer._prepare_cache_retirements(
            ((old, snapshot),),
            current_install=current,
            preparation_root=self.root / "prepared-retirements",
        )
        self.assertEqual(len(plans), 1)
        plan = plans[0]
        self.assertTrue(plan.prestate.bytecode_inventory)
        self.assertTrue(installer._path_outside_cache_enumeration_root(plan.target))
        self.assertNotEqual(plan.target.parent, cache_root)

        installer._publish_retirement_targets(plans)
        installer._publish_retirement_aliases(plans)
        installer._verify_retirement_descriptors(
            installer._retirement_descriptors(plans)
        )
        self.assertTrue(old.is_symlink())
        self.assertEqual(old.resolve(), plan.target.resolve())
        self.assertFalse(installer.warm_tree_state(plan.target).bytecode_inventory)
        self.assertEqual(
            (plan.target / installer.LIVE_SESSION_BRIDGE_FILES[0]).read_bytes(),
            (current / installer.LIVE_SESSION_BRIDGE_FILES[0]).read_bytes(),
        )

        sources = installer._legacy_install_sources(())
        controlled = next(row for row in sources if row.target == old)
        self.assertEqual(controlled.mode, "controlled_retired_alias")
        self.assertEqual(controlled.source.resolve(), plan.target.resolve())
        self.assertEqual(installer._previous_install_paths((old.name, old)), ())

        controlled_snapshot = installer._snapshot_plugin_trees(
            (plan.target,), self.root / "controlled-retirement-snapshots"
        )[0][1]
        repeated_plan = installer._prepare_cache_retirements(
            ((old, controlled_snapshot),),
            current_install=current,
            preparation_root=self.root / "repeated-prepared-retirements",
        )[0]
        self.assertTrue(repeated_plan.alias_preexisting)
        self.assertEqual(
            repeated_plan.preexisting_target.resolve(), plan.target.resolve()
        )
        old.unlink()
        installer._restore_preexisting_retirement_aliases(
            {
                "expected_postconditions": {
                    "retirements": installer._retirement_descriptors(
                        (repeated_plan,)
                    )
                }
            }
        )
        self.assertEqual(old.resolve(), plan.target.resolve())

        plan.target.joinpath("drift.txt").write_text("drift\n", encoding="utf-8")
        with self.assertRaisesRegex(installer.InstallError, "no same-version"):
            installer._legacy_install_sources(())

    def test_stable_jsonl_accepts_complete_and_ignores_only_moving_tail(self) -> None:
        installer = load_installer()
        session = self.root / "session.jsonl"
        session.write_bytes(b'{"sequence":1}\n')
        stable = installer._stable_jsonl_snapshot(session)
        self.assertEqual(stable["status"], "stable")
        self.assertEqual(stable["records"], [{"sequence": 1}])
        self.assertRegex(stable["sha256"], r"^[0-9a-f]{64}$")

        observed_session = self.codex_home / "sessions/peer.jsonl"
        observed_session.parent.mkdir(parents=True)
        observed_session.write_bytes(session.read_bytes())
        with mock.patch.object(installer.os, "kill") as terminate:
            observation = installer._observe_peer_session_safety()
        terminate.assert_not_called()
        self.assertEqual(observation["status"], "observed")
        self.assertEqual(observation["files_observed"], 1)
        self.assertEqual(observation["validation_scope"], "metadata_only")
        self.assertEqual(observation["deep_audit"], "failure_triggered")
        self.assertFalse(observation["termination_authority"])

        observed_session.write_text("historical corruption is unrelated\n", encoding="utf-8")
        metadata_only = installer._observe_peer_session_safety()
        self.assertEqual(metadata_only["status"], "observed")
        self.assertEqual(metadata_only["files_observed"], 1)

        session.write_bytes(b'{"sequence":1}\n{"sequence":')
        additions = iter((b"2", b"3"))

        def advance_tail(_delay):
            with session.open("ab") as handle:
                handle.write(next(additions))

        with mock.patch.object(installer.time, "sleep", side_effect=advance_tail):
            moving = installer._stable_jsonl_snapshot(
                session, attempts=3, retry_delay=0
            )
        self.assertEqual(moving["status"], "concurrent_tail_ignored")
        self.assertEqual(moving["records"], [{"sequence": 1}])
        self.assertIsNone(moving["sha256"])

    def test_stable_jsonl_rejects_stable_partial_and_structural_damage(self) -> None:
        installer = load_installer()
        session = self.root / "session.jsonl"
        session.write_bytes(b'{"sequence":1')
        with self.assertRaisesRegex(installer.InstallError, "stable damaged tail"):
            installer._stable_jsonl_snapshot(session, retry_delay=0)

        session.write_bytes(b'{"sequence":1}\nnot-json\n')
        with self.assertRaisesRegex(installer.InstallError, "structurally damaged"):
            installer._stable_jsonl_snapshot(session, retry_delay=0)

        target = self.root / "real-session.jsonl"
        target.write_bytes(b'{"sequence":1}\n')
        session.unlink()
        session.symlink_to(target)
        with self.assertRaisesRegex(installer.InstallError, "unambiguous regular file"):
            installer._stable_jsonl_snapshot(session, retry_delay=0)

    def test_app_server_initialize_handshake_orders_notification_after_response(self) -> None:
        installer = load_installer()
        server = (
            "import json,sys; "
            "request=json.loads(sys.stdin.readline()); "
            "print(json.dumps({'id':request['id'],'result':{'ok':True}}),flush=True); "
            "notice=json.loads(sys.stdin.readline()); "
            "raise SystemExit(0 if notice.get('method')=='initialized' else 7)"
        )
        completed = installer._app_server_initialize_handshake(
            [sys.executable, "-B", "-c", server],
            environment=dict(os.environ),
            timeout=2,
        )
        self.assertEqual(completed.returncode, 0)
        response = json.loads(completed.stdout.splitlines()[0])
        self.assertEqual(response["id"], 0)
        self.assertEqual(response["result"], {"ok": True})

    def test_app_server_initialize_handshake_rejects_zero_exit_and_partial_line(self) -> None:
        installer = load_installer()
        zero_without_response = (
            "import json,sys; sys.stdin.readline(); "
            "print(json.dumps({'id':99,'result':{}}),flush=True); raise SystemExit(0)"
        )
        with self.assertRaisesRegex(installer.InstallError, "response timed out"):
            installer._app_server_initialize_handshake(
                [sys.executable, "-B", "-c", zero_without_response],
                environment=dict(os.environ),
                timeout=1,
            )

        partial_then_hang = (
            "import sys,time; sys.stdin.readline(); "
            "sys.stdout.write('{\\\"id\\\":0'); sys.stdout.flush(); time.sleep(30)"
        )
        started = installer.time.monotonic()
        with self.assertRaisesRegex(installer.InstallError, "response timed out"):
            installer._app_server_initialize_handshake(
                [sys.executable, "-B", "-c", partial_then_hang],
                environment=dict(os.environ),
                timeout=0.2,
            )
        self.assertLess(installer.time.monotonic() - started, 2)

    def test_installed_mcp_denial_requires_evaluated_readable_scope(self) -> None:
        installer = load_installer()
        for reason in (
            "目标不在可读意图范围内；未授予写权限。",
            (
                "此动作需要一次当前会话确认。操作：update_document。"
                "范围：doc://candidate-promotion-canary。"
                "Allow 仅执行一次；Deny 不执行。"
            ),
        ):
            with self.subTest(reason=reason):
                verified = installer._verify_installed_mcp_scope_denial(
                    {
                        "hookSpecificOutput": {
                            "permissionDecision": "deny",
                            "permissionDecisionReason": reason,
                        }
                    }
                )
                self.assertEqual(verified["permissionDecision"], "deny")

        confirmed = installer._verify_installed_mcp_scope_denial(
            {
                "hookSpecificOutput": {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "此动作需要一次当前会话确认。操作：update_document。"
                        "范围：doc://candidate-promotion-canary。"
                        "Allow 仅执行一次；Deny 不执行。"
                    ),
                }
            },
            require_confirmation=True,
        )
        self.assertEqual(confirmed["permissionDecision"], "deny")

        for reason in (
            "Sulde intent guardian is busy or unavailable; this material/unknown action was not dispatched.",
            "runtime is unavailable; 可读意图范围无法计算。",
            "批准事件 event_fingerprint=fixture；可读意图范围内。",
            "此动作需要一次当前会话确认。Allow 仅执行一次；Deny 不执行。",
        ):
            with self.subTest(reason=reason), self.assertRaisesRegex(
                installer.InstallError, "readable scope decision"
            ):
                installer._verify_installed_mcp_scope_denial(
                    {
                        "hookSpecificOutput": {
                            "permissionDecision": "deny",
                            "permissionDecisionReason": reason,
                        }
                    }
                )

    def test_promoted_smoke_delegates_workspace_creation_to_boundary(self) -> None:
        installer = load_installer()
        installed = self.root / "installed-plugin"
        installed.mkdir()
        observed_workspaces: list[Path] = []

        def boundary(
            _installed_plugin,
            *,
            workspace,
            session,
            environment,
            runner,
        ):
            del session, environment, runner
            self.assertFalse(workspace.exists())
            workspace.mkdir(parents=True)
            observed_workspaces.append(workspace)
            return {
                "status": "ready",
                "permission_decision": "deny",
                "decision_kind": "current_session_confirmation",
            }

        def runner(command, **_kwargs):
            return installer.CommandResult(
                tuple(command),
                0,
                "sulde@sulde-local  installed, enabled  0.2.5+fixture  /fixture\n",
                "",
            )

        with (
            mock.patch.object(
                installer,
                "_smoke_current_session_mcp_confirmation",
                side_effect=boundary,
            ),
            mock.patch.object(
                installer,
                "_mcp_initialize_smoke",
                return_value={"server_name": "sulde-kb"},
            ),
            mock.patch.object(
                installer,
                "_codex_plugin_mcp_projection",
                return_value={"command": ["mcp"], "cwd": str(self.root)},
            ),
            mock.patch.object(
                installer,
                "_codex_hook_trust_observation",
                return_value={"status": "ready"},
            ),
            mock.patch.object(installer, "plugin_version", return_value="0.2.5+fixture"),
        ):
            result = installer._smoke_promoted_candidate(
                installed,
                self.root / "kb",
                codex="codex",
                expected_tree_sha256="a" * 64,
                runner=runner,
                installed_descriptor={"mcp_stdio_route": {"command": ["mcp"]}},
                installed_tree_sha256="a" * 64,
                candidate_receipt={"receipt_sha256": "b" * 64},
            )

        self.assertEqual(len(observed_workspaces), 1)
        self.assertEqual(
            result["promotion_preexecution_boundary"]["status"], "ready"
        )

    def test_registry_add_requires_canonical_cache_readback(self) -> None:
        installer = load_installer()
        version = "1.2.3+canonical"
        marketplace = self.root / "marketplace"
        marketplace.mkdir()
        canonical = self.codex_home / "plugins/cache/sulde-local/sulde" / version
        canonical.mkdir(parents=True)

        def runner(command, **_kwargs):
            if command[1:4] == ["plugin", "marketplace", "add"]:
                payload = {
                    "marketplaceName": "sulde-local",
                    "installedRoot": str(marketplace.resolve()),
                }
            else:
                payload = {
                    "pluginId": "sulde@sulde-local",
                    "version": version,
                    "installedPath": str(canonical),
                }
            return installer.CommandResult(tuple(command), 0, json.dumps(payload), "")

        self.assertEqual(
            installer._registry_add(
                str(self.fake), marketplace, runner, expected_version=version
            ),
            canonical.resolve(),
        )

        displayed_source = marketplace / "plugins/sulde"
        displayed_source.mkdir(parents=True)

        def mismatched_runner(command, **kwargs):
            result = runner(command, **kwargs)
            if command[1:3] == ["plugin", "add"]:
                payload = json.loads(result.stdout)
                payload["installedPath"] = str(displayed_source)
                return installer.CommandResult(
                    result.command, 0, json.dumps(payload), ""
                )
            return result

        with self.assertRaisesRegex(
            installer.InstallError, "not the canonical cache authority"
        ):
            installer._registry_add(
                str(self.fake),
                marketplace,
                mismatched_runner,
                expected_version=version,
            )

    def test_shared_staged_marketplace_fixture_contains_exact_native_inventory(self) -> None:
        installer = load_installer()
        for alternate in ("missing", "stale"):
            with self.subTest(alternate=alternate):
                marketplace = self.root / f"marketplace-{alternate}"
                plugin = marketplace / "plugins" / "sulde"
                descriptor = plugin / ".codex-plugin" / "plugin.json"
                descriptor.parent.mkdir(parents=True)
                descriptor.write_text(
                    json.dumps({"name": "sulde", "version": "0.2.5+fixture"}),
                    encoding="utf-8",
                )
                runtime_kb = plugin / "runtime" / "scripts" / "kb"
                runtime_kb.mkdir(parents=True)
                if alternate == "stale":
                    for relative, _mode in installer.INSTALLER_NATIVE_RUNTIME_INVENTORY:
                        target = plugin / "runtime" / relative
                        target.write_text("stale fixture bytes\n", encoding="utf-8")
                        target.chmod(0o600)

                installer._complete_staged_native_runtime(
                    marketplace,
                    platform="posix",
                )

                for relative, expected_mode in installer.INSTALLER_NATIVE_RUNTIME_INVENTORY:
                    source = ROOT / relative
                    target = plugin / "runtime" / relative
                    self.assertEqual(target.read_bytes(), source.read_bytes())
                    if os.name != "nt":
                        self.assertEqual(target.stat().st_mode & 0o777, expected_mode)
                sealed = installer._delivery_generation(
                    plugin,
                    expected_version="0.2.5+fixture",
                )
                self.assertEqual(sealed["platform"], "posix")
                self.assertEqual(
                    sealed["runtime_tree_sha256"],
                    installer.tree_digest(plugin / "runtime"),
                )

    def test_validation_rejects_tampered_packaged_history_after_reseal(self) -> None:
        self.prepare_artifact()
        installer = load_installer()
        history = (
            self.artifact
            / "plugins"
            / "sulde"
            / "runtime"
            / "knowledge"
            / "HISTORY.json"
        )
        payload = json.loads(history.read_text(encoding="utf-8"))
        payload["documents"][0]["last_commit_at"] = "2000-01-01T00:00:00+00:00"
        history.write_text(json.dumps(payload), encoding="utf-8")
        installer._complete_staged_native_runtime(
            self.artifact,
            platform="posix",
        )

        with self.assertRaisesRegex(installer.InstallError, "knowledge history"):
            installer.validate_staged_marketplace(
                self.artifact,
                expected_version=installer.plugin_version(),
            )

    def test_stage_artifact_completes_native_inventory_before_validation(self) -> None:
        installer = load_installer()
        artifact = self.root / "focused-artifact"
        validated = []

        def fixture_stager(command, **_kwargs):
            output = Path(command[command.index("--output") + 1])
            descriptor = (
                output
                / "plugins"
                / "sulde"
                / ".codex-plugin"
                / "plugin.json"
            )
            descriptor.parent.mkdir(parents=True)
            descriptor.write_text(
                json.dumps(
                    {
                        "name": "sulde",
                        "version": installer.plugin_version(),
                    }
                ),
                encoding="utf-8",
            )
            return installer.CommandResult(tuple(command), 0, "staged fixture\n", "")

        def validate_complete(marketplace, *, expected_version):
            plugin = marketplace / "plugins" / "sulde"
            for relative, expected_mode in installer.INSTALLER_NATIVE_RUNTIME_INVENTORY:
                target = plugin / "runtime" / relative
                self.assertEqual(target.read_bytes(), (ROOT / relative).read_bytes())
                if os.name != "nt":
                    self.assertEqual(target.stat().st_mode & 0o777, expected_mode)
            installer._delivery_generation(
                plugin,
                expected_version=expected_version,
            )
            validated.append(marketplace)
            return {
                "mcp_stdio_route": {
                    "cwd": str(plugin.resolve()),
                    "launcher": str((plugin / "scripts/run-mcp.sh").resolve()),
                }
            }

        with mock.patch.object(
            installer,
            "validate_staged_marketplace",
            side_effect=validate_complete,
        ):
            evidence = installer._stage_artifact(
                artifact,
                platform="posix",
                runner=fixture_stager,
            )
        self.assertEqual(len(validated), 2)
        self.assertNotEqual(validated[0], artifact)
        self.assertEqual(validated[1], artifact)
        self.assertTrue(artifact.is_dir())
        self.assertEqual(evidence.marketplace, artifact.resolve())
        self.assertEqual(
            evidence.descriptor["mcp_stdio_route"]["cwd"],
            str((artifact / "plugins/sulde").resolve()),
        )
        self.assertEqual(
            evidence.plugin_tree_sha256,
            installer.tree_digest(artifact / "plugins" / "sulde"),
        )

    def test_verified_candidate_publishes_only_equivalent_canonical_artifact(self) -> None:
        installer = load_installer()
        candidate_root = self.root / "candidate"
        canonical = self.root / "canonical"

        def descriptor(root: Path) -> dict[str, object]:
            plugin = root / "plugins" / "sulde"
            return {
                "delivery_generation": {"generation": "fixture"},
                "mcp_stdio_route": {
                    "command": ["./scripts/run-mcp.sh"],
                    "cwd": str(plugin),
                    "launcher": str(plugin / "scripts" / "run-mcp.sh"),
                },
            }

        candidate = installer.PreparedArtifact(
            candidate_root,
            descriptor(candidate_root),
            "a" * 64,
        )
        published = installer.PreparedArtifact(
            canonical,
            descriptor(canonical),
            candidate.plugin_tree_sha256,
        )

        with (
            mock.patch.object(
                installer, "default_artifact_root", return_value=canonical
            ),
            mock.patch.object(
                installer, "_stage_artifact", return_value=published
            ) as stage,
        ):
            result = installer._publish_verified_candidate_artifact(
                candidate,
                platform="posix",
                runner=installer.run_command,
            )

        self.assertEqual(result, published)
        stage.assert_called_once_with(
            canonical,
            platform="posix",
            runner=installer.run_command,
        )

        for drifted in (
            installer.PreparedArtifact(
                canonical,
                {
                    **published.descriptor,
                    "delivery_generation": {"generation": "drifted"},
                },
                candidate.plugin_tree_sha256,
            ),
            installer.PreparedArtifact(
                canonical,
                published.descriptor,
                "b" * 64,
            ),
        ):
            with (
                self.subTest(drifted=drifted),
                mock.patch.object(
                    installer, "default_artifact_root", return_value=canonical
                ),
                mock.patch.object(
                    installer, "_stage_artifact", return_value=drifted
                ),
                self.assertRaisesRegex(
                    installer.InstallError, "differs from the verified candidate"
                ),
            ):
                installer._publish_verified_candidate_artifact(
                    candidate,
                    platform="posix",
                    runner=installer.run_command,
                )

        escaped_descriptor = descriptor(canonical)
        escaped_descriptor["mcp_stdio_route"] = {
            **escaped_descriptor["mcp_stdio_route"],
            "launcher": str(self.root / "outside" / "run-mcp.sh"),
        }
        escaped = installer.PreparedArtifact(
            canonical,
            escaped_descriptor,
            candidate.plugin_tree_sha256,
        )
        with (
            mock.patch.object(
                installer, "default_artifact_root", return_value=canonical
            ),
            mock.patch.object(installer, "_stage_artifact", return_value=escaped),
            self.assertRaisesRegex(
                installer.InstallError, "escapes the plugin root"
            ),
        ):
            installer._publish_verified_candidate_artifact(
                candidate,
                platform="posix",
                runner=installer.run_command,
            )

    def test_candidate_install_routes_receipt_evidence_to_canonical_marketplace(self) -> None:
        self.prepare_artifact()
        installer = load_installer()
        candidate = installer.PreparedArtifact(
            self.root / "candidate",
            {"delivery_generation": {"generation": "fixture"}},
            "a" * 64,
        )
        canonical = installer.PreparedArtifact(
            self.root / "canonical",
            candidate.descriptor,
            candidate.plugin_tree_sha256,
        )
        receipt = {"receipt_sha256": "b" * 64, "python": installer.invoking_environment()}
        live = {"schema": "sulde-codex-promotion-prestate-v1"}

        with (
            mock.patch.object(
                installer, "_codex_host_preflight", return_value={"status": "clear"}
            ),
            mock.patch.object(
                installer, "_deployment_lock", return_value=nullcontext("lock")
            ),
            mock.patch.object(installer, "load_active_transaction", return_value=None),
            mock.patch.object(installer, "_assert_deployment_cas"),
            mock.patch.object(
                installer,
                "validate_staged_marketplace",
                return_value=candidate.descriptor,
            ),
            mock.patch.object(
                installer,
                "tree_digest",
                return_value=candidate.plugin_tree_sha256,
            ),
            mock.patch.object(
                installer, "_validated_candidate_receipt", return_value=receipt
            ) as validate_receipt,
            mock.patch.object(
                installer,
                "_publish_verified_candidate_artifact",
                return_value=canonical,
            ) as publish,
            mock.patch.object(
                installer, "_scheduler_actor_preflight", return_value={}
            ),
            mock.patch.object(
                installer, "_legacy_home_migration_source", return_value=None
            ),
            mock.patch.object(installer, "_legacy_memory_database", return_value=None),
            mock.patch.object(installer, "ensure_contract_identity_map", return_value=None),
            mock.patch.object(
                installer,
                "_install_locked",
                return_value={"status": "generation_verified"},
            ) as install_locked,
        ):
            result = installer.install(
                artifact=candidate.marketplace,
                kb_home=self.kb_home,
                codex="codex",
                platform="posix",
                prepared_artifact=candidate,
                candidate_receipt=receipt,
                expected_live_state=live,
            )

        self.assertEqual(result["status"], "generation_verified")
        validate_receipt.assert_called_once_with(
            receipt,
            prepared=installer.PreparedArtifact(
                candidate.marketplace.resolve(),
                candidate.descriptor,
                candidate.plugin_tree_sha256,
            ),
            expected_live_state=live,
            codex="codex",
            runner=installer.run_command,
        )
        canonical_candidate = installer.PreparedArtifact(
            candidate.marketplace.resolve(),
            candidate.descriptor,
            candidate.plugin_tree_sha256,
        )
        publish.assert_called_once_with(
            canonical_candidate,
            platform="posix",
            runner=installer.run_command,
        )
        self.assertEqual(install_locked.call_args.kwargs["artifact"], canonical.marketplace)
        self.assertEqual(
            install_locked.call_args.kwargs["prepared_artifact"], canonical
        )
        self.assertEqual(
            install_locked.call_args.kwargs["candidate_evidence"], canonical_candidate
        )

    def test_native_runtime_authority_executes_installed_broker_and_binds_generation(self) -> None:
        installer = load_installer()
        plugin = self.root / "installed-plugin"
        runtime_kb = plugin / "runtime" / "scripts" / "kb"
        runtime_kb.mkdir(parents=True)
        shutil.copy2(ROOT / "scripts" / "kb" / "agent-runtime.py", runtime_kb)
        shutil.copy2(ROOT / "scripts" / "kb" / "codex_cli_contract.py", runtime_kb)
        shutil.copy2(ROOT / "scripts" / "kb" / "native_agent_broker.py", runtime_kb)
        generation = {
            "generation": "fixture:runtime-generation",
            "runtime_tree_sha256": installer.tree_digest(plugin / "runtime"),
        }
        with mock.patch.dict(os.environ, {"SULDE_TEST_MODE": "1"}):
            authority = installer._installed_native_runtime_authority(
                plugin,
                generation,
                registry_codex=str(self.fake),
                runner=installer.run_command,
            )
        self.assertEqual(authority["runtime_generation"], generation["generation"])
        self.assertEqual(
            authority["runtime_tree_sha256"], generation["runtime_tree_sha256"]
        )
        self.assertEqual(
            authority["production_codex_executable"], str(self.fake.resolve())
        )
        self.assertEqual(
            authority["broker_sha256"],
            hashlib.sha256((runtime_kb / "native_agent_broker.py").read_bytes()).hexdigest(),
        )
        self.assertEqual(
            authority["codex_cli_contract_sha256"],
            hashlib.sha256(
                (runtime_kb / "codex_cli_contract.py").read_bytes()
            ).hexdigest(),
        )
        profile_spec = installer._permission_profile_spec()
        self.assertEqual(
            profile_spec,
            {
                "schema": "sulde-codex-permission-profile-spec-v1",
                "spec_version": 4,
                "profile_name": "sulde-owned-paths",
                "codex_parent_sandbox": "danger-full-access",
                "command_boundary": "pre-tool-use-updated-input-single-seatbelt-v1",
                "shell_startup_policy": "sealed-empty-zdotdir-v1",
                "non_command_write_tools": "deny",
                "filesystem_default_write": "deny",
                "owned_path_permission": "literal-file-write-star",
                "scratch_permission": "codex-agent-native-command-scratch-subpath",
                "network_enabled": False,
                "path_rendering": "physical-canonical-exact-owned-full-clone-v4",
                "native_destructive_boundary": "global-file-write-star-deny-v1",
            },
        )
        profile_digest = hashlib.sha256(
            installer._canonical_json_bytes(profile_spec)
        ).hexdigest()
        self.assertEqual(authority["permission_profile_spec_version"], 4)
        self.assertEqual(
            authority["permission_profile_spec_sha256"], profile_digest
        )
        for legacy_field, legacy_value in (
            ("spec_version", 1),
            ("path_rendering", "canonical-worktree-relative-v1"),
        ):
            with self.subTest(legacy_profile_field=legacy_field):
                legacy_profile = dict(profile_spec)
                legacy_profile[legacy_field] = legacy_value
                self.assertNotEqual(
                    authority["permission_profile_spec_sha256"],
                    hashlib.sha256(
                        installer._canonical_json_bytes(legacy_profile)
                    ).hexdigest(),
                )
        unsigned = dict(authority)
        digest = unsigned.pop("authority_sha256")
        self.assertEqual(
            digest,
            hashlib.sha256(installer._canonical_json_bytes(unsigned)).hexdigest(),
        )
        unsigned["runtime_generation"] = "rollback:generation"
        self.assertNotEqual(
            digest,
            hashlib.sha256(installer._canonical_json_bytes(unsigned)).hexdigest(),
        )

    def test_native_authority_load_smoke_rejects_post_seal_bytecode_mutation(self) -> None:
        installer = load_installer()
        plugin = self.root / "installed-plugin-bytecode-mutation"
        runtime = plugin / "runtime"
        runtime_kb = runtime / "scripts" / "kb"
        runtime_kb.mkdir(parents=True)
        agent_runtime = runtime_kb / "agent-runtime.py"
        agent_runtime.write_text("# sealed fixture runtime\n", encoding="utf-8")
        runtime_sha256 = installer.tree_digest(runtime)
        sealed = {
            "schema": installer.DELIVERY_GENERATION_SCHEMA,
            "schema_version": 1,
            "provider": "codex",
            "plugin_version": installer.plugin_version(),
            "platform": "posix",
            "runtime_tree_sha256": runtime_sha256,
            "generation": f"{installer.plugin_version()}:{runtime_sha256}",
        }
        descriptor = plugin / ".codex-plugin" / installer.DELIVERY_GENERATION_NAME
        descriptor.parent.mkdir(parents=True)
        descriptor.write_text(
            json.dumps(sealed, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        authority = {"authority_sha256": "a" * 64}

        def mutating_runner(command, **_kwargs):
            bytecode = runtime_kb / "__pycache__" / "agent-runtime.cpython-313.pyc"
            bytecode.parent.mkdir()
            bytecode.write_bytes(b"post-seal mutation")
            return installer.CommandResult(
                tuple(command),
                0,
                json.dumps(authority),
                "",
            )

        with self.assertRaisesRegex(
            installer.InstallError,
            "executable Python bytecode",
        ):
            installer._installed_native_authority_load_smoke(
                plugin,
                self.kb_home,
                sealed,
                authority,
                runner=mutating_runner,
            )

    def test_production_native_authority_load_smoke_avoids_entrypoint_bytecode(
        self,
    ) -> None:
        installer = load_installer()
        plugin = self.root / "installed-plugin-production-load"
        runtime = plugin / "runtime"
        runtime_kb = runtime / "scripts" / "kb"
        runtime_kb.mkdir(parents=True)
        authority = {
            "authority_sha256": "b" * 64,
            "loaded_by": "installed-runtime",
        }
        agent_runtime = runtime_kb / "agent-runtime.py"
        agent_runtime.write_text(
            "def load_installed_native_authority():\n"
            f"    return {authority!r}\n",
            encoding="utf-8",
        )
        runtime_sha256 = installer.tree_digest(runtime)
        sealed = {
            "schema": installer.DELIVERY_GENERATION_SCHEMA,
            "schema_version": 1,
            "provider": "codex",
            "plugin_version": installer.plugin_version(),
            "platform": "posix",
            "runtime_tree_sha256": runtime_sha256,
            "generation": f"{installer.plugin_version()}:{runtime_sha256}",
        }
        descriptor = plugin / ".codex-plugin" / installer.DELIVERY_GENERATION_NAME
        descriptor.parent.mkdir(parents=True)
        descriptor.write_text(
            json.dumps(sealed, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        with mock.patch.dict(os.environ, {"SULDE_TEST_MODE": "0"}):
            evidence = installer._installed_native_authority_load_smoke(
                plugin,
                self.kb_home,
                sealed,
                authority,
                runner=installer.run_command,
            )

        self.assertTrue(evidence["authority_load_verified"])
        self.assertFalse(list(runtime.rglob("__pycache__")))
        self.assertFalse(list(runtime.rglob("*.pyc")))

    def test_native_runtime_authority_seal_and_recovery_are_alias_independent(self) -> None:
        installer = load_installer()
        plugin = self.root / "installed-plugin-alias"
        runtime_kb = plugin / "runtime" / "scripts" / "kb"
        runtime_kb.mkdir(parents=True)
        shutil.copy2(ROOT / "scripts" / "kb" / "agent-runtime.py", runtime_kb)
        shutil.copy2(ROOT / "scripts" / "kb" / "codex_cli_contract.py", runtime_kb)
        shutil.copy2(ROOT / "scripts" / "kb" / "native_agent_broker.py", runtime_kb)
        generation = {
            "generation": "fixture:stable-runtime-generation",
            "runtime_tree_sha256": installer.tree_digest(plugin / "runtime"),
        }
        alias = self.root / "codex-alias"
        alias.symlink_to(self.fake)
        with mock.patch.dict(os.environ, {"SULDE_TEST_MODE": "1"}):
            sealed = installer._installed_native_runtime_authority(
                plugin,
                generation,
                registry_codex=str(alias),
                runner=installer.run_command,
            )
            recovery = installer._installed_native_runtime_authority(
                plugin.resolve(),
                dict(generation),
                registry_codex=str(self.fake.resolve()),
                runner=installer.run_command,
            )
        self.assertEqual(
            {key for key in sealed if sealed[key] != recovery[key]},
            set(),
        )
        self.assertEqual(sealed, recovery)

        previous_projection = dict(sealed)
        previous_projection["production_codex_executable"] = str(alias)
        previous_projection["authority_sha256"] = hashlib.sha256(
            installer._canonical_json_bytes(
                {
                    key: value
                    for key, value in previous_projection.items()
                    if key != "authority_sha256"
                }
            )
        ).hexdigest()
        self.assertEqual(
            {
                key
                for key in previous_projection
                if previous_projection[key] != recovery[key]
            },
            {"production_codex_executable", "authority_sha256"},
        )

    def test_production_native_authority_binds_canonical_installation_target(self) -> None:
        installer = load_installer()
        plugin = self.root / "installed-plugin-production-alias"
        runtime_kb = plugin / "runtime" / "scripts" / "kb"
        runtime_kb.mkdir(parents=True)
        shutil.copy2(ROOT / "scripts" / "kb" / "agent-runtime.py", runtime_kb)
        shutil.copy2(ROOT / "scripts" / "kb" / "codex_cli_contract.py", runtime_kb)
        shutil.copy2(ROOT / "scripts" / "kb" / "native_agent_broker.py", runtime_kb)
        generation = {
            "generation": "fixture:production-runtime-generation",
            "runtime_tree_sha256": installer.tree_digest(plugin / "runtime"),
        }
        audited_alias = self.root / "audited-codex-0.153"
        audited_alias.symlink_to(self.fake)
        smoke = {
            "version": installer.AUDITED_CODEX_VERSION,
            "help_observation_sha256": hashlib.sha256(b"audited help").hexdigest(),
        }
        with (
            mock.patch.dict(os.environ, {"SULDE_TEST_MODE": "0"}),
            mock.patch.object(
                installer,
                "_codex_cli_installed_smoke",
                return_value=smoke,
            ),
        ):
            sealed = installer._installed_native_runtime_authority(
                plugin,
                generation,
                registry_codex=str(audited_alias),
                runner=installer.run_command,
            )
            recovery = installer._installed_native_runtime_authority(
                plugin.resolve(),
                dict(generation),
                registry_codex=str(self.fake.resolve()),
                runner=installer.run_command,
            )
        self.assertEqual(sealed, recovery)
        self.assertEqual(
            sealed["production_codex_executable"],
            str(self.fake.resolve()),
        )
        self.assertEqual(
            sealed["production_codex_resolved_executable"],
            str(self.fake.resolve()),
        )
        self.assertEqual(sealed["codex_version"], "codex-cli 0.154.0")

    def test_recovery_rejects_recomputed_native_authority_drift(self) -> None:
        installer = load_installer()
        plugin = self.root / "installed-plugin-drift"
        runtime_kb = plugin / "runtime" / "scripts" / "kb"
        runtime_kb.mkdir(parents=True)
        shutil.copy2(ROOT / "scripts" / "kb" / "agent-runtime.py", runtime_kb)
        shutil.copy2(ROOT / "scripts" / "kb" / "codex_cli_contract.py", runtime_kb)
        shutil.copy2(ROOT / "scripts" / "kb" / "native_agent_broker.py", runtime_kb)
        generation = {
            "generation": "fixture:sealed-runtime-generation",
            "runtime_tree_sha256": installer.tree_digest(plugin / "runtime"),
        }
        with mock.patch.dict(os.environ, {"SULDE_TEST_MODE": "1"}):
            sealed = installer._installed_native_runtime_authority(
                plugin,
                generation,
                registry_codex=str(self.fake),
                runner=installer.run_command,
            )
        deployment = {
            "native_runtime_authority": sealed,
            "native_runtime_authority_sha256": sealed["authority_sha256"],
        }
        installer._verify_recomputed_native_runtime_authority(deployment, sealed)

        def recompute(selected_generation=generation):
            with mock.patch.dict(os.environ, {"SULDE_TEST_MODE": "1"}):
                return installer._installed_native_runtime_authority(
                    plugin,
                    selected_generation,
                    registry_codex=str(self.fake),
                    runner=installer.run_command,
                )

        def reject(recomputed):
            with self.assertRaisesRegex(
                installer.InstallError,
                "recovery postcondition native runtime authority differs",
            ):
                installer._verify_recomputed_native_runtime_authority(
                    deployment,
                    recomputed,
                )

        resigned_help = dict(sealed)
        resigned_help["codex_help_observation_sha256"] = hashlib.sha256(
            b"attacker-resigned-help-observation"
        ).hexdigest()
        unsigned_resigned_help = dict(resigned_help)
        unsigned_resigned_help.pop("authority_sha256")
        resigned_help["authority_sha256"] = hashlib.sha256(
            installer._canonical_json_bytes(unsigned_resigned_help)
        ).hexdigest()
        with self.subTest(drift="re-signed-help-authority"):
            reject(resigned_help)

        for label, target in (
            ("broker", runtime_kb / "native_agent_broker.py"),
            ("shared contract", runtime_kb / "codex_cli_contract.py"),
            ("runtime", runtime_kb / "agent-runtime.py"),
            ("CLI", self.fake),
        ):
            with self.subTest(drift=label):
                original = target.read_bytes()
                try:
                    target.write_bytes(original + b"\n# genuine recovery drift\n")
                    reject(recompute())
                finally:
                    target.write_bytes(original)

        changed_profile = installer._permission_profile_spec()
        changed_profile["test_recovery_drift"] = True
        with self.subTest(drift="profile"), mock.patch.object(
            installer,
            "_permission_profile_spec",
            return_value=changed_profile,
        ):
            reject(recompute())

        changed_generation = dict(generation)
        changed_generation["generation"] = "fixture:changed-generation"
        with self.subTest(drift="generation"):
            reject(recompute(changed_generation))

    def test_previous_live_session_path_is_pinned_to_pre_switch_bytes(self) -> None:
        installer = load_installer()
        installed = self.root / "new cache"
        previous = self.root / "old cache"
        snapshot = self.root / "snapshot"
        new_hook = installed / "scripts" / "user-prompt-submit.py"
        old_hook = snapshot / "scripts" / "user-prompt-submit.py"
        new_hook.parent.mkdir(parents=True)
        old_hook.parent.mkdir(parents=True)
        new_hook.write_text("new hook\n", encoding="utf-8")
        old_hook.write_text("old hook\n", encoding="utf-8")

        evidence = installer._preserve_previous_install_path(
            previous,
            snapshot,
            current_install=installed,
        )

        self.assertIsNotNone(evidence)
        self.assertFalse(previous.is_symlink())
        self.assertEqual(
            (previous / "scripts" / "user-prompt-submit.py").read_text(encoding="utf-8"),
            "old hook\n",
        )
        self.assertEqual(evidence["mode"], "pinned_copy")

        repeated = installer._preserve_previous_install_path(
            previous,
            snapshot,
            current_install=installed,
        )
        self.assertEqual(repeated["mode"], "existing_pinned_copy")

        (previous / "scripts" / "user-prompt-submit.py").write_text(
            "unexpected new bytes\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(installer.InstallError, "reused with different bytes"):
            installer._preserve_previous_install_path(
                previous,
                snapshot,
                current_install=installed,
            )

    def test_previous_paths_ignore_display_source_and_select_canonical_cache(self) -> None:
        installer = load_installer()
        registered = self.root / "artifact" / "plugins" / "sulde"
        cached = (
            self.root
            / "codex-home"
            / "plugins"
            / "cache"
            / "sulde-local"
            / "sulde"
            / "1.2.3"
        )
        registered.mkdir(parents=True)
        cached.mkdir(parents=True)
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.root / "codex-home")}):
            paths = installer._previous_install_paths(("1.2.3", registered))
        self.assertEqual(paths, (cached,))

    def test_legacy_cache_hook_entrypoints_rebind_and_roll_back_exactly(self) -> None:
        installer = load_installer()
        current = self.root / "current"
        legacy = (
            self.root
            / "codex-home"
            / "plugins"
            / "cache"
            / "sulde-local"
            / "sulde"
            / "0.1.0"
        )
        for plugin, version, marker in (
            (current, "0.2.0", "current"),
            (legacy, "0.1.0", "legacy"),
        ):
            descriptor = plugin / ".codex-plugin" / "plugin.json"
            descriptor.parent.mkdir(parents=True)
            descriptor.write_text(
                json.dumps({"name": "sulde", "version": version}),
                encoding="utf-8",
            )
            for relative in installer.LIVE_SESSION_BRIDGE_FILES:
                hook = plugin / relative
                hook.parent.mkdir(parents=True, exist_ok=True)
                hook.write_text(f"{marker}:{relative.as_posix()}\n", encoding="utf-8")
            prompt = plugin / "scripts" / "user-prompt-submit.py"
            prompt.write_text(f"{marker}:static adapter\n", encoding="utf-8")
            skill = plugin / "skills" / "intent-guardian" / "SKILL.md"
            skill.parent.mkdir(parents=True, exist_ok=True)
            skill.write_text(f"{marker}:static skill\n", encoding="utf-8")

        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.root / "codex-home")}):
            discovered = installer._legacy_install_paths(())
        self.assertEqual(discovered, (legacy,))
        snapshots = installer._snapshot_plugin_trees(
            discovered,
            self.root / "legacy-snapshots",
        )
        shutil.rmtree(legacy)
        legacy.symlink_to(current, target_is_directory=True)
        installer._restore_previous_install_path(legacy, snapshots[0][1])
        evidence = installer._install_live_session_bridges(discovered, current)
        self.assertEqual(evidence[0]["mode"], "stable_current_runtime_bridge")
        for relative in installer.LIVE_SESSION_BRIDGE_FILES:
            self.assertEqual(
                (legacy / relative).read_bytes(),
                (current / relative).read_bytes(),
            )
        self.assertEqual(
            (legacy / "skills" / "intent-guardian" / "SKILL.md").read_text(
                encoding="utf-8"
            ),
            "legacy:static skill\n",
        )

        (legacy / "skills" / "intent-guardian" / "SKILL.md").write_text(
            "mutated static skill\n",
            encoding="utf-8",
        )
        installer._restore_previous_install_path(legacy, snapshots[0][1])
        for relative in installer.LIVE_SESSION_BRIDGE_FILES:
            self.assertEqual(
                (legacy / relative).read_text(encoding="utf-8"),
                f"legacy:{relative.as_posix()}\n",
            )

    def test_partial_legacy_cache_is_recoverable_only_from_exact_artifact(self) -> None:
        installer = load_installer()
        version = "0.2.5+codex.20260816085221-d23c66e4b9"
        cache = (
            self.root
            / "codex-home"
            / "plugins"
            / "cache"
            / "sulde-local"
            / "sulde"
            / version
        )
        for relative in installer.LIVE_SESSION_BRIDGE_FILES:
            hook = cache / relative
            hook.parent.mkdir(parents=True, exist_ok=True)
            hook.write_text("partial bridge\n", encoding="utf-8")

        artifacts = self.root / "artifacts"
        artifact = (
            artifacts
            / f"sulde-{installer.product_version()}-{version.replace('+', '-')}"
            / "codex"
            / "plugins"
            / "sulde"
        )
        required_content = {
            Path(".codex-plugin/plugin.json"): json.dumps(
                {"name": "sulde", "version": version}
            ),
            Path("scripts/user-prompt-submit.py"): "adapter\n",
            Path("runtime/scripts/kb/intent-guardian.py"): "runtime\n",
            Path("skills/intent-guardian/SKILL.md"): "skill\n",
            Path("scripts/run-hook.sh"): "posix bridge\n",
            Path("scripts/run-hook.ps1"): "windows bridge\n",
        }
        for relative, content in required_content.items():
            path = artifact / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.root / "codex-home")}):
            sources = installer._legacy_install_sources(
                (),
                artifacts_root=artifacts,
            )
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].target, cache)
        self.assertEqual(sources[0].source, artifact)
        self.assertEqual(sources[0].mode, "persistent_artifact_recovery")

        artifact_descriptor = artifact / ".codex-plugin" / "plugin.json"
        artifact_descriptor.write_text(
            json.dumps({"name": "sulde", "version": "mismatched"}),
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.root / "codex-home")}):
            self.assertEqual(
                installer._legacy_install_sources((), artifacts_root=artifacts),
                (),
            )
        artifact_descriptor.write_text(
            json.dumps({"name": "sulde", "version": version}),
            encoding="utf-8",
        )
        installer._restore_previous_install_path(cache, sources[0].source)
        self.assertEqual(
            json.loads(
                (cache / ".codex-plugin" / "plugin.json").read_text(
                    encoding="utf-8"
                )
            )["version"],
            version,
        )

    def test_retired_whole_tree_symlink_requires_exact_artifact_and_never_relinks(self) -> None:
        installer = load_installer()
        version = "0.2.5+codex.20260816090000-symlink"
        cache_root = (
            self.root
            / "codex-home/plugins/cache/sulde-local/sulde"
        )
        donor = cache_root / "current-real"
        donor.mkdir(parents=True)
        legacy = cache_root / version
        legacy.symlink_to(donor, target_is_directory=True)
        artifacts = self.root / "artifacts"
        artifact = (
            artifacts
            / f"sulde-{installer.product_version()}-{version.replace('+', '-')}"
            / "codex/plugins/sulde"
        )
        required_content = {
            Path(".codex-plugin/plugin.json"): json.dumps(
                {"name": "sulde", "version": version}
            ),
            Path("scripts/user-prompt-submit.py"): "adapter\n",
            Path("runtime/scripts/kb/intent-guardian.py"): "runtime\n",
            Path("skills/intent-guardian/SKILL.md"): "static old skill\n",
            Path("scripts/run-hook.sh"): "posix bridge\n",
            Path("scripts/run-hook.ps1"): "windows bridge\n",
        }
        for relative, content in required_content.items():
            path = artifact / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.root / "codex-home")}):
            sources = installer._legacy_install_sources(
                (), artifacts_root=artifacts
            )
        recovered = next(row for row in sources if row.target == legacy)
        self.assertEqual(
            recovered.mode, "retired_whole_tree_symlink_recovery"
        )
        installer._restore_previous_install_path(legacy, recovered.source)
        self.assertTrue(legacy.is_dir())
        self.assertFalse(legacy.is_symlink())
        self.assertEqual(
            (legacy / "skills/intent-guardian/SKILL.md").read_text(
                encoding="utf-8"
            ),
            "static old skill\n",
        )
        self.assertFalse(hasattr(installer, "_restore_legacy_symlink"))

        missing = cache_root / "0.0.1-missing-artifact"
        missing.symlink_to(donor, target_is_directory=True)
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.root / "codex-home")}):
            with self.assertRaisesRegex(installer.InstallError, "no same-version"):
                installer._legacy_install_sources((), artifacts_root=artifacts)

        donor_content = {
            Path(".codex-plugin/plugin.json"): json.dumps(
                {"name": "sulde", "version": donor.name}
            ),
            Path("scripts/run-hook.sh"): "posix donor bridge\n",
            Path("scripts/run-hook.ps1"): "windows donor bridge\n",
        }
        for relative, content in donor_content.items():
            path = donor / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.root / "codex-home")}):
            with self.assertRaisesRegex(installer.InstallError, "no same-version"):
                installer._legacy_install_sources((donor,), artifacts_root=artifacts)
        self.assertTrue(missing.is_symlink())

    def test_install_rebinds_every_preexisting_legacy_cache(self) -> None:
        legacy = (
            self.root
            / "codex-home"
            / "plugins"
            / "cache"
            / "sulde-local"
            / "sulde"
            / "0.0.9"
        )
        descriptor = legacy / ".codex-plugin" / "plugin.json"
        descriptor.parent.mkdir(parents=True)
        descriptor.write_text(
            json.dumps({"name": "sulde", "version": "0.0.9"}),
            encoding="utf-8",
        )
        for relative in (Path("scripts/run-hook.sh"), Path("scripts/run-hook.ps1")):
            hook = legacy / relative
            hook.parent.mkdir(parents=True, exist_ok=True)
            hook.write_text("legacy hook\n", encoding="utf-8")

        completed = self.run_installer()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(len(result["live_session_bridges"]), 1)
        self.assertTrue(result["hook_restart_required"])
        self.assertTrue(result["hook_hot_rebind_available"])
        self.assertEqual(
            result["legacy_cache_restorations"][0]["mode"],
            "controlled_retired_alias",
        )
        self.assertEqual(
            Path(result["live_session_bridges"][0]["path"]).resolve(),
            legacy.resolve(),
        )
        installed = Path(result["installed_path"])
        for relative in (Path("scripts/run-hook.sh"), Path("scripts/run-hook.ps1")):
            self.assertEqual(
                (legacy / relative).read_bytes(),
                (installed / relative).read_bytes(),
            )

    def test_install_rejects_retired_alias_to_different_version_cache(self) -> None:
        old_version = "0.2.5+codex.old-frozen"
        cache_root = (
            self.root
            / "codex-home/plugins/cache/sulde-local/sulde"
        )
        previous = cache_root / old_version
        previous_files = {
            Path(".codex-plugin/plugin.json"): json.dumps(
                {"name": "sulde", "version": old_version}
            ),
            Path("scripts/user-prompt-submit.py"): "old adapter\n",
            Path("scripts/run-hook.sh"): "old posix bridge\n",
            Path("scripts/run-hook.ps1"): "old windows bridge\n",
        }
        for relative, content in previous_files.items():
            path = previous / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        alias = cache_root / "0.1.0-retired-alias"
        alias.symlink_to(previous, target_is_directory=True)
        self.state.write_text(
            json.dumps(
                {
                    "marketplace": None,
                    "installed": str(previous),
                    "version": old_version,
                }
            ),
            encoding="utf-8",
        )

        completed = self.run_installer()
        self.assertEqual(completed.returncode, 1)
        self.assertIn("no same-version immutable artifact", completed.stderr)
        self.assertTrue(alias.is_symlink())
        self.assertEqual(alias.resolve(), previous.resolve())
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(state["installed"], str(previous))

    def test_known_retired_actor_is_only_mutated_inside_atomic_transaction(self) -> None:
        launchagents = self.root / "Library" / "LaunchAgents"
        launchagents.mkdir(parents=True)
        retired = launchagents / "com.sulde.codex-cache-repair.plist"
        retired.write_text("retired actor\n", encoding="utf-8")
        completed = self.run_installer(
            loaded_labels=("com.sulde.codex-cache-repair",)
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        preflight = result["scheduler_actor_preflight"]
        self.assertEqual(preflight["status"], "retirement_required")
        self.assertEqual(
            preflight["retirement_labels"], ["com.sulde.codex-cache-repair"]
        )
        self.assertFalse(retired.exists())
        archived = (
            launchagents
            / ".sulde-retired/archive/com.sulde.codex-cache-repair.plist"
        )
        self.assertTrue(archived.is_file())
        self.assertEqual(archived.read_text(encoding="utf-8"), "retired actor\n")
        tombstone = (
            launchagents
            / ".sulde-retired/tombstones/com.sulde.codex-cache-repair.json"
        )
        self.assertTrue(tombstone.is_file())
        self.assertEqual(
            json.loads(tombstone.read_text(encoding="utf-8"))["status"],
            "retired",
        )
        self.assertTrue(self.state.exists())
        self.assertTrue(self.artifact.exists())
        self.assertEqual(result["scheduler_generation"]["status"], "generation_verified")

    def test_unknown_actor_still_blocks_before_registry_switch(self) -> None:
        launchagents = self.root / "Library" / "LaunchAgents"
        launchagents.mkdir(parents=True)
        unknown = launchagents / "com.sulde.codex-cache-repair-v2.plist"
        unknown.write_text("unknown actor\n", encoding="utf-8")
        completed = self.run_installer(
            loaded_labels=("com.sulde.codex-cache-repair-v2",)
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("unknown Sulde LaunchAgents", completed.stderr)
        self.assertTrue(unknown.is_file())
        self.assertFalse(self.state.exists())
        self.assertTrue(self.artifact.exists())

    def test_loaded_actor_without_rollback_plist_blocks_before_registry_switch(self) -> None:
        completed = self.run_installer(
            loaded_labels=("com.sulde.daily-distill",)
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("have no rollback-safe plist", completed.stderr)
        self.assertFalse(self.state.exists())
        self.assertFalse((self.kb_home / "deployment-generation.json").exists())
        self.assertTrue(self.artifact.exists())

    def test_live_deployment_lock_blocks_concurrent_installer(self) -> None:
        lock = self.kb_home / ".deployment.lock"
        lock.mkdir(parents=True)
        (lock / "owner.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "pid": os.getpid(),
                    "token": "fixture-live-owner",
                }
            ),
            encoding="utf-8",
        )
        completed = self.run_installer()
        self.assertEqual(completed.returncode, 1)
        self.assertIn("another plugin or scheduler deployment owns", completed.stderr)
        self.assertFalse(self.state.exists())

    def test_stale_deployment_lock_is_reclaimed_without_touching_other_state(self) -> None:
        installer = load_installer()
        lock = self.kb_home / ".deployment.lock"
        lock.mkdir(parents=True)
        (lock / "owner.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "pid": 999_999_999,
                    "token": "fixture-dead-owner",
                }
            ),
            encoding="utf-8",
        )
        sentinel = self.kb_home / "unrelated.txt"
        sentinel.write_text("preserve\n", encoding="utf-8")
        with installer._deployment_lock(self.kb_home):
            current = json.loads(
                (lock / "owner.json").read_text(encoding="utf-8")
            )
            self.assertEqual(current["pid"], os.getpid())
            self.assertNotEqual(current["token"], "fixture-dead-owner")
        self.assertFalse(lock.exists())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve\n")


if __name__ == "__main__":
    unittest.main()
