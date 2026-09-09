"""Metroid Prime 2: Echoes world package.

Output generation (``generate_output``, ``patch_data.py``,
``container.py``) and the Dolphin client (``client/``, ``settings.py``,
registered below as the "Metroid Prime 2 Client" Component) are both
implemented; see ``PLAN.md`` sections E, F, G, H, I, J and K (M2/M3).
"""

from __future__ import annotations

import json
import uuid
from typing import Any, ClassVar, TextIO

from BaseClasses import ItemClassification, Tutorial
from worlds.AutoWorld import WebWorld, World
from worlds.LauncherComponents import Component, SuffixIdentifier, Type, components, icon_paths, launch

from . import constants
from .container import MetroidPrime2Container
from .item_pool import create_item_pool
from .items import ITEM_GROUPS, ITEM_TABLE, MetroidPrime2Item, item_name_to_id
from .locations import LOCATION_GROUPS, location_name_to_id
from .logic import regions as logic_regions
from .logic.dock_rando import DockRandoAssignment, build_dock_rando_assignment
from .logic.translator_gate_rando import TranslatorGateAssignment, build_translator_gate_assignment
from .options import (
    MetroidPrime2Options,
    OPTION_GROUPS,
    trick_levels_from_options,
)
from .patch_data import make_rando_configuration
from .settings import MetroidPrime2Settings
from .utils import get_apworld_version

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
    tutorials = [
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
    options: MetroidPrime2Options  # type: ignore[assignment]
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
        slot_data["apworld_version"] = get_apworld_version()
        return slot_data

    @staticmethod
    def interpret_slot_data(slot_data: dict[str, Any]) -> dict[str, Any]:
        # Returning slot_data makes it available again as
        # multiworld.re_gen_passthrough[game] the next time the world is
        # generated (Universal Tracker regeneration).
        return slot_data

    def write_spoiler(self, spoiler_handle: TextIO) -> None:
        if not self.sky_temple_key_locations:
            return
        spoiler_handle.write(f"\n\nSky Temple Keys ({self.player_name}):\n")
        for location_name in self.sky_temple_key_locations:
            spoiler_handle.write(f"    {location_name}\n")
