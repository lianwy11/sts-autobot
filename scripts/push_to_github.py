#!/usr/bin/env python3
"""Push this repository to GitHub through the REST API.

Why: on some networks `git push` to github.com:443 is blocked while
api.github.com still works. This script uploads the working tree straight
through the Git Data API instead.

Requirements:
    GITHUB_TOKEN  – fine-grained PAT with "Contents: Read and write" on the
                    target repository (classic PAT: `repo` scope).

Usage:
    python scripts/push_to_github.py --owner <your-username> --repo sts-autobot
    python scripts/push_to_github.py --owner me --repo sts-autobot --branch main --message "update docs"
"""

import argparse
import base64
import fnmatch
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"
SKIP_DIRS = {".git", "out", "__pycache__", ".idea", ".vscode"}
SKIP_FILES = ("last_state.json", "manual_cmd.txt", "mode.txt", "game_out.log", "game_err.log")


def call(token, method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "sts-autobot-pusher",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
            return r.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400]


def collect_files(root):
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            rel = Path(dirpath, name).relative_to(root).as_posix()
            if fnmatch.fnmatch(name, "*.log") or name in SKIP_FILES:
                continue
            files.append(rel)
    return sorted(files)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--branch", default="main")
    ap.add_argument("--message", default="更新：通过 API 推送")
    ap.add_argument("--root", default=Path(__file__).resolve().parent.parent,
                    type=Path, help="repository root (defaults to the project root)")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is not set.", file=sys.stderr)
        return 1

    root = args.root
    files = collect_files(root)
    print("files: %d" % len(files))

    tree = []
    for rel in files:
        data = base64.b64encode((root / rel).read_bytes()).decode()
        st, blob = call(token, "POST", f"/repos/{args.owner}/{args.repo}/git/blobs",
                        {"content": data, "encoding": "base64"})
        if st not in (200, 201):
            print("blob failed for %s: %s %s" % (rel, st, blob))
            return 1
        tree.append({"path": rel, "mode": "100755" if rel.endswith(".ps1") else "100644",
                     "type": "blob", "sha": blob["sha"]})
    print("blobs uploaded: %d" % len(tree))

    st, tree_res = call(token, "POST", f"/repos/{args.owner}/{args.repo}/git/trees",
                        {"tree": tree})
    if st not in (200, 201):
        print("tree failed: %s %s" % (st, tree_res))
        return 1

    parents = []
    st, ref = call(token, "GET", f"/repos/{args.owner}/{args.repo}/git/ref/heads/{args.branch}")
    if st == 200:
        parents = [ref["object"]["sha"]]
        print("updating existing branch %s (parent %s)" % (args.branch, parents[0][:8]))

    st, commit = call(token, "POST", f"/repos/{args.owner}/{args.repo}/git/commits",
                      {"message": args.message, "tree": tree_res["sha"], "parents": parents})
    if st not in (200, 201):
        print("commit failed: %s %s" % (st, commit))
        return 1
    print("commit: %s" % commit["sha"][:8])

    if parents:
        st, res = call(token, "PATCH", f"/repos/{args.owner}/{args.repo}/git/refs/heads/{args.branch}",
                       {"sha": commit["sha"], "force": False})
    else:
        st, res = call(token, "POST", f"/repos/{args.owner}/{args.repo}/git/refs",
                       {"ref": f"refs/heads/{args.branch}", "sha": commit["sha"]})
    if st not in (200, 201):
        print("ref update failed: %s %s" % (st, res))
        return 1

    print("pushed: https://github.com/%s/%s" % (args.owner, args.repo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
