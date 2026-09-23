"""Persistent, cross-session tower unlocks for the roguelike run's draft
pool.

A registry of lockable towers (same {key: ...} shape as ACHIEVEMENTS/
TOWER_TYPES/ENEMY_TYPES/LEVELS), each keyed off crossing a threshold on one
of a handful of cumulative lifetime counters -- built on threshold_unlocks.py's
shared mechanics, the same ones achievements.py itself is built on (see that
module's own docstring for why the *mechanics* are shared while the file/
registry/JSON state stay genuinely separate). Kept as a genuinely separate
module and file from achievements.py on purpose: achievements are cosmetic/
trophy-flavored (there's no gameplay consequence to unlocking one), while
these unlocks are gameplay-flavored -- they change what card_pool.draft_offer()
can actually offer a future run. Conflating the two would make one registry
serve two very different urgencies of "what does this number gate."

Unlike Achievement, a MetaUnlock has no display_name/description of its
own -- it unlocks a specific TOWER_TYPES entry, which already has a
display_name; toasting/describing an unlock reads that off TOWER_TYPES
directly (see Game._queue_meta_unlock_toasts) rather than duplicating it
here where it could drift out of sync.

RelicMetaUnlock/LevelMetaUnlock below extend the same threshold-crossing
mechanics to two more content kinds -- relics.py's own RELICS and
levels.py's own LEVELS -- once there was finally new content (the relic-
gaps and multi-lane-levels batches) worth gating behind a deeper curve
than the original 7-tower one, which fully exhausts within a handful of
runs. Deliberately two more small, separate classes rather than
generalizing MetaUnlock into one class with a "kind" discriminator --
MetaUnlock is read directly (`unlock.tower_name`) in a few places and
heavily covered by existing tests; a second, additive registry per
content kind is safer than teaching that one class to be polymorphic.
Both stay genuinely optional gating, same spirit as the tower curve: only
the *newest* relics/levels are ever gated, every relic/level that shipped
before this existed remains permanently ungated (relics.py's own
docstring used to say relics are never account-gated at all -- see its
own note on why that's now only true of the pre-existing 29).
"""

from persistence.json_io import module_relative_path
from progression import threshold_unlocks
from progression.threshold_unlocks import CountersState
from world.levels import LEVELS, Level

SCHEMA_VERSION = 1
META_PROGRESSION_PATH = module_relative_path(__file__, "meta_progression.json")


class MetaUnlock:
    """One registry entry -- `tower_name` becomes draftable account-wide
    once `counter` (a key into the persisted counters dict) reaches
    `goal`."""

    def __init__(self, key: str, tower_name: str, counter: str, goal: int) -> None:
        self.key = key
        self.tower_name = tower_name
        self.counter = counter
        self.goal = goal


# Every TOWER_TYPES entry not in card_pool.STARTER_TOWERS gets exactly one
# entry here -- not imported from card_pool.py to avoid a circular import
# (card_pool.draft_offer's own default pool reads unlocked_tower_pool()
# below), so this list is the one place that pairing has to be kept
# correct by hand. total_floors_cleared/runs_played/runs_reached_endless
# are bumped from game.py (_advance_run_floor and _record_run_permadeath)
# -- see their own comments there for exactly when each fires.
#
# unlock_knockback's goal of 1 is load-bearing, not just the easiest one:
# _advance_run_floor bumps total_floors_cleared *before* the player ever
# sees a draft screen (see its own comment), so a brand new player's very
# first floor clear already crosses this threshold -- their first-ever
# draft screen (Milestone 2's own "every floor clear enters DRAFT"
# assumption) has a real card to offer instead of finding STARTER_TOWERS
# fully exhausted and silently skipping straight to the next floor. Every
# later threshold only has to keep pace with that, not also solve it.
META_UNLOCKS: dict[str, MetaUnlock] = {
    "unlock_knockback": MetaUnlock("unlock_knockback", "knockback", "total_floors_cleared", 1),
    "unlock_poison": MetaUnlock("unlock_poison", "poison", "total_floors_cleared", 3),
    "unlock_lightning": MetaUnlock("unlock_lightning", "lightning", "total_floors_cleared", 5),
    "unlock_sniper": MetaUnlock("unlock_sniper", "sniper", "runs_played", 1),
    "unlock_support": MetaUnlock("unlock_support", "support", "runs_played", 2),
    "unlock_beam": MetaUnlock("unlock_beam", "beam", "runs_reached_endless", 1),
    "unlock_beacon": MetaUnlock("unlock_beacon", "beacon", "runs_played", 3),
    "unlock_siphon": MetaUnlock("unlock_siphon", "siphon", "runs_played", 4),
    "unlock_overload_cannon": MetaUnlock("unlock_overload_cannon", "overload_cannon", "total_floors_cleared", 8),
}


class RelicMetaUnlock:
    """One registry entry -- `relic_key` (a relics.RELICS key) becomes
    offerable account-wide once `counter` reaches `goal`. Same shape as
    MetaUnlock, kept as its own class rather than a generalized one -- see
    this module's own docstring."""

    def __init__(self, key: str, relic_key: str, counter: str, goal: int) -> None:
        self.key = key
        self.relic_key = relic_key
        self.counter = counter
        self.goal = goal


