"""Run real isolated legacy install and candidate prepare/verify as UID 502.

Stops before the separate interactive maintenance approval. No synthetic receipts,
process inventory substitutions, paid provider, or production user paths.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import time

CASE = Path('/Users/suldeverify/s3c-r18')
TEST_HOME = Path('/Users/suldeverify')
KB = TEST_HOME / '.sulde/data/kb'
PYTHON = KB / 'venv/bin/python'
CODEX = CASE / 'tools/codex'
LEGACY = CASE / 'legacy-source'
CANDIDATE = CASE / 'candidate-source'


def main():
    if os.getuid() != os.geteuid() or os.getuid() != 502:
        raise RuntimeError('isolated preparation must never run as root')
    manager = subprocess.check_output(['/bin/launchctl', 'manageruid'], text=True,
                                      encoding='utf-8', errors='strict').strip()
    if manager != '502':
        raise RuntimeError('wrong isolated bootstrap domain')
    ready = json.loads((CASE / 'toolchain-result-resume.json').read_text(encoding='utf-8'))
    if ready['status'] != 'toolchain-ready-not-installed':
        raise RuntimeError('toolchain has not passed preflight')
    os.umask(0o077)
    evidence = CASE / 'entry-preparation-canonical'
    evidence.mkdir(mode=0o700)
    # The historical installer smoke clears SULDE_HOME. Use its real canonical
    # HOME/.sulde layout, rather than patching historical code or fake bridges.
    if KB.exists() or KB.is_symlink():
        raise RuntimeError('canonical fixture already exists; inspect before retry')
    KB.mkdir(parents=True, mode=0o700)
    original_python = CASE / 'live/sulde/data/kb/venv/bin/python'
    subprocess.run([str(original_python), '-B', '-m', 'venv', '--copies', '--system-site-packages', str(KB / 'venv')],
                   check=True, timeout=120)
    original_site = CASE / 'live/sulde/data/kb/venv/lib/python3.10/site-packages'
    new_site = KB / 'venv/lib/python3.10/site-packages'
    shutil.copytree(original_site / 'yaml', new_site / 'yaml', ignore=shutil.ignore_patterns('__pycache__'))
    env = {'HOME': '/Users/suldeverify', 'USER': 'suldeverify', 'LOGNAME': 'suldeverify',
           'PATH': str(CASE / 'tools') + ':/usr/bin:/bin:/usr/sbin:/sbin',
           'LANG': 'en_US.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8': '1',
           'CODEX_HOME': str(TEST_HOME / '.codex'), 'SULDE_HOME': str(TEST_HOME / '.sulde'),
           'SULDE_KB_HOME': str(KB), 'SULDE_LAUNCHER_HOME': str(TEST_HOME / '.sulde'),
           'SULDE_LAUNCHAGENTS_DIR': str(TEST_HOME / 'Library/LaunchAgents'),
           'SULDE_HOST_PROVIDER': 'codex', 'SULDE_CODEX_EXE': str(CODEX),
           'SULDE_CANDIDATE_PYTHON': str(PYTHON), 'TMPDIR': str(CASE / 'tmp')}
    for key in ('CODEX_HOME', 'SULDE_LAUNCHAGENTS_DIR', 'TMPDIR'):
        Path(env[key]).mkdir(parents=True, exist_ok=True, mode=0o700)
    os.environ.clear()
    os.environ.update(env)
    phases = []

    def run(label, command, cwd, timeout):
        start = time.monotonic()
        with (evidence / (label + '.stdout')).open('x', encoding='utf-8') as out, (evidence / (label + '.stderr')).open('x', encoding='utf-8') as err:
            process = subprocess.run(command, cwd=cwd, env=env, stdout=out, stderr=err, timeout=timeout)
        fact = {'phase': label, 'exit_code': process.returncode,
                'duration_seconds': round(time.monotonic() - start, 3), 'argv': command}
        phases.append(fact)
        print(json.dumps(fact), flush=True)
        (evidence / 'phases.json').write_text(json.dumps(phases, indent=2), encoding='utf-8')
        if process.returncode:
            # Installer diagnostics only; do not print any configuration/auth file.
            print((evidence / (label + '.stderr')).read_text(encoding='utf-8')[-2500:], flush=True)
            raise RuntimeError(label + ' failed; all evidence retained')

    try:
        run('legacy-install', [str(PYTHON), '-B', str(LEGACY / 'scripts/release/install_codex_plugin.py'),
                              '--artifact-root', str(CASE / 'artifacts/legacy-canonical'), '--kb-home', str(KB),
                              '--codex', str(CODEX), '--json'], LEGACY, 900)
        base = [str(PYTHON), '-B', str(CANDIDATE / 'scripts/release/candidate_codex_plugin.py'),
                '--candidate-home', str(CASE / 'candidates-canonical'), '--codex', str(CODEX), '--json']
        run('candidate-prepare', base + ['prepare', '--candidate-id', 'r18-maintenance'], CANDIDATE, 600)
        run('candidate-verify', base + ['verify', 'r18-maintenance'], CANDIDATE, 900)
        draft_args = dict(candidate_home=str(CASE / 'candidates-canonical'), candidate_id='r18-maintenance',
            kb_home=str(KB), codex_home=env['CODEX_HOME'], launcher_home=env['SULDE_HOME'],
            user_home=env['HOME'], launchagents_dir=env['SULDE_LAUNCHAGENTS_DIR'],
            output=str(CASE / 'maintenance-draft.json'), seconds=3600)
        draft_code = ('import sys,json;sys.path.insert(0,' + repr(str(CANDIDATE / 'scripts/release'))
                      + ');import legacy_maintenance;print(json.dumps(legacy_maintenance.prepare_draft(**'
                      + repr(draft_args) + ')))')
        run('draft', [str(PYTHON), '-B', '-I', '-c', draft_code], CANDIDATE, 120)
        draft = json.loads((evidence / 'draft.stdout').read_text(encoding='utf-8'))
        (evidence / 'draft-result.json').write_text(json.dumps(draft, indent=2), encoding='utf-8')
        print(json.dumps({'status': 'awaiting-separate-native-maintenance-choice', **draft}), flush=True)
    finally:
        manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in evidence.iterdir() if p.is_file()}
        (evidence / 'sha256.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
