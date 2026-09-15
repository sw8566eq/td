"""Floor-by-floor difficulty escalation for a roguelike run.

Composed as an *additional* factor alongside difficulty.DIFFICULTY_MODES'
own multipliers -- never replacing them, per difficulty.py's own "extra
factor" rule -- so a run on Hard is still harder than the same run on Easy
at every floor, just also escalating further the deeper it goes.

Not a fixed-key registry like DIFFICULTY_MODES: floor_index is unbounded
once the final floor's own endless tail is running (see waves.py's
_default_endless_wave, which already provides the escalation *within* one
floor once its authored waves run out). This is the *between-floors*
escalation layered on top of that, growing once per floor rather than once
per wave.

Rows 0-2 get an *early grace* discount instead of the growth above -- a
real full-run playtest ([[td-floor1-wave2-difficulty-spike]] in memory)
found the opposite of the intended "ease players in" shape: a brand-new
run's own opening floor was its least forgiving one, not its most. A
solo level-1 tower rarely finishes off even a base-HP Grunt in one pass,
and gold is only ever awarded on a kill (Game.update()) -- so a rough
first wave starves exactly the economy a player needs to afford a 3rd
tower before wave 2 (which nearly doubles enemy count on the levels this
was tested against) arrives. The grace discount directly targets both
halves of that spiral: cheaper-to-kill, slower enemies (more of a solo
tower's hits actually land a kill, so the economy doesn't stall) and a
starting-gold bump (affording a real opening board from floor 0, not
just from floor 2 onward). Tapers linearly to zero by EARLY_GRACE_ROWS --
every row from EARLY_GRACE_ROWS onward, and every Elite/boss multiplier
below, sees zero contribution *from grace itself* (EARLY_GRACE_ROWS
deliberately equals run_map.MIN_ELITE_ROW, so an Elite node -- never
reachable before that row -- can never overlap the grace window either).
starting_gold_multiplier keeps growing past that row regardless, on its
own flat per-floor rate independent of grace (see
_STARTING_GOLD_GROWTH_PER_FLOOR below) -- a harder, later floor should
still open with more to build a board from, not just the run's opening
floors, so unlike enemy_hp/speed_multiplier there's no "flat forever
after the grace window" plateau for this one field. This intentionally makes a
run's own floor 0 diverge from that same level played standalone in
Practice mode, unlike every other floor -- Practice is exactly "the raw
level, undiscounted," which is the point of it as a place to learn a
level's real difficulty; the grace period is specifically a run-openers-
only kindness.

Widened from an original rows-0-1 window (EARLY_GRACE_ROWS=2) after
following the intended arc all the way through: a player who clears the
graced floors, visits a Shop, and drafts a couple of relics/tower
unlocks still hit a wall immediately on reaching row 3 -- not a repeat
of the wave 1/2 problem above, but a second, structural one.
run_map._level_pool_for_row switches from single-lane to multi-lane
levels exactly at row 3, the same row grace used to end at -- so a
player's first fully-escalated fight and their first-ever multi-lane
fight (needing roughly double the tower investment, one defense per
lane, from the very first wave) used to land on the same row, with
reduced lives already spent clearing the graced floors and only one
floor's worth of shop currency banked. Extending the grace window (and
MIN_ELITE_ROW alongside it, see run_map.py's own comment) by one more
row doesn't remove that structural coincidence -- level tier and grace
still change on the same row, just row 3 instead of row 2 -- but it
does give a player one more graced floor's income, one more shop/event
opportunity, and a materially larger life cushion heading into it,
which a live playthrough confirmed for a 2-lane row-3 level (see
[[td-floor1-wave2-difficulty-spike]] again).

**Known open question, not yet resolved**: a live playthrough against a
*3*-lane row-3 level (three spawns merging toward two goals, wave 1
already 18 enemies vs. the 2-lane level's 13) still lost the run
outright across several attempted strategies, even with this wider
grace window and two Shop visits' worth of relics/tower unlocks banked
first. Whether that's this specific level's own wave-1 tuning, 3-lane
levels needing more than a 2-lane level does structurally, or genuinely
needing a further grace extension, is unconfirmed -- worth a dedicated
investigation before changing these constants again rather than
guessing at another bump.
"""

from dataclasses import dataclass

# Tuned so hp grows fastest -- that's what a deck of newly-drafted towers
# most needs to keep pace with as a run goes on -- while gold grows a
# little too, so a longer run's economy doesn't fall behind its own
# escalating threat, and speed grows slowest since a faster-moving enemy
# is harder to compensate for with towers alone than a tankier one.
_HP_GROWTH_PER_FLOOR = 0.12
_SPEED_GROWTH_PER_FLOOR = 0.02
_GOLD_GROWTH_PER_FLOOR = 0.05

