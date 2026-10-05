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
| 13 | *(retired)* | -- | -- | -- | Varia Suit is not an item (2026-10-04): it is the default suit and the player always has it; slot 12 is pinned to 1 as the Defense Up counter. AP id left unassigned. |
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

STK modes (`item_pool.py`): numeric N -> keys 1..N in pool, N+1..9 precollected; `all_bosses` -> 9 keys locked onto the 9 boss locations; `all_guardians` -> 3 keys locked onto 43/79/115, 6 precollected. Starting inventory: `DEFAULT_STARTING_ITEMS` (Power Beam, Charge Beam, Combat Visor, Scan Visor, Morph Ball) pushed via `push_precollected`; `start_inventory` copies of those are ignored.

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

`death_link` (client/death_link.py, client/client.py): own-death detection polls `EchoesInterface.get_current_health()` (CPlayerState+`versions.HEALTH_OFFSET`, `0x14` -- verified against OPR's `apply_reverse_energy_tank_heal_patch`'s `health_offset` for `Game.ECHOES`, not derived) against 0, debounced by `is_pending_death_link_reset` exactly like `worlds/metroidprime`. An incoming DeathLink writes `-1.0` to that same field via `EchoesInterface.set_current_health()` (kept only so the debounce below still arms -- there's no remote-execution-safe way to force a death through the normal item-grant call path) **and** flips `CPlayerState::alive` false via `EchoesInterface.set_alive()` (`versions.ALIVE_OFFSET`/`ALIVE_BIT_MASK`), which is what actually triggers the game's death handling. Earlier versions of this client claimed the raw health poke alone "mirrors Prime 1's `set_alive(False)`" -- that was wrong: Prime 1's client never touches health, only an alive bit at a different CPlayerState offset, and a health-only poke here was confirmed in-game to zero the HUD without killing the player, leaving the camera and gun model stuck (bypasses the real damage/death pipeline entirely). `set_alive`'s bit position (CPlayerState+0x4, high bit) is derived from PrimeDecomp/echoes's CPlayerState.hpp struct layout, not confirmed against a live game -- no decompiled function in that project yet sets `alive` false to check against; re-derive empirically if DeathLink still doesn't kill the player after this change. `on_deathlink` **must** also set `is_pending_death_link_reset = True`: without it the next poll tick sees `health <= 0` with the flag clear and re-broadcasts the incoming death straight back to the group (`CommonContext.send_death` has no debounce), so one player's death ping-pongs around the DeathLink group. `worlds/metroidprime`'s `on_deathlink` has this exact bug; do not "restore parity" with it. The flag clears itself once health goes positive on respawn, so a later organic death still sends normally. `set_current_health`/`set_alive` also guard `DolphinException`, like every other Dolphin access in that class. `build_static_context`: `trick_levels[short] = trick_level.value if per-trick == 0 else per_trick - 1`. Groups: Goal, Item Pool, Entrances, Logic, Tricks, Cosmetic.

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
 "practice_mod": "disabled", "auto_enabled_elevators": bool(world.options.pre_scan_elevators.value), "two_way_portals": bool(world.options.portal_rando), "inverted_mode": False,
 "damage_changes": {"energy_per_tank": E, "safe_zone_heal_per_second": 1.0, "dangerous_energy_tanks": ...,
                    "dark_world_damage": float(dark_aether_damage), "dark_suit_protection": dark_suit_damage / dark_aether_damage},
 "world_changes": [...], "string_changes": [],
}
```
`world_changes` also carries, for each of the 17 configurable nodes, an AreaChange `translator_gates` entry `{"translator": <color lowercased, or "unlocked">, **node.extra.get("gate_instances", {})}` (randovania `prime2_opr` `create_translator_gates`) -- the color/"unlocked" comes from `world.translator_gate_assignment` when `translator_gate_rando` reassigned that gate, else its vanilla color (section E.2); plus, when `door_lock_rando`/`elevator_rando`/`portal_rando` reassigned anything, `door_locks`/`elevators`/`portals` AreaChange entries from `world.dock_rando` (sections E.1/E.3), and the top-level `two_way_portals` key is `bool(world.options.portal_rando)`.
(`beam_configuration`, `custom_items`, `game_options_defaults` left at OPR defaults.)

`starting_items_config`: sum `gains` of every `precollected_items[player]` item (k-th copy of a progressive applies stage k) plus mandatory `{8:1, 9:1, 0:1, 22:1, 15:1}`; always write Varia (12) as exactly 1, clamp Energy Tank to 14; emit `[{"item": id, "capacity": n}]`.

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
    current_area_id()                 # u32 at cstate+0x16A0 (CStateManager::m_nextAreaId), a TAreaId index
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
0. Goal check (also run in the IN_MENU branch): `current_mlvl() == TEMPLE_GROUNDS_MLVL` and `current_area_id() in GAME_END_AREA_INDICES` -> `StatusUpdate CLIENT_GOAL` once.
1. `has_pending_op()` -> skip tick.
2. `inv = read_inventory()`; `amount, cap = inv[74]`; `ensure_magic_capacity(cap)` once per connection.
3. `amount > 0`: `index = amount - 1`; `0..118` -> `LocationChecks[base+index]` then `consume_magic_item(amount)`; anything else is implausible, reconciled against `missing_locations` or warned about, then consume.
4. Else compute deltas and `grant` one body.
5. `notification_manager.handle_notifications()` when idle; tracker `Set` of current MLVL.
State machine: DISCONNECTED -> WRONG_GAME (build string mismatch, log once) -> WRONG_SEED (uuid mismatch) -> IN_MENU -> IN_GAME. Commands: `/export_iso`, `/status`, `/test_hud`, `/mp2_debug_inventory`. `main()` parses `apmp2_file` + optional ISO, `setup_libs()`, sets `ctx.auth` from `options.json`. Register in `__init__.py`: `Component("Metroid Prime 2 Client", func=run_client, component_type=Type.CLIENT, file_identifier=SuffixIdentifier(".apmp2"), icon="Metroid Prime 2")`, `icon_paths["Metroid Prime 2"] = "ap:worlds.metroidprime2/assets/icon.png"`.

Goal detection is **one mechanism: a memory read** (the in-ISO sentinel mechanism 1 never fired in practice, so it was removed -- section O).
* `EchoesInterface.current_area_id()` reads `CStateManager::m_nextAreaId` at `cstate_manager_global + 0x16A0` (a TAreaId *index* into the active MLVL's area list, not the MREA asset id; `SetCurrentAreaId`'s shipped NTSC DOL body at 0x80041728 stores it there, verified by disassembly).
* The client declares the goal when `current_mlvl() == TEMPLE_GROUNDS_MLVL` and `current_area_id() in constants.GAME_END_AREA_INDICES`. Echoes has no separate end-of-game MLVL: the Credits room is `!!game_end_part3` (randovania Temple Grounds/Credits asset id `CREDITS_MREA`) inside Temple Grounds, and the four sibling `!!game_end_part*` areas are also post-Dark-Samus, so accepting all five avoids depending on catching one ending segment in a 0.5 s poll. Same shape as `worlds/metroidprime`'s "current level == End_of_Game" check.

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

**M4 – Goal, UT, docs.** Goal detection (memory read of the current area -- section J / section O); `CLIENT_GOAL` after credits; Universal Tracker loads and shows reachability; `docs/setup_en.md` + `docs/en_Metroid Prime 2 Echoes.md` (supported ISOs, Python/OPR install, patch flow, limitations); `write_spoiler` lists pre-placed keys.

**M5 – Distribution.** Frozen-build wheel bootstrap in `setup_libs`; apworld build excluding `tools/` and `test/`.

---

## L. Risks and resolutions

1. **Per-edge damage vs randovania's cumulative energy**: AP checks each damage requirement against max energy, so dark-world chains are more lenient than randovania. Default `damage_strictness = medium` like the starter preset; document.
2. **Negated events folded to True**: over-permissive only after the event fires; `NEGATED_EVENT_OVERRIDES` hook for tuning.
3. **Two pickups between polls** sum into an ambiguous amount. 0.5 s poll, detect implausible values and warn. v2: also read the pickup MemoryRelays (Prime 1 style) as an exact second signal.
4. **Goal offsets** (was "unknown"): resolved -- current area is `CStateManager::m_nextAreaId` at `cstate_manager_global + 0x16A0`, verified by disassembling `SetCurrentAreaId` in the shipped NTSC DOL; see section J/O. The script-injected sentinel mechanism was removed after it failed to fire in real play.
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

## M. `missile_expansions_unlock_launcher`, `power_bomb_expansions_unlock_power_bombs`, and item map dots

Three independent options, done together only because they touch overlapping files.

**`missile_expansions_unlock_launcher` (item pool option).** Off by default, matching Randovania: a Missile Expansion grants nothing (0 capacity, launcher flag stays off) until the Missile Launcher itself is collected. The rule "missile capacity requires the launcher (or, with the option, at least one expansion)" is **duplicated in two places that must be kept in sync**:

- `logic/item_mapping.expression`'s `Missile` branch (generation-time logic: what counts toward a `Missile` resource requirement). Takes a `missile_expansions_unlock_launcher` kwarg, threaded through `logic/requirements.StaticContext`/`build_static_context` and both of that module's `item_mapping.expression(...)` call sites (`_compile_item`, `_reductions_for`). `build_static_context`'s two callers (`logic/regions.create_regions`, `logic/dock_rando._build_compiler`) pass `bool(world.options.missile_expansions_unlock_launcher)`.
- `client/receive_items.compute_desired_capacities` (the in-game grant: what capacity/flags actually get written to the OPR inventory). Takes the same flag as its third parameter, read by `client.py`'s `_handle_grant_items` out of slot_data (`ctx.slot_data.get("missile_expansions_unlock_launcher", False)` -- the `.get` default keeps old `.apmp2` files working). Lands in slot_data automatically since `_slot_data_option_names()` includes every non-base option.

The logic database itself needed **no edit**, but it does gate on the launcher in two places, which is easy to miss: `MissileLauncher` (item id 73) has zero requirement references in any of the 9 region files, yet `header.json`'s `resource_database.requirement_template` uses it in `Destroy Seeker Locks` and `Destroy Underwater Seeker Locks` -- templates reached from **15 requirement sites** (Agon Wastes x4, Sky Temple Grounds x4, Temple Grounds x2, Torvus Bog x2, Dark Torvus Bog x1, plus the Seeker Missile Blast Shield dock type). Those gate on the launcher *item*, not on `Missile` capacity, so widening only the `Missile` expression would have left logic **stricter than the patched game** at all 15 (a Seeker Launcher + one expansion really does break those locks once the client sets slot 73). Both expressions therefore share one `item_mapping._effective_launcher` predicate, so they cannot drift apart. An audit of all 52 item short names the database actually references confirms `MissileLauncher` is the only main-item-style gate the option touches; `PowerBomb` has the same shape (a counted-ammo expression gated on a main pickup) but was, at the time, deliberately left alone (no equivalent option had been asked for) -- see below for where that changed.

Consequence for **precollected** items: `patch_data.starting_items_config` sums raw `gains_for` over `multiworld.precollected_items`, so a precollected Missile Expansion (e.g. via `start_inventory`) writes capacity into item 44 but never sets the launcher flag (item 73) on its own -- `gains_for("Missile Expansion", ...)` only ever touches id 44. With the option on, `starting_items_config` now also sets id 73 to 1 whenever id 44's capacity is nonzero, so the ISO's own starting inventory is consistent with what the option grants at runtime; without this, the client would have to correct it on the very first tick, and `plan_grants` logs a spurious "capacity is already above desired" warning when it does.

**`power_bomb_expansions_unlock_power_bombs` (item pool option, the Power Bomb counterpart).** Same option shape and default (off) as the missile toggle, and the same duplicated-rule discipline: `item_mapping.expression`'s `PowerBomb` branch (via a new `_effective_power_bomb` predicate) and `client/receive_items.compute_desired_capacities`'s Power Bomb block must agree, so both take the flag and both are exercised end to end in the tests. `StaticContext`/`build_static_context` gained a matching `power_bomb_expansions_unlock_power_bombs` field/parameter, threaded through both `item_mapping.expression(...)` call sites in `requirements.py` (`_compile_item`, `_reductions_for`) exactly like the missile flag, and both `build_static_context` callers (`regions.create_regions`, `dock_rando._build_compiler`) pass `bool(world.options.power_bomb_expansions_unlock_power_bombs)`.

The key **contrast** with missiles, worth recording because it is the fact most likely to be re-litigated: `MissileLauncher` is its own logic-DB resource (item id 73), separately gated in the two `requirement_template`s described above (15 usage sites) -- so the missile option has to widen *two* independent expressions (`MissileLauncher`'s own `_effective_launcher` check, and `Missile`'s count formula) via one shared predicate, or logic would be stricter than the patched game at those 15 sites. **Power Bombs have no such main-item resource at all.** `PowerBomb` (id 43) is the only power-bomb-shaped DB item; there is no `requirement_template` anywhere that gates on a bare "Power Bomb collected" boolean the way the two Seeker Lock templates gate on `MissileLauncher`. So the entire gate for this option lives in exactly one place, `item_mapping.expression`'s `PowerBomb` branch (guarded by `_effective_power_bomb`, which -- unlike `_effective_launcher` -- has only that one caller and says so in its own docstring); nothing under `data/` needed inspection or change, and `DB_ITEM_TO_AP_ITEM` gained no new entry.

`patch_data.starting_items_config` needed a **subtractive** fix that missiles did not, for a reason specific to how OPR treats each ammo type. Missile capacity (id 44) is inert without the separate launcher flag (id 73) being set, so a precollected Missile Expansion writing capacity into id 44 alone was always harmless in-game (unusable ammo, just a latent number) -- the existing fix is purely additive (also set id 73 when the option is on). Power Bombs have no such flag: `open_prime_rando`'s `PlayerItemEnum.PowerBomb` (43) is directly settable and `StartingItemConfig.amount` defaults to `capacity`, so a precollected Power Bomb Expansion with **no** unlock mechanism at all (the option didn't exist yet) would have started the player with a genuinely usable power bomb count that neither logic nor the client's `compute_desired_capacities` credited -- worse than inert, and it made `plan_grants` log its "capacity is already above desired" warning every tick once the client noticed capacity 43 sitting above its own computed desired value of 0. So `starting_items_config` now drops id 43 entirely (rather than leaving whatever `gains_for` summed for expansions alone) whenever `power_bomb_expansions_unlock_power_bombs` is off and no main `Power Bomb` was itself precollected -- determined from the same `precollected_items` loop that already walks every item, not a second pass. The identical failure mode existed for missiles all along (just masked by the launcher flag keeping the capacity unusable rather than making it a live warning), so the same subtractive treatment was added to id 44 symmetrically in this change: `missile_expansions_unlock_launcher` off and no main `Missile Launcher` precollected now also drops id 44. This is a **behavior change**: `start_inventory` with only an expansion (either kind) no longer starts the player with usable ammo unless the corresponding unlock option is on -- see `patch_data.starting_items_config`'s docstring and `test/test_patch_data.py`'s updated `TestStartingItemsWithPrecollectedMissileExpansionAndOptionOff.test_launcher_flag_not_set`.

**`item_map_dots` (cosmetic Choice `off`/`on`/`always`, default `on`; replaced `show_item_locations` 2026-10-04).** The first version of this feature, `show_item_locations`, only rewrote the `visibility_mode` of open-prime-rando's pickup map icons and never drew a single dot in-game. Disassembling the retail DOL showed why. Nothing renders OPR's icons at all:

- `CMappableObject::Draw` (NTSC `fn_800BB924`, PAL 0x800BB9B8) picks a texture with a switch over object types 0x10..0x19 (jump table NTSC 0x803B3638, PAL 0x803B4A80, which OPR lists as `map_icon_jumptable` but never uses). OPR's custom pickup type 0x12 lands in the case for types without an icon (texture -1), so it draws nothing whatever its visibility.
- retro-data-structures' `ObjectVisibility` uses Prime 1's names. In Echoes `CMappableObject::GetIsVisibleToAutoMapper` (NTSC `fn_800BB53C`) reads 0 never, 1 always, 2 visited-or-mapped-or-map-station (what vanilla doors use), 3 door visited, 4 visited. OPR's hardcoded `AreaVisitOrMapStation` is 1, i.e. *always*. So the old "fix" set a value that would have shown the dot in every drawn room, if the dot had been drawn at all.

Everything else was already in OPR 0.20.1: each pickup gets a `TranslatorDoorLocation` SpecialFunction that the pickup sends `DECR` on collection (`pickups/location.py`). That handler (`CScriptSpecialFunction::AcceptMapObjectVisibility`) sets a per-editor-id flag in `CMapWorldInfo`, and the translator gate draw case (type 0x17) skips drawing when that flag is set. The SpecialFunctions land in each SAVW's `unmappable_objects` (OPR's `AreaPatcher` rebuilds the SAVW), which is the list `CMapWorldInfo` saves those flags for. The dot texture `pickup_map_icon.TXTR` (64x64 IA4) is added to every pak holding the translator icon, which includes GGuiSys.pak.

`client/item_map_dots_patch.py` adds the missing renderer piece, following randomprime's `patch_set_pickup_icon_txtr`. It points the jump table entry for 0x12 at a 6-7 instruction cave that loads the dot texture into r30, sets up the translator case's flag-lookup arguments for the pickup's editor id, and branches to that case's `bl`. The vanilla tail then hides collected pickups. NTSC and PAL allocate registers differently (object r9/r28, `CMapWorldInfo` r3/r29), so `client/versions.py`'s `ItemMapDotAddresses` carries both. The patch refuses a DOL whose table entry or `bl` isn't the expected one. `pickup_icon_visibility_installed` (the old `_add_map_icon` wrapper) writes the visibility mode. `on` writes mode 2, so dots follow the door-icon rule: they show in visited rooms and map-station-revealed rooms, and a `full_map` reveal doesn't count. `always` writes mode 1 (OPR's own value): a dot shows whenever its room is drawn, which only differs from `on` under `full_map`, because `CMapWorld::DrawAreas` only walks the objects of rooms it draws. `patcher_runner.item_map_dots_installed` applies both halves unless options.json's `item_map_dots` is `constants.ITEM_MAP_DOTS_OFF` (`.apmp2` files from when it was a Toggle carry `true`/`false`, read as on/off). Verified by patching both real ISOs and disassembling the result; MT19 is the in-game check.

**`item_map_dots: map_station` (2026-10-04, the fourth value).** Dots only once the world's map station has been used, whatever has been visited and whatever `map_visibility`/`unvisited_room_names` say. No vanilla visibility mode does this: `CMappableObject::GetIsVisibleToAutoMapper` (NTSC `fn_800BB53C`, PAL 0x800BB5D0; one caller, `CMapWorld`'s area draw loop) answers mode 2 with `worldVis || IsAreaVisible(object's area)`, where `worldVis` is `IsWorldVisible(area, dark)` = `IsMapped(area) || (CMapWorldInfo+0x48 mMapStationUsed && !dark)`, and the visited half of `IsAreaVisible` is what lets a visited room through. Modes 0/1/3/4 are never/always/door/visited-only. So `client/item_map_dots_patch.apply_map_station_dol_patch` adds a mode 5: the compare ladder sends every mode above 4 to `li r3, 1` (always) through a `bge` (a scan of every Echoes MAPA in the NTSC ISO found no vanilla object above mode 4; one MAPA failed to parse and was skipped); that `bge` is retargeted at an unreachable `b` the compiler left right after the mode-1 case, which now jumps to a two-instruction cave, `lbz r3, 0x48(r30); b <epilogue>` (r30 holds the `CMapWorldInfo&` on both versions; the two functions are byte-identical 0x94 apart). It reads the flag directly rather than `worldVis`, so dark-world rooms (same MLVL and `CMapWorldInfo` as their light world) show dots too, and `IsMapped` areas don't. Mode 5 isn't an `ObjectVisibility` member; its EnumAdapter is non-strict, so `pickup_icon_visibility_installed` writes the raw int. The patch refuses a DOL whose `bge`/`b` differ from vanilla. The flag is per world, so each world's station only unlocks that world's dots; a world with no station would never show any. (An earlier draft of this paragraph said only Agon/Torvus/Sanctuary have stations, from grepping the logic DB for room names containing "Map Station"; wrong, Temple Grounds' station is in Hive Chamber A.) Verified by patching both real ISOs in memory and disassembling; MT19's `map_station` variant is the in-game check (unrun).

