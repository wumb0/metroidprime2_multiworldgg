"""Client entrypoint for Metroid Prime 2: Echoes (PLAN.md section J
deliverable 5), structured after ``worlds/metroidprime/MetroidPrimeClient.py``.
"""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import subprocess
import time
import traceback
import zipfile
from typing import TYPE_CHECKING, Any

import Utils
from CommonClient import get_base_parser, gui_enabled, logger, server_loop
from NetUtils import ClientStatus
from settings import get_settings

from .. import constants
from ..pickup_encoding import decode
from ..utils import get_apworld_version, get_output_path, setup_libs
from .death_link import death_link_check
from .dolphin_client import (
    DolphinException,
    assert_no_running_dolphin,
    get_num_dolphin_instances,
)
from .game_interface import ConnectionState, EchoesInterface
from .notification_manager import NotificationManager
from .receive_items import compute_desired_capacities, plan_grants

apname = Utils.instance_name if Utils.instance_name else "Archipelago"

tracker_loaded = False
try:
    from worlds.tracker.TrackerClient import (
        UT_VERSION,
    )
    from worlds.tracker.TrackerClient import (
        TrackerCommandProcessor as ClientCommandProcessor,
    )
    from worlds.tracker.TrackerClient import (
        TrackerGameContext as CommonContext,
    )

    tracker_loaded = True
except ImportError:
    from CommonClient import ClientCommandProcessor, CommonContext

if TYPE_CHECKING:
    pass

HUD_MESSAGE_DURATION = 4.0  # PLAN.md section J: 4s cooldown between messages.

_STATUS_MESSAGES: dict[ConnectionState, str] = {
    ConnectionState.DISCONNECTED: "Not connected to Dolphin, attempting to reconnect...",
    ConnectionState.WRONG_GAME: "Connected to Dolphin, but it isn't running Metroid Prime 2: Echoes",
    ConnectionState.WRONG_SEED: "Connected to Metroid Prime 2: Echoes, but it's running a different seed/uuid",
    ConnectionState.IN_MENU: "Connected to the game, waiting for a save to load",
    ConnectionState.IN_GAME: "Connected to Metroid Prime 2: Echoes",
}


