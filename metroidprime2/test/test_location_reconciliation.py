"""Exhaustive correctness tests for location_reconciliation's subset-sum
search. Correctness matters more than usual here: a wrong answer would
credit a location (and send its item to whoever the fill placed it for)
that was never actually collected -- so every returned result is checked
against brute force for a range of random-ish cases, in addition to the
targeted unique/ambiguous/impossible scenarios.
"""

from __future__ import annotations

import itertools
import random
import unittest

from ..client.location_reconciliation import find_unique_missed_locations


def _brute_force_solutions(amount: int, candidate_indices: list[int], max_missed: int) -> list[tuple[int, ...]]:
    """All combinations (any size 1..max_missed) of candidate_indices whose
    (idx + 1) values sum to amount. Reference implementation for
    cross-checking the DP on small inputs."""
    solutions = []
    for size in range(1, max_missed + 1):
        solutions.extend(
            combo
            for combo in itertools.combinations(sorted(candidate_indices), size)
            if sum(idx + 1 for idx in combo) == amount
        )
    return solutions


class TestUniqueMatch(unittest.TestCase):
    def test_single_candidate_exact_match(self) -> None:
        self.assertEqual([9], find_unique_missed_locations(10, [9]))

    def test_unique_pair(self) -> None:
        # values 61 (idx60) + 91 (idx90) = 152, only pair summing to it.
        self.assertEqual([60, 90], find_unique_missed_locations(152, [5, 60, 90]))

    def test_unique_triple(self) -> None:
        # idx 0,1,2 -> values 1,2,3 -> sum 6. idx 10 (value 11) is a
        # distractor that can't participate in any combination summing to 6.
        self.assertEqual([0, 1, 2], find_unique_missed_locations(6, [0, 1, 2, 10]))

    def test_order_of_candidate_indices_does_not_matter(self) -> None:
        self.assertEqual(
            find_unique_missed_locations(152, [90, 5, 60]),
            find_unique_missed_locations(152, [5, 60, 90]),
        )

    def test_duplicate_candidate_indices_are_deduplicated(self) -> None:
        self.assertEqual([9], find_unique_missed_locations(10, [9, 9, 9]))


class TestAmbiguousOrImpossible(unittest.TestCase):
    def test_ambiguous_pair_returns_none(self) -> None:
        # {59,62} (idx 58,61) and {60,61} (idx 59,60) both sum to 121.
        self.assertIsNone(find_unique_missed_locations(121, [58, 59, 60, 61]))

    def test_no_combination_reaches_target(self) -> None:
        self.assertIsNone(find_unique_missed_locations(1000, [0, 1, 2]))

    def test_empty_candidates_returns_none(self) -> None:
        self.assertIsNone(find_unique_missed_locations(10, []))

    def test_zero_or_negative_amount_returns_none(self) -> None:
        self.assertIsNone(find_unique_missed_locations(0, [1, 2, 3]))
        self.assertIsNone(find_unique_missed_locations(-5, [1, 2, 3]))

    def test_solution_needs_more_than_max_missed_returns_none(self) -> None:
        # Only way to reach 15 from values 1..6 (idx 0..5) using at most 2
        # is impossible (max pair is 5+6=11); the actual (unique, size-5)
        # solution 1+2+3+4+5=15 must NOT be found once it's excluded by
        # the size cap.
        candidates = [0, 1, 2, 3, 4]  # values 1,2,3,4,5
        self.assertIsNone(find_unique_missed_locations(15, candidates, max_missed=2))
        # But it IS found once the cap allows it.
        self.assertEqual(candidates, find_unique_missed_locations(15, candidates, max_missed=5))


class TestAgainstBruteForce(unittest.TestCase):
    """Cross-checks the DP against a brute-force combinations search over
    many random small instances -- if the DP ever disagrees with brute
    force, that's a correctness bug, not a design choice."""

    def test_random_small_instances_match_brute_force(self) -> None:
        rng = random.Random(0)
        for _ in range(200):
            pool_size = rng.randint(1, 10)
            candidates = rng.sample(range(0, 30), pool_size)
            max_missed = rng.randint(1, 4)
            amount = rng.randint(1, 40)

            expected_solutions = _brute_force_solutions(amount, candidates, max_missed)
            result = find_unique_missed_locations(amount, candidates, max_missed=max_missed)

            if len(expected_solutions) == 1:
                self.assertEqual(
                    sorted(expected_solutions[0]),
                    result,
                    f"amount={amount} candidates={candidates} max_missed={max_missed}",
                )
            else:
                self.assertIsNone(
                    result,
                    f"amount={amount} candidates={candidates} max_missed={max_missed} "
                    f"expected ambiguous/impossible ({len(expected_solutions)} solutions) but got {result}",
                )

    def test_every_returned_result_actually_sums_to_amount(self) -> None:
        rng = random.Random(1)
        for _ in range(200):
            pool_size = rng.randint(1, 12)
            candidates = rng.sample(range(0, 119), pool_size)
            amount = rng.randint(1, 300)

            result = find_unique_missed_locations(amount, candidates)
            if result is not None:
                self.assertEqual(amount, sum(idx + 1 for idx in result))
                self.assertEqual(len(set(result)), len(result))  # no duplicates
                self.assertTrue(set(result) <= set(candidates))


if __name__ == "__main__":
    unittest.main()
