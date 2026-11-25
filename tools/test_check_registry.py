"""Exercise the checker CLI against malformed registry documents."""

import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from check_change import snapshot, verify_change
from check_registry import digest_of, main

A = "a" * 64
B = "b" * 64
TRACK_FILE = "tracks/sample.json"
REVISION = ("tracks", 0, "revisions", 0)
AUTHOR_LISTING = ("authors", 0, "client_listing")
TRACK_LISTING = ("tracks", 0, "client_listing")
ORIGIN = ("tracks", "sample")
CITATION = (*ORIGIN, "evidence", 0)
DELETE = object()


def fixture():
    track = {
        "track_key": "sample", "display_title": "Circuit Étoile", "block_index": 0,
        "ap_name": "Circuit Étoile", "state": "named", "mint_status": "mint",
        "maps_to": None, "shipped_in": None,
        "revisions": [{
            "revision": "1.0", "hash_state": "verified", "content_id": A,
            "modes": ["arcade", "ctr_challenge"], "files": {"lev": {"sha256": B, "size": 256}},
        }],
    }
    listing = {"status": "granted", "on": "2024-02-29", "evidence": "https://example.org/%C2%9F"}
    return {
        "registry.json": {"schema_version": 1, "tracks": [track]},
        TRACK_FILE: copy.deepcopy(track),
        "DIGEST.json": {"digest": A},
        "named_tracks.json": {
            "format": 1, "registry": {"digest": ""},
            "tracks": [{
                "track_key": "sample", "block_index": 0, "ap_name": "Circuit Étoile",
                "shipped_in": None, "revisions": [A],
            }],
        },
        "origins.json": {
            "format": 1,
            "games": {"sample-game": {"title": "Étoile Racing", "racing_game": True, "code": "ETR"}},
            "tracks": {"sample": {
                "origin_game": "sample-game", "relation": "remake", "review": "verified",
                "corrected_by": "author", "own_letter_models": {B: "ETR"},
                "evidence": [{"url": "https://example.org/race", "note": "Course citation"}],
            }},
        },
        "consent.json": {
            "format": 1, "about": "Author permissions",
            "authors": [{"saphi_author_id": 2, "name": "Renée",
                         "client_listing": {**listing, "scope": "all_saphi_tracks"}}],
            "tracks": [{"track_key": "sample", "client_listing": dict(listing)}],
        },
    }


def add_descriptor(documents):
    track_revision = documents[TRACK_FILE]["revisions"][0]
    summary_revision = documents["registry.json"]["tracks"][0]["revisions"][0]
    for rev in (track_revision, summary_revision):
        rev["descriptor_schema"] = 1
        rev["files"].setdefault("vrm", {"sha256": A, "size": 256})
    rev = track_revision
    rev["descriptor"] = {
        "schema_version": 1, "revision": rev["revision"], "content_id": rev["content_id"],
        "files": copy.deepcopy(rev["files"]), "relic_targets": None,
        "pack": {"authors": ["Renée"], "title": "Sample pack"},
        "provenance": {"xdelta": {"base_disc_sha256": A, "patch_sha256": B,
                                  "bigfile_index": 0, "cutter_version": 1}},
    }
    return rev["descriptor"]


def resolve(data, path):
    for key in path:
        data = data[key]
    return data


def mutate(documents, file, path, value):
    parent = resolve(documents, (file, *path[:-1])) if path else documents
    key = path[-1] if path else file
    if value is DELETE:
        del parent[key]
    else:
        parent[key] = value


def write_fixture(root, documents, *, keep_digest=False):
    (root / "tracks").mkdir(exist_ok=True)
    for file, value in documents.items():
        (root / file).write_text(json.dumps(value), encoding="utf-8")
    if not keep_digest:
        digest = digest_of(root)
        (root / "DIGEST.json").write_text(json.dumps({"digest": digest}), encoding="utf-8")
        named = documents["named_tracks.json"]
        if isinstance(named, dict) and isinstance(named.get("registry"), dict):
            named["registry"]["digest"] = digest
            (root / "named_tracks.json").write_text(json.dumps(named), encoding="utf-8")