**`map_visibility` (the player-facing option, folded from two Toggles).** `show_item_locations` originally shipped alongside a second, independent `reveal_map` Toggle (`config.json`'s `map_visibility.reveal_map_at_start`, unrelated to this one's name beyond both concerning the map) with the interaction noted above: the map doesn't draw a room at all until the room itself has been revealed, so in an unvisited room `show_item_locations`'s dot was only visible when `reveal_map` was *also* on. That made "item dots without the revealed map" a real, selectable, but meaningless combination -- indistinguishable from vanilla. The two Toggles were folded into one `options.py` Choice, `MapVisibility` (`vanilla`/`full_map`/`full_map_and_items`), making the invalid combination unrepresentable: `patch_data.make_rando_configuration` sets `reveal_map_at_start` for anything other than `option_vanilla`, and `MetroidPrime2World.generate_output` sets the internal `show_item_locations` flag only for `option_full_map_and_items`. (Since 2026-10-04, item dots are their own option, `item_map_dots`, and `full_map_and_items` is an `alias_` of `full_map` so old YAMLs still generate.)

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

## O. Premature goal completion (bug fix)

Reported from real play (M4 in-game validation): the multiworld was marked
complete after collecting only 6 of 9 Sky Temple Keys, without reaching the
Credits area. Root cause was in `client.py`'s `_handle_magic_item_amount`,
not in the Sky Temple Key/gate logic (which is untouched by
`sky_temple_keys` -- that option only controls pool-vs-precollected
distribution, per its own docstring; the physical gate always needs all 9,
matching vanilla).

