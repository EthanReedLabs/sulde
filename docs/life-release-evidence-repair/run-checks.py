"""Persistent scoped evidence using the repository's OS-isolated test runner."""
import json
import os
from pathlib import Path
import runpy
import sys

sys.dont_write_bytecode = True
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
ROOT = Path(__file__).resolve().parents[2]
os.environ['SULDE_TEST_EVIDENCE_HOME'] = str(ROOT / '.sulde/data/test-evidence')
sys.path.insert(0, str(ROOT / 'scripts/kb'))
module = runpy.run_path(str(ROOT / 'scripts/kb/test-evidence.py'))
tests = sys.argv[1:] or [
    'tests.test_candidate_codex_plugin', 'tests.test_codex_plugin_install',
    'tests.test_python_environment_preflight', 'tests.test_life_health_closure',
    'tests.test_hook_observer_closure', 'tests.test_codex_hook_bridge',
    'tests.test_native_posttool_delivery', 'tests.test_native_pretool_delivery',
]
plan = dict(schema='sulde-test-plan-v1', base='a0ba44b02370b07dcd12f0892686afe84ec4160a',
            baseline_commit='a0ba44b02370b07dcd12f0892686afe84ec4160a',
            head=module['_git']('rev-parse', 'HEAD').strip(), risk='high', suite='targeted', tests=tests,
            scope={'selection': 'frozen_four_finding_impact_set',
                   'rationale': 'Release isolation, native execution evidence, LIFE closure and Hook identity; no general policy rewrite.'})
status, record = module['run_plan'](plan, reuse=False)
print(json.dumps(record, ensure_ascii=False, indent=2))
raise SystemExit(status)
