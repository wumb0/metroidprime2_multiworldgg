"""M3 tests: ``client/game_interface.py``'s ``EchoesInterface`` and
``encode_hud_message``, exercised against a fake ``DolphinClient`` (no
Dolphin/ISO needed -- PLAN.md section K (M3) explicitly rules out a live
connection here) and, for the remote-execution body-budget test, the real
open-prime-rando ``create_remote_execution_body`` so the size check is
against the actual 420-byte limit rather than a guess.
"""

from __future__ import annotations

import importlib.util
import logging
import struct
import unittest

from ..client import versions
from ..client.dolphin_client import DolphinClient, DolphinException
from ..client.game_interface import ConnectionState, EchoesInterface, encode_hud_message

_OPR_AVAILABLE = importlib.util.find_spec("open_prime_rando") is not None
_NULL_LOGGER = logging.getLogger("metroidprime2.test.test_game_interface")


class FakeDolphinClient:
    """Stands in for ``client.dolphin_client.DolphinClient`` in tests: a
    sparse ``{address: bytes}`` memory map, with every ``write_address``
    call recorded so tests can assert on write order/count without a real
    emulator."""

    def __init__(self) -> None:
        self.memory: dict[int, bytes] = {}
        self.writes: list[tuple[int, bytes]] = []
        self.connected = True
        self.connect_calls = 0
        self.disconnect_calls = 0

    def is_connected(self) -> bool:
        return self.connected

    def connect(self) -> None:
        self.connect_calls += 1
        self.connected = True

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    def read_address(self, address: int, bytes_to_read: int):
        data = self.memory.get(address)
        if data is None or len(data) != bytes_to_read:
            raise DolphinException(f"no fake memory at {address:#x} for {bytes_to_read} bytes")
        return data

    def write_address(self, address: int, data: bytes):
        self.memory[address] = bytes(data)
        self.writes.append((address, bytes(data)))
        return True


def _make_interface() -> tuple[EchoesInterface, FakeDolphinClient]:
    interface = EchoesInterface(_NULL_LOGGER)
    fake = FakeDolphinClient()
    interface.dolphin_client = fake  # type: ignore[assignment]
    return interface, fake


class TestVersionDetection(unittest.TestCase):
    def test_connect_to_game_detects_ntsc(self) -> None:
        interface, fake = _make_interface()
        fake.memory[0x80000000] = versions.NTSC.game_id
        interface.connect_to_game()
        self.assertIs(interface.version, versions.NTSC)

    def test_connect_to_game_detects_pal(self) -> None:
        interface, fake = _make_interface()
        fake.memory[0x80000000] = versions.PAL.game_id
        interface.connect_to_game()
        self.assertIs(interface.version, versions.PAL)

    def test_connect_to_game_wrong_game_leaves_version_none(self) -> None:
        interface, fake = _make_interface()
        fake.memory[0x80000000] = b"GM8E01"  # Metroid Prime 1, not Echoes.
        interface.connect_to_game(attempts=1, base_delay=0)
        self.assertIsNone(interface.version)


