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

consent.json, required (track author permission, read live by the
CTR Archipelago client): format 1, known keys only, one record per Saphi
author id and per name, one per track key, a track key that registry.json
lists, the status vocabulary (granted, declined, withdrawn), an author grant
scoped to all_saphi_tracks, a date, evidence that is a public link or the
fixed private-receipt wording, and no private fields. consent.json is not in
the digest and has no freeze rules: answers change, identity does not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

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
ORIGIN_CODE_RE = re.compile(r"[A-Z0-9]{3}")
CONTROL_CHAR = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
DNS_NAME = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")
CONSENT_FORMAT = 1
CONSENT_STATUSES = {"granted", "declined", "withdrawn"}
CONSENT_SCOPES = {"all_saphi_tracks"}
CONSENT_PRIVATE_EVIDENCE = "private receipt held by the maintainer"
CONSENT_PRIVATE_KEYS = PRIVATE_KEYS | {"handle", "discord", "dm", "message", "messages", "contact"}
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
AUTHOR_ID_MAX = 100_000_000
NAME_MAX = 80
TEXT_MAX_BYTES = 4096
MISSING = object()


def typed(value, kind, where, errors, *, default=MISSING, nullable=False):
    if value is MISSING:
        if default is not MISSING:
            return default
        errors.append(f"{where}: missing")
    elif value is None and nullable:
        return None
    elif type(value) is kind:  # bool is a subclass of int
        return value
    else:
        errors.append(f"{where}: expected {kind.__name__}, got {type(value).__name__}")
    return kind() if kind in (dict, list) else None


def text_value(value, where, errors, *, limit=TEXT_MAX_BYTES, pattern=None, **options):
    value = typed(value, str, where, errors, **options)
    if value is None:
        return None
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        size = 0
    if not 0 < size <= limit or value != value.strip() or CONTROL_CHAR.search(value):
        errors.append(f"{where}: expected 1 to {limit} UTF-8 bytes without controls or surrounding whitespace")
        return None
    if pattern is not None and not pattern.fullmatch(value):
        errors.append(f"{where}: invalid format")
        return None
    return value


class Record:
    def __init__(self, value, where, errors):
        self.where = where
        self.errors = errors
        self.data = typed(value, dict, where, errors)

    def read(self, key, kind, **options):
        return typed(self.data.get(key, MISSING), kind, f"{self.where}.{key}", self.errors, **options)

    def text(self, key, **options):
        return text_value(self.data.get(key, MISSING), f"{self.where}.{key}", self.errors, **options)

    def choices(self, key, choices, **options):
        value = self.text(key, **options)
        if value is not None and value not in choices:
            self.error(f"{key} must be one of {sorted(choices)}")
            return None
        return value

    def day(self, key):
        value = self.text(key, pattern=DATE_RE)
        if value is not None:
            try:
                return date.fromisoformat(value)
            except ValueError:
                self.error(f"{key} must be a valid calendar date")
        return None

    def object(self, key):
        return self.child(key, self.data.get(key, MISSING))

    def child(self, key, value):
        where = f"{self.where}.{key}"
        if type(value) is dict:
            return Record(value, where, self.errors)
        typed(value, dict, where, self.errors)
        return None

    def rows(self, key, **options):
        for index, value in enumerate(self.read(key, list, **options)):
            row = self.child(f"{key}[{index}]", value)
            if row is not None:
                yield row

    def text_list(self, key, **options):
        return tuple(
            text_value(value, f"{self.where}.{key}[{index}]", self.errors, **options)
            for index, value in enumerate(self.read(key, list))
        )

    def exact(self, allowed):
        extra = self.data.keys() - allowed
        if extra:
            self.error(f"unknown keys {sorted(extra)!r}")

    def error(self, message):
        self.errors.append(f"{self.where}: {message}")


def reject_constant(value):
    raise ValueError(f"{value} is not a JSON constant")


