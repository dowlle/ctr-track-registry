# Contributing

## Adding or correcting a track

Changes to this list are made by hand. To ask for a new track, a new revision,
a correction to a title or credit, or a removal, post on the
[Discord server](https://discord.com/invite/HxXy4mKQ5E) or open an issue here.
Include a link to the page where the track is published.

A maintainer turns the request into a pull request. CI runs the checker, and
the pull request is merged by hand once the check is green.

If you made a track and want it removed, ask in either place. The track is then
marked as withdrawn in `consent.json` and the game no longer offers it for
download. The README explains which values stay listed after removal.

## What belongs in this repository

Names, credits, hashes, descriptors and links. **Never track files** (`.lev`,
`.vrm`, `.sca`, archives, textures, audio). CI rejects them.

## Pull requests

Pull requests that change the data are welcome when the checker passes, and so
are these:

- fixes to `tools/check_registry.py` and the workflow
- documentation improvements
- reviewed road hashes, supplemental LEV identities and historical aliases

## Running the checks locally

    python tools/check_registry.py .
    python tools/check_registry.py . --previous ../older-checkout

The second form is the freeze check: it fails if any track, block index,
shipped name, verified hash, road identity or historical alias from the older checkout
changed or is missing. CI also runs the base branch's freeze checker.

### Importing an AP-Pie export

Export into a separate directory. Older exporters write a checker and two
JSON indexes that predate the road hashes. Keep the registry repository's
checker. Carry `track_key_aliases`, `road_sha256` and `patch_lev_keys` from
the current `registry.json` into the new export, and each track's `mode_pairs`
into both its `registry.json` row and `tracks/<key>.json` (the exporter does
not write them, and the freeze check does not protect them). When a supplemental LEV
becomes a verified registry revision on the same track, remove its redundant
supplemental entry.
Keep the aliases targeting mint and built-in entries in `named_tracks.json`.
Update `DIGEST.json` and `named_tracks.json` from the new
`tools.check_registry.digest_of(Path("."))` value, then run the freeze check
against the previous checkout before opening the export PR.
