"""One bounded read-only r18 diagnosis; archive only allowlisted test evidence.

Administrator reads the exact test home, then launches read-only probes as UID
502. No service load/unload, account change, installation or general command API.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess

TEST_HOME = Path('/Users/suldeverify')
CASE = TEST_HOME / 's3c-r18'
ARCHIVES = Path('/private/tmp')
GUID = '025B11A2-1162-4B20-AA0D-B025D2CC32F9'
ENV = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'en_US.UTF-8',
       'HOME': str(TEST_HOME), 'USER': 'suldeverify', 'LOGNAME': 'suldeverify',
       'PYTHONDONTWRITEBYTECODE': '1'}


def run(argv):
    result = subprocess.run(argv, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=30, env=ENV)
    return {'argv': argv, 'exit_code': result.returncode,
            'stdout': result.stdout, 'stderr': result.stderr}


PROBE = '''
import json, os, subprocess
commands = [
    ['/bin/launchctl', 'manageruid'], ['/bin/launchctl', 'managername'],
    ['/bin/launchctl', 'print', 'gui/502'],
    ['/bin/launchctl', 'print', 'user/502'], ['/bin/launchctl', 'list']]
rows = []
for argv in commands:
    p = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=15)
    rows.append(dict(argv=argv, exit_code=p.returncode, stdout=p.stdout, stderr=p.stderr))
print(json.dumps(dict(uid=os.getuid(), euid=os.geteuid(), probes=rows)))
'''


def main():
    if os.getuid() != 0 or os.geteuid() != 0:
        raise RuntimeError('requires exact separately approved diagnostic execution')
    account = pwd.getpwnam('suldeverify')
    identity = run(['/usr/bin/dscl', '.', '-read', '/Users/suldeverify', 'GeneratedUID'])
    if (account.pw_uid != 502 or account.pw_gid != 20 or account.pw_dir != str(TEST_HOME)
            or identity['exit_code'] or identity['stdout'].strip() != 'GeneratedUID: ' + GUID):
        raise RuntimeError('test account identity changed')
    for path in (TEST_HOME, CASE, ARCHIVES):
        if not path.is_dir() or path.resolve() != path:
            raise RuntimeError('expected real directory unavailable: ' + str(path))
    root_probes = [run(['/bin/launchctl', 'print', domain])
                   for domain in ('gui/502', 'user/502')]
    drop = ('import os; os.initgroups("suldeverify",20); os.setgid(20); os.setuid(502); '
            + 'os.execve("/usr/bin/python3",["/usr/bin/python3","-B","-I","-c",'
            + repr(PROBE) + '],' + repr(ENV) + ')')
    child = run(['/bin/launchctl', 'asuser', '502', '/usr/bin/python3', '-B', '-I', '-c', drop])
    if child['exit_code']:
        raise RuntimeError('read-only user probe failed: ' + child['stderr'])
    user_probe = json.loads(child['stdout'])
    if user_probe['uid'] != 502 or user_probe['euid'] != 502:
        raise RuntimeError('probe did not drop privileges')
    files = [TEST_HOME / 's3c-environment-result.json',
             CASE / 'toolchain-result.json', CASE / 'toolchain-result-resume.json']
    for directory in ('entry-preparation', 'entry-preparation-canonical'):
        files.extend(CASE / directory / name for name in
                     ('phases.json', 'sha256.json', 'legacy-install.stdout', 'legacy-install.stderr'))
    payloads = {}
    for path in files:
        if not path.is_file() or path.resolve() != path or path.stat().st_size > 4 * 1024 * 1024:
            raise RuntimeError('allowlisted evidence absent/aliased/oversize: ' + str(path))
        payloads[str(path.relative_to(TEST_HOME))] = path.read_bytes()
    kb = TEST_HOME / '.sulde/data/kb'
    diagnosis = {'schema': 'sulde-r18-isolated-scheduler-diagnosis-v1',
                 'root_domain_probes': root_probes, 'user_probe': user_probe,
                 'deployment_exists': (kb / 'deployment-generation.json').exists(),
                 'service_state_claim': 'see actual list; no service was loaded or removed'}
    payloads['diagnosis.json'] = (json.dumps(diagnosis, indent=2) + '\n').encode('utf-8')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    # OS administrator execution can lack removable-volume privacy permission.
    # Hand off locally; the coordinator archives to Optimus as its ordinary UID.
    destination = ARCHIVES / ('sulde-s3c-r18-environment-' + stamp)
    os.umask(0o077)
    destination.mkdir(mode=0o700)
    hashes = {}
    for relative, content in payloads.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with target.open('xb') as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        hashes[relative] = hashlib.sha256(content).hexdigest()
    with (destination / 'manifest.json').open('x', encoding='utf-8') as out:
        json.dump(hashes, out, indent=2)
        out.flush()
        os.fsync(out.fileno())
    # Only the newly created evidence tree changes ownership, never source state.
    for root, dirs, names in os.walk(destination):
        for name in names:
            os.chown(Path(root) / name, 501, 20)
        os.chown(root, 501, 20)
    print(json.dumps({'archive': str(destination), 'files': len(hashes),
                      'gui_exit': root_probes[0]['exit_code'],
                      'gui_error': root_probes[0]['stderr'],
                      'user_exit': root_probes[1]['exit_code'],
                      'uid': user_probe['uid'], 'deployment_exists': diagnosis['deployment_exists']}))


if __name__ == '__main__':
    main()