def load_record(root, rel, errors, *, label=None, private_keys=PRIVATE_KEYS):
    where = label or rel

    def unique_object(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                errors.append(f"{where}: duplicate JSON field {key!r}")
            obj[key] = value
        return obj

    try:
        value = json.loads((root / rel).read_text(encoding="utf-8"),
                           parse_constant=reject_constant, object_pairs_hook=unique_object)
    except (OSError, ValueError, RecursionError) as exc:
        errors.append(f"{where}: cannot read JSON ({exc})")
        return Record({}, where, errors)
    # Bound nesting before any structural comparisons and check privacy even in
    # metadata whose schema is owned by the exporter.
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > 128:
            errors.append(f"{where}: JSON nesting exceeds 128 levels")
            return Record({}, where, errors)
        if isinstance(item, dict):
            for key, child in item.items():
                if key in private_keys:
                    errors.append(f"{where}: private field {key!r}")
                stack.append((child, depth + 1))
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    return Record(value, where, errors)


def digest_of(root: Path) -> str:
    paths = ["registry.json"] + sorted(f"tracks/{p.name}" for p in (root / "tracks").glob("*.json"))
    h = hashlib.sha256()
    for rel in sorted(paths):
        h.update(rel.encode() + b"\0" + hashlib.sha256((root / rel).read_bytes()).hexdigest().encode() + b"\n")
    return h.hexdigest()


@dataclass
class Revision:
    revision: str | None
    hash_state: str | None
    content_id: str | None
    files: dict
    lev_hash: str | None
    modes: tuple

    @classmethod
    def read(cls, row):
        revision = row.text("revision")
        state = row.text("hash_state")
        content = row.text("content_id", pattern=HEX64, nullable=True)
        files = row.object("files")
        lev_hash = None
        has_hash = False
        if files is not None:
            for name, value in files.data.items():
                text_value(name, files.where, row.errors)
                item = files.child(name, value)
                if item is not None:
                    sha = item.text("sha256", pattern=HEX64)
                    has_hash = has_hash or sha is not None
                    item.read("size", int, default=None)
                    if name == "lev":
                        lev_hash = sha
        if state == "verified" and (content is None or not has_hash):
            row.error("verified revisions need a content_id and file hashes")
        return cls(revision, state, content, files.data if files is not None else {},
                   lev_hash, row.text_list("modes"))


@dataclass
class Track:
    key: str | None
    block: int | None
    name: str | None
    mint: str | None
    mapping: str | None
    shipped: str | None
    revisions: list[Revision]

    @classmethod
    def read(cls, row):
        key = row.text("track_key", pattern=KEY_RE, limit=250)
        state = row.choices("state", STATES)
        row.text("display_title")
        block = row.read("block_index", int, nullable=True, default=None)
        name = row.text("ap_name", limit=NAME_MAX_BYTES, nullable=True, default=None)
        mint = row.choices("mint_status", MINT_STATUSES, default="mint")
        mapping = row.text("maps_to", nullable=True, default=None)
        shipped = row.text("shipped_in", nullable=True,
                           default=MISSING if block is not None and mint == "mint" else None)
        revisions = [Revision.read(rev) for rev in row.rows("revisions")]
        if block is None:
            if state == "named":
                row.error("state named without a block_index")
            if shipped is not None:
                row.error("shipped_in without a block_index")
        else:
            if not 0 <= block < MAX_BLOCKS:
                row.error(f"block_index {block} out of range")
            if name is None:
                row.error("a block needs an ap_name")
            elif any(c in name for c in "[]{}"):
                row.error("ap_name breaks the name rules")
            if mint == "builtin" and mapping is None:
                row.error("a builtin entry needs maps_to")
            if mint == "mint" and mapping is not None:
                row.error("maps_to is only for builtin or reserved entries")
            if mint in ("builtin", "reserved") and shipped is not None:
                row.error(f"{mint} entries cannot be shipped")
        seen = set()
        for rev in revisions:
            if rev.content_id is not None:
                if rev.content_id in seen:
                    row.error(f"duplicate content_id {rev.content_id}")
                seen.add(rev.content_id)
        return cls(key, block, name, mint, mapping, shipped, revisions)

    def named_row(self):
        return {"track_key": self.key, "block_index": self.block, "ap_name": self.name,
                "shipped_in": self.shipped,
                "revisions": [rev.content_id for rev in self.revisions if rev.content_id is not None]}

    def verified_ctr_revisions(self):
        return {
            (rev.revision, rev.lev_hash, rev.modes) for rev in self.revisions
            if rev.hash_state == "verified" and rev.revision is not None and rev.lev_hash is not None
            and "ctr_challenge" in rev.modes and None not in rev.modes
        }


def registry_tracks(root, errors):
    doc = load_record(root, "registry.json", errors)
    if doc.read("schema_version", int) != SCHEMA_VERSION:
        doc.error(f"schema_version must be {SCHEMA_VERSION}")
    tracks, blocks, names = {}, {}, {}
    for row in doc.rows("tracks"):
        track = Track.read(row)
        if track.key is not None:
            if track.key in tracks:
                row.error(f"duplicate track_key {track.key}")
            tracks[track.key] = track
        if track.block is not None:
            if track.block in blocks:
                row.error(f"block_index {track.block} also used by {blocks[track.block]}")
            blocks[track.block] = row.where
            if track.name is not None:
                folded = track.name.casefold()
                if folded in names:
                    row.error(f"ap_name {track.name!r} also used by {names[folded]}")
                names[folded] = row.where
    return tracks


def per_track_records(root, registry, errors):
    paths = {path.stem: f"tracks/{path.name}" for path in (root / "tracks").glob("*.json")}
    for key in registry.keys() - paths.keys():
        errors.append(f"{key}: tracks/{key}.json is missing")
    records = {}
    for key, path in paths.items():
        row = load_record(root, path, errors)
        track = Track.read(row)
        if track.key != key:
            row.error("track_key must agree with the file name")
        elif key not in registry:
            row.error("track is not listed in registry.json")
        else:
            if verified_hashes(track) != verified_hashes(registry[key]):
                row.error("verified revisions must agree with registry.json")
            records[key] = track
    return records


def verified_hashes(track):
    return {rev.content_id: (rev.revision, rev.files) for rev in track.revisions
            if rev.hash_state == "verified"}


def check_identity(root, registry, errors):
    doc = load_record(root, "registry.json", errors)
    pins = {rev.lev_hash for track in registry.values() for rev in track.revisions}
    aliases = {}
    for field, pattern in (("track_key_aliases", KEY_RE), ("road_sha256", HEX64), ("patch_lev_keys", HEX64)):
        mapping = doc.read(field, dict, default={})
        if field == "track_key_aliases":
            aliases = mapping or {}
        for key, target in (mapping or {}).items():
            if len(key) > 64 or not pattern.fullmatch(key):
                doc.error(f"{field}: invalid key {key!r}")
            if type(target) is not str or target not in registry:
                doc.error(f"{field}: {key} must refer directly to a registered track")
            if field == "track_key_aliases" and key in registry:
                doc.error(f"{field}: {key} shadows a registered track")
            if field == "patch_lev_keys" and key in pins:
                doc.error(f"{field}: {key} is already a registry revision pin")
    return aliases


def check_named(root, registry, digest, aliases, errors):
    doc = load_record(root, "named_tracks.json", errors)
    if doc.read("format", int) != 1:
        doc.error("format must be 1")
    source = doc.object("registry")
    if source is not None and source.text("digest", pattern=HEX64) != digest:
        doc.error("carries a different digest than DIGEST.json")
    for row in doc.rows("tracks"):
        row.text("track_key", pattern=KEY_RE, limit=250)
        row.read("block_index", int)
        row.text("ap_name", limit=NAME_MAX_BYTES)
        row.text("shipped_in", nullable=True)
        row.text_list("revisions", pattern=HEX64)
    expected = [track.named_row() for track in registry.values()
                if track.block is not None and track.mint == "mint"]
    if doc.read("tracks", list) != expected:
        doc.error("tracks do not match registry.json")
    keys = {row["track_key"] for row in expected}
    if doc.read("track_key_aliases", dict, default={}) != {
            key: target for key, target in aliases.items() if isinstance(target, str) and target in keys}:
        doc.error("track_key_aliases do not match the mint entries in registry.json")


def origin_code(value, where, errors):
    code = text_value(value, where, errors, limit=3, pattern=ORIGIN_CODE_RE)
    if code is not None and len(set(code)) != 3:
        errors.append(f"{where}: code must have three distinct characters")
        return None
    return code


def public_origin_url(source):
    if any(c.isspace() for c in source):
        return False
    try:
        url = urlsplit(source)
        host = url.hostname or ""
        return (url.scheme == "https" and not url.username and not url.password
                and bool(DNS_NAME.fullmatch(host))
                and host != "home.arpa" and not host.endswith(".home.arpa")
                and host.rsplit(".", 1)[-1] not in ("local", "localhost", "internal", "test", "invalid")
                and (url.port is None or url.port > 0))
    except ValueError:
        return False


def check_origins(root, registry, per_track, errors):
    doc = load_record(root, "origins.json", errors)
    if doc.read("format", int) != 1:
        doc.error("format must be 1")
    games = {}
    game_rows = doc.object("games")
    if game_rows is not None:
        for key, value in game_rows.data.items():
            text_value(key, game_rows.where, errors, pattern=KEY_RE)
            game = game_rows.child(key, value)
            if game is not None:
                game.text("title")
                origin_code(game.data.get("code", MISSING), f"{game.where}.code", errors)
                games[key] = game.read("racing_game", bool)
    tracks = doc.object("tracks")
    if tracks is None:
        return
    relations = {"port", "remake", "reimagined", "mashup", "inspired", "level", "original"}
    for key, value in tracks.data.items():
        text_value(key, tracks.where, errors, pattern=KEY_RE, limit=250)
        row = tracks.child(key, value)
        if row is None:
            continue
        if key not in registry:
            row.error("track is missing from registry.json")
        origin = row.text("origin_game", pattern=KEY_RE)
        if origin is not None and origin not in games:
            row.error("origin_game is missing from games")
        relation = row.choices("relation", relations)
        review = row.choices("review", {"unverified", "disputed", "verified"})
        if "code_override" in row.data:
            origin_code(row.data["code_override"], f"{row.where}.code_override", errors)
            if relation != "mashup":
                row.error("code_override requires a mashup")
        row.choices("corrected_by", {"maintainer", "author"}, default=None)
        citations = list(row.rows("evidence"))
        if not citations:
            row.error("expected public evidence")
        for citation in citations:
            url = citation.text("url")
            citation.text("note")
            if url is not None and not public_origin_url(url):
                citation.error("expected a public https URL")
        models = row.read("own_letter_models", dict, default={})
        if not models:
            continue
        matched = set()
        if key in registry and key in per_track:
            matched = registry[key].verified_ctr_revisions() & per_track[key].verified_ctr_revisions()
        levs = {lev for _revision, lev, _modes in matched}
        for lev, glyphs in models.items():
            where = f"{row.where}.own_letter_models"
            if text_value(lev, where, errors, pattern=HEX64) is not None and lev not in levs:
                row.error("own_letter_models needs verified CTR Challenge LEV hashes")
            origin_code(glyphs, f"{where}.{lev!r}", errors)
        if not (review == "verified" and relation in ("port", "remake") and games.get(origin)):
            row.error("stage 1 models require a verified racing game port or remake")


def check_listing(record, *, author_level):
    listing = record.object("client_listing")
    if listing is None:
        return
    listing.exact({"status", "scope", "on", "evidence"})
    status = listing.choices("status", CONSENT_STATUSES)
    scope = listing.choices("scope", CONSENT_SCOPES, default=None, nullable=True)
    if author_level and status == "granted" and scope is None:
        listing.error(f"an author grant needs scope {sorted(CONSENT_SCOPES)}")
    listing.day("on")
    evidence = listing.text("evidence")
    if evidence is not None and evidence != CONSENT_PRIVATE_EVIDENCE and (
            len(evidence) > 300 or not evidence.startswith("https://") or any(c.isspace() for c in evidence)):
        listing.error(f"evidence must be a public https link or {CONSENT_PRIVATE_EVIDENCE!r}")


def check_consent(root, registry, errors):
    doc = load_record(root, "consent.json", errors, private_keys=CONSENT_PRIVATE_KEYS)
    if doc.read("format", int) != CONSENT_FORMAT:
        doc.error(f"format must be {CONSENT_FORMAT}")
    doc.exact({"format", "about", "authors", "tracks"})
    doc.text("about", default=None)
    ids, names = set(), set()
    for row in doc.rows("authors"):
        row.exact({"saphi_author_id", "name", "client_listing"})
        aid = row.read("saphi_author_id", int)
        if aid is not None:
            if not 0 < aid <= AUTHOR_ID_MAX:
                row.error("saphi_author_id must be a positive integer in range")
            elif aid in ids:
                row.error(f"saphi_author_id {aid} listed twice")
            ids.add(aid)
        name = row.text("name", limit=NAME_MAX)
        if name is not None:
            if name in names:
                row.error(f"name {name!r} listed twice")
            names.add(name)
        check_listing(row, author_level=True)
    seen = set()
    for row in doc.rows("tracks", default=[]):
        row.exact({"track_key", "client_listing"})
        key = row.text("track_key", pattern=KEY_RE, limit=250)
        if key is not None:
            if key not in registry:
                row.error(f"track_key {key!r} is not in registry.json")
            elif key in seen:
                row.error(f"track_key {key} listed twice")
            seen.add(key)
        check_listing(row, author_level=False)


def check_freeze(previous, current, errors):
    # Older snapshots are inputs to the freeze comparison only. In particular,
    # titles and modes can be corrected without applying current rules to them.
    doc = load_record(previous, "registry.json", errors, label="previous registry.json", private_keys=set())
    for old in doc.rows("tracks"):
        key = old.read("track_key", str)
        if key is None:
            continue
        now = current.get(key)
        if now is None:
            errors.append(f"frozen: {key} disappeared")
            continue
        block = old.read("block_index", int, default=None, nullable=True)
        mint = old.read("mint_status", str, default="mint")
        if block is not None and now.block != block:
            errors.append(f"frozen: {key} block_index changed")
        if mint == "builtin":
            mapping = old.read("maps_to", str, default=None, nullable=True)
            if now.mint != "builtin" or now.mapping != mapping:
                errors.append(f"frozen: {key} builtin mapping changed")
        shipped = old.read("shipped_in", str, default=None, nullable=True)
        if shipped:
            name = old.read("ap_name", str, default=None, nullable=True)
            for field, before, after in (("mint_status", mint, now.mint),
                                         ("shipped_in", shipped, now.shipped),
                                         ("ap_name", name, now.name)):
                if before != after:
                    errors.append(f"frozen: {key} {field} changed after shipping")
        now_revs = {rev.revision: rev for rev in now.revisions if rev.revision is not None}
        for row in old.rows("revisions", default=[]):
            # Only an exact verified marker freezes an older revision. Allow
            # corrections to any historical value that never froze hashes.
            if row.data.get("hash_state") != "verified":
                continue
            revision = row.read("revision", str)
            content = row.read("content_id", str, default=None, nullable=True)
            files = row.read("files", dict, default=None, nullable=True)
            cur = now_revs.get(revision)
            if (cur is None or cur.hash_state != "verified"
                    or cur.content_id != content or cur.files != files):
                errors.append(f"frozen: {key} verified revision {revision} changed")


def check(root: Path, previous: Path | None = None) -> list[str]:
    errors: list[str] = []
    registry = registry_tracks(root, errors)
    aliases = check_identity(root, registry, errors)
    per_track = per_track_records(root, registry, errors)
    digest_doc = load_record(root, "DIGEST.json", errors)
    digest = digest_doc.text("digest", pattern=HEX64)
    try:
        actual_digest = digest_of(root)
    except (OSError, UnicodeError) as exc:
        digest_doc.error(f"cannot compute registry digest ({exc})")
    else:
        if digest != actual_digest:
            digest_doc.error("digest does not match registry.json and tracks/")
    check_named(root, registry, digest, aliases, errors)
    check_consent(root, registry, errors)
    check_origins(root, registry, per_track, errors)
    if previous is not None:
        check_freeze(previous, registry, errors)
    return errors


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", type=Path, nargs="?", default=Path("."))
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args(argv)
    errors = check(args.root, args.previous)
    for error in errors:
        # JSON permits escaped lone surrogates. Keep diagnostics printable even
        # when the process runs with a restrictive stdout encoding.
        encoding = sys.stdout.encoding or "utf-8"
        printable = CONTROL_CHAR.sub(lambda match: ascii(match[0])[1:-1], error)
        print("FAIL", printable.encode(encoding, "backslashreplace").decode(encoding))
    print("registry check:", "FAILED" if errors else "ok", f"({len(errors)} problems)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