class TestConnectRetry(unittest.TestCase):
    """PLAN.md's Dolphin backoff/retry: connect_to_game() shouldn't settle
    on an unrecognized read (or a transient hook failure) from the brief
    window right after Dolphin launches, before it's retried the hook+read a
    few times."""

    def test_retries_past_transient_garbage_game_id(self) -> None:
        interface, fake = _make_interface()
        # Garbage game id on the first attempt (disc still booting); the
        # real id is in place by the second attempt.
        fake.memory[0x80000000] = b"\xff\xff\xff\xff\xff\xff"
        real_connect = fake.connect

        def flaky_connect() -> None:
            real_connect()
            if fake.connect_calls == 2:
                fake.memory[0x80000000] = versions.NTSC.game_id

        fake.connect = flaky_connect  # type: ignore[method-assign]

        interface.connect_to_game(attempts=5, base_delay=0)

        self.assertIs(interface.version, versions.NTSC)
        # The failed attempt must drop the (possibly stale) hook so the retry
        # rebuilds it from scratch instead of polling the same dead region.
        self.assertEqual(1, fake.disconnect_calls)
        self.assertEqual(2, fake.connect_calls)

    def test_wrong_game_id_drops_hook_so_next_call_rehooks(self) -> None:
        interface, fake = _make_interface()
        fake.memory[0x80000000] = b"\xff\xff\xff\xff\xff\xff"

        interface.connect_to_game(attempts=1, base_delay=0)

        self.assertIsNone(interface.version)
        # Hook is left dropped, so the sync loop's next connect_to_game()
        # (which only runs for DISCONNECTED) gets a fresh hook.
        self.assertFalse(fake.is_connected())
        self.assertEqual(1, fake.disconnect_calls)

        fake.memory[0x80000000] = versions.NTSC.game_id
        interface.connect_to_game()

        self.assertIs(interface.version, versions.NTSC)

    def test_retries_past_transient_hook_failure(self) -> None:
        interface, fake = _make_interface()
        fake.memory[0x80000000] = versions.NTSC.game_id
        fake.connected = False

        real_connect = fake.connect
        calls = {"count": 0}

        def flaky_connect() -> None:
            calls["count"] += 1
            if calls["count"] == 1:
                raise DolphinException("verify that you have a game running in the emulator")
            real_connect()

        fake.connect = flaky_connect  # type: ignore[method-assign]

        interface.connect_to_game(attempts=5, base_delay=0)

        self.assertIs(interface.version, versions.NTSC)
        self.assertEqual(calls["count"], 2)

    def test_gives_up_after_exhausting_attempts(self) -> None:
        interface, fake = _make_interface()
        fake.memory[0x80000000] = b"\xff\xff\xff\xff\xff\xff"

        calls = {"count": 0}
        real_read_address = fake.read_address

        def counting_read_address(address: int, bytes_to_read: int):
            calls["count"] += 1
            return real_read_address(address, bytes_to_read)

        fake.read_address = counting_read_address  # type: ignore[method-assign]

        interface.connect_to_game(attempts=3, base_delay=0)

        self.assertIsNone(interface.version)
        # One probe sequence per attempt, each dropping the hook first.
        self.assertEqual(3, fake.disconnect_calls)
        self.assertGreater(calls["count"], 0)


class TestBuildStringAndUuid(unittest.TestCase):
    def _patched_build_string(self, version: versions.EchoesVersionInfo, uid: bytes) -> bytes:
        data = bytearray(version.build_string)
        data[6:22] = uid
        return bytes(data)

    def test_matching_build_string_with_uuid(self) -> None:
        interface, fake = _make_interface()
        interface.version = versions.NTSC
        uid_bytes = bytes(range(16))
        fake.memory[versions.NTSC.build_string_address] = self._patched_build_string(versions.NTSC, uid_bytes)

        matches, found_uuid = interface.read_build_string()
        self.assertTrue(matches)
        assert found_uuid is not None
        self.assertEqual(uid_bytes, found_uuid.bytes)

    def test_unpatched_build_string_matches_with_no_uuid(self) -> None:
        interface, fake = _make_interface()
        interface.version = versions.NTSC
        fake.memory[versions.NTSC.build_string_address] = versions.NTSC.build_string

        matches, found_uuid = interface.read_build_string()
        self.assertTrue(matches)
        self.assertIsNone(found_uuid)

    def test_wrong_game_build_string_does_not_match(self) -> None:
        interface, fake = _make_interface()
        interface.version = versions.NTSC
        garbage = b"\x00" * len(versions.NTSC.build_string)
        fake.memory[versions.NTSC.build_string_address] = garbage

        matches, found_uuid = interface.read_build_string()
        self.assertFalse(matches)
        self.assertIsNone(found_uuid)

    def test_get_connection_state_wrong_seed(self) -> None:
        interface, fake = _make_interface()
        interface.version = versions.NTSC
        interface.expected_uuid = "11111111-1111-1111-1111-111111111111"
        fake.memory[versions.NTSC.build_string_address] = self._patched_build_string(
            versions.NTSC, bytes(range(16))
        )
        self.assertEqual(ConnectionState.WRONG_SEED, interface.get_connection_state())


