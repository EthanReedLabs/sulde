"""Small, conservative proofs for builtin data methods with filesystem names.

This is not a Python type checker. Literal/list proofs remain conservative;
bounded forward string proofs additionally support ordinary text transformations.
Unknown objects and effectful arguments never receive a data-method exemption.
"""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
import re

from python_string_flow import proven_string_method_calls


def inline_source(tokens: list[str]) -> str | None:
    """One exact Python -c invocation, including harmless interpreter flags."""
    if not tokens or not re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", Path(tokens[0]).name.lower()):
        return None
    position = 1
    while position < len(tokens) and re.fullmatch(r"-[BEIsSuq]+", tokens[position]):
        position += 1
    if len(tokens) >= position + 2 and tokens[position] == "-c":
        return tokens[position + 1]
    return None


def literal_shell_transport(command: str) -> bool:
    """No shell interpolation; shell control is checked separately by caller."""
    quote = ""
    escaped = False
    for char in command:
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote != "'":
            escaped = True
        elif quote == "'":
            if char == "'":
                quote = ""
        elif char in {"$", "`"}:
            return False
        elif char == quote:
            quote = ""
        elif not quote and char in {"'", '"'}:
            quote = char
    return not quote


def proven_data_method_calls(tree: ast.Module) -> set[int]:
    nodes = list(ast.walk(tree))
    writes = Counter(
        node.id for node in nodes
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))
    )
    shadowed = {node.arg for node in nodes if isinstance(node, ast.arg)}
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            shadowed.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            shadowed.update(item.asname or item.name.split(".")[0] for item in node.names)
    dynamic_namespace = any(
        (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
         and node.func.id in {"exec", "eval", "globals", "locals", "vars", "setattr"})
        or (isinstance(node, (ast.Attribute, ast.Subscript))
            and isinstance(node.ctx, (ast.Store, ast.Del)))
        or (isinstance(node, ast.Import) and any(item.name != "pathlib" for item in node.names))
        or (isinstance(node, ast.ImportFrom) and node.module != "pathlib")
        for node in nodes
    )
    positions = lambda node: (node.lineno, node.col_offset)
    parents = {id(child): parent for parent in nodes for child in ast.iter_child_nodes(parent)}
    path_names = {item.asname or item.name for node in tree.body
                  if isinstance(node, ast.ImportFrom) and node.module == "pathlib"
                  for item in node.names if item.name == "Path"}

    def stable_binding(use: ast.Name, since: tuple[int, int], depth: int) -> bool:
        parent = parents.get(id(use))
        while parent is not None:
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                                   ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                return False
            parent = parents.get(id(parent))
        for call in nodes:
            if not isinstance(call, ast.Call) or not since < positions(call):
                continue
            # Enclosing calls execute after evaluating this argument. Earlier
            # opaque calls could mutate the module namespace or a borrowed list.
            if (call.end_lineno, call.end_col_offset) > positions(use):
                continue
            if is_data_call(call, depth + 1):
                continue
            if isinstance(call.func, ast.Name) and not writes[call.func.id]:
                if (call.func.id in path_names and not call.keywords and len(call.args) == 1
                        and isinstance(call.args[0], ast.Constant) and type(call.args[0].value) is str):
                    continue
                if (call.func.id == "print" and "print" not in shadowed and not call.keywords
                        and all(literal_kind(arg, positions(call), depth + 1) for arg in call.args)):
                    continue
            return False
        return True
    # A list can acquire user-defined elements through aliases/append; remove
    # could then execute arbitrary __eq__. Only unescaped literal lists qualify.
    def unescaped_list(name: str) -> bool:
        for use in nodes:
            if isinstance(use, ast.Name) and use.id == name and isinstance(use.ctx, ast.Load):
                parent = parents.get(id(use))
                if not (isinstance(parent, ast.Attribute) and parent.attr == "remove"):
                    # Printing a list is safe only before it can contain custom
                    # elements, but proving general call escape is out of scope.
                    if not (isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name)
                            and parent.func.id == "print" and "print" not in shadowed and not writes["print"]):
                        return False
        return True

    assignments: dict[str, tuple[ast.AST, tuple[int, int]]] = {}
    if not dynamic_namespace:
        for statement in tree.body:
            if (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)):
                name = statement.targets[0].id
                if writes[name] == 1 and name not in shadowed:
                    if not isinstance(statement.value, ast.List) or unescaped_list(name):
                        assignments[name] = (statement.value, positions(statement))

    def literal_kind(node: ast.AST, before: tuple[int, int], depth: int = 0) -> str:
        if depth > 12:
            return ""
        if isinstance(node, ast.Constant):
            if type(node.value) is str:
                return "str"
            if type(node.value) is bytes:
                return "bytes"
            if type(node.value) in {int, float, bool, type(None)}:
                return "scalar"
        if isinstance(node, ast.List) and all(
            literal_kind(item, before, depth + 1) in {"str", "bytes", "scalar"}
            for item in node.elts
        ):
            return "list"
        if isinstance(node, ast.Name) and node.id in assignments:
            value, line = assignments[node.id]
            if line < before and value is not node and stable_binding(node, line, depth):
                return literal_kind(value, line, depth + 1)
        if isinstance(node, ast.Call) and is_data_call(node, depth + 1):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "replace":
                return literal_kind(node.func.value, positions(node), depth + 1)
        return ""

    def is_data_call(node: ast.Call, depth: int = 0) -> bool:
        if depth > 12 or not isinstance(node.func, ast.Attribute) or node.keywords:
            return False
        receiver = literal_kind(node.func.value, positions(node), depth + 1)
        if node.func.attr == "replace" and receiver in {"str", "bytes"}:
            return len(node.args) in {2, 3} and all(
                literal_kind(argument, positions(node), depth + 1)
                == (receiver if index < 2 else "scalar")
                for index, argument in enumerate(node.args)
            )
        if node.func.attr == "remove" and receiver == "list":
            return len(node.args) == 1 and literal_kind(
                node.args[0], positions(node), depth + 1
            ) in {"str", "bytes", "scalar"}
        return False

    proved = {id(node) for node in nodes if isinstance(node, ast.Call) and is_data_call(node)}
    if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
           and node.func.attr == "replace" and id(node) not in proved for node in nodes):
        proved.update(proven_string_method_calls(tree))
    return proved


