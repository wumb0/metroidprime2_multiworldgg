# Port Metroid Prime 2: Echoes randomization from Randovania to MultiWorldGG

## Context

The goal is a MultiWorldGG (Archipelago fork) world for Metroid Prime 2: Echoes so it can join a multiworld with other games. Randovania owns the game knowledge (logic database, pickup database, patch-data export, in-game connector); open-prime-rando (OPR) is the game-file patcher. MultiWorldGG already ships a Metroid Prime 1 world (`MultiWorldGG/worlds/metroidprime`) whose architecture (patch config in a player container, ISO patched client-side, Dolphin memory client that grants every item) is the template to copy.

Repos in `/Users/wumb0/Projects/prime2mwgg` (all three gitignored; the new world dir is the tracked content of this repo):

| Repo | Version | Role |
|---|---|---|
| `MultiWorldGG/` | 0.7.267, Python 3.12/3.13 | framework; `worlds/metroidprime` is the template |
| `randovania/` | v10.10.0-251 (logic DB schema 34) | source of logic DB, pickup DB, exporter + connector reference |
| `open-prime-rando/` | v0.20.1-20 (pin PyPI `open-prime-rando==0.20.1`) | patcher `open_prime_rando.echoes.patcher.patch_iso`, DOL addresses, remote-execution primitives |