class MetroidPrime2CommandProcessor(ClientCommandProcessor):
    ctx: MetroidPrime2Context

    def _cmd_export_iso(self, *_args: list[Any]) -> None:
        """Force-regenerate the patched ISO from the .apmp2 file, deleting
        any existing one first."""
        if not self.ctx.apmp2_file:
            logger.error("That client wasn't started from an apmp2 file!")
            return

        output_path = get_output_path(self.ctx.apmp2_file)

        if self.ctx.connection_state != ConnectionState.DISCONNECTED:
            logger.error("Cannot regenerate the ISO while connected to a running game!")
            return

        if os.path.isfile(output_path):
            logger.info("Existing patched ISO detected; deleting so it will be regenerated...")
            os.remove(output_path)

        Utils.async_start(patch_and_run_game(self.ctx.apmp2_file, self.ctx.mp2_iso))

    def _cmd_status(self, *_args: list[Any]) -> None:
        """Display the current Dolphin connection status."""
        logger.info(f"Connection status: {_STATUS_MESSAGES[self.ctx.connection_state]}")

    def _cmd_reconnect(self, *_args: list[Any]) -> None:
        """Force-disconnect from Dolphin and immediately try to reconnect.

        Useful if Dolphin's memory hook goes stale (e.g. emulation was
        stopped/restarted without closing Dolphin itself), which can leave
        the client reading garbage memory and reporting the wrong game."""
        logger.info("Disconnecting from Dolphin...")
        self.ctx.game_interface.disconnect_from_game()
        self.ctx.connection_state = ConnectionState.DISCONNECTED
        logger.info("Reconnecting to Dolphin...")
        self.ctx.game_interface.connect_to_game()
        state = self.ctx.game_interface.get_connection_state()
        update_connection_status(self.ctx, state)
        if state == ConnectionState.DISCONNECTED:
            reason = self.ctx.game_interface.last_connect_error or "unknown reason"
            logger.error(f"Reconnect failed: {reason}")
        else:
            logger.info(f"Reconnect succeeded: {_STATUS_MESSAGES[state]}")

    def _cmd_test_hud(self, *args: list[Any]) -> None:
        """Queue a HUD message to display in-game."""
        self.ctx.notification_manager.queue_notification(" ".join(map(str, args)))

    def _cmd_mp2_debug_inventory(self, *_args: list[Any]) -> None:
        """Print the raw inventory (amount/capacity per item id) read from
        game memory, skipping empty slots. Requires debug: true under
        metroidprime2_options in host.yaml."""
        if not self.ctx.debug_enabled:
            logger.error("This command requires debug: true under metroidprime2_options in host.yaml.")
            return
        inventory = self.ctx.game_interface.read_inventory()
        if inventory is None:
            logger.info("Not connected to a running game.")
            return
        for item_id, (amount, capacity) in sorted(inventory.items()):
            if amount or capacity:
                logger.info(f"  item {item_id:3d}: {amount}/{capacity}")

    def _cmd_deathlink(self) -> None:
        """Toggle DeathLink from the client. Overrides the default setting."""
        self.ctx.death_link_enabled = not self.ctx.death_link_enabled
        Utils.async_start(
            self.ctx.update_death_link(self.ctx.death_link_enabled),
            name="Update Deathlink",
        )
        message = f"DeathLink {'enabled' if self.ctx.death_link_enabled else 'disabled'}"
        logger.info(message)
        self.ctx.notification_manager.queue_notification(message)

    def _cmd_test_deathlink(self, *args: list[Any]) -> None:
        """Test the DeathLink send or receive path. Usage:
        /test_deathlink <incoming|outgoing> [reason]. 'outgoing' sends a
        test DeathLink to the rest of the group without touching in-game
        health, to verify the send path. 'incoming' simulates a DeathLink
        arriving from another player, which does kill you in-game, to
        verify the receive path. Requires DeathLink to be enabled (see
        /deathlink), a connection to the server, and debug: true under
        metroidprime2_options in host.yaml."""
        if not self.ctx.debug_enabled:
            logger.error("This command requires debug: true under metroidprime2_options in host.yaml.")
            return
        if not self.ctx.death_link_enabled:
            logger.error("DeathLink is disabled; enable it with /deathlink first.")
            return
        if not self.ctx.slot:
            logger.error("Not connected to a server.")
            return
        if not args or str(args[0]).lower() not in ("incoming", "outgoing"):
            logger.error("Usage: /test_deathlink <incoming|outgoing> [reason]")
            return

        direction, *reason_words = args
        reason = " ".join(map(str, reason_words)) if reason_words else "triggered a test DeathLink"

        if str(direction).lower() == "outgoing":
            Utils.async_start(
                self.ctx.send_death(f"{self.ctx.player_names[self.ctx.slot]} {reason}"),
                name="Test Deathlink",
            )
            logger.info("Sent test DeathLink.")
        else:
            self.ctx.on_deathlink({
                "time": time.time(),
                "source": self.ctx.player_names[self.ctx.slot],
                "cause": reason,
            })
            logger.info("Simulated an incoming DeathLink.")