The goal check was `index >= _GOAL_INDEX_THRESHOLD` (i.e. `amount >= 120`)
rather than an exact match against the sentinel the in-ISO Credits trigger
actually writes (`constants.GOAL_SENTINEL_AMOUNT`, 120). Section J's own
risk 3 already documented the mechanism that can produce a bogus amount:
"two pickups between polls sum into an ambiguous amount" -- `amount` is a
single memory cell set (not incremented) by whichever pickup's script last
ran, consumed via a relative `adjust_item_amount_patch(74, -amount)` a
poll tick later, and `has_pending_op()` only guards the client's *own*
in-flight writes, not a second in-game pickup script firing between this
tick's read and its consume. Two Sky Temple Keys (or any two pickups)
collected inside the same 0.5s poll window can therefore leave item 74 at
some garbage value derived from both pickups' assigned amounts. Under the
old `>=` check, any such value landing above 119 was read as the goal
sentinel instead of falling into the "implausible value... warn and
consume" branch the code already had (visible in the pre-fix `else` branch
being dead code: `index = amount - 1` can never be negative here, since
the caller only calls this function when `amount > 0`, so every amount from
120 to infinity fell into the goal branch, not the warning one). PLAN.md's
own prose for this mechanism had the identical bug baked into the original
spec (`"index >= 119 -> goal sentinel"` alongside `"> 120 -- implausible"`,
which is unreachable once phrased as two `>=`/`>` comparisons against the
same boundary) -- it was never caught because M4's in-game validation
hadn't happened yet.

**Fix.** `GOAL_SENTINEL_AMOUNT = 120` moved to `constants.py` as the single
source of truth (`patcher_runner._add_goal_trigger` now reads it from
there instead of a private module constant), and `client.py`'s goal branch
is now `elif amount == constants.GOAL_SENTINEL_AMOUNT` -- anything past the
sentinel now correctly falls into the existing implausible-value warning
branch instead of declaring victory. `client.py` also asserts at import
time that the sentinel is exactly one past `_GOAL_INDEX_THRESHOLD`, so the
two constants can't silently drift apart again. This does not fix the
underlying poll race (still section J risk 3, still unresolved -- a
same-window double pickup can still cost a missed/misattributed location
check); it only ensures that race can no longer be misread as game
completion. `test_goal_detection.py` covers the exact-match boundary
(pass-through at the last real index, exact sentinel, sentinel+1, and a
clearly-garbage large amount) and that every amount is still consumed
regardless of which branch handled it.

**Confirmed trigger, and a correction to the mechanism above.** The
player confirmed what actually happened: they reconnected to the server
after a stretch playing with Dolphin running but the client not attached,
and got a burst of items delivered at once on reconnect. The magic item is
not a `SetInventoryAmount`-style absolute write for real pickups the way
the Credits trigger is -- `pickup_editing.py`'s per-pickup stage sets
`pickup.amount = first.amount; pickup.capacity_increase = first.amount`,
which is `CScriptPickup`'s ordinary additive pickup behavior (the same
mechanism a real Missile Expansion uses: amount and capacity both increase
by a fixed delta on pickup, they aren't set outright). So every real
pickup ADDS `pickup_index + 1` to whatever item 74 already holds;
`consume_magic_item` zeroes it back out with a matching negative delta
once the client has read and reported it. This means risk 3's window
isn't a tight ~0.5s poll race -- it's "however long the client isn't
attached and consuming while the player keeps collecting pickups". Two or
more real pickups (their indices summed, e.g. 45+1 + 87+1 = 134) collected
during any disconnect trivially clears 119 and, under the old `>=` check,
read as game completion on the very first poll after reconnecting.

The exact-match fix above still fully closes the false-victory outcome
for this case -- any accumulated sum other than exactly 120 now warns
instead of declaring goal, regardless of how large or how it arose. It
does **not** recover the location checks that contributed to a dropped
sum: a summed value can't be decomposed back into which pickup indices
produced it, so those checks are silently lost rather than reported (the
player's own in-game inventory for whatever was collected is not itself
in question -- that's granted for real by the same pickup -- only the
server-side location-check credit for it). Recovering that would need a
different signal than this single accumulator (e.g. reading the game's
actual per-item inventory as ground truth and reconciling against
already-checked locations on reconnect); not implemented, flagged here
rather than attempted blind.

