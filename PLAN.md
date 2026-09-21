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
3. **v1 scope**: item shuffle with randovania logic + trick options, Sky Temple Key modes, progressive suit/grapple, starting inventory, damage strictness, death link, door lock/elevator/portal randomization (`logic/dock_rando.py`, each behind its own Toggle option; see sections E.1/E.3), and translator gate color randomization (`logic/translator_gate_rando.py`, a `translator_gate_rando` Choice option; see section E.2). Vanilla starting room.
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
  logic/dock_rando.py      build_dock_rando_assignment(world) -> DockRandoAssignment, consulted by both regions.py and patch_data.py (sections E.1/E.3)
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

Two independent Toggle options in this subsection (`door_lock_rando`, `elevator_rando`; a third, `portal_rando`, shares this same module and is described separately in section E.3; translator gate color rando is a separate Choice option, section E.2). `world.generate_early()` calls `build_dock_rando_assignment(world)` once and stores the result (`DockRandoAssignment(door_lock, elevator, portal, portal_weakness)`) on `world.dock_rando`; both `create_regions` (via `dock_target`/`dock_weakness_for`) and `patch_data._world_changes` (emitting `door_locks`/`elevators`/`portals` `AreaChange` entries) read the same dicts, so the logic graph and the in-ISO patch can never disagree. `generate_early` builds `world.translator_gate_assignment` **before** `world.dock_rando`: the reject-and-retry probe below evaluates translator gate requirements through `regions.py`'s `translator_gate_requirement`, which reads that assignment.

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

### E.3. Portal randomization (`logic/dock_rando.py`)

Aether portal randomization (the fixed Light/Dark Aether rift-travel pairs, `dock_type == "portal"` in the vendored DB -- 66 nodes across four light/dark region pairs: Temple Grounds/Sky Temple Grounds 5/5, Agon Wastes/Dark Agon Wastes 6/6, Torvus Bog/Dark Torvus Bog 7/7, Sanctuary Fortress/Ing Hive 15/15) is fully supported by open-prime-rando (`open_prime_rando.echoes.portal`: a top-level `two_way_portals` bool plus per-area `PortalChange` entries -- `source_dock_name`/`target_mrea_id`/`target_dock_name`/`portal_scan_destination`) and by randovania's `prime2_opr` game (`portal_rando` bool, `EchoesOPRBasePatchesFactory.portal_assignment`/`assign_static_dock_weakness` in `games/prime2_opr/generator/base_patches_factory.py`). It was not implemented in this port before this section was added; it now is, as a third Toggle option (`portal_rando`) sharing `logic/dock_rando.py`'s `DockRandoAssignment`/`build_dock_rando_assignment` with door locks/elevators (section E.1).

Mirrors randovania's algorithm exactly, in two independent parts:

1. **Target shuffle**: every portal node is bucketed by light/dark region pair (`_portal_region_pairs` -- light regions have their own MLVL `asset_id`; dark regions are grouped by `associated_region`, their light counterpart's name). Within a pair, both lists are shuffled independently and zipped element-wise both ways (`_shuffle_portal_region_pair`) -- there is no cross-pair shuffling (a Temple Grounds portal can only ever target a Sky Temple Grounds portal). Unlike elevators, this is *not* a free perfect matching over the combined pool; it stays within each pair, matching the real physical rift network and randovania's own grouping.
2. **Static weakness override** (`_portal_weakness_overrides`, unconditional whenever `portal_rando` is on, independent of the shuffle outcome): every portal node whose *vanilla* weakness is "No Return Portal" -- an arrival-only pad with an Impossible (empty `or`) open requirement, 13 of the 66 nodes -- gets a real beam-color weakness instead ("Dark Portal" if the node's own region is Light, "Light Portal" otherwise), matching the new physical return-portal object open-prime-rando's `two_way_portals` flag adds there (`register_make_portals_two_way`). A portal's weakness otherwise never changes; only its target does.

`dock_target`/`dock_weakness_for` (section E step 5) gained a `dock_type == "portal"` branch each, consulting `world.dock_rando.portal`/`.portal_weakness` the same way the door/elevator branches already did -- no other change was needed in `_dock_edge`, since portal weaknesses never carry a lock (`lock: null` for every entry in the DB's `portal` dock-type table), so the existing lock-broken machinery (door-only) doesn't apply. `_reachable_nodes` gained an optional `portal_targets` parameter (default `None`, so the existing elevator-only call site is unaffected) for the same item-blind topology pre-filter elevators use; `build_portal_assignment` reject-and-retries (`_MAX_SHUFFLE_ATTEMPTS`, shared with elevators) against that filter and then `_meets_progression_bar`, exactly like elevators, since a portal reshuffle can just as easily strand a sub-branch of a region as an elevator reshuffle can (e.g. Sanctuary Fortress/Ing Hive's 15/15 pool spans several otherwise-loosely-connected areas). Patch side: `_portal_modification` emits `{"source_dock_name", "target_mrea_id", "target_dock_name", "portal_scan_destination"}` directly against OPR's `PortalChange` schema (validated by `test_patch_data.py`'s existing `RandoConfiguration.model_validate(..., extra="forbid")` check); the top-level `"two_way_portals"` config key is `bool(world.options.portal_rando)` instead of the previous hardcoded `False`. `PortalChange` has no `target_mlvl_id` sibling field -- portal targets never cross an MLVL boundary (light/dark counterparts of one room share a world file) -- so `_portal_modification` only looks up the target's MREA id, with a cheap same-MLVL assertion as a sanity check.

Covered by `test/test_dock_rando.py` (pure-logic unit tests for the region-pair grouping/shuffle/weakness-override helpers, plus full-generation reachability checks) and `test/test_patch_data.py` (portal count/shape assertions plus the existing OPR schema validation).

### E.4. Save-station door protection (`normal_save_station_doors`)

A new `DefaultOnToggle` option layered on top of section E.1's door locks, addressing a gap `door_lock_rando` otherwise leaves open: nothing stops the global weakness substitution from landing a restrictive lock (a beam-colored door, or a blast shield) on a Save Station room, so a bad roll could gate the *only* reliably-reachable heal/save point behind a beam or ammo type the player doesn't yet have.

The important structural fact this feature has to respect: door lock rando is **not** a per-door roll. `_global_weakness_mapping` computes one random `old_weakness -> new_weakness` substitution for the whole seed, and `_sample_door_lock_candidate` applies `mapping[node.default_dock_weakness]` uniformly to every eligible door. There is no per-door pool to simply exclude a save-station face from -- excluding "Normal Door" as a source would still let some *other* source type map onto it (not helpful), and excluding it as a target would break the substitution for every other door sharing that door's vanilla weakness too (far too broad). So this has to be a **post-mapping, per-door override**, applied after `_sample_door_lock_candidate`'s existing loop (global mapping, then two-way mirroring) has produced a candidate, forcing every protected node id to `"Normal Door"` regardless of what the mapping or mirroring produced for it. Doing the override last also matters for a subtler reason: a protected face's *partner* could otherwise end up overwritten by mirroring from some unprotected node that happened to map onto it first, if the override ran before mirroring instead of after.

A "save station room" is defined the same way `starting_room`'s `save_stations` pool already is (`db_reader.GameDatabase.starting_location_candidates`, section C): an area containing a `generic` node literally named `"Save Station"` with `valid_starting_location` set. `save_station_door_faces` (`logic/dock_rando.py`) reuses that method directly rather than re-deriving the predicate, so the two can never drift apart after a DB resync. It returns the door dock node ids inside each of those 18 areas, plus each one's `_door_pairs` partner (the far-side face) -- the far face has to be forced too, not just left alone, because it's the face shot *from the neighbouring room* to get into the save station in the first place; protecting only the near side would still leave the room unreachable behind a restrictive lock, and it's also what the existing two-way invariant (both faces of one physical door must agree) requires regardless. Measured against the vendored DB: 18 save-station areas, 25 door nodes inside them, 25 distinct `_door_pairs` partners, 50 faces total out of 556 shuffleable doors (~9%) -- asserted exactly in `test/test_dock_rando.py` so a DB resync that changes the count fails loudly.

`build_door_lock_assignment` computes this protected set once, outside the `_MAX_DOOR_LOCK_ATTEMPTS` retry loop (it's a pure function of the static DB and `_door_pairs`, unaffected by which candidate is currently being tried), passing an empty `frozenset` through when the option is off. Forcing a door to "Normal Door" only ever *loosens* the requirement graph (any beam opens it, a strict subset of every other lock type's requirements), so `_meets_progression_bar` can only pass more often with the override applied, never less -- no change was needed to the progression bar itself or the attempt budget.

On by default (`DefaultOnToggle`) so a save is always reachable out of the box; the option's docstring calls out that this can also *remove* a vanilla lock (a few save rooms ship with a Missile Blast Shield or Dark Door on one face) rather than merely leaving an already-eligible door un-randomized.

Covered by `test/test_dock_rando.py`: `save_station_door_faces`'s 18-area/50-face shape; every protected id forced to "Normal Door" with the option on; protected pairs still agreeing with each other; the option off *not* vacuously forcing every protected face normal (asserted over the union of several draws, since a single `_global_weakness_mapping` draw is a bijection and can put at most one source type back onto "Normal Door" -- see that test's docstring); and `door_lock_rando` off still returning an empty assignment regardless of this option's value.

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
| `portal_rando` | Toggle | off; group "Entrances"; see section E.3 |
| ~~`teleporter_rando`~~ | removed (see section E.1's update note) | -- |
| `translator_gate_rando` | Choice | `vanilla=0` (default), `full_random=1`, `full_random_unlocked=2`; group "Entrances" |
| `display_nonlocal_items` | Choice | `none=0`, `match_game=1` default |
| `reveal_map` | Toggle | off |
| `unvisited_room_names` | DefaultOnToggle | |
| `death_link` | DeathLink | off; not grouped, same as `worlds/metroidprime` |

Both dark-damage options are stored in **tenths of a point per second** and converted by the single helper `options.dark_damage_per_second(tenths)` before any use (logic and patch data alike); never read `.value` directly for a damage calculation. `Options.Range` is integer-only (`numbers.Integral`) and MultiWorldGG has no fractional option class, so tenths are the only way to express randovania's starter-preset `dark_suit_damage: 1.2` exactly. A whole-number `Range` could only default to 1 -- ~17% *more permissive* than randovania, i.e. logic assuming less dark-aether damage than the player actually takes, an out-of-logic death risk -- or 2, which is stricter than upstream but not what upstream uses. Defaults 60/12 reproduce randovania exactly: `dark_world_base == 1.0`, `dark_suit_multiplier == 0.2`, patch `dark_world_damage == 6.0`, `dark_suit_protection == 0.2`.

`door_lock_rando`/`elevator_rando`: see section E.1 (`logic/dock_rando.py`) for the full algorithm. `portal_rando`: see section E.3 (same module). `translator_gate_rando`: see section E.2 (`logic/translator_gate_rando.py`).

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
`world_changes` also carries, for each of the 17 configurable nodes, an AreaChange `translator_gates` entry `{"translator": <color lowercased, or "unlocked">, **node.extra.get("gate_instances", {})}` (randovania `prime2_opr` `create_translator_gates`) -- the color/"unlocked" comes from `world.translator_gate_assignment` when `translator_gate_rando` reassigned that gate, else its vanilla color (section E.2); plus, when `door_lock_rando`/`elevator_rando`/`portal_rando` reassigned anything, `door_locks`/`elevators`/`portals` AreaChange entries from `world.dock_rando` (sections E.1/E.3), and the top-level `two_way_portals` key is `bool(world.options.portal_rando)`.
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

## M. `missile_expansions_unlock_launcher`, `power_bomb_expansions_unlock_power_bombs`, and `show_item_locations`

Three independent options, done together only because they touch overlapping files.

**`missile_expansions_unlock_launcher` (item pool option).** Off by default, matching Randovania: a Missile Expansion grants nothing (0 capacity, launcher flag stays off) until the Missile Launcher itself is collected. The rule "missile capacity requires the launcher (or, with the option, at least one expansion)" is **duplicated in two places that must be kept in sync**:

- `logic/item_mapping.expression`'s `Missile` branch (generation-time logic: what counts toward a `Missile` resource requirement). Takes a `missile_expansions_unlock_launcher` kwarg, threaded through `logic/requirements.StaticContext`/`build_static_context` and both of that module's `item_mapping.expression(...)` call sites (`_compile_item`, `_reductions_for`). `build_static_context`'s two callers (`logic/regions.create_regions`, `logic/dock_rando._build_compiler`) pass `bool(world.options.missile_expansions_unlock_launcher)`.
- `client/receive_items.compute_desired_capacities` (the in-game grant: what capacity/flags actually get written to the OPR inventory). Takes the same flag as its third parameter, read by `client.py`'s `_handle_grant_items` out of slot_data (`ctx.slot_data.get("missile_expansions_unlock_launcher", False)` -- the `.get` default keeps old `.apmp2` files working). Lands in slot_data automatically since `_slot_data_option_names()` includes every non-base option.

The logic database itself needed **no edit**, but it does gate on the launcher in two places, which is easy to miss: `MissileLauncher` (item id 73) has zero requirement references in any of the 9 region files, yet `header.json`'s `resource_database.requirement_template` uses it in `Destroy Seeker Locks` and `Destroy Underwater Seeker Locks` -- templates reached from **15 requirement sites** (Agon Wastes x4, Sky Temple Grounds x4, Temple Grounds x2, Torvus Bog x2, Dark Torvus Bog x1, plus the Seeker Missile Blast Shield dock type). Those gate on the launcher *item*, not on `Missile` capacity, so widening only the `Missile` expression would have left logic **stricter than the patched game** at all 15 (a Seeker Launcher + one expansion really does break those locks once the client sets slot 73). Both expressions therefore share one `item_mapping._effective_launcher` predicate, so they cannot drift apart. An audit of all 52 item short names the database actually references confirms `MissileLauncher` is the only main-item-style gate the option touches; `PowerBomb` has the same shape (a counted-ammo expression gated on a main pickup) but was, at the time, deliberately left alone (no equivalent option had been asked for) -- see below for where that changed.

Consequence for **precollected** items: `patch_data.starting_items_config` sums raw `gains_for` over `multiworld.precollected_items`, so a precollected Missile Expansion (e.g. via `start_inventory`) writes capacity into item 44 but never sets the launcher flag (item 73) on its own -- `gains_for("Missile Expansion", ...)` only ever touches id 44. With the option on, `starting_items_config` now also sets id 73 to 1 whenever id 44's capacity is nonzero, so the ISO's own starting inventory is consistent with what the option grants at runtime; without this, the client would have to correct it on the very first tick, and `plan_grants` logs a spurious "capacity is already above desired" warning when it does.

**`power_bomb_expansions_unlock_power_bombs` (item pool option, the Power Bomb counterpart).** Same option shape and default (off) as the missile toggle, and the same duplicated-rule discipline: `item_mapping.expression`'s `PowerBomb` branch (via a new `_effective_power_bomb` predicate) and `client/receive_items.compute_desired_capacities`'s Power Bomb block must agree, so both take the flag and both are exercised end to end in the tests. `StaticContext`/`build_static_context` gained a matching `power_bomb_expansions_unlock_power_bombs` field/parameter, threaded through both `item_mapping.expression(...)` call sites in `requirements.py` (`_compile_item`, `_reductions_for`) exactly like the missile flag, and both `build_static_context` callers (`regions.create_regions`, `dock_rando._build_compiler`) pass `bool(world.options.power_bomb_expansions_unlock_power_bombs)`.

The key **contrast** with missiles, worth recording because it is the fact most likely to be re-litigated: `MissileLauncher` is its own logic-DB resource (item id 73), separately gated in the two `requirement_template`s described above (15 usage sites) -- so the missile option has to widen *two* independent expressions (`MissileLauncher`'s own `_effective_launcher` check, and `Missile`'s count formula) via one shared predicate, or logic would be stricter than the patched game at those 15 sites. **Power Bombs have no such main-item resource at all.** `PowerBomb` (id 43) is the only power-bomb-shaped DB item; there is no `requirement_template` anywhere that gates on a bare "Power Bomb collected" boolean the way the two Seeker Lock templates gate on `MissileLauncher`. So the entire gate for this option lives in exactly one place, `item_mapping.expression`'s `PowerBomb` branch (guarded by `_effective_power_bomb`, which -- unlike `_effective_launcher` -- has only that one caller and says so in its own docstring); nothing under `data/` needed inspection or change, and `DB_ITEM_TO_AP_ITEM` gained no new entry.

`patch_data.starting_items_config` needed a **subtractive** fix that missiles did not, for a reason specific to how OPR treats each ammo type. Missile capacity (id 44) is inert without the separate launcher flag (id 73) being set, so a precollected Missile Expansion writing capacity into id 44 alone was always harmless in-game (unusable ammo, just a latent number) -- the existing fix is purely additive (also set id 73 when the option is on). Power Bombs have no such flag: `open_prime_rando`'s `PlayerItemEnum.PowerBomb` (43) is directly settable and `StartingItemConfig.amount` defaults to `capacity`, so a precollected Power Bomb Expansion with **no** unlock mechanism at all (the option didn't exist yet) would have started the player with a genuinely usable power bomb count that neither logic nor the client's `compute_desired_capacities` credited -- worse than inert, and it made `plan_grants` log its "capacity is already above desired" warning every tick once the client noticed capacity 43 sitting above its own computed desired value of 0. So `starting_items_config` now drops id 43 entirely (rather than leaving whatever `gains_for` summed for expansions alone) whenever `power_bomb_expansions_unlock_power_bombs` is off and no main `Power Bomb` was itself precollected -- determined from the same `precollected_items` loop that already walks every item, not a second pass. The identical failure mode existed for missiles all along (just masked by the launcher flag keeping the capacity unusable rather than making it a live warning), so the same subtractive treatment was added to id 44 symmetrically in this change: `missile_expansions_unlock_launcher` off and no main `Missile Launcher` precollected now also drops id 44. This is a **behavior change**: `start_inventory` with only an expansion (either kind) no longer starts the player with usable ammo unless the corresponding unlock option is on -- see `patch_data.starting_items_config`'s docstring and `test/test_patch_data.py`'s updated `TestStartingItemsWithPrecollectedMissileExpansionAndOptionOff.test_launcher_flag_not_set`.

**`show_item_locations` (internal patch-time flag, driven by the `map_visibility` cosmetic option).** open-prime-rando 0.20.1 already adds a map icon for every pickup it patches: `open_prime_rando.echoes.pickups.pickup_editing._add_map_icon` appends a `MappableObject` of custom `object_type=0x12` with `visibility_mode=ObjectVisibility.AreaVisitOrMapStation` hardcoded -- the dot only shows once the room has been visited or a map station used. OPR's own `map_visibility.unvisited_map_icons` option does **not** cover pickup icons: `general_changes.py`'s `objects_to_reveal` set (the object types that setting forces visible) lists only Elevator/SaveStation/Portal/LightTeleporter/TranslatorGate/Up-DownArrow. `_add_map_icon` has exactly one call site, `patch_simple_pickup` (an unqualified module-global lookup, resolved at call time -- the same mechanism `goal_trigger_installed` relies on for `register_world_changes`); `patch_complex_pickup` delegates to `patch_simple_pickup`, so monkeypatching the module attribute covers every pickup regardless of stage count.

The feature is therefore a client-side monkeypatch, `client/patcher_runner.item_map_icons_always_visible()`, mirroring `goal_trigger_installed`/`warp_to_start_installed`'s context-manager structure: wrap `pickup_editing._add_map_icon`, call through to the original, then walk the mappable objects it just appended (tracked by a before/after length on `area.mapa.mappable_objects` -- appending is the only mutation `_add_map_icon` makes) and set `visibility_mode = ObjectVisibility.Always`. `MappableObject.visibility_mode` is a `wrapper_classes.field(ObjectVisibility)` descriptor with a working `__set__` (confirmed against `general_changes.py`'s own `mappable.visibility_mode = ...` assignment).

Like `warp_to_start`, this is a **patch-time** setting with no home in OPR's `RandoConfiguration` (`config.json` is validated `extra="forbid"`), so it travels in the `.apmp2`'s `options.json` instead, read once in `patch_iso_with_ap` alongside `warp_to_start` and entered into the existing `contextlib.ExitStack` when set.

**`map_visibility` (the player-facing option, folded from two Toggles).** `show_item_locations` originally shipped alongside a second, independent `reveal_map` Toggle (`config.json`'s `map_visibility.reveal_map_at_start`, unrelated to this one's name beyond both concerning the map) with the interaction noted above: the map doesn't draw a room at all until the room itself has been revealed, so in an unvisited room `show_item_locations`'s dot was only visible when `reveal_map` was *also* on. That made "item dots without the revealed map" a real, selectable, but meaningless combination -- indistinguishable from vanilla. The two Toggles were folded into one `options.py` Choice, `MapVisibility` (`vanilla`/`full_map`/`full_map_and_items`), making the invalid combination unrepresentable: `patch_data.make_rando_configuration` sets `reveal_map_at_start` for anything other than `option_vanilla`, and `MetroidPrime2World.generate_output` sets the internal `show_item_locations` flag only for `option_full_map_and_items`.

`reveal_map` itself had already shipped in 1.0.0 by the time of the fold (`show_item_locations` had not -- added and folded away in the same uncommitted change, so it needed no compatibility shim). The last field of `MetroidPrime2Options` is therefore `reveal_map: RevealMapRemoved`, a hidden (`Visibility.none`) `FreeText` subclass that raises, naming `map_visibility` as the replacement, only for a value that actually asked for a revealed map. It is deliberately **not** `Options.Removed`: that class rejects every value, because `FreeText.from_any` is `cls(str(data))` and so YAML's `false` reaches it as the *truthy string* `"False"` -- and `reveal_map: false` is exactly what 1.0.0's own `example_world_config.yaml` shipped, so a bare `Removed` would abort generation for every YAML copied from it while losing nothing (`false` means what `map_visibility: vanilla` now means). The shim's tests go through `from_any`, not the constructor, for the same reason.

## N. `/grant_item` bypassing the desired-capacity model (bug fix)

`MetroidPrime2CommandProcessor._cmd_grant_item` used to look the requested
name up in `items.ITEM_TABLE` and push its raw `gains` (or, for a
progressive item, only `progression[0]`) straight to game memory via
`ctx.game_interface.grant(...)`, entirely bypassing the
`compute_desired_capacities`/`plan_grants` model described in section J.
That model recomputes every OPR inventory slot's target capacity from the
*entire* `ctx.items_received` list every tick, and `plan_grants` only ever
emits the positive difference against live game memory -- a negative delta
is logged and never acted on, because capacities are assumed to only grow.

For any item whose capacity is cross-computed from *other* received items
rather than being a flat "1 if received" (Missile Launcher, Seeker
Launcher, Power Bomb, Power Bomb Expansion, Missile Expansion, Dark/Light
Beam, the beam ammo expansions, Energy Tank, Varia Suit -- the ids in
`receive_items._COUNTED_AMMO_IDS`), this could strand the player below
their true capacity forever: e.g. `/grant_item Missile Launcher` after 8
Missile Expansions had already been received applied raw gains of only 5
missile capacity, since the command's raw gains for the launcher don't
know about expansions already in `items_received`. Every following tick,
`compute_desired_capacities` still saw "8 expansions, no launcher" (the
manual grant never touched `items_received`), so `desired[44]` stayed 0
and `plan_grants` refused to lower the now-higher live capacity -- the
player was capped at 5 missiles instead of 45, with a "capacity is already
above the desired" warning logged every ~0.5s tick indefinitely.

**Fix.** `_cmd_grant_item` no longer touches game memory at command time.
It appends the matched item name to a new session-scoped
`ctx.manual_grants: list[str]` (per-instance, initialized in
`MetroidPrime2Context.__init__` -- unlike `slot_data`'s class-level `{}`
default, this list is *appended* to in place rather than wholesale
replaced, so a shared class-level default would leak across instances).
`_handle_grant_items` builds its `received` list as `ctx.items_received`
plus one `(item_name, ctx.slot)` entry per queued manual grant, appended
after the real items (using `ctx.slot` as the sender makes the "last item"
HUD message read `"<item> acquired"` instead of crediting another player).
The command's `data.progression[0]` special-casing is gone entirely --
`compute_desired_capacities` already applies the k-th progressive stage to
the k-th received copy of an item by name, so appending the bare name is
*more* correct than the command's old behavior, not less. Manual grants
are session-only (never persisted): a client restart forgets them, and
since capacities only ever grow, the game simply keeps whatever it already
has. The command's `has_pending_op()` guard (needed only because the old
path wrote to memory synchronously) is gone; the `IN_GAME` connection-state
check is kept as a user-facing sanity check, though it is no longer load
bearing for correctness.

`plan_grants`'s negative-delta warning is now deduplicated: a module-level
`_last_negative_delta_warning: dict[item_id, (current_capacity,
desired_capacity)]` in `receive_items.py` suppresses repeats of the exact
same triple, so the diagnosis is still logged (immediately, and again if
the numbers change) without spamming every tick forever. The message now
also names the two realistic causes: a manual `/grant_item` from before
this fix, or a save file ahead of the current received-items list.

## P. Pickup identity encoding (bitmask counters)

Section O fixed the *false victory* outcome of the shared additive
counter, but deliberately left the underlying channel unchanged: every
pickup still ADDs `pickup_index + 1` to one counter (item 74), so any
window where the client isn't attached and consuming merges several
pickups into a single number that no longer identifies them.
`location_reconciliation.py` tried to invert that sum against the
server's still-missing locations. Measured against the real 119-pickup
layout (300 randomised trials per cell, `k` pickups collected during one
disconnect), that approach does not hold up:

    missing=119 k=2: dropped 144, misattributed 155, false-goal 1
    missing= 60 k=2: dropped 145, misattributed 153, false-goal 2
    missing= 30 k=2: dropped 163, misattributed 134, false-goal 3
    missing= 10 k=2: dropped  83, misattributed 166, recovered 49
    missing=  4 k=2: dropped   4, misattributed 160, recovered 135

Three things that table shows. (1) Reconciliation is *unreachable* for
roughly half of all collisions: `client.py`'s `0 <= amount - 1 < 119`
branch runs first, so a sum landing back inside the real index range
(indices 4+9 -> 15 -> index 14) is silently credited to a location the
player never touched, and that location's item is sent to whoever the
fill placed it for -- a worse outcome than the bug section O fixed.
(2) `==` narrows but does not close the false goal: indices 50+68 sum to
exactly 120. (3) Mid-game the unique-combination search resolves
essentially never (0/300 with 30+ locations still missing, at any
`max_missed`; `max_missed=8` is actively worse than 3, since larger
subsets manufacture spurious explanations that break uniqueness).

**Why no client-side decoder fixes this.** The obvious refinement --
prefer the smallest-size unique explanation -- was measured too, and
produces *wrong* credits at 10-27%, because preferring size 1 is exactly
the misattribution in (1). The alternative, demanding a globally unique
explanation, cannot be used either: in normal play every single real
pickup's amount has dozens of subset explanations, so it would drop
every ordinary location check. The client is structurally forced to
guess, because summing distinct pickups into one accumulator destroys
their identity. The fix has to be in the encoding, not the decoder.

**Design: one bit per pickup.** Give each pickup index its own bit in
one of several persistent counters, instead of an addend in one shared
counter. Addition of distinct powers of two is bit-set: N pickups
collected during any-length disconnect produce a value that decodes
back to exactly those N indices, with no search, no uniqueness
condition, no `max_missed` ceiling, and no guessing. The goal signal
moves to a counter of its own, so it can never collide with pickup data.

**Hard constraints (verified against the vendored libraries before
choosing the layout).**

1. `ppc_asm.assembler.ppc.li` is `addi rD, r0, SIMM16` and
   `Instruction.compose` asserts `-32768 <= literal < 32768`.
   `all_prime_dol_patches.adjust_item_amount_patch` emits
   `li(r5, abs(delta))`, so *that particular instruction sequence*
   cannot consume an amount above 32767. This was first read as a hard
   15-usable-bit-per-counter cap, but the reserved-ids accounting below
   only leaves 4 counters free -- 119 pickups need >= 30 usable bits per
   counter to fit in 4, not 15. The escape hatch section P originally
   named but declined is therefore taken: `game_interface.py`'s
   `_wide_decrement_patch` composes the amount with `lis`/`ori` instead
   of `li` (both operate on unsigned 16-bit fields, per
   `Instruction.compose`, so masking a 32-bit amount's high/low halves to
   `0xFFFF` can never fail that assert, unlike `li`'s signed 16-bit one),
   hand-rolling assembly around OPR's private `_load_player_state`
   (acceptable since `pyproject.toml` pins `open-prime-rando==0.20.1`
   exactly). This raises the practical ceiling to constraint 2's signed
   32-bit backing field -- comfortably enough for 30 bits. The goal
   counter's tiny, always-small value still goes through OPR's unmodified
   `adjust_item_amount_patch`; only the four pickup counters need the
   wide variant.
2. `retro_data_structures` `Pickup.amount` / `Pickup.capacity_increase`
   are signed 32-bit (`BIG_l`), and `Pickup.absolute_value` defaults to
   `False` -- confirming section O's finding that real pickups add, and
   (per point 1 above) setting the real ceiling the wide consume patch
   raises the practical limit to.
3. `pickup_editing._patch_single_pickup_stage_basic_resources` maps the
   *first* entry of a stage's `resources` onto the native `CScriptPickup`
   (`item_to_give` / `amount` / `capacity_increase`) and only routes
   *extra* resources through `SetInventoryAmount` SpecialFunctions. Each
   pickup here grants exactly one resource, so every pickup keeps using
   the native additive path.
4. Because `capacity_increase == amount` on that path, pickup counters
   raise their own capacity in lockstep and need no client-side top-up
   -- but `powerup_max` (the u32-per-item ceiling table written in
   `patcher_runner.py`) must be raised for each counter or the adds get
   clamped. The goal counter is the exception: a SpecialFunction writes
   its amount without touching capacity, which is the entire reason
   `ensure_goal_counter_capacity` (formerly `ensure_magic_capacity`)
   exists, so it still needs a one-time client top-up -- but only a small
   one, since its value never grows the way a pickup counter's does.
5. `SetInventoryAmount`'s set-vs-add semantics remain unverified (OPR
   uses the same SF with `-1` deltas for conversions, which reads as
   additive, while section O assumed the Credits trigger is an absolute
   set). The design must not depend on the answer: giving the goal its
   own counter makes "amount nonzero on that counter" correct either
   way. This also removes section O's latent false-*negative* -- under
   add semantics, finishing while detached yields `120 + leftovers`,
   which the current `== 120` check would never recognise as victory.
6. `game_interface.read_inventory` already reads all 109 items in one
   pass, so reading 5 counters instead of 1 costs nothing.
7. `game_interface`'s remote-execution batching (`grant`'s existing
   mechanics, reused by shape for `consume_counters`) already packs
   `(item_id, delta)` pairs into one ~420-byte remote-execution body and
   returns leftovers; the wide pickup-counter patch is ~5 instructions
   and the narrow goal-counter patch ~4, so all 5 counters fit in a
   single body with room to spare.
8. `powerup_should_persist` is a byte-per-item table, so *any* item id
   can be made save-persistent -- the counter supply is not limited to
   ids named `PersistentCounterN`. (In practice, per the reserved-ids
   accounting below, only 67-70 and 74 end up used.)

**Reserved ids (found during implementation, not by the ISO scan below --
this section's first draft used all eight `PersistentCounterN` ids,
67-74, and the conflict below was only caught during implementation,
before anything was generated or played).** `data/logic_database/header.json`
-- randovania's own resource
database, already vendored in this world -- gives an authoritative
`resource_database.items[*].extra.item_id` allocation table, and it
reserves three ids in this range that are very much alive: 71
(`Temporary1`, "Temporary Missile") and 72 (`Temporary2`, "Temporary
Power Bomb") back Missile/Power Bomb Expansion's `"temporary"` field in
`data/pickup_database.json`, driven by OPR's ammo-conversion machinery;
73 (`MissileLauncher`) is this world's own "missiles unlocked" flag
(`items.py`'s Missile Launcher entry, `client/receive_items.py`'s
`_MISSILE_LAUNCHER_FLAG`). Routing pickup bits into any of the three
would corrupt real gameplay state, not just multiworld bookkeeping.
74 (`Multiworld`) is reserved too, but deliberately -- it's this design's
goal counter now, see below. That leaves only 67-70 -- four ids, not
eight -- which is the reason the slot allocation below needs 30 bits per
counter instead of 15. `test_pickup_encoding.py`'s
`TestReservedItemIdsDisjoint` derives this same reserved set (header.json
plus every id appearing in `ITEM_TABLE`'s gains) programmatically and
asserts `PICKUP_COUNTER_ITEMS` can never silently overlap it again.

**Slot allocation.** 119 pickups / 30 bits = 4 counters (only 67-70 are
actually free; see "Reserved ids" above).

    pickup index i  ->  item  PICKUP_COUNTER_ITEMS[i // 30]
                        amount 1 << (i % 30)

    PICKUP_COUNTER_ITEMS = (67, 68, 69, 70)
                            PersistentCounter1..4
    index   0.. 29 -> 67 bits 0..29
    index  30.. 59 -> 68 bits 0..29
    index  60.. 89 -> 69 bits 0..29
    index  90..118 -> 70 bits 0..28   (70 bit 29 stays unused)

    goal signal -> PersistentCounter8 (74), amount 1, "nonzero means goal"

Max value any single pickup counter can hold is `2**30 - 1`, comfortably
inside constraint 2's signed 32-bit backing field. The goal counter moves
onto item 74 -- section O's old single shared counter -- now that real
pickups have moved off it onto 67-70: randovania's table confirms nothing
else claims 74, and it is the one id in this whole range whose in-game
behavior this project has actually exercised, so it needs no further
verification.

**Verified against a retail ISO.** The question header.json cannot answer
-- whether the vanilla game itself touches 67-70 -- was settled by
scanning a retail NTSC ISO directly. Only two Echoes script object types
can name an inventory item (`Pickup.item_to_give` and
`SpecialFunction.inventory_item_parm`; confirmed by walking every
dataclass in `retro_data_structures.properties.echoes.objects` for a
`PlayerItemEnum`-typed field), so the scan decoded every `PCKP` and
`SPFN` instance in all 291 areas across all 12 MLVLs. Items 50, 51 and
60-74 have **zero** references -- 67-70 and 74 are untouched by vanilla
scripts, and there is headroom (50/51, 60-66) if more counters are ever
needed. The DOL's own per-item tables agree: a retail NTSC DOL already
carries `powerup_max = 0x7FFFFFFF` and `powerup_should_persist = 0` for
items 67-74, i.e. these are generic unused counters, and the persist byte
is the write that actually matters (`COUNTER_MAX_CAPACITY` matches
vanilla's ceiling so the patcher can never lower it).

One caveat, and one lesson. The caveat: this covers script layers and the
two DOL tables, not a disassembly of compiled game code, so it cannot
*prove* no routine touches those slots -- but `persist = 0` on all of
them is strong evidence the retail game has no reason to. The lesson:
item **73 also shows zero script references**, so an ISO scan alone would
have cleared it, while it is emphatically not free at the randovania/AP
layer. The two checks are complementary and neither substitutes for the
other, which is why `TestReservedItemIdsDisjoint` stays.

**New module: `metroidprime2/pickup_encoding.py`** (pure, no Dolphin, no
AP imports beyond `constants`/`locations`), replacing
`location_reconciliation.py` as the single source of truth for the
layout, imported by both `patch_data.py` (generation time) and
`client.py` (runtime):

- `counter_and_amount(pickup_index) -> tuple[int, int]` -- the item id
  and bit value for one index; the only place `// BITS_PER_COUNTER` and
  `% BITS_PER_COUNTER` appear.
- `decode(inventory) -> Decoded` -- over `PICKUP_COUNTER_ITEMS`, turns
  nonzero amounts into `indices: list[int]`, `deltas: list[tuple[int,
  int]]` (the exact negatives to consume), and `stray: list[tuple[int,
  int]]` for bits that decode past the last real index or at/above
  `BITS_PER_COUNTER`.
- Module-level assert that `len(PICKUP_COUNTER_ITEMS) * BITS_PER_COUNTER
  >= len(LOCATION_TABLE)`, so adding locations fails loudly at import
  rather than silently aliasing two pickups onto one bit.

**Changes, file by file.** (Every goal-counter item below was superseded
before this section shipped -- see "Goal detection rides on no counter at
all" at the end of the section. The pickup-bitmask half is as built.)

- `constants.py`: `MAGIC_ITEM` / `GOAL_SENTINEL_AMOUNT` out;
  `PICKUP_COUNTER_ITEMS = (67, 68, 69, 70)`, `BITS_PER_COUNTER = 30`,
  `GOAL_COUNTER_ITEM = 74`, `GOAL_SIGNAL_AMOUNT = 1`,
  `PICKUP_COUNTER_MAX_CAPACITY = 0x40000000`,
  `GOAL_COUNTER_MAX_CAPACITY = 65535`, `ALL_COUNTER_ITEMS` (5 ids) in.
- `patch_data.py` `_pickup_modification`: emit
  `{"item": counter, "amount": bit}` from `counter_and_amount(
  node.pickup_index)` instead of `{"item": 74, "amount": index + 1}`.
- `patcher_runner.py`: loop the `powerup_should_persist` byte write and
  the `powerup_max` u32 write over all five counters (currently a single
  pair of writes for item 74), using `PICKUP_COUNTER_MAX_CAPACITY` for
  the four pickup counters and `GOAL_COUNTER_MAX_CAPACITY` for the goal
  counter; `_add_goal_trigger` targets `GOAL_COUNTER_ITEM`
  (`PlayerItemEnum.PersistentCounter8`) with `int_parm2 =
  GOAL_SIGNAL_AMOUNT`.
- `game_interface.py`: `consume_magic_item(amount)` becomes
  `consume_counters(deltas)`, dispatching per item id -- OPR's unmodified
  `adjust_item_amount_patch` for the goal counter (always a tiny value),
  a new `_wide_decrement_patch` (constraint 1's escape hatch: `lis`/`ori`
  instead of `li`) for the four pickup counters -- batched the same way
  `grant` batches its own patches, returning leftovers and respecting the
  body budget, but built separately from `grant` since neither path
  touches capacity the way `grant` does. `ensure_magic_capacity` becomes
  `ensure_goal_counter_capacity`, a one-time top-up of item 74 only
  (pickup counters self-manage, per constraint 4).
- `client.py` `_handle_magic_item_amount` -> `_handle_pickup_counters`:
  read the goal counter first (`nonzero` -> `CLIENT_GOAL`, then consume
  it), otherwise `decode(inventory)`, send one `LocationChecks` with
  every decoded index, then consume the deltas. Keep the existing
  send-before-consume ordering. Delete `_GOAL_INDEX_THRESHOLD` and its
  import-time assert. Warn (don't drop the good bits) when `stray` is
  non-empty, and warn when a decoded index isn't in
  `ctx.missing_locations` -- that is the signature of the one residual
  failure mode below.
- `receive_items.py:162`: the `item_id == constants.MAGIC_ITEM` skip in
  `compute_desired_capacities` becomes a membership test against all
  five counter ids, so no counter can ever be driven by the item model
  (see section N for why that guard matters).
- `__init__.py` `generate_output`: add `"pickup_encoding":
  "bitmask-v1"` to the options.json metadata dict.

**Compatibility gate.** The per-pickup resource mapping is baked into
config.json at *generation* time while the DOL writes happen client-side
at *patch* time, so a new client fed an old `.apmp2` would patch an ISO
whose pickups still use the summed encoding and then misread every
pickup as a bitmask. The client must read `pickup_encoding` from
options.json and refuse to patch (clear message: regenerate with a
matching apworld version) when it is absent or unrecognised. Silent
divergence here costs location checks, so this is a hard error, not a
warning. An existing save carrying a stale item-74 amount from section
O's old encoding is inert once 74 is read only as the goal counter's
"nonzero means goal" signal, never summed against anything else -- but
the seed must be regenerated and the ISO re-patched regardless, which is
acceptable pre-release (M4 is not yet signed off).

**Residual failure modes, honestly stated.** Collecting the *same*
pickup twice without the client consuming in between would carry
(`2^k + 2^k == 2^(k+1)`) and decode as a neighbouring index. That needs
collect -> reload an older save -> collect, entirely while detached, and
the counters are save-persistent so an ordinary death/reload rolls the
counter back in lockstep with the pickup's own collected state. It is
strictly rarer and more detectable than today's equivalent (the same
sequence currently adds `2 * (index + 1)` and mis-credits silently);
the "decoded index was not in `missing_locations`" warning above is the
tell. Beyond that, the channel is lossless for any number of pickups
collected over any disconnect length.

**Tests.** (As with the file-by-file list above, the goal-counter cases
named here were superseded by the end-of-section goal-detection fix; the
pickup-bitmask cases are as built.) `test_pickup_encoding.py` (new): round-trip every index 0..118
through `counter_and_amount` -> `decode`; assert all 119
`(counter, bit)` pairs are distinct; assert a full counter's value
(`2**30 - 1`) round-trips through `decode` cleanly (constraint 1's
escape hatch, as an executable check); multi-bit and multi-counter
decodes; stray-bit reporting; `TestReservedItemIdsDisjoint`, which
derives the reserved-id set from `data/logic_database/header.json` plus
every id in `ITEM_TABLE`'s gains and asserts `PICKUP_COUNTER_ITEMS` is
disjoint from it (the regression test for this section's own near-miss
with item 73) while asserting `GOAL_COUNTER_ITEM` (74) specifically IS
that set's "Multiworld" entry, not exempted wholesale.
`test_game_interface.py` gains `TestConsumeCounters`, asserting
`_wide_decrement_patch` actually assembles (against real DOL addresses)
for a full 30-bit counter value, and that `consume_counters` routes goal
vs. pickup counters through the right patch in one batched body.
`test_patch_data.py:80`'s `test_pickup_indices_cover_0_to_118_exactly_once`
gets rewritten against the new `(item, amount)` pairs. `test_goal_detection.py`
loses its sentinel-arithmetic cases and gains: goal counter nonzero ->
goal, goal counter zero + pickup bits -> checks only, goal declared once,
every nonzero counter consumed regardless of branch, and the
multi-pickup disconnect case that motivated all of this (several bits
across several counters -> every location reported, none invented).
`test_location_reconciliation.py` is deleted with its module.

**In-game validation (M4).** Manual MT08 (rewritten for this section):
detach the client, collect one pickup per counter group, reattach, and
confirm every location is credited and nothing else is; then two more
pickups sharing already-used counters, then one with the client attached.
MT02/MT03 cover reaching the ending, per the goal-detection fix below.

**Removed by this section.** `client/location_reconciliation.py`,
`test/test_location_reconciliation.py`,
`constants.GOAL_SENTINEL_AMOUNT`, `constants.MAGIC_ITEM`,
`client._GOAL_INDEX_THRESHOLD` and its assert, and the
implausible-amount warning branch -- there is no longer an amount the
client cannot interpret. The goal-detection fix below removes
`patcher_runner._add_goal_trigger` / `goal_trigger_installed`,
`game_interface.ensure_goal_counter_capacity`, and the goal-counter
constants this section introduced.

**Goal detection rides on no counter at all (bug fix, folded in here).**
Reported from real play (M4 in-game validation), and the *opposite*
failure from section O's premature goal: the player beat the game and
reached the Credits, but the client still reported the game as unfinished.
Section J's in-ISO mechanism 1 never actually fired -- `_add_goal_trigger`
put its Timer/`SetInventoryAmount` on a newly-created `"AP Goal Trigger"`
script layer, that layer never activated, and so the sentinel was never
written. The first draft of this section kept mechanism 1 alive on a
dedicated goal counter (item 74, isolated from the pickup bitmask so it
could never alias); that isolation was sound, but it was isolating a
trigger that does not run. Mechanism 2 replaces it outright:

* `patcher_runner._add_goal_trigger` / `goal_trigger_installed` and their
  splice into `patch_iso_with_ap` are gone; patching no longer touches the
  Credits area (the per-counter DOL writes remain, for
  `PICKUP_COUNTER_ITEMS` only).
* `constants.GOAL_SENTINEL_AMOUNT` / `GOAL_COUNTER_ITEM` /
  `GOAL_SIGNAL_AMOUNT` / `ALL_COUNTER_ITEMS` are replaced by
  `constants.GAME_END_AREA_INDICES`. Item 74 stays reserved and unused: an
  existing save may still carry a stale amount on it from section O, and
  nothing reads it any more.
* `game_interface.ensure_goal_counter_capacity` is gone with it --
  capacity top-up existed only because `SetInventoryAmount` sets amount
  without touching capacity. Every pickup counter's capacity self-manages
  via the native additive pickup path (constraint 4), so
  `consume_counters` now has a single instruction shape
  (`_wide_decrement_patch`) rather than one per counter kind.
* New `EchoesInterface.current_area_id()` reads `CStateManager::m_nextAreaId`
  at `cstate_manager_global + 0x16A0` (`versions.AREA_ID_OFFSET`; verified
  against the shipped NTSC DOL: `SetCurrentAreaId` at 0x80041728 moves the
  old id to +0x16A4 and stores the new one at +0x16A0). New
  `client.py::_handle_check_goal` mirrors `worlds/metroidprime`'s
  "current level == End_of_Game" check: goal when the current MLVL is
  Temple Grounds and the area index is one of the five post-Dark-Samus
  `!!game_end_part*` areas. It runs on every IN_GAME tick and in the
  IN_MENU branch (the ending can read as "in menu").

Constraint 5 (the set-vs-add semantics of `SetInventoryAmount`) therefore
stops mattering: nothing writes a goal signal into the inventory at all.
Between this and the bitmask encoding above, section O's premature goal is
structurally impossible -- no counter amount can declare victory -- and the
false negative is fixed too, since the goal is read straight from game
state with no dependence on an injected script layer activating.
`test_goal_detection.py` covers the new detector alongside the pickup
counters, `test_game_interface.py` covers the new offset read, and manual
MT03 pokes the area field directly.