### Decisions made with the user
1. **World location**: `/Users/wumb0/Projects/prime2mwgg/metroidprime2/`, symlinked as `MultiWorldGG/worlds/metroidprime2` (`ln -s ../../metroidprime2 MultiWorldGG/worlds/metroidprime2`).
2. **Item delivery**: "client grants everything" (Prime 1 model). Every in-ISO pickup grants only the multiworld magic counter (item 74, amount `pickup_index + 1`); the client grants all items, own and remote, from `ReceivedItems` (`items_handling = 0b111`), recomputed idempotently every tick.
3. **v1 scope**: item shuffle with randovania logic + trick options, Sky Temple Key modes, progressive suit/grapple, starting inventory, damage strictness, death link, door lock/elevator/teleporter randomization (`logic/dock_rando.py`, each behind its own Toggle option; see section E.1), and translator gate color randomization (`logic/translator_gate_rando.py`, a `translator_gate_rando` Choice option; see section E.2). Vanilla starting room.
4. **Patcher**: OPR's new `patch_iso` path (ISO in, ISO out via `nod_rs`), run client-side. Not the legacy Claris `Randomizer.exe` path (C#/mono binaries MultiWorldGG does not ship). NTSC-U and PAL GameCube ISOs only (OPR limitation).
5. **Logic source**: randovania `games/prime2` logic database (the stable game; `prime2_opr` is the experimental fork), copied verbatim into the world and parsed by a small reader in the world. No randovania import at runtime.

   > **Update (prime2_opr resync).** This decision was reversed: `tools/sync_randovania_data.py` now vendors from `games/prime2_opr` instead, because open-prime-rando's actual patcher unconditionally applies several hardcoded "rebalance" patches (`open_prime_rando.echoes.specific_area_patches.rebalance_patches`) that move or re-gate specific vanilla objects -- e.g. `hive_access_tunnel_translator_gate` physically relocates the Hive Access Tunnel translator gate to guard the Hive Chamber A hole instead of the corridor to Hive Transport Area, regardless of `translator_gate_rando`. The plain `prime2` DB doesn't know about any of these and silently disagreed with the real, patched topology for every room such a patch touches -- caught via a live in-game softlock at the very start of a fresh game under fully vanilla options. `prime2_opr` is randovania's OPR-accurate game definition and already encodes all of them. Fallout from the resync (a real sphere-0 total lockout from two translator gates whose vanilla requirement this world was still reading from the wrong DB field, plus `teleporter_rando` turning out to be unimplementable against `prime2_opr`'s data) is covered in section E.1's update note and `logic/translator_gate_rando.py`/`logic/regions.py`'s docstrings; `data/vanilla_translator_gates.json` (vendored from randovania's `prime2_opr` starter preset) is now the authoritative per-gate vanilla-color source instead of the DB node's own `extra.vanilla_color` field.

### Facts verified in source that drive the design
- Logic DB: 10 region files, 1109 nodes (674 dock, 152 generic, 119 pickup, 116 event over 111 event names, 31 hint, 17 configurable_node). Requirement types: `and`, `or`, `resource`, `template` (no `node`). Resource types: `items`, `tricks`, `events`, `damage`, `misc`, `versions`. Reader: `randovania/game_description/data_reader.py`.
- Victory: `Event93` "Dark Samus 3 and 4". The reachable event node is `Sky Temple Grounds/Sky Temple Gateway/Event - Dark Samus 3 and 4` (incoming from `Elevator to Sky Temple`); the `Temple Grounds/Credits/...` copy has no connections. Goal = `state.has(event_item)`, not region reachability.
- Only `door` dock weaknesses have locks, all `front-blast-back-free-unlock`. 15 docks have `override_default_lock_requirement`, none override open. Impossible weaknesses (`or []`): `Permanently Locked`, `No Return Portal`, `Not Determined`.
- Translator gates (`configurable_node`) and hint nodes: all OUTGOING connections additionally require the node's requirement (`randovania/graph/world_graph_factory.py::_connections_from`, `requirement_to_leave`). Gate requirement = `Scan AND <translator item from extra.vanilla_actual>`.
- Dark regions have no MLVL `asset_id`; follow `extra.associated_region` (see `randovania/games/prime2_opr/exporter/patch_data_factory.py::_asset_id_for_region`). Every area has an MREA `extra.asset_id`. Every pickup node has `extra.location_data` (115 `standard`, 4 `custom`: indices 23, 46, 82, 116). Boss tags `extra.boss`: guardians 43, 79, 115; sub-guardians 37, 38, 75, 86, 88, 102.
- Randovania bootstrap (`randovania/games/prime2/generator/bootstrap.py`): energy = `energy_per_tank - 1 + energy_per_tank * tanks`; `DarkWorld1` reductions replaced by `[(none, varia_suit_damage/6), (DarkSuit, dark_suit_damage/6), (LightSuit, 0.0)]`; damage amount `int(amount * damage_strictness)` then passes iff `ceil(reduction * amount) < energy`; trick requirement amount N satisfied iff configured level >= N (0 disabled .. 5 ludicrous). Pre-granted events with the new patcher: Event2, Event4, Event71, Event78, Event73, Event75.
- OPR `patch_iso` (`open-prime-rando/src/open_prime_rando/echoes/patcher.py:444`) = `IsoFileProvider` + `PatcherEditor` + `IsoFileWriter` + `_apply_patches(...)` + `output.commit(...)`. `_apply_patches` ends with `editor.save_modifications(output)` which writes `editor.dol` into the output, so DOL writes made before `_apply_patches` land in the ISO.
- OPR does NOT persist item 74 (`echoes/custom_items/__init__.py`, `PersistentCounter8` commented out) and sets no `powerup_max` for it. `powerup_should_persist` is a 109-byte table, `powerup_max` a 109 x u32 table (`dol_patching/echoes/dol_versions.py`).
- OPR's Defense Up patch reuses **item 12 (Varia Suit)** as its counter (`powerup_max[12] = max_count`, default 1; multiplier 0.0). Always give Varia capacity exactly 1, keep `custom_items` at defaults.
- OPR hardcodes `disable_hud_popup = True`; pickup HUD memo STRG name is derived from `hud_text` so identical texts dedupe (no collision).
- Remote execution (`dol_patching/all_prime_dol_patches.py`): body budget 420 bytes (`create_remote_execution_body` raises `ValueError` if too big); player state = `*(cstate_manager_global + 0x150C)`; CPlayer vtable check `*(cstate+0x14FC)`; pending-op flag byte `cstate + 0x2`; current MLVL u32 at `*(game_state_pointer) + 4`; inventory 109 entries x 12 bytes at `player_state + 0x5C` (amount u32, capacity u32, pad).
- Randovania pickup DB model names absent from OPR `PICKUP_MODELS`: `CoinChest`, `ScanVisor INCOMPLETE`, `VariaSuit INCOMPLETE`, `ChargeBeam INCOMPLETE` (mapping table in section F).
- Prime 1 pieces confirmed reusable: `DolphinClient.py`, `NotificationManager.py`, `Container.py` pattern, `MetroidPrimeClient.py` structure (UT try/except import, `dolphin_sync_task`, `patch_and_run_game`, LauncherComponents registration), `ClientReceiveItems.py` idempotent recompute, `PrimeSettings.py`, `PrimeOptions.py` OptionGroups, `PrimeUtils.setup_libs`.

---

## A. File layout (`metroidprime2/`)

```
metroidprime2/
  __init__.py              MetroidPrime2World(World), WebWorld, Component registration (.apmp2), icon path
  archipelago.json         {"game": "Metroid Prime 2: Echoes", "authors": [...], "world_version": "0.1.0",
                            "minimum_ap_version": "0.6.3"} (version/compatible_version are injected by "Build APWorlds"; test_world_manifest forbids them in source)
  requirements.txt         open-prime-rando[nod]==0.20.1 ; dolphin-memory-engine>=1.3.0 ; ppc-asm>=1.9.0
  version.txt              apworld version string, bare digits ("0.1.0") -- must equal archipelago.json's
                           world_version (test_version.py asserts it; MultiWorldGG's own test_world_version
                           rejects a leading "v"). Read only via utils.get_apworld_version()
  constants.py             GAME_NAME, ITEM_ID_BASE=5033000, LOCATION_ID_BASE=5033200, DEFAULT_STARTING_ITEMS,
                           PREGRANTED_EVENTS, STATIC_MISC, STATIC_VERSIONS, MAGIC_ITEM=74, asset ids (Temple Grounds MLVL,
                           Landing Site MREA, Credits MREA 1393588666, Sky Temple Gateway), OPR_MODEL_NAMES frozen list
  options.py               MetroidPrime2Options dataclass + OptionGroups
  options_tricks.py        GENERATED by tools/sync_randovania_data.py: 25 trick Choice classes + TRICK_OPTION_NAMES
  settings.py              MetroidPrime2Settings (host.yaml group `metroidprime2_options`)
  items.py                 ITEM_TABLE, item groups, MetroidPrime2Item
  locations.py             LOCATION_TABLE from DB pickup nodes, location groups, MetroidPrime2Location
  item_pool.py             create_item_pool(world), STK modes, key pre-placement, starting inventory
  logic/db_reader.py       dataclasses + load_game_database() (lru_cache; importlib.resources)
  logic/item_mapping.py    DB item short_name -> AP count expression
  logic/requirements.py    RequirementCompiler (JSON requirement -> closure, constant folding), StaticContext
  logic/regions.py         create_regions(world); dock_target(world, node), dock_weakness_for(world, db, node), translator_gate_requirement(world, node)
  logic/dock_rando.py      build_dock_rando_assignment(world) -> DockRandoAssignment, consulted by both regions.py and patch_data.py (section E.1)
  logic/translator_gate_rando.py  build_translator_gate_assignment(world) -> {gate NodeId: color|None}, consulted by both regions.py and patch_data.py (section E.2)
  patch_data.py            make_rando_configuration(world) -> dict (OPR RandoConfiguration JSON minus client-time cosmetics)
  container.py             MetroidPrime2Container(APPlayerContainer) ".apmp2": config.json + options.json
  client/dolphin_client.py        copy of worlds/metroidprime/DolphinClient.py
  client/notification_manager.py  copy of worlds/metroidprime/NotificationManager.py
  client/versions.py       NTSC/PAL address table copied from OPR dol_versions (importable without OPR)
  client/game_interface.py EchoesInterface: connect, version+uuid detection, inventory, remote execution, HUD, magic item
  client/receive_items.py  compute_desired_capacities(), sync_inventory()
  client/patcher_runner.py patch_iso_with_ap(): OPR patch + item-74 DOL fixes + goal trigger
  client/client.py         MetroidPrime2Context, command processor, dolphin_sync_task, main()
  utils.py                 setup_libs (Prime 1 pattern), get_output_path, get_apworld_version -- the single
                           apworld-version accessor; __init__.py imports it rather than defining its own copy
  data/__init__.py         load_json(relative) via importlib.resources (works inside .apworld zip)
  data/logic_database/     header.json + 10 region .json (compacted copies)
  data/pickup_database.json, data/RANDOVANIA_VERSION.txt
  docs/en_Metroid Prime 2 Echoes.md, docs/setup_en.md
  assets/icon.png, assets/__init__.py
  tools/sync_randovania_data.py   (excluded from the apworld zip)
  test/__init__.py, test/bases.py (MP2TestBase(WorldTestBase)), test_db_reader.py, test_requirements.py,
       test_regions.py, test_pool.py, test_items_locations.py, test_patch_data.py, test_client_receive.py,
       test_game_interface.py, test_deathlink.py, test_dock_rando.py, test_translator_gate_rando.py,
       test_fill.py (real distribute_items_restrictive matrix, section K), test_version.py
```

Per MultiWorldGG rules: `world_version` only in `archipelago.json` (setting it in the class raises); `settings_key` auto-derives from the folder name; `origin_region_name = "Temple Grounds/Landing Site/Save Station"` as a class attribute.

---

## B. Data pipeline: `tools/sync_randovania_data.py`

`main(randovania_root: Path, out_dir=<world>/data)`:
1. Read `<rv>/randovania/games/prime2/logic_database/header.json`; assert `schema_version == 34` and `game == "prime2"`.
2. Copy `header.json` and each file in `header["regions"]` to `data/logic_database/`, compact JSON (`separators=(",", ":")`). Strip: node `description` -> `""`, requirement `comment` -> `null`, `hint_feature_database` -> `{}`, `hint_features` -> `[]`, `minimal_logic` -> `null`, `dock_type_database.types[*].weakness_distributor` -> `null`. Keep `used_trick_levels` and trick `description` (option docstrings). Do not copy the `.txt` files.
3. Copy `pickup_database/pickup-database.json` -> `data/pickup_database.json` (strip `offworld_models`, `hint_features`).
4. Write `data/RANDOVANIA_VERSION.txt` from `git -C <rv> describe --tags`.
5. Generate `options_tricks.py` from `resource_database.tricks` (section G).
6. Print counts; assert 119 pickup nodes.

Runtime loading (`data/__init__.py`): `load_json(relative)` using `importlib.resources.files(__package__).joinpath(relative).open("rb")`, `lru_cache`d. `load_game_database()` is also cached so the parse happens once per process regardless of player count.

---

## C. Logic-DB reader (`logic/db_reader.py`)

Fields consumed (everything else ignored):

```python
@dataclass(frozen=True)
class NodeId: region: str; area: str; node: str
    ap_name -> f"{region}/{area}/{node}"

ItemResource(short_name, long_name, max_capacity, item_id: int|None)       # items[*].extra.item_id (>=1000 = pseudo)
TrickResource(short_name, long_name, description)
DamageReduction(item_short_name: str|None, quantity: int, multiplier: float)
DockWeakness(dock_type, name, requirement: dict, lock_requirement: dict|None, lock_type: str|None, door_type: str|None)

Node(id, node_type, heal, coordinates, connections: dict[str, dict],
     dock_type, default_connection: NodeId|None, default_dock_weakness, override_default_open_requirement,
     override_default_lock_requirement,
     pickup_index, location_category, location_data: dict|None, boss: str|None,
     event_name, gate_index, vanilla_actual, hint_kind, requirement_to_collect,
     teleporter_instance_id, scan_asset_id, dock_name)
Area(name, region, asset_id, default_node, nodes)
Region(name, asset_id: int|None, associated_region: str|None, areas)
GameDatabase(items, events: dict[short,long], tricks, damage, versions, misc, requirement_templates,
             damage_reductions: dict[damage_name, list[DamageReduction]], energy_tank_item,
             dock_weaknesses: dict[(dock_type, name), DockWeakness], regions, victory_condition, starting_location)
    node(id), all_nodes(), pickup_nodes() (sorted, asserts 0..118 contiguous), mlvl_for_region(name)
```

Validation on load: every `default_connection` resolves; every `default_dock_weakness` exists; every referenced template exists; pickup indices == `range(119)`.

---

## D. Requirement compiler (`logic/requirements.py`)

```python
Rule = Callable[[CollectionState], bool]
class Impossible(Exception): ...           # subtree folded to constant False
# constant True is returned as None ("no rule needed")

@dataclass
class StaticContext:
    player: int
    trick_levels: dict[str, int]           # short_name -> 0..5
    misc: dict[str, int]                   # SafeZone=1, DarkWaterJump=0, RoomRando=0, DoorRando=0, Drops=0,
                                           # VanillaGreatTempleEmeraldGate=1, VanillaDarkBeam/LightBeam/Seekers/Echo/SA/Gravity/Boost/Spider/DarkVisor=1
    versions: dict[str, int]               # NTSC=1, PAL=0, Japan=0, Trilogy=0
    pregranted_events: frozenset[str]      # Event2, Event4, Event71, Event78, Event73, Event75
    damage_strictness: float               # 1.0 / 1.5 / 2.0
    energy_per_tank: int
    dark_world_base: float                 # dark_aether_damage / 6.0
    dark_suit_multiplier: float            # dark_suit_damage / 6.0
    progressive_suit: bool; progressive_grapple: bool
    absent_items: frozenset[str]           # DB items never obtainable this seed -> constant False

class RequirementCompiler:
    def __init__(self, db: GameDatabase, ctx: StaticContext)
    def compile(self, req: dict) -> Rule | None          # raises Impossible
    def compile_all(self, reqs: list[dict | None]) -> Rule | None   # AND of several
    def compile_to_string(self, req: dict) -> str        # debug pretty-print with folded constants
```

Algorithm (`_compile`), no DNF expansion:
- `and`: compile children, drop `None`; any `Impossible` -> raise; 0 left -> `None`; 1 -> it; else `lambda s, fs=tuple(fs): all(f(s) for f in fs)`.
- `or`: compile children catching `Impossible` per child; any `None` child -> `None`; 0 left -> raise `Impossible`; 1 -> it; else `any(...)`.
- `template`: compile `db.requirement_templates[name]` with a memo dict and recursion guard (templates nest: `Open Normal Door` -> `Shoot Any Beam` -> `Shoot Dark Beam`).
- `resource` by `data.type`:
  - `tricks`: constant `ctx.trick_levels[name] >= amount` (negate inverts).
  - `misc` / `versions`: constant from ctx.
  - `events`: pregranted -> True (negated -> False); negated -> **True** (policy below); else `lambda s: s.has(event_item_name(name), player)`.
  - `items`: negated -> **False**; else expression from `item_mapping` (`kind in {"bool","count","const"}`; `amount == 1` on a bool item emits `state.has` directly).
  - `damage`: closure per model below (assert never negated).
- Closures capture values through default args; constant subtrees create no closures.

Negation policy (record in code comments): negated misc/version/trick are folded as constants (86 leaves, e.g. `not RoomRando` -> True). Negated events (~60 edges such as `not Event40` Grapple Guardian, `not Event26` Dark Forgotten Bridge rotated) fold to **True**: AP state is monotonic, folding to False would delete the only pre-fight route into several boss arenas; folding to True is over-permissive only after the event fires, which cannot make a seed unbeatable. Keep `NEGATED_EVENT_OVERRIDES: dict[str, bool] = {}` for tuning. Negated items (`LightSuit` x7, `SpaceJump` x2, `Gravity` x1) fold to **False**: each guards a trick alternative inside an `or` that has item-positive alternatives.

Item mapping (`logic/item_mapping.py`); `C(x)=state.count(x, player)`, `H(x)=state.has(x, player)`:

| DB item | AP expression |
|---|---|
| Power, Charge, Combat, Scan, Varia, MorphBall | `H("Power Beam")` etc. (default starting; precollected) |
| Dark, Light, Annihilator, Supers, Darkburst, Sunburst, SonicBoom, DarkVisor, Echo, Boost, Spider, Bombs, SpaceJump, Gravity, Seekers, Violet/Amber/Emerald/Cobalt | `H(<AP item name>)` |
| DarkSuit / LightSuit | `H("Dark Suit") or C("Progressive Suit") >= 1` / `H("Light Suit") or C("Progressive Suit") >= 2` |
| Grapple / ScrewAttack | `H("Grapple Beam") or C("Progressive Grapple") >= 1` / `H("Screw Attack") or C("Progressive Grapple") >= 2` |
| MissileLauncher | `H("Missile Launcher")` |
| Missile | `0 if not H("Missile Launcher") else 5 * (1 + C("Seeker Launcher") + C("Missile Expansion"))` |
| PowerBomb | `0 if not H("Power Bomb") else 2 + C("Power Bomb Expansion")` |
| DarkAmmo | `50*C("Dark Beam") + 20*C("Dark Ammo Expansion") + 200*C("Beam Ammo Expansion")` |
| LightAmmo | `50*C("Light Beam") + 20*C("Light Ammo Expansion") + 200*C("Beam Ammo Expansion")` |
| EnergyTank | `C("Energy Tank")` |
| TempleKey1..9 | `H(f"Sky Temple Key {n}")` |
| AgonKey/TorvusKey/HiveKey 1..3 | `H("Dark Agon Key n")` / `H("Dark Torvus Key n")` / `H("Ing Hive Key n")` |
| Percent, Multiworld, ETM, ObjectCount, Health, Temporary1/2, ChargeCombo | constant 0 (assert never required by logic) |
| DoubleDamage, UnlimitedMissiles, UnlimitedBeamAmmo, CannonBall | `H(name)` but in `absent_items` -> False (not in v1 pool) |

Damage model (`data.type == "damage"`, names `Damage`, `DarkWorld1..3`, `Poison`):
```python
amt = int(amount * ctx.damage_strictness)
reductions = db.damage_reductions.get(name, [])   # DarkWorld1 replaced at compile time by
                                                  # [(None, dark_world_base), ("DarkSuit", dark_suit_multiplier), ("LightSuit", 0.0)]
def rule(s):
    mults = [r.multiplier for r in reductions if r.item is None or item_count(r.item)(s) >= r.quantity]
    reduction = min(mults) if mults else 1.0
    energy = (E - 1) + E * s.count("Energy Tank", player)
    return math.ceil(reduction * amt) < energy
```
`amt == 0` -> True. Plain `Damage` with no reductions -> pure Energy Tank threshold closure.

---

## E. Region builder (`logic/regions.py`)

`create_regions(world)` steps:
1. `db = load_game_database()`; `ctx = build_static_context(world.options, world.player)`; `compiler = RequirementCompiler(db, ctx)`.
2. One `Region(node.id.ap_name)` per node except the dangling `Temple Grounds/Credits/Event - Dark Samus 3 and 4`. Hint nodes get regions but no locations. `multiworld.regions.extend(...)`.
3. Node-level leave requirement: `configurable_node` -> `translator_gate_requirement(world, node)` returning `{"and": [Scan>=1, <color translator>>=1]}`, or just `{"and": [Scan>=1]}` for an "Unlocked" gate (single override point for gate rando; see section E.2). The color/None per gate comes from `world.translator_gate_assignment` when `translator_gate_rando` reassigned it, else falls back to `extra.vanilla_color` (matching randovania's starter preset); the patch data must then emit a translator-gate change for all 17 gates so the game matches (2 gates check a different translator than `extra.vanilla_actual` even at vanilla settings); `hint` -> `node.requirement_to_collect`; else `None`.
4. Intra-area connections: for each `(target, req)` in `node.connections`: `rule = compiler.compile_all([req, leave_req])`; on `Impossible` skip; else `src.connect(dst, name=f"{src} -> {dst}", rule=rule)`.
5. Dock connections: `target = dock_target(world, node)` (vanilla `default_connection`, unless `world.dock_rando.elevator`/`.teleporter` reassigned it -- section E.1); `weakness = dock_weakness_for(world, db, node)` (vanilla `db.dock_weaknesses[(dock_type, default_dock_weakness)]`, unless `world.dock_rando.door_lock` reassigned it); `open = override_default_open_requirement or weakness.requirement`; `lock = (override_default_lock_requirement or weakness.lock_requirement)` if the weakness has a lock -- **both overrides only apply when `weakness.name == node.default_dock_weakness`** (i.e. door lock rando left this node at its vanilla weakness): a node-specific override was authored against that *specific* vanilla weakness's geometry/trick (e.g. one Seeker Launcher Blast Shield's particular sequence break) and doesn't carry over once door lock rando reassigns the node elsewhere. All Echoes locks are `front-blast-back-free-unlock` (randovania `world_graph_factory._create_dock_connection`): crossing from the back is free and the lock stays broken afterwards. So: for a locked dock A targeting dock B, place an event item `Lock Broken - {A}` on an event location in B's region (no rule), and rule(A -> B) = `AND(open, OR(lock, has(lock event)))`; rule(B -> A) = B's own open (and B's own lock) only. Skip on `Impossible`. Entrance name `f"{src} -> {dst}"`. After building, prune event locations from regions with no incoming entrances (dead nodes such as the room-rando-only Great Temple emerald gate route).
6. Event nodes (not pregranted): `MetroidPrime2Location(player, node.id.ap_name, None, region)`, `place_locked_item(MetroidPrime2Item(f"Event - {db.events[short]}", progression, None, player))`, `show_in_spoiler = False`. Duplicate event names across nodes are fine.
7. Pickup nodes: `MetroidPrime2Location(player, LOCATION_TABLE[index].name, LOCATION_ID_BASE + index, region)`.
8. `completion_condition[player] = lambda s: s.has("Event - Dark Samus 3 and 4", player)`.
9. No rule uses `can_reach`, so no indirect conditions; leave `explicit_indirect_conditions` default.

