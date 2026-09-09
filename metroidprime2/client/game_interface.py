"""Dolphin memory interface for Metroid Prime 2: Echoes (PLAN.md section J
deliverable 3).

Every ``open_prime_rando``/``retro_data_structures`` import here is
deferred into the methods that need it, so this module (and therefore
``client/dolphin_client.py`` / ``client/versions.py`` importers) can be
imported without the patcher stack installed; only actually talking to a
running Dolphin (``execute``/``grant``/``consume_magic_item``/
``ensure_magic_capacity``/``send_hud_message``) requires it.

Protocol reference: ``open_prime_rando.dol_patching.all_prime_dol_patches``
and randovania's ``PrimeRemoteConnector``/``EchoesRemoteConnector`` (see
PLAN.md Context facts and section J).
"""

from __future__ import annotations

import struct
import uuid
from enum import Enum
from logging import Logger
from typing import TYPE_CHECKING

from .. import constants
from . import versions
from .dolphin_client import DolphinClient, DolphinException

if TYPE_CHECKING:
    from open_prime_rando.dol_patching.all_prime_dol_patches import (
        PowerupFunctionsAddresses,
        StringDisplayPatchAddresses,
    )
    from ppc_asm.assembler import BaseInstruction

_GC_GAME_ID_ADDRESS = 0x80000000
_MESSAGE_OVERHEAD = 6
_MAGIC_ITEM_MIN_CAPACITY = 4096


class ConnectionState(Enum):
    DISCONNECTED = 0
    WRONG_GAME = 1
    WRONG_SEED = 2
    IN_MENU = 3
    IN_GAME = 4


def encode_hud_message(message: str, max_message_size: int, last_encoded_size: int) -> tuple[bytes, int]:
    """UTF-16-BE encodes ``message`` the way the game's wstring constructor
    expects it in the message-receiver buffer (randovania's
    ``PrimeRemoteConnector._write_string_to_game_buffer``): truncated to
    ``max_message_size - 6`` bytes, null-terminated, padded to a multiple
    of 4 bytes, with a trailing space appended when the encoded body is
    the same byte length as the previous message (the game doesn't
    re-display a string at the same address with the same size).

    Returns the encoded bytes and the new "last encoded size" the caller
    should remember for the next call (measured before the null
    terminator/padding are appended, matching randovania's
    ``_last_message_size`` bookkeeping).
    """
    encoded_message = message.encode("utf-16-be")[: max_message_size - _MESSAGE_OVERHEAD]

    if len(encoded_message) == last_encoded_size:
        encoded_message += b"\x00 "

    new_last_encoded_size = len(encoded_message)

    encoded_message += b"\x00\x00"
    if len(encoded_message) & 3:
        num_to_align = (len(encoded_message) | 3) - len(encoded_message) + 1
        encoded_message += b"\x00" * num_to_align

    return encoded_message, new_last_encoded_size


