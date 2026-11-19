# CTR track registry

The public record of custom-track names, credits and content hashes for
[CTR Archipelago](https://github.com/dowlle/ctr-archipelago-apworld), the Archipelago
randomizer for Crash Team Racing.

**This repository holds names, credits, hashes and links. It never holds track
files.** No `.lev`, `.vrm`, `.sca` or other track asset is stored here, and none
will be. Downloads stay with the track authors and
[Project Saphi](https://www.projectsaphi.com).

## What a registry entry is

One entry is one custom track. It has:

- a `track_key`, a short permanent identifier such as `baby-t-park`
- a display title and credits for the people who made it
- one or more revisions, each with the SHA-256 of its files and a `content_id`
  derived from them
- links to where the track is published
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
| `named_tracks.json` | The input an apworld release pins: tracks to mint as named id blocks, in block order |
| `DIGEST.json` | A digest over `registry.json` and `tracks/`, so a build can pin one commit and one digest |
| `tools/check_registry.py` | The checker CI runs (Python standard library only) |

Ids are computed from the block, never stored by hand: location ids are
`35200000 + 200 * block_index + offset` and item ids are
`35100000 + 5 * block_index + offset`. Room for 10,000 tracks.

## How entries get in

Entries come in through [AP-Pie](https://ap-pie.com). People submit tracks
there, a maintainer reviews them, and approved entries are exported into this
repository as a pull request. CI runs the checker, and a green run merges.
Please do not edit the generated files by hand; see [CONTRIBUTING.md](CONTRIBUTING.md).

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
who made the track, its music and its Archipelago boxes, as published on the
track's own page.

The titles, author credits and version metadata come from
[Project Saphi](https://www.projectsaphi.com), the community track library for
Crash Team Racing, through its public API. Thank you to Project Saphi and to
every track author. If a title or credit is wrong or you want an entry
changed, see [CONTRIBUTING.md](CONTRIBUTING.md).

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
| `21e1ffe395f1` | `ancient-lake` | Project Saphi track 56, 1.1.0 |
| `286d6574d87e` | `sunken-sprint` | Project Saphi track 123, 1.0.0 |
| `2b18c6305d3c` | `toasty-terrace` | Project Saphi track 39, 1.3.0 |
| `37f2daddfe7f` | `haven-stadium` | Project Saphi track 22, 1.1.0 |
| `50250966e9b3` | `green-hill-raceway` | Project Saphi track 6, 2.0.0 |
| `5d9f0d66fdc0` | `sunken-sprint` | Project Saphi track 123, 1.0.0 |
| `7a090016795b` | `drive-thru-danger` | 30th Anniversary Adventure slot 57, identical LEV in Lockbox Adventure slot 185 |
| `7ddbd88c8988` | `north-pole` | Project Saphi track 20, 1.2.0 |
| `860d5d340207` | `redrock-ravine` | Project Saphi track 9, 1.2.0 |
| `9201064be973` | `chasqui-rally` | Project Saphi track 41, 2.3.0 |
| `9fa73436daaf` | `country-speedway` | Project Saphi track 24, 1.3.0 |
| `a4bfafc6e1be` | `matsuri` | Project Saphi track 25, 1.1.0 |
| `add8c2b43aaa` | `snowy-valley` | Project Saphi track 62, 1.1.0 |
| `bbebd28a0c61` | `coco-park-2025` | Project Saphi track 14, 1.1.0 |
| `c09b56940f31` | `green-hill-raceway` | Project Saphi track 6, 1.1.0 |
| `c3a5a77e754c` | `pepsi-city` | Project Saphi track 58, 1.1.0 |
| `c6a3f63d190e` | `space-labs` | Project Saphi track 21, 1.2.4 |
| `d1b54abf41ca` | `matsuri` | Project Saphi track 25, 1.1.0 |
| `db74f5ae84d1` | `toasty-terrace` | Project Saphi track 39, 1.3.1 |
| `e9dd31ad94bc` | `space-labs` | Project Saphi track 21, 1.2.4 |
| `f9dd02599eee` | `pepsi-city` | Project Saphi track 58, 1.1.1 |
