# Metroid Prime 2: Echoes — MultiworldGG World

An [Archipelago](https://archipelago.gg)/[MultiworldGG](https://github.com/MultiworldGG/MultiworldGG)
world for *Metroid Prime 2: Echoes* (GameCube), so it can be randomized on its own or joined into a
multiworld with other games. Item shuffle and logic are ported from
[Randovania](https://github.com/randovania/randovania)'s prime2 logic database; the ISO is patched
client-side using [open-prime-rando](https://github.com/randovania/open-prime-rando) (OPR),
following the same "client grants every item" architecture MultiworldGG's Metroid Prime 1 world
uses.

**Note:** This was almost entirely generated using Claude fable/opus/sonnet. I wanted to play a multiworld with my favorite Metroid games and I had some free credits, so I thought this would be a nice way to use them. I'm happy to spend some tokens/time to fix it if it is broken or buggy, so open issues if you want. 

## Status

- **Done:** item shuffle + logic/tricks, generation, ISO patching, the client receive/connect
  loop, client item granting, server communication, Death Link, door lock / elevator / translator gate / starting room randomization, warp to starting room implementation.
- **Needs testing**: portal randomization, goal-trigger detection (beat dark samus).
- **In progress:** Universal Tracker support and final docs

See [`PLAN.md`](PLAN.md) for the full design/porting plan and milestone breakdown.

## Installing and using

This world isn't in a packaged MultiworldGG release yet, so it currently has to be run from
source. The short version:

1. **Get MultiworldGG from source** and make sure `metroidprime2/` is loaded as
   `MultiWorldGG/worlds/metroidprime2`. Requires
   Python 3.12 or 3.13 (not 3.14).
2. **Install this world's extra dependencies** — `open-prime-rando[nod]==0.20.1`,
   `dolphin-memory-engine>=1.3.0`, `ppc-asm>=1.9.0` (see `metroidprime2/requirements.txt`). The
   client installs these automatically the first time it patches an ISO; to do it yourself:
   ```
   [uv] pip install -r metroidprime2/requirements.txt
   ```
3. **Get a player YAML.** Generate a template from the MultiworldGG Launcher
   (`Generate Template Options`). See the options table below for what you can configure.
4. **Generate:** put your YAML(s) in MultiworldGG's `Players/` folder and run `python Generate.py`
   (a single Echoes YAML on its own generates a solo game — you don't need other games'
   YAMLs present).
5. **Host:** `python MultiServer.py output/<your-seed>.zip`, or upload the output `.zip` to
   [multiworld.gg](https://multiworld.gg).
6. **Play:** open your `.apmp2` patch file in the Launcher, choose the **Metroid Prime 2 Client**,
   and point it at your own unmodified *Metroid Prime 2: Echoes* GameCube ISO (NTSC-U or PAL
   only, uncompressed). It patches the ISO, launches Dolphin, and connects automatically via
   Dolphin's memory engine — then just enter the server address/port.

For deeper troubleshooting and host.yaml details specific to this world, see
[`metroidprime2/docs/setup_en.md`](metroidprime2/docs/setup_en.md).

### Running the tests

```
cd MultiWorldGG
python -m pytest worlds/metroidprime2/test/
```

The suite (200+ tests across `metroidprime2/test/`) covers the logic-DB reader, requirement
compiler, region/reachability generation, item pool composition, patch data, entrance
(door lock/elevator/translator gate) randomization, Death Link, and the client's
item-receive logic.

## Config options

These are the keys you can set under the `Metroid Prime 2: Echoes:` section of a player YAML
(see `metroidprime2/options.py`). Anything left out uses its default.

### Goal / item pool

| Option | Type | Default | Description |
|---|---|---|---|
| `sky_temple_keys` | Choice: `0`-`9`, `all_bosses`, `all_guardians` | `9` | How many of the 9 Sky Temple Keys are shuffled into the general pool vs. pre-placed/pre-collected. `all_bosses` places one key on each of the 9 boss/guardian locations; `all_guardians` places keys on the 3 dark temple guardians and pre-collects the rest. |
| `progressive_suit` | Toggle (on by default) | on | Combine Dark Suit and Light Suit into two copies of a single Progressive Suit item. |
| `progressive_grapple` | Toggle | off | Combine Grapple Beam and Screw Attack into two copies of a single Progressive Grapple item. |
| `missile_expansions_unlock_launcher` | Toggle | off | Receiving any Missile Expansion also unlocks the Missile Launcher itself, so expansions are usable before the launcher is found. Off matches Randovania (expansions grant nothing without the launcher); this also affects logic, not just the in-game grant. |
| `power_bomb_expansions_unlock_power_bombs` | Toggle | off | Receiving any Power Bomb Expansion also unlocks Power Bombs themselves, so expansions are usable before the main Power Bomb pickup is found. Off matches Randovania (expansions grant nothing without the main pickup); this also affects logic, not just the in-game grant. Independent of `missile_expansions_unlock_launcher`. |
| `split_beam_ammo` | Toggle (on by default) | on | On: 10 Dark Ammo Expansions + 10 Light Ammo Expansions, 20 ammo each (matches vanilla/Randovania's default). Off: both are replaced by 20 unified Beam Ammo Expansions granting 10 Dark + 10 Light ammo each (Randovania's "Split Beam Ammo Expansions" toggle, inverted) — same total ammo economy, fewer/bigger pickups. |

### Logic

| Option | Type | Default | Description |
|---|---|---|---|
| `trick_level` | Choice: `disabled`/`beginner`/`intermediate`/`advanced`/`expert`/`ludicrous` | `disabled` | Default difficulty of tricks logic is allowed to require; applies to every individual trick left at "use global setting" (see the Tricks table below). |
| `damage_strictness` | Choice: `strict`/`medium`/`lenient` | `medium` | How strictly damage requirements are calculated — higher leniency assumes less incoming damage, so logic needs fewer energy tanks / less reduction to cross hazards. |
| `energy_per_tank` | Range 50-500 | `100` | How much energy (health) each Energy Tank is worth. |
| `dark_aether_damage` | Range 10-600 (tenths of a point/second) | `60` (6.0/sec) | Damage per second taken in a dark world without appropriate suit protection. |
| `dark_suit_damage` | Range 0-600 (tenths of a point/second) | `12` (1.2/sec) | Damage per second taken in a dark world with the Dark Suit (but not the Light Suit). |
| `dangerous_energy_tanks` | Toggle | off | Allow some Energy Tanks to be placed behind their own dark-world/damage requirement, without another tank to make the trip safe. |

### Entrance randomization

| Option | Type | Default | Description |
|---|---|---|---|
| `door_lock_rando` | Toggle | off | Shuffle certain door locks (beam-colored doors, blast shields) among a vetted pool of lock types instead of each door's vanilla lock. |
| `normal_save_station_doors` | Toggle | **on** | When `door_lock_rando` is on, force every door of a Save Station room -- and the matching face on the far side, the one you shoot to get in -- to a Normal Door (any beam opens it), so a save is always reachable. Can also *remove* a vanilla lock: a few save rooms ship with a Missile Blast Shield or Dark Door, and those get normalized too. No effect unless `door_lock_rando` is on. |
| `elevator_rando` | Toggle | off | Shuffle elevators into new two-way connections (every region stays reachable, just not necessarily via the same elevator). The one-way trip to Sky Temple and the intra-Aerie elevator are never shuffled. |
| `portal_rando` | Toggle | off | Shuffle the Light/Dark Aether portals into new connections within each light/dark region pair, and make every portal two-way (including the vanilla one-way arrival-only ones). Each portal keeps its own beam-color requirement; only where it leads changes. |
| `translator_gate_rando` | Choice: `vanilla`/`full_random`/`full_random_unlocked` | `vanilla` | How each of the 17 translator gates' required color is chosen. `full_random`: every gate independently requires a random one of the four translator colors. `full_random_unlocked`: like `full_random`, but each gate may also independently come up "Unlocked" (open with just Scan Visor, no translator at all). Matches Randovania's own translator gate presets. |
| `starting_room` | Choice: `vanilla`/`save_stations`/`anywhere` | `vanilla` | Which pool the starting room is drawn from. `vanilla`: always Temple Grounds - Landing Site. `save_stations`: one of the 18 save-station rooms across the game (9 in light regions, 9 in dark). `anywhere`: one of 272 rooms -- every room Randovania's logic database considers a valid starting location (162 light / 110 dark), including e.g. boss arenas and rooms normally reached only via a one-way drop. A dark-region start means taking Dark Aether damage from the moment the game begins until a suit or safe zone is reached. Declining a save at any of the 18 save stations while holding L+R (see `warp_to_start` below) always returns you to whichever room was chosen, regardless of pool. |
| `starting_room_light_world_only` | Toggle | off | Drops every dark-region room (Dark Agon Wastes, Dark Torvus Bog, Ing Hive, Sky Temple, Sky Temple Grounds) from whichever pool `starting_room` selects, guaranteeing a light-world start. No effect when `starting_room` is `vanilla`. |

### Tricks

`trick_level` sets the default for every trick below; set an individual `trick_*` option to
override just that one. Every trick option shares the same scale: `use_global` (default) /
`disabled` / `beginner` / `intermediate` / `advanced` / `expert` / `ludicrous`.

| Option | Trick | Summary |
|---|---|---|
| `trick_airunderwater` | Air Underwater | Morph on the frame the camera crosses a water surface to trick movement logic about whether Samus is underwater. |
| `trick_bsj` | Bomb Space Jump | Bomb jump + fast unmorph for an instant-unmorph height boost. |
| `trick_bombjump` | Bomb Jump | Chain bomb jumps to reach otherwise-unattainable heights. |
| `trick_bomblessslot` | Bomb Slot without Bombs | Activate some Bomb Slots with Darkburst/Sunburst/Sonic Boom instead of Bombs. |
| `trick_boostjump` | Boost Jump | Morph, desync the camera, and Boost Ball jump for extra distance. |
| `trick_combat` | Combat | Defeat enemies/bosses with fewer items and less health than intended. |
| `trick_dash` | Combat/Scan Dash | Lock onto an enemy or scan point and strafe-dash to preserve momentum across gaps. |
| `trick_edash` | Extended Dash | Strafe dash interrupted mid-jump for a large speed boost. |
| `trick_enemyhop` | Jump Off Enemy | Jump off enemies for extra height. |
| `trick_instantmorph` | Instant Morph | Morph near a wall/ceiling to skip the morph animation and enter tunnels from the wrong side. |
| `trick_invisibleobjects` | Invisible Objects | Interact with objects (e.g. Dark Visor platforms) without the visor needed to see them. |
| `trick_knowledge` | Knowledge | Use non-obvious vulnerabilities of destructible objects (e.g. Super Missiles on rubble meant for Screw Attack). |
| `trick_movement` | Movement | Catch-all for non-obvious precise movement and traversal optimizations. |
| `trick_nosuits` | Suitless Dark Aether | Traverse Dark Aether, or tank Ingclaw/Ingstorm damage, without the matching suit. |
| `trick_oob` | Single Room Out of Bounds | Leave a room's boundaries to reach otherwise-unreachable areas within that room. |
| `trick_rolljump` | Roll Jump | Roll off a ledge into an instant unmorph and jump for extra speed/distance. |
| `trick_sanosj` | Screw Attack at Z-Axis | Screw Attack without Space Jump in rooms where Samus's Z-position isn't 0 (mainly upper Sanctuary Fortress). |
| `trick_scanpost` | Open Gates from Behind | Open one-way gates from the wrong side via scan posts or beam combos. |
| `trick_screwattacktunnels` | Screw Attack into Tunnels/Openings | Use Screw Attack's small hitbox to fit into tunnels and tight gaps. |
| `trick_seekerlesslocks` | Seeker Locks without Seeker Missiles | Break some Seeker Locks using standard Missiles + Screw Attack instead of Seeker Missiles. |
| `trick_slopejump` | Slope Jump | Jump into sloped surfaces for extra height via a physics quirk. |
| `trick_standableterrain` | Standable Terrain | Stand on unlikely scenery (small ledges, vines, railings) to reach new places. |
| `trick_terminalfall` | Terminal Fall Abuse | Abuse fall-void triggers to warp into unintended parts of a room. |
| `trick_underwaterdash` | Underwater Dash | Hold L+R while swimming to lock speed and reach some areas early. |
| `trick_wallboost` | Wall Boost | Boost on wall contact to partially scale terrain, typically in Morph Ball tunnels. |

### Quality of Life

| Option | Type | Default | Description |
|---|---|---|---|
| `warp_to_start` | Toggle (on by default) | on | Declining to save at a Save Station while holding L+R warps you back to the starting room (Samus' ship in Landing Site, or wherever `starting_room` chose). Declining without L+R held behaves exactly as in vanilla. |

Cutscenes are always skippable (press Start) -- this isn't a configurable option because open-prime-rando's `patch_iso` applies it unconditionally to every seed, the same way it always randomizes a couple of small cosmetic puzzle colors (Main Gyro Chamber, the Sanctuary/Temple Grounds "echo lock" panels) from your seed.

### Combat

| Option | Type | Default | Description |
|---|---|---|---|
| `beam_ammo_costs` | Choice: `vanilla`/`cheap`/`expensive`/`free` | `vanilla` | How much Dark/Light Ammo the Dark Beam, Light Beam, and Annihilator Beam cost per shot. `cheap`/`expensive` halve/double the uncharged, charged, and charge-combo ammo costs; `free` zeroes them (the charge combo's missile cost is untouched either way -- open-prime-rando requires it to stay >=1). Doesn't affect logic, which only cares about ammo capacity, not consumption rate. |
| `annihilator_ammo_source` | Choice: `both`/`dark_only`/`light_only` | `both` | Which ammo pool(s) the Annihilator Beam draws from per shot. `both` is vanilla (costs Dark and Light Ammo simultaneously); the other two make it cost only one type. Doesn't affect logic (the Annihilator Beam is a simple boolean requirement there). |
| `double_damage_multiplier` | Range 100-500 (percent) | `200` | Damage multiplier granted by the Double Damage item. Not in the default item pool, so this only matters if a copy reaches you some other way (e.g. `start_inventory`). |
| `defense_up_damage_reduction` | Range 0-90 (percent) | `0` | Percentage of incoming damage permanently negated by the Defense Up custom item, on top of the Dark Aether/Dark Suit damage math `dark_aether_damage`/`dark_suit_damage` already model. Since Varia Suit's capacity is always locked at exactly 1, this is a single flat value applied from the start of the game, not a stacking pickup. Not modeled in logic -- a non-zero value can only make survival easier than logic assumes, never harder. |

### Cosmetic

| Option | Type | Default | Description |
|---|---|---|---|
| `display_nonlocal_items` | Choice: `none`/`match_game` | `match_game` | Whether items belonging to other players show a matching in-game model, or a generic model. `match_game` covers other Echoes players and conceptually-equivalent items from MultiWorldGG's other Metroid games (Metroid Prime, Metroid: Zero Mission, Metroid Fusion, Super Metroid) -- e.g. another player's Metroid Prime Energy Tank or Super Metroid Missile shows up using this game's own Energy Tank/Missile Expansion model. A few of these cross-game matches are experimental (never independently verified safe to place outside their own vanilla spot -- see `patch_data.py`'s `_CROSS_GAME_ITEM_NAMES`/`_CROSS_GAME_MODEL_OVERRIDES`); anything unmatched still falls back to the generic model. |
| `map_visibility` | Choice: `vanilla`/`full_map`/`full_map_and_items` | `vanilla` | How much of the in-game map is revealed from the start. `vanilla`: fills in as you explore, item dots wait for their room to be visited or a map station used. `full_map`: every room is drawn from the start (rooms still need to be visited for name/details), but item dots still wait for their room. `full_map_and_items`: as `full_map`, plus a dot at every item location from the start, mirroring the Metroid Prime 1 randomizer. One setting rather than two toggles because an item dot needs its room drawn to be visible at all. |
| `unvisited_room_names` | Toggle (on by default) | on | Show room names on the map for rooms not yet visited. |

### Common Archipelago options

| Option | Type | Default | Description |
|---|---|---|---|
| `death_link` | Toggle | off | Share deaths with every other Death Link player in the multiworld. |
| `start_inventory_from_pool` | Item dict | `{}` | Start with the given items already collected, removing that many copies from the shuffled pool. |
| `progression_balancing` | Range 0-99 | `50` | Standard core Archipelago option: nudges progression items earlier to reduce being stuck. |
| `accessibility` | Choice: `full`/`minimal` | `full` | Standard core Archipelago option: whether generation must guarantee every item/location is reachable, or only what's needed to reach the goal. |

### Host-only settings (`host.yaml`, not part of a player YAML)

Set once per MultiworldGG install under the `metroidprime2_options` group; see
[`metroidprime2/docs/setup_en.md`](metroidprime2/docs/setup_en.md) for details.

| Setting | Description |
|---|---|
| `rom_file` | Path to your vanilla NTSC-U/PAL Echoes ISO, used when no ISO is given directly on the client command line. |
| `emulator_settings.executable_path` | Path to your Dolphin executable. |
| `emulator_settings.arguments` | Extra command-line arguments passed to Dolphin. |
| `emulator_settings.auto_start` | Whether the client launches Dolphin with the patched ISO automatically (default on). |
| `hud_settings.color` | `default`, `custom` (with `color_red`/`color_green`/`color_blue`), or a named color. |
| `suit_settings.varia_skin` / `dark_skin` / `light_skin` | Cosmetic suit model swap: `player1` (vanilla), `player2`, `player3`, or `player4`. |

## Caveats / Bugs

- Currently this cannot be used alongside the Metroid Prime 1 world implementation out of the box because it declares `ppc_asm==1.2.1` in its requirements.txt and `open-prime-rando` requires `ppc_asm>=1.9.0`. **However** in my testing the prime world's use of `ppc_asm` is compatible with 1.9.0, so you can run the default requirements install and then `[uv] pip install -U 'ppc_asm>=1.9.0'` and it will still function. Once you have all requirements installed and `ppc_asm` pinned to the newer version, you can prevent the MultiWorldGG launcher from trying to re-install (revert) dependencies by setting the `SKIP_REQUIREMENTS_CHECK` environement variable.
