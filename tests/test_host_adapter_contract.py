from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts" / "kb"
ADAPTER_DIR = ROOT / "integrations" / "codex" / "plugins" / "sulde" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ADAPTER_DIR))

from intent_guardian import (  # noqa: E402
    GuardianSession,
    default_contract,
    load_contract,
    normalize_hook_event,
    write_contract,
)


def load_adapter(filename: str):
    name = "test_" + filename.replace("-", "_").replace(".", "_")
    spec = importlib.util.spec_from_file_location(name, ADAPTER_DIR / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load adapter {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PRE_ADAPTER = load_adapter("pre-tool-use.py")
POST_ADAPTER = load_adapter("post-tool-use.py")


def adapt(module, payload: dict) -> dict:
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        return module._payload()


def semantic_signature(event: dict) -> tuple:
    return tuple(
        event.get(key)
        for key in ("kind", "action", "capability", "target", "effect", "call_id")
    )


class HostAdapterConformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        (self.workspace / ".git").mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def contract_path(self, name: str) -> Path:
        path = self.root / f"{name}.json"
        contract = default_contract(
            intent_id=name,
            objective="inspect one approved local file",
            rationale="adapter conformance",
            acceptance_criteria=["the read lifecycle closes"],
            workspace=self.workspace,
            mode="enforce",
            preserve=[],
            reject=[],
            allowed_paths=["resume.md"],
            confirmed_by="human",
        )
        write_contract(path, contract)
        return path

    def test_codex_adapter_preserves_claude_equivalent_identity_and_response(self) -> None:
        raw = {
            "cwd": str(self.workspace),
            "sessionId": "thread-one",
            "toolUseId": "call-one",
            "toolName": "Read",
            "toolInput": {"file_path": "resume.md"},
            "toolResponse": {"content": "verified"},
        }
        codex_start = normalize_hook_event(
            adapt(PRE_ADAPTER, raw),
            phase="started",
            provider="codex",
        )
        codex_end = normalize_hook_event(
            adapt(POST_ADAPTER, raw),
            phase="completed",
            provider="codex",
        )
        claude_end = normalize_hook_event(
            {
                "client": "claude",
                "session_id": "thread-one",
                "tool_use_id": "call-one",
                "tool_name": "Read",
                "tool_input": {"file_path": "resume.md"},
                "tool_response": {"content": "verified"},
            },
            phase="completed",
            provider="claude",
        )

        self.assertEqual(codex_start["call_id"], "call-one")
        self.assertEqual(codex_end["call_id"], "call-one")
        self.assertEqual(codex_end["verification_evidence"], claude_end["verification_evidence"])
        self.assertEqual(
            semantic_signature(codex_end)[0:5],
            semantic_signature(claude_end)[0:5],
        )

    def test_claude_codex_and_managed_l3_close_the_same_read_lifecycle(self) -> None:
        signatures: list[tuple] = []

        claude_path = self.contract_path("claude-host")
        claude = GuardianSession(claude_path, provider="claude", session_id="claude-one")
        claude_start = normalize_hook_event(
            {
                "client": "claude",
                "session_id": "claude-one",
                "tool_use_id": "read-one",
                "tool_name": "Read",
                "tool_input": {"file_path": "resume.md"},
            },
            phase="started",
            provider="claude",
        )
        claude_end = dict(claude_start, phase="completed", success=True)
        claude.observe(claude_start)
        claude.observe(claude_end)
        signatures.append(semantic_signature(claude_end))
        self.assertEqual(load_contract(claude_path)["runtime"]["open_events"], [])

        codex_path = self.contract_path("codex-host")
        codex = GuardianSession(codex_path, provider="codex", session_id="codex-one")
        raw = {
            "sessionId": "codex-one",
            "toolUseId": "read-one",
            "toolName": "Read",
            "toolInput": {"file_path": "resume.md"},
            "toolResponse": {"content": "verified"},
        }
        codex_start = normalize_hook_event(
            adapt(PRE_ADAPTER, raw), phase="started", provider="codex"
        )
        codex_end = normalize_hook_event(
            dict(adapt(POST_ADAPTER, raw), success=True),
            phase="completed",
            provider="codex",
        )
        codex.observe(codex_start)
        codex.observe(codex_end)
        signatures.append(semantic_signature(codex_end))
        self.assertEqual(load_contract(codex_path)["runtime"]["open_events"], [])

        l3_path = self.contract_path("managed-l3")
        l3 = GuardianSession(l3_path, provider="codex", session_id="l3-one")
        started = {
            "type": "item.started",
            "item": {
                "id": "read-one",
                "type": "function_call",
                "name": "Read",
                "arguments": {"file_path": "resume.md"},
                "status": "in_progress",
            },
        }
        completed = json.loads(json.dumps(started))
        completed["type"] = "item.completed"
        completed["item"]["status"] = "completed"
        l3.observe_provider_line(json.dumps(started))
        l3.observe_provider_line(json.dumps(completed))
        self.assertEqual(len(l3.last_observed_events), 1)
        signatures.append(semantic_signature(l3.last_observed_events[0]))
        self.assertEqual(load_contract(l3_path)["runtime"]["open_events"], [])

        self.assertEqual(signatures[0], signatures[1])
        self.assertEqual(signatures[1], signatures[2])


if __name__ == "__main__":
    unittest.main()