**Follow-up: `client/location_reconciliation.py`.** The per-item-inventory
idea above doesn't actually work for this design -- physical pickups in
this world never grant a distinguishable real item at all (only the
shared magic counter, see `constants.MAGIC_ITEM`'s docstring), so the
native inventory can't tell you which *locations* were collected, only
which *items* the AP server has already sent you (a fully separate,
downstream signal). The actual usable second source of truth is simpler
and was already sitting in `ctx.missing_locations`: the server's live set
of this player's still-unchecked locations. Only those pickups are still
physically collectible in-game (a checked one's object is already gone),
so they're the only candidates that could have contributed to a fresh,
unexplained sum.

`location_reconciliation.find_unique_missed_locations(amount,
candidate_indices, max_missed=8)` is a bounded 0/1-knapsack subset-sum
search (counting DP over size x sum, reconstructed backward) that looks
for a combination of 1..8 candidate pickups whose `index + 1` values sum
to `amount`. It returns the combination only if it's the *unique* one --
if two or more different combinations could explain the same number
(easily possible once several plausible values are in play), or none can,
it returns `None` and the caller falls back to the original warn-and-drop
behavior unchanged. This is a correctness-critical function (a wrong
answer credits a location, and sends its item to whoever the fill placed
it for, that was never actually collected), so `max_missed` doubles as a
sanity bound: a real disconnect losing 9+ checks at once isn't a case
worth searching for even if a unique combination happened to exist.
`test_location_reconciliation.py` cross-checks the DP against a brute-force
`itertools.combinations` search over 200 randomized small instances (not
just the targeted unique/ambiguous/impossible cases) precisely because of
that stakes asymmetry.

`client.py`'s `_handle_magic_item_amount` calls this from the existing
"implausible value" branch: it builds `candidate_indices` by translating
`ctx.missing_locations` (AP location ids) back to 0-based pickup indices
(filtering to this world's own id range, defensively, since a combined
tracker view could in principle carry other games' location ids in the
same set), and on a unique match sends one `LocationChecks` message
covering every recovered index instead of the warning. Nothing changes
about goal detection itself -- reconciliation only ever runs in the
"amount is not a single valid pickup index" bucket, since any amount in
1..119 already matches a single real index in the first branch regardless
of `missing_locations`.

**Follow-up: `/grant_item`/`/getitem` removed entirely -- it duplicated a
setting AP already has.** The client was first renamed `/grant_item` ->
`/getitem` and gated behind `ctx.finished_game`, matching the convention
other worlds' clients use for a post-goal item-request command. But
`MultiServer.py` already has its own `!getitem` (a chat-style command sent
to the server, not the local client), gated by host.yaml's
`disable_item_cheat`: it synthesizes a `NetworkItem` server-side
(`_cmd_getitem`, sender slot -1) and sends it exactly like an item from
another player. Because our client's item-receiving pipeline
(`compute_desired_capacities`/`plan_grants`, section J/M) treats every
received item identically regardless of sender, that server command
already worked for this world with zero code of our own -- our local
`/getitem` was a strictly worse duplicate (no host.yaml gating reachable
from the client at all, since `item_cheat` isn't broadcast to clients the
way `release`/`remaining`/`collect` permissions are -- there is no
`ctx.missing_locations`-style signal for it).

Removed: `MetroidPrime2CommandProcessor._cmd_getitem`, the
`ctx.manual_grants: list[str]` attribute and its `__init__` default, and
its fold-in inside `_handle_grant_items` (which now just builds `received`
from `ctx.items_received` directly, and returns early on `not
ctx.items_received` rather than also checking `manual_grants`). Checked
every other `_cmd_*` in `MetroidPrime2CommandProcessor` against
`MultiServer.py`'s server-side commands and `CommonClient.py`'s base
`ClientCommandProcessor` for the same kind of duplication: `_cmd_status`/
`_cmd_reconnect`/`_cmd_test_hud`/`_cmd_mp2_debug_inventory`/
`_cmd_export_iso` are all Dolphin/local-hardware concepts the server has
no equivalent for (`_cmd_reconnect` reconnects to *Dolphin*, distinct from
`CommonClient`'s own `_cmd_connect`/`_cmd_disconnect` which target the AP
server); `_cmd_deathlink`/`_cmd_test_deathlink` follow the standard
per-world DeathLink pattern used across dozens of other worlds' clients
(no shared base-class or server implementation exists to defer to). None
of those are duplicates. The "late arrival in received order" shape the
old `/grant_item` regression tests covered (a launcher/main pickup arriving
after its expansions) still applies to any real AP item, so it lives on as
the reordered-receive assertions in `test_client_receive.py`'s
`TestMissileGating`/`TestPowerBombGating`.

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

## Q. Sky Temple Key hint scans (foundation for lore hints)

Goal: the 9 Luminoth pillars in Sky Temple Gateway (Sky Temple Grounds)
each name where one Sky Temple Key really is -- in whichever player's
world it landed -- and scanning a pillar sends a real AP hint to the
server. Parallels `worlds/metroidprime`'s `artifact_hints`
(`Config.make_artifact_hints` for text, `MetroidPrimeInterface.get_scans`
+ `MetroidPrimeClient.handle_artifact_hints` for detection). **No DOL
patch**: text goes in through OPR's existing `string_changes`, detection
is a pure memory read of state the game already keeps.

### Q.1 Facts (verified 2026-09-26, do not re-derive)

* **Scan state lives in `CPlayerState`.** PrimeDecomp/echoes
  `CPlayerState::SPersistentState::vec` is an `rstl::vector<SScanState>`,
  `SScanState = {u32 scan_asset_id; u8 progress; u8 flag; pad[2]}` (8
  bytes), sorted ascending by id (binary-searched by `GetScanTime`/
  `SetScanTime`). `progress == 255` means scan complete (`SetScanTime`
  stores `255*t`; loading a save restores complete scans as 255). The
  first 4 entries are placeholder ids 0..3; the rest is
  `gpMemoryCard->GetScanStates()`, i.e. every SCAN listed in any SAVW.
* **Offsets, identical NTSC and PAL** (disassembled from both retail
  DOLs): `ScanStates__12CPlayerStateFv` is `addi r3,r3,0x59C; blr`
  (NTSC 0x800851DC, PAL 0x80085318); `GetScanTime` reads the element
  count from `CPlayerState+0x5A0` and the data pointer from
  `CPlayerState+0x5A8` (NTSC 0x80085068, PAL 0x800851A4), indexes with
  `slwi 3` (stride 8) and loads progress as a u8 from element+4. So:
  count @ +0x5A0, capacity @ +0x5A4, data @ +0x5A8.
* **Pillar STRG -> SCAN ids** (STRG ids from randovania
  `games/prime2/exporter/hints.py::_SKY_TEMPLE_KEY_SCAN_ASSETS`, which
  are actually STRG ids; SCAN ids read from the retail NTSC and PAL
  ISOs -- identical on both, each SCAN's `ScannableObjectInfo.string`
  names exactly one of these STRGs, and every one is in the Sky Temple
  Grounds SAVW so the game tracks it):

      Key 1  STRG 0xD97685FE  SCAN 0x856AD9A4
      Key 2  STRG 0x32413EFD  SCAN 0x6E5D62A7
      Key 3  STRG 0xDD8355C3  SCAN 0x819F0999
      Key 4  STRG 0x3F5F4EBA  SCAN 0x634312E0
      Key 5  STRG 0xD09D2584  SCAN 0x8C8179DE
      Key 6  STRG 0x3BAA9E87  SCAN 0x67B6C2DD
      Key 7  STRG 0xD468F5B9  SCAN 0x8874A9E3
      Key 8  STRG 0x2563AE34  SCAN 0x797FF26E
      Key 9  STRG 0xCAA1C50A  SCAN 0x96BD9950

  Key N is `items.py`'s "Sky Temple Key N" (randovania's
  `echoes_items.SKY_TEMPLE_KEY_ITEMS` order, same as OPR's logbook
  renames).
* **Lore/keybearer scans (for the follow-up, recorded now so nobody
  needs the ISO again).** Every `hint` node in the vendored logic DB
  with `extra.string_asset_id` maps 1:1 to a SAVW-tracked SCAN, same ids
  NTSC/PAL (STRG -> SCAN):

      0x24E69725->0xC108FC20  0xA272E58B->0x479C8E8E  0x5324575E->0xB6CA3C5B
      0x692E362E->0x8CC05D2B  0x150E8DB8->0xF0E0E6BD  0xEFBA4480->0x0A542F85
      0xDE525E1D->0x3BBC3518  0xC3576EA5->0x26B905A0  0xF2BF7438->0x17511F3D
      0x62CC4DC3->0x872226C6  0x0405EE3F->0xE1EB853A  0xBF77D533->0x5A99BE36
      0xA9909E66->0x4C7EF563  0x742B0696->0x91C56D93  0xF5535CEA->0x10BD37EF
      0x3E0F8F4F->0xDBE1E44A  0xE3B417BF->0x065A7CBA  0x987884FB->0x7D96EFFE
      0x65206511->0x80CE0E14  0x8E9FCFAE->0x6B71A4AB  0x39E3A79D->0xDC0DCC98
      0x28E8C41A->0xCD06AF1F  0xCF593D9A->0x2AB7569F  0x58C62CB3->0xBD2847B6
      0x45C31C0B->0xA02D770E  0x54C87F8C->0xB1261489  0xD25C0D22->0x37B26627
      0x49CD4F34->0xAC232431  0x9F94AC29->0x7A7AC72C  0x82919C91->0x677FF794
      0x939AFF16->0x76749413

* **STRG layout.** A pillar STRG has 3 strings (scan popup, then the
  logbook body twice). randovania writes `[hint, "", hint]`
  (`create_simple_logbook_hint`); copy that exactly. Markup:
  `&push;&main-color=#RRGGBB[AA];text&pop;`. randovania's Echoes colors:
  item `#FF6705B3`, world/player `#d4cc33`, location `#FF3333`.
* **Server `CreateHints`** (`MultiServer.py` ~2238): `player` = the
  location's owner, `locations` = that player's location ids.
  `HINT_PRIORITY` is allowed only when the hinted *item* belongs to the
  sender (true for our own STKs, in any world). Hinting someone else's
  item is only allowed in our own world and must use
  `HINT_UNSPECIFIED` -- matters for lore hints later, not for STKs.
  `notify_hints(only_new=True)` dedups, so re-sending after a reconnect
  is harmless.

### Q.2 Option

`options.py`: `SkyTempleKeyHints(Choice)`, display name "Sky Temple Key
Hints", `option_disabled = 0`, `option_scanned = 1`,
`option_precollected = 2`, `default = option_scanned`,
`alias_false = option_disabled`, `alias_true = option_scanned`.
Docstring: scanning a pillar in Sky Temple Gateway shows where that key
is and (scanned) sends the hint to the server; precollected gives all
key hints at start; disabled replaces the pillars' text with a
non-hint. Field `sky_temple_key_hints` in `MetroidPrime2Options` right
after `sky_temple_keys`; add to the "Goal" `OptionGroup`. It flows into
slot_data automatically via `_slot_data_option_names()`.

### Q.3 Shared module `metroidprime2/hint_scans.py`

Pure data + pure functions, no top-level AP imports beyond `TYPE_CHECKING`
(unit-testable without a multiworld, like `pickup_encoding.py`).

* `@dataclass(frozen=True) class HintScan: strg_id: int; scan_id: int`
* `SKY_TEMPLE_KEY_HINT_SCANS: tuple[HintScan, ...]` -- the 9 rows
  above, index `n-1` is key `n`.
* `LORE_HINT_SCAN_IDS: dict[int, int]` -- the STRG->SCAN table above
  (unused by runtime code for now; guarded by a test).
* `SCAN_COMPLETE = 255`
* `sky_temple_key_locations(world) -> list[Location | None]` -- length
  9; entry `n-1` is the filled location holding this player's "Sky
  Temple Key n" (search `world.multiworld.get_filled_locations()` once
  for `item.player == world.player and item.name in STK_ITEM_NAMES`;
  ignore locations with `address is None`), or `None` if it is
  precollected / not placed anywhere (item links). This is the single
  source of truth for both the pillar text and slot_data, so they can
  never disagree.
* `encode_hint_scans(entries: dict[int, tuple[int, int]]) -> dict[str, list[int]]`
  and `decode_hint_scans(raw) -> dict[int, tuple[int, int]]`:
  `{scan_id: (location_player, location_id)}` <-> JSON-safe
  `{str(scan_id): [location_player, location_id]}`. `decode` must
  tolerate `None`/missing (older slot_data) -> `{}`.
* `newly_completed_hints(scan_progress: dict[int, int], hint_scans: dict[int, tuple[int, int]], already_sent: set[int]) -> tuple[set[int], dict[int, list[int]]]`
  -> (scan ids newly completed, `{location_player: sorted location
  ids}`). Only `progress >= SCAN_COMPLETE`, only ids in `hint_scans`,
  skip `already_sent`. Pure; the caller updates `already_sent`.

