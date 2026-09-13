# Licensing guide

**English** | [简体中文](LICENSING.zh-CN.md)

Sulde's current source is offered under the **PolyForm Noncommercial License 1.0.0**, with SPDX
identifier `PolyForm-Noncommercial-1.0.0`. Commercial use is outside this license grant.
See [LICENSE](../LICENSE) for the full terms and [NOTICE](../NOTICE) for copyright and attribution.
This guide explains usage; the English license text controls. This guide does not add, remove,
or replace any license term.

## Permitted uses

- Use Sulde for personal study, experiments, research, and hobby projects without any anticipated commercial application.
- Read, copy, modify, maintain forks, and share modified versions for purposes permitted by the license.
- Submit issues, documentation fixes, and code contributions under the [contribution guidelines](../CONTRIBUTING.md).

The standard license's `Noncommercial Organizations` provision also expressly permits use by
charitable organizations, educational institutions, public research organizations, public safety
or health organizations, environmental protection organizations, and government institutions,
regardless of their funding sources or obligations arising from that funding. That provision
remains intact; this license must not be described as prohibiting all organizational use.

## Commercial use boundaries

For commercial purposes outside the license's express permissions, the following uses are not granted:

| Scenario | Current license |
| --- | --- |
| Selling or distributing Sulde, or products based on modified Sulde source, for a fee | Not granted |
| Packaging Sulde as a paid plugin, SaaS offering, hosted service, or part of a commercial product | Not granted |
| Using Sulde internally to support commercial development, production, or business operations | Not granted; internal use is not an exemption |
| Using Sulde for paid contracting, client delivery, or commercial consulting | Not granted |
| Providing Sulde services for free to generate commercial leads, advertising revenue, or promotion for a commercial product | Free access does not itself grant permission |

The purpose of the use and the license's express permissions determine the boundary, not just
whether a separate plugin fee is charged. A personal account, private fork, internal deployment,
or publication of modified source does not automatically confer commercial use rights.
This repository does not offer commercial authorization or promise that it will be available
separately. Direct licensing questions to [eric.gao.tech@gmail.com](mailto:eric.gao.tech@gmail.com).

## Copying, modification, and redistribution

Anyone receiving any part of the software must also receive the license text or its official URL,
and all `Required Notice:` statements provided with the project. Include `LICENSE` and `NOTICE`
unchanged where practical, identify modifications and their source, and retain applicable
third-party license and copyright notices. Forking or repackaging does not remove license restrictions.

The project license covers project-owned code, scripts, hooks, skills, templates, and documentation,
except material explicitly licensed otherwise. Third-party dependencies, downloaded models, and
external hosts or API services retain their own terms. This license does not claim ownership of
users' independently authored project code or knowledge. Material containing or adapting Sulde
content remains subject to the applicable terms. Ownership of an independent output does not
itself authorize commercial use of Sulde as a tool.

See the [third-party inventory](../THIRD_PARTY_NOTICES.md) for dependency and model sources,
their upstream license references, and the additional records needed for bundled distributions.

## Why source available

[Section 6 of the Open Source Definition](https://opensource.org/osd) requires that licenses do
not restrict fields of endeavor, including business use. Sulde therefore uses the description
“source available for noncommercial use” rather than claiming to be open source in the OSI sense.
Publicly accessible source does not grant permission for every purpose.

## License history

The change takes effect at the **source revision containing the license change**. A reused plugin
version number alone is not enough to identify applicable terms. Check the exact commit, the
`LICENSE` bundled with the release, and its accompanying notices.

| Material | Applicable terms |
| --- | --- |
| Historical v0.1.x | Existing MIT grants remain effective; see the [MIT text in Git history](https://github.com/EthanReedLabs/sulde-cc/blob/d70748711e00a772fee5073f67a8d9b6c1bce91e/LICENSE-v0.1.0-MIT-archive) |
| Copies distributed under BSL 1.1 before this change | Their original BSL conditions and change-license rights remain effective; see the [BSL declaration in Git history](https://github.com/EthanReedLabs/sulde-cc/blob/d70748711e00a772fee5073f67a8d9b6c1bce91e/LICENSE-BSL-1.1-archive) |
| New material first distributed under the current license | PolyForm Noncommercial 1.0.0, with no automatic MIT conversion date |

Historical license files are kept in the pinned Git revision above rather than the current source
tree or plugin packages. The current project license file is `LICENSE`.

The new declaration does not revoke or reduce rights already granted for historical versions or
their content. It does not relicense third-party or historical contributor material without the
necessary permission. Historical material may be used under its original grant; a version that
includes new material must also satisfy the applicable terms for that material. The archives do
not offer an MIT or BSL dual-license option for new material.

## Official references

- [PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0)
- [SPDX license identifier](https://spdx.org/licenses/PolyForm-Noncommercial-1.0.0.html)
- [Historical BSL 1.1 text](https://mariadb.com/bsl11/)