# Only the newest relic batch (the knockback/mark/anti-flying/shielded/
# healer/Splitter-counterplay one) gets any gating consideration -- every
# relic that shipped before this existed stays permanently ungated, same
# "only the non-starter subset" precedent META_UNLOCKS sets for towers.
# Thresholds are deliberately well past every META_UNLOCKS one above (that
# curve fully exhausts by runs_played<=3), so there's still something to
# chase long after every tower is already unlocked.
# unlock_containment_charges gated on bosses_defeated is a deliberate
# cross-chunk payoff: Game._handle_boss_defeated bumps that counter every
# time a run's final boss's authored waves clear for the first time, so
# this is "beat the final boss once" rather than a grind threshold.
RELIC_META_UNLOCKS: dict[str, RelicMetaUnlock] = {
    "unlock_flak_rounds": RelicMetaUnlock(
        "unlock_flak_rounds", "flak_rounds", "total_floors_cleared", 25,
    ),
    "unlock_breach_charges": RelicMetaUnlock(
        "unlock_breach_charges", "breach_charges", "runs_played", 10,
    ),
    "unlock_containment_charges": RelicMetaUnlock(
        "unlock_containment_charges", "containment_charges", "bosses_defeated", 1,
    ),
    # A second wave of gating, on the cross-status combo-capstone batch's
    # two Mark-keyed relics -- the highest per-relic power multiplier in
    # the whole registry (1.35x, unconditional whenever both statuses are
    # live, vs. every chance-gated crit relic's much smaller *effective*
    # average). frostbitten_mark/plague_mark are gated; chill_rot
    # (Frost+Poison, the more approachable pairing between two starter-
    # tower-adjacent towers) stays ungated on purpose, so the cross-status
    # mechanic itself is still reachable early -- only the chase for the
    # other two, keyed on the rarer Mark status (Beacon has only 2
    # dedicated relics total), is long-tail. Thresholds are set well past
    # every existing RELIC_META_UNLOCKS entry above, so there's still
    # something to chase once those are all cleared.
    "unlock_frostbitten_mark": RelicMetaUnlock(
        "unlock_frostbitten_mark", "frostbitten_mark", "total_floors_cleared", 50,
    ),
    "unlock_plague_mark": RelicMetaUnlock(
        "unlock_plague_mark", "plague_mark", "runs_played", 20,
    ),
    # A third wave of gating, completing the cross-status combo-capstone
    # batch's gating: seismic_slam (Knockback's 2nd exclusive relic) is the
    # only relic from that same batch still ungated -- chill_rot stays
    # deliberately ungated on purpose (see the comment above), so it is NOT
    # re-gated here. Threshold set past frostbitten_mark/plague_mark, the
    # previous highest in this registry.
    "unlock_seismic_slam": RelicMetaUnlock(
        "unlock_seismic_slam", "seismic_slam", "total_floors_cleared", 75,
    ),
}


class LevelMetaUnlock:
    """One registry entry -- `level_id` (a levels.LEVELS key) becomes
    drawable into a run's map once `counter` reaches `goal`. Same shape as
    MetaUnlock/RelicMetaUnlock."""

    def __init__(self, key: str, level_id: int, counter: str, goal: int) -> None:
        self.key = key
        self.level_id = level_id
        self.counter = counter
        self.goal = goal


# Only the hardest of Chunk C's 4 new multi-lane levels is gated -- most
# new content stays immediately available, matching the design note in
# this module's own docstring; a run whose map can't draw a gated level id
# just never offers that node's floor, same as any other seed variance.
# Level 15 ("Double Confluence") joins it as a second gate -- the only
# other ordinary (non-boss) multi-lane level still ungated, a genuine step
# up from Quad Muster (4 spawns into 1 goal) via 2 independent goals
# instead of 1. Threshold set past unlock_quad_muster's own 15.
LEVEL_META_UNLOCKS: dict[str, LevelMetaUnlock] = {
    "unlock_quad_muster": LevelMetaUnlock("unlock_quad_muster", 14, "runs_played", 15),
    "unlock_double_confluence": LevelMetaUnlock("unlock_double_confluence", 15, "runs_played", 25),
}


class ShopMetaUnlock:
    """One registry entry -- an account-wide Shop *capability* (not a
    specific tower/relic/level id) unlocks once `counter` reaches `goal`.
    A 4th, genuinely separate class rather than reusing MetaUnlock/
    RelicMetaUnlock/LevelMetaUnlock or teaching one of them a "kind"
    discriminator -- none of the three has a content id to point at here,
    this just gates a permanent change to how shop.build_offer() itself
    behaves."""

    def __init__(self, key: str, counter: str, goal: int) -> None:
        self.key = key
        self.counter = counter
        self.goal = goal


