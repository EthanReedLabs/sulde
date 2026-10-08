"""Archive bounded S3-B release facts, without installing or changing ledgers."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
DEV = ROOT.parent / 'guardian-v3-dev-merge'
DATA = Path('/Users/eric/.sulde/data/kb')
CONTRACT = DATA / 'intent/sessions/completion-6514aef628e75bf2049c2c4ee06cbc5e.active.json'
SLOT = DEV / '.tmp/s3b-candidates/guardian-s3b-20261005-r8'
OUT = Path('/Volumes/Optimus/Sulde/tasks/guardian-unified-plan-20261004/S3-B')
VERSION = '0.2.5+codex.20261005134315-d918c7a2ed'
RUNTIME = Path('/Users/eric/.codex/plugins/cache/sulde-local/sulde') / VERSION / 'runtime'
SESSION = '01a04634-318f-7203-ba2d-26fa6ac442b0'


def main():
    assert os.path.ismount('/Volumes/Optimus')
    os.umask(0o077)
    out = OUT / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '-final')
    out.mkdir(parents=True, exist_ok=False)
    hashes = {}

    def write(name, content):
        with (out / name).open('xb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        assert (out / name).read_bytes() == content
        hashes[name] = hashlib.sha256(content).hexdigest()

    def document(name, value):
        write(name, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())

    for name, source in {
        'candidate-state.json': SLOT / 'state.json',
        'candidate-verification.json': SLOT / 'verification-receipt.json',
        'deployment.json': DATA / 'deployment-generation.json',
        'runtime-owner.json': DATA / 'runtime-owner.json',
        'launcher.json': Path('/Users/eric/.sulde/bin/.sulde-launchers.json'),
        'release-tests.log': ROOT / '.tmp/s3b-release-tests.log',
        'codex-generation.json': RUNTIME.parent / '.codex-plugin/generation.json',
    }.items():
        write(name, source.read_bytes())
    contract = json.loads(CONTRACT.read_bytes())
    document('contract-runtime.json', {
        'schema': 'sulde-s3-contract-readback-v1', 'source': str(CONTRACT),
        'source_sha256': hashlib.sha256(CONTRACT.read_bytes()).hexdigest(),
        'revision': contract['revision'], 'continuation': contract['continuation'],
        'runtime': contract['runtime'],
    })
    audit = CONTRACT.with_name(CONTRACT.stem + '.events.jsonl')
    selected = []
    for line in audit.read_text(encoding='utf-8').splitlines():
        if 'd2227b8110c411b3c6ff7c075d73715c' in line:
            selected.append(json.loads(line))
    assert selected, 'live proof event not found'
    document('live-probe-events.json', {'source': str(audit), 'rows': selected})
    command = ['/Users/eric/.sulde/bin/intent-guardian', 'doctor', '--workspace', str(DEV),
               '--provider', 'codex', '--session-id', SESSION]
    result = subprocess.run(command, capture_output=True, timeout=90)
    write('doctor.stdout.json', result.stdout)
    write('doctor.stderr.log', result.stderr)
    document('doctor-process.json', {'argv': command, 'exit_code': result.returncode})
    assert result.returncode == 0
    doctor = json.loads(result.stdout)
    assert doctor['operational_readiness']['status'] == 'ready'
    changed = subprocess.check_output(
        ['git', 'diff', '--name-only', 'ac5dc9c', 'c325c7c', '--', 'scripts', 'hooks'], cwd=ROOT,
        text=True).splitlines()
    matches = {}
    source_only = {}
    # stage_plugin.RUNTIME_PREFIXES includes scripts/kb/, not scripts/release/.
    # These two release-side consumers were exercised by the installer/tests.
    release_only = {'scripts/release/install_codex_plugin.py',
                    'scripts/release/install_transaction_journal.py'}
    for relative in changed:
        source, installed = ROOT / relative, RUNTIME / relative
        if relative in release_only:
            assert source.is_file() and not installed.exists(), relative
            source_only[relative] = hashlib.sha256(source.read_bytes()).hexdigest()
            continue
        assert source.is_file() and installed.is_file(), relative
        assert source.read_bytes() == installed.read_bytes(), relative
        matches[relative] = hashlib.sha256(installed.read_bytes()).hexdigest()
    document('installed-source-matches.json', {'source_commit': 'c325c7c', 'matches': matches,
               'source_only_release_tools': source_only,
               'inventory_authority': 'scripts/release/stage_plugin.py:RUNTIME_PREFIXES'})
    document('manifest.json', {'schema': 'sulde-s3-release-archive-v1', 'files': hashes.copy(),
                               'self_excluded': True})
    print(json.dumps({'path': str(out), 'manifest_sha256': hashes['manifest.json'],
                      'files': len(hashes), 'status': 'archived_and_readback_verified'}))


if __name__ == '__main__':
    main()