def _set_u32(fake: FakeDolphinClient, address: int, value: int) -> None:
    fake.memory[address] = struct.pack(">I", value)


class TestInGameState(unittest.TestCase):
    def test_is_in_game_true_when_cplayer_and_mlvl_known(self) -> None:
        interface, fake = _make_interface()
        interface.version = versions.NTSC
        cplayer_addr = 0x80500000
        world_mlvl = next(iter(versions.KNOWN_MLVLS))

        _set_u32(fake, versions.NTSC.cstate_manager_global + versions.CPLAYER_OFFSET, cplayer_addr)
        _set_u32(fake, cplayer_addr, versions.NTSC.cplayer_vtable)

        game_state_addr = 0x80600000
        _set_u32(fake, versions.NTSC.game_state_pointer, game_state_addr)
        _set_u32(fake, game_state_addr + 4, world_mlvl)

        self.assertEqual(world_mlvl, interface.current_mlvl())
        self.assertTrue(interface.is_in_game())

    def test_is_in_game_false_when_cplayer_null(self) -> None:
        interface, fake = _make_interface()
        interface.version = versions.NTSC
        _set_u32(fake, versions.NTSC.cstate_manager_global + versions.CPLAYER_OFFSET, 0)
        self.assertFalse(interface.is_in_game())

    def test_is_in_game_false_at_menu_mlvl(self) -> None:
        interface, fake = _make_interface()
        interface.version = versions.NTSC
        cplayer_addr = 0x80500000
        _set_u32(fake, versions.NTSC.cstate_manager_global + versions.CPLAYER_OFFSET, cplayer_addr)
        _set_u32(fake, cplayer_addr, versions.NTSC.cplayer_vtable)

        menu_mlvl = next(mlvl for mlvl, kind in versions.KNOWN_MLVLS.items() if kind == "menu")
        game_state_addr = 0x80600000
        _set_u32(fake, versions.NTSC.game_state_pointer, game_state_addr)
        _set_u32(fake, game_state_addr + 4, menu_mlvl)

        self.assertFalse(interface.is_in_game())

    def test_current_area_id_reads_cstate_offset(self) -> None:
        interface, fake = _make_interface()
        interface.version = versions.NTSC
        _set_u32(fake, versions.NTSC.cstate_manager_global + versions.AREA_ID_OFFSET, 53)
        self.assertEqual(53, interface.current_area_id())

    def test_current_area_id_none_when_version_unset(self) -> None:
        interface, _fake = _make_interface()
        self.assertIsNone(interface.current_area_id())

    def test_current_area_id_none_when_unreadable(self) -> None:
        interface, _fake = _make_interface()
        interface.version = versions.NTSC
        self.assertIsNone(interface.current_area_id())

    def test_has_pending_op(self) -> None:
        interface, fake = _make_interface()
        interface.version = versions.NTSC
        fake.memory[versions.NTSC.cstate_manager_global + versions.PENDING_OP_OFFSET] = b"\x00"
        self.assertFalse(interface.has_pending_op())
        fake.memory[versions.NTSC.cstate_manager_global + versions.PENDING_OP_OFFSET] = b"\x01"
        self.assertTrue(interface.has_pending_op())


class TestReadInventory(unittest.TestCase):
    def test_parses_synthetic_109_item_buffer(self) -> None:
        interface, fake = _make_interface()
        interface.version = versions.NTSC

        player_state_addr = 0x80700000
        _set_u32(fake, versions.NTSC.cstate_manager_global + versions.PLAYER_STATE_OFFSET, player_state_addr)

        buffer = bytearray(versions.INVENTORY_ITEM_COUNT * versions.INVENTORY_ITEM_SIZE)
        expected: dict[int, tuple[int, int]] = {}
        for item_id in range(versions.INVENTORY_ITEM_COUNT):
            amount = item_id
            capacity = item_id * 2 + 1
            struct.pack_into(">II", buffer, item_id * versions.INVENTORY_ITEM_SIZE, amount, capacity)
            expected[item_id] = (amount, capacity)

        fake.memory[player_state_addr + versions.INVENTORY_OFFSET] = bytes(buffer)

        inventory = interface.read_inventory()
        self.assertEqual(expected, inventory)

    def test_null_player_state_pointer_returns_none(self) -> None:
        interface, fake = _make_interface()
        interface.version = versions.NTSC
        _set_u32(fake, versions.NTSC.cstate_manager_global + versions.PLAYER_STATE_OFFSET, 0)
        self.assertIsNone(interface.read_inventory())