Cheap asserts: 119 pickup locations, >2000 entrances, origin region exists.

### E.1. Door lock / elevator randomization (`logic/dock_rando.py`)

> **Update.** `teleporter_rando` (a third Toggle option this section originally described alongside `door_lock_rando`/`elevator_rando`) was removed after vendoring from randovania's `prime2_opr` game definition (see the "prime2_opr resync" update near the top of this file) revealed the inter-region Energy Controller light-transports aren't reciprocal dock pairs in the real, OPR-patched game at all -- they're an `is_unlocked`-gated many-to-many fast-travel network (`node_type == "teleporter_network"`), with no OPR patch-data schema field or vendored instance id to even write a reassignment to. The option had been a silent no-op since that resync (its dock pool was always empty). See `logic/dock_rando.py`'s module docstring and `build_elevator_assignment`'s docstring for the full story. The rest of this section (E.1) describes `door_lock_rando`/`elevator_rando`, which are unaffected.

Two independent Toggle options (`door_lock_rando`, `elevator_rando`; translator gate color rando is a separate Choice option, section E.2). `world.generate_early()` calls `build_dock_rando_assignment(world)` once and stores the result (`DockRandoAssignment(door_lock, elevator)`) on `world.dock_rando`; both `create_regions` (via `dock_target`/`dock_weakness_for`) and `patch_data._world_changes` (emitting `door_locks`/`elevators` `AreaChange` entries) read the same dicts, so the logic graph and the in-ISO patch can never disagree. `generate_early` builds `world.translator_gate_assignment` **before** `world.dock_rando`: the reject-and-retry probe below evaluates translator gate requirements through `regions.py`'s `translator_gate_requirement`, which reads that assignment.