class EchoesInterface:
    logger: Logger
    dolphin_client: DolphinClient
    version: versions.EchoesVersionInfo | None
    expected_uuid: str | None

    def __init__(self, logger: Logger):
        self.logger = logger
        self.dolphin_client = DolphinClient(logger)
        self.version = None
        self.expected_uuid = None
        self._logged_wrong_game_id: bytes | None = None
        self._last_message_size = 0

    # ----------------------------------------------------------------
    # Connection / version detection
    # ----------------------------------------------------------------

    def connect_to_game(self) -> None:
        """Hooks into Dolphin if needed, then reads the 6-byte game id at
        0x80000000 to pick NTSC/PAL (or neither)."""
        try:
            if not self.dolphin_client.is_connected():
                self.dolphin_client.connect()
            game_id = self.dolphin_client.read_address(_GC_GAME_ID_ADDRESS, 6)
        except DolphinException:
            self.version = None
            return

        matched = next((v for v in versions.VERSIONS if v.game_id == game_id), None)
        if matched is None:
            self.version = None
            if game_id != b"\x00\x00\x00\x00\x00\x00" and game_id != self._logged_wrong_game_id:
                self.logger.info(
                    f"Connected to the wrong game ({game_id!r}); please load an NTSC-U or "
                    "PAL Metroid Prime 2: Echoes ISO."
                )
                self._logged_wrong_game_id = game_id
            return

        self._logged_wrong_game_id = None
        self.version = matched

    def disconnect_from_game(self) -> None:
        self.dolphin_client.disconnect()
        self.version = None

    def read_build_string(self) -> tuple[bool, uuid.UUID | None]:
        """Returns (matches, embedded_uuid). ``matches`` is True if the
        header (bytes[:6]) and tail (bytes[22:]) of the build string at
        ``version.build_string_address`` match this version's known build
        string -- i.e. this is genuinely a patched Metroid Prime 2: Echoes
        build, whether or not it embeds a uuid. ``embedded_uuid`` is the
        16 bytes at ``build_string_address + 6`` decoded as a UUID, or
        None if the build string is unpatched (vanilla) or didn't match at
        all (randovania's ``PrimeRemoteConnector.check_for_world_uid`` /
        OPR's ``apply_build_info_patch``)."""
        assert self.version is not None
        data = self.dolphin_client.read_address(
            self.version.build_string_address, len(self.version.build_string)
        )
        if data is None:
            return False, None

        expected = self.version.build_string
        if data[:6] != expected[:6] or data[22:] != expected[22:]:
            return False, None

        embedded = data[6:22]
        if bytes(embedded) == bytes(expected[6:22]):
            # Exported with an old/non-multiworld patcher: no uuid embedded.
            return True, None
        return True, uuid.UUID(bytes=bytes(embedded))

    def get_connection_state(self) -> ConnectionState:
        if not self.dolphin_client.is_connected() or self.version is None:
            return ConnectionState.DISCONNECTED

        try:
            matches, world_uuid = self.read_build_string()
        except DolphinException:
            return ConnectionState.DISCONNECTED

        if not matches:
            return ConnectionState.WRONG_GAME

        if self.expected_uuid is not None and world_uuid is not None and str(world_uuid) != self.expected_uuid:
            return ConnectionState.WRONG_SEED

        if self.is_in_game():
            return ConnectionState.IN_GAME
        return ConnectionState.IN_MENU

    # ----------------------------------------------------------------
    # Raw state reads
    # ----------------------------------------------------------------

    def _read_u32(self, address: int) -> int | None:
        try:
            data = self.dolphin_client.read_address(address, 4)
        except DolphinException:
            return None
        if data is None:
            return None
        return struct.unpack(">I", data)[0]

    def current_mlvl(self) -> int | None:
        """u32 at *(game_state_pointer) + 4."""
        if self.version is None:
            return None
        game_state = self._read_u32(self.version.game_state_pointer)
        if not game_state:
            return None
        return self._read_u32(game_state + 4)

    def is_in_game(self) -> bool:
        """*(cstate + CPLAYER_OFFSET) != 0 and its vtable == cplayer_vtable,
        and the current MLVL is a known *world* (not the menu/frontend)."""
        if self.version is None:
            return False

        cplayer_ptr = self._read_u32(self.version.cstate_manager_global + versions.CPLAYER_OFFSET)
        if not cplayer_ptr:
            return False

        vtable = self._read_u32(cplayer_ptr)
        if vtable != self.version.cplayer_vtable:
            return False

        mlvl = self.current_mlvl()
        return mlvl is not None and versions.KNOWN_MLVLS.get(mlvl) == "world"

    def has_pending_op(self) -> bool:
        """Byte at cstate + PENDING_OP_OFFSET; non-zero means the game
        hasn't consumed the last remote-execution body yet."""
        if self.version is None:
            return True  # Unknown state -- be conservative and don't write.
        data = self.dolphin_client.read_address(
            self.version.cstate_manager_global + versions.PENDING_OP_OFFSET, 1
        )
        return data != b"\x00"

    def write_pending_op(self) -> None:
        assert self.version is not None
        self.dolphin_client.write_address(
            self.version.cstate_manager_global + versions.PENDING_OP_OFFSET, b"\x01"
        )

    def read_inventory(self) -> dict[int, tuple[int, int]] | None:
        """Single 109*12-byte read at *(cstate + PLAYER_STATE_OFFSET) +
        INVENTORY_OFFSET, unpacked into {item_id: (amount, capacity)}.
        Returns None if the CPlayerState pointer is currently null (e.g.
        during an elevator transition) or Dolphin isn't connected."""
        player_state = self._player_state_pointer()
        if player_state is None:
            return None

        try:
            data = self.dolphin_client.read_address(
                player_state + versions.INVENTORY_OFFSET,
                versions.INVENTORY_ITEM_COUNT * versions.INVENTORY_ITEM_SIZE,
            )
        except DolphinException:
            return None
        if data is None:
            return None

        inventory: dict[int, tuple[int, int]] = {}
        for item_id in range(versions.INVENTORY_ITEM_COUNT):
            amount, capacity = struct.unpack_from(">II", data, item_id * versions.INVENTORY_ITEM_SIZE)
            inventory[item_id] = (amount, capacity)
        return inventory

    def _player_state_pointer(self) -> int | None:
        if self.version is None:
            return None
        return self._read_u32(self.version.cstate_manager_global + versions.PLAYER_STATE_OFFSET) or None

    def get_current_health(self) -> float | None:
        """Current HP (``CPlayerState::CalculateHealth``'s backing field,
        ``versions.HEALTH_OFFSET``). None if the CPlayerState pointer is
        currently null (e.g. during an elevator transition) or Dolphin
        isn't connected."""
        player_state = self._player_state_pointer()
        if player_state is None:
            return None

        try:
            data = self.dolphin_client.read_address(player_state + versions.HEALTH_OFFSET, 4)
        except DolphinException:
            return None
        if data is None:
            return None
        return struct.unpack(">f", data)[0]

    def set_current_health(self, new_health_amount: float) -> None:
        """Direct write to the same field ``get_current_health`` reads --
        used to kill the player on an incoming DeathLink (mirrors
        ``worlds/metroidprime``'s raw CPlayerState pokes; there's no
        remote-execution-safe way to force a death through the normal
        item-grant call path)."""
        player_state = self._player_state_pointer()
        if player_state is None:
            return
        try:
            self.dolphin_client.write_address(
                player_state + versions.HEALTH_OFFSET, struct.pack(">f", new_health_amount)
            )
        except DolphinException:
            # Called from on_deathlink(), which runs on the server-loop package
            # handler -- a dropped connection mid-write must not propagate out
            # of that handler, matching every other Dolphin access in this class.
            return

    # ----------------------------------------------------------------
    # OPR dataclass construction (lazy import)
    # ----------------------------------------------------------------

    def _string_display_addresses(self) -> StringDisplayPatchAddresses:
        from open_prime_rando.dol_patching.all_prime_dol_patches import StringDisplayPatchAddresses

        assert self.version is not None
        sd = self.version.string_display
        return StringDisplayPatchAddresses(
            update_hint_state=sd.update_hint_state,
            message_receiver_string_ref=sd.message_receiver_string_ref,
            wstring_constructor=sd.wstring_constructor,
            display_hud_memo=sd.display_hud_memo,
            max_message_size=sd.max_message_size,
        )

    def _powerup_functions_addresses(self) -> PowerupFunctionsAddresses:
        from open_prime_rando.dol_patching.all_prime_dol_patches import PowerupFunctionsAddresses

        assert self.version is not None
        pf = self.version.powerup_functions
        return PowerupFunctionsAddresses(
            add_power_up=pf.add_power_up,
            incr_pickup=pf.incr_pickup,
            decr_pickup=pf.decr_pickup,
        )

    # ----------------------------------------------------------------
    # Remote execution
    # ----------------------------------------------------------------

    def _try_body(
        self, instructions: list[BaseInstruction], message: str | None
    ) -> tuple[int, bytes]:
        """Builds the remote-execution body for ``instructions`` (plus a
        ``call_display_hud_patch`` tail if ``message`` is not None).
        Raises ValueError (via ``create_remote_execution_body``) if the
        result exceeds the 420-byte remote-execution budget."""
        from open_prime_rando.dol_patching import all_prime_dol_patches
        from retro_data_structures.game_check import Game

        string_display = self._string_display_addresses()
        final_instructions = list(instructions)
        if message is not None:
            final_instructions.extend(all_prime_dol_patches.call_display_hud_patch(string_display))
        return all_prime_dol_patches.create_remote_execution_body(Game.ECHOES, string_display, final_instructions)

    def execute(self, instructions: list[BaseInstruction], message: str | None = None) -> None:
        """Writes ``message`` (if any) to the message-receiver buffer,
        THEN writes the remote-execution body (``instructions`` plus a HUD
        display call when there's a message), THEN arms it by writing
        b"\\x01" to cstate + PENDING_OP_OFFSET last."""
        assert self.version is not None
        address, body = self._try_body(instructions, message)

        if message is not None:
            encoded, new_last_size = encode_hud_message(
                message, self.version.string_display.max_message_size, self._last_message_size
            )
            self._last_message_size = new_last_size
            self.dolphin_client.write_address(self.version.string_display.message_receiver_string_ref, encoded)

        self.dolphin_client.write_address(address, body)
        self.write_pending_op()

    def grant(
        self, deltas: list[tuple[int, int]], message: str | None = None
    ) -> list[tuple[int, int]]:
        """Executes as many (item_id, delta) capacity/amount adjustments
        as fit in a single remote-execution body (batching via
        ``create_remote_execution_body``'s 420-byte limit -- PLAN.md
        Context fact 33/Risk L5), then returns the leftover deltas that
        didn't fit this tick (in order, for the next call)."""
        from open_prime_rando.dol_patching import all_prime_dol_patches
        from retro_data_structures.game_check import Game

        powerup_functions = self._powerup_functions_addresses()

        batch_instructions: list[BaseInstruction] = []
        batch_count = 0
        leftovers: list[tuple[int, int]] = []
        exhausted = False

        for item_id, delta in deltas:
            if exhausted:
                leftovers.append((item_id, delta))
                continue

            candidate = [
                *batch_instructions,
                *all_prime_dol_patches.adjust_item_amount_and_capacity_patch(
                    powerup_functions, Game.ECHOES, item_id, delta
                ),
            ]
            try:
                self._try_body(candidate, message)
            except ValueError:
                if batch_count == 0:
                    # A single item's patch alone exceeds the budget -- shouldn't
                    # happen given the ~420-byte budget, but don't get stuck
                    # retrying it forever.
                    self.logger.error(
                        f"Grant for item {item_id} (delta {delta}) alone exceeds the "
                        "remote-execution body budget; dropping it."
                    )
                    continue
                leftovers.append((item_id, delta))
                exhausted = True
                continue

            batch_instructions = candidate
            batch_count += 1

        if batch_count > 0:
            self.execute(batch_instructions, message)

        return leftovers

    def consume_magic_item(self, amount: int) -> None:
        """adjust_item_amount_patch(MAGIC_ITEM, -amount) -- amount only,
        capacity is left untouched (PLAN.md section J)."""
        from open_prime_rando.dol_patching import all_prime_dol_patches
        from retro_data_structures.game_check import Game

        instructions = all_prime_dol_patches.adjust_item_amount_patch(
            self._powerup_functions_addresses(), Game.ECHOES, constants.MAGIC_ITEM, -amount
        )
        self.execute(instructions, None)

    def ensure_magic_capacity(self, capacity: int) -> None:
        """Tops up the magic item's capacity to at least 4096 so its
        amount can climb well past the 119 real pickup indices (and the
        120 goal sentinel) without wrapping (PLAN.md Context fact 33/Risk
        L5)."""
        if capacity >= _MAGIC_ITEM_MIN_CAPACITY:
            return
        from open_prime_rando.dol_patching import all_prime_dol_patches
        from retro_data_structures.game_check import Game

        instructions = all_prime_dol_patches.increment_item_capacity_patch(
            self._powerup_functions_addresses(),
            Game.ECHOES,
            constants.MAGIC_ITEM,
            _MAGIC_ITEM_MIN_CAPACITY - capacity,
        )
        self.execute(instructions, None)

    def send_hud_message(self, message: str) -> bool:
        """Standalone HUD message (no item deltas), for
        ``NotificationManager``/``/test_hud``. Returns False (and does
        nothing) if a remote-execution op is already pending, so the
        caller can retry later."""
        if self.version is None or self.has_pending_op():
            return False
        self.execute([], message)
        return True
