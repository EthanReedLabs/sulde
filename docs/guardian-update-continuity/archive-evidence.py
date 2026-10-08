"""Local-only, unique Optimus archive with independent content readback."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
DESTINATION = Path("/Volumes/Optimus/Sulde/tasks/guardian-unified-plan-20261004/S3-C-repair")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if not Path("/Volumes/Optimus").is_mount():
        raise SystemExit("Optimus not mounted; local evidence retained")
    os.umask(0o077)
    destination = DESTINATION / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ-candidate")
    destination.mkdir(parents=True, exist_ok=False)
    sources = {
        "integration": ROOT / ".codex-agent/s3c-evidence",
        "stable-integration": ROOT / ".codex-agent/s3c-stable-evidence",
        "dev-integration": ROOT / ".codex-agent/s3c-dev-integration-evidence",
        "m1": ROOT / ".codex-agent/s3c-m1-evidence",
        "m2": ROOT / ".codex-agent/s3c-m2-evidence",
        "bootstrap": ROOT / ".codex-agent/s3c-bootstrap-evidence",
        "maintenance": ROOT / ".codex-agent/s3c-maintenance-evidence",
        "interactive": ROOT / ".codex-agent/s3c-bootstrap-interactive",
        "entry": ROOT.parent / "guardian-update-entry/.codex-agent/s3-c-entry-evidence",
    }
    manifest = {}
    for label, source in sources.items():
        paths = (list(source.glob("*/probe-state.json")) + list(source.glob("*/isolated/workspace/benign-marker.json"))
                 if label == "interactive" else source.rglob("*"))
        for path in sorted(paths):
            if not path.is_file() or path.is_symlink():
                continue
            if (label == "dev-integration" and "host-schema" in path.relative_to(source).parts
                    and path.name not in {"ClientRequest.json", "PluginReconcileResponse.json",
                                          "HooksListParams.json", "ThreadLoadedListResponse.json"}):
                continue  # Keep relevant exact protocol evidence, not unrelated generated schemas.
            relative = Path(label) / path.relative_to(source)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            assert digest(target) == digest(path), relative
            manifest[str(relative)] = digest(target)
    names = subprocess.check_output(["git", "diff", "--name-only", "eacee08", "HEAD"],
                                    cwd=ROOT, text=True, encoding="utf-8", errors="replace").splitlines()
    for name in names:
        source = ROOT / name
        if not source.is_file() or source.is_symlink():
            raise ValueError("unexpected source kind: " + name)
        target = destination / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        assert digest(source) == digest(target), name
        manifest["source/" + name] = digest(target)
    index = destination / "sha256.json"
    index.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, expected in json.loads(index.read_text(encoding="utf-8")).items():
        assert digest(destination / name) == expected, name
    print(json.dumps({"archive": str(destination), "files_verified": len(manifest),
                      "manifest_sha256": digest(index), "self_excluded": True}))


if __name__ == "__main__":
    main()
