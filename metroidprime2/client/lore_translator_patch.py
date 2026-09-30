"""Translator lore hologram recoloring (``translator_lore_rando``): changes
which translator each of the 22 Luminoth lore holograms needs, and recolors
the hologram and its glow to match.

open-prime-rando only does this for translator gates
(``open_prime_rando.echoes.translator_gates``), so like
``sky_temple_key_gate_patch.py`` this goes straight at each room's SCLY
through a registered area function. No DOL patch and no STRG change: the
"untranslated" popup every hologram shares (SCAN 0x0D16CCEE -> STRG
0xF11AD0F9, "Unable to activate Luminoth Lore Projector. / Proper
Translator Module needed for access.") never names a color.

Reading the SCLY of all 22 rooms (retail NTSC-U and PAL, via
retro_data_structures against real ISOs -- instance ids are identical on
both) shows every hologram is wired the same way, and just like a
translator gate:

* a ``ConditionalRelay`` "Does Player Have Correct Translator?" whose
  ``conditional1.player_item`` is the translator; on Open it deactivates
  the "Translator No" POI and activates "Translator Yes" (the POI whose
  SCAN is the tracked lore scan, ``hint_scans.TRANSLATOR_LORE_HINT_SCANS``);
* an ``Actor`` "Lore Hologram" (the ScanSource for both POIs) whose model
  -- unique per hologram -- has one material set with one texture, which
  is the per-color hologram texture (``_HOLOGRAM_TEXTURES``);
* an ``Actor`` "Glow For Holo 1" whose model is the per-color glow, the
  same four models OPR uses for gate glows.

Instance ids are hardcoded rather than looked up by name because several
of these rooms also hold a translator gate with its own "Glow For Holo 1".
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from open_prime_rando.area_patcher import AreaPatcher
    from retro_data_structures.formats.mrea import Area


@dataclass(frozen=True)
class LoreHologram:
    mlvl_id: int
    mrea_id: int
    vanilla_color: str
    """Lowercase, matching open-prime-rando's ``TranslatorRequirement``."""
    relay_id: int
    """"Does Player Have Correct Translator?" ``ConditionalRelay``."""
    hologram_id: int
    """"Lore Hologram" ``Actor``."""
    glow_id: int
    """The hologram's own "Glow For Holo 1" ``Actor``."""


# Keyed by the hologram's STRG id (hint_scans.HintScan.strg_id).
LORE_HOLOGRAMS: dict[int, LoreHologram] = {
    # Agon Wastes
    0x24E69725: LoreHologram(0x42B935E4, 0x427FAD9A, "amber", 0x202FE, 0x2027D, 0x2027C),  # Mining Plaza
    0xA272E58B: LoreHologram(0x42B935E4, 0xDB7B2CED, "amber", 0x802C1, 0x80279, 0x80277),  # Mining Station B
    0x5324575E: LoreHologram(0x42B935E4, 0xE3BEF27F, "amber", 0xA02BD, 0xA020C, 0xA0208),  # Mining Station A
    0x692E362E: LoreHologram(0x42B935E4, 0x2BCD44A7, "amber", 0x1201DA, 0x120221, 0x1201EB),  # Portal Terminal
    0xEFBA4480: LoreHologram(0x42B935E4, 0x02FC3717, "amber", 0x270037, 0x270045, 0x270042),  # Agon Energy Ctrl
    # Great Temple
    0xC3576EA5: LoreHologram(0x863FCD72, 0x02A01334, "violet", 0x70028, 0x70159, 0x7015A),  # Main Energy Ctrl
    # Sanctuary Fortress
    0xF2BF7438: LoreHologram(0x1BAA96C2, 0x47265C0B, "cobalt", 0x2033C, 0x20343, 0x20346),  # Sanctuary Entrance
    0x0405EE3F: LoreHologram(0x1BAA96C2, 0x5571E89E, "cobalt", 0xA0202, 0xA01FB, 0xA01F8),  # Hall of Combat Mastery
    0xBF77D533: LoreHologram(0x1BAA96C2, 0x914F1381, "cobalt", 0xB0117, 0xB0250, 0xB0254),  # Main Research
    0x742B0696: LoreHologram(0x1BAA96C2, 0xA2406387, "cobalt", 0x180198, 0x180193, 0x180190),  # Watch Station
    0xF5535CEA: LoreHologram(0x1BAA96C2, 0x73342A54, "cobalt", 0x240180, 0x240179, 0x240178),  # Main Gyro Chamber
    0x3E0F8F4F: LoreHologram(0x1BAA96C2, 0x0D032A6A, "cobalt", 0x370047, 0x37003E, 0x37003F),  # Sanc. Energy Ctrl
    # Temple Grounds
    0x987884FB: LoreHologram(0x3BFA3EFF, 0x9B5EFA75, "violet", 0x40081, 0x4005F, 0x4005D),  # Meeting Grounds
    0x8E9FCFAE: LoreHologram(0x3BFA3EFF, 0xEE4732BE, "violet", 0xE00FB, 0xE00E1, 0xE00E2),  # Path of Eyes
    0x39E3A79D: LoreHologram(0x3BFA3EFF, 0x62FF94EE, "violet", 0x1800CF, 0x1800C8, 0x1800C7),  # Transport to Agon
    0xCF593D9A: LoreHologram(0x3BFA3EFF, 0x70E5E6DD, "violet", 0x3000AC, 0x3000A5, 0x3000A2),  # Fortress Transport Acc.
    # Torvus Bog
    0x45C31C0B: LoreHologram(0x3DFD2249, 0x7448931C, "emerald", 0x500AE, 0x5009B, 0x500A0),  # Path of Roots
    0x54C87F8C: LoreHologram(0x3DFD2249, 0x80E67F90, "emerald", 0x1E0082, 0x1E00E9, 0x1E00E4),  # Underground Tunnel
    0xD25C0D22: LoreHologram(0x3DFD2249, 0x133BF5B8, "emerald", 0x290087, 0x29007E, 0x29007D),  # Torvus Energy Ctrl
    0x49CD4F34: LoreHologram(0x3DFD2249, 0x3501473A, "emerald", 0x360199, 0x36019F, 0x3601A2),  # Gathering Hall
    0x9F94AC29: LoreHologram(0x3DFD2249, 0x4BB5AE60, "emerald", 0x370116, 0x370121, 0x37011E),  # Training Chamber
    0x82919C91: LoreHologram(0x3DFD2249, 0xFB628DCB, "emerald", 0x380105, 0x380100, 0x380103),  # Catacombs
}

