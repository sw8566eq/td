# Tower Defense

[![Tests](https://github.com/sw8566eq/td/actions/workflows/tests.yml/badge.svg)](https://github.com/sw8566eq/td/actions/workflows/tests.yml)

A roguelike deckbuilder tower defense game built with Python + Pygame.

You don't pick a level and beat it -- you start a **run**: a seeded, fully-visible branching map of
floors (combat fights, a shop, random events, rest stops, treasure, and a final boss), played with a
small pool of towers you grow by **drafting** cards as you go. Lives carry from floor to floor; gold
resets fresh every floor, but whatever you don't spend converts into a second, persistent currency you
spend at the Shop. Enemies escalate as you descend, and losing your last life ends the run for good.
What you unlock along the way -- towers, relics, levels -- sticks around for every run after it.

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

Press any unbound key at the main menu to start a run. That generates a **branching map** -- six
rows of nodes, shown to you in full from the start, no fog of war -- and hands you a starter pool of
three towers: Basic, Cannon, and Frost (`card_pool.STARTER_TOWERS`). The build menu shows only those
three at first; the rest exist but you can't build them until you've unlocked them (see
"Meta-progression" below).

Row 0 is always three Combat choices -- your very first click always starts a real fight. From
there, click any node connected to the one you just cleared to move on. Most rows are a mix of six
node types:

- **Combat** -- a normal tower-defense floor.
- **Elite** -- a harder floor that pays out more shop currency on clear. Risk/reward, not just
  "harder for its own sake."
- **Shop** -- spend shop currency on towers and relics (see "The Shop and two currencies" below).
- **Event** -- a short prompt with 2-3 honestly-described options (gain currency, lose a relic for a
  bigger reward, unlock a tower early, heal, ...) -- never a hidden-odds gamble.
- **Rest** -- heals some lives back, no choice involved.
- **Treasure** -- a guaranteed shop-currency payout plus a guaranteed relic pick.

The final row is always a single **Boss** node. It loads in Endless mode from the very start, so its
waves never run out and there's no "you won the run" screen -- while the boss itself is still alive
it periodically reinforces (or, on the other boss level, shields itself), and defeating it just means
the fight keeps going, now boss-free. A run ends only by **permadeath** -- losing your last life --
which records the run (`run_history.py`, keyed by seed, keeping your best result) and banks its
progress toward the next one.

Clearing a Combat or Elite floor's waves shows a **Floor Cleared** results screen, then returns you
to the map to pick your next node. The Boss floor never reaches that screen -- it's Endless from the
start, so its waves never technically finish (see above); every other node type resolves in its own
screen instead and returns you to the map the same way.

Three things make each floor harder than the last: the level itself gets more complex the deeper the
row, a per-floor **escalation** multiplies enemy HP/speed/gold reward on top of your difficulty
setting (`run_escalation.py` -- floor 0 is exactly 1.0x, so a run's first floor plays identically to
that level in Practice), and an Elite/Boss node layers a further bump of its own on top of that.

`D` from the menu starts the **Daily Run** -- the same thing, seeded off today's UTC date, so
everyone gets the identical map, offers, and events today. Its difficulty is pinned to Normal
regardless of your own setting, so scores are comparable.

## The Shop and two currencies

A run tracks two currencies that never convert into each other. **Battle gold** is what places,
upgrades, and sells towers mid-floor -- it resets fresh at the start of every floor rather than
carrying forward, so hoarding it into a fight you've already won is wasted... unless you convert it:
clearing a floor turns whatever gold you still had left into **shop currency**, which persists for
the whole run and is the only thing that buys anything at a Shop node.

A Shop visit offers a small mix of tower cards and relic cards together; buy as many (or as few) as
you like, then click Continue. Prices go up a little with every purchase made in that same visit, so
there's a real choice in what to prioritize, not just "buy everything eventually."

## Relics

A relic is a passive, run-wide modifier drafted from Shop/Treasure/Event nodes -- 61 of them as of
this writing, everything from "+20 gold at the start of every floor" to relics that make one specific
tower's own signature mechanic (Basic's crit, Sniper's execute, Frost's slow, Poison's DoT,
Knockback's shove) hit harder, and a handful of combo relics that reward running two towers' mechanics
together (bonus damage against an enemy that's simultaneously Marked *and* Slowed, say). Almost none
of them are gated behind an account-wide unlock -- see `relics.py` for the full registry and
"Meta-progression" below for the handful that are. Press `R` while playing a run floor to bring up a
read-only overlay of every relic you're currently holding.

## Controls

From the main **menu**: press any other key to start a new run (see "Runs" above), `E` opens the
map editor, `L` opens the level browser to practice a single floor, `S` opens Settings, `A` opens
your Achievements, `H` opens an in-game How to Play screen, `D` starts today's Daily Run, `B` opens
the Credits screen, and `C` (shown only when one exists) continues a saved in-progress run.

On the **map** screen, click any highlighted node to enter it; a legend explains what each node
color means, and hovering a node shows a tooltip with its specific details (which level, how much a
Rest heals, and so on).

While **playing** a floor: click a tower button in the bottom bar, then click a buildable tile to
place it -- the sidebar on the right shows that tower type's stats while it's selected; right-click
at any time to clear the current selection without placing anything. A tower's required footprint is
one tile's worth of space, but it isn't locked to the tile grid -- see "Tower placement" below for
how that works.

Hover any placed tower to see its live stats and range in the sidebar; **click** it instead and that
stays pinned open even once the mouse moves away, until you click a different tower, pick a
build-menu type, or click empty ground with nothing selected. The pinned/hovered panel shows a
**Targeting** row (click to cycle first/last/strongest/closest -- which in-range enemy the tower
actually shoots at), **Upgrade** and **Sell** buttons (in addition to the small "+cost" badge in the
tower's tile corner, which still works too), and at max level, Upgrade is replaced by two
**Specialize** buttons -- see "Tower levels & specialization" below. Selling refunds a fraction of
everything spent on that tower and frees its space immediately.

The HUD shows a countdown to the next wave and a button (bottom-right) that reads "Start" before the
first wave -- it waits for you rather than auto-starting, so you get a beat to place towers first --
and "Skip" for every wave after that, forcing the between-wave delay to end early. `Space` does the
same thing as clicking it. A second button next to it cycles the simulation speed (`1x`/`2x`/`3x`, or
press `1`/`2`/`3` directly) -- real time still drives the frame rate, only the simulated world speeds
up. `R` opens a read-only overlay of your currently-held relics (a run only); any key closes it.

`P` or `Esc` opens the pause menu; the same two keys close it again. `R` there asks for confirmation
before restarting the current level (`R` again confirms, `Esc` cancels), `S` (shown only between
waves) saves the run to disk and returns to the menu -- see "Save & resume" below -- `Q` quits.
Playing a level you're playtesting from the map editor adds one more option there: `E` stops the run
and takes you straight back to the editor, paint buffer untouched.

On the **Floor Cleared** screen, any key returns to the map; on the **Shop** screen, click a card to
buy it (if you can afford it) and click Continue when you're done; on an **Event**, click one of the
options shown, then any key moves on; **Rest** and **Treasure** resolve themselves instantly and any
key continues from there. `Esc` quits from any of these, or from the main menu, game-over, or victory
screens (there's no pause menu to open on any of those). `R` restarts from the game-over screen, and
-- from the victory screen a Practice or playtested level can still reach -- advances to the next
level if there is one, otherwise replays the one you just won.

The level browser (`L`) has one extra toggle, reset every time you reopen it: `V` arms **Endless**
(Survival) mode for whichever level you pick next -- see "Practice, Difficulty, Endless, and Sandbox
modes" below for what always applies regardless.

## Testing

Run the test suite with `pytest` (from the venv) -- 1600+ tests covering every module. The
`Game`-level tests are split three ways by concern: `tests/test_game.py` (state machine, click/key
handling, update loop, rendering), `tests/test_run.py` (the whole run lifecycle -- the branching map,
Shop, Events, Rest, Treasure, the boss floor, relics, permadeath, meta-progression, save/resume,
Daily Run, Practice), and `tests/test_game_editor.py` (the editor, wave editor, and level browser
screens). `Editor` itself is also tested directly in `tests/test_editor.py`. All of the `Game`-level
files share fixtures and helpers from `tests/conftest.py`, which is also where the SDL dummy video
driver gets forced before pygame is imported -- so `pytest` runs headless with no extra setup, in CI
or anywhere else. (`tests/test_assets.py` stands alone and does its own.)

## Art

No art pack is bundled yet -- every sprite renders as a simple colored placeholder shape (see
`assets.py`). Drop a CC0 pixel-art pack's PNGs into `assets/towers/`, `assets/enemies/`,
`assets/tiles/`, `assets/projectiles/` using the filenames listed in `SPRITE_MANIFEST` (in
`assets.py`) and the real art will appear automatically -- no code changes needed. If the pack uses
different filenames, just edit the path strings in that manifest.

## Sound

No audio files are bundled either -- every cue (a tower firing, an enemy dying, a wave starting, a
floor clearing, a relic drafted, ...) is synthesized on the fly into a small chiptune-style blip
instead (see `audio.py`), matching the placeholder-shape visual style rather than aiming for
realism. Drop real files into `assets/sfx/` under the names in `SOUND_MANIFEST` (in `audio.py`) and
they'll play instead, no code changes needed. Toggle sound entirely from Settings.

## Tower placement

Each tile is cut into an 8x8 grid of small tiles (`settings.SUBTILES_PER_TILE`), and a tower's
required footprint is exactly one tile's worth of area -- 8x8 small tiles, unless a relic has
shrunk it for this floor -- but it can be *anchored* at any small tile, not just where a tile
boundary falls. Moving the build cursor shifts the footprint preview (a colored outline: white/valid,
red/blocked) in small-tile increments rather than snapping a whole tile at a time, so a tower can
straddle what used to be a tile boundary, tuck up against a path bend more precisely, or line up a
row of towers' ranges exactly. Two footprints can never overlap even partially, regardless of whether
their anchors happen to line up on any particular grid (`Grid.is_buildable`/`occupy`/`remove` in
`grid.py`), so this is purely about placement *precision* -- it doesn't let you fit more towers into
the same space.

The map itself renders each buildable tile as that same 8x8 mosaic of individually-drawn small tiles
with a thin, soft-edged gap between them (`Grid._build_background`, cached once per level rather than
redrawn every frame), so the placement grid is visible at a glance without being visually harsh. The
path renders as one unbroken tile -- no seams -- since it's never buildable anyway.

## Towers

Ten so far. In a run you start with three of them and unlock the rest (see "Runs" and
"Meta-progression"); Practice mode and editor playtests always offer all ten.

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

## Layout

The window is `PLAY_WIDTH` (the grid + the HUD bar beneath it) plus a fixed `PANEL_WIDTH` stats
sidebar on the right (both in `settings.py`) -- the window was simply grown to fit the sidebar rather
than shrinking the grid. `ui.draw_tower_stats_panel()` reads a tower class's plain stats
(`cost`/`damage`/`range`/`fire_rate`) plus its `EXTRA_STATS` (see below) to render the panel, so it
needs no changes for new tower types. Its Upgrade/Specialize/Sell buttons sit at fixed positions in
the panel regardless of which tower's stats are shown above them.

## Enemies

Ten species in total -- seven regular ones, plus three boss variants described below. The regular
seven: `GruntEnemy` (baseline), `ScoutEnemy` (fast, low HP -- also the one that gets shoved
back furthest by the knockback tower, since its knockback distance scales with the target's own
speed), `TankEnemy` (slow, high HP -- an easy target to keep in range, and frost's slow hits
especially hard on something already slow), `ShieldedEnemy` (a regenerating shield absorbs damage
before HP does, and starts regenerating again a few seconds after the last hit landed), `FlyingEnemy`
(airborne -- only a tower that can target flying enemies can hit it at all, which is every current
tower except Cannon and Knockback), `SplitterEnemy` (on death, splits into two weaker children that
keep going from the same point along the route), and `HealerEnemy` (never fights, but heals every
other enemy within range every frame -- rewards focusing it down first).

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

Seventeen built in -- fifteen ordinary ones the run map's own nodes draw from (single-lane corridors
for early rows, branching/merging multi-lane maps for later ones), plus two dedicated boss levels
reserved for the map's final row. `L` from the main menu opens a level browser listing every
built-in level plus any custom ones you've saved from the map editor -- each one shown with a small
thumbnail of its actual path (ground/path fill plus spawn/goal dots), not just its name. Nothing here
is locked: picking one is **Practice** (see below), which is deliberately decoupled from real
progress, so there's no reason to gate it. Saved levels persist across game sessions -- quit and
relaunch, and `L` still finds everything you'd saved before, straight off disk. More levels than fit
on screen at once scroll with the mouse wheel -- a "more below"/"more above" hint appears whenever
there's further to go.

## Meta-progression

Six of the ten towers start locked account-wide behind lifetime counters (`meta_progression.py`):
clearing floors unlocks Knockback, Poison, and Lightning; playing more runs unlocks Sniper, Support,
and Beacon; reaching the endless final floor once unlocks Beam. An unlocked tower joins the pool the
Shop can offer from -- it doesn't start in your hand, it just becomes a card you might see. A
handful of the game's newest relics and one of its levels are gated the same way, behind steeper
thresholds, so there's still something to chase long after every tower is unlocked. A toast pops up
in-game the moment you unlock anything.

## Practice, Difficulty, Endless, and Sandbox modes

**Practice** is what the level browser (`L`) does: play any single built-in or custom level on its
own, outside a run. It always loads in Sandbox mode (below) -- unlimited gold, invulnerable, every
tower available -- because it's for trying things out, not for earning anything. Nothing you do in
Practice touches your progress, achievements, or meta-progression unlocks. Real progress comes from
clearing run floors.

**Difficulty** (`S` from the main menu -> Settings) picks one of Easy/Normal/Hard -- a bundle of
multipliers on enemy HP/speed/gold reward and starting gold/lives (`difficulty.py`). Normal is every
multiplier at 1.0, i.e. exactly the original numbers -- see "Settings" below for how your choice
persists. A run snapshots your setting when it starts, so changing it mid-run doesn't move the
goalposts partway through; the per-floor escalation (see "Runs") stacks on top of it rather than
replacing it.

**Endless (Survival) mode** -- armed with `V` from the level browser before picking a level -- keeps
generating new waves once a level's own last wave clears instead of ending the level: each new wave
takes the previous one's enemy counts and bumps them up further, so it escalates without limit rather
than plateauing. There's no way to "win" an endless level; it plays until you run out of lives. A
run's own boss floor always plays this way, unconditionally.

**Sandbox mode** gives you unlimited gold and makes you invulnerable (a leaked enemy never actually
costs a life), for freely experimenting with tower combinations. A sandbox win/clear doesn't count
toward progress, achievements, or meta-progression unlocks, since it isn't a real test of anything.
Practice always uses it -- unconditionally, not as a toggle -- which is exactly why Practice earns
nothing.

## Settings

`S` from the main menu opens a Settings screen for **Fullscreen** (toggle), **Sound** (toggle -- see
"Sound" above), and **Difficulty** (Easy/Normal/Hard, see above) -- all three take effect and save to
disk immediately, so they're still set the same way the next time you launch the game.

## Post-level results

The Floor Cleared, Victory, and Game Over screens all show a compact table of every tower you built
(including ones you later sold), sorted by damage dealt -- damage, kills, and accuracy per tower, so
you can see which of your towers actually carried it. A Support tower shows `--` for accuracy rather
than a misleading 0%, since it never fires a shot.

## Achievements

`A` from the main menu opens an Achievements screen listing all eleven you can unlock -- landing your
first kill, racking up 100/1000 kills total, placing your first tower, maxing one out, choosing your
first specialization, clearing your first level, clearing every built-in level at least once,
clearing waves of enemies over time, and defeating a run's final boss for the first time. Progress
toward a still-locked achievement is shown right there (e.g. "37/100"), and a small toast pops up
in-game the moment you unlock a new one. None of this counts while playing in Sandbox mode, which
includes all of Practice.

Achievements are deliberately separate from the **meta-progression** unlocks described above:
achievements are trophies with no gameplay consequence (`achievements.py`), meta-progression unlocks
change what a future run's Shop can offer you (`meta_progression.py`). They're tracked in separate
files and separate registries, so one number never has to serve both purposes.

## Save & resume

The pause menu's `S` (shown only between waves, not mid-wave) saves what you're playing -- the
level, gold, lives, wave progress, every placed tower's level/specialization/targeting mode, and
whether it's an endless or sandbox session -- to disk and returns you to the main menu, which now
shows a `C` option to pick it back up exactly where you left off, even after quitting and relaunching
the game entirely. If a run is active, the run itself is saved too: its seed, map and current
position on it, drafted tower pool, and relics, so you resume on the same floor with the same deck.
Resuming never re-spends the gold you already spent on upgrades, and picks up right where the
*saved* difficulty was, even if you've changed the setting since. Playing that resumed session
through to its own conclusion clears the save, so "Continue" only ever offers something genuinely
still in progress -- there's only ever one save slot.

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
  rather than leaving it on the generic Power/Precision placeholder. A new tower not in
  `card_pool.STARTER_TOWERS` also needs a `MetaUnlock` entry (see below) or it can never be offered.
- **New enemy**: subclass `Enemy` in `enemy.py`, override its stats
  (`base_hp`, `base_speed`, `base_reward`, etc. -- or `update()`/
  `take_damage()` too, for something like a shielded unit or `BossEnemy`'s enrage/armor phase),
  then add it to `ENEMY_TYPES` under a short name. Reference that name from a level's
  `wave_specs` to use it.
- **New built-in level**: add a `Level(...)` entry to `LEVELS` in `levels.py` with its own path
  (`path_cells`/`spawn_cells`/`goal_cells` -- `pathing.path_cells_from_corners()` turns a terse
  ordered corner list into `path_cells` for a simple single-lane route; a branching/merging level
  unions several corner lists together instead), wave composition (`wave_specs`, a list of
  `{spawn_cell: {enemy_type_name: count}}` dicts -- one per wave, each spawn's own composition
  independent of any other spawn's), and starting gold/lives. `Grid`, `WaveManager`, and `Game` all
  consume whichever level is active generically, so this needs no other changes. Give its final wave
  a `"boss": 1` entry to match every other level. A player-made level doesn't need a registry entry
  at all -- see "Map editor" above.
- **New achievement**: add an `Achievement(...)` entry to `ACHIEVEMENTS` in `achievements.py`,
  keyed off one of the existing cumulative counters (`kills`, `towers_built`, `towers_maxed`,
  `towers_specialized`, `levels_cleared`, `distinct_levels_cleared`, `waves_survived`,
  `bosses_defeated`) or a new one -- a new counter just needs one `Game._record_achievement(...)`
  call added at whatever point in `game.py` the event actually happens.
- **New relic**: add a `Relic(...)` entry to `RELICS` in `relics.py` with whichever modifier
  fields it sets; `compose_relic_modifiers()` folds every held relic together into one bundle that
  feeds a floor's `Economy`/`WaveManager`/tower construction alongside difficulty and escalation, so
  nothing else needs changing for a per-floor or per-tower effect. Most relics aren't unlock-gated --
  only a handful of the newest ones are, via `RELIC_META_UNLOCKS` in `meta_progression.py`.
- **New tower/relic/level unlock**: add a `MetaUnlock`/`RelicMetaUnlock`/`LevelMetaUnlock` entry to
  `META_UNLOCKS`/`RELIC_META_UNLOCKS`/`LEVEL_META_UNLOCKS` in `meta_progression.py`, pairing the
  tower name/relic key/level id with a threshold on one of the lifetime run counters
  (`total_floors_cleared`, `runs_played`, `runs_reached_endless`, `bosses_defeated`).
- **New Random Event**: add an `Event(...)` entry to `EVENTS` in `events.py` with a short prompt and
  2-3 `EventOption`s, each a fixed, honestly-described delta (currency, lives, a relic grant, a tower
  unlock, or giving up a relic already held) -- see the existing sixteen for the shape.
