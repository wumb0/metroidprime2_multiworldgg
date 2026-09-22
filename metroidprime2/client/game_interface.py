"""Dolphin memory interface for Metroid Prime 2: Echoes (PLAN.md section J
deliverable 3).

Every ``open_prime_rando``/``retro_data_structures`` import here is
deferred into the methods that need it, so this module (and therefore
``client/dolphin_client.py`` / ``client/versions.py`` importers) can be
imported without the patcher stack installed; only actually talking to a
running Dolphin (``execute``/``grant``/``consume_counters``/
``send_hud_message``) requires it.

Protocol reference: ``open_prime_rando.dol_patching.all_prime_dol_patches``
and randovania's ``PrimeRemoteConnector``/``EchoesRemoteConnector`` (see
PLAN.md Context facts and section J).
"""

from __future__ import annotations

import struct
import time
import uuid
from enum import Enum
from logging import Logger
from typing import TYPE_CHECKING

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

# Version detection reads the 6-byte disc id at 0x80000000 and matches it
# against each known version's ``game_id`` (the "NR"-suffixed patched id --
# see ``versions.NTSC``'s comment).
#
# Right after Dolphin launches (or right after a savestate/game boot) the
# memory hook can attach and read the game id before the disc has actually
# finished booting -- e.g. leftover memory from a previous run, or a
# partial DMA of the disc header -- which reads as something other than a
# real, known game id. Rather than treat that first read as a definitive
# "wrong game"/failure, connect_to_game() retries the hook+read a few times
# with backoff before settling on whatever it last saw. dolphin-memory-engine
# caches the emulated MEM1 region address the moment hook() runs (and keeps
# its cached instance alive even across a failed hook()), so a hook taken too
# early can keep returning a stale region forever -- every attempt therefore
# calls un_hook()+hook() unconditionally (DolphinClient.connect) to force a
# full region rescan. Only the last attempt's result (or error) is kept.
_GAME_ID_CONNECT_ATTEMPTS = 5
_GAME_ID_RETRY_BASE_DELAY = 0.2  # seconds
_GAME_ID_RETRY_MAX_DELAY = 2.0  # seconds
_EMPTY_GAME_ID = b"\x00\x00\x00\x00\x00\x00"

# dolphin-memory-engine's Windows hook() finds the MEM1 buffer purely by
# scanning the Dolphin process for a *same-sized* memory region -- it does
# not inspect the region's contents at all (upstream's own comment in
# WindowsDolphinProcess.cpp: "it can happen that multiple pages with these
# criteria exist[] and have nothing to do with the emulated memory"). So a
# "hooked" status doesn't guarantee we're actually looking at real GC RAM;
# a decoy region can read back as 6 bytes of unrelated process memory that
# happen not to be empty and don't match a known game id, which otherwise
# looks identical to "genuinely the wrong disc". Every real GameCube disc
# header carries a fixed magic word here once it's actually been read into
# RAM (see YAGCD / Dolphin's DiscIO::Volume -- offset 0x1c of the disc
# header), so requiring it too filters out decoy regions/pre-boot reads
# from a real, if unrecognized, disc header -- at the cost of not being
# able to tell "decoy region" apart from "real disc, but somehow corrupt
# header", which is an acceptable tradeoff since the latter shouldn't
# happen with a real GC disc/ISO.
_GC_DISC_MAGIC_WORD_OFFSET = 0x1C
_GC_DISC_MAGIC_WORD = b"\xc2\x33\x9f\x3d"

# Rehooking (un_hook()+hook()) forces a full region rescan, but that rescan
# runs against the same still-running Dolphin process -- if hook() latched
# onto a wrong-but-plausible MEM1 candidate region, that match tends to be
# stable for the process's lifetime, so rehooking keeps re-finding the same
# wrong region instead of clearing it. Once connect_to_game() has seen the
# exact same unrecognized game id this many times in a row (across separate
# calls from the sync loop, each of which already retries internally), warn
# that a full Dolphin restart -- not just reloading the game -- may be needed.
_STUCK_HOOK_WARNING_THRESHOLD = 5


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