def run(root, previous=None):
    argv = [str(root)]
    if previous is not None:
        argv += ["--previous", str(previous)]
    output = io.StringIO()
    with redirect_stdout(output):
        status = main(argv)
    return status, output.getvalue()


class CheckerTests(unittest.TestCase):
    def test_partial_track_identity_fails(self):
        docs = fixture()
        docs["registry.json"]["road_sha256"] = {}
        write_fixture(self.root, docs)
        status, output = run(self.root)
        self.assertEqual(status, 1)
        self.assertIn("track identity fields must be supplied together", output)

    def test_historical_alias_cannot_disappear(self):
        docs = fixture()
        docs["registry.json"].update(track_key_aliases={"former-name": "sample"},
                                     road_sha256={}, patch_lev_keys={})
        docs["named_tracks.json"]["track_key_aliases"] = {"former-name": "sample"}
        write_fixture(self.previous, docs)
        status, output = run(self.root, self.previous)
        self.assertEqual(status, 1)
        self.assertIn("frozen: track alias former-name changed or disappeared", output)

    def test_hashes_survive_export_and_exact_lev_can_be_promoted(self):
        docs = fixture()
        registry = docs["registry.json"]
        road, lev = "c" * 64, "d" * 64
        registry.update(track_key_aliases={}, road_sha256={road: "sample"}, patch_lev_keys={lev: "sample"})
        write_fixture(self.previous, docs)

        registry["road_sha256"].clear()
        registry["patch_lev_keys"].clear()
        write_fixture(self.root, docs)
        status, output = run(self.root, self.previous)
        self.assertEqual(status, 1)
        self.assertIn(f"road hash {road} changed or disappeared", output)
        self.assertIn(f"supplemental LEV {lev} changed or disappeared", output)

        registry["road_sha256"][road] = "sample"
        revision = {"revision": "1.1", "hash_state": "verified", "content_id": "e" * 64,
                    "files": {"lev": {"sha256": lev, "size": 256}}, "modes": ["arcade"]}
        registry["tracks"][0]["revisions"].append(revision)
        docs[TRACK_FILE]["revisions"].append(copy.deepcopy(revision))
        docs["named_tracks.json"]["tracks"][0]["revisions"].append(revision["content_id"])
        write_fixture(self.root, docs)
        self.assertEqual(run(self.root, self.previous)[0], 0)

    def test_track_identity_uses_canonical_keys(self):
        docs = fixture()
        registry = docs["registry.json"]
        registry["track_key_aliases"] = {"former-name": "sample"}
        registry["road_sha256"] = {"c" * 64: "sample"}
        registry["patch_lev_keys"] = {"d" * 64: "sample"}
        docs["named_tracks.json"]["track_key_aliases"] = registry["track_key_aliases"].copy()
        write_fixture(self.root, docs)
        self.assertEqual(run(self.root)[0], 0)
        registry["track_key_aliases"]["sample"] = "former-name"
        registry["road_sha256"]["uppercase"] = "sample"
        registry["patch_lev_keys"][B] = "sample"
        write_fixture(self.root, docs)
        status, output = run(self.root)
        self.assertEqual(status, 1)
        self.assertIn("shadows a registered track", output)
        self.assertIn("must refer directly to a registered track", output)
        self.assertIn("invalid key 'uppercase'", output)
        self.assertIn("is already a registry revision pin", output)

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "current"
        self.previous = Path(temp.name) / "base"
        self.root.mkdir()
        self.previous.mkdir()
        write_fixture(self.root, fixture())
        write_fixture(self.previous, fixture())

    def assert_invalid(self, expected, *, fragment=False):
        status, output = run(self.root, self.previous)
        self.assertEqual(status, 1, output)
        self.assertIn(expected if fragment else f"FAIL {expected}", output)
        self.assertIn("registry check: FAILED", output)
        self.assertNotIn("Traceback", output)

    def test_valid_registry_and_freeze(self):
        self.assertEqual(run(self.root, self.previous), (0, "registry check: ok (0 problems)\n"))

    def test_claimed_revision_without_size_is_valid(self):
        documents = fixture()
        claimed = {"revision": "2.0", "hash_state": "claimed", "content_id": B,
                   "modes": [], "files": {"lev": {"sha256": A}}}
        documents["registry.json"]["tracks"][0]["revisions"].append(claimed)
        documents[TRACK_FILE]["revisions"].append(claimed)
        documents["named_tracks.json"]["tracks"][0]["revisions"].append(B)
        write_fixture(self.root, documents)
        self.assertEqual(run(self.root, self.previous), (0, "registry check: ok (0 problems)\n"))

    def test_wrong_types_nulls_and_missing_fields(self):
        cases = [
            ("registry.json", ("schema_version",), True, "registry.json.schema_version"),
            ("registry.json", ("tracks",), {}, "registry.json.tracks"),
            ("registry.json", ("tracks", 0), [], "registry.json.tracks[0]"),
            ("registry.json", ("tracks", 0, "track_key"), [], "registry.json.tracks[0].track_key"),
            ("registry.json", ("tracks", 0, "state"), [], "registry.json.tracks[0].state"),
            ("registry.json", ("tracks", 0, "display_title"), 42, "registry.json.tracks[0].display_title"),
            ("registry.json", ("tracks", 0, "revisions"), {}, "registry.json.tracks[0].revisions"),
            ("registry.json", REVISION, [], "registry.json.tracks[0].revisions[0]"),
            ("registry.json", (*REVISION, "revision"), [], "registry.json.tracks[0].revisions[0].revision"),
            (TRACK_FILE, ("revisions", 0, "files"), [], f"{TRACK_FILE}.revisions[0].files"),
            (TRACK_FILE, ("revisions", 0, "files", "lev"), [], f"{TRACK_FILE}.revisions[0].files.lev"),
            (TRACK_FILE, ("revisions", 0, "files", "lev", "sha256"), [], f"{TRACK_FILE}.revisions[0].files.lev.sha256"),
            (TRACK_FILE, ("revisions", 0, "modes"), {}, f"{TRACK_FILE}.revisions[0].modes"),
            (TRACK_FILE, ("revisions", 0, "modes", 0), {}, f"{TRACK_FILE}.revisions[0].modes[0]"),
            ("named_tracks.json", ("format",), True, "named_tracks.json.format"),
            ("named_tracks.json", ("registry",), [], "named_tracks.json.registry"),
            ("named_tracks.json", ("tracks", 0), [], "named_tracks.json.tracks[0]"),
            ("named_tracks.json", ("tracks", 0, "block_index"), False, "named_tracks.json.tracks[0].block_index"),
            ("named_tracks.json", ("tracks", 0, "revisions", 0), [], "named_tracks.json.tracks[0].revisions"),
            ("DIGEST.json", ("digest",), [], "DIGEST.json.digest"),
            ("origins.json", ("games",), [], "origins.json.games"),
            ("origins.json", ("games", "sample-game"), [], "origins.json.games.sample-game"),
            ("origins.json", ("games", "sample-game", "racing_game"), 1, "origins.json.games.sample-game.racing_game"),
            ("origins.json", ORIGIN, [], "origins.json.tracks.sample"),
            ("origins.json", (*ORIGIN, "origin_game"), [], "origins.json.tracks.sample.origin_game"),
            ("origins.json", (*ORIGIN, "relation"), [], "origins.json.tracks.sample.relation"),
            ("origins.json", CITATION, [], "origins.json.tracks.sample.evidence"),
            ("origins.json", (*CITATION, "note"), [], "origins.json.tracks.sample.evidence[0].note"),
            ("consent.json", ("authors", 0), [], "consent.json.authors"),
            ("consent.json", ("authors", 0, "saphi_author_id"), True, "consent.json.authors[0].saphi_author_id"),
            ("consent.json", AUTHOR_LISTING, [], "consent.json.authors[0].client_listing"),
            ("consent.json", (*AUTHOR_LISTING, "status"), [], "consent.json.authors[0].client_listing"),
            ("consent.json", ("tracks", 0), [], "consent.json.tracks"),
            ("consent.json", ("tracks", 0, "track_key"), [], "consent.json.tracks[0]"),
            ("consent.json", TRACK_LISTING, [], "consent.json.tracks[0].client_listing"),
            ("consent.json", (*TRACK_LISTING, "on"), [], "consent.json.tracks[0].client_listing"),
        ]
        # Deleting an entry from a collection changes its membership. Only
        # missing fields of required records are type/schema errors.
        map_entries = {("games", "sample-game"), ORIGIN, ("revisions", 0, "files", "lev")}
        for file, path, wrong_type, diagnostic in cases:
            values = (wrong_type, None)
            if isinstance(path[-1], str) and path not in map_entries:
                values += (DELETE,)
            for value in values:
                with self.subTest(file=file, path=path, value=value):
                    documents = fixture()
                    mutate(documents, file, path, value)
                    write_fixture(self.root, documents, keep_digest=file == "DIGEST.json")
                    self.assert_invalid(diagnostic)

    def test_every_document_rejects_a_non_object_root(self):
        for file in fixture():
            for value in (None, [], 1, "text"):
                with self.subTest(file=file, value=value):
                    documents = fixture()
                    documents[file] = value
                    write_fixture(self.root, documents, keep_digest=file == "DIGEST.json")
                    self.assert_invalid(f"{file}: expected dict")

    def test_text_rules(self):
        fields = [
            ("registry.json", ("tracks", 0, "display_title"), "registry.json.tracks[0].display_title"),
            ("registry.json", ("tracks", 0, "ap_name"), "registry.json.tracks[0].ap_name"),
            (TRACK_FILE, ("revisions", 0, "revision"), f"{TRACK_FILE}.revisions[0].revision"),
            ("named_tracks.json", ("tracks", 0, "ap_name"), "named_tracks.json.tracks[0].ap_name"),
            ("origins.json", ("games", "sample-game", "title"), "origins.json.games.sample-game.title"),
            ("origins.json", (*CITATION, "note"), "origins.json.tracks.sample.evidence[0].note"),
            ("origins.json", (*CITATION, "url"), "origins.json.tracks.sample.evidence[0].url"),
            ("consent.json", ("authors", 0, "name"), "consent.json.authors[0].name"),
            ("consent.json", (*TRACK_LISTING, "evidence"), "consent.json.tracks[0].client_listing.evidence"),
        ]
        for file, path, diagnostic in fields:
            for bad in ("x\x00y", "x\x1fy", "x\x7fy", "x\x9fy", "x\u2028y", "x\u2029y",
                        " leading", "trailing ", "trailing\n", "\ud800", "x" * 4097):
                with self.subTest(file=file, path=path, value=bad[:20]):
                    documents = fixture()
                    mutate(documents, file, path, bad)
                    write_fixture(self.root, documents)
                    self.assert_invalid(diagnostic)

    def test_strict_consent_dates(self):
        for value in ("2024-02-29\n", "2024-02-29\x9f", "2025-02-29", "2024-13-01",
                      "0000-02-29", "２０２４-０２-２９", "2024-2-29", "20240229"):
            with self.subTest(date=value):
                documents = fixture()
                mutate(documents, "consent.json", (*AUTHOR_LISTING, "on"), value)
                write_fixture(self.root, documents)
                self.assert_invalid("consent.json.authors[0].client_listing")

    def test_malformed_data_keeps_checking_other_records(self):
        documents = fixture()
        documents["registry.json"]["tracks"][0]["revisions"] = [None]
        documents["consent.json"]["authors"][0]["name"] = "x\x9fy"
        documents["origins.json"]["games"]["sample-game"]["title"] = "title\n"
        write_fixture(self.root, documents)
        for expected in ("registry.json.tracks[0].revisions[0]", "consent.json.authors[0].name",
                         "origins.json.games.sample-game.title"):
            self.assert_invalid(expected)

    def test_invalid_or_deep_json_in_previous_snapshot(self):
        path = self.previous / "registry.json"
        for bad in ("{", "NaN", "[" * 160 + "0" + "]" * 160, "[" * 1500 + "0" + "]" * 1500):
            with self.subTest(data=bad[:20]):
                path.write_text(bad, encoding="utf-8")
                self.assert_invalid("previous registry.json")

    def test_freeze_still_checks_verified_files(self):
        documents = fixture()
        mutate(documents, "registry.json", (*REVISION, "files", "lev", "size"), 512)
        write_fixture(self.root, documents)
        self.assert_invalid("frozen: sample verified revision 1.0 changed")

    def test_freeze_allows_corrections_to_unfrozen_fields(self):
        documents = fixture()
        mutate(documents, "registry.json", ("tracks", 0, "display_title"), "Old title ")
        mutate(documents, "registry.json", (*REVISION, "modes"), DELETE)
        write_fixture(self.previous, documents)
        self.assertEqual(run(self.root, self.previous), (0, "registry check: ok (0 problems)\n"))

    def test_freeze_allows_corrections_to_old_unverified_revisions(self):
        for old_state in (None, [], DELETE):
            with self.subTest(old_state=old_state):
                current = fixture()
                pending = {"revision": "2.0", "hash_state": "pending", "content_id": None,
                           "modes": [], "files": {}}
                current["registry.json"]["tracks"][0]["revisions"].append(pending)
                current[TRACK_FILE]["revisions"].append(pending)
                previous = copy.deepcopy(current)
                mutate(previous, "registry.json", ("tracks", 0, "revisions", 1, "hash_state"), old_state)
                write_fixture(self.root, current)
                write_fixture(self.previous, previous)
                self.assertEqual(run(self.root, self.previous), (0, "registry check: ok (0 problems)\n"))

    def test_verified_hashes_must_be_present(self):
        documents = fixture()
        for rev in (resolve(documents["registry.json"], REVISION), documents[TRACK_FILE]["revisions"][0]):
            rev.update(content_id=None, files={})
        documents["named_tracks.json"]["tracks"][0]["revisions"] = []
        write_fixture(self.root, documents)
        status, output = run(self.root)
        self.assertEqual(status, 1, output)
        self.assertIn("verified revisions need a content_id and file hashes", output)

    def test_per_track_identity_matches_registry(self):
        for path, value, diagnostic in (
            (("track_key",), "other", "track_key must agree with the file name"),
            (("revisions", 0, "content_id"), B, "verified revisions must agree with registry.json"),
        ):
            with self.subTest(path=path):
                documents = fixture()
                mutate(documents, TRACK_FILE, path, value)
                write_fixture(self.root, documents)
                self.assert_invalid(f"{TRACK_FILE}: {diagnostic}")

    def test_per_track_summary_matches_registry(self):
        for path, value in (
            (("display_title",), "Different title"),
            (("revisions", 0, "modes"), ["race"]),
            (("review",), {"value": True}),
        ):
            with self.subTest(path=path):
                docs = fixture()
                mutate(docs, TRACK_FILE, path, value)
                write_fixture(self.root, docs)
                self.assert_invalid(f"{TRACK_FILE}: entry must match registry.json")

    def test_descriptor_schema_and_pins(self):
        for key, value, diagnostic in (
            ("schema_version", True, ".schema_version: expected int"),
            ("content_id", B, ": content_id must agree with the revision"),
            ("files", {"lev": {"sha256": A}}, ": files must agree with the revision"),
            ("relic_targets", {}, ".relic_targets.schema_version: missing"),
        ):
            with self.subTest(key=key):
                docs = fixture()
                add_descriptor(docs)[key] = value
                write_fixture(self.root, docs)
                self.assert_invalid(f"{TRACK_FILE}.revisions[0].descriptor{diagnostic}")

    def test_manager_descriptor_keeps_pre_verification_metadata(self):
        docs = fixture()
        docs[TRACK_FILE]["revisions"][0]["descriptor"] = {
            "revision": " Submitted label ", "content_id": B, "title": "Manager export",
            "files": {"lev": {"sha256": A, "size": None}, "vrm": {"sha256": B}},
            "relic_targets": {
                "schema_version": 1, "laps": 3, "ticks_per_second": 960,
                "lev_sha256": A, "vrm_sha256": B, "platinum": 105, "gold": 120, "sapphire": 136,
            },
        }
        write_fixture(self.root, docs)
        self.assertEqual(run(self.root, self.previous)[0], 0)

    def test_descriptor_schema_matches_revision(self):
        for embedded, declared in ((2, 1), (None, 1), (1, None)):
            with self.subTest(embedded=embedded, declared=declared):
                docs = fixture()
                add_descriptor(docs)["schema_version"] = embedded
                docs[TRACK_FILE]["revisions"][0]["descriptor_schema"] = declared
                resolve(docs["registry.json"], REVISION)["descriptor_schema"] = declared
                write_fixture(self.root, docs)
                self.assert_invalid(f"{TRACK_FILE}.revisions[0].descriptor: schema_version must agree")

    def test_xdelta_requires_verified_geometry(self):
        for field, value in (("hash_state", "claimed"), ("files", {"lev": {"sha256": B, "size": 256}})):
            with self.subTest(field=field):
                docs = fixture()
                descriptor = add_descriptor(docs)
                for rev in (docs[TRACK_FILE]["revisions"][0], resolve(docs["registry.json"], REVISION)):
                    rev[field] = value
                if field == "files":
                    descriptor[field] = value
                write_fixture(self.root, docs)
                self.assert_invalid(f"{TRACK_FILE}.revisions[0].descriptor: xdelta requires")

    def test_verified_descriptor_can_be_added_but_then_freezes(self):
        docs = fixture()
        descriptor = add_descriptor(docs)
        previous = copy.deepcopy(docs)
        del previous[TRACK_FILE]["revisions"][0]["descriptor"]
        write_fixture(self.previous, previous)
        write_fixture(self.root, docs)
        self.assertEqual(run(self.root, self.previous)[0], 0)
        write_fixture(self.previous, docs)
        descriptor["pack"]["title"] = "Different pack"
        write_fixture(self.root, docs)
        self.assert_invalid(f"frozen: {TRACK_FILE} verified revision 1.0 descriptor changed")
        docs[TRACK_FILE]["revisions"][0]["descriptor"] = None
        write_fixture(self.root, docs)
        self.assert_invalid(f"frozen: {TRACK_FILE} verified revision 1.0 descriptor changed")

    def test_relic_targets_must_match_revision_files(self):
        docs = fixture()
        for rev in (docs[TRACK_FILE]["revisions"][0], resolve(docs["registry.json"], REVISION)):
            rev["files"]["vrm"] = {"sha256": A, "size": 256}
        add_descriptor(docs)["relic_targets"] = {
            "schema_version": 1, "laps": 3, "ticks_per_second": 960,
            "lev_sha256": A, "vrm_sha256": A, "platinum": 105, "gold": 120, "sapphire": 136,
        }
        write_fixture(self.root, docs)
        self.assert_invalid(f"{TRACK_FILE}.revisions[0].descriptor.relic_targets: lev_sha256")

    def test_relic_targets_use_native_bounds(self):
        for field, value in (("ticks_per_second", 1000), ("laps", 128), ("sapphire", 21474837)):
            with self.subTest(field=field):
                docs = fixture()
                for rev in (docs[TRACK_FILE]["revisions"][0], resolve(docs["registry.json"], REVISION)):
                    rev["files"]["vrm"] = {"sha256": A, "size": 256}
                targets = {
                    "schema_version": 1, "laps": 3, "ticks_per_second": 960,
                    "lev_sha256": B, "vrm_sha256": A, "platinum": 105, "gold": 120, "sapphire": 136,
                }
                targets[field] = value
                add_descriptor(docs)["relic_targets"] = targets
                write_fixture(self.root, docs)
                self.assert_invalid(f"{TRACK_FILE}.revisions[0].descriptor.relic_targets: {field}")

    def test_policy_changes_are_separate_from_registry_exports(self):
        with patch("check_change.git") as git:
            git.return_value = b"registry.json\0tracks/sample.json\0"
            verify_change("base", "candidate")
            git.return_value = b"tools/check_registry.py\0"
            verify_change("base", "candidate")
            git.return_value = b"registry.json\0tools/check_registry.py\0"
            with self.assertRaisesRegex(ValueError, "separate pull requests"):
                verify_change("base", "candidate")
            git.return_value = b"sources.json\0"
            verify_change("base", "candidate")
            git.return_value = b"sources.json\0tools/check_registry.py\0"
            with self.assertRaisesRegex(ValueError, "separate pull requests"):
                verify_change("base", "candidate")

    def test_revision_mode_vocabulary(self):
        cases = [
            (["saphi_only"], "modes contains unknown"),
            (["arcade", "arcade"], "modes contains duplicates"),
            ([[]], "modes[0]: expected str"),
        ]
        for modes, message in cases:
            with self.subTest(modes=modes):
                documents = fixture()
                mutate(documents, "registry.json", (*REVISION, "modes"), modes)
                mutate(documents, TRACK_FILE, ("revisions", 0, "modes"), modes)
                write_fixture(self.root, documents)
                self.assert_invalid(message, fragment=True)

    def test_modes_require_verified_lev(self):
        cases = [("hash_state", "pending"), ("files", {"vrm": {"sha256": B}})]
        for field, value in cases:
            with self.subTest(field=field):
                documents = fixture()
                mutate(documents, "registry.json", (*REVISION, field), value)
                mutate(documents, TRACK_FILE, ("revisions", 0, field), value)
                write_fixture(self.root, documents)
                self.assert_invalid("registry.json.tracks[0].revisions[0]: nonempty modes require a verified LEV")

    def test_patch_sources_schema(self):
        source = "https://example.org/patch-release"
        slot = {"bigfile_index": 0, "lev_sha256": A, "vrm_sha256": B}
        patch_record = {"file_name": "Track Pack.xdelta", "patch_sha256": A,
                        "slots": [slot.copy()], "source_url": source}
        documents = fixture()
        documents["sources.json"] = {"schema_version": 1, "patches": [patch_record]}
        without_page = {k: v for k, v in patch_record.items() if k != "source_url"}
        without_page["slots"] = [{**slot, "bigfile_index": 4095}]
        for fields in (patch_record, without_page):
            documents["sources.json"]["patches"] = [fields]
            write_fixture(self.root, documents)
            self.assertEqual(run(self.root, self.previous), (0, "registry check: ok (0 problems)\n"))
        cases = [
            (("schema_version",), 2, "schema_version must be 1"),
            (("patches",), {}, "patches: expected list"),
            (("patches",), [patch_record, patch_record], "duplicate patch_sha256"),
            (("patches", 0, "patch_sha256"), "bad", "patch_sha256: invalid format"),
            (("patches", 0, "file_name"), "../pack.xdelta", "file_name: invalid format"),
            (("patches", 0, "source_url"), None, "source_url: expected str"),
            (("patches", 0, "sources"), b"payload".hex(), "unknown keys"),
            (("patches", 0, "slots"), [], "patch needs at least one slot"),
            (("patches", 0, "slots"), [slot, slot], "duplicate bigfile_index"),
            (("patches", 0, "slots", 0, "bigfile_index"), -1, "bigfile_index must be at least 0"),
            (("patches", 0, "slots", 0, "bigfile_index"), 4096, "bigfile_index must be at most 4095"),
            (("patches", 0, "slots", 0, "bigfile_index"), False, "bigfile_index: expected int"),
            (("patches", 0, "slots", 0, "lev_sha256"), "bad", "lev_sha256: invalid format"),
            (("patches", 0, "slots", 0, "vrm_sha256"), "bad", "vrm_sha256: invalid format"),
            (("patches", 0, "slots", 0, "name"), "Extra field", "unknown keys"),
        ]
        for path, value, message in cases:
            with self.subTest(path=path, value=value):
                invalid = copy.deepcopy(documents)
                invalid["sources.json"]["patches"] = [copy.deepcopy(patch_record)]
                mutate(invalid, "sources.json", path, value)
                write_fixture(self.root, invalid)
                self.assert_invalid(message, fragment=True)
        for url in ("http://example.org/release", "https://localhost/release",
                    "https://discord.com/channels/1/2/3", "https://discord.gg/invite",
                    "https://cdn.discordapp.com/attachments/1/2/pack",
                    "https://example.org/pack%2exdelta?download=true", "https://example.org/pack.zip",
                    "https://example.org/pack.tar.gz",
                    "https://example.org/pack.tar.gz/.",
                    "https://www.projectsaphi.com/tracks/121/download/872",
                    "https://www.projectsaphi.com/tracks/121/%2e/download/872",
                    "https://github.com/example/patch/releases/download/v1/pack",
                    "https://github.com/example/patch/releases/./download/v1/pack"):
            with self.subTest(url=url):
                invalid = copy.deepcopy(documents)
                invalid["sources.json"]["patches"] = [{**patch_record, "source_url": url}]
                write_fixture(self.root, invalid)
                self.assert_invalid("sources.json.patches[0]: source_url must be a public HTTPS publication page")

    def test_candidate_snapshot_requires_policy_files(self):
        with patch("check_change.git", return_value=b""):
            with self.assertRaisesRegex(ValueError, "required policy files missing:.*registry-policy.yml"):
                snapshot("candidate", self.root)

    def test_consent_evidence_preserves_character_limit(self):
        documents = fixture()
        prefix = "https://example.org/"
        valid = prefix + "é" * (300 - len(prefix))
        mutate(documents, "consent.json", (*TRACK_LISTING, "evidence"), valid)
        write_fixture(self.root, documents)
        self.assertEqual(run(self.root, self.previous), (0, "registry check: ok (0 problems)\n"))
        mutate(documents, "consent.json", (*TRACK_LISTING, "evidence"), valid + "é")
        write_fixture(self.root, documents)
        self.assert_invalid("consent.json.tracks[0].client_listing")

    def test_duplicate_json_members_are_reported(self):
        consent = self.root / "consent.json"
        source = consent.read_text(encoding="utf-8")
        consent.write_text(source.replace('"on":', '"on": null, "on":', 1), encoding="utf-8")
        self.assert_invalid("consent.json: duplicate JSON field 'on'")

    def test_origin_models_require_both_verified_records(self):
        documents = fixture()
        mutate(documents, TRACK_FILE, ("revisions", 0, "modes"), ["race"])
        write_fixture(self.root, documents)
        self.assert_invalid("origins.json.tracks.sample: own_letter_models needs verified CTR Challenge LEV hashes")


if __name__ == "__main__":
    unittest.main()
