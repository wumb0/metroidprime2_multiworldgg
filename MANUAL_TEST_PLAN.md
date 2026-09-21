# Manual (in-game) test plan — Metroid Prime 2: Echoes world

Status: **plan only, nothing implemented yet.** This is the design for PLAN.md milestone
M4 ("in-game validation"). Everything below describes files to be written under
`metroidprime2/test/manual/`.

## 1. Why this exists

The automated suite (262 tests, `metroidprime2/test/`) covers everything that can be decided
from data: the logic DB reader, requirement compiler, region graph, item pool, fill, patch-data
JSON, entrance/gate assignments, and the client's *pure* item-receive math. It cannot observe:

* whether the patched ISO **boots** and whether a patched room **loads without crashing**
  (the `VariaSuit` model crash and the Hive Access Tunnel softlock were both found only by playing);
* whether a DOL patch found the right address on *this* build (warp-to-start pattern match,
  item-74 persistence/`powerup_max`, goal sentinel);
* whether the *live* client/game/server loop does the right thing (grants, HUD memos, location
  reports, reconnects, Death Link, goal);
* whether the thing the player sees matches the config we generated (models, HUD text, door
  colors, elevator destinations, gate colors, map dots).

So each manual test is a **python script that builds a purpose-made ISO** that makes exactly one
of those facts cheap to observe, plus a README section that says what to press and what to expect.

Design rules, from the request:

1. One script = one thing under test.
2. The ISO it builds does the **minimum possible work** to observe that thing (start you next to
   what you need; give you everything you need to get there; no unrelated randomization).
3. Item-model tests place items in rooms that **don't depend on each other** — collecting one
   never gates or perturbs another.
4. Reproducible: fixed seed per script, fixed options, and a pinned hash of the generated config
   so a rebuild months later is the same ISO or fails loudly.
5. Every script has a section in `metroidprime2/test/manual/README.md` telling a human how to run it.

## 2. Layout

```
metroidprime2/test/manual/
  README.md            GENERATED (section 6) -- the human-facing manual test book
  __init__.py
  harness.py           ManualTest spec + build pipeline (generate -> apmp2 -> patched ISO)
  presets.py           reusable option/start-inventory/plando bundles
  routes.py            DB-derived helpers: door-distance BFS, independent-pickup selection,
                       unique-subset-sum pairs for the reconciliation test
  build_readme.py      regenerates README.md from every mt*.py module
  catalog.py           imports every mt*.py, exposes the ordered list (used by README + `list`)
  mt01_smoke_vanilla.py
  mt02_goal_credits.py
  ... (section 5)
```

`metroidprime2/.apignore` already excludes `/test`, so none of this ships in the `.apworld`.

Everything runs from the MultiWorldGG checkout with its venv, e.g.

```
cd MultiWorldGG
SKIP_REQUIREMENTS_UPDATE=1 .venv/bin/python -m worlds.metroidprime2.test.manual.mt02_goal_credits \
    --iso ~/isos/echoes-ntsc.iso
```

## 3. Harness (`harness.py`)

### 3.1 The spec object

Each `mtNN_*.py` module defines exactly one module-level `TEST = ManualTest(...)` and ends with
`if __name__ == "__main__": harness.cli(TEST)`.

```python
@dataclass(frozen=True)
class Step:
    do: str                      # what the human does
    expect: str                  # what must happen
    why: str = ""                # optional: which code path this exercises

@dataclass(frozen=True)
class SlotSpec:
    name: str                    # slot name
    game: str                    # "Metroid Prime 2: Echoes", "Metroid: Zero Mission", "Clique", ...
    options: dict[str, Any]

@dataclass(frozen=True)
class ManualTest:
    slug: str                    # "mt02_goal_credits"
    title: str
    priority: str                # "P0" | "P1" | "P2"
    proves: str                  # one sentence: the in-game fact this establishes
    seed: int                    # FIXED, never randomized
    options: dict[str, Any]      # this world's player options
    start_inventory: dict[str, int] = {}
    plando: list[dict] = []      # core AP plando_items entries
    starting_room: str | None = None   # NodeId.ap_name, forced (section 3.3)
    companions: list[SlotSpec] = []    # extra slots in the multiworld
    setup: list[str] = []        # host.yaml / Dolphin prerequisites for this test
    steps: list[Step] = []
    pass_criteria: list[str] = []
    on_failure: list[str] = []   # modules/addresses to inspect when it fails
    config_sha256: str | None = None   # pinned digest of the generated config.json
```