class MetroidPrime2Context(CommonContext):
    command_processor = MetroidPrime2CommandProcessor
    game_interface: EchoesInterface
    notification_manager: NotificationManager
    game = constants.GAME_NAME
    items_handling = 0b111
    dolphin_sync_task: asyncio.Task[Any] | None = None
    connection_state: ConnectionState = ConnectionState.DISCONNECTED
    slot_data: dict[str, Any] = {}  # noqa: RUF012 -- matches CommonContext.slot_data's own unannotated convention
    expected_uuid: str | None = None
    last_sent_mlvl: int | None = None
    last_error_message: str | None = None
    apmp2_file: str | None = None
    mp2_iso: str | None = None
    death_link_enabled: bool = False
    is_pending_death_link_reset: bool = False
    debug_enabled: bool = False

    def __init__(
        self,
        server_address: str | None,
        password: str | None,
        apmp2_file: str | None = None,
        mp2_iso: str | None = None,
    ) -> None:
        super().__init__(server_address, password)

        self.game_interface = EchoesInterface(logger)
        self.notification_manager = NotificationManager(HUD_MESSAGE_DURATION, self.game_interface.send_hud_message)
        self.apmp2_file = apmp2_file
        self.mp2_iso = mp2_iso

    async def server_auth(self, password_requested: bool = False) -> None:
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.get_username()
        self.tags: set[str] = set()
        await self.send_connect()

    def on_deathlink(self, data: dict[str, Any]) -> None:
        super().on_deathlink(data)
        self.game_interface.set_current_health(-1.0)
        # Mark this death as already reported so the next _handle_check_deathlink
        # poll tick (which sees health <= 0) does not re-send it as if it were an
        # organic in-game death -- that would re-broadcast the incoming DeathLink
        # right back out to the group. death_link_check() clears this flag itself
        # once health goes positive again on respawn, so a later organic death
        # still sends normally. (worlds/metroidprime/MetroidPrimeClient.py has the
        # same bug in its on_deathlink; do not "restore parity" with it here.)
        self.is_pending_death_link_reset = True

    def on_package(self, cmd: str, args: dict[str, Any]) -> None:
        super().on_package(cmd, args)

        if cmd == "Connected":
            self.slot_data = args["slot_data"]
            self.expected_uuid = self.slot_data.get("world_uuid")
            self.game_interface.expected_uuid = self.expected_uuid

            if "death_link" in self.slot_data:
                self.death_link_enabled = bool(self.slot_data["death_link"])
                Utils.async_start(self.update_death_link(self.death_link_enabled))

    def make_gui(self):
        from kvui import GameManager

        base_class: type = GameManager
        ut_title = ""

        if tracker_loaded and UT_VERSION >= "v0.2.12":
            base_class = super().make_gui()
            ut_title = f" | Universal Tracker {UT_VERSION}"

        class MetroidPrime2Manager(base_class):
            logging_pairs = [("Client", "Archipelago")]  # noqa: RUF012 -- matches kvui GameManager's own convention
            base_title = f"Metroid Prime 2: Echoes Client {get_apworld_version()}{ut_title} | {apname}"

        return MetroidPrime2Manager


def update_connection_status(ctx: MetroidPrime2Context, status: ConnectionState) -> None:
    if ctx.connection_state == status:
        return
    logger.info(_STATUS_MESSAGES[status])
    if get_num_dolphin_instances() > 1:
        # Windows only (get_num_dolphin_instances() returns 0 elsewhere).
        # dolphin-memory-engine's findPID() hooks the first Dolphin.exe it
        # sees, so with several running the client can attach to the wrong
        # one and read garbage/another game -- notify so the user can close
        # the extras. Mirrors worlds/metroidprime's MULTIPLE_DOLPHIN_INSTANCES.
        logger.warning(
            "Multiple Dolphin instances detected; the client may be attached to the wrong "
            "one. Close all but the Dolphin running Metroid Prime 2: Echoes."
        )
    ctx.connection_state = status


async def dolphin_sync_task(ctx: MetroidPrime2Context) -> None:
    try:
        logger.info(f"Using metroidprime2.apworld version: {get_apworld_version()}")
    except Exception:
        pass

    if ctx.apmp2_file:
        Utils.async_start(patch_and_run_game(ctx.apmp2_file, ctx.mp2_iso))

    logger.info("Starting Dolphin Connector, attempting to connect to emulator...")

    while not ctx.exit_event.is_set():
        try:
            state = ctx.game_interface.get_connection_state()
            update_connection_status(ctx, state)

            if state == ConnectionState.IN_GAME:
                await _handle_game_ready(ctx)
            else:
                if state == ConnectionState.IN_MENU:
                    # worlds/metroidprime does the same: the game can read as
                    # "in menu" during the ending, so keep checking the goal
                    # there too rather than only in the IN_GAME branch.
                    await _handle_check_goal(ctx)
                await _handle_game_not_ready(ctx)
        except Exception as e:
            if isinstance(e, DolphinException):
                logger.error(str(e))
            else:
                logger.error(traceback.format_exc())
            await asyncio.sleep(3)
            continue