def _wide_decrement_patch(
    powerup_functions: PowerupFunctionsAddresses, item_id: int, amount: int
) -> list[BaseInstruction]:
    """Amount-only ``decr_pickup(item_id, amount)`` call for a counter
    whose value can exceed the signed 16-bit range
    ``open_prime_rando.dol_patching.all_prime_dol_patches.
    adjust_item_amount_patch`` assumes (PLAN.md section P's constraint-1
    escape hatch, taken once the reserved-id accounting forced the layout
    down to 4 counters of 30 usable bits each -- see
    ``constants.PICKUP_COUNTER_ITEMS``'s docstring for why).

    ``adjust_item_amount_patch`` builds its amount operand with
    ``li(r5, abs(delta))`` -- ``addi rD, r0, SIMM16``, a SIGNED 16-bit
    immediate (``Instruction.compose`` asserts
    ``-32768 <= literal < 32768``) -- so it cannot express an amount
    bigger than 32767. This builds the exact same
    ``_load_player_state`` -> ``li(r4, item_id)`` -> ``bl(decr_pickup)``
    shape (mirroring ``adjust_item_amount_patch``'s own negative-delta
    branch), just with a wider amount load: ``lis`` loads the high 16
    bits into r5 and ``ori`` ORs in the low 16 bits. Both ``addis``'s and
    ``ori``'s literal fields are UNSIGNED 16-bit per
    ``Instruction.compose`` (``0 <= it < 65536``), and both halves below
    are masked to ``0xFFFF`` before being passed in, so neither call can
    ever fail that assert regardless of ``amount`` -- unlike ``li``, there
    is no upper bound this trips over short of the 32-bit register itself.

    ``amount`` must be >= 0: this only ever decrements (there is no
    ``incr_pickup`` counterpart here, matching ``consume_counters``'s
    contract that every delta it's given is already the exact negative
    amount to remove).

    ``_load_player_state`` is private to ``all_prime_dol_patches``, not
    part of its public API -- importing it directly is acceptable here
    because ``pyproject.toml`` pins ``open-prime-rando==0.20.1`` exactly.
    On Echoes (the only game this world targets) it is a single
    instruction, ``lwz(r3, 0x150C, r31)``; inline that literal ``lwz`` in
    place of the import if a future OPR version ever removes or changes
    it.
    """
    assert amount >= 0, f"_wide_decrement_patch amount must be non-negative, got {amount}"

    from open_prime_rando.dol_patching.all_prime_dol_patches import _load_player_state
    from ppc_asm.assembler.ppc import bl, li, lis, ori, r3, r4, r5, r31
    from retro_data_structures.game_check import Game

    return [
        *_load_player_state(Game.ECHOES, r3, r31),
        li(r4, item_id),
        lis(r5, (amount >> 16) & 0xFFFF),
        ori(r5, r5, amount & 0xFFFF),
        bl(powerup_functions.decr_pickup),
    ]


