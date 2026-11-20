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

## Running the checks locally

    python tools/check_registry.py .
    python tools/check_registry.py . --previous ../older-checkout

The second form is the freeze check: it fails if any track, block index,
shipped name or verified hash from the older checkout changed or is missing.
