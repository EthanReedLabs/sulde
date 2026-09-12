from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
KB_SCRIPTS = ROOT / "scripts" / "kb"
sys.path.insert(0, str(KB_SCRIPTS))

from intent_guardian_parts.readiness import guardian_report  # noqa: E402
from intent_guardian_parts.continuation_audit import (  # noqa: E402
    _append_continuation_event_once,
)
from intent_guardian_parts.state import (  # noqa: E402
    audit_path,
    default_contract,
    load_contract,
    write_contract,
)
from session_continuity import build_capsule  # noqa: E402


class GuardianPerformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.contract = self.root / "intent.json"
        write_contract(
            self.contract,
            default_contract(
                intent_id="guardian-performance",
                objective="keep diagnostics bounded",
                acceptance_criteria=["bounded report"],
                workspace=self.root,
                mode="enforce",
                allowed_paths=["**"],
                confirmed_by="human-readable-proposal-approval",
            ),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_default_report_reads_a_bounded_tail_and_deep_scan_is_explicit(self) -> None:
        audit = audit_path(self.contract)
        rows = [
            json.dumps(
                {
                    "event": {"kind": "tool", "provider": "codex"},
                    "decision": {"would_action": "allow"},
                    "padding": "x" * 400,
                    "sequence": index,
                }
            )
            for index in range(1200)
        ]
        audit.write_text("\n".join(rows) + "\n", encoding="utf-8")
        contract = load_contract(self.contract)
        contract["runtime"]["verified_effects"] = [
            {"index": index} for index in range(50)
        ]
        contract["runtime"]["inconclusive_outcomes"] = [
            {"index": index} for index in range(100)
        ]
        write_contract(self.contract, contract)

        bounded = guardian_report(self.contract)
        deep = guardian_report(self.contract, deep_audit=True)

        self.assertEqual(bounded["audit_window"]["mode"], "tail")
        self.assertTrue(bounded["audit_window"]["truncated"])
        self.assertLessEqual(bounded["audit_window"]["scanned_bytes"], 256 * 1024)
        self.assertLessEqual(bounded["audit_window"]["scanned_lines"], 512)
        self.assertEqual(deep["audit_window"]["mode"], "deep")
        self.assertFalse(deep["audit_window"]["truncated"])
        self.assertEqual(deep["event_counts"]["tool"], 1200)
        self.assertEqual(bounded["verified_effects"]["returned"], 20)
        self.assertEqual(bounded["verified_effects"]["total"], 50)
        self.assertEqual(bounded["inconclusive_outcomes"]["returned"], 20)

    def test_continuation_idempotency_uses_incremental_index_and_rebuilds(self) -> None:
        capsule = build_capsule(
            contract_path=self.contract,
            proposal_path=self.root / "proposal.json",
            review={
                "intent_id": "guardian-performance",
                "base_revision": 1,
                "proposed_revision": 2,
                "proposal_digest": "a" * 64,
                "decision_route": "agent",
                "decision_card": {"要完成的结果": "resume once"},
            },
            workspace_root=self.root,
            created_at="2026-08-31T00:00:00+00:00",
            provider="codex",
            session_id="source-thread",
        )
        audit = audit_path(self.contract)
        audit.write_text(
            "".join(json.dumps({"padding": "x" * 400, "row": index}) + "\n" for index in range(1200)),
            encoding="utf-8",
        )
        self.assertTrue(
            _append_continuation_event_once(
                self.contract,
                action="created",
                capsule=capsule,
                provider="codex",
                session_id="thread-one",
            )
        )
        original_read_text = Path.read_text

        def guarded_read_text(path: Path, *args, **kwargs):
            if path == audit:
                raise AssertionError("idempotency replayed the complete audit")
            return original_read_text(path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", guarded_read_text):
            self.assertFalse(
                _append_continuation_event_once(
                    self.contract,
                    action="created",
                    capsule=capsule,
                    provider="codex",
                    session_id="thread-one",
                )
            )

        index = audit.with_name(f".{audit.name}.continuation-index.json")
        index.write_text("{broken\n", encoding="utf-8")
        self.assertFalse(
            _append_continuation_event_once(
                self.contract,
                action="created",
                capsule=capsule,
                provider="codex",
                session_id="thread-one",
            )
        )
        continuation_rows = [
            json.loads(line)
            for line in audit.read_text(encoding="utf-8").splitlines()
            if "sulde-continuation-event-v1" in line
        ]
        self.assertEqual(len(continuation_rows), 1)

    @unittest.skipIf(os.name == "nt", "POSIX timer preserves in-process timeout")
    def test_in_process_runtime_keeps_a_bounded_timeout(self) -> None:
        common_path = (
            ROOT
            / "integrations"
            / "codex"
            / "plugins"
            / "sulde"
            / "scripts"
            / "_adapter_common.py"
        )
        spec = importlib.util.spec_from_file_location("test_adapter_deadline", common_path)
        assert spec is not None and spec.loader is not None
        common = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(common)
        script = self.root / "hang.py"
        script.write_text("while True:\n    pass\n", encoding="utf-8")
        old_streams = (sys.stdin, sys.stdout, sys.stderr)
        with mock.patch.dict(os.environ, {"SULDE_CODEX_IN_PROCESS_HOOK": "1"}):
            with self.assertRaises(subprocess.TimeoutExpired):
                common.run_runtime(script, timeout=0.05)
        self.assertEqual((sys.stdin, sys.stdout, sys.stderr), old_streams)


if __name__ == "__main__":
    unittest.main()
