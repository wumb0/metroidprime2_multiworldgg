"""Pure DeathLink polling decision for Metroid Prime 2: Echoes.

No Dolphin/AP context dependency (mirrors ``receive_items.py``) so it can
be unit tested directly (``test/test_deathlink.py``).
"""

from __future__ import annotations


def death_link_check(
    health: float | None, is_pending_reset: bool, alive: bool | None = None
) -> tuple[bool, bool]:
    """Given the player's current health, the ``CPlayerState::alive`` flag
    (``None`` if unknown/untrusted) and whether a send is already pending
    reset (debounces a multi-tick organic death -- health stays <= 0 and/or
    alive stays cleared for several ticks of the death animation before
    respawn restores them), returns ``(should_send_death,
    new_is_pending_reset)``. Either health <= 0 or a cleared alive flag counts
    as dead. ``health=None`` (not connected/no CPlayerState yet) never sends
    and leaves the pending-reset flag untouched."""
    if health is None:
        return False, is_pending_reset
    dead = health <= 0 or alive is False
    if dead and not is_pending_reset:
        return True, True
    if not dead and is_pending_reset:
        return False, False
    return False, is_pending_reset
