"""RunState: the small bundle of state that survives *across* node loads
within one roguelike run -- lives, shop currency, drafted tower pool,
relics, seed, and the run's own map/position within it. Battle gold
(Economy.gold) is deliberately *not* one of these fields -- it resets fresh
every floor instead of carrying forward; see game.py's _load_combat_node and
CLAUDE.md's "Two currencies" section for the split this reflects.

Everything else about a floor (Grid/Economy/WaveManager/towers/enemies) is
fully rebuilt fresh by Game._load_level_object() on every combat/elite node
load, exactly like a normal level load already works today -- a RunState is
purely what a deckbuilder run carries between those resets, the same way a
deckbuilder doesn't carry board state between combats, only your deck and
HP. See run_map.py for how the map itself is generated and card_pool.py for
the starter tower pool a run begins with.
"""

from dataclasses import dataclass, field


@dataclass
class RunState:
    seed: int
    # The run's whole branching map, generated once (run_map.generate_run_
    # map) at start_new_run() and never regenerated or mutated afterward --
    # replaces the old flat, ascending floor_sequence tuple entirely (see
    # run_map.py's own module docstring for why a full map upfront is
    # generated once rather than re-derived per floor the way _run_rng's
    # streams are).
    map: object
    difficulty: str
    unlocked_towers: list
    # The node currently occupied -- None only before the player has picked
    # one of the map's row-0 nodes yet (right after start_new_run(), while
    # sitting on the map screen for the very first time). Replaces the old
    # floor_index int: a branching map has no single "how far along" number
    # that identifies a position the way a flat sequence's index did, only
    # a specific node.
    current_node_id: str = None
    # Every node id resolved so far, in the order they were reached --
    # combat/elite nodes append their own id in Game._advance_run_floor;
    # every other node type appends via Game._finish_node once its own
    # resolution (Shop's Continue, an Event's chosen option, Rest/Treasure's
    # auto-resolve) completes. What RunState.floors_cleared below counts
    # from.
    visited_node_ids: list = field(default_factory=list)
    # Placeholder until _load_combat_node captures the very first combat
    # node's own freshly-loaded Economy -- see that method's own docstring
    # for why the run's first-ever node is the one exception to "the run's
    # own lives carry into a node load." There is no equivalent `gold`
    # field: battle gold (Economy.gold) resets fresh every floor now (see
    # game.py's _load_combat_node and CLAUDE.md's "Two currencies" section)
    # and so has nothing left to carry -- only lives still survives a node
    # transition.
    lives: int = 0
    # The run's own cross-floor currency -- unlike battle gold (Economy.
    # gold, reset fresh every floor), this persists exactly like
    # unlocked_towers/relics below, reset only at start_new_run. Earned at
    # every combat/elite node clear (see shop.income_for_floor/Game.
    # _advance_run_floor) and at every Treasure node (see run_map.
    # treasure_shop_currency_for_row), spent at the Shop screen (see
    # shop.py/game.py's GameState.DRAFT for why the code still says
    # "draft" throughout even though the screen is a shop now, only
    # reachable via a Shop map node rather than automatically now).
    shop_currency: int = 0
    # Run-wide passive modifier cards -- see relics.py. Grows via relic
    # cards bought at the Shop (see shop.build_offer), granted by a
    # Treasure node, or granted by a Random Event's own grant_relic option
    # (see events.py) -- the same "appended to a list" shape unlocked_
    # towers already has, though unlike unlocked_towers (a required field,
    # no default of its own to get wrong), this one does need
    # field(default_factory=list) rather than a bare `= []`, the same
    # mutable-default-arg precedent levels.py's own Level.blocked_cells/
    # branch_weights already establish, so this default is never shared/
    # aliased across RunState instances.
    relics: list = field(default_factory=list)
    # Whether this is a Daily Run -- see Game.start_new_run's own docstring
    # for the one thing that actually branches on it (pinning difficulty
    # to "normal" for a fair, comparable score). Not currently threaded
    # into run_history.record_run_result, so a Daily Run's outcome isn't
    # yet distinguishable from an ordinary run's in run_history.json --
    # this field only lives on the in-memory RunState for now; a future
    # run-history browse screen wanting that distinction would need
    # record_run_result to start accepting/persisting it too.
    is_daily: bool = False
    # Miser's Coffer's own gate (relics.py) -- flips true the instant this
    # run ever spends any gold (Game._spend_gold, the one choke point
    # every gold-spending call site routes through) and stays true
    # forever after, tracked unconditionally regardless of whether the
    # relic is even held, the same "always tracked, only some relics read
    # it" precedent floors_cleared/current_row already set for
    # veterans_momentum.
    has_spent_gold: bool = False
    # Guardian's Reprieve's one-time charge (relics.py) -- flips true the
    # first time it actually saves the run from losing its last life
    # (Game._lose_a_life), and never resets for the rest of the run.
    used_guardians_reprieve: bool = False

    @property
    def current_level_id(self):
        return self.map.node(self.current_node_id).level_id

    @property
    def current_row(self):
        """Which row of the map the current node sits on -- the depth
        value run_escalation.escalation_for_floor()/relics.
        compose_relic_modifiers() read (see game.py's _floor_load_context),
        the same role floor_index used to play when the run was a flat
        sequence."""
        return self.map.node(self.current_node_id).row

    @property
    def is_final_floor(self):
        return self.current_row == self.map.final_row_index

    @property
    def floors_cleared(self):
        """How many Combat/Elite nodes have been fully cleared so far --
        deliberately excludes Shop/Event/Rest/Treasure stops, so browsing a
        handful of non-combat nodes on the way to the boss doesn't inflate
        this the way visiting more nodes overall would. This is what
        run_history.py/meta_progression.py's total_floors_cleared actually
        mean by "a floor" -- a fight genuinely fought and won, not a stop
        visited."""
        return sum(
            1 for node_id in self.visited_node_ids
            if self.map.node(node_id).node_type in ("combat", "elite")
        )