async def _handle_game_not_ready(ctx: MetroidPrime2Context) -> None:
    if ctx.connection_state == ConnectionState.DISCONNECTED:
        ctx.game_interface.connect_to_game()
    elif ctx.connection_state == ConnectionState.WRONG_GAME:
        # The game id matched a known version but the build string didn't
        # (get_connection_state's check), which can mean the hook is reading
        # a stale/partially-loaded region rather than a genuinely different
        # disc (dolphin-memory-engine caches the emulated MEM1 region at
        # hook() time). Drop the hook and re-hook so this can recover instead
        # of sitting in WRONG_GAME forever -- the sync loop only ever re-runs
        # connect_to_game() from DISCONNECTED, so without this a stale read
        # here never recovers.
        ctx.game_interface.disconnect_from_game()
        ctx.game_interface.connect_to_game()
    await asyncio.sleep(1)


_DEFAULT_TICK_DELAY = 0.5


async def _handle_game_ready(ctx: MetroidPrime2Context) -> None:
    """Every early return below falls through to the ``finally``'s sleep
    (defaulting to ``_DEFAULT_TICK_DELAY``, overridable per branch via
    ``delay``), so a future branch added here can't accidentally skip
    throttling the way an ad-hoc ``sleep()``-then-``return`` per branch
    could."""
    delay = _DEFAULT_TICK_DELAY
    try:
        if not ctx.server or not ctx.slot:
            message = "Waiting for player to connect to server"
            if ctx.last_error_message != message:
                logger.info(message)
                ctx.last_error_message = message
            delay = 1
            return
        ctx.last_error_message = None

        # 0. Goal check is a pure memory read, so it runs before (and
        # independently of) the pending-op guard and the inventory protocol.
        await _handle_check_goal(ctx)

        # 1. Pending-op guard: never write over a body the game hasn't consumed yet.
        if ctx.game_interface.has_pending_op():
            delay = 0.1
            return

        # 2. Inventory read.
        inventory = ctx.game_interface.read_inventory()
        if inventory is None:
            return

        # 3./4. Pickup-counter protocol: any of the four pickup bitmask
        # counters being nonzero takes priority over granting received
        # items, exactly one body per tick.
        pickup_counters_pending = any(
            inventory[item_id][0] > 0 for item_id in constants.PICKUP_COUNTER_ITEMS
        )
        if pickup_counters_pending:
            await _handle_pickup_counters(ctx, inventory)
        else:
            await _handle_grant_items(ctx, inventory)

        # 5. Idle-time notification flush + tracker datastorage.
        if not ctx.game_interface.has_pending_op():
            ctx.notification_manager.handle_notifications()

        await _send_mlvl_datastorage(ctx)

        if ctx.death_link_enabled:
            await _handle_check_deathlink(ctx)
    finally:
        await asyncio.sleep(delay)


async def _handle_check_deathlink(ctx: MetroidPrime2Context) -> None:
    health = ctx.game_interface.get_current_health()
    should_send, ctx.is_pending_death_link_reset = death_link_check(health, ctx.is_pending_death_link_reset)
    if should_send and ctx.slot:
        await ctx.send_death(f"{ctx.player_names[ctx.slot]} ran out of energy.")