The generic `hint_scans` shape (scan id -> location to hint) is the
lore-hint foundation: a future lore feature only adds entries (and,
because of the CreateHints rules above, probably a third per-entry
field for status); the client path does not change.

### Q.4 Generation side

* `patch_data.py`: new `_sky_temple_key_string_changes(world) -> list[dict]`,
  wired into `make_rando_configuration`'s `"string_changes"` (currently
  `[]`). One `{"strg_id": scan.strg_id, "strings": [text, "", text]}`
  per key. Text, with `key = colorize("#FF6705B3", "Sky Temple Key n")`:
  - option disabled: `f"{key} is lost somewhere in Aether."` (randovania's
    `hide_stk_hints` wording) -- always overwrite: the vanilla riddles
    describe vanilla key spots and would mislead.
  - location found: `f"{key} is in {owner}'s {loc}."` where `owner` is
    `"your"` (no "'s") when `location.player == world.player`, else the
    sanitized `multiworld.player_name[location.player]` in `#d4cc33`
    plus `'s`; `loc` is the sanitized `location.name` in `#FF3333`. Use
    `_sanitize` (strips `&`, `;`, newlines -- they'd break STRG markup;
    no length cap).
  - `None` and the key is in `multiworld.precollected_items[player]`:
    `f"{key} is already in your possession."`
  - otherwise: `f"{key} is lost somewhere in the multiverse."`
  Put the colorize helper next to `_sanitize`.
* `__init__.py`:
  - `post_fill`: if option is `precollected`, add every `STK_ITEM_NAMES`
    entry whose location is not `None` to `self.options.start_hints.value`
    (Main.py reads start_hints after post_fill -- same as Prime 1).
  - `fill_slot_data`: `slot_data["hint_scans"] = encode_hint_scans(...)`
    containing, only when option is `scanned`, `{SKY_TEMPLE_KEY_HINT_SCANS[n].scan_id: (loc.player, loc.address)}`
    for each non-`None` location; `{}` otherwise.

### Q.5 Client side

* `client/versions.py`: `SCAN_STATES_OFFSET = 0x5A0` (count; capacity at
  +4, data pointer at +8), `SCAN_STATE_SIZE = 8`,
  `SCAN_STATES_MAX_COUNT = 2048` (sanity cap; retail has ~820), with a
  comment citing the Q.1 disassembly.
* `client/game_interface.py`: `EchoesInterface.read_scan_progress() -> dict[int, int] | None`.
  `_player_state_pointer()`; one 12-byte read at
  `+SCAN_STATES_OFFSET` -> `count, capacity, data_ptr`; return `None`
  unless `0 < count <= min(capacity, SCAN_STATES_MAX_COUNT)` and
  `0x80000000 <= data_ptr < 0x81800000`; one `count*8` read; unpack
  `">IBBxx"` into `{scan_id: progress}`. `DolphinException`/`None` read
  -> `None`, same as `read_inventory`.
* `client/client.py`:
  - Context fields `hint_scans: dict[int, tuple[int, int]]` and
    `sent_hint_scans: set[int]`; in `on_package("Connected")` set
    `hint_scans = decode_hint_scans(slot_data.get("hint_scans"))` and
    reset `sent_hint_scans = set()`.
  - `async def _handle_hint_scans(ctx)`: return early (no Dolphin read)
    if `set(ctx.hint_scans) <= ctx.sent_hint_scans`; read progress (None
    -> return); `newly_completed_hints(...)`; for each player send
    `{"cmd": "CreateHints", "locations": ids, "player": player, "status": HintStatus.HINT_PRIORITY}`
    in a single `send_msgs`; then add the ids to `sent_hint_scans`;
    `logger.info` once per newly scanned hint.
  - Call it in `_handle_game_ready` right after `_send_mlvl_datastorage`
    (it's a pure read, independent of the pending-op protocol).

### Q.6 Tests

* `test/test_hint_scans.py`: 9 distinct strg/scan ids in key order;
  `LORE_HINT_SCAN_IDS` covers every vendored DB `hint` node's
  `extra.string_asset_id` (so a DB resync that adds one fails loudly)
  and is disjoint from the STK table; encode/decode round trip and
  `decode(None) == {}`; `newly_completed_hints` ignores progress < 255,
  unknown ids, already-sent ids, and groups by player.
* `test_patch_data.py` (reuse its existing generation bases): 9 STK
  string changes with the right strg ids and `[t, "", t]` shape; own
  world says "your"; disabled wording; numeric `sky_temple_keys` mode
  -> "already in your possession" for precollected keys; a player/
  location name containing `&`/`;` is sanitized.
* slot_data: `hint_scans` has one entry per placed key with the right
  (player, address) under `scanned`, `{}` under `disabled` and
  `precollected`; `precollected` puts the placed keys into start_hints.
* `test_game_interface.py`: `read_scan_progress` against its existing
  fake Dolphin client: happy path, null player state, count 0, count >
  cap, bad data pointer, `DolphinException`.
* Client (style of `test_client_grant_message.py`): CreateHints sent
  once per newly completed scan, grouped by player, not re-sent on the
  next tick, and no Dolphin read once everything's sent.

### Q.7 Docs / validation

Add the option and a short "Sky Temple Key hints" paragraph to
`docs/en_Metroid Prime 2 Echoes.md`. Manual validation still needed in
Dolphin: patch a seed, visit Sky Temple Gateway, confirm pillar text and
that the server receives the hint after the scan completes (and not
from a partial scan).

## R. Translator lore hints

Builds on section Q. The 22 colored Luminoth lore holograms (the `hint`
nodes with `extra.translator`; NOT translator gates, NOT the 9 Keybearer
corpses) get their text replaced with a hint about a progression item, and
scanning one sends that hint to the server through the same `hint_scans`
path as the Sky Temple Key pillars.

### R.1 Facts (verified 2026-09-26)

* The 22 holograms (region / room, translator, STRG -> SCAN; SCAN ids from
  the Q.1 lore table):

      Agon Wastes / Mining Plaza                  Amber   0x24E69725 -> 0xC108FC20
      Agon Wastes / Mining Station B              Amber   0xA272E58B -> 0x479C8E8E
      Agon Wastes / Mining Station A              Amber   0x5324575E -> 0xB6CA3C5B
      Agon Wastes / Portal Terminal               Amber   0x692E362E -> 0x8CC05D2B
      Agon Wastes / Agon Energy Controller        Amber   0xEFBA4480 -> 0x0A542F85
      Great Temple / Main Energy Controller       Violet  0xC3576EA5 -> 0x26B905A0
      Sanctuary Fortress / Sanctuary Entrance     Cobalt  0xF2BF7438 -> 0x17511F3D
      Sanctuary Fortress / Hall of Combat Mastery Cobalt  0x0405EE3F -> 0xE1EB853A
      Sanctuary Fortress / Main Research          Cobalt  0xBF77D533 -> 0x5A99BE36
      Sanctuary Fortress / Watch Station          Cobalt  0x742B0696 -> 0x91C56D93
      Sanctuary Fortress / Main Gyro Chamber      Cobalt  0xF5535CEA -> 0x10BD37EF
      Sanctuary Fortress / Sanctuary Energy Controller Cobalt 0x3E0F8F4F -> 0xDBE1E44A
      Temple Grounds / Meeting Grounds            Violet  0x987884FB -> 0x7D96EFFE
      Temple Grounds / Path of Eyes               Violet  0x8E9FCFAE -> 0x6B71A4AB
      Temple Grounds / Transport to Agon Wastes   Violet  0x39E3A79D -> 0xDC0DCC98
      Temple Grounds / Fortress Transport Access  Violet  0xCF593D9A -> 0x2AB7569F
      Torvus Bog / Path of Roots                  Emerald 0x45C31C0B -> 0xA02D770E
      Torvus Bog / Underground Tunnel             Emerald 0x54C87F8C -> 0xB1261489
      Torvus Bog / Torvus Energy Controller       Emerald 0xD25C0D22 -> 0x37B26627
      Torvus Bog / Gathering Hall                 Emerald 0x49CD4F34 -> 0xAC232431
      Torvus Bog / Training Chamber               Emerald 0x9F94AC29 -> 0x7A7AC72C
      Torvus Bog / Catacombs                      Emerald 0x82919C91 -> 0x677FF794

* The tracked SCAN only completes once translated: in Meeting Grounds the
  SCAN 0x7D96EFFE belongs to the `POIN "Translator Yes"` instance (popup
  "Luminoth Lore translated."), which is only live with the translator.
  Lore STRGs have 3 strings (popup, "Data transferred...", body);
  randovania writes `[hint, "", hint]` for these too -- copy that.
* `CreateHints` rejects the WHOLE packet if any entry breaks a rule, and
  another player's item may only be hinted with `HINT_UNSPECIFIED`
  (`HintStatus` value 0; `HINT_PRIORITY` is 30). So each hint needs its
  own status and the client must group sends by (player, status).
* `Main.py` order: fill -> `post_fill` -> progression balancing ->
  `pre_output` -> `generate_output` (threaded, per world) ->
  `fill_slot_data`. Balancing can move items after `post_fill`, so hint
  choice must happen at/after `pre_output`.

### R.2 Option

`options.py`: `TranslatorLoreHints(Choice)`, display name "Translator
Lore Hints", `option_off = 0`, `option_my_items = 1`, `option_any = 2`,
`default = option_my_items`. Only progression items (`item.advancement`)
are ever hinted.
* `my_items`: each hologram names where one of *your* progression items
  is, in any player's world.
* `any`: the pool is your progression items anywhere **plus** other
  players' progression items placed in *your* world (the most the server
  allows).
