"""Exact r18 copy/drop-privilege/toolchain preparation; never installs Sulde."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tarfile

HOME = Path('/Users/suldeverify')
DEST = HOME / 's3c-r18'
SOURCE_PARENT = Path('/Users/eric/ClaudePlugin/sulde-pro/.worktrees/guardian-update-continuity/.codex-agent/s3c-user-environment')


def read_exact(path, sha):
    if path.resolve() != path or path.is_symlink():
        raise ValueError('aliased input')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        raw = stream.read()
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError('input identity changed')
    return raw


def call(argv, cwd=None):
    return subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True,
                          encoding='utf-8', errors='strict', timeout=120).stdout.strip()


def child_payload(source, resume=False):
    return ('ns={"__name__":"child_payload"};exec(' + repr(source)
            + ',ns);ns["child"](resume=' + repr(resume) + ')')


def extract(path, target):
    target.mkdir(mode=0o700)
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        for item in members:
            p = Path(item.name)
            if p.is_absolute() or '..' in p.parts or not (item.isfile() or item.isdir() or item.issym()):
                raise ValueError('unsafe archive member')
            if item.issym():
                link = (target / p.parent / item.linkname).resolve()
                if not link.is_relative_to(target):
                    raise ValueError('archive symlink escapes snapshot')
        archive.extractall(target)


def child(resume=False):
    if os.getuid() != 502 or os.geteuid() != 502 or Path.home() != HOME:
        raise RuntimeError('not the isolated test identity')
    if call(['/bin/launchctl', 'manageruid']) != '502':
        raise RuntimeError('wrong bootstrap domain')
    data = json.loads((DEST / 'inputs/inputs.json').read_text(encoding='utf-8'))
    for name, sha in data['files'].items():
        read_exact(DEST / 'inputs' / name, sha)
    facts = {'uid': os.getuid(), 'manageruid': 502, 'source': {}, 'production_install': False}
    try:
        for label in ('candidate', 'legacy'):
            target = DEST / (label + '-source')
            if not target.exists():
                extract(DEST / 'inputs' / (label + '.tar'), target)
            elif not resume or target.is_symlink() or target.resolve() != target:
                raise RuntimeError('unexpected existing snapshot')
            call(['/usr/bin/git', 'init', '-q'], target)
            # git archive contains tracked files even if .gitignore matches them.
            # Reconstruct that exact tracked tree, not a fresh untracked selection.
            call(['/usr/bin/git', 'add', '--force', '--all'], target)
            tree = call(['/usr/bin/git', 'write-tree'], target)
            if tree != data['source'][label]['tree']:
                raise RuntimeError('source snapshot tree differs: ' + label)
            call(['/usr/bin/git', '-c', 'user.name=Sulde isolated fixture', '-c',
                  'user.email=fixture@localhost', 'commit', '-qm', 'Exact isolated source snapshot'], target)
            facts['source'][label] = {**data['source'][label], 'snapshot_head': call(['/usr/bin/git', 'rev-parse', 'HEAD'], target)}
        (DEST / 'tools').mkdir(mode=0o700)
        binary = DEST / 'tools/codex'
        binary.write_bytes((DEST / 'inputs/codex').read_bytes())
        binary.chmod(0o700)
        facts['codex_version'] = call([str(binary), '--version'])
        if facts['codex_version'] != 'codex-cli 0.160.0':
            raise RuntimeError('unexpected Codex version')
        kb = DEST / 'live/sulde/data/kb'
        kb.mkdir(parents=True, mode=0o700)
        call([data['base_python'], '-B', '-m', 'venv', '--copies', '--system-site-packages', str(kb / 'venv')])
        python = kb / 'venv/bin/python'
        site = Path(call([str(python), '-B', '-I', '-c', 'import sysconfig;print(sysconfig.get_path("purelib"))']))
        # Archive has only a yaml/ prefix and no links; extract beneath the venv.
        with tarfile.open(DEST / 'inputs/yaml.tar') as archive:
            for member in archive.getmembers():
                if not member.isfile() or not member.name.startswith('yaml/') or '..' in Path(member.name).parts:
                    raise ValueError('unsafe dependency archive')
            archive.extractall(site)
        code = 'import json,sys;from pathlib import Path;sys.path.insert(0,' + repr(str(DEST / 'candidate-source/scripts/release')) + ');from python_environment import inspect_python;print(json.dumps(inspect_python(Path(sys.executable))))'
        facts['python'] = json.loads(call([str(python), '-B', '-I', '-c', code]))
        facts['status'] = 'toolchain-ready-not-installed'
    except Exception as error:
        facts.update(status='incomplete', error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        name = 'toolchain-result-resume.json' if resume else 'toolchain-result.json'
        with (DEST / name).open('x', encoding='utf-8') as output:
            json.dump(facts, output, indent=2)
        print(json.dumps(facts, sort_keys=True), flush=True)


def parent(slot, digest, resume=False):
    if os.getuid() != 0 or os.geteuid() != 0:
        raise RuntimeError('requires approved preparation only')
    account = pwd.getpwnam('suldeverify')
    guid = call(['/usr/bin/dscl', '.', '-read', '/Users/suldeverify', 'GeneratedUID'])
    if (account.pw_uid != 502 or account.pw_gid != 20 or account.pw_dir != str(HOME)
            or guid != 'GeneratedUID: 025B11A2-1162-4B20-AA0D-B025D2CC32F9'):
        raise RuntimeError('test account identity drifted')
    if slot.parent != SOURCE_PARENT or slot.resolve() != slot:
        raise RuntimeError('unexpected input root')
    raw = read_exact(slot / 'inputs.json', digest)
    data = json.loads(raw)
    if set(data['files']) != {'candidate.tar', 'legacy.tar', 'codex', 'yaml.tar'}:
        raise RuntimeError('unexpected copy scope')
    os.umask(0o077)
    if resume:
        if (DEST.resolve() != DEST or not DEST.is_dir() or DEST.stat().st_uid != 502
                or not (DEST / 'toolchain-result.json').is_file()):
            raise RuntimeError('no exact partial preparation to resume')
    else:
        DEST.mkdir(mode=0o700)
        os.chown(DEST, 502, 20)
    inputs = DEST / 'inputs'
    if resume:
        read_exact(inputs / 'inputs.json', digest)
        for name, expected in data['files'].items():
            read_exact(inputs / name, expected)
    else:
        inputs.mkdir(mode=0o700)
        os.chown(inputs, 502, 20)
        for name, expected in data['files'].items():
            held = read_exact(slot / name, expected)
            path = inputs / name
            with path.open('xb') as output:
                output.write(held)
            path.chmod(0o400)
            os.chown(path, 502, 20)
        (inputs / 'inputs.json').write_bytes(raw)
        (inputs / 'inputs.json').chmod(0o400)
        os.chown(inputs / 'inputs.json', 502, 20)
    # Held source enters the child, but execution after setuid is unprivileged.
    source = Path(__file__).read_text(encoding='utf-8')
    environment = {'HOME': str(HOME), 'USER': 'suldeverify', 'LOGNAME': 'suldeverify',
                   'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'en_US.UTF-8',
                   'PYTHONDONTWRITEBYTECODE': '1', 'CODEX_HOME': str(DEST / 'tool-preflight-codex')}
    drop = ('import os;os.initgroups("suldeverify",20);os.setgid(20);os.setuid(502);'
            + 'os.execve("/usr/bin/python3",["/usr/bin/python3","-B","-I","-c",'
            + repr(child_payload(source, resume)) + '],'
            + repr(environment) + ')')
    os.execve('/bin/launchctl', ['/bin/launchctl', 'asuser', '502', '/usr/bin/python3', '-B', '-I', '-c', drop],
              {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'en_US.UTF-8'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('slot', type=Path)
    parser.add_argument('digest')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    parent(args.slot, args.digest, args.resume)
