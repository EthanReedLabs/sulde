"""S3-C bounded boundary injection; never changes installed files or runs payloads."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = ROOT / '.tmp/s3c-diagnostics'
SCRIPTS = ROOT / 'integrations/codex/plugins/sulde/scripts'


def hook_case(parent, name, failure, remove_scripts=False, tool='Read', command=None):
    case = parent / name
    scripts = case / 'plugin/scripts'
    shutil.copytree(SCRIPTS, scripts)
    bridge = case / 'sulde/bin/intent-guardian'
    bridge.parent.mkdir(parents=True)
    # Fault stub is the external launcher boundary, never the classifier.
    content = '#!/bin/sh\n# sulde-observer-in-process-v1\n'
    if remove_scripts:
        content += 'mv -- "$S3C_FAULT_SCRIPTS" "$S3C_FAULT_RETAINED"\n'
    content += 'exit ' + ('73' if failure else '0') + '\n'
    bridge.write_text(content, encoding='utf-8')
    bridge.chmod(0o700)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('SULDE_', 'CODEX_', 'CLAUDE_'))}
    env.update(PYTHONDONTWRITEBYTECODE='1', SULDE_HOME=str(case / 'sulde'),
               SULDE_KB_HOME=str(case / 'sulde/data/kb'), SULDE_SOURCE_ROOT=str(ROOT),
               S3C_FAULT_SCRIPTS=str(scripts), S3C_FAULT_RETAINED=str(case / 'retained-scripts'))
    payload = {'tool_name': tool, 'tool_input': {'command': command} if command else
               {'file_path': str(ROOT / 'CANON.md')}, 'session_id': 's3c-fixture',
               'call_id': name, 'cwd': str(ROOT)}
    result = subprocess.run(['/bin/sh', str(scripts / 'run-hook.sh'), 'pre-tool-use'],
                            input=json.dumps(payload), text=True, capture_output=True,
                            env=env, cwd=case, timeout=20)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout) if result.stdout.strip() else {}
    decision = output.get('hookSpecificOutput', {}).get('permissionDecision')
    database = case / 'sulde/data/kb/hook-observer/observations.sqlite3'
    observations = []
    if database.exists():
        with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as connection:
            observations = [json.loads(row[0]) for row in connection.execute('select row from observations')]
    return {'name': name, 'decision': decision, 'exit': result.returncode,
            'stdout': result.stdout, 'stderr': result.stderr, 'observations': observations,
            'scripts_available_after': scripts.exists(), 'payload_executed': False}


def main():
    assert os.path.ismount('/Volumes/Optimus'), 'Optimus unavailable'
    os.umask(0o077)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    # Retain fixtures as evidence; no production cleanup or symlink substitution.
    scratch = Path(tempfile.mkdtemp(prefix='run-', dir=SCRATCH))
    cases = [hook_case(scratch, 'normal-read', False),
             hook_case(scratch, 'bridge-failure-read', True),
             hook_case(scratch, 'bridge-failure-ps', True, tool='Bash', command='ps -Ao pid,ppid,etime,command'),
             hook_case(scratch, 'removed-adapter-read', True, True),
             hook_case(scratch, 'removed-adapter-write', True, True, 'Bash', 'touch marker')]
    assert cases[0]['decision'] is None and cases[1]['decision'] is None
    assert cases[1]['observations'], 'failed bridge must be observed with static dependencies present'
    assert cases[2]['decision'] == 'deny' and 'fallback failed' not in cases[2]['stdout']
    for row in cases[3:]:
        assert row['decision'] == 'deny' and 'fallback failed' in row['stdout']
        assert not row['scripts_available_after'] and not row['observations']
    spec = importlib.util.spec_from_file_location('s3c_status', ROOT / 'scripts/kb/sulde-status.py')
    status = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(status)
    base = {'missing_sources': [], 'life_status': 'ready', 'life_age_seconds': 0,
            'runtime_available': True, 'launcher_contract_healthy': True,
            'scheduler_health': {'status': 'ready'},
            'operational_readiness': {'readiness_scope': 'scheduler', 'status': 'ready'}}
    healthy = status.statusline_healthy(base)
    identity_only = status.statusline_healthy(dict(base, life_status='degraded'))
    assert healthy is True and identity_only is False
    life_path = Path('/Users/eric/.sulde/data/kb/life/state.json')
    life_bytes = life_path.read_bytes()
    life = json.loads(life_bytes)
    result = {'schema': 'sulde-s3c-diagnostics-v1', 'source': 'eacee08',
              'at': datetime.now(timezone.utc).isoformat(), 'fixture': str(scratch),
              'cases': cases, 'status_projection_pair': {'normal': healthy, 'identity_only_degraded': identity_only},
              'production_life_readback': {'sha256': hashlib.sha256(life_bytes).hexdigest(),
                 'generated_at': life.get('generated_at'), 'status': life['status'],
                 'closed_loop': life['closed_loop'], 'levels': life['levels'],
                 'operational_status': life['operational_readiness']['status'],
                 'operational_scope': life['operational_readiness']['readiness_scope']},
              'evidence_scope': 'real shell wrapper with injected external bridge/cache boundary; not historical causal proof',
              'source_hashes': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in [SCRIPTS/'run-hook.sh', SCRIPTS/'pre-tool-use.py', SCRIPTS/'_recovery_defer.py',
                            ROOT/'scripts/kb/sulde-status.py', Path(__file__)]}}
    out = Path('/Volumes/Optimus/Sulde/tasks/guardian-unified-plan-20261004/S3-C')
    out.mkdir(parents=True, exist_ok=True)
    path = out / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '-diagnostic.json')
    with path.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    assert json.loads(path.read_bytes()) == result
    print(json.dumps({'status': 'diagnostic-assertions-passed', 'path': str(path),
                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'hook_cases': len(cases)}))


if __name__ == '__main__':
    main()
