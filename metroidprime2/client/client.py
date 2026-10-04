"""Client entrypoint for Metroid Prime 2: Echoes (PLAN.md section J
deliverable 5), structured after ``worlds/metroidprime/MetroidPrimeClient.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
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
from ..hint_scans import decode_hint_scans, newly_completed_hints
from ..pickup_encoding import decode
from ..utils import get_apworld_version, get_output_path, setup_libs
from .death_link import death_link_check
from .dolphin_client import (
    DolphinException,
    assert_no_running_dolphin,
    get_num_dolphin_instances,
)
from .game_interface import ConnectionState, EchoesInterface
from .item_panel import ItemPanel, compute_panel_state, required_width_dp
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

# ISO patching status goes to this logger rather than the "Client" one: the
# client UI only displays "Client" (and its children), whereas this one
# propagates to the root logger's console/file handlers.
patch_logger = logging.getLogger("MetroidPrime2Patcher")

GOAL_COMPLETE_MESSAGE = "Goal complete!"

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

        Utils.async_start(patch_and_run_game(self.ctx.apmp2_file, self.ctx.mp2_iso, self.ctx.verbose))

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
    last_sent_area: tuple[int, int] | None = None
    # items_received index up to which receipts have been announced on the
    # HUD (None = not yet synced this connection); see _handle_grant_items.
    last_announced_index: int | None = None
    last_error_message: str | None = None
    apmp2_file: str | None = None
    mp2_iso: str | None = None
    death_link_enabled: bool = False
    is_pending_death_link_reset: bool = False
    # See _handle_check_goal: set once a read shows the goal marker absent.
    goal_marker_armed: bool = False
    debug_enabled: bool = False
    # Set by the client's -v/--verbose flag: log ISO patching progress to the console.
    verbose: bool = False
    hint_scans: dict[int, tuple[int, int, int]] = {}  # noqa: RUF012 -- reassigned wholesale in on_package, never mutated in place
    sent_hint_scans: set[int] = set()  # noqa: RUF012 -- same as hint_scans above

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
        # set_current_health alone doesn't kill the player -- it bypasses the
        # game's damage/death pipeline entirely, leaving the camera and gun
        # model stuck in whatever state they were in. set_alive(False) is
        # what actually triggers the game's own death handling (mirrors
        # worlds/metroidprime's set_alive(False)); the health write above is
        # kept so the health <= 0 debounce below still arms.
        self.game_interface.set_alive(False)
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
            self.goal_marker_armed = False
            self.expected_uuid = self.slot_data.get("world_uuid")
            self.game_interface.expected_uuid = self.expected_uuid
            self.hint_scans = decode_hint_scans(self.slot_data.get("hint_scans"))
            self.sent_hint_scans = set()
            self.last_announced_index = None
            self.last_sent_mlvl = None
            self.last_sent_area = None

            if "death_link" in self.slot_data:
                self.death_link_enabled = bool(self.slot_data["death_link"])
                Utils.async_start(self.update_death_link(self.death_link_enabled))

            self._refresh_item_panel()
        elif cmd == "ReceivedItems":
            self._refresh_item_panel()

    def _refresh_item_panel(self) -> None:
        panel = getattr(self.ui, "item_panel", None) if self.ui else None
        if panel is None:
            return
        names = [self.item_names.lookup_in_game(network_item.item, self.game) for network_item in self.items_received]
        panel.update(compute_panel_state(names, self.slot_data))

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

            def build(self):
                container = super().build()
                # Kivy's default window (800dp wide) is narrower than the panel.
                from kivy.core.window import Window
                from kivy.metrics import dp

                Window.size = (max(Window.width, dp(required_width_dp())), Window.height)
                self.item_panel = ItemPanel()
                self.grid.add_widget(self.item_panel.layout)
                return container

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
        Utils.async_start(patch_and_run_game(ctx.apmp2_file, ctx.mp2_iso, ctx.verbose))

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
            await _sleep_unless_exiting(ctx, 3)
            continue


async def _sleep_unless_exiting(ctx: MetroidPrime2Context, seconds: float) -> None:
    """``asyncio.sleep`` that returns early once the client is closing, so
    the sync loop notices ``exit_event`` right away instead of after its
    current tick delay."""
    try:
        await asyncio.wait_for(ctx.exit_event.wait(), seconds)
    except TimeoutError:
        pass


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
    await _sleep_unless_exiting(ctx, 1)


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
        # The inventory is read first because the boss-skip goals' marker
        # lives in it (``constants.GOAL_MARKER_ITEM``).
        inventory = ctx.game_interface.read_inventory()
        await _handle_check_goal(ctx, inventory)

        # 1. Pending-op guard: never write over a body the game hasn't consumed yet.
        if ctx.game_interface.has_pending_op():
            delay = 0.1
            return

        # 2. Inventory read (done above).
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
        await _handle_hint_scans(ctx)

        if ctx.death_link_enabled:
            await _handle_check_deathlink(ctx)
    finally:
        await _sleep_unless_exiting(ctx, delay)


async def _handle_check_deathlink(ctx: MetroidPrime2Context) -> None:
    health = ctx.game_interface.get_current_health()
    should_send, ctx.is_pending_death_link_reset = death_link_check(health, ctx.is_pending_death_link_reset)
    if should_send and ctx.slot:
        await ctx.send_death(f"{ctx.player_names[ctx.slot]} ran out of energy.")


async def _handle_check_goal(
    ctx: MetroidPrime2Context, inventory: dict[int, tuple[int, int]] | None = None
) -> None:
    """Declares the goal once the player's current area satisfies
    ``slot_data["goal"]`` (``options.py``'s ``Goal`` choice, defaulting to
    ``constants.GOAL_BOTH_BOSSES`` for slot_data predating this option).
    Mirrors ``worlds/metroidprime``'s "current level == End_of_Game" check:
    a raw memory read of the current MLVL plus ``CStateManager::m_nextAreaId``
    (the old in-ISO magic-item sentinel never fired in practice). Either
    read returns None while disconnected or at the menu, which simply won't
    match.

    ``GOAL_EMPEROR_ING`` and ``GOAL_KEYS`` additionally rely on the ISO
    patch in ``client/goal_warp_patch.py``, which warps the player to the
    Credits as soon as the condition is met (after Emperor Ing is dead, on
    returning to Sky Temple Gateway; or on reaching Sky Temple Energy
    Controller), so they report through the Credits check below like the
    vanilla goal does.

    * ``GOAL_BOTH_BOSSES`` (vanilla): current area is one of the five
      post-Dark-Samus ``!!game_end_part*`` areas
      (``constants.GAME_END_AREA_INDICES``).
    * ``GOAL_EMPEROR_ING``: nothing beyond the Credits check. There is
      deliberately no client-side proxy for his death: leaving his arena is
      not proof of it (respawning after dying there also changes the area),
      and the warp patch keys off the game's own state instead.
    * ``GOAL_KEYS``: also accepts reaching Sky Temple Energy Controller
      (``constants.SKY_TEMPLE_ENERGY_CONTROLLER_AREA_INDEX``), reachable
      only once the Sky Temple Gateway's key gate
      (``sky_temple_keys_required``) has opened. The warp patch leaves it
      for the Credits about a second later; this check just reports first.

    Both boss-skipping goals also report on the *goal marker*: the warp
    patch writes ``constants.GOAL_MARKER_AMOUNT`` onto
    ``constants.GOAL_MARKER_ITEM`` as it starts the warp, and ``inventory``
    (the caller's read of it, None when unreadable) is checked for that.
    This is the route that does not depend on the area-id read matching,
    which in play it did not after the warp. Only an absent -> present
    change counts (see ``goal_marker_armed`` below), so a stale marker in
    memory at connect time reports nothing.

    A harder condition always satisfies an easier one too, so continuing
    to play past your goal still ends the slot correctly."""
    if ctx.finished_game or not ctx.slot:
        return

    mlvl = ctx.game_interface.current_mlvl()
    area = ctx.game_interface.current_area_id()

    goal = ctx.slot_data.get("goal", constants.GOAL_BOTH_BOSSES)

    reached_credits = mlvl == constants.TEMPLE_GROUNDS_MLVL and area in constants.GAME_END_AREA_INDICES
    reached_keys = (
        goal == constants.GOAL_KEYS
        and mlvl == constants.GREAT_TEMPLE_SKY_TEMPLE_MLVL
        and area == constants.SKY_TEMPLE_ENERGY_CONTROLLER_AREA_INDEX
    )
    # The marker only counts as an absent -> present transition seen by this
    # client: one already present on the first read (stale memory from a
    # finished run still sitting under the title screen, a leftover save)
    # must not report anything. ``goal_marker_armed`` is set the first time
    # a read shows it absent.
    marker_set = False
    if goal != constants.GOAL_BOTH_BOSSES and inventory is not None:
        marker_present = inventory.get(constants.GOAL_MARKER_ITEM, (0, 0))[0] >= constants.GOAL_MARKER_AMOUNT
        if not marker_present:
            ctx.goal_marker_armed = True
        else:
            marker_set = getattr(ctx, "goal_marker_armed", False)
    if not (reached_credits or reached_keys or marker_set):
        return

    logger.info("Goal complete! Reporting it to the server.")
    await ctx.send_msgs([{"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}])
    ctx.finished_game = True
    ctx.notification_manager.queue_notification(GOAL_COMPLETE_MESSAGE)


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
    max_energy_tanks = int(
        ctx.slot_data.get("max_energy_tanks", constants.DEFAULT_MAX_ENERGY_TANKS)
    )
    desired = compute_desired_capacities(
        received, first_non_starting, unlock_launcher, unlock_power_bombs, max_energy_tanks
    )
    deltas = plan_grants(desired, inventory)
    if ctx.last_announced_index is None and not deltas:
        # First sync this connection and the save already reflects
        # everything received -- nothing to announce up to here.
        ctx.last_announced_index = len(received)
    _announce_received_items(ctx, received, first_non_starting)
    if not deltas:
        return

    leftovers = ctx.game_interface.grant(deltas)
    if leftovers:
        logger.debug(
            f"{len(leftovers)} item grant(s) deferred to a later tick (remote-execution body budget)."
        )


def _announce_received_items(
    ctx: MetroidPrime2Context, received: list[tuple[str, int]], first_non_starting: int
) -> None:
    """Queues HUD notifications for the items received since the last
    announcement, grouped per sender and item, so 3 Missile Expansions from
    one player show as a single "Received 15 Missiles from X" rather than
    three messages (NotificationManager packs each sender's items into as
    few HUD messages as fit, merging into ones still queued).

    Start-inventory catch-up (indices below ``first_non_starting``) is never
    announced -- grant()'s per-tick body budget can take several ticks to
    apply a large start_inventory block. Neither are this slot's own
    items: the game already shows its own pickup HUD message for those.
    """
    start = max(ctx.last_announced_index or 0, first_non_starting)
    ctx.last_announced_index = len(received)

    groups: dict[tuple[int, str], int] = {}
    for item_name, sender in received[start:]:
        if sender == ctx.slot:
            continue
        groups[sender, item_name] = groups.get((sender, item_name), 0) + 1

    for (sender, item_name), count in groups.items():
        sender_name = ctx.player_names.get(sender, "another world")
        ctx.notification_manager.queue_received_items(item_name, sender_name, count)


async def _send_mlvl_datastorage(ctx: MetroidPrime2Context) -> None:
    mlvl = ctx.game_interface.current_mlvl()
    if mlvl is None or not ctx.slot:
        return
    messages: list[dict[str, Any]] = []
    if mlvl != ctx.last_sent_mlvl:
        ctx.last_sent_mlvl = mlvl
        messages.append(_datastorage_replace(f"metroidprime2_mlvl_{ctx.team}_{ctx.slot}", mlvl, 0))
    # The MLVL alone can't tell a light region from its dark counterpart
    # (they share one), so UT's map tab follows this finer-grained key.
    area = ctx.game_interface.current_area_id()
    if area is not None and (mlvl, area) != ctx.last_sent_area:
        ctx.last_sent_area = (mlvl, area)
        key = constants.AREA_DATASTORAGE_KEY.format(team=ctx.team, slot=ctx.slot)
        messages.append(_datastorage_replace(key, f"{mlvl:X}:{area}", ""))
    if messages:
        await ctx.send_msgs(messages)


def _datastorage_replace(key: str, value: Any, default: Any) -> dict[str, Any]:
    return {
        "cmd": "Set",
        "key": key,
        "default": default,
        "want_reply": False,
        "operations": [{"operation": "replace", "value": value}],
    }


async def _handle_hint_scans(ctx: MetroidPrime2Context) -> None:
    """Sky Temple Key and translator lore hint scans (PLAN.md sections Q,
    R): a pillar/hologram's SCAN is tracked by the game's own save data
    regardless of anything this world patches, so detecting a completed
    scan is a plain memory read -- unlike granting items or consuming
    pickup counters, it never needs to arm or wait on the remote-execution
    pending-op flag, so it doesn't need any of that protocol's bookkeeping
    here.

    Skips the Dolphin read entirely once every hint scan this slot knows
    about (``ctx.hint_scans``, from slot_data -- empty unless
    ``sky_temple_key_hints="scanned"``/``translator_lore_hints`` is not
    ``"off"``) has already been reported, so an idle tick after
    everything's sent costs nothing.
    """
    if set(ctx.hint_scans) <= ctx.sent_hint_scans:
        return

    scan_progress = ctx.game_interface.read_scan_progress()
    if scan_progress is None:
        return

    newly_completed, locations_by_group = newly_completed_hints(scan_progress, ctx.hint_scans, ctx.sent_hint_scans)
    if not newly_completed:
        return

    # One CreateHints call per (player, status) group, not just per player:
    # section R's translator lore hints can name another player's item,
    # which the server only allows under HINT_UNSPECIFIED, so a tick that
    # completes both a Sky Temple Key pillar (HINT_PRIORITY) and a lore
    # hologram naming someone else's item (HINT_UNSPECIFIED) for the same
    # player needs two separate messages.
    await ctx.send_msgs([
        {"cmd": "CreateHints", "locations": locations, "player": player, "status": status}
        for (player, status), locations in locations_by_group.items()
    ])
    ctx.sent_hint_scans |= newly_completed
    for scan_id in sorted(newly_completed):
        logger.info(f"Hint scan complete (scan {scan_id:#x}); sent the hint to the server.")


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


async def patch_and_run_game(apmp2_file: str, mp2_iso: str | None = None, verbose: bool = False) -> None:
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
            patch_logger.info(f"[{percent * 100:5.1f}%] {text}")

        if verbose:
            patch_logger.setLevel(logging.INFO)
        else:
            patch_logger.setLevel(logging.WARNING)

        try:
            patch_logger.info("--------------")
            patch_logger.info(f"Input ISO Path: {input_iso_path}")
            patch_logger.info(f"Output ISO Path: {output_path}")
            logger.info("Patching ISO... Please wait")
            cosmetics = cosmetics_dict(mp2_settings)
            try:
                output_path = await asyncio.to_thread(
                    patch_iso_with_ap, apmp2_file, input_iso_path, cosmetics, _progress
                )
            except asyncio.CancelledError:
                # The patch thread itself can't be interrupted, and asyncio.run
                # waits for it before the process exits -- which is what we
                # want (killing it mid-write would leave a partial output ISO
                # that the os.path.exists check above would then trust).
                logger.info("Client closing; waiting for ISO patching to finish first...")
                raise
            patch_logger.info("Patching Complete")
        except BaseException as e:
            logger.error(f"Failed to patch ISO: {e}")
            raise RuntimeError(f"Failed to patch ISO: {e}") from e
        patch_logger.info("--------------")

    Utils.async_start(run_game(output_path, mp2_settings))


_SHUTDOWN_TIMEOUT = 5.0


async def _shutdown(ctx: MetroidPrime2Context) -> None:
    """Bounded version of worlds/metroidprime's shutdown sequence (which
    also unconditionally slept 3s before joining the sync task).

    ``CommonContext.shutdown()`` awaits ``server_task``, which can sit in a
    pending websocket connect (a connect/auto-reconnect attempt to an
    unreachable server: websockets' 10s open timeout) or close handshake
    (a dead connection: 10s close timeout) -- the client window closes but
    the process hangs around, and a connect that then fails tries to open
    a connection-loss message box on the already-stopped UI and throws.
    """
    if ctx.dolphin_sync_task:
        try:
            await asyncio.wait_for(ctx.dolphin_sync_task, _SHUTDOWN_TIMEOUT)
        except TimeoutError:
            logger.warning("Dolphin sync task didn't stop in time; cancelled it.")

    if ctx.server_task and not ctx.server_task.done() and ctx.server is None:
        # Still connecting: there's no connection to close gracefully.
        ctx.server_task.cancel()
        await asyncio.gather(ctx.server_task, return_exceptions=True)
        ctx.server_task = None

    try:
        await asyncio.wait_for(ctx.shutdown(), _SHUTDOWN_TIMEOUT)
    except TimeoutError:
        logger.warning("Server connection didn't close in time; exiting anyway.")


def main(*args: str) -> None:
    Utils.init_logging("MetroidPrime2Client")

    async def _main(
        connect: str | None, password: str | None, apmp2_file: str | None, iso: str | None, verbose: bool
    ) -> None:
        setup_libs()

        multiprocessing.freeze_support()
        logger.info("main")

        ctx = MetroidPrime2Context(connect, password, apmp2_file, iso)
        ctx.debug_enabled = bool(get_settings()["metroidprime2_options"]["debug"])
        ctx.verbose = verbose

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

        await _shutdown(ctx)

    parser = get_base_parser()
    parser.add_argument("apmp2_file", default="", type=str, nargs="?", help="Path to an apmp2 file")
    parser.add_argument("iso", default="", type=str, nargs="?", help="Path to a Metroid Prime 2: Echoes iso")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log ISO patching progress to the console.")
    parser_args = parser.parse_args(args)

    import colorama

    colorama.init()
    asyncio.run(
        _main(
            parser_args.connect,
            parser_args.password,
            parser_args.apmp2_file,
            parser_args.iso,
            parser_args.verbose,
        )
    )
    colorama.deinit()
