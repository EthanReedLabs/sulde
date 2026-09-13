# Third-party software and models

**English** | [简体中文](THIRD_PARTY_NOTICES.zh-CN.md)

This inventory describes external components referenced by Sulde's source and bootstrap scripts.
Sulde's [LICENSE](LICENSE) and [NOTICE](NOTICE) apply to project-owned material; they do not replace
the terms of these components. Upstream declarations below were reviewed on **2026-09-13**.

## Distribution scope

The source staging workflow packages Sulde code, documentation, and empty knowledge containers.
It does not install Python packages or download model weights into the plugin artifact. Bootstrap
installs packages and downloads models separately into the user's data environment. Claude Code
and Codex are separate host products, not included binaries.

This is a source dependency inventory, **not a resolved SBOM or a complete notice bundle for an
offline distribution**. Versions, transitive dependencies, model conversions, and binary contents
depend on the actual environment. A listed upstream license is not an attestation about every
version or download bearing the same name.

## Python dependencies

Source references below are paths within the Sulde repository. Bootstrap is
`scripts/kb/bootstrap.sh`; imports also occur in `tools/kb-index/` and `scripts/kb/`.

| Component | Role and declaration | Upstream license reference |
| --- | --- | --- |
| PyYAML | YAML parsing; `hooks/requirements.txt` declares `pyyaml>=6.0`; bootstrap installs `pyyaml` | [MIT — PyYAML](https://github.com/yaml/pyyaml/blob/main/LICENSE) |
| FastEmbed | Embeddings and reranking; bootstrap installs `fastembed` | [Apache-2.0 — FastEmbed](https://github.com/qdrant/fastembed/blob/main/LICENSE) |
| jieba | Chinese tokenization; bootstrap installs `jieba` | [MIT — jieba](https://github.com/fxsjy/jieba/blob/master/LICENSE) |
| cryptography | Encryption used by `scripts/kb/mem-sync.py`; bootstrap installs `cryptography` | [Apache-2.0 OR BSD-3-Clause — cryptography](https://github.com/pyca/cryptography/blob/main/LICENSE) |
| NumPy | Numerical operations in retrieval and memory modules; supplied through the FastEmbed dependency environment | [BSD-3-Clause — NumPy](https://github.com/numpy/numpy/blob/main/LICENSE.txt) |

Bootstrap does not pin exact package versions and reuses an existing environment when its import
check succeeds. These declarations therefore do not identify a reproducible installed dependency
set. Binary wheels may contain additional components and notices, including native libraries.

## Models

| Model name used by Sulde | Purpose | Original upstream declaration |
| --- | --- | --- |
| `BAAI/bge-small-zh-v1.5` | Chinese text embeddings | [MIT — original model card](https://huggingface.co/BAAI/bge-small-zh-v1.5/blob/main/README.md) |
| `BAAI/bge-reranker-base` | Cross-encoder reranking | [MIT — original model card](https://huggingface.co/BAAI/bge-reranker-base/blob/main/README.md) |

FastEmbed resolves these model names to downloadable artifacts. This repository does not pin the
conversion repository, revision, or weight hashes. Before redistributing weights, identify the
actual downloaded files and their accompanying terms; the original model card alone is not a
license inventory for a converted artifact.

## Redistribution records

For a source-only plugin package, retain this inventory with the project license and notices.
If adding dependencies, native binaries, dictionaries, or model weights to a distribution:

1. Record exact component versions, source URLs, model revisions, file hashes, and the target platform.
2. Obtain the license, copyright, and applicable NOTICE files from those exact distribution files,
   including transitive and embedded components; include the notices required by their terms.
3. Record any modifications and review compatibility for the actual use and distribution.
4. Keep third-party rights separate from Sulde's noncommercial grant and its historical MIT/BSL grants.

These records supplement the [licensing guide](docs/LICENSING.md). Product names identify integration
points and sources; they do not imply endorsement or ownership by Sulde.
