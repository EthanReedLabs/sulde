"""One-shot r18 environment setup. Not a product installer or root service.

Only --apply creates the exact new standard account. Refuse any existing account
or home; leave partial outcomes for inspection, never delete or reset a user.
Run through a separately approved, digest-bound administrator invocation.
"""
import argparse
import json
import os
from pathlib import Path
import pwd
import secrets
import subprocess

ACCOUNT = "suldeverify"
HOME = Path("/Users/suldeverify")
ENV = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8"}


def execute(argv, *, input_text=None, timeout=30):
    return subprocess.run(argv, input=input_text, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=ENV, timeout=timeout)


def missing_user():
    try:
        pwd.getpwnam(ACCOUNT)
    except KeyError:
        return True
    return False


PROBE = r'''
import json, os, pathlib, subprocess
def run(args):
    p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=15)
    return {"exit_code": p.returncode, "stdout": p.stdout.strip()}
manager = run(["/bin/launchctl", "manageruid"])
inventory = run(["/bin/ps", "-ww", "-U", str(os.getuid()), "-o", "pid=,ppid=,lstart=,comm="])
rows = []
for line in inventory["stdout"].splitlines():
    fields = line.split(None, 7)
    if len(fields) != 8:
        raise ValueError("invalid process inventory")
    if "codex" in pathlib.Path(fields[7]).name.lower():
        rows.append({"pid": int(fields[0]), "started": " ".join(fields[2:7])})
result = {"uid": os.getuid(), "euid": os.geteuid(), "gid": os.getgid(),
          "groups": os.getgroups(), "home": str(pathlib.Path.home()),
          "manager": manager, "inventory_exit": inventory["exit_code"],
          "codex_cohort": rows, "python": run(["/usr/bin/python3", "--version"]),
          "git": run(["/usr/bin/git", "--version"])}
print(json.dumps(result, sort_keys=True))
'''


