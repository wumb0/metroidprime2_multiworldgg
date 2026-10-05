"""Based on ``worlds/metroidprime/NotificationManager.py`` (PLAN.md section
J deliverable 2). Pure queue/cooldown logic with no Dolphin dependency.

Beyond the MP1 original, received items are queued as
``ReceivedItemsNotification`` entries rather than plain strings: one entry
per sender listing everything received from them ("Received 15 Missiles,
Energy Tank x2 from X"), which later receipts merge into while it's still
queued. An entry only starts a second message for the same sender once the
first would no longer fit on the HUD. A new entry is held for
``RECEIVE_GROUP_WINDOW`` seconds before it can be shown, so items arriving
over a few consecutive ticks still land in one message.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ..items import ITEM_TABLE

RECEIVE_GROUP_WINDOW = 1.0

# The HUD message buffer holds (max_message_size - 6) / 2 = 97 UTF-16 code
# units on both NTSC and PAL (versions.py); leave some slack for a merged
# count gaining a digit after the entry was packed.
HUD_MAX_CHARS = 90

# Ammo expansions are announced as the total ammo received when grouped
# (the per-copy amount comes from items.py so the two can't drift apart).
_AMMO_LABELS = {
    "Missile Expansion": "Missiles",
    "Power Bomb Expansion": "Power Bombs",
    "Dark Ammo Expansion": "Dark Ammo",
    "Light Ammo Expansion": "Light Ammo",
    "Beam Ammo Expansion": "Dark and Light Ammo",
}


def format_item_count(item_name: str, count: int) -> str:
    if count == 1:
        return item_name
    label = _AMMO_LABELS.get(item_name)
    if label is not None:
        return f"{ITEM_TABLE[item_name].gains[0][1] * count} {label}"
    return f"{item_name} x{count}"


def format_received_items(items: dict[str, int], sender_name: str) -> str:
    listed = ", ".join(format_item_count(name, count) for name, count in items.items())
    return f"Received {listed} from {sender_name}"


@dataclass
class ReceivedItemsNotification:
    sender_name: str
    items: dict[str, int]
    ready_at: float = field(default_factory=lambda: time.time() + RECEIVE_GROUP_WINDOW)

    def __str__(self) -> str:
        return format_received_items(self.items, self.sender_name)


class NotificationManager:
    notification_queue: list[str | ReceivedItemsNotification]
    time_since_last_message: float = 0
    last_message_time: float = 0
    message_duration: float
    send_notification_func: Callable[[str], bool]

    def __init__(self, message_duration: float, send_notification_func: Callable[[str], bool]):
        self.message_duration = message_duration / 2  # If there are multiple messages, the duration is shorter
        self.send_notification_func = send_notification_func
        self.notification_queue = []

    def queue_notification(self, message: str):
        if message not in self.notification_queue:
            self.notification_queue.append(message)

    def queue_received_items(self, item_name: str, sender_name: str, count: int = 1):
        entries = [
            entry
            for entry in self.notification_queue
            if isinstance(entry, ReceivedItemsNotification) and entry.sender_name == sender_name
        ]
        for entry in entries:
            if item_name in entry.items:
                entry.items[item_name] += count
                return
        if entries:
            last = entries[-1]
            if len(format_received_items({**last.items, item_name: count}, sender_name)) <= HUD_MAX_CHARS:
                last.items[item_name] = count
                return
        self.notification_queue.append(ReceivedItemsNotification(sender_name, {item_name: count}))

    def handle_notifications(self) -> bool:
        """Sends the next due notification, if any. Returns True when a
        message was sent (so the caller knows the game-side op slot is now
        taken for this tick)."""
        now = time.time()
        self.time_since_last_message = now - self.last_message_time
        if len(self.notification_queue) > 0 and self.time_since_last_message >= self.message_duration:
            notification = self.notification_queue[0]
            if isinstance(notification, ReceivedItemsNotification) and now < notification.ready_at:
                return False
            result = self.send_notification_func(str(notification))
            if result:
                self.notification_queue.pop(0)
                self.last_message_time = time.time()
                self.time_since_last_message = 0
                return True
        return False