# A permanent, account-wide upgrade to every future Shop visit outranks
# any single relic/level, so this is deliberately the single longest
# chase in the whole system -- past even RELIC_META_UNLOCKS' own current
# highest (unlock_frostbitten_mark's total_floors_cleared=50).
SHOP_META_UNLOCKS: dict[str, ShopMetaUnlock] = {
    "unlock_third_relic_slot": ShopMetaUnlock("unlock_third_relic_slot", "total_floors_cleared", 100),
}

# Every registry above shares one JSON file's flat {"counters": ..,
# "unlocked": {key, ...}} state -- a single combined dict lets bump() below
# unlock across all four content kinds from one shared counter (e.g.
# bosses_defeated feeding unlock_containment_charges) without needing to
# know in advance which registry a given counter_name belongs to. Key
# namespaces never collide (every key is its own "unlock_<name>" string),
# so merging is safe.
ALL_UNLOCKS: dict[str, MetaUnlock | RelicMetaUnlock | LevelMetaUnlock | ShopMetaUnlock] = {
    **META_UNLOCKS, **RELIC_META_UNLOCKS, **LEVEL_META_UNLOCKS, **SHOP_META_UNLOCKS,
}


def load_meta_progression(path: str = META_PROGRESSION_PATH) -> CountersState:
    """{"counters": {name: int}, "unlocked": {key, ...}} -- falls back to
    empty state if the file doesn't exist yet or fails to parse, same
    spirit as achievements.load_achievements()."""
    return threshold_unlocks.load_counters_state(path)


def save_meta_progression(state: CountersState, path: str = META_PROGRESSION_PATH) -> None:
    threshold_unlocks.save_counters_state(state, path, SCHEMA_VERSION)


def bump(counter_name: str, amount: int = 1, path: str = META_PROGRESSION_PATH) -> list[str]:
    """Bump `counter_name` by `amount` and return the list of unlock keys
    newly unlocked by this bump (in registry insertion order), across all
    three of META_UNLOCKS/RELIC_META_UNLOCKS/LEVEL_META_UNLOCKS at once
    (see ALL_UNLOCKS) -- a caller doesn't (and shouldn't need to) know
    which content kind a given counter_name happens to gate. For a counter
    that's a simple +1-(or more)-per-event tally -- every counter above is
    one of these; achievements.py's sibling set_counter() (for a counter
    driven by an already-deduplicated external count, like its own
    distinct_levels_cleared) has no equivalent here yet since nothing
    needs it -- threshold_unlocks.set_counter() already exists to mirror
    that shape if a future counter does."""
    return threshold_unlocks.bump_counter(ALL_UNLOCKS, counter_name, amount, path, SCHEMA_VERSION)


def unlocked_tower_pool(path: str = META_PROGRESSION_PATH) -> set[str]:
    """Every TOWER_TYPES name unlocked account-wide via META_UNLOCKS so
    far -- card_pool.draft_offer()'s default pool is this plus
    card_pool.STARTER_TOWERS (composed there, not here, for the same
    circular-import reason META_UNLOCKS above isn't built from
    card_pool.STARTER_TOWERS directly)."""
    state = load_meta_progression(path)
    return {unlock.tower_name for key, unlock in META_UNLOCKS.items() if key in state["unlocked"]}


def unlocked_relic_pool(path: str = META_PROGRESSION_PATH) -> set[str]:
    """Every relics.RELICS key unlocked account-wide via RELIC_META_UNLOCKS
    so far -- relics._default_relic_pool()'s own pool is every RELICS key
    *not* gated here, plus this (mirrors unlocked_tower_pool's shape)."""
    state = load_meta_progression(path)
    return {unlock.relic_key for key, unlock in RELIC_META_UNLOCKS.items() if key in state["unlocked"]}


def unlocked_level_pool(path: str = META_PROGRESSION_PATH) -> dict[int, Level]:
    """levels.LEVELS, minus whatever LEVEL_META_UNLOCKS entries haven't
    been unlocked yet -- unlike unlocked_tower_pool/unlocked_relic_pool
    (a small "what's been added" set a caller still has to combine with
    the rest of its own pool), this returns the whole ready-to-use pool
    directly: LEVEL_META_UNLOCKS gates only 2 of 15 levels today, so
    exposing "what's locked" and making every caller re-derive "everything
    else" would be the more awkward shape for the common case. Passed
    straight into run_map.generate_run_map's own level_pool param."""
    state = load_meta_progression(path)
    locked_ids = {
        unlock.level_id for key, unlock in LEVEL_META_UNLOCKS.items() if key not in state["unlocked"]
    }
    return {level_id: level for level_id, level in LEVELS.items() if level_id not in locked_ids}


def has_unlocked_third_relic_slot(path: str = META_PROGRESSION_PATH) -> bool:
    """Whether SHOP_META_UNLOCKS' own single entry has been crossed yet --
    unlike unlocked_tower_pool/unlocked_relic_pool/unlocked_level_pool,
    this gates a Shop *behavior* (shop.build_offer() offering a 3rd relic
    slot instead of RELIC_OFFER_COUNT's usual 2), not a specific content
    id, so a plain bool is the natural shape rather than a pool/set."""
    state = load_meta_progression(path)
    return "unlock_third_relic_slot" in state["unlocked"]