* `off`: holograms keep their vanilla lore text; no hints.
Field `translator_lore_hints` right after `sky_temple_key_hints`; add it
to the "Goal" `OptionGroup` next to `SkyTempleKeyHints` (or a new
"Hints" group holding both -- pick one, keep it tidy).

### R.3 `hint_scans.py`

* Give `HintScan` a `room: str = ""` field (e.g. `"Temple Grounds -
  Meeting Grounds"`) and add `TRANSLATOR_LORE_HINT_SCANS:
  tuple[HintScan, ...]`, the 22 rows above in that order. Test: its STRG
  set equals exactly the DB `hint` nodes that have `extra.translator`,
  each row's scan equals `LORE_HINT_SCAN_IDS[strg]`, and `room` matches
  the node's region/area.
* slot_data entries grow a status: `{scan_id: (location_player,
  location_id, status)}` <-> `{str(scan_id): [player, location, status]}`.
  `decode_hint_scans` accepts old 2-element entries as
  `HintStatus.HINT_PRIORITY`. STK entries (section Q) are written with
  `HINT_PRIORITY` explicitly.
* `newly_completed_hints` returns `{(location_player, status): sorted
  location ids}` instead of `{player: ids}`.
* `translator_lore_hint_locations(world) -> list[Location | None]`
  (length 22, index i is `TRANSLATOR_LORE_HINT_SCANS[i]`), computed once
  and cached on the world (e.g. `world._translator_lore_hints`):
  - `off` -> 22 `None`s (and callers don't write anything, see below).
  - candidates = every filled location in the multiworld with
    `address is not None`, `item.advancement`, and
    `item.player == world.player`; under `any` also every location with
    `location.player == world.player` holding another player's
    progression item. Exclude this player's Sky Temple Key items unless
    `sky_temple_key_hints` is `disabled` (the pillars already cover them).
    Also skip `skip_balancing` items (expansions and other bulk
    progression). Dedupe, sort by `(location.player, location.address)`.
  - `rng.shuffle(candidates)`, then take in order skipping any repeat of
    `(item.player, item.name)` (one Energy Tank hint, not four), up to
    22; pad with `None`. (Added after the first build: plain
    `rng.sample` spent most holograms on expansions and Energy Tanks.)
  - RNG: `random.Random(f"{world.multiworld.seed}:{world.player}:translator_lore_hints")`
    -- deterministic per seed but NOT drawn from `world.random`, so toggling
    this option never reshuffles the rest of the patch (the OPR `seed`
    field etc.). Comment why.
  - Lazy compute is safe: its first caller is `generate_output` (after
    balancing). Also call it from `pre_output` so the choice is pinned
    before the threaded output stage. Initialize the cache attribute
    where `sky_temple_key_locations` is initialized.

### R.4 Generation side

* `patch_data.py`: rename the three `_STK_*_COLOR` constants to shared
  `_HINT_ITEM_COLOR` / `_HINT_PLAYER_COLOR` / `_HINT_LOCATION_COLOR`.
  New `_translator_lore_hint_text(world, location, colored=True) -> str`:
  - location: `f"{item_owner} {item} can be found in {loc_owner} {loc}."`
    where `item_owner` is `"Your"` or `"<player>'s"`, `loc_owner` is
    `"your"` or `"<player>'s"`, names/item/location sanitized with
    `_sanitize` and colorized (player color on player names only) when
    `colored`.
  - `None`: `"The Luminoth have nothing more to tell you."`
  New `_translator_lore_string_changes(world)`: `[]` when `off`,
  otherwise one `{"strg_id", "strings": [t, "", t]}` per hologram.
  `make_rando_configuration`'s `string_changes` = STK changes + these.
* `__init__.py`:
  - `pre_output`: call `translator_lore_hint_locations(self)`.
  - `fill_slot_data`: add each non-`None` hologram hint to `hint_scans`
    as `(loc.player, loc.address, HINT_PRIORITY if loc.item.player ==
    self.player else HINT_UNSPECIFIED)`.
  - `write_spoiler`: when not `off`, a "Translator Lore Hints
    (<player>):" block, one line per hologram: `f"    {room}: {plain text}"`
    using `colored=False`.

### R.5 Client

`client.py::_handle_hint_scans` sends one `CreateHints` per
`(player, status)` group with that status (single `send_msgs` list).
Nothing else changes.

### R.6 Tests

* `test_hint_scans.py`: table checks above; 3-tuple encode/decode round
  trip + 2-element backward compat; grouping by (player, status).
* Selection (use the existing generation test bases, 2 players where
  needed): `off` -> no lore string changes and no lore slot_data entries;
  `my_items` -> every chosen location holds this player's progression
  item, 22 distinct; `any` with a second player -> candidates include
  foreign progression items in this world, and those entries carry
  `HINT_UNSPECIFIED`; STK exclusion follows `sky_temple_key_hints`;
  determinism (same seed -> same choice) and the text/slot_data agree
  (same locations). Fewer candidates than holograms -> padded with the
  "nothing more" text and no slot_data entry.
* Client: mixed statuses produce separate `CreateHints` messages.

### R.7 Excluding bulk/indistinguishable-copy items (2026-09-28)

Originally only `skip_balancing` items (Missile/Power Bomb/Dark/Light/Beam
Ammo Expansions) were excluded from the candidate pool by classification,
plus a conditional `exclude_own_stk` that only dropped this player's own
Sky Temple Keys when `sky_temple_key_hints != disabled` (letting STK
locations leak into the lore-hint pool as a fallback when the pillars
themselves were turned off) -- Energy Tank was never excluded at all
(plain `progression`, not `skip_balancing`), so a hologram could point at
"an Energy Tank" out of 14 indistinguishable copies, which isn't
actionable.

`hint_scans.py`'s `_LORE_HINT_EXCLUDED_ITEM_NAMES` (`STK_ITEM_NAMES |
{"Energy Tank"}`) now excludes both by name, unconditionally -- Sky Temple
Keys are excluded regardless of `sky_temple_key_hints` (own or foreign,
under `any`), and Energy Tank is excluded the same way `skip_balancing`
expansions already were. The `exclude_own_stk`/`SkyTempleKeyHints` import
this replaced is gone from `hint_scans.py` entirely.

## S. `sky_temple_keys_required` (MP1-style reduced key requirement)

Ported from `worlds/metroidprime`'s `required_artifacts`/`has_group`
pattern: a separate knob from `sky_temple_keys` (section F) that lets
fewer than all 9 Sky Temple Keys actually be *required* to finish the
game, independent of how many of the 9 `sky_temple_keys` shuffles into
the pool as findable pickups versus pre-collects for free. Requested
directly (MP1 has this; MP2 vanilla and every prior tool checked --
randovania's `prime2`/`prime2_opr` games, open-prime-rando -- did not).

**Why this is a real difficulty reduction, not just relocation.**
Randovania's own `LayoutSkyTempleKeyMode.num_keys` looks similar but
isn't: it only controls how many of the 9 are shuffled-vs-precollected,
and the *physical* Sky Temple Gateway door still hardcodes "all 9" no
matter the mode, so the player ends up holding all 9 regardless (some
found, some free) -- confirmed by reading
`randovania/games/prime2/generator/pickup_pool/sky_temple_keys.py` and
grepping open-prime-rando for any "gateway"/counter patch (none exists).
This project's own `sky_temple_keys` option (section F) already matches
that same present-vs-precollected shape. `sky_temple_keys_required`
instead patches the in-game gate itself, so a lower value genuinely means
fewer key *locations* ever need to be found before Dark Samus 3/4 is
reachable -- the other keys still exist and can still be collected
(nothing is removed from the pool), they simply stop being necessary.

**The in-game mechanism (verified against a retail NTSC-U ISO via
`retro_data_structures`/open-prime-rando's `PatcherEditor`, Temple
Grounds/Sky Temple Gateway MREA).** An `AdvancedCounter` named "Count Keys
Returned" (`Default` layer) increments once per Sky Temple Key whose
`PlayerItem` amount reads 1: 9 "\[IN\] Query Key Return" `ConditionalRelay`
objects (one per key) are re-evaluated from scratch whenever "Initiate
Returned Key Tests" (a `SequenceTimer` in the `All columns` layer) pulses
them with `SetToZero` -- on room load and after a key is inserted -- so
this naturally also covers keys the player already held on first arrival,
not just ones inserted in front of the player. The counter's `Open`
message to a `Switch` named "Got All Keys ?" -- which starts the
"Returned All Keys" `SequenceTimer` that lowers the ring of columns and
unlocks everything downstream (elevator to Sky Temple, Dark Samus 3/4) --
is wired from the counter's 9th internal state (`InternalState08`; state
N corresponds to N+1 keys held, confirmed by state 2, the 3rd, driving
the "Returned 3 Keys" HUD message via a separate connection on the same
counter). Moving that one connection to an earlier internal state
(`InternalState{required-1:02d}`) is the entire patch: every query relay,
the per-key column-raising visuals (`All columns` layer), and the
"Returned N Keys" HUD messages are all untouched and still track every
key the player actually holds, up to 9 -- they just no longer gate
progress past `required`. (The room also has several unrelated "\[OUT\]
Has 8 Keys" `Counter`s fed by a `Temporary keys` layer's "Check Key N"
relays, one set per key excluded -- an 8-of-9 "final key" detector for
cinematic purposes, confirmed unrelated by tracing incoming/outgoing
connections; not touched.)

**HUD memo text.** The "Returned N Keys" memos' STRGs hardcode the
remainder as `9 - N` ("3 Sky Temple Keys have been returned. You must find
6 more."), which would be wrong for `required < 9`.
`_rewrite_return_memos` finds each memo through the counter's `Activate`
connection from `InternalState{N-1:02d}` and rewrites its STRG to
`required - N` remaining; at or past `required` (the gate is open) the second
line becomes "You can now enter the Sky Temple." rather than "find 0 more".
The 9-key "All Sky Temple Keys have been returned" memo is untouched.
Checked against a real NTSC-U ISO (in-memory, not in-game).

**Where this lives, and why not in open-prime-rando.** The user maintains
a fork of open-prime-rando (already carrying an unreleased
`feature/warp-to-start` branch) and the pinned dependency
(`open-prime-rando[nod]==0.20.1` in `pyproject.toml`) is a released PyPI
version, not a local/path install of either checkout on disk -- so a
change made only in the fork's source wouldn't actually run until a new
release is cut and the pin bumped. This project already has a precedent
for exactly this situation: `client/warp_patch.py`'s "open-prime-rando has
no equivalent" docstring, which reimplements warp-to-start's SCLY half
directly against the client's own `PatcherEditor` instance and hooks it
into `open_prime_rando.echoes.patcher._apply_patches` via a monkeypatched
`register_world_changes` (`client/patcher_runner.py`'s
`warp_to_start_installed` context manager) rather than waiting on an OPR
release. `client/sky_temple_key_gate_patch.py` follows the identical
shape (`set_sky_temple_key_requirement`/`register`,
`patcher_runner.sky_temple_keys_required_installed` wrapping
`register_world_changes` the same way) -- simpler than warp-to-start
since this feature needs no DOL patch at all, only one more registered
SCLY function, so there is no "DOL half" to this module. Like
`warp_to_start`, this is a candidate to upstream into the OPR fork later;
not done here since the pinned release wouldn't pick it up regardless.

**Config plumbing.** `sky_temple_keys_required` (options.py, `Range`
1-9, default 9) is resolved (and clamped -- see below) by
`item_pool.sky_temple_keys_required_count`, which is also where
`item_pool.sky_temple_keys_present_count` now lives (a small refactor:
the existing numeric-mode branch of `_apply_sky_temple_keys` calls it
too, instead of duplicating `int(mode)`). Like `warp_to_start`/
`item_map_dots`/`spring_ball` before it, the resolved value has no
home in OPR's `RandoConfiguration` (`config.json` is validated with
`extra="forbid"`), so `__init__.py`'s `generate_output` writes it into
`options.json` instead, where `patcher_runner.patch_iso_with_ap` reads it
back (default 9 if absent, so a `.apmp2` produced before this option
existed still patches unchanged).

**Clamping.** `sky_temple_keys_required_count` clamps the raw option
value down to `sky_temple_keys_present_count(world)` -- the same
present-vs-precollected count `_apply_sky_temple_keys` uses -- so a seed
can never require more keys than could possibly be held (e.g.
`sky_temple_keys=all_guardians` only ever makes 3 keys distinguishable
from "already held for free"; requiring 9 there would be trivially
satisfied by the 6 precollected keys alone regardless, since
`CollectionState.__init__` processes precollected items unconditionally
-- clamping to 3 instead keeps the option's stated number meaningful).

**Logic side.** The generated logic database (from randovania's
`prime2_opr` data, section C) has exactly one edge anywhere that mentions
a `TempleKeyN` resource -- verified by grepping every region JSON's
connections for the substring -- Sky Temple Grounds/Sky Temple Gateway's
"Spawn Point/Front of Teleporter" -> "Elevator to Sky Temple", whose
requirement is a flat `and` of the 9 `TempleKeyN` resources (each amount
1) plus a `DarkWorld1` damage check. `logic/regions.py`'s
`_intra_area_edges` special-cases this one edge (`SKY_TEMPLE_GATEWAY_KEY_
NODE`/`_TARGET`, alongside the file's existing `translator_gate_
requirement` override for `configurable_node`s): `_strip_sky_temple_key_
items` removes the 9 key resources from the requirement tree before
compiling (leaving the damage check to compile normally), and the result
is ANDed with `_sky_temple_key_count_rule` -- a `Rule` closure counting
`state.has("Sky Temple Key N", player)` across all 9 and comparing
against `sky_temple_keys_required_count(world)`, matching in state-space
exactly what the ISO patch above checks in the actual game (every key
currently held, regardless of how it was obtained).

**Tests.** `test_regions.py` (region graph, via `can_reach_location` on
the real victory event location -- *not* `multiworld.can_beat_game`,
which sweeps for reachable-but-uncollected advancement items first and
would auto-collect a deliberately-excluded key, defeating the point):
required=6 beatable holding exactly 6 of 9 keys, still unbeatable holding
5; default (9) still needs every key; `sky_temple_keys=3` with
`required=9` clamped down to 3 is satisfiable via the 6 precollected keys
alone, without ever collecting the 3 findable ones (the case that would
fail unclamped). `test_pool.py`: present/required count helper values
across modes, including the `all_guardians` clamp. `test_sky_temple_key_
gate_patch.py`: the connection-rewiring logic against a fake `Area`/
`ScriptInstance` (moves the `Open` connection to the right internal
state, preserves unrelated connections, no-ops at 9, rejects out-of-range
values and a malformed room with more than one `Open` connection);
`register`'s wiring; `sky_temple_keys_required_installed`'s wrap/restore
(including on exception, matching `TestWarpToStartInstalled`'s
coverage); the resolved value's route into `options.json` (default,
lowered, clamped) with `assertNotIn` on `config.json`.

---

## T. `move_while_scanning`

A port of randomprime's (undocumented) `moveWhileScan` CtwkConfig field
(`randomprime/schema/randomprime.schema.json`'s `moveWhileScan`,
`randomprime/src/patches.rs::patch_ctwk_player` -- `ctwk_player.
scan_freezes_game = 0` when set): lets the player move while Scan Visor is
locked onto a scan point, instead of the game freezing movement for the
scan's duration. Purely a resource-tweak field flip, no DOL asm and no
SCLY object involved at all -- the simplest of the QoL ports so far.

**Where this lives, and why not in open-prime-rando (same reasoning as
section S's `sky_temple_keys_required`).** The pinned dependency
(`open-prime-rando[nod]==0.20.1`) is a released PyPI version; a
`move_while_scanning: bool` field was added to the fork's
`RandoConfiguration` (`echoes/rando_configuration.py`) and wired into
`echoes/patcher.py::apply_dol_patches` (`with editor.edit_tweak(TweakPlayer)
as tweak: tweak.scan_visor.scan_freezes_game = not configuration.
move_while_scanning`, mirroring `damage_changes.py`'s existing `edit_tweak
(TweakPlayer)` usage for `dark_world`/`dark_suit_damage_reduction`) as a
candidate to upstream later, but the pinned release wouldn't pick it up
regardless -- confirmed by regenerating the fork's own golden-hash export
tests (`tests/test_files/echoes/new_patcher.json` gained `"move_while_
scanning": true`; only `Standard.ntwk`'s hash changed, and the full 251-test
OPR suite still passes against real NTSC/PAL ISOs). So, like
`warp_to_start`/`item_map_dots`/`spring_ball`/
`sky_temple_keys_required` before it, the actual shipped feature lives in
`client/patcher_runner.py`: `install_move_while_scanning(editor)` calls the
exact same `editor.edit_tweak(TweakPlayer)` two-liner directly against the
client's own `PatcherEditor`. Unlike every other patch-time setting so far
this needs no hook into `_apply_patches` at all (no `register_world_changes`
wrap, no code-cave request) -- like `install_spring_ball`, it only needs to
run once on `editor` before `_apply_patches`'s trailing
`editor.save_modifications(output, ...)`, which `patch_iso_with_ap` already
guarantees by calling it in the same place spring ball's installer runs,
right before the `ExitStack` of hook-based patches. Verified directly
against the pinned 0.20.1 release and a real vanilla ISO (not just the
fork): `editor.edit_tweak(TweakPlayer)` reads `scan_freezes_game=True`
before `install_move_while_scanning`, `False` after.

