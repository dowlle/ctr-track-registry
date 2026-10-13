#!/usr/bin/env python3
"""Standalone checker for a CTR track registry directory (standard library only).

    python tools/check_registry.py [REGISTRY_DIR] [--previous OLDER_DIR]

Exit status 0 when every check passes, 1 otherwise. This is the file the
registry repository's CI runs. It is copied from AP-Pie's export, so it holds
its own copies of the id constants (a test in AP-Pie keeps them in step).

Checks: file set and digest, mint_status (mint, reserved, builtin), schema version, unique keys and block indexes,
id ranges, name rules, named_tracks.json agreement, no private fields, and with
--previous the freeze rules: no track, block, shipped name or verified hash
that was in the older set may change or disappear.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

SCHEMA_VERSION = 1
MAX_BLOCKS = 10_000
LOCATION_BASE, LOCATIONS_PER_TRACK = 35_200_000, 200
ITEM_BASE, ITEMS_PER_TRACK = 35_100_000, 5
NAME_MAX_BYTES = 105
MINT_STATUSES = {"mint", "reserved", "builtin"}
STATES = {"approved", "named", "withdrawn", "source-unavailable"}
PRIVATE_KEYS = {"submitter", "submitter_user_id", "discord_id", "discord_username", "email",
                "reviewed_by", "decided_by", "user_id"}
KEY_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _walk_private(value, where: str, errors: list) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            if k in PRIVATE_KEYS:
                errors.append(f"{where}: private field {k!r}")
            _walk_private(v, where, errors)
    elif isinstance(value, list):
        for v in value:
            _walk_private(v, where, errors)


def digest_of(root: Path) -> str:
    paths = ["registry.json"] + sorted(f"tracks/{p.name}" for p in (root / "tracks").glob("*.json"))
    h = hashlib.sha256()
    for rel in sorted(paths):
        h.update(rel.encode() + b"\0" + hashlib.sha256((root / rel).read_bytes()).hexdigest().encode() + b"\n")
    return h.hexdigest()


def check(root: Path, previous: Path | None = None) -> list[str]:
    errors: list[str] = []
    for rel in ("registry.json", "named_tracks.json", "DIGEST.json"):
        if not (root / rel).is_file():
            return [f"missing {rel}"]
    registry, named, digest_doc = (_load(root / n) for n in ("registry.json", "named_tracks.json", "DIGEST.json"))
    if registry.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"registry.json: schema_version must be {SCHEMA_VERSION}")
    if digest_of(root) != digest_doc.get("digest"):
        errors.append("DIGEST.json does not match registry.json and tracks/")
    if named.get("registry", {}).get("digest") != digest_doc.get("digest"):
        errors.append("named_tracks.json carries a different digest than DIGEST.json")

    tracks = registry.get("tracks", [])
    keys, blocks, names = {}, {}, {}
    for t in tracks:
        key = t.get("track_key")
        if not isinstance(key, str) or not KEY_RE.match(key):
            errors.append(f"bad track_key {key!r}")
            continue
        if key in keys:
            errors.append(f"duplicate track_key {key}")
        keys[key] = t
        if t.get("state") not in STATES:
            errors.append(f"{key}: bad state {t.get('state')!r}")
        if not t.get("display_title"):
            errors.append(f"{key}: missing display_title")
        _walk_private(t, key, errors)
        if not (root / "tracks" / f"{key}.json").is_file():
            errors.append(f"{key}: tracks/{key}.json is missing")
        bi = t.get("block_index")
        if bi is not None:
            if type(bi) is not int or not 0 <= bi < MAX_BLOCKS:
                errors.append(f"{key}: block_index {bi!r} out of range")
            elif bi in blocks:
                errors.append(f"{key}: block_index {bi} also used by {blocks[bi]}")
            else:
                blocks[bi] = key
            name = t.get("ap_name")
            if not isinstance(name, str) or not name.strip():
                errors.append(f"{key}: a block needs an ap_name")
            else:
                if len(name.encode("utf-8")) > NAME_MAX_BYTES or any(c in name for c in "[]{}") \
                        or any(ord(c) < 32 for c in name):
                    errors.append(f"{key}: ap_name {name!r} breaks the name rules")
                if name.casefold() in names:
                    errors.append(f"{key}: ap_name {name!r} also used by {names[name.casefold()]}")
                names[name.casefold()] = key
            ms = t.get("mint_status", "mint")
            if ms not in MINT_STATUSES:
                errors.append(f"{key}: bad mint_status {ms!r}")
            elif ms == "builtin" and not t.get("maps_to"):
                errors.append(f"{key}: a builtin entry needs maps_to")
            elif ms == "mint" and t.get("maps_to"):
                errors.append(f"{key}: maps_to is only for builtin or reserved entries")
            elif ms != "mint" and t.get("shipped_in"):
                errors.append(f"{key}: {ms} entries cannot be shipped")
        elif t.get("state") == "named":
            errors.append(f"{key}: state named without a block_index")
        if t.get("shipped_in") and bi is None:
            errors.append(f"{key}: shipped_in without a block_index")
        seen_ids = set()
        for r in t.get("revisions", []):
            cid = r.get("content_id")
            if cid is not None:
                if not HEX64.match(cid):
                    errors.append(f"{key}: bad content_id {cid!r}")
                elif cid in seen_ids:
                    errors.append(f"{key}: duplicate content_id {cid}")
                seen_ids.add(cid)
    for p in (root / "tracks").glob("*.json"):
        if p.stem not in keys:
            errors.append(f"tracks/{p.name} is not listed in registry.json")

    expected = [
        {"track_key": t["track_key"], "block_index": t["block_index"], "ap_name": t["ap_name"],
         "shipped_in": t["shipped_in"],
         "revisions": [r["content_id"] for r in t["revisions"] if r.get("content_id")]}
        for t in tracks if t.get("block_index") is not None and t.get("track_key")
        and t.get("mint_status", "mint") == "mint"
    ]
    if named.get("format") != 1 or named.get("tracks") != expected:
        errors.append("named_tracks.json does not match registry.json")

    if previous is not None:
        errors += freeze_errors(previous, keys)
    return errors


def freeze_errors(previous: Path, current_by_key: dict) -> list[str]:
    errors = []
    if not (previous / "registry.json").is_file():
        return [f"--previous {previous}: no registry.json"]
    old = _load(previous / "registry.json")
    for t in old.get("tracks", []):
        key = t["track_key"]
        now = current_by_key.get(key)
        if now is None:
            errors.append(f"frozen: {key} disappeared")
            continue
        if t.get("block_index") is not None and now.get("block_index") != t["block_index"]:
            errors.append(f"frozen: {key} block_index changed")
        if t.get("mint_status") == "builtin" and (now.get("mint_status") != "builtin"
                                                   or now.get("maps_to") != t.get("maps_to")):
            errors.append(f"frozen: {key} builtin mapping changed")
        if t.get("shipped_in"):
            if now.get("mint_status", "mint") != t.get("mint_status", "mint"):
                errors.append(f"frozen: {key} mint_status changed after shipping")
            if now.get("shipped_in") != t["shipped_in"]:
                errors.append(f"frozen: {key} shipped_in changed")
            if now.get("ap_name") != t.get("ap_name"):
                errors.append(f"frozen: {key} shipped ap_name changed")
        now_revs = {r.get("revision"): r for r in now.get("revisions", [])}
        for r in t.get("revisions", []):
            if r.get("hash_state") != "verified":
                continue
            cur = now_revs.get(r["revision"])
            if cur is None or cur.get("content_id") != r.get("content_id") or cur.get("files") != r.get("files"):
                errors.append(f"frozen: {key} verified revision {r['revision']} changed")
    return errors


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    previous = None
    if "--previous" in argv:
        i = argv.index("--previous")
        previous = Path(argv[i + 1])
        args = [a for a in args if a != argv[i + 1]]
    root = Path(args[0]) if args else Path(".")
    errors = check(root, previous)
    for e in errors:
        print("FAIL", e)
    print("registry check:", "FAILED" if errors else "ok", f"({len(errors)} problems)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
