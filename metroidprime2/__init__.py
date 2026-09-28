"""Metroid Prime 2: Echoes world package.

Output generation (``generate_output``, ``patch_data.py``,
``container.py``) and the Dolphin client (``client/``, ``settings.py``,
registered below as the "Metroid Prime 2 Client" Component) are both
implemented; see ``PLAN.md`` sections E, F, G, H, I, J and K (M2/M3).
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any, ClassVar, TextIO

from BaseClasses import ItemClassification, Tutorial
from NetUtils import HintStatus
from worlds.AutoWorld import WebWorld, World
from worlds.LauncherComponents import Component, SuffixIdentifier, Type, components, icon_paths, launch

from . import constants
from .container import MetroidPrime2Container
from .hint_scans import (
    SKY_TEMPLE_KEY_HINT_SCANS,
    TRANSLATOR_LORE_HINT_SCANS,
    encode_hint_scans,
    sky_temple_key_locations,
    translator_lore_hint_locations,
)
from .item_pool import STK_ITEM_NAMES, create_item_pool, sky_temple_keys_required_count
from .items import ITEM_GROUPS, ITEM_TABLE, MetroidPrime2Item, item_name_to_id
from .locations import LOCATION_GROUPS, location_name_to_id
from .logic import regions as logic_regions
from .logic.db_reader import NodeId, load_game_database
from .logic.dock_rando import DockRandoAssignment, build_dock_rando_assignment
from .logic.translator_gate_rando import TranslatorGateAssignment, build_translator_gate_assignment
from .options import (
    OPTION_GROUPS,
    MapVisibility,
    MetroidPrime2Options,
    SkyTempleKeyHints,
    TranslatorLoreHints,
    trick_levels_from_options,
)
from .patch_data import _translator_lore_hint_text, make_rando_configuration
from .settings import MetroidPrime2Settings
from .utils import get_apworld_version

if TYPE_CHECKING:
    from BaseClasses import Location

GAME_NAME = "Metroid Prime 2: Echoes"


def run_client(*args: str) -> None:
    from .client.client import main

    launch(main, name="MetroidPrime2Client", args=args)


components.append(
    Component(
        "Metroid Prime 2 Client",
        func=run_client,
        component_type=Type.CLIENT,
        file_identifier=SuffixIdentifier(".apmp2"),
        icon="Metroid Prime 2",
    )
)

icon_paths["Metroid Prime 2"] = "ap:worlds.metroidprime2/assets/icon.png"


# Every one of MetroidPrime2Options' own fields (i.e. everything except the
# common/per-game base fields inherited from Options.CommonOptions /
# Options.PerGameCommonOptions, which either aren't meaningful to the game
# client or are handled by the core server instead). Computed from
# MetroidPrime2Options.type_hints so this always tracks options.py without
# needing to be kept in sync by hand.
_BASE_OPTION_NAMES = frozenset(
    {
        "progression_balancing",
        "accessibility",
        "local_items",
        "non_local_items",
        "start_inventory",
        "start_hints",
        "start_location_hints",
        "exclude_locations",
        "priority_locations",
        "item_links",
        "plando_items",
        "allow_collecting_from",
    }
)


def _slot_data_option_names() -> tuple[str, ...]:
    return tuple(
        name for name in MetroidPrime2Options.type_hints if name not in _BASE_OPTION_NAMES
    )


class MetroidPrime2Web(WebWorld):
    tutorials = [  # noqa: RUF012 -- matches WebWorld.tutorials' own unannotated convention across every world
        Tutorial(
            "Multiworld Setup Guide",
            "A guide to setting up Metroid Prime 2: Echoes for MultiworldGG",
            "English",
            "setup_en.md",
            "setup/en",
            ["wumb0"],
        )
    ]
    option_groups = OPTION_GROUPS


class MetroidPrime2World(World):
    """Metroid Prime 2: Echoes is a first-person action-adventure game for
    the Nintendo GameCube. Play as bounty hunter Samus Aran as she
    investigates a distress signal on planet Aether, only to find it split
    between a light and a corrupted dark dimension by an ancient war."""

    game = GAME_NAME
    web = MetroidPrime2Web()
    options_dataclass = MetroidPrime2Options
    options: MetroidPrime2Options
    settings: ClassVar[MetroidPrime2Settings]

    item_name_to_id = item_name_to_id
    location_name_to_id = location_name_to_id
    item_name_groups = ITEM_GROUPS
    location_name_groups = LOCATION_GROUPS

    origin_region_name = "Temple Grounds/Landing Site/Save Station"
    required_client_version = (0, 5, 0)
    topology_present = True

    trick_levels: dict[str, int]
    world_uuid: str
    sky_temple_key_locations: list[str]
    dock_rando: DockRandoAssignment
    translator_gate_assignment: TranslatorGateAssignment
    starting_location: NodeId
    """The node ``origin_region_name`` was set to for this player -- one of
    ``options.starting_room``'s selected pool (the DB's own vanilla
    ``starting_location`` when that option is left at "vanilla"). Kept
    around (rather than just the derived region-name string) so
    ``patch_data.py`` can resolve its mlvl/mrea without re-deriving which
    node ``origin_region_name`` came from."""
    _translator_lore_hints: list[Location | None] | None
    """``hint_scans.translator_lore_hint_locations``'s cache (PLAN.md
    section R.3) -- ``None`` until first computed, then the 22 chosen
    locations (or ``None`` entries) for the rest of generation. Cached
    because that function draws from its own RNG; recomputing it would
    reshuffle the choice out from under later callers."""

    def generate_early(self) -> None:
        multiworld = self.multiworld

        # Universal Tracker passthrough: when regenerating for the tracker,
        # option values arrive via multiworld.re_gen_passthrough instead of
        # the normal player yaml, so apply them before anything below reads
        # self.options (e.g. trick_levels_from_options just below).
        if hasattr(multiworld, "re_gen_passthrough"):
            passthrough = multiworld.re_gen_passthrough.get(self.game)
            if passthrough:
                for key, value in passthrough.items():
                    option = getattr(self.options, key, None)
                    if option is not None:
                        option.value = value

        self.trick_levels = trick_levels_from_options(self.options)
        self.world_uuid = str(
            uuid.uuid5(constants.NAMESPACE_UUID, f"{multiworld.seed_name}/{self.player}")
        )
        self.sky_temple_key_locations = []
        self._translator_lore_hints = None

        # Must run before create_regions (logic/regions.py) builds the
        # region graph -- it reads world.origin_region_name to find the BFS
        # root and to seed logic/regions.py's can_warp_to_start wiring. Safe
        # to do here: AP's own Main.py calls generate_early for every world
        # before create_regions for any of them (worlds/AutoWorld.py's
        # origin_region_name is likewise only ever consulted from
        # create_regions onward). The "vanilla" branch below makes zero
        # self.random calls, so leaving starting_room at its default
        # doesn't perturb any other option's random draws -- an existing
        # seed's generation is bit-for-bit unaffected.
        db = load_game_database()
        starting_room_pool = self.options.starting_room.current_key
        if starting_room_pool == "vanilla":
            self.starting_location = db.starting_location
        else:
            candidates = db.starting_location_candidates(
                starting_room_pool, light_world_only=bool(self.options.starting_room_light_world_only)
            )
            self.starting_location = self.random.choice(candidates)
        self.origin_region_name = self.starting_location.ap_name

        # translator_gate_assignment must be built first: dock_rando's own
        # reject-and-retry reachability probe (logic/dock_rando.py's
        # _meets_progression_bar) evaluates translator gate requirements
        # through logic/regions.py's translator_gate_requirement, which
        # reads world.translator_gate_assignment.
        self.translator_gate_assignment = build_translator_gate_assignment(self)
        self.dock_rando = build_dock_rando_assignment(self)

    def create_regions(self) -> None:
        logic_regions.create_regions(self)

    def create_items(self) -> None:
        self.multiworld.itempool += create_item_pool(self)

    def create_item(self, name: str) -> MetroidPrime2Item:
        data = ITEM_TABLE[name]
        classification = data.classification
        if hasattr(self.multiworld, "generation_is_fake"):
            # Universal Tracker: every item must be progression so the
            # tracker's logic sees everything as potentially required.
            classification = ItemClassification.progression
        return MetroidPrime2Item(name, classification, data.code, self.player)

    def get_filler_item_name(self) -> str:
        return "Missile Expansion"

    def set_rules(self) -> None:
        # No-op: all access/entrance rules are attached directly in
        # create_regions() (logic/regions.py), since building them requires
        # the same RequirementCompiler/StaticContext used to build the
        # region graph itself.
        pass

    def post_fill(self) -> None:
        # PLAN.md section Q.4: sky_temple_key_hints="precollected" means
        # every key hint is already known at the start of the game, which
        # AP models as start_hints -- Main.py's output-generation phase
        # reads options.start_hints after post_fill/fill has run (the
        # precollect_hint loop keyed on `location.item.name in
        # multiworld.worlds[location.item.player].options.start_hints`,
        # right after every world's fill_slot_data() has already been
        # called), so appending here is early enough for a real generation
        # run to pick it up.
        if self.options.sky_temple_key_hints.value != SkyTempleKeyHints.option_precollected:
            return
        for item_name, location in zip(STK_ITEM_NAMES, sky_temple_key_locations(self), strict=True):
            if location is not None:
                self.options.start_hints.value.add(item_name)

    def pre_output(self) -> None:
        # PLAN.md section R.3: pin the translator lore hint choice before
        # generate_output's threaded stage. translator_lore_hint_locations
        # caches on self._translator_lore_hints, so this is also safe to
        # call again from generate_output/fill_slot_data/write_spoiler --
        # they all see this same result.
        translator_lore_hint_locations(self)

    def generate_output(self, output_directory: str) -> None:
        # Prime 1 pattern (worlds/metroidprime/__init__.py generate_output):
        # build the patcher-format config dict, write it plus a small
        # client-metadata dict into a .apmp2 zip. See PLAN.md sections H
        # (make_rando_configuration) and I (MetroidPrime2Container).
        config_json = json.dumps(make_rando_configuration(self), indent=4)
        options_json = json.dumps(
            {
                "player_name": self.player_name,
                "world_uuid": self.world_uuid,
                "apworld_version": get_apworld_version(),
                # Patch-time settings that have no home in the OPR
                # RandoConfiguration (config.json is validated with
                # extra="forbid"), so the client reads them from here.
                "warp_to_start": bool(self.options.warp_to_start),
                "spring_ball": bool(self.options.spring_ball),
                "spring_ball_button": self.options.spring_ball_button.current_key,
                "show_item_locations": bool(
                    self.options.map_visibility.value == MapVisibility.option_full_map_and_items
                ),
                # PLAN.md section S: physically rewires the Sky Temple
                # Gateway's key-count gate (client/sky_temple_key_gate_
                # patch.py) -- open-prime-rando has no field for this, so
                # like the settings above it travels here rather than in
                # config.json.
                "sky_temple_keys_required": sky_temple_keys_required_count(self),
                # PLAN.md section P's compatibility gate: client/patcher_runner.py
                # refuses to patch a .apmp2 whose pickup encoding it doesn't
                # recognize, since the per-pickup resource mapping baked into
                # config.json at generation time and the DOL writes that make
                # a client understand it happen at two different times.
                "pickup_encoding": constants.PICKUP_ENCODING_VERSION,
            },
            indent=4,
        )

        outfile_name = self.multiworld.get_out_file_name_base(self.player)
        container = MetroidPrime2Container(
            config_json,
            options_json,
            outfile_name,
            output_directory,
            player=self.player,
            player_name=self.player_name,
        )
        container.write()

    def fill_slot_data(self) -> dict[str, Any]:
        slot_data: dict[str, Any] = self.options.as_dict(*_slot_data_option_names())
        slot_data["world_uuid"] = self.world_uuid
        slot_data["first_non_starting_item_index"] = len(
            self.multiworld.precollected_items[self.player]
        )
        slot_data["sky_temple_key_locations"] = list(self.sky_temple_key_locations)
        slot_data["starting_region"] = self.origin_region_name
        slot_data["apworld_version"] = get_apworld_version()

        # PLAN.md section Q.4/Q.5: {scan_id: (location_player, location_id,
        # status)} for the client's _handle_hint_scans, only when there's
        # actually something to scan for (sky_temple_key_hints="scanned" --
        # disabled replaces the pillar text with a non-hint, and
        # precollected already sent every hint via start_hints above, so
        # neither needs a client scan-detection path). Sky Temple Key
        # entries are always our own item, so they're always HINT_PRIORITY.
        hint_scans: dict[int, tuple[int, int, int]] = {}
        if self.options.sky_temple_key_hints.value == SkyTempleKeyHints.option_scanned:
            for hint_scan, location in zip(
                SKY_TEMPLE_KEY_HINT_SCANS, sky_temple_key_locations(self), strict=True
            ):
                if location is not None:
                    hint_scans[hint_scan.scan_id] = (location.player, location.address, HintStatus.HINT_PRIORITY)

        # PLAN.md section R.4: translator lore hints, added independent of
        # sky_temple_key_hints -- translator_lore_hint_locations already
        # returns all-None (no entries added below) under
        # translator_lore_hints="off", so no extra option check is needed
        # here. A hologram naming another player's item (translator_lore_
        # hints="any") must use HINT_UNSPECIFIED: CreateHints only allows
        # HINT_PRIORITY when the hinted item belongs to the sender.
        for hint_scan, location in zip(
            TRANSLATOR_LORE_HINT_SCANS, translator_lore_hint_locations(self), strict=True
        ):
            if location is not None:
                assert location.item is not None
                status = (
                    HintStatus.HINT_PRIORITY
                    if location.item.player == self.player
                    else HintStatus.HINT_UNSPECIFIED
                )
                hint_scans[hint_scan.scan_id] = (location.player, location.address, status)

        slot_data["hint_scans"] = encode_hint_scans(hint_scans)

        return slot_data

    @staticmethod
    def interpret_slot_data(slot_data: dict[str, Any]) -> dict[str, Any]:
        # Returning slot_data makes it available again as
        # multiworld.re_gen_passthrough[game] the next time the world is
        # generated (Universal Tracker regeneration).
        return slot_data

    def write_spoiler(self, spoiler_handle: TextIO) -> None:
        if self.options.starting_room.current_key != "vanilla":
            spoiler_handle.write(f"\n\nStarting Region ({self.player_name}): {self.origin_region_name}\n")

        if self.sky_temple_key_locations:
            spoiler_handle.write(f"\n\nSky Temple Keys ({self.player_name}):\n")
            for location_name in self.sky_temple_key_locations:
                spoiler_handle.write(f"    {location_name}\n")

        # PLAN.md section R.4: one line per hologram, plain text
        # (colored=False -- the spoiler log has no STRG rich-text markup).
        if self.options.translator_lore_hints.value != TranslatorLoreHints.option_off:
            spoiler_handle.write(f"\n\nTranslator Lore Hints ({self.player_name}):\n")
            for hint_scan, location in zip(
                TRANSLATOR_LORE_HINT_SCANS, translator_lore_hint_locations(self), strict=True
            ):
                text = _translator_lore_hint_text(self, location, colored=False)
                spoiler_handle.write(f"    {hint_scan.room}: {text}\n")