# Same per-floor rate as _GOLD_GROWTH_PER_FLOOR above (a kept-independent
# constant, not a derived alias, matching this module's own "one dial per
# knob" style even where two dials start at the same value) -- but applied
# to the floor's own *starting* Economy rather than compounding across
# every kill within it, so its cumulative effect on any one floor is much
# smaller than enemy_gold_multiplier's own. A starting point, not yet
# headless-playtested: the goal is simply that a harder, later floor also
# hands the player a bigger opening board to face it with, on top of
# whatever the early-grace bonus below already gives rows 0-2.
_STARTING_GOLD_GROWTH_PER_FLOOR = 0.05

# Early grace (see this module's own docstring) -- rows 0-2 get an inverse
# discount instead of the growth above, tapering linearly to zero by
# EARLY_GRACE_ROWS (deliberately == run_map.MIN_ELITE_ROW, not imported
# from there to avoid a run_map <-> run_escalation import cycle -- both
# already independently encode "row 3 is where the run gets serious", so
# keeping them in sync by hand if either ever changes is a one-line check,
# not a real coordination burden). HP gets by far the largest discount,
# same "HP is the most cliff-inducing stat" lesson ELITE_HP_MULTIPLIER's
# own comment already documents -- a solo level-1 tower needs multiple
# hits to finish off even a base-hp Grunt, and every hit that doesn't
# land a kill is wasted (no partial-kill gold, no partial-kill anything).
# Speed gets a much smaller discount, same asymmetry the growth rates
# above already establish (a faster enemy is harder to compensate for
# with towers alone than a tankier one, so it's touched more gently in
# either direction). Gold is bumped up front rather than eased in like
# HP/speed are, deliberately overshooting where the growth curve above
# would otherwise put it at row 0-2 -- the whole point is affording a
# real opening board (3 starter towers, not 2) from the very first
# floor, not a gradual ramp toward that.
EARLY_GRACE_ROWS = 3
EARLY_GRACE_HP_DISCOUNT = 0.5
EARLY_GRACE_SPEED_DISCOUNT = 0.15
EARLY_GRACE_GOLD_BONUS = 0.5

# An Elite map node's own extra bump on top of whatever its row already
# escalates to (see apply_elite_multiplier below). Gold scales with hp (a
# tougher fight should pay out more in the fight itself too, on top of
# shop.ELITE_INCOME_MULTIPLIER's own bonus at the *floor-clear* level) --
# speed barely moves, since a faster-*and* tankier enemy compounds harder
# than either alone.
#
# ELITE_HP_MULTIPLIER tuned down from an original 1.5 after headless
# playtesting (a coverage-greedy simulated build, same level/row/starting
# resources for Combat vs Elite) showed 1.5 turning "harder floor" into
# "near-total wipe" even on a run's very first Elite-eligible floor --
# HP is by far the most cliff-inducing stat here (wave arrival is on a
# fixed clock regardless of whether earlier enemies are dead, so once
# per-enemy HP outpaces tower DPS enough to fall behind schedule, losses
# cascade fast), with a real, sharp playability cliff between 1.3 and 1.4
# multiplier for this game's wave/DPS balance -- 1.25 sits comfortably
# below it: a real fight (Elite clearly costs more lives than Combat at
# the same row -- roughly 30% of a fresh run's lives at row 0, escalating
# to a genuine near-wipe risk by the earliest row Elite can appear even
# with one Shop visit's worth of upgrades already bought), not a coin
# flip. ELITE_GOLD_MULTIPLIER stayed at its original value -- removing it
# in the same playtest made even a modest HP bump unsurvivable, since it's
# what lets a mid-fight economy snowball (more kills -> more gold -> more
# towers) keep pace with the added toughness at all.
ELITE_HP_MULTIPLIER = 1.25
ELITE_SPEED_MULTIPLIER = 1.1
ELITE_GOLD_MULTIPLIER = 1.5

# The map's own boss node's extra bump -- unambiguously the hardest fight in
# the run, tuned higher than Elite's own multiplier above on the same "gold
# scales with hp, speed barely moves" reasoning (a starting point, same as
# ELITE_HP_MULTIPLIER once was, pending a real headless-playtest tuning pass
# once FinalBossEnemy's reinforcement-summon mechanic is actually in play).
BOSS_HP_MULTIPLIER = 1.4
BOSS_SPEED_MULTIPLIER = 1.1
BOSS_GOLD_MULTIPLIER = 1.75


