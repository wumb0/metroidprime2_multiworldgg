"""Client entrypoint for Metroid Prime 2: Echoes (PLAN.md section J
deliverable 5), structured after ``worlds/metroidprime/MetroidPrimeClient.py``.
"""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import subprocess
import traceback
import zipfile
from typing import TYPE_CHECKING, Any

import Utils
from CommonClient import get_base_parser, gui_enabled, logger, server_loop
from NetUtils import ClientStatus
from settings import get_settings

from .. import constants
from ..items import ITEM_TABLE
from ..locations import LOCATION_TABLE
from ..utils import get_apworld_version, get_output_path, setup_libs
from .death_link import death_link_check
from .dolphin_client import DolphinException
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

# PLAN.md section J: "amount - 1 >= 119" is the goal sentinel (the
# in-ISO trigger sets the magic item's amount to 120 -- see
# client/patcher_runner.py's _GOAL_SENTINEL_AMOUNT).
_GOAL_INDEX_THRESHOLD = len(LOCATION_TABLE)

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

    def _cmd_grant_item(self, *args: list[Any]) -> None:
        """Grant an item directly, bypassing the normal AP item-receipt
        flow (useful for testing). Usage: /grant_item <item name>, e.g.
        /grant_item Missile Expansion. Item names are matched
        case-insensitively against items.ITEM_TABLE; progressive items
        (e.g. Progressive Suit) grant their first stage."""
        if not args:
            logger.error("Usage: /grant_item <item name>")
            return

        requested = " ".join(map(str, args))
        match = next((name for name in ITEM_TABLE if name.lower() == requested.lower()), None)
        if match is None:
            logger.error(f"Unknown item {requested!r}.")
            return

        if self.ctx.connection_state != ConnectionState.IN_GAME:
            logger.error("Not connected to a running game.")
            return

        if self.ctx.game_interface.has_pending_op():
            logger.error("A remote-execution op is already pending; try again in a moment.")
            return

        data = ITEM_TABLE[match]
        gains = data.progression[0] if data.progression is not None else data.gains
        leftovers = self.ctx.game_interface.grant(list(gains), f"{match} granted")
        if leftovers:
            logger.warning(f"Grant for {match} deferred (remote-execution body budget); try again.")
        else:
            logger.info(f"Granted {match}.")

    def _cmd_mp2_debug_inventory(self, *_args: list[Any]) -> None:
        """Print the raw inventory (amount/capacity per item id) read from
        game memory, skipping empty slots."""
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
        """Send a test DeathLink to the rest of the group, without touching
        in-game health, to verify the send/receive path end-to-end. Usage:
        /test_deathlink [reason]. Requires DeathLink to be enabled (see
        /deathlink) and a connection to the server."""
        if not self.ctx.death_link_enabled:
            logger.error("DeathLink is disabled; enable it with /deathlink first.")
            return
        if not self.ctx.slot:
            logger.error("Not connected to a server.")
            return

        reason = " ".join(map(str, args)) if args else "triggered a test DeathLink"
        Utils.async_start(
            self.ctx.send_death(f"{self.ctx.player_names[self.ctx.slot]} {reason}"),
            name="Test Deathlink",
        )
        logger.info("Sent test DeathLink.")


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
    magic_capacity_ensured: bool = False
    last_sent_mlvl: int | None = None
    last_error_message: str | None = None
    apmp2_file: str | None = None
    mp2_iso: str | None = None
    death_link_enabled: bool = False
    is_pending_death_link_reset: bool = False

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
            self.magic_capacity_ensured = False

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
    ctx.connection_state = status
    if status != ConnectionState.IN_GAME:
        ctx.magic_capacity_ensured = False


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
    await asyncio.sleep(1)


async def _handle_game_ready(ctx: MetroidPrime2Context) -> None:
    if not ctx.server or not ctx.slot:
        message = "Waiting for player to connect to server"
        if ctx.last_error_message != message:
            logger.info(message)
            ctx.last_error_message = message
        await asyncio.sleep(1)
        return
    ctx.last_error_message = None

    # 1. Pending-op guard: never write over a body the game hasn't consumed yet.
    if ctx.game_interface.has_pending_op():
        await asyncio.sleep(0.1)
        return

    # 2. Inventory read + one-time magic item capacity top-up per connection.
    inventory = ctx.game_interface.read_inventory()
    if inventory is None:
        await asyncio.sleep(0.5)
        return

    magic_amount, magic_capacity = inventory[constants.MAGIC_ITEM]

    if not ctx.magic_capacity_ensured:
        ctx.game_interface.ensure_magic_capacity(magic_capacity)
        ctx.magic_capacity_ensured = True
        await asyncio.sleep(0.5)
        return

    # 3./4. Magic item protocol: a collected pickup (amount > 0) takes
    # priority over granting received items, exactly one body per tick.
    if magic_amount > 0:
        await _handle_magic_item_amount(ctx, magic_amount)
    else:
        await _handle_grant_items(ctx, inventory)

    # 5. Idle-time notification flush + tracker datastorage.
    if not ctx.game_interface.has_pending_op():
        ctx.notification_manager.handle_notifications()

    await _send_mlvl_datastorage(ctx)

    if ctx.death_link_enabled:
        await _handle_check_deathlink(ctx)

    await asyncio.sleep(0.5)


async def _handle_check_deathlink(ctx: MetroidPrime2Context) -> None:
    health = ctx.game_interface.get_current_health()
    should_send, ctx.is_pending_death_link_reset = death_link_check(health, ctx.is_pending_death_link_reset)
    if should_send and ctx.slot:
        await ctx.send_death(f"{ctx.player_names[ctx.slot]} ran out of energy.")


async def _handle_magic_item_amount(ctx: MetroidPrime2Context, amount: int) -> None:
    index = amount - 1
    if 0 <= index < _GOAL_INDEX_THRESHOLD:
        await ctx.send_msgs([{"cmd": "LocationChecks", "locations": [constants.LOCATION_ID_BASE + index]}])
    elif index >= _GOAL_INDEX_THRESHOLD:
        if not ctx.finished_game:
            await ctx.send_msgs([{"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}])
            ctx.finished_game = True
    else:
        logger.warning(
            f"Magic item amount {amount} doesn't correspond to a pickup index or the goal "
            "sentinel; consuming it without acting on it."
        )
    ctx.game_interface.consume_magic_item(amount)


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
    desired = compute_desired_capacities(received, first_non_starting, unlock_launcher)
    deltas = plan_grants(desired, inventory)
    if not deltas:
        return

    last_item_name, last_sender = received[-1]
    if last_sender != ctx.slot:
        sender_name = ctx.player_names.get(last_sender, "another world")
        message = f"Received {last_item_name} from {sender_name}"
    else:
        message = f"{last_item_name} acquired"

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

    if auto_start:
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