**Config plumbing.** `move_while_scanning` (options.py, `Toggle`, default
off -- matching randomprime's own default-off `moveWhileScan`, since there
is no MP1-world precedent either way to mirror) has no home in OPR's
`RandoConfiguration` for the reason above, so `__init__.py`'s
`generate_output` writes it into `options.json` alongside `warp_to_start`,
where `patcher_runner.patch_iso_with_ap` reads it back (default `False` if
absent, so a `.apmp2` produced before this option existed still patches
unchanged).

**Tests.** `test_move_while_scanning.py`: the option's route into
`options.json` with `assertNotIn` on `config.json` (enabled/default-off);
`install_move_while_scanning` against a fake `PatcherEditor` exposing just
`edit_tweak`, asserting it flips `scan_visor.scan_freezes_game` and nothing
else.

---

## U. Splitting `sky_temple_keys` into count + `sky_temple_keys_locations`

Section F's original `sky_temple_keys` was a single `Choice` conflating
two independent axes: how many of the 9 keys are findable at all
(`0`-`9`), and where the findable ones are placed (numeric modes leave
them to the general pool; `all_bosses`/`all_guardians`/
`all_guardians_plus_6` lock them onto boss/guardian pickups). That made
the option's own value space redundant -- `all_guardians` and
`all_guardians_plus_6` differed only in whether keys 4-9 were
precollected or pooled, a distinction that had nothing to do with
"guardians" -- and forced anyone wanting, say, 5 findable keys locked
across the 3 guardians-plus-pool to fall back to a numeric mode and lose
the guardian placement entirely.

Split into two options (`options.py`): `sky_temple_keys` is now a plain
`Range(0, 9)`, just the findable-count axis from section F, with the
exact same semantics as the old numeric modes (`N` findable, `9-N`
precollected). `sky_temple_keys_locations` is a `Choice` with only the
placement axis: `off` (default; matches the old numeric modes exactly),
`all_bosses` (matches the old `all_bosses`, but now requires
`sky_temple_keys == 9` since there are exactly 9 boss/guardian slots to
fill), `all_guardians` (locks keys 1-3 onto the 3 guardians, same as
before, then shuffles keys 4..`sky_temple_keys` into the pool -- which
subsumes both old `all_guardians` (`sky_temple_keys=3`, nothing left to
pool) and old `all_guardians_plus_6` (`sky_temple_keys=9`, keys 4-9
pooled) as special cases of one mechanism, so `all_guardians_plus_6` is
gone entirely). Requires `sky_temple_keys >= 3` (enough keys to cover the
3 locked guardian slots).

