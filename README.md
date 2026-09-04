# Tower Defense

[![Tests](https://github.com/sw8566eq/td/actions/workflows/tests.yml/badge.svg)](https://github.com/sw8566eq/td/actions/workflows/tests.yml)

A roguelike deckbuilder tower defense game built with Python + Pygame.

You don't pick a level and beat it -- you start a **run**: a seeded sequence of floors, each one a
tower-defense map, played with a small pool of towers you grow by **drafting** a new card between
floors. Gold and lives carry from floor to floor, the enemies escalate as you descend, and losing
your last life ends the run for good. What you unlock along the way sticks around for the next one.

## Run it

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Pass `--unlimited-gold` to run with a debug flag that makes every purchase (placing, upgrading, or
specializing a tower) always succeed without actually spending gold -- the HUD shows
"Gold: unlimited" while it's on. (In-game **Sandbox mode**, below, is the player-reachable version
of this same idea, plus invulnerability.) Pass `--editor` to launch straight into the map editor
instead of the main menu (see "Map editor" below).

Don't want to set up Python at all? Grab a pre-built Linux binary from the
[Releases page](https://github.com/sw8566eq/td/releases) instead -- extract the tarball and run
`./td/td`. Keep the whole `td/` folder together (it bundles its own Python runtime and assets next
to the executable); progress, achievements, settings, and saved runs are all written there too, so
moving just the `td` binary out on its own would leave those behind.

## Runs

Press any unbound key at the main menu to start a run. That samples a **floor sequence** -- six
built-in levels drawn from the eleven available, kept in ascending order so they escalate
(`run_floors.py`) -- and hands you a starter pool of three towers: Basic, Cannon, and Frost
(`card_pool.STARTER_TOWERS`). The build menu shows only those three; the other six towers exist,
but you can't build them yet.

Clear a floor's waves and you get a **Floor Cleared** screen with that floor's tower results, then
a **draft**: three cards, pick one. Usually that's a new tower added to the run's pool for every
remaining floor. Every other floor it's a **relic** instead (`relics.py`) -- a passive, run-wide
modifier like "+20 gold at the start of every floor" or "+3 extra lives for this run." Picking a
card loads the next floor: fresh grid, fresh towers to place, but your gold and lives carry over.

Three things make each floor harder than the last:

- The levels themselves get more complex as the sequence ascends.
- A per-floor **escalation** multiplies enemy HP, speed, and gold reward on top of your difficulty
  setting rather than replacing it (`run_escalation.py`) -- floor 0 is exactly 1.0x, so a run's
  first floor plays identically to that level on its own.
- The **last** floor loads in Endless mode from the start, so its waves never run out.

That last point is the point: there is no "you won the run" screen. A run ends only by
**permadeath** -- losing your last life -- which records the run (`run_history.py`, keyed by seed,
keeping your best result) and banks its progress toward the next one.

**Meta-progression** is what carries across runs. Six of the nine towers are locked account-wide
behind lifetime counters (`meta_progression.py`): clear 1/3/5 total floors to unlock Knockback,
Poison, and Lightning; play 1/2 runs for Sniper and Support; reach the endless final floor once for
Beam. An unlocked tower joins the pool the draft can offer from -- it doesn't start in your hand,
it just becomes a card you might be dealt. A toast pops up in-game the moment you unlock one.

`D` from the menu starts the **Daily Run** -- the same thing, seeded off today's UTC date, so
everyone gets the identical floor sequence and identical draft offers today. Its difficulty is
pinned to Normal regardless of your own setting, so scores are comparable.

## Controls

From the main **menu**: press any other key to start a new run (see "Runs" above), `E` opens the
map editor, `L` opens the level browser to practice a single floor, `S` opens Settings, `A` opens
your Achievements, `H` opens an in-game How to Play screen (a condensed version of this section),
`D` starts today's Daily Run, and `C` (shown only when one exists) continues a saved in-progress
run.

While **playing**: click a tower button in the bottom bar, then click a buildable tile to place it
-- the sidebar on the right shows that tower type's stats while it's selected; right-click at any
time to clear the current selection without placing anything. A tower's required footprint is one
tile's worth of space, but it isn't locked to the tile grid -- see "Tower placement" below for how
that works and what the footprint outline that follows your cursor is showing you.

Hover any placed tower to see its live stats and range in the sidebar; **click** it instead and
that stays pinned open even once the mouse moves away, until you click a different tower, pick a
build-menu type, or click empty ground with nothing selected. The pinned/hovered panel shows a
**Targeting** row (click to cycle first/last/strongest/closest -- which in-range enemy the tower
actually shoots at), **Upgrade** and **Sell** buttons (in addition to the small "+cost" badge in
the tower's tile corner, which still works too), and at max level, Upgrade is replaced by two
**Specialize** buttons -- see "Tower levels & specialization" below. Selling refunds a fraction of
everything spent on that tower (`settings.SELL_REFUND_FRACTION`) and frees its space immediately.

The HUD shows a countdown to the next wave and a button (bottom-right) that reads "Start" before
the first wave -- it waits for you rather than auto-starting, so you get a beat to place towers
first -- and "Skip" for every wave after that, forcing the between-wave delay to end early. `Space`
does the same thing as clicking it. A second button next to it cycles the simulation speed
(`1x`/`2x`/`3x`, or press `1`/`2`/`3` directly) -- real time still drives the frame rate, only the
simulated world speeds up.

`P` or `Esc` opens the pause menu; the same two keys close it again, `R` restarts the current
level, `S` (shown only between waves) saves the run to disk and returns to the menu -- see "Save &
resume" below -- `Q` quits. Playing a level you're playtesting from the map editor adds one more
option there: `E` stops the run and takes you straight back to the editor, paint buffer untouched
-- not offered on a built-in level, which has no editor session to return to.

On the **Floor Cleared** screen, any key moves on to the draft; on the **draft** screen, click one
of the three cards to take it and load the next floor. `Esc` quits from either, same as it does
from the main menu, game-over, or victory screens (there's no pause menu to open on any of those).
`R` restarts from the game-over screen, and -- from the victory screen a practice or playtested
level can still reach -- advances to the next level if there is one, otherwise replays the one you
just won.

The level browser (`L`) has two extra toggles, both reset every time you reopen it and combinable
with each other: `V` arms **Endless** (Survival) mode for whichever level you pick next -- see
"Practice, Difficulty, Endless, and Sandbox modes" below for what always applies regardless.

## Testing

Run the test suite with `pytest` (from the venv) -- 1060+ tests covering every module. The
`Game`-level tests are split three ways by concern: `tests/test_game.py` (state machine, click/key
handling, update loop, rendering), `tests/test_run.py` (the whole run lifecycle -- floors, drafts,
relics, permadeath, meta-progression, save/resume, Daily Run, Practice), and
`tests/test_game_editor.py` (the editor, wave editor, and level browser screens). All three share
fixtures and helpers from `tests/conftest.py`, which is also where the SDL dummy video driver gets
forced before pygame is imported -- so `pytest` runs headless with no extra setup, in CI or
anywhere else. (`tests/test_assets.py` stands alone and does its own.)

## Art

No art pack is bundled yet -- every sprite renders as a simple colored placeholder shape (see
`assets.py`). Drop a CC0 pixel-art pack's PNGs into `assets/towers/`, `assets/enemies/`,
`assets/tiles/`, `assets/projectiles/` using the filenames listed in `SPRITE_MANIFEST` (in
`assets.py`) and the real art will appear automatically -- no code changes needed. If the pack uses
different filenames, just edit the path strings in that manifest.

## Tower placement

Each tile is cut into an 8x8 grid of small tiles (`settings.SUBTILES_PER_TILE`), and a tower's
required footprint is exactly one tile's worth of area -- 8x8 small tiles -- but it can be
*anchored* at any small tile, not just where a tile boundary falls. Moving the build cursor shifts
the footprint preview (a colored outline: white/valid, red/blocked) in small-tile increments
rather than snapping a whole tile at a time, so a tower can straddle what used to be a tile
boundary, tuck up against a path bend more precisely, or line up a row of towers' ranges exactly.
Two footprints can never overlap even partially, regardless of whether their anchors happen to
line up on any particular grid (`Grid.is_buildable`/`occupy`/`remove` in `grid.py`), so this is
purely about placement *precision* -- it doesn't let you fit more towers into the same space.

The map itself renders each buildable tile as that same 8x8 mosaic of individually-drawn small
tiles with a thin, soft-edged gap between them (`Grid._build_background`, cached once per level
rather than redrawn every frame), so the placement grid is visible at a glance without being
visually harsh. The path renders as one unbroken tile -- no seams -- since it's never buildable
anyway.

## Towers

Nine so far. In a run you start with three of them and draft the rest (see "Runs" above); Practice
mode and editor playtests always offer all nine.

- **Basic** -- cheap, single-target, no special mechanic; its damage scales especially steeply with
  level so it stays worth building late-game.
- **Cannon** -- splash damage in a radius around impact; can't hit flying enemies.
- **Frost** -- slows its target on hit.
- **Knockback** -- splash damage plus a shove backward along the path (further for a faster
  enemy, since the shove is measured in seconds of its own progress, not a fixed distance); can't
  hit flying enemies either.
- **Lightning** -- hits its target, then arcs to the *nearest enemy it hasn't already hit this
  shot* within `chain_range` (50px -- short, since nothing else bounds the chain) of wherever the
  bolt currently is (not the tower), repeating for as long as there's an unvisited enemy left in
  range -- `max_chain_targets` is `float("inf")`, so a dense enough cluster gets fully chained
  through, not capped at some fixed count. That's genuinely different from Cannon's splash: splash
  hits everyone within a radius of one impact point simultaneously, chain hits a *sequence* of
  individual enemies, each becoming the next jump's origin, so it can reach targets strung out
  along the path rather than just clustered together. See `Projectile._resolve_chain()` in
  `projectile.py`.
- **Sniper** -- very high damage, very long range, slow fire rate; a pure glass-cannon pick with no
  special mechanic.
- **Poison** -- a light direct hit, but leaves a damage-over-time effect running afterward.
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

## Tower levels & specialization

Every tower can be upgraded twice (level 1 -> 3) by clicking its "+cost" badge in-game, or the
sidebar's Upgrade button while it's pinned/hovered (`Tower.upgrade_badge_center`/
`contains_upgrade_badge` in `tower.py` own the badge's position and hit-testing, so drawing and
clicking can never disagree about where it is). Each level multiplies `damage` and `range` by a
fixed amount (see `Tower.LEVEL_STAT_MULTIPLIERS` in `tower.py`); the upgrade's gold cost is a
multiplier of that tower's base `cost` (`Tower.UPGRADE_COST_MULTIPLIERS`). This is generic on the
`Tower` base class, so new tower types get levels for free. A tower can opt its own special stat
into scaling too by extending `LEVEL_SCALED_STATS`, e.g. `LEVEL_SCALED_STATS =
Tower.LEVEL_SCALED_STATS + ("slow_duration",)` -- just make sure "bigger is better" actually holds
for that stat (it wouldn't for `FrostTower.slow_factor`, where lower is stronger).

A stat can also scale on its *own* curve instead of the shared one via
`LEVEL_STAT_MULTIPLIER_OVERRIDES`, e.g. `BasicTower` uses
`{"damage": {1: 1.0, 2: 1.7, 3: 2.6}}` so it hits much harder at level 2/3
than the generic curve would give it (10 -> 17 -> 26, vs. the ~10 -> 13.5
-> 18 the shared curve produces) while its `range` still scales normally
-- balance doesn't have to mean every tower's numbers grow at the same
rate to feel worth using.

Once a tower hits level 3, it can choose one of two named **specializations**
(`Tower.SPECIALIZATIONS`) instead of leveling further -- a one-time branching choice, separate from
`level` (`Tower.can_specialize`/`specialize()`). Every tower now offers its own tuned pair playing
off its own mechanic -- Cannon's bigger-blast vs. heavier-payload, Frost's deeper-freeze vs.
longer-lasting slow, Lightning's longer chains vs. harder-hitting ones, Support's stronger buff vs.
wider radius, and so on; Basic and Sniper (which have no distinctive mechanic to key a
specialization off) just get their own names on bigger damage/range/fire-rate instead. A specific
tower overrides `SPECIALIZATIONS` on its own class to offer these; the numbers are still rough
starting points, not tuned balance.

Selling a tower (the sidebar's Sell button) refunds `settings.SELL_REFUND_FRACTION` of
`Tower.total_invested` -- everything spent placing, upgrading, *and* specializing it, not just the
base cost -- and immediately frees its footprint.

## Layout

The window is `PLAY_WIDTH` (the grid + the HUD bar beneath it) plus a
fixed `PANEL_WIDTH` stats sidebar on the right (both in `settings.py`) --
the window was simply grown to fit the sidebar rather than shrinking the
grid. `ui.draw_tower_stats_panel()` reads a tower class's plain stats
(`cost`/`damage`/`range`/`fire_rate`) plus its `EXTRA_STATS` (see below)
to render the panel, so it needs no changes for new tower types. Its Upgrade/Specialize/Sell
buttons sit at fixed positions in the panel (`ui.py`'s `ACTION_AREA_TOP`/`SELL_BUTTON_TOP`)
regardless of which tower's stats are shown above them.

## Enemies

Six species: `GruntEnemy` (baseline), `ScoutEnemy` (fast, low HP -- also the one that gets shoved
back furthest by the knockback tower, since its knockback distance scales with the target's own
speed), `TankEnemy` (slow, high HP -- an easy target to keep in range, and frost's slow hits
especially hard on something already slow), `ShieldedEnemy` (a regenerating shield absorbs damage
before HP does, and starts regenerating again a few seconds after the last hit landed),
`FlyingEnemy` (airborne -- only a tower that can target flying enemies can hit it at all, which is
every current tower except Cannon and Knockback), and `BossEnemy` -- a level's one-off final-wave
heavyweight: dramatically more HP and gold reward, moving at a deliberate crawl, but with two real
mechanics of its own once it's taken enough punishment: it **enrages** (a permanent speed boost)
past 50% HP lost, and gets a one-time **armor phase** (reduced incoming damage for a few seconds)
past 80% HP lost -- both shown as a colored ring around it while active. Each level's `wave_specs`
introduces the regular species gradually and puts exactly one boss in the final wave -- see
`test_every_levels_final_wave_includes_a_boss` in `tests/test_levels.py` for that as an enforced
invariant, not just a convention.

## Levels

Eleven built in -- collectively, the pool a run's floors are drawn from. Six are single-lane
corridors of increasing switchback complexity (`LEVELS[1]`-`[5]`, `[10]`), and five branch and/or
merge: `LEVELS[6]` ("Confluence", two spawns merging into one goal), `LEVELS[7]` ("Forked River",
one spawn branching into two goals), `LEVELS[8]` ("Twin Confluence", two spawns merge then branch
again into two goals), `LEVELS[9]` ("Triple Crossing", three spawns merging into one goal), and
`LEVELS[11]` ("Grand Delta"). The ids are an authored difficulty ramp, which is why a run samples
its floors *without* reordering them (`run_floors.py`) -- a shuffle would occasionally front-load a
hard map onto floor 1.

`L` from the main menu opens a level browser listing every built-in level plus any custom ones
you've saved from the map editor -- each one shown with a small thumbnail of its actual path
(ground/path fill plus spawn/goal dots), not just its name. Nothing here is locked: picking one is
**Practice** (see below), which is deliberately decoupled from real progress, so there's no reason
to gate it. Saved levels persist across game sessions -- quit and relaunch, and `L` still finds
everything you'd saved before, straight off disk. More levels than fit on screen at once scroll
with the mouse wheel -- a "more below" hint appears whenever there's further to go.

## Practice, Difficulty, Endless, and Sandbox modes

**Practice** is what the level browser (`L`) does: play any single built-in or custom level on its
own, outside a run. It always loads in Sandbox mode (below) -- unlimited gold, invulnerable, all
nine towers available -- because it's for trying things out, not for earning anything. Nothing you
do in Practice touches your progress, achievements, or meta-progression unlocks. Real progress
comes from clearing run floors.

**Difficulty** (`S` from the main menu -> Settings) picks one of Easy/Normal/Hard -- a bundle of
multipliers on enemy HP/speed/gold reward and starting gold/lives (`difficulty.py`). Normal is
every multiplier at 1.0, i.e. exactly the original numbers -- see "Settings" below for how your
choice persists. A run snapshots your setting when it starts, so changing it mid-run doesn't move
the goalposts partway through; the per-floor escalation (see "Runs") stacks on top of it rather
than replacing it.

**Endless (Survival) mode** -- armed with `V` from the level browser before picking a level -- keeps
generating new waves once a level's own last wave clears instead of ending the level: each new wave
takes the previous one's enemy counts and bumps them up further, so it escalates without limit
rather than plateauing. There's no way to "win" an endless run; it plays until you run out of
lives.

**Sandbox mode** gives you unlimited gold and makes you invulnerable (a leaked enemy never
actually costs a life), for freely experimenting with tower combinations. A sandbox win/clear
doesn't count toward progress, achievements, or meta-progression unlocks, since it isn't a real
test of anything. Practice always uses it -- unconditionally, not as a toggle -- which is exactly
why Practice earns nothing.

## Settings

`S` from the main menu opens a Settings screen for **Fullscreen** (toggle) and **Difficulty**
(Easy/Normal/Hard, see above) -- both take effect and save to disk immediately, so they're still
set the same way the next time you launch the game.

## Post-level results

The Floor Cleared, Victory, and Game Over screens all show a compact table of every tower you built
on that floor/level (including ones you later sold), sorted by damage dealt -- damage, kills, and
accuracy per tower, so you can see which of your towers actually carried it. A Support tower shows
`--` for accuracy rather than a misleading 0%, since it never fires a shot.

## Achievements

`A` from the main menu opens an Achievements screen listing all ten you can unlock -- landing your
first kill, racking up 100/1000 kills total, placing your first tower, maxing one out, choosing
your first specialization, clearing your first level (and eventually every built-in one), and
clearing waves of enemies over time. Progress toward a still-locked achievement is shown right
there (e.g. "37/100"), and a small toast pops up in-game the moment you unlock a new one. None of
this counts while playing in Sandbox mode, which includes all of Practice.

Achievements are deliberately separate from the **meta-progression** unlocks described under
"Runs": achievements are trophies with no gameplay consequence (`achievements.py`), meta-progression
unlocks change what a future run's draft can offer you (`meta_progression.py`). They're tracked in
separate files and separate registries, so one number never has to serve both purposes. Clearing
floors feeds both: "Campaign Complete" wants every built-in level cleared at least once, counted
across however many runs it takes (`progress.py` keeps that per-level tally -- your best lives
remaining on each is recorded alongside it, kept for a future summary screen to show, though
nothing displays it yet).

## Save & resume

The pause menu's `S` (shown only between waves, not mid-wave) saves what you're playing -- the
level, gold, lives, wave progress, every placed tower's level/specialization/targeting mode, and
whether it's an endless or sandbox session -- to disk and returns you to the main menu, which now
shows a `C` option to pick it back up exactly where you left off, even after quitting and
relaunching the game entirely. If a run is active, the run itself is saved too: its seed, floor
sequence and position, drafted tower pool, and relics, so you resume on the same floor with the
same deck. Resuming never re-spends the gold you already spent on upgrades, and picks up right
where the *saved* difficulty was, even if you've changed the setting since. Playing that resumed
session through to its own conclusion clears the save, so "Continue" only ever offers something
genuinely still in progress -- there's only ever one save slot.

Saving is only possible between waves, which is what keeps this simple: there's no live enemy or
projectile state to serialize, so a resumed run always restarts from a clean wave boundary.

## Map editor

`E` from the main menu (or `python main.py --editor`) opens a freeform
tile-paint editor: drag to paint or erase path tiles like a pixel brush,
and use the Spawn/Goal tools to mark where enemies start and where reaching
one costs a life. A path can **branch** (one lane fanning out into several)
and **merge** (several spawns converging on shared lanes toward a goal) --
junctions are detected automatically from the painted shape (any tile with
3+ path-neighbors), you never have to declare one yourself. Enemies pick a
direction at each branch point at random (evenly, by default).

The one rule the brush enforces is that the path can't loop back on itself
-- a lane splitting and later reconnecting downstream is a closed loop,
which is rejected the same as a literal roundabout would be. The sidebar
shows live feedback (in red) on whatever's wrong -- disconnected cells, a
missing spawn/goal, a loop -- and turns green once the path is valid, at
which point **Edit Waves** becomes clickable.

Painting has a few more quality-of-life tools alongside the freeform brush: **Undo**/**Redo**
buttons (or `Ctrl+Z`/`Ctrl+Y`) step back/forward one whole paint stroke at a time, not one tile.
**Line**, **Rect**, and **Select** tools let you drag out a straight run, a filled rectangle, or a
selection instead of freehand painting every tile (a freshly-stamped rectangle starts out as a
closed loop -- erase one edge tile to open it into a valid path). **Copy**/**Paste** duplicates
whatever's in your current selection -- path, spawns, and goals -- somewhere else on the map; a
pasted spawn doesn't carry over any wave data, since it's a genuinely new spawn point, not a copy
of the original's.

**Load Map...**, also in the sidebar, reopens a previously saved custom
level for further editing -- it's the same level browser `L` uses, just
filtered to only your saved custom levels (a built-in level has no file to
reopen) and, instead of starting to play whichever one you pick, it loads
that map's path *and* waves straight into the editor in place of whatever
was there, ready to keep painting or rebalancing. There's no prompt about
unsaved changes -- same as Playtest and Save elsewhere in the editor never
asking either -- so save first if you want to keep what you were working on.

That opens the wave editor: numbered tabs across the bottom select which
wave you're editing, with **+**/**-** tabs to add or remove one (there's
always at least one, shared by every spawn -- the whole level counts
"Wave X of Y" together). Within a wave, **+**/**-** next to each species in
the sidebar sets how many of that type spawn -- but only *from whichever
spawn is currently selected*. If your path has more than one spawn point,
**click a spawn's numbered marker** in the map preview to switch to it --
each spawn keeps its own independent unit counts per wave, so one spawn can
send a wave of grunts while another sends tanks, or sits that wave out
entirely. A wave still needs at least one unit from *some* spawn before you
can move on. **Playtest** loads the level you're editing immediately,
without saving; **Save** writes it to `custom_levels/` (as JSON, via
`persistence.py`) under a name slugged from the level's name -- the
sidebar shows exactly where afterward -- and `L`'s level browser will find
it from then on, this session or a future one. Since a saved level is a
self-contained JSON file with nothing player-specific in it, sharing one
with another player is as simple as sending them the file and having them
drop it into their own `custom_levels/`.

Spawns stay synchronized during play: the 1st enemy out of every spawn point
in a wave emerges at the same moment, then the 2nd from every spawn that
still has one, and so on -- not one spawn's whole queue emptying before the
next spawn's even starts. A spawn with fewer enemies queued for that wave
just stops contributing once its own queue runs out, without holding the
others back. Within one spawn, its own species still go out together, one
type fully before the next -- interleaving species order within a single
spawn's queue is a possible future refinement.

## Adding content

The game is built so new content is additive -- a new subclass or registry
entry, not a change to the systems that already work.

- **New tower**: subclass `Tower` in `tower.py`, set its stats
  (`cost`/`range`/`damage`/`fire_rate`/`sprite_name`) and implement
  `create_projectile()`, then add it to `TOWER_TYPES`. It shows up in the
  build menu automatically. If it has its own special mechanic (splash,
  slow, knockback, ...), list it in `EXTRA_STATS` as
  `(label, attribute_name, format_function)` and it shows up in the stats
  panel automatically too. Override `SPECIALIZATIONS` with your own two named,
  mechanic-specific level-3 choices -- see how every current tower does this in `tower.py` --
  rather than leaving it on the generic Power/Precision placeholder.
- **New enemy**: subclass `Enemy` in `enemy.py`, override its stats
  (`base_hp`, `base_speed`, `base_reward`, etc. -- or `update()`/
  `take_damage()` too, for something like a shielded unit or `BossEnemy`'s enrage/armor phase),
  then add it to `ENEMY_TYPES` under a short name. Reference that name from a level's
  `wave_specs` to use it.
- **New built-in level**: add a `Level(...)` entry to `LEVELS` in `levels.py` with its own path
  (`path_cells`/`spawn_cells`/`goal_cells` -- `pathing.path_cells_from_corners()` turns a terse
  ordered corner list into `path_cells` for a simple single-lane route, same as levels 1-5; a
  branching/merging level like 6-9 unions several corner lists together instead -- see
  `_multi_lane_level()` in `levels.py`), wave composition (`wave_specs`, a list of
  `{spawn_cell: {enemy_type_name: count}}` dicts -- one per wave, each spawn's own composition
  independent of any other spawn's -- hand-authored, or via `generate_default_waves()`/
  `_single_spawn_waves()` for the common single-spawn case), and starting gold/lives. `Grid`,
  `WaveManager`, and `Game` all consume whichever level is active generically, so this needs no
  other changes -- registering it is also what makes it reachable: it joins the pool a run's floors
  are drawn from (`run_floors.py`), and it's listed in `L`'s level browser for Practice. Put it at
  the id its difficulty belongs at, since the ids are the ramp a run ascends. (All levels currently
  share the same map size, set in `settings.py` -- only the path/waves differ.)
  Give its final wave a `"boss": 1` entry to match every other level -- enforced by
  `tests/test_levels.py::test_every_levels_final_wave_includes_a_boss`. A player-made level doesn't
  need a registry entry at all -- see "Map editor" above.
- **New achievement**: add an `Achievement(...)` entry to `ACHIEVEMENTS` in `achievements.py`,
  keyed off one of the existing cumulative counters (`kills`, `towers_built`, `towers_maxed`,
  `towers_specialized`, `levels_cleared`, `waves_survived`) or a new one -- a new counter just needs
  one `Game._record_achievement("your_counter_name")` call added at whatever point in `game.py` the
  event actually happens.
- **New relic**: add a `Relic(...)` entry to `RELICS` in `relics.py` with whichever modifier fields
  it sets (`gold_per_floor_bonus`, `starting_gold_multiplier`, `starting_lives_bonus`,
  `enemy_gold_multiplier`). `compose_relic_modifiers()` folds every held relic together and
  `Game._load_floor` composes the result into the floor's `Economy`/`WaveManager` alongside
  difficulty and escalation, so nothing else needs changing. Relics aren't unlock-gated -- every
  registered one is eligible in any run. Write the description to say what it *actually* does: a
  `starting_*` field only ever affects floor 0, since every later floor carries gold and lives
  forward instead of reconstructing them.
- **New tower unlock**: add a `MetaUnlock(...)` entry to `META_UNLOCKS` in `meta_progression.py`
  pairing a `TOWER_TYPES` name with a threshold on one of the lifetime run counters
  (`total_floors_cleared`, `runs_played`, `runs_reached_endless`). Every tower not in
  `card_pool.STARTER_TOWERS` should have exactly one entry, so a new tower needs one here too or it
  can never be drafted.