### 3.2 Build pipeline

`harness.build(test, iso, outdir, *, pal=False, patch=True) -> BuildResult`

1. `outdir/<slug>/` (default `manual_tests/<slug>/` next to the repo, gitignored); `--clean` wipes it.
2. Write `players/<slug>.yaml` — slot 1 is this world, with `options`, `start_inventory`,
   `plando_items`; then one YAML per `companions` entry.
3. Enter the forced-starting-room context (3.3) if `starting_room` is set.
4. Call `Generate.main()` **in-process** (`Generate.main(argv)` returns `(args, seed)`), with
   `--player_files_path players --outputpath out --seed <test.seed> --spoiler 3 --plando items
   --outputname <slug>`. In-process rather than a subprocess so the monkeypatch in 3.3 applies;
   `--plando items` means no host.yaml edit is needed to enable plando.
   `test_fill.py` already proves this style of in-process generation works here.
5. From `out/<slug>.zip`: keep the zip (that is what `MultiServer.py` hosts), extract the
   `.apmp2` and the spoiler log into `outdir/<slug>/`.
6. `sha256(config.json)` from the `.apmp2`; compare to `test.config_sha256` and fail with a diff
   summary on mismatch (`--repin` prints the new value to paste into the script).
7. `patch_iso_with_ap(apmp2, iso, cosmetics_dict(settings))` -> `<slug>.iso`
   (skipped with `--no-patch`; `patch_iso_with_ap` no-ops if the output exists, so `--clean`
   is what forces a re-patch). Keep the `.apmp2` and the patched `.iso` side by side with the same
   basename — that is exactly `utils.get_output_path`, so when the Launcher later starts the client
   on that `.apmp2` it finds this ISO and skips patching instead of doing the work twice.
