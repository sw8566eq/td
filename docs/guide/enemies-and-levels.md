# Enemies and levels

What you're fighting, and where.

[Back to the guide](README.md)

## Enemies

The regular species, before the boss variants: `GruntEnemy` (baseline), `ScoutEnemy` (fast, low HP -- also the one that gets shoved
back furthest by the knockback tower, since its knockback distance scales with the target's own
speed), `TankEnemy` (slow, high HP -- an easy target to keep in range, and frost's slow hits
especially hard on something already slow), `ShieldedEnemy` (a regenerating shield absorbs damage
before HP does, and starts regenerating again a few seconds after the last hit landed), `FlyingEnemy`
(airborne -- only a tower that can target flying enemies can hit it at all, Cannon, Knockback, Mortar, Brazier and the path traps can't), `SplitterEnemy` (on death, splits into two weaker children that
keep going from the same point along the route), and `HealerEnemy` (never fights, but heals every
other enemy within range every frame -- rewards focusing it down first). Deeper in a run, Sappers, Burrowers, Disruptors and Bulwarks join them -- see the Barricade entry in [Towers](towers.md#towers).

`BossEnemy` is a level's one-off final-wave heavyweight: dramatically more HP and gold reward, moving
at a deliberate crawl, but with two real mechanics of its own once it's taken enough punishment: it
**enrages** (a permanent speed boost) past 50% HP lost, and gets a one-time **armor phase** (reduced
incoming damage for a few seconds) past 80% HP lost -- both shown as a colored ring around it while
active. Every regular level's final wave puts exactly one boss in it.

The run map's own final row is always a dedicated **boss floor**, using one of two further
subclasses instead: `FinalBossEnemy` inherits the enrage/armor mechanics above and periodically
summons reinforcements while still alive; `FinalBossShieldedEnemy` inherits the same two mechanics
but periodically shields itself instead. Since a boss floor is always Endless, there's no "you
defeated the boss" victory screen -- the fight just keeps going, boss-free, once it's down (a toast
and an achievement mark the moment it happens).

## Levels

The built-in levels are mostly ordinary ones the run map's own nodes draw from (single-lane corridors
for early rows, branching/merging multi-lane maps for later ones), plus dedicated boss levels
reserved for the map's final row. Four are each built around one placement puzzle:
**The Coil** (a route that winds into the middle of the map and back out between its own legs),
**Killing Field** (one route passing the same open arena twice, eastbound then westbound),
**Saddleback Ridge** (two parallel lanes with a high-ground ridge between them, the only spot that
reaches both) and **Tributaries** (three spawns merging at two different points, the last one only
four tiles from the goal). `L` from the main menu opens a level browser listing every
built-in level plus any custom ones you've saved from the map editor -- each one shown with a small
thumbnail of its actual path (ground/path fill plus spawn/goal dots), not just its name. Nothing here
is locked: picking one is **Practice** (see [Modes and progression](modes-and-progression.md#practice-difficulty-endless-and-sandbox-modes)), which is deliberately decoupled from real
progress, so there's no reason to gate it. Saved levels persist across game sessions -- quit and
relaunch, and `L` still finds everything you'd saved before, straight off disk. More levels than fit
on screen at once scroll with the mouse wheel -- a "more below"/"more above" hint appears whenever
there's further to go.
