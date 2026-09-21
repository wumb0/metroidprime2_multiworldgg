"""Host-side settings for Metroid Prime 2: Echoes (host.yaml group
``metroidprime2_options``, auto-derived from the folder name). Modeled on
``worlds/metroidprime/PrimeSettings.py`` (PLAN.md section G): ``rom_file``,
``emulator_settings``, ``hud_settings``, ``suit_settings``.
"""

from __future__ import annotations

from typing import Any

from settings import Bool, Group, UserFilePath

# Named HUD colors (0-255 RGB), mirroring worlds/metroidprime's HudColor
# enum in spirit but kept self-contained (this world has no dependency on
# worlds.metroidprime). "default" leaves OPR's own HudColorConfiguration
# default untouched (cosmetics_dict omits hud_color entirely for it).
_NAMED_HUD_COLORS: dict[str, tuple[int, int, int]] = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "violet": (255, 0, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "white": (255, 255, 255),
    "orange": (255, 128, 0),
    "pink": (255, 128, 255),
    "lime": (128, 255, 0),
    "teal": (128, 255, 255),
    "purple": (128, 0, 255),
}


class RomFile(UserFilePath):
    """File name of the Metroid Prime 2: Echoes ISO (NTSC-U or PAL only)."""

    description = "Metroid Prime 2: Echoes GC ISO file"
    copy_to = "Metroid_Prime_2.iso"


class EmulatorSettings(Group):
    """Settings related to the emulator."""

    class EmulatorExecutable(UserFilePath):
        """Path to Dolphin."""

        is_exe = True
        description = "Dolphin Emulator Executable"

    class EmulatorArguments(list):
        """Arguments to use with Dolphin."""

    class EmulatorAutoStart(Bool):
        """Should the Emulator be started automatically?"""

    executable_path: EmulatorExecutable = EmulatorExecutable(EmulatorExecutable.copy_to)
    arguments: EmulatorArguments = EmulatorArguments([])
    # `Bool` can't hold a value (see MultiWorldGG/settings.py: "can't subclass
    # bool, so we use this and Union or type: ignore") -- this is that ignore.
    auto_start: EmulatorAutoStart = True  # type: ignore[assignment]

    def __init__(self) -> None:
        should_save = any(attr not in self for attr in self)
        if should_save:
            self.update({attr: self[attr] for attr in self.__dict__.keys()})


class HUDSettings(Group):
    """Settings related to the in-game HUD color (OPR
    ``HudColorConfiguration.main_color``)."""

    class HudColorName(str):
        """One of "default", "custom" (use color_red/color_green/
        color_blue), or a named color: red, green, blue, violet, yellow,
        cyan, white, orange, pink, lime, teal, purple."""

    class HudColorChannel(int):
        """Value must be between 0 and 255."""

    color: HudColorName = HudColorName("default")
    color_red: HudColorChannel = HudColorChannel(0)
    color_green: HudColorChannel = HudColorChannel(0)
    color_blue: HudColorChannel = HudColorChannel(0)

    def __init__(self) -> None:
        should_save = any(attr not in self for attr in self)
        if should_save:
            self.update({attr: self[attr] for attr in self.__dict__.keys()})


class SuitSettings(Group):
    """Cosmetic suit skin replacement (OPR ``suit_replacement``/
    ``SuitMapping``): each value is one of "player1" (vanilla/unchanged),
    "player2", "player3", or "player4"."""

    class SuitSkin(str):
        """"player1" (vanilla), "player2", "player3", or "player4"."""

    varia_skin: SuitSkin = SuitSkin("player1")
    dark_skin: SuitSkin = SuitSkin("player1")
    light_skin: SuitSkin = SuitSkin("player1")

    def __init__(self) -> None:
        should_save = any(attr not in self for attr in self)
        if should_save:
            self.update({attr: self[attr] for attr in self.__dict__.keys()})


class MetroidPrime2Settings(Group):
    class Debug(Bool):
        """Enable debug-only client commands (e.g. /test_deathlink,
        /mp2_debug_inventory). Leave this off unless you're developing or
        troubleshooting the client -- these commands can manipulate
        in-game state (deaths) or exist solely to poke at internals not
        meant for normal play."""

    rom_file: RomFile = RomFile(RomFile.copy_to)
    emulator_settings: EmulatorSettings = EmulatorSettings()
    hud_settings: HUDSettings = HUDSettings()
    suit_settings: SuitSettings = SuitSettings()
    debug: Debug = False  # type: ignore[assignment]

    def __init__(self) -> None:
        should_save = any(attr not in self for attr in self)
        if should_save:
            self.update({attr: self[attr] for attr in self.__dict__.keys()})


def _hud_color_rgb(mp2_settings: MetroidPrime2Settings) -> tuple[int, int, int] | None:
    name = str(mp2_settings["hud_settings"]["color"]).lower()
    if name == "default":
        return None
    if name == "custom":
        return (
            int(mp2_settings["hud_settings"]["color_red"]),
            int(mp2_settings["hud_settings"]["color_green"]),
            int(mp2_settings["hud_settings"]["color_blue"]),
        )
    if name not in _NAMED_HUD_COLORS:
        raise RuntimeError(
            f"Unknown hud_settings color {name!r}; expected 'default', 'custom', or one of "
            f"{sorted(_NAMED_HUD_COLORS)}."
        )
    return _NAMED_HUD_COLORS[name]


def cosmetics_dict(mp2_settings: MetroidPrime2Settings) -> dict[str, Any]:
    """Builds the ``settings`` dict ``client.patcher_runner.
    patch_iso_with_ap`` expects (see its ``_load_configuration``
    docstring): ``hud_color`` as an RGB 0-255 3-tuple (omitted entirely for
    "default", leaving OPR's own default main_color in place), and
    ``suit_replacement`` as ``{"varia": ..., "dark": ..., "light": ...}``.

    This matches ``client/patcher_runner.py``'s existing contract exactly
    (it already accepts int-or-float RGB and a plain suit_replacement
    dict), so no changes to ``patcher_runner.py`` were needed for this
    deliverable.
    """
    result: dict[str, Any] = {}

    hud_rgb = _hud_color_rgb(mp2_settings)
    if hud_rgb is not None:
        result["hud_color"] = hud_rgb

    result["suit_replacement"] = {
        "varia": str(mp2_settings["suit_settings"]["varia_skin"]),
        "dark": str(mp2_settings["suit_settings"]["dark_skin"]),
        "light": str(mp2_settings["suit_settings"]["light_skin"]),
    }

    return result