8. Write `outdir/<slug>/INSTRUCTIONS.md` (this test's README section, with real paths filled in)
   and print it to the terminal.

CLI flags shared by every script: `--iso PATH` (defaults to host.yaml `rom_file`), `--pal`
(use the PAL ISO and tag the output dir, section 5 MT24), `--out DIR`, `--clean`, `--no-patch`,
`--verify` (build, check the hash, do not patch), `--repin`, `--print-readme`.

### 3.3 Forcing a starting room

No player option selects a *specific* room (`starting_room` only picks a pool), and several tests
are only cheap because they start you next to the thing under test. The harness therefore
monkeypatches, rather than adding a production option:

```python
@contextlib.contextmanager
def forced_starting_room(ap_name: str):
    # wraps MetroidPrime2World.generate_early: run the original, then overwrite
    # self.starting_location / self.origin_region_name and rebuild the two
    # assignments that are derived from the origin (translator gates, dock rando).
```

Notes:

* Split the name with `ap_name.split("/", 2)` — node names themselves can contain `/`
  (e.g. `Sky Temple Grounds/Sky Temple Gateway/Spawn Point/Front of Teleporter`).
* The harness asserts the node is in `db.starting_location_candidates("anywhere")` (272 nodes);
  anything else is not a legal `AreaReference` for OPR's `edit_starting_area_dol`.
* Overriding *after* `generate_early` keeps the seed's random draws identical to an unpatched run,
  so the rest of the seed stays reproducible.
* If this monkeypatch ever gets brittle, the fallback is a dev-only env var read in
  `generate_early` (`MP2_FORCE_STARTING_ROOM`). Not proposed for now — keep production code clean.

### 3.4 Presets (`presets.py`)

* `ALL_ITEMS_START` — `start_inventory` (not `_from_pool`) with every item at max count, derived
  from `items.ITEM_TABLE` so it can't drift. Leaves the pool full, so every location still holds a
  real item *and* the grant path is exercised at connect time.
* `GOD_MODE` — `energy_per_tank: 500`, 14 Energy Tanks, `defense_up_damage_reduction: 90`,
  `double_damage_multiplier: 500` + Double Damage in start inventory. For tests whose subject is
  not "can I survive".
* `FULL_MAP` — `map_visibility: full_map_and_items`, `unvisited_room_names: true`. Navigation aid.
* `NO_RANDO` — every entrance/gate rando off, `translator_gate_rando: vanilla`, so a failure
  can't be blamed on entrance shuffling.
* `FAST_RETRY` — `warp_to_start: true`, so a tester can reposition without replaying.
* `filler_slot(n)` — n `Clique` companion slots, for tests that need a second player cheaply.

### 3.5 Route/selection helpers (`routes.py`)

* `door_distance(from_area)` — BFS over `default_connection` docks; used to order a walking route
  and to prove "independent" pickups are all close to the start.
* `independent_pickups(start_area, max_distance, count)` — pickups whose rooms are within
  `max_distance` doors and where no chosen pickup's room is on the *required* path to another
  (with `ALL_ITEMS_START` active, reachability is trivially satisfied, so "independent" here means
  no shared blocking object and no shared HUD/model dedupe). Verified set within 8 doors of
  Landing Site (pickup index — location):

  ```
  0  Temple Grounds: Hive Chamber A - Pickup (Missile)
  1  Temple Grounds: Hall of Honored Dead - Pickup (Seeker Launcher)
  2  Temple Grounds: Hive Chamber B - Pickup (Missile)
  4  Temple Grounds: Windchamber Gateway - Pickup (Energy Tank)
  5  Temple Grounds: Transport to Agon Wastes - Pickup (Missile)
  6  Temple Grounds: Temple Assembly Site - Pickup (Missile)
  8  Temple Grounds: Dynamo Chamber - Pickup (Power Bomb)
  9  Temple Grounds: Storage Cavern B - Pickup (Energy Tank)
  12 Temple Grounds: Communication Area - Pickup (Missile)
  13 Temple Grounds: GFMC Compound - Pickup (Missile Launcher)
  14 Temple Grounds: GFMC Compound - Pickup 2 (Missile On Ship)
  20 Great Temple: Transport A Access - Pickup (Missile)
  21 Great Temple: Temple Sanctuary - Pickup (Energy Transfer Module)
  22 Great Temple: Transport B Access - Pickup (Missile)
  ```

  14 pickups, all in the two starting regions, none gating another. This is the standard
  "model bench" used by MT06/MT07/MT13.
* `unique_sum_pairs(missing_indices)` — wraps
  `client.location_reconciliation.find_unique_missed_locations` to pick (a) a pair of pickups whose
  index sum has exactly one explanation and (b) a pair whose sum is ambiguous. Used by MT09; the
  script prints both, so the tester doesn't have to reason about subset sums.

### 3.6 Reproducibility

* Fixed `seed` per script (never `--seed` from the clock).
* `config_sha256` pinned in the script; `--verify` is a fast (no-patch) check that the world still
  produces the same patch data for that seed. Deliberately hashing `config.json`, not the ISO —
  ISO writing is not guaranteed byte-stable.
* A pytest test (`test/test_manual_plan.py`) asserts: every `mt*.py` module loads, every `TEST`
  has a unique slug/seed, every referenced location/item/room name exists in the DB, and the
  checked-in `README.md` equals `build_readme.py`'s output. That keeps the book honest without
  ever launching a game.

## 4. Running a test (the shape every README section has)

```
1. Build      python -m worlds.metroidprime2.test.manual.<slug> --iso <vanilla.iso>
2. Host       python MultiServer.py manual_tests/<slug>/<slug>.zip
3. Connect    python Launcher.py "Metroid Prime 2 Client" manual_tests/<slug>/<slug>.apmp2 <vanilla.iso>
              (client.py has no __main__ guard, so it is started through the Launcher, not `python -m`;
               the ISO is already patched by step 1, so the client reuses it rather than re-patching)
4. Steps      <do / expect pairs>
5. Pass if    <criteria>
6. If it fails, look at <modules>
```

## 5. Test catalog

Legend: **P0** = must pass before anyone else plays this; **P1** = must pass before release;
**P2** = polish/cosmetic.

| ID | Slug | Pri | Proves |
|---|---|---|---|
| MT01 | `mt01_smoke_vanilla` | P0 | A default-options patched ISO boots, starts, saves, and reports a check. |
| MT02 | `mt02_goal_credits` | P0 | Beating the game reaches Credits, fires the sentinel, and the client/server mark the goal. |
| MT03 | `mt03_goal_sentinel_poke` | P0 | Goal *detection* alone, without the final boss (memory poke). |
| MT04 | `mt04_warp_to_start_save_station` | P0 | L+R decline warps; plain decline is vanilla; prompt shows the hint. |
| MT05 | `mt05_warp_to_start_remote_room` | P0 | Warp target follows `starting_area` into a non-save-station room. |
| MT06 | `mt06_item_models_local_route` | P0 | Every pickup class shows the right model + HUD text and grants once. |
| MT07 | `mt07_item_grant_capacities` | P0 | Cross-computed capacities (ammo, launcher, progressives) land correctly in-game. |
| MT08 | `mt08_counter_persistence` | P0 | Item 74 survives save/quit/reload and checkpoint reloads; no lost/doubled checks. |
| MT09 | `mt09_missed_checks` | P0 | Multi-pickup-while-detached reconciles (unique) and refuses to guess (ambiguous). |
| MT10 | `mt10_remote_items_reconnect` | P0 | Remote items arrive, queue, and re-sync idempotently across a client restart. |
| MT11 | `mt11_models_energy_controllers` | P1 | The 4 `custom` location_data pickups patch and grant. |
| MT12 | `mt12_models_boss_drops` | P1 | Guardian/sub-guardian drops patch and grant. |
| MT13 | `mt13_cross_game_models` | P1 | Every cross-game model (verified + experimental) loads without crashing. |
| MT14 | `mt14_death_link` | P1 | Death Link both directions in a live game. |
| MT15 | `mt15_door_lock_rando` | P1 | In-game door locks match the assignment; save rooms normalized. |
| MT16 | `mt16_elevator_rando` | P1 | Elevators go where the config says, both ways. |
| MT17 | `mt17_portal_rando` | P1 | Portals go where the config says, and one-way vanilla portals are now two-way. |
| MT18 | `mt18_translator_gates` | P1 | Gate colors/unlocked state match the assignment, incl. the relocated Hive gate. |
| MT19 | `mt19_starting_room` | P1 | Randomized starts spawn correctly, light and dark. |
| MT20 | `mt20_sky_temple_keys` | P1 | Key modes place/pre-collect correctly and the Gateway opens. |
| MT21 | `mt21_map_and_cosmetics` | P2 | Map visibility, room names, HUD color, suit skins. |
| MT22 | `mt22_combat_tuning` | P2 | Beam ammo costs, annihilator source, double damage, defense up. |
| MT23 | `mt23_session_lifecycle` | P2 | Menu/new game/load/wrong-seed/`/reconnect`/`/export_iso`. |
| MT24 | `mt24_pal_parity` | P1 | MT01/MT02/MT04 pass on a PAL ISO (different DOL addresses). |

---

### MT01 — `mt01_smoke_vanilla` (P0)

*Proves the patch pipeline produces a playable game at all.*

* Seed fixed; options: defaults + `NO_RANDO`; no forced start (vanilla Landing Site); no plando.
* Steps: patch -> boot in Dolphin -> New Game -> ship cutscene skips with Start -> walk to
  Hive Chamber A -> collect the pickup -> client logs the check, server shows it, HUD memo shows
  the item name -> save at the ship -> quit to menu -> load the save.
* Pass: no crash, check reported exactly once, HUD memo correct, save/load works.
* On failure: `client/patcher_runner.py` (DOL writes), `patch_data.py`, OPR version pin.

### MT02 — `mt02_goal_credits` (P0)

*Proves the real end-to-end goal path.*

* `starting_room` forced to **`Sky Temple/Sanctum/Door to Sanctum Access`** (a
  `valid_starting_location`, i.e. the Emperor Ing arena itself).
* `ALL_ITEMS_START` + `GOD_MODE` (so the fight is short and the escape is survivable);
  `sky_temple_keys: 9` but all 9 keys are in the start inventory.
* Steps: New Game -> you spawn in the Sanctum -> kill Emperor Ing -> escape sequence -> Dark Samus
  3 & 4 at Sky Temple Gateway -> Credits.
* Expect: within ~1s of the Credits area loading the client logs the goal, sends
  `StatusUpdate(GOAL)`, the server prints the slot as finished, and `/getitem <name>` becomes
  allowed (it is goal-gated).
* Also expect: the Credits sentinel (amount 120) is **not** mistaken for a pickup index or fed to
  the missed-check reconciler (PLAN.md section O).
* Pass: goal reported once, no spurious location checks, no client traceback.
* On failure: `patcher_runner._add_goal_trigger`, `constants.GOAL_SENTINEL_AMOUNT`,
  `client/client.py::_handle_magic_item_amount`.

### MT03 — `mt03_goal_sentinel_poke` (P0)

*Same detection, 2 minutes instead of 30 — run this first; MT02 confirms the trigger actually fires.*

* Same build as MT01 (any seed works), plus the script prints the **pointer chain** to item 74's
  amount for the detected ISO version, from `client/versions.py`:
  `player_state = *(cstate_manager_global + 0x150C)`, then `player_state + 0x5C + 74*12`.
* Steps: start a game, open Dolphin's Memory viewer, follow the chain, write `120` to the amount,
  wait one client tick.
* Expect: exactly the MT02 client-side behavior (goal reported, `/getitem` unlocked).
* Pass/fail separates "detection is broken" from "the in-ISO trigger is broken".

### MT04 — `mt04_warp_to_start_save_station` (P0)

*Proves the warp-to-start SCLY layer + DOL hook on this build.*

* `starting_room` forced to **`Temple Grounds/Hive Save Station/Save Station`** — you spawn in a
  save-station room, so the subject is one step away. `warp_to_start: true`,
  `ALL_ITEMS_START`, `NO_RANDO`.
* Steps:
  1. Spawn -> the save station is in the room. Activate it -> **expect** the prompt text to carry
     the extra line "Hold L + R while choosing No to warp to the starting room."
  2. Choose No **without** L+R -> **expect** bit-for-bit vanilla behavior (the "no save" cinematic,
     no warp, no HUD memo).
  3. Choose No **with** L+R held -> **expect** the HUD memo "Returning to starting room...",
     then a room transition ~3s later back into this same room.
  4. Walk two rooms away, come back, repeat 3 -> **expect** the same result (layer is per-room,
     not a one-shot).
  5. Travel to a *different* save station (`Temple Grounds/Landing Site/Save Station`, the ship) and
     repeat 3 -> **expect** the warp to return you to **Hive Save Station**, not the ship.
  6. Rebuild with `warp_to_start: false` (`--variant off`) -> **expect** no hint line and no warp.
* Pass: all six. On failure: `client/warp_patch.py`, `client/versions.py::WarpToStartAddresses`,
  `tools/find_warp_addresses.py` (re-derive the hook address for this build).

### MT05 — `mt05_warp_to_start_remote_room` (P0)

*Proves the warp target follows `configuration.starting_area`, not "the nearest save station".*

* `starting_room: anywhere` forced to **`Temple Grounds/Windchamber Gateway/Door to Path of Eyes`**
  (not a save-station room). `warp_to_start: true`, `ALL_ITEMS_START`.
* Steps: spawn -> note the room -> travel to the nearest save station -> decline with L+R.
* Expect: you land in Windchamber Gateway. Also confirms `can_warp_to_start`'s logic assumption
  (the 18 save rooms are the only warp sources) matches the ISO.

### MT06 — `mt06_item_models_local_route` (P0)

*Proves pickup appearance + HUD + grant for one representative of every model/sound class.*

* `NO_RANDO`, `FULL_MAP`, `ALL_ITEMS_START` (so nothing is gated), vanilla start.
* `plando_items` fills the 14 independent pickups from 3.5, one per class:
  major upgrade (Space Jump Boots), suit (Progressive Suit), beam (Dark Beam), visor (Dark Visor),
  morph upgrade (Boost Ball), charge combo (Sonic Boom), translator (Violet Translator),
  ammo expansion (Missile Expansion, Dark Ammo Expansion, Power Bomb Expansion),
  Energy Tank, Sky Temple Key 1, Energy Transfer Module, and one **other player's** item
  (needs a companion slot, generic model).
* Steps: walk the printed route; at each room, **before** touching the pickup note the model, then
  collect it.
* Expect per pickup: model matches the table the script prints; **one** HUD memo with the right
  name; client reports the location once; `/mp2_debug_inventory` matches the expected line the
  script prints; no second popup from the game's own HUD (`disable_hud_popup` is forced on in OPR,
  so a double popup means a regression).
