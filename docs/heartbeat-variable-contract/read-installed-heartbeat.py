#!/usr/bin/env python3
"""Read-only identities/state, never a model invocation or problem closure."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    home = Path(sys.argv[1]).resolve()
    expected = sys.argv[2]
    deployment = json.loads((home / "deployment-generation.json").read_text())
    owner = json.loads((home / "runtime-owner.json").read_text())
    assert deployment["status"] == "generation_verified"
    assert deployment["generation"] == owner["generation"] == expected
    assert owner["provider"] == "codex"
    runtime = Path(owner["runtime_root"]).resolve()
    manifest = json.loads((runtime.parent / ".codex-plugin/generation.json").read_text())
    assert manifest["generation"] == expected
    source = runtime / "scripts/kb/heartbeat.py"
    sys.path.insert(0, str(source.parent))
    spec = importlib.util.spec_from_file_location("installed_heartbeat_readback", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    raw = (home / "SELF.md").read_bytes()
    text = raw.decode("utf-8")
    module.variable_self(text)
    fixed = module.fixed_self(text).encode("utf-8")
    beat = json.loads((home / "heartbeat-state.json").read_text())
    life = json.loads((home / "life/state.json").read_text())
    print(json.dumps(dict(schema="heartbeat-installed-readback-v1", generation=expected,
        provider=owner["provider"], heartbeat_source_sha256=sha(source.read_bytes()),
        self_sha256=sha(raw), fixed_sha256=sha(fixed), fixed_bytes=len(fixed),
        self_chars=len(text), layout_valid=True,
        heartbeat={key: beat.get(key) for key in
                   ("sequence", "last_ts", "last_mode", "last_degraded_reason", "compression_attempts", "collection_status")},
        life={"status": life.get("status"), "generated_at": life.get("generated_at"),
              "heartbeat_generation": life.get("health_domains", {}).get("heartbeat_generation"),
              "problems": life.get("health_domains", {}).get("problems")}), indent=2))


if __name__ == "__main__":
    main()
