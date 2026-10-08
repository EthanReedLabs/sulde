"""Paired scope tests, reusable unchanged against an extracted baseline tree."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
import runpy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(os.environ.get("SULDE_HEALTH_TEST_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "scripts/kb"))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts/kb" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STATUS = load("health_scope_status", "sulde-status.py")
SNAPSHOT = load("health_scope_snapshot", "sulde_status_snapshot.py")


class LifeScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.now = datetime.now(timezone.utc)
        self.state = {
            "schema": "sulde-life-cycle-v2", "status": "degraded",
            "generated_at": self.now.isoformat(),
            "levels": {name: {"status": "ready"} for name in ("L2", "L3", "L4")},
            "evolution": {"status": "ready"},
            "closed_loop": {
                "dimensions": {name: True for name in ("sense", "persist", "decide", "act", "verify")},
                "readback": {name: True for name in ("l2", "l3", "l4", "evolution")},
                "human_gates": {"preserved": False, "unknown_effects_fail_closed": True, "reason": "scheduler delivery does not prove a current human decision lane"},
                "identity_resume": {"guarded": False, "reason": "no current interactive session identity"},
            },
            "operational_readiness": {
                "readiness_scope": "scheduler", "status": "ready", "reasons": [],
                "scheduler_readiness": {"status": "ready"},
                "artifact_generation_readiness": {"generation": "fixture-generation"},
            },
        }

    def status(self, state=None):
        path = self.home / "state.json"
        path.write_text(json.dumps(self.state if state is None else state), encoding="utf-8")
        result = STATUS.read_life(path, self.now)
        self.assertIsNotNone(result)
        return {
            "missing_sources": [], "kb_docs": 1, "kb_edges": 0,
            "mem_total": 1, "mem_today": 0, "mem_pending_embedding": 0,
            "harvest_age_seconds": 0, "distill_age_seconds": 0,
            "runtime_available": True, "launcher_contract_healthy": True,
            "scheduler_health": {"status": "ready"},
            "operational_readiness": {"readiness_scope": "scheduler", "status": "ready"},
            **result,
        }

    def test_ready_normal_control(self):
        state = deepcopy(self.state)
        state["status"] = "ready"
        self.assertTrue(STATUS.statusline_healthy(self.status(state)))

    def test_scheduler_missing_human_lane_is_not_background_failure(self):
        result = self.status()
        self.assertTrue(STATUS.statusline_healthy(result))
        self.assertEqual(result["life_status"], "degraded")
        self.assertEqual(result["life_projection"]["interactive_status"], "unobserved")
        self.assertEqual(result["life_projection"]["generation"], "fixture-generation")
        self.assertEqual(result["life_projection"]["source_reasons"]["human_gates"], self.state["closed_loop"]["human_gates"]["reason"])
        self.assertIn("交互未观测", STATUS.statusline(result))

    def test_real_faults_never_turn_green(self):
        mutations = [
            ("scheduler", lambda s: s["operational_readiness"]["scheduler_readiness"].update(status="degraded")),
            ("persist", lambda s: s["closed_loop"]["readback"].update(l3=False)),
            ("dimension", lambda s: s["closed_loop"]["dimensions"].update(verify=False)),
            ("level", lambda s: s["levels"]["L2"].update(status="degraded")),
            ("evolution", lambda s: s["evolution"].update(status="degraded")),
            ("unknown", lambda s: s.update(status="unknown")),
            ("effect", lambda s: s["closed_loop"]["human_gates"].update(unknown_effects_fail_closed=False)),
            ("missing-time", lambda s: s.pop("generated_at")),
            ("stale", lambda s: s.update(generated_at=(self.now - timedelta(days=1)).isoformat())),
            ("future", lambda s: s.update(generated_at=(self.now + timedelta(days=1)).isoformat())),
            ("legacy", lambda s: s.pop("operational_readiness")),
        ]
        for name, mutate in mutations:
            with self.subTest(name=name):
                state = deepcopy(self.state)
                mutate(state)
                self.assertFalse(STATUS.statusline_healthy(self.status(state)))

    def test_current_interactive_fault_not_hidden_by_background(self):
        result = self.status()
        result["operational_readiness"] = {"readiness_scope": "interactive", "status": "degraded", "reasons": ["task_lane_bound"]}
        self.assertFalse(STATUS.statusline_healthy(result))
        self.assertIn("任务未就绪", STATUS.statusline(result))

    def test_scheduler_fault_does_not_claim_unobserved_interactive_success(self):
        result = self.status()
        result["scheduler_health"] = {"status": "degraded", "reasons": ["scheduler_process_ready"]}
        self.assertNotIn("交互可用", STATUS.statusline(result))
        result["operational_readiness"] = {"readiness_scope": "interactive", "status": "ready"}
        self.assertIn("交互可用·调度降级", STATUS.statusline(result))

    def test_corrupt_or_missing_life_is_unavailable(self):
        path = self.home / "missing.json"
        self.assertIsNone(STATUS.read_life(path, self.now))
        for value in ("bad json", "[]", '{"levels":[]}'):
            path.write_text(value, encoding="utf-8")
            self.assertIsNone(STATUS.read_life(path, self.now))

    def test_snapshot_preserves_scopes_and_reasons_without_recomputation(self):
        result = self.status()
        self.assertTrue(SNAPSHOT.write_snapshot(self.home, line=STATUS.statusline(result), healthy=True, life=result["life_projection"], now=self.now))
        actual = SNAPSHOT.read_snapshot(self.home, now=self.now)
        self.assertTrue(actual["healthy"])
        self.assertEqual(actual["life"], result["life_projection"])
        self.assertEqual(actual["scope"], "background_runtime")
        self.assertFalse(SNAPSHOT.read_snapshot(self.home, now=self.now + timedelta(hours=4))["healthy"])

    def test_old_snapshot_never_claims_interactive_or_global_ready(self):
        self.assertTrue(SNAPSHOT.write_snapshot(self.home, line="sulde legacy", healthy=False, now=self.now))
        actual = SNAPSHOT.read_snapshot(self.home, now=self.now)
        self.assertFalse(actual["healthy"])
        self.assertEqual(actual["life"]["global_status"], "unknown")
        self.assertEqual(actual["life"]["interactive_status"], "unobserved")

    def test_snapshot_rejects_conflicting_life_status(self):
        projection = self.status()["life_projection"]
        projection["background_status"] = "degraded"
        self.assertFalse(SNAPSHOT.write_snapshot(self.home, line="sulde green", healthy=True, life=projection, now=self.now))

    def test_source_age_is_not_reset_by_snapshot_publication(self):
        projection = self.status()["life_projection"]
        projection["generated_at"] = (self.now - timedelta(hours=11)).isoformat()
        self.assertTrue(SNAPSHOT.write_snapshot(self.home, line="sulde background", healthy=True, life=projection, now=self.now))
        self.assertFalse(SNAPSHOT.read_snapshot(self.home, now=self.now + timedelta(hours=2))["healthy"])

    def test_mcp_preserves_scopes_using_only_bounded_snapshot(self):
        server = runpy.run_path(str(ROOT / "tools/kb-mcp/server.py"))
        projection = self.status()["life_projection"]
        self.assertTrue(SNAPSHOT.write_snapshot(self.home, line="sulde background", healthy=True, life=projection, now=self.now))
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(self.home)}), mock.patch.object(server["subprocess"], "run", side_effect=AssertionError("deep scan")):
            result = json.loads(server["kb_status"]({})["content"][0]["text"])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["scope"], "background_runtime")
        self.assertEqual(result["life"]["global_status"], "degraded")
        self.assertEqual(result["life"]["interactive_status"], "unobserved")


if __name__ == "__main__":
    unittest.main()