* Pass: 14/14. On failure: `patch_data._pickup_appearance`, `OPR_MODEL_NAMES`,
  `client/notification_manager.py`.

### MT07 — `mt07_item_grant_capacities` (P0)

*Proves the client's capacity model survives contact with the real inventory — the manual-grant class
of bug (raw `gains` written straight to memory stranding a cross-computed capacity).*

* Two variants the script builds side by side (`--variant a|b`):
  * **a**: `missile_expansions_unlock_launcher: false`, `power_bomb_expansions_unlock_power_bombs:
    false`, `split_beam_ammo: true`, `progressive_suit: true`, `progressive_grapple: true`,
    `energy_per_tank: 250`.
  * **b**: both `*_unlock_*` true, `split_beam_ammo: false` (unified Beam Ammo Expansion).
* Start inventory intentionally **empty** except Scan Visor/Morph Ball defaults; the 14 independent
  rooms hold, in a printed order: 3 Missile Expansions, the Missile Launcher, 2 Power Bomb
  Expansions, the Power Bomb, 2 Energy Tanks, Progressive Suit x2, Progressive Grapple x2,
  Dark/Light (or unified Beam) Ammo Expansions.
* Steps: collect in the printed order, running `/mp2_debug_inventory` after each and comparing to
  the script's expected `amount/capacity` table (which it derives from
  `client.receive_items.compute_desired_capacities`, so the table and the code can't disagree).
