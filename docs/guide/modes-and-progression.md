# Modes and progression

Practice, difficulty, endless and sandbox modes, plus everything that persists between runs.

[Back to the guide](README.md)

## Meta-progression

Every tower except the three starters (Basic, Cannon, Frost) starts locked account-wide behind a lifetime counter (`progression/meta_progression.py`): floors cleared, runs played, or reaching the endless final floor. The Unlocks screen (`U` from the main menu) lists them. An unlocked tower joins the pool the Shop can offer from -- it doesn't start in your
hand, it just becomes a card you might see. A handful of the game's newest relics and three of its
levels are gated the same way, behind steeper thresholds, so there's still something to chase long
after every tower is unlocked. A toast pops up in-game the moment you unlock anything.

## Practice, Difficulty, Endless, and Sandbox modes

**Practice** is what the level browser (`L`) does: play any single built-in or custom level on its
own, outside a run. It always loads in Sandbox mode (below) -- unlimited gold, invulnerable, every
tower available -- because it's for trying things out, not for earning anything. Nothing you do in
Practice touches your progress, achievements, or meta-progression unlocks. Real progress comes from
clearing run floors.

**Difficulty** (`S` from the main menu -> Settings) picks one of Easy/Normal/Hard -- a bundle of
multipliers on enemy HP/speed/gold reward and starting gold/lives (`run/difficulty.py`). Normal is every
multiplier at 1.0, i.e. exactly the original numbers -- see [Settings](#settings) for how your choice
persists. A run snapshots your setting when it starts, so changing it mid-run doesn't move the
goalposts partway through; the per-floor escalation (see [Runs](runs.md#runs)) stacks on top of it rather than
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
[Sound](contributing.md#sound)), and **Difficulty** (Easy/Normal/Hard) -- all three take effect and save to
disk immediately, so they're still set the same way the next time you launch the game.

**Field Notes** are short hints shown once the first time you meet a system: a new node type on
the map, the reward screen, a potion or module, a resonance, a flyer or burrower, low lives, and so
on. They appear one at a time in a corner panel. Click one to dismiss it, or let it fade after 10
seconds. **Hints: On/Off** in Settings turns them off, and **Reset Hints** shows them all again. The
hints you've already seen are kept in `hints.json` next to the game's other local files.

**Accessibility...** (a button on the Settings screen) has two more saved toggles. **Colorblind
palette** swaps the colors that only work if you can tell red from green: the placement outline
(blue = buildable, vermillion = blocked), enemy health bars (yellow), lives and warning text, a
Mortar's dead-zone ring, a boss's enrage ring, and the run map's node colors. They become an Okabe-Ito
blue/orange/yellow set that stays distinct under deuteranopia and protanopia. **Reduce effects** dims
hit flashes, death poofs and floating damage numbers. The screen previews the active palette.

## Post-level results

The Floor Cleared, Victory, and Game Over screens all show a compact table of every tower you built
(including ones you later sold), sorted by damage dealt -- damage, kills, and accuracy per tower, so
you can see which of your towers actually carried it. A Support tower shows `--` for accuracy rather
than a misleading 0%, since it never fires a shot.

## Achievements

`A` from the main menu opens an Achievements screen listing every achievement, from landing your first kill to defeating a run's final boss. Progress
toward a still-locked achievement is shown right there (e.g. "37/100"), and a small toast pops up
in-game the moment you unlock a new one. None of this counts while playing in Sandbox mode, which
includes all of Practice.

Achievements are deliberately separate from the **meta-progression** unlocks described above:
achievements are trophies with no gameplay consequence (`progression/achievements.py`), meta-progression unlocks
change what a future run's Shop can offer you (`progression/meta_progression.py`). They're tracked in separate
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

Runs also **autosave** every time you're on the map or step into a node, so you can quit from
anywhere and `C` picks the run back up. If you quit in the middle of a fight you hadn't saved, you
resume at the start of that same fight -- quitting never lets you skip a node you already chose.
Starting a new run replaces any run still saved (there's only one slot).