@dataclass(frozen=True)
class FloorEscalation:
    enemy_hp_multiplier: float = 1.0
    enemy_speed_multiplier: float = 1.0
    enemy_gold_multiplier: float = 1.0
    # Unlike the three enemy_* fields above, this scales the floor's own
    # starting Economy (Game._scaled_starting_gold), not anything
    # WaveManager reads. Two independent effects add into it: the
    # early-grace bonus (rows 0-2 only, tapering to zero) and a flat
    # per-floor growth that keeps going for every floor after that, so a
    # harder, later floor still opens with more to build a board from, not
    # just the run's opening floors -- see _STARTING_GOLD_GROWTH_PER_FLOOR
    # above. Elite/boss never touch it (see apply_elite_multiplier/
    # apply_boss_multiplier), since neither is about handing the player
    # more to prepare *with*, just a harder fight and a bigger payout
    # *from* it.
    starting_gold_multiplier: float = 1.0


def _early_grace_factor(floor_index):
    """1.0 at floor_index==0, tapering straight down to 0.0 at
    floor_index==EARLY_GRACE_ROWS and staying 0.0 (no effect at all) for
    every row after -- the one shared taper escalation_for_floor below
    scales each of its three grace constants by."""
    return max(0.0, 1.0 - floor_index / EARLY_GRACE_ROWS)


def escalation_for_floor(floor_index):
    """FloorEscalation for the floor_index-th floor of a run (0-based) --
    for a branching run this is the current node's *row*, not a linear
    floor count (see RunState.current_row), but the formula itself doesn't
    care which int it's handed. enemy_hp_multiplier/enemy_speed_multiplier
    fold in the early-grace discount (see this module's own docstring);
    enemy_gold_multiplier doesn't (kill-gold reward isn't the problem the
    grace period targets, starting gold is -- see starting_gold_multiplier
    below) and keeps growing exactly as it always has, even within the
    grace window. starting_gold_multiplier itself is two additive effects,
    not one: the early-grace bonus (fades to 0 by EARLY_GRACE_ROWS) plus a
    flat per-floor growth that runs for every floor, grace window included
    -- so the multiplier dips over rows 0-2 as the (much larger) grace
    bonus fades faster than the flat growth accumulates, bottoms out right
    at EARLY_GRACE_ROWS, and climbs from there for the rest of the run."""
    grace = _early_grace_factor(floor_index)
    return FloorEscalation(
        enemy_hp_multiplier=(1.0 + _HP_GROWTH_PER_FLOOR * floor_index) * (1.0 - EARLY_GRACE_HP_DISCOUNT * grace),
        enemy_speed_multiplier=(
            (1.0 + _SPEED_GROWTH_PER_FLOOR * floor_index) * (1.0 - EARLY_GRACE_SPEED_DISCOUNT * grace)
        ),
        enemy_gold_multiplier=1.0 + _GOLD_GROWTH_PER_FLOOR * floor_index,
        starting_gold_multiplier=(
            1.0 + EARLY_GRACE_GOLD_BONUS * grace + _STARTING_GOLD_GROWTH_PER_FLOOR * floor_index
        ),
    )


def apply_elite_multiplier(escalation):
    """Layers an Elite map node's own extra bump on top of an already-
    computed FloorEscalation -- multiplicative, the same "extra factor,
    never replacing" rule this module's own docstring states for
    difficulty.py/relics.py, so an Elite node at row 3 is harder than a
    plain Combat node at that same row, not just harder than row 0.
    starting_gold_multiplier passes through unchanged -- structurally a
    no-op in practice, since MIN_ELITE_ROW already keeps Elite off every
    row the early-grace discount ever touches, but carried through anyway
    so this stays a straightforward "copy every field, bump the three
    that mean anything here" rather than quietly dropping one."""
    return FloorEscalation(
        enemy_hp_multiplier=escalation.enemy_hp_multiplier * ELITE_HP_MULTIPLIER,
        enemy_speed_multiplier=escalation.enemy_speed_multiplier * ELITE_SPEED_MULTIPLIER,
        enemy_gold_multiplier=escalation.enemy_gold_multiplier * ELITE_GOLD_MULTIPLIER,
        starting_gold_multiplier=escalation.starting_gold_multiplier,
    )


def apply_boss_multiplier(escalation):
    """Layers the map's own boss node's extra bump on top of an already-
    computed FloorEscalation -- same shape as apply_elite_multiplier
    (multiplicative, an extra factor never replacing the row's own
    escalation), tuned higher so the boss is unambiguously the hardest
    fight in the run, harder than an Elite node would be at that same
    row. starting_gold_multiplier passes through unchanged, same reasoning
    as apply_elite_multiplier's own (the boss row is always past the
    grace window anyway, being the run's final row)."""
    return FloorEscalation(
        enemy_hp_multiplier=escalation.enemy_hp_multiplier * BOSS_HP_MULTIPLIER,
        enemy_speed_multiplier=escalation.enemy_speed_multiplier * BOSS_SPEED_MULTIPLIER,
        enemy_gold_multiplier=escalation.enemy_gold_multiplier * BOSS_GOLD_MULTIPLIER,
        starting_gold_multiplier=escalation.starting_gold_multiplier,
    )
