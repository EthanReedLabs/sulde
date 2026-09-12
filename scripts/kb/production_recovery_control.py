"""Independent Codex recovery decision/execute bridge.

PermissionRequest records a question only. Execution of its exact protected
command after native Allow consumes it once. Neither a CLI phrase nor a
caller-supplied recovery dictionary can authorize another shell command.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import sys
import time

from production_recovery_readiness import _private_key, _private_directory
from production_recovery_targets import (
    RepairTarget, ProductionRepairAdapter, ProductionRepairVerifier, SUPPORTED_ACTIONS,
)
from recovery_lane import RecoveryLane, RecoveryLaneError, DECISION_SCHEMA, _plain_digest, _seal
from sulde_paths import layout
from command_template import split_command_template

CLI_NAME = "production-recovery.py"
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
CAPABILITY = re.compile(r"^sha256:[a-f0-9]{64}$")


def parse_command(command: str, runtime: Path) -> dict | None:
    if (not isinstance(command, str) or not command or len(command) > 65536
            or re.search(r"[;&|<>`$()\x00-\x08\x0a-\x1f\x7f]", command)):
        return None
    try:
        tokens = split_command_template(command)
    except ValueError:
        return None
    if tokens and re.fullmatch(r"python(?:3(?:\.\d+)?)?", Path(tokens[0]).name):
        if not Path(tokens[0]).is_absolute() or Path(tokens[0]).resolve() != Path(sys.executable).resolve():
            return None
        tokens.pop(0)
        if tokens and tokens[0] == "-B":
            tokens.pop(0)
    script = runtime / "scripts" / "kb" / CLI_NAME
    if len(tokens) < 2 or tokens[0] != str(script) or tokens[1] not in {"prepare", "execute", "status"}:
        return None
    action = tokens[1]
    options = {}
    for index in range(2, len(tokens), 2):
        if index + 1 >= len(tokens) or tokens[index] in options:
            return None
        options[tokens[index]] = tokens[index + 1]
    required = {"--workspace", "--session-id", "--intent-id"}
    if action == "prepare":
        required |= {"--action", "--target"}
    elif action == "execute":
        required |= {"--capability-id"}
    if set(options) != required:
        return None
    if any(not IDENTIFIER.fullmatch(options[k]) for k in ("--session-id", "--intent-id")):
        return None
    if action == "execute" and not CAPABILITY.fullmatch(options["--capability-id"]):
        return None
    workspace = Path(options["--workspace"])
    if not workspace.is_absolute() or str(workspace.resolve()) != str(workspace):
        return None
    return {"operation": action, **{k[2:].replace("-", "_"): v for k, v in options.items()}}


class ProductionRecoveryControl:
    def __init__(self, home: Path, runtime: Path):
        self.home, self.runtime = home.resolve(), runtime.resolve()
        key_path = self.home / "control" / "recovery.key"
        _private_directory(key_path.parent, label="recovery control directory")
        _private_directory(self.home / "state", label="recovery state directory")
        self.key = _private_key(key_path)
        self.lane = RecoveryLane(
            str(self.home / "state" / "recovery-lane.jsonl"), seal_key=self.key,
            wall_clock=time.time, monotonic_clock=time.monotonic,
        )

    def close(self):
        self.lane.state.close()

    def _rows(self, kind):
        return [e["payload"] for e in self.lane.state.snapshot_read_only()["events"]
                if e["event_type"] == kind]

    def _prepared(self, identity):
        rows = [r for r in self._rows("production_recovery_prepared")
                if r["capability"]["capability_id"] == identity]
        if len(rows) != 1:
            raise RecoveryLaneError("recovery plan is not uniquely prepared")
        row = rows[0]
        material = {k: v for k, v in row.items() if k != "seal"}
        if row.get("seal") != _seal(self.key, material):
            raise RecoveryLaneError("prepared recovery plan seal differs")
        return row

    def prepare(self, *, action, target, workspace, session_id, intent_id):
        repair = RepairTarget(self.home, self.runtime, action, target)
        before = repair.snapshot()
        if repair.passed(before):
            raise RecoveryLaneError("target already satisfies repair postcondition")
        capability = self.lane.issue_capability(
            provider="codex", session_id=session_id, workspace=workspace,
            installed_generation=before["generation"], action=action,
            target_identity=target, expected_pre_state=before,
            expires_at=time.time() + 600,
            verifier_identity=ProductionRepairVerifier.identity, nonce=secrets.token_hex(16),
        ).to_dict()
        row = {"capability": capability, "intent_id": intent_id,
               "executor_identity": ProductionRepairAdapter.identity,
               "control_identity": _plain_digest("recovery-control", Path(__file__).read_text())}
        row["seal"] = _seal(self.key, row)
        self.lane.state.append("production_recovery_prepared", row, unique_fields=("seal",))
        return self.preview(row)

    def preview(self, row):
        cap = row["capability"]
        if cap["action"] == "repair_launcher":
            change = f"重建启动入口 {self.home / 'bin' / cap['target_identity']}"
        else:
            change = f"清理 {self.runtime} 下已冻结清单中的 {len(cap['expected_pre_state']['files'])} 个生成字节码文件"
        argv = [sys.executable, "-B", str(self.runtime / "scripts" / "kb" / CLI_NAME),
                "execute", "--capability-id", cap["capability_id"],
                "--workspace", cap["workspace"], "--session-id", cap["session_id"],
                "--intent-id", row["intent_id"]]
        description = (
            f"允许 Sulde 在当前 Codex 会话{change}吗？"
            f"任务：{cap['workspace']}；版本：{cap['installed_generation'].split(':', 1)[0]}。"
            "仅修改已列出的派生产物，"
            "保留原文件备份、源代码和权威账本；失败尝试恢复原文件，独立回读通过才报告恢复成功。"
            "本次确认仅使用一次，不授权安装、清除债务或其他命令。"
        )
        return {"command_argv": argv, "description": description,
                "intent_id": row["intent_id"], "card": self.lane.recovery_card(cap),
                "human_confirmation": "pending", "repair_execution": "configured",
                "recovery_verified": False}

    def validate(self, spec, *, allow_prepared=False):
        row = self._prepared(spec["capability_id"])
        cap = row["capability"]
        for key in ("workspace", "session_id"):
            if spec[key] != cap[key]:
                raise RecoveryLaneError("recovery session/workspace identity differs")
        if spec["intent_id"] != row["intent_id"]:
            raise RecoveryLaneError("recovery intent identity differs")
        if (row["executor_identity"] != ProductionRepairAdapter.identity
                or row["control_identity"] != _plain_digest("recovery-control", Path(__file__).read_text())):
            raise RecoveryLaneError("recovery executor bytes changed since preview")
        target = RepairTarget(self.home, self.runtime, cap["action"], cap["target_identity"])
        current = target.snapshot()
        prepared = self.lane._prepared(cap["capability_id"]) if allow_prepared else None
        # On re-entry, only independent readback may run. Source generation is
        # still checked even when the original target bytes have been repaired.
        self.lane.validate_capability(
            cap, **{k: cap[k] for k in (
                "provider", "session_id", "workspace", "action", "target_identity")},
            installed_generation=current["generation"],
            current_pre_state=cap["expected_pre_state"] if prepared else current,
            require_unused=prepared is None,
        )
        return row, target

    def observe(self, payload, spec, event):
        tool = payload.get("tool_input") or payload.get("toolInput") or {}
        session = str(payload.get("session_id") or payload.get("sessionId") or "")
        if payload.get("client") != "codex" or session != spec["session_id"]:
            raise RecoveryLaneError("native recovery belongs to another provider/session")
        if spec["operation"] != "execute":
            return {"action": "defer", "reason": "authority-free recovery preparation/diagnosis"}
        if event == "PostToolUse":
            row = self._prepared(spec["capability_id"])
            cap = row["capability"]
            if (cap["session_id"] != session or cap["workspace"] != spec["workspace"]
                    or row["intent_id"] != spec["intent_id"]):
                raise RecoveryLaneError("recovery completion identity differs")
            target = RepairTarget(self.home, self.runtime, cap["action"], cap["target_identity"])
            prepared = self.lane._prepared(cap["capability_id"])
            terminal = self.lane._terminal_for(prepared["run_id"]) if prepared else None
            verified = bool(terminal and terminal["status"] == "succeeded"
                            and target.passed(cap["expected_pre_state"]))
            return {"action": "defer", "reason": json.dumps({
                "intent_id": row["intent_id"], "recovery_verified": verified,
                "effect_owner": "independent_recovery_journal",
                "original_task_authority_changed": False,
            }, ensure_ascii=False)}
        row, _ = self.validate(spec, allow_prepared=True)
        expected = self.preview(row)
        if split_command_template(str(tool.get("command") or tool.get("cmd") or "")) != expected["command_argv"]:
            raise RecoveryLaneError("native recovery command differs from preview")
        if event == "PermissionRequest":
            # PreToolUse can carry only execution arguments or a tool summary,
            # not the later native approval card. It must reach that surface
            # without creating authority. Bind the exact text only here;
            # execute() still requires this sealed, live paired prompt.
            description = str(tool.get("description") or tool.get("justification") or "")
            if description != expected["description"]:
                raise RecoveryLaneError("native recovery description differs from current card")
            if (payload.get("permission_mode") or payload.get("permissionMode")) not in {"default", "acceptEdits"}:
                raise RecoveryLaneError("native recovery requires an interactive permission mode")
            prompt = {"capability_id": spec["capability_id"],
                      "session_id": session, "intent_id": row["intent_id"],
                      "description": description, "observed_at": time.time(),
                      "command": str(tool.get("command") or tool.get("cmd") or "")}
            prompt["seal"] = _seal(self.key, prompt)
            self.lane.state.append("production_recovery_prompt", prompt)
        return {"action": "defer", "reason": "current Codex native Allow/Deny owns the decision"}

    def execute(self, spec):
        if os.environ.get("CODEX_THREAD_ID") != spec["session_id"]:
            raise RecoveryLaneError("executor is not in the bound live Codex session")
        row, target = self.validate(spec, allow_prepared=True)
        cap = row["capability"]
        prompts = [p for p in self._rows("production_recovery_prompt")
                   if p["capability_id"] == spec["capability_id"]]
        if not prompts:
            raise RecoveryLaneError("no paired live native PermissionRequest; do not synthesize approval")
        prompt = prompts[-1]
        if prompt["seal"] != _seal(self.key, {k: v for k, v in prompt.items() if k != "seal"}):
            raise RecoveryLaneError("native prompt seal differs")
        command_spec = parse_command(prompt["command"], self.runtime)
        if (command_spec != spec or prompt["description"] != self.preview(row)["description"]
                or prompt["session_id"] != spec["session_id"]
                or not cap["issued_at"] <= prompt["observed_at"] <= time.time() < cap["expires_at"]):
            raise RecoveryLaneError("native prompt binding/expiry differs")
        card = self.lane.recovery_card(cap)
        decisions = self.lane._payloads("human_decision_recorded")
        if not any(d["capability_id"] == cap["capability_id"] for d in decisions):
            # The hook itself never records Allow. This protected process is
            # reached by Codex only after executing the displayed command.
            decision = {"schema": DECISION_SCHEMA, "card_id": card["card_id"],
                        "capability_id": cap["capability_id"], "provider": "codex",
                        "session_id": cap["session_id"], "outcome": "allow",
                        "decided_at": time.time(), "authority": "human",
                        "channel": "native_typed_receipt", "receipt_id": prompt["seal"]}
            self.lane.state.append("human_decision_recorded", decision,
                                   unique_fields=("capability_id",))
        self.lane.trusted_adapter = ProductionRepairAdapter(target)
        self.lane.trusted_verifier = ProductionRepairVerifier(
            RepairTarget(self.home, self.runtime, cap["action"], cap["target_identity"]))
        self.lane.adapter_identity = ProductionRepairAdapter.identity
        self.lane.verifier_identity = ProductionRepairVerifier.identity
        # Publish terminal observations to the independent supervisor journal.
        self.lane.supervisor = self
        result = self.lane.execute(cap, current_pre_state=target.snapshot())
        return {**result, "intent_id": row["intent_id"],
                "recovery_verified": result["status"] == "succeeded" and target.passed(cap["expected_pre_state"]),
                "original_task_authority_changed": False}

    def record_recovery_event(self, event):
        self.lane.state.append("production_recovery_supervisor", event)

    def status(self, spec):
        plans = [row for row in self._rows("production_recovery_prepared")
                 if row["intent_id"] == spec["intent_id"]
                 and row["capability"]["session_id"] == spec["session_id"]
                 and row["capability"]["workspace"] == spec["workspace"]]
        result = {"diagnosis_available": True, "intent_id": spec["intent_id"],
                  "human_confirmation": "unobserved", "repair_execution": "unverified",
                  "recovery_verified": False, "runs": []}
        for row in plans:
            cap = row["capability"]
            # Verify the stored plan seal without renewing expired authority.
            self._prepared(cap["capability_id"])
            run = self.lane._prepared(cap["capability_id"])
            terminal = self.lane._terminal_for(run["run_id"]) if run else None
            decisions = [d for d in self.lane._payloads("human_decision_recorded")
                         if d["capability_id"] == cap["capability_id"]]
            current = False
            if terminal and terminal["status"] == "succeeded":
                try:
                    current = RepairTarget(self.home, self.runtime, cap["action"], cap["target_identity"]).passed(cap["expected_pre_state"])
                except (OSError, RuntimeError, ValueError):
                    pass
            entry = {"action": cap["action"], "target": cap["target_identity"],
                     "generation": cap["installed_generation"],
                     "human_confirmation": "native_decision_recorded" if decisions else "pending",
                     "repair_execution": terminal["status"] if terminal else "not_completed",
                     "recovery_verified": current}
            result["runs"].append(entry)
            result.update({key: entry[key] for key in (
                "human_confirmation", "repair_execution", "recovery_verified")})
        return result


def route_native_recovery(payload, *, runtime, event):
    tool = payload.get("tool_input") or payload.get("toolInput") or {}
    # Unified-exec supplies source text, not native shell arguments. Leave
    # wrappers and malformed inputs to ordinary normalization/enforcement;
    # returning None here is not an authorization or a recovery decision.
    if not isinstance(tool, dict):
        return None
    command = str(tool.get("command") or tool.get("cmd") or "")
    spec = parse_command(command, runtime)
    if spec is None:
        return None
    if str(payload.get("tool_name") or payload.get("toolName") or "").lower() not in {
        "bash", "exec_command", "command_execution", "commandexecution",
    }:
        return {"action": "deny", "reason": "recovery requires the exact native shell tool"}
    control = None
    try:
        control = ProductionRecoveryControl(layout().root, runtime)
        return control.observe(payload, spec, event)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        return {"action": "deny", "reason": str(error)}
    finally:
        if control:
            control.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("operation", choices=("prepare", "execute", "status"))
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--intent-id", required=True)
    parser.add_argument("--action", choices=sorted(SUPPORTED_ACTIONS))
    parser.add_argument("--target")
    parser.add_argument("--capability-id")
    args = parser.parse_args()
    runtime = Path(__file__).resolve().parents[2]
    spec = parse_command(shlex.join([str(runtime / "scripts" / "kb" / CLI_NAME), *sys.argv[1:]]), runtime)
    if spec is None:
        parser.error("exact recovery arguments required")
    control = None
    try:
        control = ProductionRecoveryControl(layout().root, runtime)
        if args.operation == "prepare":
            result = control.prepare(**{k: v for k, v in spec.items() if k != "operation"})
        elif args.operation == "execute":
            result = control.execute(spec)
        else:
            result = control.status(spec)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error), "recovery_verified": False}))
        return 2
    finally:
        if control:
            control.close()