# The vanilla lore hologram texture for each color (every vanilla hologram
# of a color uses the same one).
_HOLOGRAM_TEXTURES: dict[str, int] = {
    "violet": 0x4BE5342E,
    "amber": 0xF5308558,
    "emerald": 0xA9640FDF,
    "cobalt": 0x2C56D2D4,
}

# Vanilla lore glow models; identical to
# open_prime_rando.echoes.translator_gates.TRANSLATOR_DATA's glow_model.
_GLOW_MODELS: dict[str, int] = {
    "violet": 0x0E264630,
    "amber": 0xB9824E7E,
    "emerald": 0xB9347860,
    "cobalt": 0xF2DE555A,
}


def recolor_lore_hologram(editor: Any, mlvl: Any, area: Area, *, hologram: LoreHologram, color: str) -> None:
    """Makes ``hologram`` require ``color``'s translator and look like it.
    The hologram's model is duplicated rather than edited in place (the
    same way open-prime-rando recolors a gate hologram), so nothing else
    referencing the vanilla model changes."""
    from retro_data_structures.enums.echoes import PlayerItemEnum
    from retro_data_structures.formats import Cmdl
    from retro_data_structures.properties.echoes.objects import Actor, ConditionalRelay

    if color not in _HOLOGRAM_TEXTURES:
        raise ValueError(f"unknown translator lore color {color!r}")

    with area.get_instance(hologram.relay_id).edit_properties(ConditionalRelay) as relay:
        relay.conditional1.player_item = PlayerItemEnum[f"{color.capitalize()}Translator"]

    with area.get_instance(hologram.glow_id).edit_properties(Actor) as glow:
        glow.model = _GLOW_MODELS[color]

    holo = area.get_instance(hologram.hologram_id)
    original_model_id = holo.get_properties_as(Actor).model
    new_model_id = editor.duplicate_asset(original_model_id, f"translator_lore_holo_{hologram.hologram_id:x}.CMDL")
    new_model = editor.get_file(new_model_id, Cmdl)
    new_model.raw.material_sets[0].texture_file_ids[0] = _HOLOGRAM_TEXTURES[color]
    with holo.edit_properties(Actor) as holo_props:
        holo_props.model = new_model_id


def register(area_patcher: AreaPatcher, colors: dict[int, str]) -> None:
    """Registers one ``recolor_lore_hologram`` per ``{strg_id: color}``
    entry whose color differs from the hologram's vanilla one."""
    for strg_id, color in colors.items():
        hologram = LORE_HOLOGRAMS[strg_id]
        if color == hologram.vanilla_color:
            continue
        area_patcher.add_raw_function(
            hologram.mlvl_id,
            hologram.mrea_id,
            functools.partial(recolor_lore_hologram, hologram=hologram, color=color),
        )
