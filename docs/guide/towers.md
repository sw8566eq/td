# Towers

Every tower, how placement works, and the systems that make towers stronger during a run.

[Back to the guide](README.md)

## Towers

In a run you start with three towers and unlock the rest (see [Runs](runs.md#runs) and
[Meta-progression](modes-and-progression.md#meta-progression)); Practice mode and editor playtests always offer every tower. Once the build
menu holds more than nine, it wraps into two rows.

- **Basic** -- cheap, single-target, no special mechanic; its damage scales especially steeply with
  level so it stays worth building late-game, and it has a native chance to land a bigger crit.
- **Cannon** -- splash damage in a radius around impact; can't hit flying enemies.
- **Frost** -- slows its target on hit.
- **Knockback** -- splash damage plus a shove backward along the path (further for a faster enemy,
  since the shove is measured in seconds of its own progress, not a fixed distance); can't hit
  flying enemies either.
- **Lightning** -- hits its target, then arcs to the *nearest enemy it hasn't already hit this shot*
  within `chain_range` (short, since nothing else bounds the chain) of wherever the bolt currently is
  (not the tower), repeating for as long as there's an unvisited enemy left in range -- a dense
  enough cluster gets fully chained through, not capped at some fixed count. That's genuinely
  different from Cannon's splash: splash hits everyone within a radius of one impact point
  simultaneously, chain hits a *sequence* of individual enemies, each becoming the next jump's
  origin, so it can reach targets strung out along the path rather than just clustered together.
- **Sniper** -- very high damage, very long range, slow fire rate; also has a native Execute --
  bonus damage once a target's remaining HP drops low enough.
- **Poison** -- a light direct hit, but leaves a damage-over-time effect running afterward.
- **Beacon** -- near-zero direct damage; its real job is Marking whatever its always-on AoE flash
  touches, so every enemy caught in it takes bonus damage from *every* source, not just Beacon's own
  hits, for a few seconds.
- **Support** -- never attacks at all. Instead, every frame, it buffs every *other* tower within its
  own range (more damage, more range); several overlapping Support towers don't stack, they just
  take the strongest buff on offer, and a tower that walks out of every Support tower's range
  reverts immediately. Its own level-ups scale the buff strength rather than a nonexistent attack
  stat.
- **Beam** -- fires rapidly at one target and rewards staying locked onto it: each consecutive hit
  on the same, uninterrupted target ramps its damage further, capped at `max_ramp_multiplier`.
  Switching targets -- because a different enemy wandered into range, or the targeting mode picked
  someone new -- resets the ramp on the very next shot. Weaker than Basic until a target is
  committed to, the roster's best sustained single-target damage once it's fully ramped.
- **Overload Cannon** -- doesn't fire on a steady rhythm. Locks onto one target, charges for a few
  seconds, then unleashes one massive burst -- high ceiling, but a real risk: if the target dies or
  leaves range mid-charge, the whole charge is lost with no partial credit, and it starts over from
  nothing.
- **Mortar** -- huge range and a big, slow splash, but a **dead zone**: it can't hit anything within
  80px of itself (the red ring in its range preview), so it wants to sit back from the path. Ground
  enemies only. Unlocks after 10 floors cleared.
- **Barricade** -- a wall built on the path. Ground enemies that reach it stop and batter it until it
  breaks (no refund), taking a little thorns damage while they do; bosses smash it far faster and
  flyers pass over. Upgrading raises its hit points and fully repairs it. Unlocks after 12 floors.
  From Act 2 on, every run wave brings **Sappers** -- demolition troops that batter a Barricade five
  times as hard -- so a wall alone won't hold a deep run. A little deeper, **Burrowers** join them:
  they tunnel under the path, so Spike Traps, Tar Pits and Barricades can't touch them -- unless a
  Beacon Marks them, which drags them to the surface until the mark wears off. Two relics
  answer back: **Seismic Sensors** (traps can hit Burrowers) and **Booby-Trapped Walls** (a breaking
  Barricade explodes for its max hit points).
  Two more reinforcements punish lazy defenses. From Act 1's fifth row, **Disruptors** jam every
  tower within a short radius so it can't fire for 1.5s (Support and Barricades are immune), which
  punishes crowding every tower at one choke point. Long-range Snipers and Mortars outrange them.
  From Act 2, slow, tanky **Bulwarks** give the enemies around them 30% damage reduction, so kill
  them first. **Faraday Mesh** (shorter jams) and **Linebreaker** (weaker auras) answer back.
- **Spike Trap** / **Tar Pit** -- path traps, built on the path itself (see [Path traps](#path-traps)).
- **Harpoon** -- middling damage on a slow reload, but every hit **Grounds** a flyer for a few seconds:
  dragged down, it can be hit by ground-only towers (Cannon, Mortar, Knockback, traps, burning ground)
  and stopped by a Barricade. It starts on the **Flying** targeting mode, aiming at flyers that are
  still airborne first. Specializes into Deep Anchor (grounds far longer) or Reel In (hits also slow).
  The **Barbed Tethers** relic makes grounding last 60% longer. Unlocks after 6 floors cleared.
- **Brazier** -- a short-range flamethrower, and the only tower that attacks a **cone**: every shot
  washes flame over a 70-degree wedge pointed at its target, hitting every ground enemy inside for
  modest damage and setting it **Burning** (damage over time that stacks with Poison). Strong against
  dense ground swarms, weak against a lone tank, and it can't reach airborne flyers or Burrowers.
  Specializes into Wide Arc (a 110-degree cone, harder hits) or Blue Flame (hotter, longer burns). The
  **Pitch Oil** relic makes its burns 50% stronger. Unlocks after 8 floors cleared.
- **Siphon** -- a light direct hit, but converts a fraction of the damage it deals into battle gold --
  the only tower that generates economy from damage dealt rather than from kills.

## Tower placement

Each tile is cut into an 8x8 grid of small tiles (`settings.SUBTILES_PER_TILE`), and a tower's
required footprint is exactly one tile's worth of area -- 8x8 small tiles, unless a relic has
shrunk it for this floor -- but it can be *anchored* at any small tile, not just where a tile
boundary falls. Moving the build cursor shifts the footprint preview (a colored outline: white/valid,
red/blocked) in small-tile increments rather than snapping a whole tile at a time, so a tower can
straddle what used to be a tile boundary, tuck up against a path bend more precisely, or line up a
row of towers' ranges exactly. Two footprints can never overlap even partially, regardless of whether
their anchors happen to line up on any particular grid (`Grid.is_buildable`/`occupy`/`remove` in
`world/grid.py`), so this is purely about placement *precision* -- it doesn't let you fit more towers into
the same space.

The map itself renders each buildable tile as that same 8x8 mosaic of individually-drawn small tiles
with a thin, soft-edged gap between them (`Grid._build_background`, cached once per level rather than
redrawn every frame), so the placement grid is visible at a glance without being visually harsh. The
path renders as one unbroken tile -- no seams -- since it's never buildable anyway.

**High ground.** Some maps have raised tiles: lighter, with a bright top/left edge and a shadow on
the bottom/right. A tower with at least half its footprint on high ground gets **+20% range**
(`settings.HIGH_GROUND_RANGE_BONUS`). It stacks with range relics and Support auras, and a Support
tower up there also buffs a wider area. High ground sits inside bends and beside merges, so one tower
there can cover two stretches of path. The placement preview's ring already shows the bigger range
when you hover high ground, and a placed tower's panel says "High ground". Path traps never get the
bonus, and a moved tower gains or loses it at its new spot. The **Watchtowers** relic adds +15% damage
to high-ground towers.

## Tower levels & specialization

Every tower can be upgraded twice (level 1 -> 3) by clicking its "+cost" badge in-game, or the
sidebar's Upgrade button while it's pinned/hovered (`Tower.upgrade_badge_center`/
`contains_upgrade_badge` in `entities/tower.py` own the badge's position and hit-testing, so drawing and
clicking can never disagree about where it is). Each level multiplies `damage` and `range` by a
fixed amount (see `Tower.LEVEL_STAT_MULTIPLIERS` in `entities/tower.py`); the upgrade's gold cost is a
multiplier of that tower's base `cost` (`Tower.UPGRADE_COST_MULTIPLIERS`). This is generic on the
`Tower` base class, so new tower types get levels for free. A tower can opt its own special stat
into scaling too by extending `LEVEL_SCALED_STATS`, e.g. `LEVEL_SCALED_STATS =
Tower.LEVEL_SCALED_STATS + ("slow_duration",)` -- just make sure "bigger is better" actually holds
for that stat (it wouldn't for `FrostTower.slow_factor`, where lower is stronger).

A stat can also scale on its *own* curve instead of the shared one via
`LEVEL_STAT_MULTIPLIER_OVERRIDES`, e.g. `BasicTower` uses `{"damage": {1: 1.0, 2: 1.7, 3: 2.6}}` so
it hits much harder at level 2/3 than the generic curve would give it, while its `range` still scales
normally -- balance doesn't have to mean every tower's numbers grow at the same rate to feel worth
using.

Once a tower hits level 3, it can choose one of two named **specializations**
(`Tower.SPECIALIZATIONS`) instead of leveling further -- a one-time branching choice, separate from
`level` (`Tower.can_specialize`/`specialize()`). Every tower offers its own tuned pair playing off its
own mechanic -- Cannon's bigger-blast vs. heavier-payload, Frost's deeper-freeze vs. longer-lasting
slow, Lightning's longer chains vs. harder-hitting ones, Support's stronger buff vs. wider radius, and
so on; Basic and Sniper (which have no distinctive mechanic to key a specialization off) just get
their own names on bigger damage/range/fire-rate instead. A specific tower overrides
`SPECIALIZATIONS` on its own class to offer these.

## Tower modules

Every tower type has one **module** slot per run. Elite fights reward a module already paired with one
of your tower types ("Rapid Loader, for your Frost towers") in place of their potion -- take it, and
every tower of that type you build from then on carries it. Fitting a new module to a type replaces
the old one. Every Shop also has a **module stand** selling one paired module per visit. Ten modules: Long Barrel (+range), Rapid Loader (+fire rate), Heavy Payload (big damage,
slower), Cryo Coil (every hit slows), Venom Injector (every hit poisons), Targeting Chip (+crit),
Arc Coupler (hits can chain), Target Painter (every hit Marks), Recoil Plate (hits can knock back) and
Overclocked Core (a little of everything, less range). The sidebar shows a type's fitted module.

## Path traps

Two towers are **traps**, built *on* the path instead of beside it -- click any path tile and the trap
snaps to it. They have a short reach and only catch ground enemies (flyers pass over), but they're cheap
and sit exactly where enemies must walk: the **Spike Trap** (splash damage to whatever is on top of it)
and the **Tar Pit** (barely hurts, but bogs everything in its splash down). Both unlock through play
(4 and 7 floors cleared). They level, specialize, sell and earn veterancy like any tower. Three relics
build around them: Serrated Spikes (+40% Spike Trap damage), Clinging Tar (Tar Pit hits also Mark) and
Hair Trigger (traps strike 35% more often).

## Resonances

Some tower pairs work better together. A tower with its **partner** type within reach gets a named
bonus: **Superconductor** (Lightning near Frost: +25% damage), **Spotter** (Sniper near Beacon: +20%
range), **Fortified Battery** (Mortar near Barricade: +20% damage), **Sticky Spikes** (Spike Trap near Tar
Pit: +25% fire rate), **Shock and Awe** (Cannon near Knockback: +15% fire rate), **Toxic Cloud** (Poison
near Cannon: +20% range), **Power Relay** (Beam near Siphon: +15% damage), **Overwatch** (Basic near
Sniper: +10% damage), **Static Charge** (Overload Cannon near Lightning: +20% damage), **Deep Freeze** (Frost
near Tar Pit: +20% range), **Bounty Link** (Siphon near Sniper: +20% fire rate), **Thermal Shock** (Mortar
near Frost: +15% damage), **Grounded Barrage** (Mortar near Harpoon: +15% fire rate), **Anchor Line**
(Harpoon near Cannon: +20% range), **Firebreak** (Brazier near Barricade: +25% fire rate) and **Kindling**
(Brazier near Tar Pit: +20% damage). Hovering a build button shows what that tower pairs with (or boosts); while placing, purple lines
show which towers it would resonate with; a placed tower lists its active resonances. The **Harmonic
Tuning** relic doubles every resonance. The Field Manual has them all.

## Tower veterancy

Your towers learn on the job. Every **tower type** in a run earns experience from the kills its towers
make (towers that support rather than kill -- Support, Beacon -- earn a share of every kill as assists).
Experience is banked when a floor is cleared, and each type climbs four ranks -- **Blooded**,
**Seasoned**, **Veteran**, **Legendary** -- each one making every tower of that type you build from
then on stronger (the floor-cleared screen lists the experience each type earned): +6% damage per rank (Support: a stronger aura; Beacon: stronger marks). Gold pips on
a build button show its rank; the sidebar shows the rank, its bonus, and experience to the next one.
The Drill Instructor Event can train your crews too. Three relics build around it: Drill Sergeant (+50% experience), Battlefield Commission (every type
counts one rank higher) and Old Guard (Veteran-or-better types fire 15% faster).
