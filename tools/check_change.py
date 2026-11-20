"""Validate a registry change using a base checker and Git data-only snapshots."""

import argparse
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory


DATA = {"registry.json", "named_tracks.json", "DIGEST.json", "consent.json", "origins.json"}
DOCS = {"README.md", "CONTRIBUTING.md", "LICENSE", ".gitignore"}
POLICY = {
    ".github/CODEOWNERS",
    ".github/workflows/check.yml",
    ".github/workflows/registry-policy.yml",
    "tools/check_change.py",
    "tools/check_registry.py",
    "tools/test_check_registry.py",
}
TRACK = re.compile(r"tracks/[a-z0-9]+(?:-[a-z0-9]+)*\.json")
SHA = re.compile(r"[0-9a-f]{40}")
MAX_BYTES = 1024 * 1024


def git(*args):
    return subprocess.check_output(["git", *args])


def is_data(path):
    return path in DATA or TRACK.fullmatch(path) is not None


def verify_change(base, candidate):
    changed = set(git("diff", "--name-only", "--no-renames", "-z", base, candidate).decode().split("\0"))
    changed.discard("")
    if changed & POLICY and any(map(is_data, changed)):
        raise ValueError("submit policy and registry data changes in separate pull requests")
    for path in sorted(changed):
        if not (is_data(path) or path in DOCS or path in POLICY):
            raise ValueError(f"unexpected path: {path!r}")


def snapshot(commit, destination, *, include_checker=False):
    tree = git("ls-tree", "-rlz", commit)
    for line in tree.split(b"\0")[:-1]:
        metadata, path = line.decode().split("\t", 1)
        mode, kind, oid, size = metadata.split()
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError(f"expected a regular file: {path!r}")
        if int(size) > MAX_BYTES:
            raise ValueError(f"file over 1 MiB: {path!r}")
        if not (is_data(path) or (include_checker and path == "tools/check_registry.py")):
            continue
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git("cat-file", "blob", oid))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base")
    parser.add_argument("candidate")
    parser.add_argument("--pull-head", help="Verify that the candidate is this pull request's merge commit")
    args = parser.parse_args()
    if not all(SHA.fullmatch(sha) for sha in (args.base, args.candidate, args.pull_head or args.base)):
        parser.error("expected full Git commit IDs")
    try:
        if args.pull_head:
            parents = git("show", "-s", "--format=%P", args.candidate).decode().split()
            if parents != [args.base, args.pull_head]:
                raise ValueError("merge commit does not match the event's base and head")
        verify_change(args.base, args.candidate)
        with TemporaryDirectory() as temp:
            previous, current = Path(temp) / "previous", Path(temp) / "current"
            snapshot(args.base, previous, include_checker=True)
            snapshot(args.candidate, current)
            checker = previous / "tools" / "check_registry.py"
            return subprocess.run([sys.executable, "-I", str(checker), str(current),
                                   "--previous", str(previous)], cwd=temp, check=False).returncode
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"Registry policy failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
