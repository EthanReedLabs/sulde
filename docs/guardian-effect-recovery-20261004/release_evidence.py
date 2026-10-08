"""Bounded release readback; never installs plugins or mutates production debt."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path('/Volumes/Optimus/Sulde/tasks/guardian-effect-recovery-20261004/release')
ARTIFACT = Path('/Users/eric/.sulde/artifacts/sulde-claude-0.8.9-20261004-final')
USER = Path('/Users/eric')
CHANGED = ['scripts/kb/intervention.py', 'scripts/kb/intent-guardian.py', 'scripts/kb/intent_guardian.py',
           'scripts/kb/plugin_creator_dependency.py',
           *['scripts/kb/intent_guardian_parts/' + n + '.py' for n in
             ['resources', 'policy', 'approvals', 'intervention_control', 'state']]]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(root):
    result = {}
    for path in sorted(root.rglob('*')):
        assert not path.is_symlink(), path
        assert path.name != '__pycache__' and path.suffix != '.pyc', path
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha(path)
    return result


def command(argv, **kwargs):
    result = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=90, **kwargs)
    return {'argv': argv, 'returncode': result.returncode,
            'stdout': result.stdout, 'stderr': result.stderr}


def inventory():
    results = {name: command(argv) for name, argv in {
        'claude': ['claude', 'plugin', 'list', '--json'],
        'marketplaces': ['claude', 'plugin', 'marketplace', 'list', '--json'],
        'codex': ['codex', 'plugin', 'list', '--json']}.items()}
    assert all(row['returncode'] == 0 for row in results.values()), results
    protected = [USER/'.sulde/data/kb/deployment-generation.json', USER/'.sulde/data/kb/runtime-owner.json']
    protected += list((USER/'.sulde/bin').glob('*')) + list((USER/'.sulde/bin').glob('.*json'))
    protected += list((USER/'Library/LaunchAgents').glob('com.sulde.*.plist'))
    return {'inventory':results, 'shared_sha256':{str(p):sha(p) for p in protected if p.is_file()}}


def smoke(root):
    env = {k:v for k,v in os.environ.items() if not k.startswith(('SULDE_', 'CODEX_', 'CLAUDE_'))}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    with tempfile.TemporaryDirectory(prefix='sulde-effect-recovery-', dir='/private/tmp') as temporary:
        scratch = Path(temporary)
        workspace = scratch/'workspace'
        workspace.mkdir()
        env.update(SULDE_HOME=str(scratch/'sulde'), SULDE_KB_HOME=str(scratch/'sulde/data/kb'),
                   SULDE_INTENT_CONTRACT=str(scratch/'intent.json'), CLAUDE_PLUGIN_ROOT=str(root))
        setup = '''from pathlib import Path
import sys
sys.path.insert(0,sys.argv[1])
from intent_guardian import default_contract, write_contract
c=default_contract(intent_id="release-fixture",objective="isolated release check",acceptance_criteria=["read allowed; remote denied"],workspace=Path(sys.argv[3]),mode="enforce",confirmed_by="synthetic-fixture")
c["permissions"]["external_write"]="deny"
write_contract(Path(sys.argv[2]),c)
'''
        result = command([sys.executable, '-B', '-c', setup, str(root/'scripts/kb'),
                          str(scratch/'intent.json'), str(workspace)], env=env, cwd=workspace)
        assert result['returncode'] == 0, result
        rows = []
        for name, tool, arguments, denied in [
            ('read', 'Read', {'file_path':str(root/'.claude-plugin/plugin.json')}, False),
            ('ssh-write', 'Bash', {'command':"ssh host 'mkdir /opt/app'"}, True),
            ('wrapped-ssh', 'Bash', {'command':"env ssh host 'test -e /opt/app && mkdir /opt/app'"}, True),
            ('ssh-delete', 'Bash', {'command':"ssh host 'rm -rf /opt/app'"}, True)]:
            payload = {'client':'claude','session_id':'isolated-release', 'tool_use_id':name,
                       'cwd':str(workspace),'tool_name':tool,'tool_input':arguments}
            row = command([sys.executable,'-B',str(root/'hooks/pre_tool_use.py')],
                          input=json.dumps(payload), env=env, cwd=workspace)
            row['case'] = name
            rows.append(row)
            assert row['returncode'] == 0, row
            decision = json.loads(row['stdout'])['hookSpecificOutput']['permissionDecision'] if row['stdout'].strip() else None
            assert (decision == 'deny') == denied, row
            assert 'pyyaml not installed' not in row['stderr'].lower(), row
        return {'evidence_class':'synthetic_hook_process_not_live_host', 'results':rows}


def main():
    action = sys.argv[1]
    result = {'action':action, 'at':datetime.now(timezone.utc).isoformat(),
              'source':command(['git','rev-parse','HEAD'],cwd=ROOT)['stdout'].strip()}
    if action in {'before', 'before-claude', 'final'}:
        result.update(inventory())
    elif action == 'installed-codex':
        result.update(inventory())
        selected = [p for p in json.loads(result['inventory']['codex']['stdout'])['installed']
                    if p['pluginId'] == 'sulde@sulde-local']
        assert len(selected) == 1 and selected[0]['enabled'], selected
        version = selected[0]['version']
        assert version == '0.2.5+codex.20261004042610-d1eeed94b5'
        root = USER/'.codex/plugins/cache/sulde-local/sulde'/version/'runtime'
        result['changed_files'] = {rel:sha(root/rel) for rel in CHANGED}
        assert all(value == sha(ROOT/rel) for rel,value in result['changed_files'].items())
        result['deployment'] = json.loads((USER/'.sulde/data/kb/deployment-generation.json').read_text(encoding='utf-8'))
        result['doctor'] = command([str(USER/'.sulde/bin/intent-guardian'), 'doctor',
                                    '--workspace', str(ROOT), '--provider', 'codex'])
        result['candidate_state'] = json.loads((USER/'.sulde/candidates/codex/effect-recovery-20261004-756598f/state.json').read_text(encoding='utf-8'))
        contract = json.loads((USER/'.sulde/data/kb/intent/workspaces/f832450b7d95b8e267274afc.active.json').read_text(encoding='utf-8'))
        result['contract_runtime'] = contract['runtime']
    elif action in {'candidate-claude', 'installed-claude'}:
        current = inventory()
        root = ARTIFACT
        if action == 'installed-claude':
            selected = [p for p in json.loads(current['inventory']['claude']['stdout']) if p['id']=='sulde-cc@sulde']
            assert len(selected)==1 and selected[0]['version']=='0.8.9' and selected[0]['enabled'], selected
            root = Path(selected[0]['installPath'])
        snapshot = files(root)
        for rel in CHANGED:
            assert snapshot[rel] == sha(ROOT/rel), rel
        if action == 'installed-claude':
            assert snapshot == files(ARTIFACT), 'installed artifact mismatch'
        result['files'] = snapshot
        result['smoke'] = smoke(root)
        assert files(root) == snapshot, 'smoke changed immutable tree'
        result.update(current)
    else:
        raise ValueError('unsupported action')
    OUT.mkdir(parents=True,exist_ok=True)
    path = OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-'+action+'.json')
    with path.open('x', encoding='utf-8') as handle:
        json.dump(result,handle,ensure_ascii=False,indent=2)
    print(json.dumps({'path':str(path),'sha256':sha(path),'status':'verified'}))


if __name__ == '__main__':
    main()