def proven_path_method_calls(tree: ast.Module, aliases: dict[str, str]) -> set[int]:
    """Recognize only direct Path construction or a single module binding."""
    nodes = list(ast.walk(tree))
    counts = Counter(node.id for node in nodes if isinstance(node, ast.Name)
                     and isinstance(node.ctx, (ast.Store, ast.Del)))
    shadowed = {node.arg for node in nodes if isinstance(node, ast.arg)}
    dynamic = any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id in {"exec", "eval", "globals", "locals", "vars", "setattr"}
                  for node in nodes)

    def constructor(node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        if isinstance(node.func, ast.Name):
            return aliases.get(node.func.id) == "pathlib.Path" and node.func.id not in shadowed and not counts[node.func.id]
        return (isinstance(node.func, ast.Attribute) and node.func.attr == "Path"
                and isinstance(node.func.value, ast.Name)
                and aliases.get(node.func.value.id) == "pathlib"
                and not counts[node.func.value.id])

    bindings = {}
    if not dynamic:
        for node in tree.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and counts[node.targets[0].id] == 1 and node.targets[0].id not in shadowed
                    and constructor(node.value)):
                bindings[node.targets[0].id] = (node.lineno, node.col_offset)
    proved = set()
    for node in nodes:
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        receiver = node.func.value
        if constructor(receiver) or (
            isinstance(receiver, ast.Name) and receiver.id in bindings
            and bindings[receiver.id] < (node.lineno, node.col_offset)
        ):
            proved.add(id(node))
    return proved
