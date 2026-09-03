"""RunState: the small bundle of state that survives *across* floor loads
within one roguelike run -- lives, gold, drafted tower pool, relics, seed,
and floor position.

Everything else about a floor (Grid/Economy/WaveManager/towers/enemies) is
fully rebuilt fresh by Game._load_level_object() on every floor load, exactly
like a normal level load already works today -- a RunState is purely what a
deckbuilder run carries between those resets, the same way a deckbuilder
doesn't carry board state between combats, only your deck and HP. See
run_floors.py for how floor_sequence is sampled and card_pool.py for the
starter tower pool a run begins with.
"""

from dataclasses import dataclass

# Milestone 4 adds `relics: list` (run-wide passive modifier cards) and
# `is_daily: bool` (Daily Run) to this dataclass -- left out for now rather
# than added unused, since nothing reads either until that milestone gives
# them real behavior.


@dataclass
class RunState:
    seed: int
    floor_sequence: tuple
    difficulty: str
    unlocked_towers: list
    floor_index: int = 0
    # Placeholder until _load_floor(0) captures floor 0's own freshly-loaded
    # Economy -- see _load_floor's docstring for why floor 0 is the one
    # exception to "the run's own lives/gold carry into a floor load."
    lives: int = 0
    gold: int = 0

    @property
    def current_level_id(self):
        return self.floor_sequence[self.floor_index]

    @property
    def is_final_floor(self):
        return self.floor_index == len(self.floor_sequence) - 1

    @property
    def floors_cleared(self):
        """How many floors have been fully cleared so far. Always equal to
        floor_index -- floor_index only ever advances when a floor clears
        (see Game._advance_run_floor), so a separate counter would just be
        two numbers that can never actually disagree. Kept as its own named
        property (rather than having callers read floor_index directly)
        since "floors cleared" is the semantically meaningful thing a
        summary screen or run_history entry (a future milestone) wants to
        report, even though floor_index is what's actually stored."""
        return self.floor_index
