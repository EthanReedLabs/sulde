"""Task-local readback and synthetic Claude checks; does not install anything."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = Path('/Users/eric/.sulde/artifacts/sulde-claude-0.8.10-20261005-s3')
OUT = Path('/Volumes/Optimus/Sulde/tasks/guardian-unified-plan-20261004/S3-B')
spec = importlib.util.spec_from_file_location(
    'prior_readback', ROOT/'docs/guardian-effect-recovery-20261004/release_evidence.py')
prior = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prior)
prior.ROOT = ROOT


def main():
    action = sys.argv[1]
    assert action in {'before', 'before-claude', 'candidate-claude', 'installed-claude', 'final'}
    assert os.path.ismount('/Volumes/Optimus'), 'external disk not mounted'
    os.umask(0o077)
    result = {'schema':'sulde-s3-release-readback-v1', 'action':action,
              'at':datetime.now(timezone.utc).isoformat(),
              'source':prior.command(['git','rev-parse','HEAD'],cwd=ROOT)['stdout'].strip()}
    result.update(prior.inventory())
    if action in {'candidate-claude', 'installed-claude'}:
        root = ARTIFACT
        if action == 'installed-claude':
            installed = json.loads(result['inventory']['claude']['stdout'])
            selected = [p for p in installed if p['id'] == 'sulde-cc@sulde']
            assert len(selected)==1 and selected[0]['version']=='0.8.10' and selected[0]['enabled']
            root = Path(selected[0]['installPath'])
        snapshot = prior.files(root)
        changed = prior.command(['git','diff','--name-only','ac5dc9c','HEAD','--','scripts','hooks'],cwd=ROOT)
        assert changed['returncode']==0
        matched = {}
        for rel in changed['stdout'].splitlines():
            if (root/rel).is_file():
                matched[rel] = prior.sha(root/rel)
                assert matched[rel]==prior.sha(ROOT/rel), rel
        if action == 'installed-claude':
            assert snapshot == prior.files(ARTIFACT), 'artifact/install content differs'
        result['files'] = snapshot
        result['source_matches'] = matched
        result['smoke'] = prior.smoke(root)
        assert prior.files(root)==snapshot, 'Hook subprocess changed immutable artifact'
    OUT.mkdir(parents=True,exist_ok=True)
    path = OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-'+action+'.json')
    with path.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    parsed=json.loads(path.read_text(encoding='utf-8'))
    assert parsed==result
    print(json.dumps({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                      'status':'readback_verified','matched_modules':len(result.get('source_matches',{}))}))


if __name__=='__main__':
    main()
