from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from intent_guardian import IntentGuardianError, normalize_hook_event  # noqa: E402
from intent_guardian_parts.events import _effect_resource_identity  # noqa: E402
from resource_adapters import figma_use_script_is_read_only  # noqa: E402


class TypedResourceIdentityTests(unittest.TestCase):
    def test_registered_figma_download_is_read_only(self) -> None:
        event = normalize_hook_event(
            {
                "tool_name": "mcp__figma__download_assets",
                "tool_input": {"node_id": "1:2"},
            },
            phase="started",
            provider="codex",
        )

        self.assertEqual(event["capability"], "mcp:figma:download_assets")
        self.assertEqual(event["effect"], "read")

    def test_registered_figma_mutation_does_not_depend_on_verb_guessing(self) -> None:
        event = normalize_hook_event(
            {
                "tool_name": "mcp__figma__use_figma",
                "tool_input": {"node_id": "1:2"},
            },
            phase="started",
            provider="codex",
        )

        self.assertEqual(event["capability"], "mcp:figma:use_figma")
        self.assertEqual(event["effect"], "external_write")

    def test_figma_server_aliases_remain_execution_passthrough(self) -> None:
        for tool_name in (
            "mcp__figma_desktop__mutate_selection",
            "mcp__codex_apps__figma_use_figma",
            "mcp__codex_apps__figma_whoami",
        ):
            with self.subTest(tool_name=tool_name):
                event = normalize_hook_event(
                    {
                        "tool_name": tool_name,
                        "tool_input": {"fileKey": "File", "node_id": "1:2"},
                    },
                    phase="started",
                    provider="codex",
                )

                self.assertEqual(
                    event["supervision_domain"], "execution_passthrough"
                )
                self.assertEqual(event["execution_domain"], "figma")

    def test_use_figma_proven_inspection_script_is_read_only(self) -> None:
        event = normalize_hook_event(
            {
                "tool_name": "mcp__codex_apps__figma_use_figma",
                "tool_input": {
                    "fileKey": "0G32qTbFLqMfW5gG8wvv8X",
                    "description": "Inspect pages and fonts",
                    "skillNames": "figma-use",
                    "code": (
                        "const pages=figma.root.children.map(p=>({id:p.id,name:p.name}));"
                        "const fonts=await figma.listAvailableFontsAsync();"
                        "return {pages,fonts:fonts.filter(f=>"
                        "[\"Inter\"].includes(f.fontName.family)).slice(0,80)};"
                    ),
                },
            },
            phase="started",
            provider="codex",
        )

        self.assertEqual(event["effect"], "read")
        self.assertEqual(event["typed_resource"]["status"], "classified")
        self.assertEqual(event["typed_resource"]["effect"], "read")
        self.assertEqual(event["verification_kind"], "none")
        self.assertEqual(event["supervision_domain"], "execution_passthrough")
        self.assertEqual(event["execution_domain"], "figma")

    def test_figma_read_audit_distinguishes_comparison_from_assignment(self) -> None:
        self.assertTrue(
            figma_use_script_is_read_only(
                'const page=figma.root.children.find(p=>p.name === "R22"); return page?.id;'
            )
        )
        self.assertFalse(
            figma_use_script_is_read_only(
                'const page=figma.root.children[0]; page.name = "R22"; return page.id;'
            )
        )

    def test_use_figma_unknown_or_mutating_script_remains_external_write(self) -> None:
        scripts = (
            "const frame=figma.createFrame(); return {id:frame.id};",
            "const node=await figma.getNodeByIdAsync(\"1:2\"); node.name=\"changed\";",
            "const node=await figma.getNodeByIdAsync(\"1:2\"); mutate(node);",
            "const method=\"remove\"; node[method]();",
        )
        for code in scripts:
            with self.subTest(code=code):
                event = normalize_hook_event(
                    {
                        "tool_name": "mcp__figma__use_figma",
                        "tool_input": {
                            "fileKey": "File_123",
                            "description": "script",
                            "skillNames": "figma-use",
                            "code": code,
                        },
                    },
                    phase="started",
                    provider="codex",
                )
                self.assertEqual(event["effect"], "external_write")
                self.assertEqual(event["typed_resource"]["status"], "rejected")

    def test_codex_apps_namespace_normalizes_to_the_real_app(self) -> None:
        event = normalize_hook_event(
            {
                "tool_name": "mcp__codex_apps__figma__get_screenshot",
                "tool_input": {"fileKey": "File", "nodeId": "1:2"},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(event["server"], "figma")
        self.assertEqual(event["action"], "get_screenshot")
        self.assertEqual(event["capability"], "mcp:figma:get_screenshot")
        self.assertEqual(event["effect"], "read")
        self.assertEqual(event["typed_resource"]["kind"], "figma")

    def test_git_hook_events_are_execution_passthrough_without_typed_resource(self) -> None:
        for command in (
            "git status",
            "git push --force origin main",
            "git worktree add .worktrees/task task/one",
            "/usr/bin/git -C /tmp commit -am release",
            "git status && git add -A",
        ):
            with self.subTest(command=command):
                event = normalize_hook_event(
                    {"tool_name": "Bash", "tool_input": {"command": command}},
                    phase="started",
                    provider="codex",
                )
                self.assertEqual(event["supervision_domain"], "execution_passthrough")
                self.assertEqual(event["execution_domain"], "git")
                self.assertEqual(event["uncertainty_kind"], "execution_passthrough")
                self.assertNotIn("typed_resource", event)
                self.assertNotIn("git_resource_context", event)
                self.assertNotIn("write_targets", event)

    def test_git_passthrough_does_not_call_retired_git_classifiers(self) -> None:
        from intent_guardian_parts import resources as resources_module

        with (
            mock.patch.object(
                resources_module,
                "_git_invocation",
                side_effect=AssertionError("retired Git parser was called"),
            ),
            mock.patch.object(
                resources_module,
                "_git_ref_observation",
                side_effect=AssertionError("retired Git ref observer was called"),
            ),
            mock.patch.object(
                resources_module,
                "_classify_hook_resource",
                side_effect=AssertionError("typed adapter was called for Git"),
            ),
        ):
            event = normalize_hook_event(
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": "git -C /repo worktree add task branch"},
                },
                phase="started",
                provider="codex",
            )
        self.assertEqual(event["supervision_domain"], "execution_passthrough")

    def test_mixed_git_shell_command_retains_non_git_effect(self) -> None:
        event = normalize_hook_event(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git status | tee status.txt"},
            },
            phase="started",
            provider="codex",
        )
        self.assertNotIn("supervision_domain", event)
        self.assertEqual(event["effect"], "local_write")
        self.assertEqual(event["write_targets"], ["status.txt"])

    def test_unregistered_mcp_retains_legacy_fallback(self) -> None:
        read_event = normalize_hook_event(
            {
                "tool_name": "mcp__legacy__get_document",
                "tool_input": {"uri": "doc://one"},
            },
            phase="started",
            provider="codex",
        )
        unknown_event = normalize_hook_event(
            {
                "tool_name": "mcp__legacy__frobnicate",
                "tool_input": {"uri": "doc://one"},
            },
            phase="started",
            provider="codex",
        )

        self.assertEqual(read_event["effect"], "read")
        self.assertEqual(unknown_event["effect"], "unknown")

    def test_path_uri_mcp_git_and_opaque_bindings_are_complete(self) -> None:
        digest = hashlib.sha256(b"operation").hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "hook.sh"
            script.write_text("exit 0\n", encoding="utf-8")
            contract = {"workspace_root": str(root)}

            path_event = normalize_hook_event(
                {
                    "tool_name": "Bash",
                    "cwd": str(root),
                    "tool_input": {"command": f"/bin/sh -n {script}"},
                },
                phase="started",
                provider="codex",
            )
            path_key, path_base, path_context, path_relation = (
                _effect_resource_identity(contract, path_event)
            )
            self.assertTrue(path_key.startswith("v2:path:"))
            self.assertEqual(path_base, str(root))
            self.assertEqual(path_context, {})
            self.assertEqual(path_relation["arguments_digest"], path_event["arguments_digest"])

            uri_event = {
                "kind": "tool",
                "effect": "read",
                "target": "https://example.invalid/document/1",
                "arguments_digest": digest,
                "resource_base": str(root),
            }
            uri_key, uri_base, uri_context, _ = _effect_resource_identity(
                contract, uri_event
            )
            self.assertTrue(uri_key.startswith("v2:uri:"))
            self.assertEqual((uri_base, uri_context), ("", {}))

            mcp_event = normalize_hook_event(
                {
                    "tool_name": "mcp__docs__update_document",
                    "tool_input": {"uri": "doc://resume", "content": "new"},
                },
                phase="started",
                provider="codex",
            )
            mcp_key, mcp_base, mcp_context, mcp_relation = (
                _effect_resource_identity(contract, mcp_event)
            )
            self.assertTrue(mcp_key.startswith("v2:mcp:"))
            self.assertEqual(mcp_base, "")
            self.assertEqual(
                mcp_context,
                {
                    "server": "docs",
                    "resource_kind": "document",
                    "identifier": "doc://resume",
                },
            )
            self.assertEqual(mcp_relation["arguments_digest"], mcp_event["arguments_digest"])

            git_event = {
                "kind": "tool",
                "effect": "external_write",
                "target": "git-ref:" + "b" * 64 + ":refs/heads/main",
                "arguments_digest": digest,
                "resource_base": str(root),
                "git_resource_context": {
                    "remote": "b" * 64,
                    "ref": "refs/heads/main",
                    "oid": "c" * 40,
                },
            }
            git_key, git_base, git_context, git_relation = (
                _effect_resource_identity(contract, git_event)
            )
            self.assertTrue(git_key.startswith("v2:git:"))
            self.assertEqual(git_base, "")
            self.assertEqual(git_context, git_event["git_resource_context"])
            self.assertRegex(git_relation["verification_sha256"], r"^[0-9a-f]{64}$")

            opaque_event = {
                "kind": "tool",
                "effect": "unknown",
                "target": "[command:opaque]",
                "arguments_digest": digest,
                "resource_base": str(root),
            }
            opaque_key, opaque_base, opaque_context, _ = _effect_resource_identity(
                contract, opaque_event
            )
            self.assertEqual(opaque_key, "v2:opaque:[command:opaque]")
            self.assertEqual(opaque_base, "")
            self.assertEqual(
                opaque_context,
                {"schema": "exact", "value": "[command:opaque]"},
            )

    def test_mcp_identity_missing_identifier_fails_closed(self) -> None:
        event = normalize_hook_event(
            {
                "tool_name": "mcp__docs__update_document",
                "tool_input": {"content": "new"},
            },
            phase="started",
            provider="codex",
        )
        with self.assertRaisesRegex(IntentGuardianError, "MCP resource identity"):
            _effect_resource_identity({"workspace_root": str(ROOT)}, event)


if __name__ == "__main__":
    unittest.main()