async def _handle_check_goal(ctx: MetroidPrime2Context) -> None:
    """Declares the goal once the player's current area is one of the ending
    areas (``constants.GAME_END_AREA_INDICES``). Mirrors
    ``worlds/metroidprime``'s "current level == End_of_Game" check: a raw
    memory read of the current MLVL plus ``CStateManager::m_nextAreaId``,
    with nothing the ISO has to be patched to produce (the old in-ISO
    magic-item sentinel never fired in practice). Either read returns None
    while disconnected or at the menu, which simply won't match."""
    if ctx.finished_game or not ctx.slot:
        return
    if ctx.game_interface.current_mlvl() != constants.TEMPLE_GROUNDS_MLVL:
        return
    if ctx.game_interface.current_area_id() not in constants.GAME_END_AREA_INDICES:
        return
    logger.info("Reached the ending areas; reporting goal.")
    await ctx.send_msgs([{"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}])
    ctx.finished_game = True


async def _handle_pickup_counters(ctx: MetroidPrime2Context, inventory: dict[int, tuple[int, int]]) -> None:
    """Reads every persistent counter this world's pickups can set, and
    reports what happened since the last successful consume (PLAN.md
    section P, replacing section O's single-shared-counter
    ``_handle_magic_item_amount``/``location_reconciliation`` approach
    entirely -- see PLAN.md section P for the measured collision rates that
    made that approach unworkable).

    Nothing here has anything to do with the goal: that is a plain memory
    read of the current area (``_handle_check_goal``), so no counter amount
    can ever declare victory.

    ``pickup_encoding.decode`` turns every nonzero pickup counter into the
    0-based indices whose bit was set -- distinct powers of two sum
    losslessly, so any number of pickups collected across any length of
    disconnect decode back to exactly the indices that produced them, with
    no search and no guessing (unlike section O's
    ``location_reconciliation``, removed by this section). Every decoded
    index is reported in one ``LocationChecks`` message before any counter
    is consumed, keeping this function's previous send-before-consume
    ordering.

    A decoded index that isn't in ``ctx.missing_locations`` is warned
    about rather than silently accepted: it is the tell for this design's
    one residual failure mode (collecting the same pickup twice across a
    save reload while detached carries into a neighbouring bit -- PLAN.md
    section P, "Residual failure modes"). ``stray`` bits (decoded past the
    last real pickup index, or above a counter's declared bit range) are
    warned about the same way without dropping the indices that DID decode
    cleanly -- every counter with a nonzero amount is still consumed by
    its exact read value regardless, so a stray bit is cleared rather than
    left to corrupt a future decode.
    """
    decoded = decode(inventory)

    if decoded.stray:
        logger.warning(
            f"Pickup counter(s) decoded {len(decoded.stray)} stray bit(s) that don't correspond to "
            f"any real pickup index: {decoded.stray}; consuming them along with the rest."
        )

    for index in decoded.indices:
        location_id = constants.LOCATION_ID_BASE + index
        if location_id not in ctx.missing_locations:
            logger.warning(
                f"Decoded pickup index {index} was already checked server-side; reporting it again "
                "anyway (likely the same pickup collected twice across a save reload while "
                "disconnected -- see PLAN.md section P's residual failure modes)."
            )

    if decoded.indices:
        await ctx.send_msgs(
            [{"cmd": "LocationChecks", "locations": [constants.LOCATION_ID_BASE + idx for idx in decoded.indices]}]
        )

    if decoded.deltas:
        ctx.game_interface.consume_counters(decoded.deltas)


async def _handle_grant_items(ctx: MetroidPrime2Context, inventory: dict[int, tuple]) -> None:
    if not ctx.items_received:
        return

    received = [
        (ctx.item_names.lookup_in_game(network_item.item, ctx.game), network_item.player)
        for network_item in ctx.items_received
    ]
    first_non_starting = ctx.slot_data.get("first_non_starting_item_index", 0)
    # .get default keeps older .apmp2/slot_data (generated before this option
    # existed) working, matching the flag-off behavior.
    unlock_launcher = bool(ctx.slot_data.get("missile_expansions_unlock_launcher", False))
    unlock_power_bombs = bool(
        ctx.slot_data.get("power_bomb_expansions_unlock_power_bombs", False)
    )
    desired = compute_desired_capacities(
        received, first_non_starting, unlock_launcher, unlock_power_bombs
    )
    deltas = plan_grants(desired, inventory)
    if not deltas:
        return

    last_item_name, last_sender = received[-1]
    if last_sender != ctx.slot:
        sender_name = ctx.player_names.get(last_sender, "another world")
        message = f"Received {last_item_name} from {sender_name}"
    else:
        # The game already shows its own pickup HUD message when you find
        # one of your own items in-game; queuing another one here would
        # double it up.
        message = None

    leftovers = ctx.game_interface.grant(deltas, message)
    if leftovers:
        logger.debug(
            f"{len(leftovers)} item grant(s) deferred to a later tick (remote-execution body budget)."
        )


async def _send_mlvl_datastorage(ctx: MetroidPrime2Context) -> None:
    mlvl = ctx.game_interface.current_mlvl()
    if mlvl is None or mlvl == ctx.last_sent_mlvl or not ctx.slot:
        return
    ctx.last_sent_mlvl = mlvl
    await ctx.send_msgs(
        [
            {
                "cmd": "Set",
                "key": f"metroidprime2_mlvl_{ctx.team}_{ctx.slot}",
                "default": 0,
                "want_reply": False,
                "operations": [{"operation": "replace", "value": mlvl}],
            }
        ]
    )


def get_options_from_apmp2(apmp2_file: str) -> dict[str, Any]:
    with zipfile.ZipFile(apmp2_file) as zf:
        with zf.open("options.json") as f:
            return json.loads(f.read().decode("utf-8"))


async def run_game(romfile: str, mp2_settings: Any) -> None:
    auto_start = mp2_settings["emulator_settings"]["auto_start"]
    emulator_path = mp2_settings["emulator_settings"]["executable_path"]
    emulator_arguments = mp2_settings["emulator_settings"]["arguments"]

    if not auto_start:
        return

    if not assert_no_running_dolphin():
        # Windows only: a Dolphin is already running, so launching another
        # one would leave the client's hook free to attach to either instance
        # (findPID() takes the first Dolphin.exe it sees). Use the one
        # that's already up instead -- the sync loop will hook it.
        logger.info("Dolphin is already running; not launching a second instance.")
        return

    subprocess.Popen(
        [str(emulator_path), romfile, *emulator_arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def patch_and_run_game(apmp2_file: str, mp2_iso: str | None = None) -> None:
    from ..settings import cosmetics_dict
    from .patcher_runner import patch_iso_with_ap

    mp2_settings = get_settings()["metroidprime2_options"]
    apmp2_file = os.path.abspath(apmp2_file)
    input_iso_path = mp2_settings["rom_file"] if not mp2_iso else mp2_iso
    output_path = get_output_path(apmp2_file)

    if not os.path.exists(output_path):
        if not zipfile.is_zipfile(apmp2_file):
            raise Exception(f"Invalid apmp2 file: {apmp2_file}")

        def _progress(text: str, percent: float) -> None:
            logger.info(f"[{percent * 100:5.1f}%] {text}")

        try:
            logger.info("--------------")
            logger.info(f"Input ISO Path: {input_iso_path}")
            logger.info(f"Output ISO Path: {output_path}")
            logger.info("Patching ISO...")
            cosmetics = cosmetics_dict(mp2_settings)
            output_path = await asyncio.to_thread(
                patch_iso_with_ap, apmp2_file, input_iso_path, cosmetics, _progress
            )
            logger.info("Patching Complete")
        except BaseException as e:
            logger.error(f"Failed to patch ISO: {e}")
            raise RuntimeError(f"Failed to patch ISO: {e}") from e
        logger.info("--------------")

    Utils.async_start(run_game(output_path, mp2_settings))


def main(*args: str) -> None:
    Utils.init_logging("MetroidPrime2Client")

    async def _main(
        connect: str | None, password: str | None, apmp2_file: str | None, iso: str | None
    ) -> None:
        setup_libs()

        multiprocessing.freeze_support()
        logger.info("main")

        ctx = MetroidPrime2Context(connect, password, apmp2_file, iso)
        ctx.debug_enabled = bool(get_settings()["metroidprime2_options"]["debug"])

        if apmp2_file:
            options = get_options_from_apmp2(apmp2_file)
            slot = options.get("player_name")
            if slot:
                ctx.auth = slot

        logger.info("Connecting to server...")
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="Server Loop")

        if tracker_loaded:
            ctx.run_generator()
            ctx.tags.remove("Tracker")

        if gui_enabled:
            ctx.run_gui()
        ctx.run_cli()

        logger.info("Running game...")
        ctx.dolphin_sync_task = asyncio.create_task(dolphin_sync_task(ctx), name="Dolphin Sync")

        await ctx.exit_event.wait()
        # Reusing https://github.com/ArchipelagoMW/Archipelago/blob/0.6.7/worlds/tww/TWWClient.py#L718-L719
        # Wake the sync task, if it is currently sleeping, so it can start shutting down when it sees that the
        # exit_event is set.
        ctx.watcher_event.set()
        ctx.server_address = None

        await ctx.shutdown()

        if ctx.dolphin_sync_task:
            await asyncio.sleep(3)
            await ctx.dolphin_sync_task

    parser = get_base_parser()
    parser.add_argument("apmp2_file", default="", type=str, nargs="?", help="Path to an apmp2 file")
    parser.add_argument("iso", default="", type=str, nargs="?", help="Path to a Metroid Prime 2: Echoes iso")
    parser_args = parser.parse_args(args)

    import colorama

    colorama.init()
    asyncio.run(_main(parser_args.connect, parser_args.password, parser_args.apmp2_file, parser_args.iso))
    colorama.deinit()
