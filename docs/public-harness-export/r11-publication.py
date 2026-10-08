"""Frozen R11 publication staging/readback only. No network or push executor."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / ".sulde/public-export"
PUBLIC = ROOT.parents[2] / "sulde-cc"
SLOT = BASE / "publication-002"
PARENT = "9cefc8a3875dafa49de9d95db68e69a74bc56da5"
MANIFEST = "f5c23776dff872ab4af6a396e0f68cff4bf412511774cfb34a38581249618d95"
REMOTE = "https://github.com/EthanReedLabs/sulde-cc.git"
sys.path.insert(0, str(ROOT / "scripts/release"))
from export_public_harness import digest, git, read_blobs, safe_path, snapshot, verify_tree


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def check_entries(repo, entries, expected):
    require(entries.keys() == expected.keys(), "Git inventory differs from frozen manifest")
    for path, raw in read_blobs(repo, entries).items():
        require(digest(raw) == expected[path]["sha256"] and
                entries[path]["mode"] == expected[path]["mode"], "Git blob/mode mismatch: " + path)


def check_files(repo, expected):
    for relative, row in expected.items():
        path = repo / relative
        require(not path.is_symlink() and path.is_file(), "nonregular worktree file: " + relative)
        require(not any(p.is_symlink() for p in path.parents), "aliased worktree parent")
        require(digest(path.read_bytes()) == row["sha256"], "worktree bytes mismatch: " + relative)
        require(("100755" if path.stat().st_mode & 0o111 else "100644") == row["mode"],
                "worktree mode mismatch: " + relative)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "verify"))
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--revision")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repository.absolute()
    require(repo in (SLOT, PUBLIC) and repo.resolve() == repo, "unapproved publication checkout")
    require(args.report.absolute().parent == BASE and not args.report.exists(), "use a fresh private report")
    require(git(repo, "remote", "get-url", "origin").decode().strip() == REMOTE, "remote mismatch")
    require(not git(repo, "status", "--porcelain", "--untracked-files=all"), "worktree is dirty")
    plan = json.loads((BASE / "review-013/review.json").read_bytes())
    require(plan["manifest_sha256"] == MANIFEST, "manifest changed")
    verify_tree(BASE / "review-013/tree", plan)
    expected = {row["path"]: row for row in plan["files"]}
    require(len(expected) == 628, "unexpected inventory size")
    if args.mode == "prepare":
        require(repo == SLOT and git(repo, "rev-parse", "HEAD").decode().strip() == PARENT,
                "publication must start from frozen public parent")
        old_plan = json.loads((BASE / "review-011/review.json").read_bytes())
        old = {row["path"]: row for row in old_plan["files"]}
        check_entries(repo, snapshot(repo, PARENT), old)
        check_files(repo, old)
        require(old.keys() == expected.keys(), "file additions/deletions are not approved")
        changed = sorted(p for p in expected if old[p]["sha256"] != expected[p]["sha256"]
                         or old[p]["mode"] != expected[p]["mode"])
        require(len(changed) == 9, "unexpected delta")
        require(git(repo, "branch", "--show-current").decode().strip() == "task/public-harness-r11",
                "publication task branch required")
        for relative in changed:
            target = repo / relative
            target.write_bytes((BASE / "review-013/tree" / relative).read_bytes())
            target.chmod(0o755 if expected[relative]["mode"] == "100755" else 0o644)
        check_files(repo, expected)
        git(repo, "add", "--", *changed)
        entries = {}
        for record in git(repo, "ls-files", "--stage", "-z").split(b"\0"):
            if not record:
                continue
            metadata, path = record.split(b"\t", 1)
            mode, oid, stage = metadata.decode().split()
            require(stage == "0", "unmerged index")
            entries[safe_path(path.decode())] = {"kind": "blob", "mode": mode, "oid": oid}
        check_entries(repo, entries, expected)
        result = {"status": "prepared-not-published", "changed": changed,
                  "tree": git(repo, "write-tree").decode().strip()}
    else:
        require(bool(args.revision), "exact commit required")
        check_entries(repo, snapshot(repo, args.revision), expected)
        lineage = git(repo, "rev-list", "--parents", "-n", "1", args.revision).decode().split()
        require(lineage == [args.revision, PARENT], "unexpected public history")
        local_head = git(repo, "rev-parse", "HEAD").decode().strip()
        if local_head == args.revision:
            check_files(repo, expected)
        else:
            require(repo == PUBLIC and local_head == PARENT, "local public HEAD drifted")
            old = json.loads((BASE / "review-011/review.json").read_bytes())
            check_files(repo, {row["path"]: row for row in old["files"]})
        result = {"status": "commit-verified", "commit": args.revision, "parent": PARENT,
                  "tree": git(repo, "rev-parse", args.revision + "^{tree}").decode().strip(),
                  "local_head": local_head, "worktree_clean": True}
    result.update(manifest_sha256=MANIFEST, files_verified=628,
                  repository=REMOTE, installation_performed=False, private_history_imported=False)
    with args.report.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
