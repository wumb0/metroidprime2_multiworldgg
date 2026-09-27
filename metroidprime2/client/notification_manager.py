"""Based on ``worlds/metroidprime/NotificationManager.py`` (PLAN.md section
J deliverable 2). Pure queue/cooldown logic with no Dolphin dependency.

Beyond the MP1 original, received-item notifications are queued as
``ReceivedItemsNotification`` entries rather than plain strings, so more
copies of the same item from the same sender merge into the still-queued
entry ("Received 15 Missiles from X") instead of each getting its own HUD
message. A new entry is held for ``RECEIVE_GROUP_WINDOW`` seconds before
it can be shown, so copies arriving over a few consecutive ticks still
land in one message.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ..items import ITEM_TABLE

RECEIVE_GROUP_WINDOW = 1.0

# Ammo expansions are announced as the total ammo received when grouped
# (the per-copy amount comes from items.py so the two can't drift apart).
_AMMO_LABELS = {
    "Missile Expansion": "Missiles",
    "Power Bomb Expansion": "Power Bombs",
    "Dark Ammo Expansion": "Dark Ammo",
    "Light Ammo Expansion": "Light Ammo",
    "Beam Ammo Expansion": "Dark and Light Ammo",
}


def format_received_items(item_name: str, count: int, sender_name: str) -> str:
    if count == 1:
        return f"Received {item_name} from {sender_name}"
    label = _AMMO_LABELS.get(item_name)
    if label is not None:
        amount = ITEM_TABLE[item_name].gains[0][1] * count
        return f"Received {amount} {label} from {sender_name}"
    return f"Received {item_name} x{count} from {sender_name}"


@dataclass
class ReceivedItemsNotification:
    item_name: str
    sender_name: str
    count: int
    ready_at: float = field(default_factory=lambda: time.time() + RECEIVE_GROUP_WINDOW)

    def __str__(self) -> str:
        return format_received_items(self.item_name, self.count, self.sender_name)


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
        for entry in self.notification_queue:
            if (
                isinstance(entry, ReceivedItemsNotification)
                and entry.item_name == item_name
                and entry.sender_name == sender_name
            ):
                entry.count += count
                return
        self.notification_queue.append(ReceivedItemsNotification(item_name, sender_name, count))

    def handle_notifications(self):
        now = time.time()
        self.time_since_last_message = now - self.last_message_time
        if len(self.notification_queue) > 0 and self.time_since_last_message >= self.message_duration:
            notification = self.notification_queue[0]
            if isinstance(notification, ReceivedItemsNotification) and now < notification.ready_at:
                return
            result = self.send_notification_func(str(notification))
            if result:
                self.notification_queue.pop(0)
                self.last_message_time = time.time()
                self.time_since_last_message = 0