**`item_pool.py` simplifies too.** `sky_temple_keys_present_count(world)`
used to special-case each old mode; since "present" (findable, as opposed
to precollected) is now always exactly `sky_temple_keys` regardless of
`sky_temple_keys_locations` (the guardian-lock + pool split still sums to
`sky_temple_keys`), it's now a one-line passthrough.
`sky_temple_keys_required_count` (section S) is unchanged -- it already
just clamped the raw `sky_temple_keys_required` value down to
`sky_temple_keys_present_count(world)`, so "`sky_temple_keys_required`
must be no higher than `sky_temple_keys`" was already the enforced
invariant, just against a more roundabout present-count calculation.

**Validation.** The two placement preconditions above
(`all_bosses` needs `sky_temple_keys == 9`; `all_guardians` needs
`sky_temple_keys >= 3`) are real constraints, not something to silently
reinterpret, so `MetroidPrime2World.generate_early` raises
`Options.OptionError` (imported as `from Options import OptionError`,
matching the `worlds/paint`/`worlds/lingo` convention -- the first use of
`OptionError` in this world) when they're violated, right after the
Universal Tracker passthrough block and before anything else reads
`self.options`. This is a harder failure mode than
`sky_temple_keys_required`'s silent clamp deliberately: a clamp has a
well-defined, always-satisfiable fallback (require fewer keys), but there
is no sensible auto-correction for "you asked to lock 9 keys onto bosses
but only made 5 of them findable" short of guessing which 5, so it errors
instead.

**Migration note.** This is a breaking option-shape change: old YAMLs
using `sky_temple_keys: all_bosses`/`all_guardians`/`all_guardians_plus_6`
need `sky_temple_keys: 9` (or `3` for old `all_guardians`) plus the new
`sky_temple_keys_locations: all_bosses`/`all_guardians` key instead. Old
numeric values (`sky_temple_keys: 0`-`9`) are unaffected --
`sky_temple_keys_locations` simply defaults to `off`, reproducing the old
numeric-mode behavior exactly.

## V. `translator_lore_rando` (lore hologram colors)

Option `TranslatorLoreRando(Choice)`, `vanilla` (default) / `full_random`,
right after `translator_lore_hints` in the "Goal" group. No "unlocked"
outcome: a hologram with no translator would need a new hologram look, and
the point of the option is colored hints.

### V.1 Facts (verified 2026-09-30 against retail NTSC and PAL, identical)

* Each of the 22 lore rooms wires its hologram like a translator gate: CRLY
  "Does Player Have Correct Translator?" (`conditional1.player_item` =
  translator) -> Open: deactivate POIN "Translator No", activate POIN
  "Translator Yes" (the tracked lore SCAN). ACTR "Lore Hologram" is
  ScanSource for both POIs; its model is unique per hologram, 1 material
  set, 1 texture = the per-color lore texture (violet 0x4BE5342E, amber
  0xF5308558, emerald 0xA9640FDF, cobalt 0x2C56D2D4). ACTR "Glow For Holo 1"
  uses the same 4 glow models as OPR's `TRANSLATOR_DATA`. The projector
  (0x34BAA476, "Active/Inactive Lore Object") is shared and color-neutral.
* The "Translator No" SCAN 0x0D16CCEE (STRG 0xF11AD0F9) is shared by all 22
  and names no color, so no string change is needed.
* Several of these rooms also have a translator gate with its own
  "Glow For Holo 1", so the patch uses instance ids
  (`client/lore_translator_patch.py`'s `LORE_HOLOGRAMS`), not names.

### V.2 Implementation

* `logic/translator_gate_rando.py`'s `build_translator_lore_assignment` ->
  `world.translator_lore_assignment` (`{strg_id: color}`, `{}` under
  vanilla, no RNG draw then), built in `generate_early` before dock rando
  (its probe goes through `_leave_requirement`).
* `logic/regions.py`'s `_leave_requirement` gives a reassigned hint node
  Scan + its new color (`Node.string_asset_id` added to find it).
* options.json `translator_lore_colors` (`{str(strg_id): "amber", ...}`) ->
  `patcher_runner.translator_lore_colors_installed` ->
  `lore_translator_patch.register`, which skips unchanged holograms and
  for the rest retargets the CRLY, swaps the glow model, and duplicates the
  hologram model with the new texture (OPR's gate technique; area
  dependency rebuild pulls the texture into the pak).
* Spoiler: "Translator Lore Colors" block when randomized.

## W. Universal Tracker regeneration

UT regenerates the world from `multiworld.re_gen_passthrough[game]` (the
static `interpret_slot_data` returns slot data unchanged) but has no access
to the original seed. Options already came through slot data, but the
per-seed *randomized state* did not: the starting room, door-lock /
elevator / portal rando, translator gate colors and lore hologram colors
are all `world.random` draws, so a regen rolled different ones and the
tracker's logic disagreed with the real game.

* `tracker_data.py`: `encode_randomization(world)` /
  `decode_randomization(slot_data)`. Slot keys `starting_location`,
  `translator_gates`, `translator_lore`, `dock_rando`; `NodeId`s are stored
  as `[region, area, node]` lists and maps as lists of pairs (JSON-safe --
  ids can't be dict keys and tuples come back as lists).
* `fill_slot_data` adds them; `generate_early` restores them after applying
  the option passthrough, skipping the `starting_room` draw and the three
  `build_*_assignment` calls (incl. dock rando's reject-and-retry probe).
* Slot data from before this change lacks the keys: `decode_randomization`
  returns `None` and generation falls back to re-rolling, which is only
  right for seeds that left every randomized option at "vanilla".
* `test/test_tracker_data.py` regenerates under a different seed with
  `generation_is_fake`/`re_gen_passthrough` set and asserts identical
  assignments and entrance graph (verified to fail with the restore off).
* `ut_can_gen_without_yaml = True`: slot data holds every world option
  (`test_slot_data_covers_every_world_option` guards future additions) plus
  the randomized state, so UT skips its first generation and needs no
  player yaml. Only server-side options (`exclude_locations`, `start_*`,
  ...) fall back to defaults in the tracker.
* Not done: deferred entrances (`found_entrances_datastorage_key`).

### W.1 Item strip (`client/item_panel.py`)

Two rows of upgrade icons plus nine counters (energy tanks, missiles, power
bombs, dark/light ammo, Sky Temple Keys, and the three Dark Temple key
sets), below the client window like `worlds/metroidprime`'s.
`compute_panel_state` (pure) derives everything from the received item
names; ammo totals and the launcher / power bomb unlock flags come from
`receive_items.compute_desired_capacities` so the strip can't drift from
what the client actually grants. Progressive Suit/Grapple resolve to Dark/
Light Suit and Grapple/Screw Attack by copy index. Sky Temple Keys show
`have/sky_temple_keys_required`.

Icons (`assets/items`, 41 PNGs) come from `tools/make_tracker_icons.py`:
16 copied from the Prime 1 world where the item is the same, 16 recolored
from the analogous Prime 1 icon (Dark/Light beams from the beam hands,
Darkburst/Sunburst/Sonic Boom from the charge combos, suits, visors, ammo
expansions), and 9 drawn with Pillow (Screw Attack, four translators, Sky
Temple Key, three Dark Temple keys). Committed, so the script only needs
re-running to change an icon.

### W.2 Map tab (`tracker/`, `tracker_data.TRACKER_WORLD`)

An internal poptracker pack, one map per logic-database region (10).
There is no Echoes map art to reuse and UT's docs advise against shipping
game images, so `tools/make_tracker_map.py` draws schematic maps from room
geometry: each area's world-space AABB (MLVL `area_bounding_box` +
`area_transform` translation, extracted once from the ISO into
`tools/room_bounds.json`) tinted by height, pickups placed from the logic
DB's node coordinates (same world frame; 118/119 fall inside their room's
box, the last is 3 units off in z). Section names are the AP location names,
which is what UT matches on.

Auto-tabbing: a light region and its dark counterpart share one MLVL
(Temple Grounds + Sky Temple Grounds, ...), so the existing
`metroidprime2_mlvl_*` key can't pick the map. The client now also writes
`metroidprime2_area_{team}_{slot}` = `"<mlvl hex>:<area index>"` (the area
index it already reads for goal detection) and `tracker_data.map_page_index`
resolves that through `tracker/area_maps.json`; unrecognized values return
-1 (keep the current tab).

Current-room highlight: UT's location indicator (`location_setting_key` /
`location_icon_coords`) reuses the same area key, so the client needs no
change. UT draws that icon as a fixed `location_icon_size` square centred on
(x, y), so a room-shaped highlight is one pre-rendered overlay per room
(`tracker/images/rooms/<region>/<area index>.png`): a green translucent
rectangle at the room's spot in a transparent square sized to the map's
largest room (that side is the map's `location_icon_size` in `maps.json`).
`tracker/room_icons.json` maps `mlvl -> area index -> {map, x, y, img}`;
`tracker_data.room_icon_coords` returns None (no icon) when the room belongs
to a different map than the one shown (auto-tab off) or is unknown.
Room-level only, no in-room position. The live UT rendering is unchecked.

Verification: unit tests cover the panel state, the headless kivy build of
the strip (mock GL), every location appearing exactly once on its region's
map with unique in-bounds pixels, the auto-tab mapping, and UT's own
`UTMapTabData` accepting `TRACKER_WORLD`. Nothing has been run in a live UT
session, so how the strip and the map actually look is unchecked.
