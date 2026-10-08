"""Failure-only pytest observer; no command, assertion or policy alteration."""
import json
import os
from pathlib import Path


def pytest_exception_interact(node, call, report):
    target = Path(os.environ["SULDE_DIAGNOSTIC_FAILURE_OUTPUT"])
    if target.exists():
        return
    selected = []
    for entry in call.excinfo.traceback:
        values = entry.frame.f_locals
        host = values.get("host")
        if host is None or not hasattr(host, "notifications"):
            continue
        items = []
        for event in host.notifications:
            if event.get("method") == "item/completed":
                item = event.get("params", {}).get("item", {})
                if item.get("type") == "commandExecution":
                    items.append(item)
            elif event.get("method") == "hook/completed":
                items.append({"hook": event.get("params", {}).get("run", {})})
        selected.append({"frame": entry.name, "events": items,
                         "fixture_results": values.get("fixture_results", [])})
    with target.open("x", encoding="utf-8") as output:
        os.chmod(target, 0o600)
        json.dump({"nodeid": node.nodeid, "frames": selected}, output,
                  ensure_ascii=False, indent=2)
        output.write("\n")
