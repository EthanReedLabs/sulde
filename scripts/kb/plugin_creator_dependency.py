"""Read-only preflight for the existing, exact plugin-creator dependency.

This module neither discovers alternate executors nor restores files or grants
authority. Restoration must be reviewed separately; absent host-owned files are
an installation prerequisite failure, not permission to relax the seal.
"""
from __future__ import annotations

import ast
from pathlib import Path


class PluginCreatorDependencyError(ValueError):
    pass


def check_cachebuster_dependency(helper: Path) -> None:
    if not helper.is_file():
        raise PluginCreatorDependencyError(
            "official plugin cachebuster helper is unavailable: " + str(helper)
            + "; restore a reviewed dependency before sealing; production unchanged"
        )
    try:
        tree = ast.parse(helper.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError) as error:
        raise PluginCreatorDependencyError("cachebuster helper cannot be inspected") from error
    # Historical lightweight helpers did not import this companion. Do not
    # invent a dependency for those rows/fixtures, or execute helper code here.
    imports_identifier = any(
        (isinstance(node, ast.ImportFrom) and node.module == "identifier_validation")
        or (isinstance(node, ast.Import) and any(
            alias.name == "identifier_validation" for alias in node.names))
        for node in ast.walk(tree)
    )
    if imports_identifier:
        companion = helper.parent / "identifier_validation.py"
        if companion.is_symlink() or not companion.is_file():
            raise PluginCreatorDependencyError(
                "cachebuster dependency is incomplete: " + str(companion)
                + "; restore the reviewed companion before sealing"
            )
        try:
            ast.parse(companion.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, SyntaxError) as error:
            raise PluginCreatorDependencyError("cachebuster companion cannot be inspected") from error
