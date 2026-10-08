"""Retain dependency regression and archived-helper entry evidence, without installing."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

from restore_dependency import restore

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = Path('/Users/eric/.sulde/candidates/codex/20260927T112231Z-c33d3a774617/isolated/codex-home/skills/.system/plugin-creator/scripts')
OUT = Path('/Volumes/Optimus/Sulde/tasks/guardian-effect-recovery-20261004/dependency')


def main():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    for key in list(env):
        if key.startswith(('SULDE_', 'CLAUDE_', 'CODEX_')):
            del env[key]
    records = []
    def run(label, argv, extra=None):
        result = subprocess.run(argv, cwd=ROOT, env=dict(env, **(extra or {})),
                                capture_output=True, text=True, encoding='utf-8', timeout=360)
        records.append({'label': label, 'argv': argv, 'env_override': extra,
                        'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
        return result
    baseline = sys.argv[1]
    base = run('baseline', [sys.executable, '-B', '-m', 'unittest',
        'tests.test_plugin_creator_dependency.BinderDependencyTests', '-v'],
        {'SULDE_TEST_SOURCE_ROOT': baseline})
    tests = run('candidate', [sys.executable, '-B', '-m', 'unittest',
        'tests.test_plugin_creator_dependency', 'tests.test_intent_guardian',
        'tests.test_launcher_contract', '-q'])
    with tempfile.TemporaryDirectory(prefix='sulde-effect-recovery-', dir='/private/tmp') as tmp:
        scratch = Path(tmp)
        restore(ARCHIVE, scratch / 'helpers', apply=True)
        plugin = scratch / 'plugin'
        (plugin / '.codex-plugin').mkdir(parents=True)
        manifest = plugin / '.codex-plugin/plugin.json'
        manifest.write_text(json.dumps({'name':'sulde', 'version':'0.2.5', 'description':'fixture'}), encoding='utf-8')
        entry = run('real-helper-entry', [sys.executable, '-B', str(scratch/'helpers/update_plugin_cachebuster.py'), str(plugin), '--cachebuster', 'recovery-proof'])
        version = json.loads(manifest.read_text(encoding='utf-8'))['version']
        validator = run('real-validator-entry', [sys.executable, '-B', str(scratch/'helpers/validate_plugin.py'),
            '/Users/eric/.codex/plugins/cache/sulde-local/sulde/0.2.5+codex.20261003135300-b04b6d9'])
    sources = ['scripts/kb/plugin_creator_dependency.py', 'scripts/kb/intent_guardian_parts/state.py',
               'tests/test_plugin_creator_dependency.py', 'docs/guardian-effect-recovery-20261004/restore_dependency.py',
               'docs/guardian-effect-recovery-20261004/verify_dependency.py']
    payload = {'source_sha256': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources},
               'baseline_commit': 'c5e4864', 'records': records, 'helper_version': version,
               'upstream_current_version': 'unverified', 'model_calls': 0}
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'.json')
    with path.open('x', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps({'evidence':str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                      'results':[(r['label'],r['returncode']) for r in records]}))
    assert base.returncode == 1 and 'FAILED (failures=3)' in base.stderr
    assert tests.returncode == entry.returncode == validator.returncode == 0
    assert version == '0.2.5+codex.recovery-proof'


if __name__ == '__main__':
    main()
