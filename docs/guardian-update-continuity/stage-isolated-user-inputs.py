"""Export exact source snapshots and tooling only, never the production KB home."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
CODEX = Path('/Users/eric/.nvm/versions/node/v18.20.8/lib/node_modules/@openai/codex/node_modules/@openai/codex-darwin-arm64/vendor/aarch64-apple-darwin/bin/codex')
YAML = Path('/Users/eric/.sulde/data/kb/venv/lib/python3.10/site-packages/yaml')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True,
                                   encoding='utf-8', errors='strict').strip()


def main():
    os.umask(0o077)
    slot = ROOT / '.codex-agent/s3c-user-environment' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    slot.mkdir(parents=True, exist_ok=False)
    source = {}
    for label, ref in [('candidate', '7e85477'), ('legacy', '756598f')]:
        path = slot / (label + '.tar')
        subprocess.run(['git', 'archive', '--format=tar', '--output', str(path), ref], cwd=ROOT, check=True)
        source[label] = {'commit': git('rev-parse', ref), 'tree': git('rev-parse', ref + '^{tree}')}
    shutil.copyfile(CODEX, slot / 'codex')
    # Only the installed dependency package, no parent directories or KB data.
    with tarfile.open(slot / 'yaml.tar', 'w') as archive:
        for path in sorted(YAML.rglob('*')):
            if path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts:
                archive.add(path, arcname='yaml/' + str(path.relative_to(YAML)), recursive=False)
    files = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in slot.iterdir() if path.is_file()}
    manifest = {'schema': 'sulde-r18-tool-input-v1', 'source': source, 'files': files,
                'base_python': '/Users/eric/.pyenv/versions/3.10.7/bin/python3.10',
                'scope': 'tracked-source-snapshots-and-codex-pyyaml-tooling-only',
                'production_kb_or_credentials_exported': False}
    (slot / 'inputs.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({'slot': str(slot), 'manifest_sha256': hashlib.sha256((slot / 'inputs.json').read_bytes()).hexdigest(), **manifest}))


if __name__ == '__main__':
    main()
