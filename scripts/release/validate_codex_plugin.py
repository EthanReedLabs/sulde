#!/usr/bin/env python3
"""Validate the Sulde Codex plugin with the repository's stdlib-only truth."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "release"))
import install_codex_plugin as installer  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "plugin",
        nargs="?",
        type=Path,
        default=ROOT / "integrations" / "codex" / "plugins" / "sulde",
    )
    parser.add_argument("--expected-version", default="")
    args = parser.parse_args()
    plugin = args.plugin.expanduser().resolve()
    if args.expected_version:
        expected = args.expected_version
    else:
        descriptor = json.loads(
            (plugin / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        expected = str(descriptor.get("version") or "")
    complete = (
        (plugin / "runtime" / "knowledge" / "MANIFEST.json").is_file()
        and (plugin / "hooks" / "hooks.json").is_file()
    )
    if complete:
        validated = installer.validate_plugin_root(plugin, expected_version=expected)
    else:
        # The repository integration tree is intentionally sparse. Validate
        # the same fully assembled marketplace that installation consumes,
        # using only the standard library and a disposable directory.
        with tempfile.TemporaryDirectory(prefix="sulde-plugin-validate-") as name:
            marketplace = Path(name) / "marketplace"
            platform = "windows" if os.name == "nt" else "posix"
            subprocess.run(
                [
                    sys.executable,
                    "-S",
                    "-B",
                    str(installer.STAGER),
                    "--target",
                    "codex",
                    "--platform",
                    platform,
                    "--output",
                    str(marketplace),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
            installer._complete_staged_native_runtime(
                marketplace,
                platform=platform,
            )
            validated = installer.validate_staged_marketplace(
                marketplace,
                expected_version=expected,
            )
    print(
        json.dumps(
            {
                "schema": "sulde-codex-plugin-validation-v1",
                "status": "valid",
                "plugin": str(plugin),
                "version": validated["version"],
                "validator": "repository-stdlib",
                "pyyaml_required": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