* Expect: in variant a, expansions before the launcher grant capacity but **no** usable missiles
  until the launcher; in b they are usable immediately; progressive suit gives Dark then Light;
  progressive grapple gives Grapple then Screw Attack; tanks give 250 each.
* Then, after finishing the game (MT03's memory poke is the cheap way to unlock it), the client's
  goal-gated `/getitem Missile Expansion` -> expect the capacity to go **up by one expansion**, not
  to a stranded raw value; repeat with the server's own `!getitem` for the non-goal-gated path.
* On failure: `client/receive_items.py`, `client/client.py::_handle_grant_items`.

### MT08 — `mt08_counter_persistence` (P0)

*Proves the two DOL table writes (`powerup_should_persist[74]`, `powerup_max[74] = 65536`).*

* Build like MT06 but with only 3 plando'd pickups, all within two rooms of a save station.
* Steps:
  1. Collect pickup 1 with the client attached -> reported.
  2. **Close the client.** Collect pickup 2. Save at the station. Quit to the main menu. Reload the
     save. Reopen the client and connect -> **expect** pickup 2 to be reported now (the counter
     survived the save) and the inventory to be rebuilt from `ReceivedItems` without duplicates.
  3. With the client attached, collect pickup 3, then die before saving and reload the checkpoint
     -> **expect** no double credit, no lost check, and the item still in inventory (it comes from
     the server, not the save file).
* On failure: `patcher_runner.patch_iso_with_ap`'s pre-`_apply_patches` DOL writes,
  `dol_versions` offsets for this build.

### MT09 — `mt09_missed_checks` (P0)

*Proves `client/location_reconciliation.py` against the real counter (new code, never played).*

* Build like MT08. The script prints two room pairs it has computed with `unique_sum_pairs`:
  a **unique-sum** pair and an **ambiguous-sum** pair.
* Steps:
  1. Close the client. Collect both pickups of the *unique* pair. Reopen the client -> **expect**
     both locations credited, a log line naming them, and both items granted.
  2. Repeat with the *ambiguous* pair -> **expect** a warning that the amount can't be explained,
     **no** locations credited, and no crash; then verify the documented recovery (collect any
     further pickup / use the server's `!collect`-style release, whichever the client supports).
  3. Sanity: a single pickup while detached still credits normally.
* On failure: `client/location_reconciliation.py`, `client.py`'s magic-amount handler.

### MT10 — `mt10_remote_items_reconnect` (P0)

*Proves the live receive loop.*

* Two slots: this world + a `Clique` companion whose item pool is filled with MP2 items via plando
  (or simply use `!getitem`-style server commands from the console, whichever is less fragile —
  the script prints the exact `/send` console commands to use).
* Steps: while in-game, send 5 items from the server console in quick succession -> expect 5 HUD
  memos, correctly spaced (4s cooldown), all 5 granted. Send an item while a cutscene is playing
  and while in the pause menu -> expect it to queue and land after. Kill the client mid-run and
  restart it -> expect a silent idempotent re-sync (no re-granting spam, no duplicate HUD).
* On failure: `receive_items.plan_grants`, `notification_manager.py`, `client.py` sync task.

### MT11 — `mt11_models_energy_controllers` (P1)

*The four `custom` `location_data` pickups (indices 23, 46, 82, 116) are patched by a different OPR
path than the 115 standard ones.*

* `--which violet|amber|emerald|cobalt` builds a seed whose start is forced next to that
  controller (e.g. violet -> `Great Temple/Main Energy Controller/Door to Controller Transport`),
  with `ALL_ITEMS_START`; plando puts a **major** item (not the vanilla translator) in the slot so a
  wrong model is obvious.
* Expect: the room loads, the pickup renders, HUD + grant correct.

### MT12 — `mt12_models_boss_drops` (P1)

* One guardian (43, Dark Agon Temple / Dark Suit slot) and one sub-guardian (38, Agon Temple /
  Morph Ball Bomb slot); `ALL_ITEMS_START` + `GOD_MODE`, start forced next to the arena.
* Expect: boss dies, drop appears with the plando'd item's model, collect -> HUD + grant + check.

### MT13 — `mt13_cross_game_models` (P1)

*The highest-risk cosmetic path: `VariaSuit` once crashed the game, and the experimental table is
explicitly unverified.*

* Companion slots for Metroid Prime, Metroid: Zero Mission, Metroid Fusion, Super Metroid
  (generation only — no ROMs needed to generate), `display_nonlocal_items: match_game`.
* Plando the *whole* `_VERIFIED_CROSS_GAME_ITEM_NAMES` + `_EXPERIMENTAL_CROSS_GAME_ITEM_NAMES` set
  across the 14 independent rooms plus additional near-start rooms as needed; the script prints
  room -> (source game, item, expected MP2 model).
* Steps: **walk into every room** (crashes happen on area load, before you collect anything), then
  collect each.
* Expect: no crash, each model as printed, unmapped items fall back to the generic model.
* On failure: move the offending entry out of `_EXPERIMENTAL_CROSS_GAME_ITEM_NAMES` (as that
  table's comment instructs) rather than reverting the feature.

### MT14 — `mt14_death_link` (P1)

* Two MP2 slots (or MP2 + any Death Link game), both `death_link: true`.
* Steps: `/test_deathlink outgoing` -> other slot dies. `/test_deathlink incoming` -> you die.
  Then a *real* death (run into Dark Aether damage with no suit) -> other slot dies. Verify no
  death loop (receiving a death while already dead / during the death animation).

### MT15 — `mt15_door_lock_rando` (P1)

* `door_lock_rando: true`, fixed seed, `ALL_ITEMS_START`, start at Landing Site.
* Script prints, from the generated `config.json`, the expected lock for every door in the first
  ~10 rooms, plus every Save Station room's doors under `normal_save_station_doors: true` and a
  second build with it `false`.
* Expect: colors/blast shields match; with the option on, every save room door (and its far face)
  is a Normal Door, including rooms that vanilla ships with a Missile Blast Shield or Dark Door.

### MT16 — `mt16_elevator_rando` (P1)

* `elevator_rando: true`. Script prints the elevator mapping table.
* Steps: ride every Temple Grounds/Great Temple elevator and the return trip.
* Expect: destinations match; return trips land back where you left; the Sky Temple one-way and the
  intra-Aerie elevator are untouched.

### MT17 — `mt17_portal_rando` (P1) — *flagged "needs testing" in README.md*

* `portal_rando: true`. Script prints the portal mapping.
* Steps: take every portal in the Temple Grounds / Sky Temple Grounds pair, then one more region
  pair; take each in **both** directions, including a vanilla arrival-only portal.
* Expect: destination matches; the return portal exists and works; beam-color requirement unchanged.

### MT18 — `mt18_translator_gates` (P1)

* `translator_gate_rando: full_random_unlocked`, all translators + Scan Visor in start inventory.
* Script prints gate -> assigned color (or Unlocked), including the OPR-relocated
  `hive_access_tunnel_translator_gate` (the one that caused the prime2_opr resync).
* Steps: scan each gate in Temple Grounds/Great Temple; check at least one in each other region.
* Expect: color matches; Unlocked gates open with Scan alone; the relocated Hive gate guards the
  Hive Chamber A hole (not the corridor), and a fresh vanilla-options start is not softlocked.

### MT19 — `mt19_starting_room` (P1)

* Three builds: `--pool save_stations`, `--pool anywhere` (forced to a light room),
  `--pool anywhere --dark` (forced to a dark room, `starting_room_light_world_only: false`).
* Expect: New Game spawns in the room the spoiler names; the dark start immediately takes Dark
  Aether damage and is survivable to the nearest safe zone with the start inventory the option
  implies; saving and reloading returns you there.

### MT20 — `mt20_sky_temple_keys` (P1)

* `--mode 9|all_bosses|all_guardians|0`. `ALL_ITEMS_START` minus keys; start forced to
  `Sky Temple Grounds/Sky Temple Gateway/Spawn Point/Front of Teleporter`.
* Expect: the Gateway refuses entry until the mode's key count is held, then opens; in
  `all_guardians`, the pre-collected keys are already in inventory at New Game; key items show the
  right model where they are placed.

### MT21 — `mt21_map_and_cosmetics` (P2)

* `map_visibility: full_map_and_items`, `unvisited_room_names: true`, host.yaml `hud_settings.color`
  custom + a non-default `suit_settings`.
* Expect: every room drawn from New Game, an item dot at every location, room names shown before
  visiting, HUD tinted, suit model swapped. Second build with `map_visibility: vanilla` to confirm
  the difference is actually the option.

### MT22 — `mt22_combat_tuning` (P2)

* `beam_ammo_costs: free` / `expensive`, `annihilator_ammo_source: dark_only`,
  `double_damage_multiplier: 500`, `defense_up_damage_reduction: 90`.
* Expect: ammo drain per shot matches; Annihilator consumes only Dark ammo; damage taken in Dark
  Aether visibly lower; Double Damage (start inventory) hits harder.

### MT23 — `mt23_session_lifecycle` (P2)

* One build, plus a *second* build of a different seed for the wrong-seed check.
* Steps: connect the client while Dolphin is at the main menu (expect `IN_MENU`); start a New Game
  (expect `IN_GAME`); load the *other* seed's ISO (expect `WRONG_SEED`); stop and restart emulation
  then `/reconnect`; `/export_iso` with the game closed (expect a re-patch) and with it open
  (expect a refusal); `/status`, `/test_hud`, `/mp2_debug_inventory`.

### MT24 — `mt24_pal_parity` (P1)

* Not a separate build: a README section that says to re-run **MT01, MT03, MT04, MT08** with
  `--pal`. These are the tests whose subjects are per-build DOL addresses
  (warp hook, `powerup_should_persist`/`powerup_max`, goal sentinel).
* Expect: identical results on the PAL ISO; any difference means `client/versions.py` or
  `find_warp_addresses.py` needs a PAL-specific fix.

## 6. The README (`metroidprime2/test/manual/README.md`)

Generated by `build_readme.py` from the `TEST` objects, so it can never drift from the scripts.
Structure:

1. **Prerequisites** — MWGG source checkout + venv, a vanilla NTSC-U (and ideally PAL) ISO,
   Dolphin with the memory engine reachable, `host.yaml` `metroidprime2_options.rom_file` and
   `emulator_settings.executable_path` set, `SKIP_REQUIREMENTS_CHECK` / `ppc_asm>=1.9.0` note.
2. **How to run any test** — the 6-line shape from section 4.
3. **Results table to copy** — ID / date / ISO version / pass-fail / notes, so a run can be pasted
   into a PR or issue.
4. **One section per test**, in catalog order, each: title, priority, *proves*, build command,
   what the build contains (start room, options, placements — rendered from the spec, not
   hand-written), numbered do/expect steps, pass criteria, and where to look on failure.
5. **Suggested runs** — "smoke" (MT01, MT03, MT06), "pre-release" (all P0+P1), "cosmetics" (P2).

## 7. Prerequisites, risks, open questions

* **Generation cost.** Each build is a full generate + a full ISO patch (minutes). Builds are
  cached by output directory; `--no-patch` is there for iterating on the spec itself.
* **Plando needs `--plando items`** — the harness passes it, so no host.yaml change is needed.
* **`ALL_ITEMS_START` uses `start_inventory`, not `start_inventory_from_pool`**, so locations keep
  holding real items (needed by MT06/MT07) and the grant path is exercised at connect.
* **Forced starting rooms are a monkeypatch** (3.3). If a future MWGG version makes that fragile,
  fall back to a dev-only env var; noted, not implemented.
* **MT02 is long** (final boss + escape). MT03 exists so a broken *detector* is caught in minutes;
  MT02 is the one that proves the in-ISO trigger.
* **MT09's ambiguous case** needs a documented recovery path. If there isn't one today, the test's
  real finding is "we need one" — worth deciding before implementing the script.
* **MT13 may crash the game by design.** Run it last in a session and note which entry crashed.
* **PAL ISO availability** — `echoes-pal.iso` is present in the repo root, so MT24 is runnable.
* Not covered here (data-only, already unit-tested, and cheaper to keep there): trick levels,
  damage strictness math, item pool composition, fill success rates.

## 8. Implementation order

1. `harness.py` + `presets.py` + `routes.py` + `build_readme.py` + `test_manual_plan.py`.
2. MT01, MT03 (fastest feedback loop; validates the harness end to end).
3. MT04, MT05, MT06, MT07, MT08, MT09, MT10 (the rest of P0).
4. MT02 (long, but the one that closes out the goal milestone), then MT24.
5. P1 (MT11-MT20), then P2 (MT21-MT23).
