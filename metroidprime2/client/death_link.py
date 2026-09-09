"""Pure DeathLink polling decision for Metroid Prime 2: Echoes.

No Dolphin/AP context dependency (mirrors ``receive_items.py``) so it can
be unit tested directly (``test/test_deathlink.py``).
"""

from __future__ import annotations

from typing import Optional


def death_link_check(health: Optional[float], is_pending_reset: bool) -> tuple[bool, bool]:
    """Given the player's current health and whether a send is already
    pending reset (debounces a multi-tick organic death -- health stays
    <= 0 for several ticks of the death animation before respawn restores
    it), returns ``(should_send_death, new_is_pending_reset)``.
    ``health=None`` (not connected/no CPlayerState yet) never sends and
    leaves the pending-reset flag untouched."""
    if health is None:
        return False, is_pending_reset
    if health <= 0 and not is_pending_reset:
        return True, True
    if health > 0 and is_pending_reset:
        return False, False
    return False, is_pending_reset