class TestHealth(unittest.TestCase):
    def test_get_current_health_reads_float_at_health_offset(self) -> None:
        interface, fake = _make_interface()
        interface.version = versions.NTSC

        player_state_addr = 0x80700000
        _set_u32(fake, versions.NTSC.cstate_manager_global + versions.PLAYER_STATE_OFFSET, player_state_addr)
        fake.memory[player_state_addr + versions.HEALTH_OFFSET] = struct.pack(">f", 42.5)

        self.assertEqual(42.5, interface.get_current_health())

    def test_get_current_health_null_player_state_pointer_returns_none(self) -> None:
        interface, fake = _make_interface()
        interface.version = versions.NTSC
        _set_u32(fake, versions.NTSC.cstate_manager_global + versions.PLAYER_STATE_OFFSET, 0)
        self.assertIsNone(interface.get_current_health())

    def test_get_current_health_disconnected_returns_none(self) -> None:
        interface, _fake = _make_interface()
        interface.version = None
        self.assertIsNone(interface.get_current_health())

    def test_set_current_health_writes_float_at_health_offset(self) -> None:
        interface, fake = _make_interface()
        interface.version = versions.NTSC

        player_state_addr = 0x80700000
        _set_u32(fake, versions.NTSC.cstate_manager_global + versions.PLAYER_STATE_OFFSET, player_state_addr)

        interface.set_current_health(-1.0)

        self.assertEqual(
            struct.pack(">f", -1.0),
            fake.memory[player_state_addr + versions.HEALTH_OFFSET],
        )
        self.assertEqual(-1.0, interface.get_current_health())

    def test_set_current_health_null_player_state_pointer_is_a_noop(self) -> None:
        interface, fake = _make_interface()
        interface.version = versions.NTSC
        _set_u32(fake, versions.NTSC.cstate_manager_global + versions.PLAYER_STATE_OFFSET, 0)

        interface.set_current_health(-1.0)  # Must not raise.
        self.assertEqual([], fake.writes)


class TestHudEncoding(unittest.TestCase):
    def test_null_terminated_and_four_byte_aligned(self) -> None:
        encoded, _last_size = encode_hud_message("Hi", max_message_size=200, last_encoded_size=0)
        self.assertEqual(0, len(encoded) % 4)
        self.assertTrue(encoded.endswith(b"\x00\x00"))
        # "Hi" -> 4 UTF-16-BE bytes, +2 null terminator = 6 bytes, padded up
        # to the next multiple of 4 (8) with two more zero bytes.
        self.assertEqual(b"\x00H\x00i\x00\x00\x00\x00", encoded)

    def test_truncates_to_max_message_size_minus_overhead(self) -> None:
        max_message_size = 20
        message = "A" * 100
        encoded, last_size = encode_hud_message(message, max_message_size, last_encoded_size=0)
        # Body (before null terminator/padding) must not exceed max-6 bytes.
        self.assertLessEqual(last_size, max_message_size - 6)
        self.assertEqual(0, len(encoded) % 4)

    def test_same_length_as_last_message_appends_space(self) -> None:
        first, first_last_size = encode_hud_message("AB", max_message_size=200, last_encoded_size=0)
        # Same message again -> encoded body would be the same length, so a
        # differentiator space must be appended before the null terminator.
        second, _second_last_size = encode_hud_message("AB", max_message_size=200, last_encoded_size=first_last_size)
        self.assertNotEqual(first, second)
        self.assertIn(b"\x00 ", second)

    def test_different_length_does_not_append_space(self) -> None:
        _first, first_last_size = encode_hud_message("AB", max_message_size=200, last_encoded_size=0)
        second, _second_last_size = encode_hud_message("ABC", max_message_size=200, last_encoded_size=first_last_size)
        self.assertNotIn(b"\x00 \x00\x00", second)


@unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
class TestGrantBatching(unittest.TestCase):
    def _prepared_interface(self) -> tuple[EchoesInterface, FakeDolphinClient]:
        interface, fake = _make_interface()
        interface.version = versions.NTSC
        return interface, fake

    def test_grant_splits_large_delta_list_across_multiple_bodies(self) -> None:
        from open_prime_rando.dol_patching import all_prime_dol_patches
        from retro_data_structures.game_check import Game

        interface, fake = self._prepared_interface()

        deltas = [(item_id, 5) for item_id in range(20)]
        remaining = list(deltas)
        executed_batches: list[list[int]] = []
        granted_ids: list[int] = []

        for _ in range(len(deltas) + 1):
            if not remaining:
                break
            writes_before = len(fake.writes)
            leftovers = interface.grant(remaining, message="Test message")
            self.assertLess(len(leftovers), len(remaining), "grant() must make progress every call")

            batch_ids = [item_id for item_id, _delta in remaining if item_id not in {i for i, _ in leftovers}]
            executed_batches.append(batch_ids)
            granted_ids.extend(batch_ids)

            # Every call that grants anything writes the string, the body,
            # and the pending-op flag -- at least 3 writes.
            self.assertGreater(len(fake.writes) - writes_before, 0)

            remaining = leftovers

        self.assertEqual([], remaining)
        self.assertEqual(sorted(item_id for item_id, _delta in deltas), sorted(granted_ids))
        # 20 items with a HUD message definitely doesn't fit in one 420-byte
        # body (PLAN.md: "~8 per body, ~6 with message").
        self.assertGreater(len(executed_batches), 1)

        # Sanity-check against the real size limit directly: the full
        # 20-item instruction list (with the HUD patch) must NOT fit.
        powerup_functions = interface._powerup_functions_addresses()
        string_display = interface._string_display_addresses()
        all_instructions = []
        for item_id, delta in deltas:
            all_instructions.extend(
                all_prime_dol_patches.adjust_item_amount_and_capacity_patch(
                    powerup_functions, Game.ECHOES, item_id, delta
                )
            )
        all_instructions.extend(all_prime_dol_patches.call_display_hud_patch(string_display))
        with self.assertRaises(ValueError):
            all_prime_dol_patches.create_remote_execution_body(Game.ECHOES, string_display, all_instructions)

    def test_grant_writes_message_before_body_and_pending_op_last(self) -> None:
        interface, fake = self._prepared_interface()
        leftovers = interface.grant([(0, 1)], message="Hello")
        self.assertEqual([], leftovers)

        pending_op_address = versions.NTSC.cstate_manager_global + versions.PENDING_OP_OFFSET
        message_address = versions.NTSC.string_display.message_receiver_string_ref

        addresses_written = [address for address, _data in fake.writes]
        self.assertIn(message_address, addresses_written)
        self.assertIn(pending_op_address, addresses_written)
        # Message must be written strictly before the pending-op flag.
        self.assertLess(addresses_written.index(message_address), addresses_written.index(pending_op_address))
        # Pending-op flag is the very last write of the call.
        self.assertEqual(pending_op_address, addresses_written[-1])
        self.assertEqual(b"\x01", fake.memory[pending_op_address])


