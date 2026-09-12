"""Bounded forward proofs for immutable strings, not general Python execution.

Only the identities of proved replace calls leave this module. All other calls
and their arguments remain independently classified by the effect collector.
No evaluation, imports, filesystem access, or inferred user-defined return types.
"""
from __future__ import annotations

import ast


class _StringFlow:
    def __init__(self) -> None:
        self.facts: dict[str, str] = {}
        self.proved: set[int] = set()
        self.pathlib_intact = True
        self.builtins_intact = True

    def barrier(self) -> None:
        # An opaque call can change globals or monkey-patch a borrowed factory.
        # A later literal assignment can establish a fresh immutable fact, but
        # re-importing a cached module cannot undo an unknown monkey-patch.
        self.facts.clear()
        self.pathlib_intact = False
        self.builtins_intact = False

    def expression(self, node: ast.AST | None, depth: int = 0) -> str:
        if depth > 48:
            raise RecursionError("string proof depth budget")
        if node is None:
            return ""
        evaluate = lambda child: self.expression(child, depth + 1)
        if isinstance(node, ast.Constant):
            return {str: "str", bytes: "bytes", int: "int", bool: "bool",
                    float: "float", type(None): "none"}.get(type(node.value), "")
        if isinstance(node, ast.Name):
            return self.facts.get(node.id, "")
        if isinstance(node, ast.Call):
            # Evaluate the bound receiver before arguments, just as Python does.
            if isinstance(node.func, ast.Attribute):
                receiver = evaluate(node.func.value)
                method = node.func.attr
                trusted_method = (receiver in {"str", "bytes"} and method == "replace") or (
                    receiver == "path" and self.pathlib_intact
                    and method in {"read_text", "read_bytes"})
                constructor = receiver == "pathlib" and method == "Path" and self.pathlib_intact
                if not trusted_method and not constructor:
                    # Attribute lookup itself may invoke a descriptor.
                    self.barrier()
            else:
                receiver, method = "", ""
                factory = evaluate(node.func)
                constructor = factory == "Path" and self.pathlib_intact
            arguments = [evaluate(arg) for arg in node.args]
            keywords = [(item.arg, evaluate(item.value)) for item in node.keywords]
            if (method == "replace" and receiver in {"str", "bytes"}
                    and not keywords and len(arguments) in {2, 3}
                    and arguments[:2] == [receiver, receiver]
                    and (len(arguments) == 2 or arguments[2] in {"int", "bool"})):
                self.proved.add(id(node))
                return receiver
            if constructor and self.pathlib_intact and arguments == ["str"] and not keywords:
                return "path"
            if receiver == "path" and self.pathlib_intact:
                if method == "read_bytes" and not arguments and not keywords:
                    return "bytes"
                if (method == "read_text" and len(arguments) <= 2
                        and all(kind in {"str", "none"} for kind in arguments)
                        and all(key in {"encoding", "errors", "newline"} and kind in {"str", "none"}
                                for key, kind in keywords)):
                    return "str"
            if (isinstance(node.func, ast.Name) and node.func.id == "print"
                    and "print" not in self.facts and self.builtins_intact
                    and not keywords and all(kind in {"str", "bytes", "int", "bool", "float", "none"}
                                             for kind in arguments)):
                return "none"
            self.barrier()
            return ""
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp)):
            generators = node.generators
            # Each eager iteration freshly binds an exact builtin value. Never
            # import a module/global name fact into this implicit scope.
            if len(generators) == 1:
                generator = generators[0]
                sequence = generator.iter
                if (not generator.is_async and not generator.ifs
                        and isinstance(generator.target, ast.Name)
                        and isinstance(sequence, (ast.Tuple, ast.List)) and sequence.elts
                        and all(isinstance(item, ast.Constant) and type(item.value) in {str, bytes}
                                for item in sequence.elts)):
                    kinds = {type(item.value) for item in sequence.elts}
                    if len(kinds) == 1:
                        nested = _StringFlow()
                        nested.barrier()
                        nested.facts[generator.target.id] = "str" if str in kinds else "bytes"
                        if isinstance(node, ast.DictComp):
                            nested.expression(node.key, depth + 1)
                            nested.expression(node.value, depth + 1)
                        else:
                            nested.expression(node.elt, depth + 1)
                        self.proved.update(nested.proved)
            self.barrier()
            return ""
        if isinstance(node, (ast.Lambda, ast.GeneratorExp)):
            # Deferred scopes must not borrow call-time facts.
            self.barrier()
            return ""
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            for item in node.elts:
                evaluate(item)
            return ""
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                evaluate(key)
                evaluate(value)
                # Unknown keys / ** expansion may invoke user code.
                if not isinstance(key, ast.Constant):
                    self.barrier()
            return ""
        # Do not execute expressions from alternative branches as sequential
        # statements, or assume overloaded operators/properties are harmless.
        self.barrier()
        return ""

    def statements(self, statements: list[ast.stmt]) -> None:
        for statement in statements:
            if isinstance(statement, ast.Assign):
                kind = self.expression(statement.value)
                if len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
                    # Keep an explicit unknown binding: print = opaque must not
                    # be mistaken for the builtin print after this assignment.
                    self.facts[statement.targets[0].id] = kind
                else:
                    self.barrier()
            elif isinstance(statement, ast.Expr):
                self.expression(statement.value)
            elif isinstance(statement, (ast.Import, ast.ImportFrom)):
                # An import is not evidence against fresh literals below it.
                # Only exact pathlib imports can establish a filesystem origin.
                if isinstance(statement, ast.ImportFrom):
                    is_pathlib = statement.level == 0 and statement.module == "pathlib"
                else:
                    is_pathlib = all(item.name == "pathlib" for item in statement.names)
                if not is_pathlib:
                    self.barrier()
                for item in statement.names:
                    name = item.asname or item.name.split(".")[0]
                    kind = ""
                    if is_pathlib and self.pathlib_intact:
                        if isinstance(statement, ast.Import):
                            kind = "pathlib"
                        elif item.name == "Path":
                            kind = "Path"
                    self.facts[name] = kind
            else:
                self.barrier()
                # Analyze eager nested suites from an empty state; no facts
                # survive joins or loop backedges. Do not enter deferred scopes.
                if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    for field in ("body", "orelse", "finalbody"):
                        suite = getattr(statement, field, None)
                        if isinstance(suite, list):
                            nested = _StringFlow()
                            nested.barrier()
                            nested.statements(suite)
                            self.proved.update(nested.proved)


def proven_string_method_calls(tree: ast.Module) -> set[int]:
    """Return bounded, forward-only proofs; unsupported shapes add no grants."""
    # Work is bounded by source size/depth, not by the runtime loop trip count.
    if sum(1 for _ in ast.walk(tree)) > 20000:
        return set()
    flow = _StringFlow()
    try:
        flow.statements(tree.body)
    except RecursionError:
        return set()
    return flow.proved