**Door locks**: one global `old_weakness -> new_weakness` substitution (`_global_weakness_mapping`) applied per node keyed by that node's *vanilla* weakness, then copied onto the node's physical pair-partner (`_door_pairs`) so both faces of one physical door always get the same lock. Sources are the 8 types in `DOOR_CAN_CHANGE_FROM` (Annihilator/Dark/Light Door, Missile/Super Missile/Power Bomb/Seeker Launcher Blast Shield, Normal Door); targets are `DOOR_CAN_CHANGE_TO` (the same 8 with Seeker Launcher Blast Shield replaced by its patched-open "(patched)" variant, the actual shuffle target). This mirrors randovania's `WEAKNESS_TO_WEAKNESS` mode with `force_change_two_way` (`randovania/generator/dock_weakness_distributor.py::_distribute_mode_weakness`). "Permanently Locked" remains deliberately excluded as a target (it compiles to `Impossible`). Patch side: `_door_lock_modification` emits `{"dock_name": node.dock_name, "old_door_type": ..., "new_door_type": ...}` (`DockTypeChange`), using `DockWeakness.door_type` (vendored `extra.door_type`) directly as OPR's `dock_lock_rando.dock_type_database.DOCK_TYPES` key -- no separate mapping table needed.

> **Correction.** An earlier revision of this plan asserted that randovania reassigns each door side independently and uniformly at random, and this world was built that way. That was wrong on both counts. Implemented as independent per-side uniform choice it cut free "Normal Door"s from 337/556 to ~72, took locked doors from 97 to 284, and left **0 of the 119 pickups reachable from the start state on every seed tested** -- 27/27 generation failures, i.e. `door_lock_rando` could never produce a playable seed.

Correcting the distribution is necessary but **not sufficient**: a straight port of randovania's global mapping still failed 10/10 seeds. Randovania's real solvability backstop is that dock weaknesses are assigned inside the same generation attempt its resolver validates, and the whole attempt is retried on failure (`generate_and_validate_expected_layout`, `tenacity.AsyncRetrying` over `UnableToGenerate`). Archipelago has no equivalent -- a `FillError` aborts generation outright. So `build_door_lock_assignment` reject-and-retries (`_MAX_DOOR_LOCK_ATTEMPTS = 2000`) against `_meets_progression_bar`.

**`_meets_progression_bar`** is a coarse but **item-aware** forward sweep, as opposed to `_reachable_nodes` (below), which is deliberately item-blind. It rebuilds the candidate's real `(target, Rule)` edge graph by calling `regions.py`'s own `_intra_area_edges`/`_dock_edge` -- factored out of `create_regions` precisely so the probe and the real region graph can never drift apart -- and runs a fixed-point sweep with a synthetic `_ProbeState` standing in for `CollectionState`. A candidate passes iff (1) the start state (`constants.DEFAULT_STARTING_ITEMS` only) reaches at least `_MIN_SPHERE_ZERO_PICKUPS` pickups, and (2) all 119 pickups are reachable with everything collected. Both door-lock and elevator/teleporter candidates must clear it.

**Elevators/teleporters**: both are reciprocal two-way pools (`_reciprocal_pairs`: every dock-type-matched (A, B) pair where A's vanilla target is B and vice versa; a one-way trip into a plain spawn point, like the Sky Temple Grounds<->Sky Temple ending elevator, is automatically excluded since it isn't reciprocal). `ELEVATOR_EXCLUDED_AP_NAMES` additionally pins the intra-region Aerie<->Aerie Transport Station pair vanilla (verified against randovania's always-excluded teleporter list), leaving 9 shufflable elevator pairs (18 nodes) and 6 teleporter pairs (12 nodes, the Great Temple/Agon/Torvus/Sanctuary Energy Controller mesh). `_shuffle_pairs` does a random perfect matching over each pool's endpoints; `build_elevator_and_teleporter_assignment` retries (`_MAX_SHUFFLE_ATTEMPTS = 2000`) until `_reachable_nodes`'s coarse fixed-point sweep still reaches every original pool endpoint node -- **not** a region-level check (a region can have independent sub-branches that only interconnect through one specific elevator, e.g. Great Temple's three "Temple Transport X Access" branches; losing one while leaving the region's other branches reachable is still a stranded softlock) and **not** ignoring every requirement (an early, simpler version that did both of those passed its own check while actually stranding Great Temple -- caught by the reachability tests in `test/test_dock_rando.py`, not derived analytically). The sweep stays optimistic about item/trick/damage/misc requirements (that risk is accepted, same as for door locks and the rest of item placement) but is *not* optimistic about `events` resource checks, because some connections are one-way switches (e.g. Great Temple/Transport C Access's "Light Block" event: free from the Temple Sanctuary side, but the reverse direction requires that event already triggered) where "ignore it, assume True" is actually wrong, not just optimistic. Patch side: `_elevator_modification` emits `{"elevator_id": node.teleporter_instance_id, "target": {"mlvl_id", "mrea_id"}, "scan_strg": node.scan_asset_id, "target_name": target_id.region}` (`ElevatorChange`); `teleporter_instance_id`/`scan_asset_id` are vendored DB fields, no lookup needed. Candidates that pass `_reachable_nodes` must additionally clear `_meets_progression_bar`. That does **not** measurably help this pool: `elevator_rando` still fails generation ~32% of the time (100 fresh seeds). Those failures clear both bars -- sphere-0 >= 1 and all-items 119/119 -- yet `Fill` still cannot place 110+ items, so the deadlock is mid-game ordering, which a two-snapshot check structurally cannot see. See risk 13.

All three assignments and the connectivity sweep are covered by `test/test_dock_rando.py` (pure-logic unit tests against a stub world, plus full-generation reachability checks across many seeds) and `test/test_patch_data.py` (the generated config validates against OPR's real `RandoConfiguration` pydantic schema with `extra="forbid"`).

### E.2. Translator gate color randomization (`logic/translator_gate_rando.py`)

A `translator_gate_rando` Choice option (`vanilla` default / `full_random` / `full_random_unlocked`), mirroring randovania's own `TranslatorConfiguration` presets (`randovania/games/prime2/layout/translator_configuration.py`'s `with_vanilla_colors()` / `with_full_random()` / `with_full_random_with_unlocked()` -- the fourth preset, `with_vanilla_actual()`, isn't offered since this world's vanilla baseline is already `vanilla_color`, per section E step 3's note on the two gates where they disagree; per-gate custom assignment, randovania's GUI-only "Custom" mode, isn't exposed either -- it doesn't fit AP's per-option model any better than door lock rando's node-by-node GUI does). `world.generate_early()` calls `build_translator_gate_assignment(world)` once and stores the result (`{gate_node_id: color | None}`, empty for `vanilla`) on `world.translator_gate_assignment`; both `translator_gate_requirement` (section E step 3) and `patch_data._translator_gate_modification` read the same dict, so the logic graph and the in-ISO patch can never disagree.