@unittest.skipUnless(_OPR_AVAILABLE, "open-prime-rando is not installed")
class TestConsumeCounters(unittest.TestCase):
    """PLAN.md section P's constraint-1 escape hatch: a pickup bitmask
    counter can hold up to 2**30 - 1 (BITS_PER_COUNTER), which doesn't fit
    ``adjust_item_amount_patch``'s signed 16-bit ``li`` -- ``consume_counters``
    routes every counter through ``_wide_decrement_patch`` instead. Exercised
    against real DOL addresses (``versions.NTSC``), like ``TestGrantBatching``
    above, specifically because a too-narrow instruction choice fails at
    *assembly* time (``Instruction.compose``'s range asserts), not at some
    higher-level check this module could fake around.
    """

    def _prepared_interface(self) -> tuple[EchoesInterface, FakeDolphinClient]:
        interface, fake = _make_interface()
        interface.version = versions.NTSC
        return interface, fake

    def test_wide_decrement_patch_assembles_for_a_full_30_bit_counter_value(self) -> None:
        from ppc_asm import assembler

        from ..client.game_interface import _wide_decrement_patch

        interface, _fake = self._prepared_interface()
        full_value = (1 << 30) - 1  # constants.BITS_PER_COUNTER
        instructions = _wide_decrement_patch(interface._powerup_functions_addresses(), 67, full_value)
        # The point of the test: this must not raise (Instruction.compose's
        # range asserts are exactly what li(r5, abs(delta)) would trip for
        # a value this large).
        assembled = bytes(assembler.assemble_instructions(versions.NTSC.cstate_manager_global, instructions))
        self.assertGreater(len(assembled), 0)

    def test_wide_decrement_patch_rejects_negative_amount(self) -> None:
        from ..client.game_interface import _wide_decrement_patch

        interface, _fake = self._prepared_interface()
        with self.assertRaises(AssertionError):
            _wide_decrement_patch(interface._powerup_functions_addresses(), 67, -1)

    def test_consume_counters_handles_several_full_counters_in_one_body(self) -> None:
        from .. import constants

        interface, fake = self._prepared_interface()
        full_value = (1 << constants.BITS_PER_COUNTER) - 1

        leftovers = interface.consume_counters(
            [(item_id, -full_value) for item_id in constants.PICKUP_COUNTER_ITEMS]
        )

        self.assertEqual([], leftovers)
        pending_op_address = versions.NTSC.cstate_manager_global + versions.PENDING_OP_OFFSET
        self.assertEqual(b"\x01", fake.memory.get(pending_op_address))

    def test_consume_counters_leaves_no_leftovers_for_a_normal_tick(self) -> None:
        from .. import constants

        interface, _fake = self._prepared_interface()
        deltas = [(item_id, -1) for item_id in constants.PICKUP_COUNTER_ITEMS]
        leftovers = interface.consume_counters(deltas)
        self.assertEqual([], leftovers)


class _FakeDmeModule:
    """Minimal stand-in for the ``dolphin_memory_engine`` module, recording
    the hook/unhook call order."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.hooked = False

    def is_hooked(self) -> bool:
        return self.hooked

    def un_hook(self) -> None:
        self.calls.append("un_hook")
        self.hooked = False

    def hook(self) -> None:
        self.calls.append("hook")
        self.hooked = True


class TestDolphinClientHookSequence(unittest.TestCase):
    """Regression for the stale-hook recovery: a fresh region scan requires
    un_hook() (which destroys the engine's cached instance) before hook(),
    even when the engine reports it isn't hooked."""

    def _client_with_fake_dme(self, hooked: bool) -> tuple[DolphinClient, _FakeDmeModule]:
        client = DolphinClient(_NULL_LOGGER)
        fake_dme = _FakeDmeModule()
        fake_dme.hooked = hooked
        client.dolphin = fake_dme  # type: ignore[assignment]
        return client, fake_dme

    def test_connect_unhooks_then_hooks(self) -> None:
        client, fake_dme = self._client_with_fake_dme(hooked=False)
        client.connect()
        self.assertEqual(["un_hook", "hook"], fake_dme.calls)

    def test_connect_unhooks_even_when_already_hooked(self) -> None:
        client, fake_dme = self._client_with_fake_dme(hooked=True)
        client.connect()
        self.assertEqual(["un_hook", "hook"], fake_dme.calls)

    def test_disconnect_unhooks_unconditionally(self) -> None:
        client, fake_dme = self._client_with_fake_dme(hooked=False)
        client.disconnect()
        self.assertEqual(["un_hook"], fake_dme.calls)


if __name__ == "__main__":
    unittest.main()
