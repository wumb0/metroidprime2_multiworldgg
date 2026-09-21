"""Pure reconciliation logic for the magic-item counter's lossy summing
behavior (PLAN.md section J risk 3 / section O).

``constants.MAGIC_ITEM``'s amount is a real MP2 pickup counter: every
pickup ADDS its own ``pickup_index + 1`` to whatever the counter already
holds (it isn't set outright -- see ``constants.MAGIC_ITEM``'s and
``patcher_runner._add_goal_trigger``'s docstrings for the one exception,
the Credits-area sentinel, which *is* an absolute set). The client
consumes it with a matching negative delta once it has read and reported
it, so the counter only ever holds "pickups collected since the last
successful read" -- normally exactly one. If the client isn't attached
and consuming for a while (most realistically: a disconnect) and the
player collects more than one real pickup in that window, the counter
ends up holding their *sum*, and there is no way to read back which
specific pickups produced it from the number alone.

There is, however, a second, independent source of truth: the server
already knows which of this player's locations are still unchecked
(``ctx.missing_locations``). Only those pickups are still physically
collectible in-game (a checked one's pickup object is already gone), so
they're the only candidates that could have contributed to a fresh,
unreported sum. If exactly one combination of currently-unchecked pickups
sums to the observed amount, it's safe to credit all of them; if more
than one combination could explain it (or none can), there is genuinely
no way to tell which pickups happened, and nothing should be guessed at --
guessing wrong would credit a location (and send its item) that was never
actually collected.
"""

from __future__ import annotations

_DEFAULT_MAX_MISSED = 8


def find_unique_missed_locations(
    amount: int, candidate_indices: list[int], max_missed: int = _DEFAULT_MAX_MISSED
) -> list[int] | None:
    """Tries to explain a magic-item ``amount`` that didn't correspond to a
    single valid pickup index as the sum of 1..``max_missed`` distinct
    pickups drawn from ``candidate_indices`` (0-based pickup indices not
    yet confirmed checked by the server, i.e. ``ctx.missing_locations``
    translated back to indices).

    Returns the sorted list of pickup indices if *exactly one* combination
    of at most ``max_missed`` of them sums to ``amount``. Returns ``None``
    if zero or more than one combination does -- callers must treat that
    as unrecoverable (the existing "implausible, warn and drop" path),
    never guess between multiple equally-valid explanations.

    ``max_missed`` bounds the search (a bounded-size subset-sum DP over
    ``len(candidate_indices)`` items and target ``amount``) and doubles as
    a sanity limit: a real disconnect losing 9+ location checks at once is
    not a scenario worth guessing about even if a unique combination
    happened to exist, so anything needing more than ``max_missed``
    pickups is left unexplained rather than searched for.
    """
    if amount <= 0 or max_missed <= 0:
        return None

    values = sorted((idx, idx + 1) for idx in set(candidate_indices))
    if not values:
        return None

    largest_first = sorted((v for _, v in values), reverse=True)
    max_possible = sum(largest_first[:max_missed])
    if amount > max_possible:
        return None

    n = len(values)
    # ways[i][k][j] = number of distinct subsets of values[:i], of size
    # exactly k, summing to j. ways[0] is the base case: only the empty
    # subset (size 0, sum 0).
    ways: list[list[list[int]]] = [[[0] * (amount + 1) for _ in range(max_missed + 1)]]
    ways[0][0][0] = 1

    for _, value in values:
        prev = ways[-1]
        current = [row[:] for row in prev]
        for k in range(1, max_missed + 1):
            for j in range(value, amount + 1):
                current[k][j] += prev[k - 1][j - value]
        ways.append(current)

    total_ways = sum(ways[n][k][amount] for k in range(1, max_missed + 1))
    if total_ways != 1:
        return None

    size = next(k for k in range(1, max_missed + 1) if ways[n][k][amount] == 1)
    remaining = amount
    found: list[int] = []
    for i in range(n, 0, -1):
        if size == 0:
            break
        idx, value = values[i - 1]
        if remaining >= value and ways[i - 1][size - 1][remaining - value] == 1:
            found.append(idx)
            size -= 1
            remaining -= value
    return sorted(found)
