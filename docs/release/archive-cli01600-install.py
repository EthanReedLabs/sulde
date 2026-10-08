"""Archive bounded local-release evidence, never modify authoritative inputs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path('/Volumes/Optimus/Sulde/tasks/codex-01600-release-20261003')
HOME = Path('/Users/eric/.sulde')
VERSION = '0.2.5+codex.20261003135300-b04b6d9'
GEN = VERSION + ':1638d80346226a17013ca5155de9c87a22d6fd2963ec8bd09ecf6fff9bbd5844'
CONTRACT = HOME / 'data/kb/intent/workspaces/9e94687525b24b14af9be303.active.json'

def save(name, data):
    with (OUT / name).open('xb') as stream:
        stream.write(data)

def capture(name, argv):
    run = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=60)
    save(name + '.stdout', run.stdout)
    save(name + '.stderr', run.stderr)
    save(name + '.result.json', json.dumps({'argv': argv, 'exit_code': run.returncode}).encode())
    if run.returncode:
        raise RuntimeError((name, run.returncode))
    return json.loads(run.stdout)

def main():
    os.umask(0o077)
    OUT.mkdir(parents=True, exist_ok=False)
    candidate = HOME / 'candidates/codex/cli01600-release-20261003'
    for name in ('state.json', 'verification-receipt.json'):
        save('candidate-' + name, (candidate / name).read_bytes())
    for name in ('deployment-generation.json', 'runtime-owner.json'):
        save(name, (HOME / 'data/kb' / name).read_bytes())
    save('launcher-manifest.json', (HOME / 'bin/.sulde-launchers.json').read_bytes())
    installed = Path('/Users/eric/.codex/plugins/cache/sulde-local/sulde') / VERSION
    for name in ('generation.json', 'plugin.json'):
        save('installed-' + name, (installed / '.codex-plugin' / name).read_bytes())
    contract = json.loads(CONTRACT.read_bytes())
    runtime = contract['runtime']
    selected = {k: runtime.get(k) for k in ('continuation_uses', 'verified_effects',
        'pending_verifications', 'open_events', 'integrity_breaches',
        'pre_execution_gaps', 'pre_execution_proofs', 'pre_execution_probe')}
    save('contract-evidence.json', json.dumps({'contract': str(CONTRACT),
        'intent_id': contract['intent_id'], 'revision': contract['revision'],
        'source_sha256': hashlib.sha256(CONTRACT.read_bytes()).hexdigest(),
        'runtime': selected}, indent=2).encode())
    doctor = capture('doctor', [str(HOME / 'bin/intent-guardian'), 'doctor',
        '--workspace', str(ROOT), '--provider', 'codex'])
    mcp = capture('mcp', [sys.executable, '-B', 'docs/release/verify-cli01551-installed-mcp.py', VERSION, GEN])
    assert doctor['operational_readiness']['domains']['artifact_generation']['generation'] == GEN
    assert doctor['status'] == 'ready'
    assert doctor['operational_readiness']['domains']['scheduler']['status'] == 'ready'
    assert doctor['operational_readiness']['domains']['pre_execution_safety']['proof_current_generation']
    assert len(selected['continuation_uses']) == 1
    assert any(v['verified_by_capability'] == 'tool:codex_plugin_install_verify' for v in selected['verified_effects'])
    assert all(not selected[k] for k in ('pending_verifications', 'open_events', 'integrity_breaches', 'pre_execution_gaps'))
    assert mcp['status'] == 'transport_passed'
    save('summary.json', json.dumps({'status': 'bounded_install_verified', 'generation': GEN,
        'background_status': mcp['kb_status']['status'], 'model_calls': 0,
        'source_commit': '3de3f07da938dad1ec95b513e4bccdf0c0bb9327',
        'scope': 'installation, current-session Hook, scheduler, fresh MCP transport; not global LIFE or Agent capability'}, indent=2).encode())
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file()}
    save('SHA256.json', json.dumps(manifest, sort_keys=True, indent=2).encode())
    assert all(hashlib.sha256((OUT / p).read_bytes()).hexdigest() == h for p, h in manifest.items())
    print(json.dumps({'evidence': str(OUT), 'files_verified': len(manifest), 'doctor': doctor['status'], 'mcp': mcp['status'], 'background': mcp['kb_status']['status']}))

if __name__ == '__main__':
    main()