def main(apply, resume_created):
    if not resume_created and (not missing_user() or HOME.exists() or HOME.is_symlink()):
        raise RuntimeError("exact account or home already exists; refuse reuse/reset")
    if HOME.parent.resolve() != HOME.parent:
        raise RuntimeError("home parent is aliased")
    plan = {"account": ACCOUNT, "home": str(HOME), "admin": False,
            "password_transport": "memory-only stdin, never argv or report",
            "scope": "create-account-and-probe-user-bootstrap-only",
            "production_install": False, "stop_existing_hosts": False}
    if not apply:
        print(json.dumps({"status": "plan-only", **plan}, sort_keys=True))
        return 0
    if os.getuid() != 0 or os.geteuid() != 0:
        raise RuntimeError("requires separately approved administrator execution")
    old_uids = {entry.pw_uid for entry in pwd.getpwall()}
    os.umask(0o077)
    result = {**plan, "status": "incomplete"}
    if resume_created:
        identity = execute(["/usr/bin/dscl", ".", "-read", "/Users/" + ACCOUNT, "GeneratedUID"])
        if (identity.returncode or identity.stdout.strip() !=
                "GeneratedUID: 025B11A2-1162-4B20-AA0D-B025D2CC32F9"
                or pwd.getpwnam(ACCOUNT).pw_uid != 502 or HOME.exists() or HOME.is_symlink()):
            raise RuntimeError("partial account identity changed; refuse recovery")
        result["create_exit"] = None
        result["recovery"] = "complete-exact-r18-created-account-home-only"
    else:
        password = secrets.token_urlsafe(48)
        created = execute(["/usr/sbin/sysadminctl", "-addUser", ACCOUNT,
                           "-fullName", "Sulde isolated verification", "-home", str(HOME),
                           "-shell", "/bin/zsh", "-password", "-"],
                          input_text=password + "\n" + password + "\n", timeout=60)
        del password
        # Do not persist sysadminctl output: authentication prompts are not evidence.
        result["create_exit"] = created.returncode
    entry = pwd.getpwnam(ACCOUNT)
    if (entry.pw_uid <= 501 or (not resume_created and entry.pw_uid in old_uids)
            or entry.pw_dir != str(HOME) or entry.pw_shell != "/bin/zsh"):
        raise RuntimeError("new account identity differs; preserve for inspection")
    disabled = execute(["/usr/bin/pwpolicy", "-u", ACCOUNT, "-disableuser"])
    # Modern macOS reports disabled-account policy through pwpolicy, not
    # necessarily a legacy ;DisabledUser; AuthenticationAuthority marker.
    allowed = execute(["/usr/bin/pwpolicy", "-u", ACCOUNT, "-authentication-allowed"])
    policy_text = allowed.stdout + allowed.stderr
    if (disabled.returncode or "not allowed to authenticate" not in policy_text
            or "account is disabled" not in policy_text):
        raise RuntimeError("test account login disable not verified; do not run tools")
    result["interactive_login_disabled"] = True
    if not HOME.exists() and not HOME.is_symlink():
        HOME.mkdir(mode=0o700)
        os.chown(HOME, entry.pw_uid, entry.pw_gid)
    if not HOME.is_dir() or HOME.is_symlink() or HOME.stat().st_uid != entry.pw_uid:
        raise RuntimeError("new home identity differs; preserve for inspection")
    groups = os.getgrouplist(ACCOUNT, entry.pw_gid)
    if 80 in groups or entry.pw_uid == 0:
        raise RuntimeError("new account is privileged; stop before running tools")
    HOME.chmod(0o700)
    result.update(uid=entry.pw_uid, groups=groups, home_mode=oct(HOME.stat().st_mode & 0o777))
    domain = "user/" + str(entry.pw_uid)
    check = execute(["/bin/launchctl", "print", domain])
    if check.returncode:
        bootstrap = execute(["/bin/launchctl", "bootstrap", domain])
        result["bootstrap_exit"] = bootstrap.returncode
    check = execute(["/bin/launchctl", "print", domain])
    result["user_domain_exit"] = check.returncode
    if check.returncode == 0:
        # Login is disabled; this is an exact administrator-owned test process,
        # not an interactive account authentication or a general command broker.
        child_env = {**ENV, "HOME": str(HOME), "USER": ACCOUNT, "LOGNAME": ACCOUNT,
                     "PYTHONDONTWRITEBYTECODE": "1"}
        drop = ("import os; " + f"os.initgroups({ACCOUNT!r},{entry.pw_gid}); "
                + f"os.setgid({entry.pw_gid}); os.setuid({entry.pw_uid}); "
                + f"os.execve('/usr/bin/python3', ['/usr/bin/python3','-B','-I','-c',{PROBE!r}],{child_env!r})")
        child = execute(["/bin/launchctl", "asuser", str(entry.pw_uid),
                         "/usr/bin/python3", "-B", "-I", "-c", drop], timeout=45)
        result["probe_exit"] = child.returncode
        if child.returncode == 0:
            probe = json.loads(child.stdout)
            result["probe"] = probe
            expected = str(entry.pw_uid)
            if (probe["uid"] == probe["euid"] == entry.pw_uid
                    and probe["home"] == str(HOME) and 80 not in probe["groups"]
                    and probe["manager"] == {"exit_code": 0, "stdout": expected}
                    and probe["inventory_exit"] == 0 and not probe["codex_cohort"]
                    and probe["git"]["exit_code"] == probe["python"]["exit_code"] == 0):
                result["status"] = "user-process-and-bootstrap-isolation-verified"
    evidence = HOME / "s3c-environment-result.json"
    with evidence.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())
    # Root-owned record: the test user cannot turn its own observation into proof.
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "user-process-and-bootstrap-isolation-verified" else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--resume-created", action="store_true",
                        help="Only finish UID 502 / bound GeneratedUID from r18 partial creation")
    args = parser.parse_args()
    raise SystemExit(main(args.apply, args.resume_created))
