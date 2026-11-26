# CTR track registry

The public record of custom-track names, credits and file hashes for
[CTR Archipelago](https://github.com/dowlle/ctr-archipelago-apworld).
[Archipelago](https://archipelago.gg) mixes several games into one shared
randomized game; CTR Archipelago adds Crash Team Racing to it, including
community-made custom tracks.

**This repository holds names, credits, hashes and links. It never holds track
files.** No `.lev`, `.vrm`, `.sca` or other track asset is stored here, and none
will be. Downloads stay with the track authors and
[Project Saphi](https://www.projectsaphi.com).

## What a listing means

Every track listed here was made by its author, not by CTR Archipelago. A
listing records the track's name, who made it and how to recognise its files.
It is not a claim of ownership, and it does not mean the author has given
permission for anything.

We are asking track authors whether CTR Archipelago may offer their tracks for
download inside the game. [`consent.json`](consent.json) shows what each author
said. From version 0.3.0-alpha4 on, the game offers a track for download only
when its author said yes there, or when the track's own Project Saphi setting
allows it and the author has not said no. Every other track is not offered.
Players can still add track files themselves.

## Where the record lives

This repository is the record. Other tools read it from here: the CTR
Archipelago game reads `registry.json` and `consent.json` straight from this
repository, and each CTR Archipelago release builds from one fixed commit of it.

In `origins.json`, `letter_placements` records three anchors in pickup slot
order for a verified origin track. Each set is keyed by LEV SHA-256 and names
the exact VRM SHA-256 from `sources.json`. Anchors use signed 16-bit world
coordinates and a yaw from 0 to 4095. The record describes client-placed
letters and leaves the source files' reported modes and contents intact.

## For track authors

If your track is listed, you can ask us to correct its title or credit, add
someone who worked on it, or remove it. Ask on our
[Discord server](https://discord.com/invite/HxXy4mKQ5E), or open an issue or a
pull request here.

Removal is done by hand. Once you ask, your track is marked as withdrawn in
`consent.json` and the game no longer offers it for download. Some values stay
in this list after removal, because games that were already made depend on
them: the track key, the block number and the hashes of its files. A hash
identifies a file; it contains no part of the track.

## What a registry entry is

One entry is one custom track. It has:

- a `track_key`, a short permanent identifier such as `baby-t-park`
- a display title and credits for the people who made it
- one or more revisions, each with the SHA-256 of its files and a `content_id`
  derived from them
- where the track comes from: its Project Saphi track number, or the patch
  it was taken from
- once the track is given its own block of Archipelago ids: a `block_index` and
  an `ap_name`
- a `mint_status`: `mint` (the default), `reserved` (the block number is kept
  but nothing is minted until the entry is confirmed) or `builtin` (the entry
  is an existing in-game named block, named in `maps_to`; its block number stays
  permanently unused). Only `mint` entries appear in `named_tracks.json`

The files:

| File | Contents |
|---|---|
| `registry.json` | Every recorded track and its revisions, in one file |
| `tracks/<key>.json` | One track with the full descriptor of each revision |
| `consent.json` | What each track author said about download in the game |
| `origins.json` | Which game or level a track is based on, with a source link |
| `named_tracks.json` | The input an apworld release pins: tracks to mint as named id blocks, in block order |
| `DIGEST.json` | A digest over `registry.json` and `tracks/`, so a build can pin one commit and one digest |
| `tools/check_registry.py` | The checker CI runs (Python standard library only) |

Ids are computed from the block, never stored by hand: location ids are
`35200000 + 200 * block_index + offset` and item ids are
`35100000 + 5 * block_index + offset`. Room for 10,000 tracks.

## How entries get in

Entries are added and corrected by hand. A maintainer prepares each change as a
pull request, CI runs the checker, and the change is merged by hand once the
check is green. Nothing merges by itself. To ask for a new track, a new
revision or a correction, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Freeze rules

Seeds and Archipelago datapackages depend on these values, so once recorded
they do not change:

- `track_key` never changes and is never reused, even after a track is withdrawn.
- `block_index` never changes and is never reused. Withdrawn, reserved and
  builtin tracks keep their block number.
- An `ap_name` is frozen from the first apworld release that ships it. Renames
  only go through the CTR Archipelago datapackage unfreeze process, never
  through this repository alone.
- A verified revision keeps its `content_id` and file hashes forever. A changed
  file is a new revision.

Titles, credits and links can be corrected at any time. They are presentation,
not identity.

CI enforces this: every pull request is compared with the commit it is based
on (`check_registry.py --previous`), and any track, block, shipped name or
verified hash that moved or disappeared fails the check.

## Credits

Every track belongs to its author. The credits in each entry name the people
who made the track.

Titles and author names come from
[Project Saphi](https://www.projectsaphi.com), the community track library for
Crash Team Racing, through its public API. Tracks that are not on Project Saphi
are credited from the patch they come from. Thank you to Project Saphi and to
every track author. If a title or credit is wrong, see
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

The registry data and the checker are released under
[CC0 1.0](LICENSE). That covers this repository's compilation and our own
contributions. It does not claim any rights in the tracks themselves, and
credits and titles remain attributed to their authors.
## Track identity

`registry.json` may also list `track_key_aliases`, `road_sha256` and
`patch_lev_keys`. Each entry maps directly to a registered track key.
An alias preserves a historical key and never shadows a registry row. Once
published, its target is frozen. Include all three maps together.

A road hash is SHA-256 over the bytes `CTR road v1` and one zero byte,
followed by unique road vertex positions in lexicographic order by signed
X, Y, Z. Pack each position as three signed little-endian 16-bit coordinates.
Use all nine indices of each quad with flag bit `0x1000` set. An empty
set or an invalid vertex index yields no hash. Omit ambiguous roads.
Exact file pins can distinguish copies on the same road.
Road and alias matches identify the track. Pickup rulings and downloads
still require their own exact file pins.

The supplemental LEV hashes in `patch_lev_keys` identify copies whose track
names are known. A row grants identity only.

| LEV hash prefix | Track key | Name evidence |
| --- | --- | --- |
| `7a090016795b` | `drive-thru-danger` | 30th Anniversary Adventure slot 57, identical LEV in Lockbox Adventure slot 185 |
| `7ddbd88c8988` | `north-pole` | Project Saphi track 20, 1.2.0 |
| `9201064be973` | `chasqui-rally` | Project Saphi track 41, 2.3.0 |
| `a4bfafc6e1be` | `matsuri` | Project Saphi track 25, 1.1.0 |
| `c09b56940f31` | `green-hill-raceway` | Project Saphi track 6, 1.1.0 |
| `c6a3f63d190e` | `space-labs` | Project Saphi track 21, 1.2.4 |
| `d1b54abf41ca` | `matsuri` | Project Saphi track 25, 1.1.0 |
| `e9dd31ad94bc` | `space-labs` | Project Saphi track 21, 1.2.4 |