class EchoesInterface:
    logger: Logger
    dolphin_client: DolphinClient
    version: versions.EchoesVersionInfo | None
    expected_uuid: str | None
    last_connect_error: str | None
    """Human-readable reason the most recent ``connect_to_game()`` call
    didn't end up with a matched ``version`` -- None once it succeeds."""

    def __init__(self, logger: Logger):
        self.logger = logger
        self.dolphin_client = DolphinClient(logger)
        self.version = None
        self.expected_uuid = None
        self.last_connect_error: str | None = None
        self._logged_wrong_game_id: bytes | None = None
        self._wrong_game_id_repeat_count = 0
        self._warned_stuck_hook = False
        self._last_message_size = 0

    # ----------------------------------------------------------------
    # Connection / version detection
    # ----------------------------------------------------------------

    def connect_to_game(
        self,
        attempts: int = _GAME_ID_CONNECT_ATTEMPTS,
        base_delay: float = _GAME_ID_RETRY_BASE_DELAY,
        max_delay: float = _GAME_ID_RETRY_MAX_DELAY,
    ) -> None:
        """Hooks into Dolphin if needed, then reads the 6-byte game id at
        0x80000000 to pick NTSC/PAL (or neither). A non-empty id is also
        required to carry the real GC disc magic word at offset 0x1c before
        it's trusted (see the ``_GC_DISC_MAGIC_WORD`` comment) -- otherwise
        it's most likely a decoy memory region dolphin-memory-engine's
        size-only hook heuristic latched onto, not a real (if unexpected)
        disc.

        Hooking and reading is retried up to ``attempts`` times (with
        exponential backoff between tries, capped at ``max_delay``) as long
        as the read game id isn't recognized -- either a known version or
        the all-zero "nothing loaded yet" sentinel -- since an unrecognized
        id can just mean Dolphin was hooked before the disc finished
        booting. Every retry un-hooks first (DolphinClient.connect) so a
        stale hook can't keep returning a dead region forever. Only the
        last attempt's result (or error) is kept."""
        last_error: DolphinException | None = None
        game_id: bytes | None = None
        delay = base_delay
        attempts = max(1, attempts)

        for attempt in range(attempts):
            try:
                # Unconditionally un_hook()+hook() every attempt (see
                # DolphinClient.connect): a hook taken before the game booted
                # can stay stuck on a wrong region until the engine's cached
                # instance is destroyed and rebuilt.
                self.dolphin_client.connect()
                game_id = self.dolphin_client.read_address(_GC_GAME_ID_ADDRESS, 6)
                if game_id != _EMPTY_GAME_ID:
                    magic = self.dolphin_client.read_address(
                        _GC_GAME_ID_ADDRESS + _GC_DISC_MAGIC_WORD_OFFSET, 4
                    )
                    if magic != _GC_DISC_MAGIC_WORD:
                        # Doesn't look like a real disc header at all -- most
                        # likely a decoy region or a read taken before boot
                        # copied the header in. Treat like any other
                        # unrecognized read rather than a confirmed "wrong
                        # disc", so it retries instead of settling on it.
                        game_id = None
                last_error = None
            except DolphinException as e:
                game_id = None
                last_error = e

            recognized = game_id is not None and (
                game_id == _EMPTY_GAME_ID or any(v.game_id == game_id for v in versions.VERSIONS)
            )
            if recognized:
                break

            # No match; leave the hook dropped so the next outer sync-loop
            # tick (or retry below) rebuilds it from scratch again.
            self.dolphin_client.disconnect()

            if game_id == _EMPTY_GAME_ID or attempt == attempts - 1:
                break
            time.sleep(delay)
            delay = min(delay * 2, max_delay)

        if last_error is not None:
            self.version = None
            self.last_connect_error = str(last_error)
            return

        matched = next((v for v in versions.VERSIONS if v.game_id == game_id), None)
        if matched is None:
            self.version = None
            if game_id is None or game_id == _EMPTY_GAME_ID:
                self.last_connect_error = "Hooked into Dolphin, but no game is loaded yet."
            else:
                self.last_connect_error = (
                    f"Connected to the wrong game ({game_id!r}); please load an NTSC-U or "
                    "PAL Metroid Prime 2: Echoes ISO."
                )
                if game_id != self._logged_wrong_game_id:
                    self.logger.info(self.last_connect_error)
                    self._logged_wrong_game_id = game_id
                    self._wrong_game_id_repeat_count = 1
                    self._warned_stuck_hook = False
                else:
                    self._wrong_game_id_repeat_count += 1

                if (
                    self._wrong_game_id_repeat_count >= _STUCK_HOOK_WARNING_THRESHOLD
                    and not self._warned_stuck_hook
                ):
                    self._warned_stuck_hook = True
                    self.logger.warning(
                        "Still reading the same unexpected game id after several reconnect "
                        "attempts. If Metroid Prime 2: Echoes is definitely loaded, "
                        "dolphin-memory-engine may have hooked a stale/wrong memory region "
                        "that re-hooking can't clear on its own -- fully close and reopen "
                        "Dolphin (not just reloading the game) to fix this."
                    )
            return

        self._logged_wrong_game_id = None
        self._wrong_game_id_repeat_count = 0
        self._warned_stuck_hook = False
        self.last_connect_error = None
        self.version = matched

    def disconnect_from_game(self) -> None:
        self.dolphin_client.disconnect()
        self.version = None
        self._logged_wrong_game_id = None
        self._wrong_game_id_repeat_count = 0
        self._warned_stuck_hook = False

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

    def current_area_id(self) -> int | None:
        """TAreaId of the area the player is currently in (u32 at
        ``cstate_manager_global + AREA_ID_OFFSET``), or None if Dolphin isn't
        connected. This is an *index* into the current MLVL's area list, not
        an MREA asset id -- see ``constants.GAME_END_AREA_INDICES``."""
        if self.version is None:
            return None
        return self._read_u32(self.version.cstate_manager_global + versions.AREA_ID_OFFSET)

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

    def consume_counters(self, deltas: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """Clears the exact amount ``pickup_encoding.decode`` read off each
        counter this tick (``deltas`` are already negative -- PLAN.md
        section P point 2: consume the exact value read, never a blanket
        zero, so a pickup landing between the read and this consume
        survives to the next tick instead of being silently discarded).

        This mirrors ``grant``'s own batching/leftover mechanics (one
        remote-execution body per tick, up to the ~420-byte budget --
        PLAN.md section P constraint 7: all four pickup counters
        comfortably fit in one, with room to spare) but is NOT built on
        ``grant`` itself, since ``grant`` always adjusts capacity alongside
        amount and that is wrong here: a pickup counter's capacity only
        ever needs to grow, and it self-manages via the native additive
        pickup path (constraint 4, with ``COUNTER_MAX_CAPACITY`` large
        enough that it never wraps).

        Each counter goes through ``_wide_decrement_patch`` rather than
        OPR's ``adjust_item_amount_patch``: a counter holds up to
        ``2**constants.BITS_PER_COUNTER - 1`` (30 bits), which does not fit
        that patch's signed 16-bit ``li`` (PLAN.md section P's constraint-1
        escape hatch).
        """
        powerup_functions = self._powerup_functions_addresses()
        batch_instructions: list[BaseInstruction] = []
        batch_count = 0
        leftovers: list[tuple[int, int]] = []
        exhausted = False

        for item_id, delta in deltas:
            if exhausted:
                leftovers.append((item_id, delta))
                continue

            item_instructions = _wide_decrement_patch(powerup_functions, item_id, -delta)

            candidate = [*batch_instructions, *item_instructions]
            try:
                self._try_body(candidate, None)
            except ValueError:
                if batch_count == 0:
                    # A single counter's consume alone exceeds the budget -- shouldn't
                    # happen given the ~420-byte budget, but don't get stuck retrying
                    # it forever.
                    self.logger.error(
                        f"Consume for item {item_id} (delta {delta}) alone exceeds the "
                        "remote-execution body budget; dropping it."
                    )
                    continue
                leftovers.append((item_id, delta))
                exhausted = True
                continue

            batch_instructions = candidate
            batch_count += 1

        if batch_count > 0:
            self.execute(batch_instructions, None)

        return leftovers

    def send_hud_message(self, message: str) -> bool:
        """Standalone HUD message (no item deltas), for
        ``NotificationManager``/``/test_hud``. Returns False (and does
        nothing) if a remote-execution op is already pending, so the
        caller can retry later."""
        if self.version is None or self.has_pending_op():
            return False
        self.execute([], message)
        return True