Each of the 17 `configurable_node` gates is assigned **independently**, uniformly at random: `full_random` picks one of the four colors (Violet/Amber/Emerald/Cobalt); `full_random_unlocked` picks one of those four or `None` ("Unlocked" -- the gate only requires Scan Visor, no translator at all, matching open-prime-rando's dedicated `"unlocked"` `TranslatorRequirement`, `open_prime_rando.echoes.translator_gates.TRANSLATOR_DATA`). Mirrors randovania's own generator step (`base_patches_factory.py::SharedEchoesBasePatches.translator_gates`) exactly, including that it's a plain `rng.choice` per gate with no reciprocal pairing. Unlike section E.1's door locks and elevators/teleporters, there is **no** reject-and-retry loop here: a translator gate's requirement change only ever adds or removes an item check on top of the vanilla graph shape (it never changes what a dock *connects to*), and both `full_random` modes measured 0 generation failures over 25 seeds. If that ever stops holding, `_meets_progression_bar` is directly reusable here. Patch side: `_translator_gate_modification` emits `{"translator": <color lowercased, or "unlocked">}`.

Covered by `test/test_translator_gate_rando.py` (pure-logic unit tests against a stub world, plus a full-generation reachability + patch-data-consistency check) and `test/test_patch_data.py`'s existing vanilla-mode `test_17_translator_gates`.

---

## F. Items and locations

`ITEM_ID_BASE = 5033000`, `LOCATION_ID_BASE = 5033200` (Prime 1 uses 5031000/5031100). Location id = base + pickup_index. Location name = `f"{region}: {area} - {node}"` (e.g. `Temple Grounds: Hive Chamber A - Pickup (Missile)`; unique). Location groups: `Boss` (9), `Guardian` (3), one per region.

`items.py` `ItemData(name, code, classification, gains: tuple[(PlayerItemEnum id, amount)], progression: stages|None, model: str, default_pool_count)`. Item ids = base + fixed list position (append only):

| # | AP item | class | gains (id, amt) | OPR model | default pool |
|---|---|---|---|---|---|
| 0 | Power Beam | prog | (0,1) | PowerBeam | 0 start |
| 1 | Charge Beam | prog | (22,1) | ChargeBeam | 0 start |
| 2 | Dark Beam | prog | (1,1),(45,50) | DarkBeam | 1 |
| 3 | Light Beam | prog | (2,1),(46,50) | LightBeam | 1 |
| 4 | Annihilator Beam | prog | (3,1) | AnnihilatorBeam | 1 |
| 5 | Super Missile | prog | (4,1) | SuperMissile | 1 |
| 6 | Darkburst | prog | (5,1) | Darkburst | 1 |
| 7 | Sunburst | prog | (6,1) | Sunburst | 1 |
| 8 | Sonic Boom | prog | (7,1) | SonicBoom | 1 |
| 9 | Combat Visor | prog | (8,1) | CombatVisor | 0 start |
| 10 | Scan Visor | prog | (9,1) | ScanVisor | 0 start |
| 11 | Dark Visor | prog | (10,1) | DarkVisor | 1 |
| 12 | Echo Visor | prog | (11,1) | EchoVisor | 1 |
| 13 | Varia Suit | prog | (12,1) | VariaSuit | 0 start, always |
| 14 | Dark Suit | prog | (13,1) | DarkSuit | 1 if not progressive_suit |
| 15 | Light Suit | prog | (14,1) | LightSuit | 1 if not progressive_suit |
| 16 | Progressive Suit | prog | stages [(13,1)],[(14,1)] | VariaSuit | 2 if progressive_suit |
| 17 | Morph Ball | prog | (15,1) | MorphBall | 0 start |
| 18 | Morph Ball Bomb | prog | (18,1) | MorphBallBomb | 1 |
| 19 | Boost Ball | prog | (16,1) | BoostBall | 1 |
| 20 | Spider Ball | prog | (17,1) | SpiderBall | 1 |
| 21 | Power Bomb | prog | (43,2) | PowerBomb | 1 |
| 22 | Space Jump Boots | prog | (24,1) | SpaceJumpBoots | 1 |
| 23 | Gravity Boost | prog | (25,1) | GravityBoost | 1 |
| 24 | Grapple Beam | prog | (23,1) | GrappleBeam | 1 if not progressive_grapple |
| 25 | Screw Attack | prog | (27,1) | ScrewAttack | 1 if not progressive_grapple |
| 26 | Progressive Grapple | prog | stages [(23,1)],[(27,1)] | GrappleBeam | 2 if progressive_grapple |
| 27 | Missile Launcher | prog | (73,1),(44,5) | MissileLauncher | 1 |
| 28 | Seeker Launcher | prog | (26,1),(44,5) | SeekerLauncher | 1 |
| 29-32 | Violet/Amber/Emerald/Cobalt Translator | prog | (97..100,1) | <Color>Translator | 1 each |
| 33 | Energy Tank | prog | (42,1) | EnergyTank | 14 |
| 34 | Missile Expansion | prog, skip_balancing | (44,5) | MissileExpansion | 33 (filler item name) |
| 35 | Power Bomb Expansion | prog, skip_balancing | (43,1) | PowerBombExpansion | 8 |
| 36 | Dark Ammo Expansion | prog, skip_balancing | (45,20) | DarkBeamAmmoExpansion | 10 |
| 37 | Light Ammo Expansion | prog, skip_balancing | (46,20) | LightBeamAmmoExpansion | 10 |
| 38 | Beam Ammo Expansion | prog, skip_balancing | (45,200),(46,200) | BeamAmmoExpansion | 0 |
| 39-47 | Sky Temple Key 1..9 | prog | ids 29,30,31,101..106 | SkyTempleKey | per STK mode |
| 48-56 | Dark Agon/Dark Torvus/Ing Hive Key 1..3 | prog | 32..34 / 35..37 / 38..40 | DarkTempleKey | 1 each |
| 57-60 | Double Damage (58), Unlimited Missiles (81), Unlimited Beam Ammo (82), Cannon Ball (96) | useful/filler | | MassiveDamage/UnlimitedMissiles/UnlimitedBeamAmmo/CannonBall | 0 |

Expansions are `progression` because the logic counts them (`Missile >= 5`, `DarkAmmo >= 30`). Pool with defaults: 25 majors + 14 tanks + 61 expansions + 9 dark keys + 9 STK = 118 (randovania's starter preset also shuffles 118 and leaves one Energy Transfer Module); `item_pool.py` pads with one Missile Expansion to reach 119 locations. Item groups: `Sky Temple Keys`, `Dark Temple Keys`, `Beams`, `Visors`, `Suits`, `Translators`, `Expansions`.

STK modes (`item_pool.py`): numeric N -> keys 1..N in pool, N+1..9 precollected; `all_bosses` -> 9 keys locked onto the 9 boss locations; `all_guardians` -> 3 keys locked onto 43/79/115, 6 precollected. Starting inventory: `DEFAULT_STARTING_ITEMS` (Power Beam, Charge Beam, Combat Visor, Scan Visor, Varia Suit, Morph Ball) pushed via `push_precollected`; `start_inventory` copies of those are ignored.

---

## G. Options and settings

`MetroidPrime2Options(PerGameCommonOptions)`:

| name | type | values / default |
|---|---|---|
| `start_inventory_from_pool` | StartInventoryPool | |
| `sky_temple_keys` | Choice | `0..9`, `all_bosses=10`, `all_guardians=11`; default 9 |
| `progressive_suit` | DefaultOnToggle | |
| `progressive_grapple` | Toggle | off |
| `trick_level` | Choice | `disabled=0 .. ludicrous=5`; default 0 (global default) |
| `trick_<snake short_name>` x25 | generated Choice | `use_global=0, disabled=1, beginner=2 .. ludicrous=6`; default 0 |
| `damage_strictness` | Choice | `strict=0 (x1.0), medium=1 (x1.5), lenient=2 (x2.0)`; default medium |
| `energy_per_tank` | Range 50..500, default 100 | logic + DamageChanges |
| `dark_aether_damage` | Range 10..600, default 60 -- **tenths** of a point/second (60 == 6.0) | logic (`dark_world_base = dps/6`) + DamageChanges |
| `dark_suit_damage` | Range 0..600, default 12 -- **tenths** (12 == 1.2) | logic (`dps/6`) + `dark_suit_protection = dps / dark_aether_dps` |
| `dangerous_energy_tanks` | Toggle | off (patch only) |
| `door_lock_rando` | Toggle | off; group "Entrances" |
| `elevator_rando` | Toggle | off; group "Entrances" |
| ~~`teleporter_rando`~~ | removed (see section E.1's update note) | -- |
| `translator_gate_rando` | Choice | `vanilla=0` (default), `full_random=1`, `full_random_unlocked=2`; group "Entrances" |
| `display_nonlocal_items` | Choice | `none=0`, `match_game=1` default |
| `reveal_map` | Toggle | off |
| `unvisited_room_names` | DefaultOnToggle | |
| `death_link` | DeathLink | off; not grouped, same as `worlds/metroidprime` |

Both dark-damage options are stored in **tenths of a point per second** and converted by the single helper `options.dark_damage_per_second(tenths)` before any use (logic and patch data alike); never read `.value` directly for a damage calculation. `Options.Range` is integer-only (`numbers.Integral`) and MultiWorldGG has no fractional option class, so tenths are the only way to express randovania's starter-preset `dark_suit_damage: 1.2` exactly. A whole-number `Range` could only default to 1 -- ~17% *more permissive* than randovania, i.e. logic assuming less dark-aether damage than the player actually takes, an out-of-logic death risk -- or 2, which is stricter than upstream but not what upstream uses. Defaults 60/12 reproduce randovania exactly: `dark_world_base == 1.0`, `dark_suit_multiplier == 0.2`, patch `dark_world_damage == 6.0`, `dark_suit_protection == 0.2`.

`door_lock_rando`/`elevator_rando`: see section E.1 (`logic/dock_rando.py`) for the full algorithm. `translator_gate_rando`: see section E.2 (`logic/translator_gate_rando.py`).

`death_link` (client/death_link.py, client/client.py): own-death detection polls `EchoesInterface.get_current_health()` (CPlayerState+`versions.HEALTH_OFFSET`, `0x14` -- verified against OPR's `apply_reverse_energy_tank_heal_patch`'s `health_offset` for `Game.ECHOES`, not derived) against 0, debounced by `is_pending_death_link_reset` exactly like `worlds/metroidprime`; an incoming DeathLink writes `-1.0` to the same field via `EchoesInterface.set_current_health()` (a direct poke, same as Prime 1's `set_alive(False)` -- there's no remote-execution-safe way to force a death through the normal item-grant call path). `on_deathlink` **must** also set `is_pending_death_link_reset = True`: without it the next poll tick sees `health <= 0` with the flag clear and re-broadcasts the incoming death straight back to the group (`CommonContext.send_death` has no debounce), so one player's death ping-pongs around the DeathLink group. `worlds/metroidprime`'s `on_deathlink` has this exact bug; do not "restore parity" with it. The flag clears itself once health goes positive on respawn, so a later organic death still sends normally. `set_current_health` also guards `DolphinException`, like every other Dolphin access in that class. `build_static_context`: `trick_levels[short] = trick_level.value if per-trick == 0 else per_trick - 1`. Groups: Goal, Item Pool, Entrances, Logic, Tricks, Cosmetic.

`settings.py` (`MetroidPrime2Settings(settings.Group)`, Prime 1 pattern): `rom_file: RomFile(UserFilePath)` (NTSC-U or PAL ISO), `emulator_settings` (`executable_path`, `arguments`, `auto_start`), `hud_settings` (named color or rgb -> `HudColorConfiguration.main_color = rgb/255`), `suit_settings` (`varia/dark/light_skin` in `player1..player4`).

---

## H. Patch data (`patch_data.py`)

`make_rando_configuration(world) -> dict` built in `generate_output`; client fills `hud_color`, `suit_replacement` from host.yaml:

```python
{
 "game_title": f"MWGG Echoes {seed_name[:10]} P{player}"[:64],
 "title_screen_text": f"\nMultiworldGG - {player_name}",
 "seed": world.random.getrandbits(31),
 "world_uuid": str(uuid.uuid5(NAMESPACE_UUID, f"{seed_name}/{player}")),   # also in slot_data
 "starting_area": {"mlvl_id": 1006255871, "mrea_id": 1655756413},          # Temple Grounds / Landing Site
 "starting_items": starting_items_config(world),
 "map_visibility": {"reveal_map_at_start": ..., "unvisited_room_names": ..., "areas_to_never_reveal": [], "unvisited_map_icons": False},
 "practice_mod": "disabled", "auto_enabled_elevators": False, "two_way_portals": False, "inverted_mode": False,
 "damage_changes": {"energy_per_tank": E, "safe_zone_heal_per_second": 1.0, "dangerous_energy_tanks": ...,
                    "dark_world_damage": float(dark_aether_damage), "dark_suit_protection": dark_suit_damage / dark_aether_damage},
 "world_changes": [...], "string_changes": [],
}
```
`world_changes` also carries, for each of the 17 configurable nodes, an AreaChange `translator_gates` entry `{"translator": <color lowercased, or "unlocked">, **node.extra.get("gate_instances", {})}` (randovania `prime2_opr` `create_translator_gates`) -- the color/"unlocked" comes from `world.translator_gate_assignment` when `translator_gate_rando` reassigned that gate, else its vanilla color (section E.2); plus, when `door_lock_rando`/`elevator_rando`/`teleporter_rando` reassigned anything, `door_locks`/`elevators` AreaChange entries from `world.dock_rando` (section E.1).
(`beam_configuration`, `custom_items`, `game_options_defaults` left at OPR defaults.)

`starting_items_config`: sum `gains` of every `precollected_items[player]` item (k-th copy of a progressive applies stage k) plus mandatory `{12:1, 8:1, 9:1, 0:1, 22:1, 15:1}`; clamp Varia to 1, Energy Tank to 14; emit `[{"item": id, "capacity": n}]`.

`world_changes`: group pickup nodes by `db.mlvl_for_region(region)` -> `WorldChange{mlvl_id, area_changes}`; per area `AreaChange{mrea_id: area.asset_id, pickups: [...]}`; per pickup:
```python
{"location": location_data_for(node),   # copy extra.location_data; flatten "instances" into top level; every connection gets "state": "ZERO";
                                        # for "custom": add "position" from node.coordinates  (mirror prime2_opr _get_location_data)
 "primary_stage": {"resources": [{"item": 74, "amount": pickup_index + 1}],
                   "appearance": {"model_data": model, "sound": SOUND[kind], "jingle": JINGLE[kind], "hud_text": hud_text, "scan": scan},
                   "conversion": []},
 "progressive_stages": []}
SOUND = {"standard": 10057, "expansion": 10057, "key": 1075}
JINGLE = {"standard": ("/audio/itm_x_long_00.dsp", 71), "expansion": ("/audio/itm_x_short_00.dsp", 55), "key": ("/audio/skytenkey-jin-short32.dsp", 110)}
```
`kind`: key models and EnergyTransferModule -> `key`; expansion/EnergyTank models -> `expansion`; else `standard`.

Model selection: own item, or another Echoes player's item with `match_game` -> `ITEM_TABLE[name].model`; otherwise `EnergyTransferModule` (keep `MODEL_BY_CLASSIFICATION` dict as hook). `hud_text`: own `f"{item} acquired!"`, remote `f"Sent {item} to {player_name}!"`; strip newlines and `&`/`;`, clamp 60 chars. `scan`: own `f"{item}."`, remote `f"{player_name}'s {item}."`.

`generate_output`: write `MetroidPrime2Container(config_json, options_json{player_name, world_uuid, apworld_version}, ...)`. `fill_slot_data`: all logic-affecting options (incl. 25 trick options) + `world_uuid` + `first_non_starting_item_index = len(precollected_items[player])` + `sky_temple_key_locations` + `apworld_version`. UT: `interpret_slot_data` returns slot_data; `generate_early` copies slot_data option values when `re_gen_passthrough` is present.

---

## I. Container and client-side patching

`container.py`: `MetroidPrime2Container(APPlayerContainer)`, `game = "Metroid Prime 2: Echoes"`, `patch_file_ending = ".apmp2"`, writes `config.json` + `options.json` (Prime 1 `Container.py` minus the PPC hook code).

`client/patcher_runner.py`:
```python
def detect_iso_version(iso_path) -> str          # game id at offset 0: b"G2ME01" ntsc, b"G2MP01" pal; reject RVZ/WIA/GCZ/CISO/NKit and G2MJ01
def patch_iso_with_ap(apmp2_file, input_iso, settings, progress) -> str   # output = <apmp2 basename>.iso
```
Body reproduces OPR `patch_iso` so DOL fixes can be inserted:
```python
provider = IsoFileProvider(Path(input_iso)); editor = PatcherEditor(provider, Game.ECHOES); output = IsoFileWriter(provider)
version = find_version_for_dol(editor.dol, dol_versions.ALL_VERSIONS)
editor.dol.write(version.powerup_should_persist + 74, b"\x01")           # persist magic item
editor.dol.write(version.powerup_max + 74 * 4, struct.pack(">I", 65536))  # its max
with goal_trigger_installed():                                          # section J
    opr_patcher._apply_patches(editor, configuration, output, progress, progress, progress)
output.commit(Path(output_iso), "ISO", callback=...)
```
Delete partial output on failure; skip if output exists (force via `/export_iso`); run in `asyncio.to_thread`. If `editor.dol.write` is unavailable in PyPI 0.20.1 use `editor.code_cave.dol_editor.write` (same object `custom_items` uses).

Dependencies: `requirements.txt` handles source installs via `ModuleUpdate`. `utils.setup_libs()` (Prime 1 pattern) pip-installs `open-prime-rando[nod]==0.20.1` + `dolphin-memory-engine` into `Utils.home_path('lib')` when versions mismatch; if OPR cannot be imported, log a clear install instruction instead of crashing. Frozen-build wheel bootstrap deferred to M5.

---

## J. Client (`client/`)

`versions.py`: `EchoesVersionInfo(name, game_id, build_string_address, build_string, game_state_pointer, cplayer_vtable, cstate_manager_global, update_hint_state, message_receiver_string_ref, max_message_size, wstring_constructor, display_hud_memo, add_power_up, incr_pickup, decr_pickup)`; `VERSIONS = [NTSC, PAL]` copied from `open-prime-rando/src/open_prime_rando/dol_patching/echoes/dol_versions.py`. OPR's instruction builders (`all_prime_dol_patches`, `ppc_asm`) are imported lazily in `game_interface.py`, constructing `StringDisplayPatchAddresses`/`PowerupFunctionsAddresses` from this table.

`game_interface.py`:
```python
class ConnectionState(Enum): DISCONNECTED, WRONG_GAME, WRONG_SEED, IN_MENU, IN_GAME
class EchoesInterface:
    connect_to_game()                 # hook; 6 bytes at 0x80000000 -> version by game_id
    read_build_string() -> (matches: bool, uuid)   # bytes[:6] and bytes[22:] must match; uuid = bytes[6:22]
    get_connection_state()
    is_in_game()                      # *(cstate+0x14FC) != 0 and its vtable == cplayer_vtable, and current MLVL is a known one
    current_mlvl()                    # u32 at *(game_state_pointer)+4
    has_pending_op()                  # byte at cstate+0x2
    read_inventory() -> dict[int, (amount, capacity)]   # 109*12 bytes at *(cstate+0x150C)+0x5C
    execute(instructions, message)    # create_remote_execution_body(Game.ECHOES, string_display, ...) -> write body, optionally
                                      # write UTF-16-BE message (<=194 bytes, 4-aligned; Prime 1 _save_message_to_memory) + call_display_hud_patch,
                                      # then write b"\x01" to cstate+0x2
    grant(deltas, message) -> leftovers   # pack adjust_item_amount_and_capacity_patch groups until ValueError (~8 per body, ~6 with message)
    consume_magic_item(amount)        # adjust_item_amount_patch(74, -amount)   (amount only)
    ensure_magic_capacity(cap)        # if cap < 4096: increment_item_capacity_patch(74, 4096 - cap)
```

`receive_items.py` `compute_desired_capacities(items, slot_data) -> dict[int, int]`, idempotent from the FULL received list including starting inventory (the ISO SpawnPoint already granted those, so their delta is zero, but they must still count so a precollected Missile Launcher unlocks later expansions; `first_non_starting_item_index` is kept in slot_data but unused): booleans -> 1; Varia always exactly 1; Energy Tank `min(count, 14)`; progressive k-th copy -> stage k; Missile 44 `0 if no launcher else 5*(1+seekers+expansions)`, 73 = launcher flag; Power Bomb 43 `0 if no main else 2+expansions`; Dark/Light ammo `50*beam + 20*exp + 200*beam_exp`. `sync_inventory(ctx, current)`: delta = desired - current capacity per id; positive deltas via `adjust_item_amount_and_capacity_patch`; negative deltas assert+log (capacities only grow). HUD: `f"Received {item} from {sender}"`, one per body, through `NotificationManager` (4 s cooldown).

`client.py` (structure of `MetroidPrimeClient.py`): `MetroidPrime2Context` (UT `TrackerGameContext` via try/except), `items_handling = 0b111`; `on_package("Connected")` stores slot_data and `expected_uuid`. `dolphin_sync_task` tick (0.5 s in game):
1. `has_pending_op()` -> skip tick.
2. `inv = read_inventory()`; `amount, cap = inv[74]`; `ensure_magic_capacity(cap)` once per connection.
3. `amount > 0`: `index = amount - 1`; `0..118` -> `LocationChecks[base+index]` then `consume_magic_item(amount)`; `index >= 119` -> goal sentinel, `StatusUpdate CLIENT_GOAL` once, consume; implausible value (already checked / > 120) -> warn and consume.
4. Else compute deltas and `grant` one body.
5. `notification_manager.handle_notifications()` when idle; tracker `Set` of current MLVL.
State machine: DISCONNECTED -> WRONG_GAME (build string mismatch, log once) -> WRONG_SEED (uuid mismatch) -> IN_MENU -> IN_GAME. Commands: `/export_iso`, `/status`, `/test_hud`, `/mp2_debug_inventory`. `main()` parses `apmp2_file` + optional ISO, `setup_libs()`, sets `ctx.auth` from `options.json`. Register in `__init__.py`: `Component("Metroid Prime 2 Client", func=run_client, component_type=Type.CLIENT, file_identifier=SuffixIdentifier(".apmp2"), icon="Metroid Prime 2")`, `icon_paths["Metroid Prime 2"] = "ap:worlds.metroidprime2/assets/icon.png"`.

Goal detection, two mechanisms:
1. **In-ISO sentinel (primary, no reverse engineering)**: in `patcher_runner`, wrap `opr_patcher.register_world_changes` to also `area_patcher.add_raw_function(TEMPLE_GROUNDS_MLVL, CREDITS_MREA, add_goal_trigger)`, where `add_goal_trigger` adds a `Timer(time=1.0, auto_start=True)` connected (`State.Zero -> Message.Action`) to a `SpecialFunction(function=Function.SetInventoryAmount, int_parm2=120, inventory_item_parm=PlayerItemEnum.PersistentCounter8)` (same pattern as OPR `pickup_editing`'s secondary-resource SpecialFunction). Client rule: `amount - 1 >= 119` -> goal. Test first by temporarily targeting Landing Site and confirming amount 120 on load.
2. **Memory read (optional)**: locate the current MREA id in Dolphin's memory search (candidates near `*(game_state_pointer)+4`, or `CStateManager` fields `m_world` ~0x1604 / `m_nextAreaId` ~0x16A0 from PrimeDecomp, unverified); if found, add `current_area_offset` to `versions.py` and `at_end_of_game = mlvl == TEMPLE_GROUNDS and mrea == CREDITS`.

---

## K. Milestones and verification

**M0 – Skeleton and data.** Create dir + symlink, `archipelago.json`, `constants.py`, `tools/sync_randovania_data.py` (run it), `data/`, `options_tricks.py`, `db_reader.py`. `test_db_reader.py`: 1109 nodes, 119 contiguous pickups, 111 events, 25 tricks, 19 templates, all dock targets resolve, 5 distinct MLVL ids matching a frozen copy of OPR `NAME_TO_ID_MLVL`, Landing Site MREA == 1655756413. Run: `cd MultiWorldGG && python -m pytest worlds/metroidprime2/test/test_db_reader.py`.

**M1 – Logic and generation.** `items.py`, `locations.py`, `item_mapping.py`, `requirements.py`, `regions.py`, `item_pool.py`, `options.py`, `__init__.py` (no output yet). Tests with `MP2TestBase(WorldTestBase)`:
- `test_requirements.py`: all templates compile; `Open Normal Door` true with Power Beam only; `Shoot Darkburst` false without launcher, true with launcher+Darkburst+Dark Beam+Charge; damage `DarkWorld1 60` @1.5 -> `int(90)` passes with 0 tanks (90 < 99), `70` -> 105 fails until 1 tank; Dark Suit x0.2; Light Suit always passes; negated event -> None; negated item -> Impossible; `not RoomRando` -> None.
- `test_regions.py`: all 119 locations reachable with everything collected; `can_beat_game()`; a few negative checks (e.g. Dark Visor location 79 unreachable without Dark Torvus keys; STK 9 at Accursed Lake unreachable without Dark Visor); ludicrous tricks still generate. Vanilla-placement test: derive vanilla item per node name (`Pickup (X)`; index 88 = Power Bomb main; STK at 11,15,19,45,53,68,91,106,117), `progressive_* = False`, `sky_temple_keys = 9`, place locked, assert beatable.
- `test_pool.py`: pool size per STK mode (numeric N: 119-(9-N) precollected; all_bosses: 9 locked, pool 110; all_guardians: 3 locked, 6 precollected, pool 116); progressive toggles.
- `test_fill.py`: **real fill coverage** -- calls `distribute_items_restrictive` across STK modes, progressive toggles, `door_lock_rando`/`elevator_rando`/`teleporter_rando`, and both translator gate modes, on hand-picked deterministically-passing seeds. Reachability-only tests are not enough: the `door_lock_rando` total-lockout bug (section E.1) shipped precisely because every existing test asserted all-items reachability and none ever ran a fill.
- `test_version.py`: `version.txt` == `archipelago.json`'s `world_version`.
- `MP2TestBase.run_default_tests` stays `False`, but **not** for the reason originally given (the Great Temple "Gate Removal" dead route -- that turned out to be a non-issue, `create_regions`'s dead-region pruning already handles it, and `run_default_tests=True` passes at defaults). The real reason is that `WorldTestBase.test_fill` runs one arbitrary seed, and entrance rando's residual failure rate (risk 13) would make it flaky. `test_fill.py` covers what it would have.
- Generation: `MultiWorldGG/Players/mp2.yaml` (defaults) + a ludicrous-tricks yaml; `python Generate.py --player_files_path Players --outputpath output`; `python -m pytest test/general -x` (framework-wide world checks). Set `SKIP_REQUIREMENTS_UPDATE=1` -- importing the world registry otherwise makes MultiWorldGG's `ModuleUpdate` shell out to `pip install` for unrelated worlds' requirements (`ModuleUpdate.py:70`), which has broken pip in the venv mid-run.

**M2 – Output.** `patch_data.py`, `container.py`, `patcher_runner.py`. `test_patch_data.py`: 119 pickups across 5 MLVLs; every model name in `OPR_MODEL_NAMES`; pydantic validation with `RandoConfiguration.model_validate(cfg, extra="forbid")` when OPR importable; starting items always include 12,8,9,0,22,15 at 1; precollected Missile Launcher -> 73:1, 44:5. Manual: install `open-prime-rando[nod]==0.20.1` in the venv, patch via a small CLI (`python -m worlds.metroidprime2.client.patcher_runner file.apmp2 in.iso`), boot in Dolphin: title text shows player name, starting inventory correct, pickups show expected models, collecting gives only item 74.

**M3 – Client loop.** `game_interface.py`, `receive_items.py`, `client.py`, `settings.py`. `test_client_receive.py` for `compute_desired_capacities` (launcher gating, progressive stages, Varia clamp, tank cap). End-to-end with `MultiWorldGGServer`: pickup -> `LocationChecks` and item 74 amount returns to 0; item sent from another slot appears with HUD message; capacities survive save/load; two quick pickups exercise the warning path.

**M4 – Goal, UT, docs.** Goal trigger (mechanism 1, then 2 if found); `CLIENT_GOAL` after credits; Universal Tracker loads and shows reachability; `docs/setup_en.md` + `docs/en_Metroid Prime 2 Echoes.md` (supported ISOs, Python/OPR install, patch flow, limitations); `write_spoiler` lists pre-placed keys.

**M5 – Distribution.** Frozen-build wheel bootstrap in `setup_libs`; apworld build excluding `tools/` and `test/`.

---

## L. Risks and resolutions

1. **Per-edge damage vs randovania's cumulative energy**: AP checks each damage requirement against max energy, so dark-world chains are more lenient than randovania. Default `damage_strictness = medium` like the starter preset; document.
2. **Negated events folded to True**: over-permissive only after the event fires; `NEGATED_EVENT_OVERRIDES` hook for tuning.
3. **Two pickups between polls** sum into an ambiguous amount. 0.5 s poll, detect implausible values and warn. v2: also read the pickup MemoryRelays (Prime 1 style) as an exact second signal.
4. **Goal offsets unknown**: mechanism 1 (script-injected sentinel) needs no offsets.
5. **`SetInventoryAmount` semantics** (amount only, clamped by capacity): keep item 74 capacity >= 4096; total pickup increments sum to 7140, under the 65536 max.
6. **OPR checkout (v0.20.1-20) vs PyPI 0.20.1 drift**: in M2 grep every used symbol against the installed package (`_apply_patches` signature, `IsoFileWriter.commit`, `find_version_for_dol`, `register_world_changes`, `PICKUP_MODELS`, `RandoConfiguration` fields); log the installed OPR version at client start.
7. **Varia == Defense Up counter**: never grant capacity > 1; tests cover it.
8. **Missile Launcher gating** lives in the client, not the ISO; document that expansions received before the launcher add capacity later.
9. **Platform**: OPR needs Python >= 3.12 and `nod_rs` wheels; `dolphin_memory_engine` on macOS is best-effort (Prime 1 uses it anyway). `py_randomprime` (hard OPR dep) has no Linux aarch64 wheel.
10. **Graph size** (~1100 regions, ~2100 entrances): comparable to large AP worlds; memoise compiled templates; cache rules per requirement id if generation is slow.
11. **Event items** are created directly in `regions.py` with id `None`; `create_item` only handles real items.
12. **Beam Ammo Expansion** amounts (200/200 from the preset with count 0) are placeholders; revisit if enabled (likely 20/20).
13. **Residual generation failure rates -- `elevator_rando` is not yet fit to ship.** Measured after the section E.1 fix, 100 fresh seeds each (5000-5099, i.e. *not* the range the fix was iterated against): `door_lock_rando` ~10%, `elevator_rando` ~32%, `teleporter_rando` ~4%; defaults ~5% (40 seeds). A `FillError` aborts the **entire multiworld**, not just this slot, so a 1-in-3 failure rate on an option is a release blocker. Both remaining classes are mid-game ordering deadlocks (`Fill` fails having placed almost nothing, ~117 items unplaced) that `_meets_progression_bar`'s two snapshots cannot see. A real fix needs an assumed-fill-style solver, or wrapping the dock assignment + fill in a joint retry the way randovania does. Note `dock_rando.py`'s own docstring quotes 1/37 and 6/37 for door-lock/elevator: those were measured on the seed range the fix was developed against and are optimistic.
14. **`VanillaGreatTempleEmeraldGate` stays pinned to 1**, deliberately diverging from randovania's `if configuration.teleporters.is_vanilla` (`prime2/generator/bootstrap.py`). That conditional belongs to the *old* patcher. This world targets OPR, whose `specific_area_patches.rebalance_patches.register_all` applies `temple_sanctuary_emerald_gate` ("keep the Emerald gate active from the beginning") unconditionally for every seed (`patcher.py:372`), and randovania's own OPR-paired database (`games/prime2_opr/logic_database/Great Temple.json`) never references the flag at all -- only the non-OPR `prime2` DB vendored here does. With the flag at 1, `Temple Sanctuary/Door to Transport A Access -> Room Center` folds to statically true (its other conjunct is a negated event), i.e. the door is free, matching the shipped ISO. Setting it to 0 under elevator/teleporter rando would make logic **stricter than the game actually is**. Documented in `constants.py`.
15. **Accepted deviations, deliberately not fixed.** (a) `_leave_requirement` applies a `hint` node's `requirement_to_collect` to that node's outgoing edges, where randovania gates only *collecting* the hint, not passing through. Harmless in practice -- all 31 hint nodes are verified dead-ends with a single outgoing edge back where you came from, so the 5 "Lore Scan" nodes that additionally require a translator can always be routed around -- but it is not randovania's semantics. (b) `item_pool.create_item_pool`'s `pool = pool[:target]` trim would silently drop Sky Temple Keys (appended last) if the pool ever exceeded the location count; unreachable today since the pool is always <= 119, but a silent-progression-loss shape if the item table grows.
