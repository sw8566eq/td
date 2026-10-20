# Controls

Every key and click, by screen.

[Back to the guide](README.md)

## Controls

From the main **menu**: press any other key to start a new run (see [Runs](runs.md#runs)), `E` opens the
map editor, `L` opens the level browser to practice a single floor, `S` opens Settings, `A` opens
your Achievements, `H` opens an in-game How to Play screen, `D` starts today's Daily Run, `B` opens
the Credits screen, `R` opens Run History, `U` opens Unlocks, `K` opens the **Field Manual** (every
relic, trophy relic, curse, potion, commander, elite affix, boss, tower module and veterancy rank with what it does),
`T` opens your **Service Record** (lifetime stats: runs, floors, kills, gold, plus damage and kills per tower,
kills per enemy and best depth per commander -- Practice never counts), and `C` (shown only
when one exists) continues a saved in-progress run.

On the run map, `R` shows the relics you're holding (as it does mid-fight). During a run's fight,
`Q` / `W` / `E` drink the potion in slot 1 / 2 / 3 (or click the slot in the
sidebar), and `V` toggles a coverage overlay of every tower's range.

On the **map** screen, click any highlighted node to enter it; a legend explains what each node
color means, and hovering a node shows a tooltip with its specific details (which level, how much a
Rest heals, and so on).

While **playing** a floor: click a tower button in the bottom bar, then click a buildable tile to
place it -- the sidebar on the right shows that tower type's stats while it's selected; right-click
at any time to clear the current selection without placing anything. A tower's required footprint is
one tile's worth of space, but it isn't locked to the tile grid -- see [Tower placement](towers.md#tower-placement) for
how that works.

Hover any placed tower to see its live stats and range in the sidebar; **click** it instead and that
stays pinned open even once the mouse moves away, until you click a different tower, pick a
build-menu type, or click empty ground with nothing selected. The pinned/hovered panel shows a
**Targeting** row (click to cycle first/last/strongest/closest/weakest, plus flying on a Harpoon -- which in-range enemy the tower
actually shoots at), **Upgrade** and **Sell** buttons (in addition to the small "+cost" badge in the
tower's tile corner, which still works too), and at max level, Upgrade is replaced by two
**Specialize** buttons -- see [Tower levels & specialization](towers.md#tower-levels--specialization). Selling refunds a fraction of
everything spent on that tower and frees its space immediately. **Move** (next to Sell) picks a placed
tower up so the next click puts it down somewhere else, keeping its level, specialization and
experience: free before a floor's first wave, 15% of what you've spent on it between waves, and never
mid-wave. Right-click (or Move again) cancels.

The HUD's top strip shows a countdown to the next wave and a button that reads "Start" before the
first wave -- it waits for you rather than auto-starting, so you get a beat to place towers first --
and "Skip" for every wave after that, forcing the between-wave delay to end early. Skipping pays an
**early-call bonus** of 3 battle gold per second cut from the countdown (shown next to the button,
e.g. "skip: +12g"). `Space` does the same thing as clicking it. The same strip also has a button that cycles the simulation speed
(`1x`/`2x`/`3x`, or press `1`/`2`/`3` directly) -- real time still drives the frame rate, only the
simulated world speeds up -- and, during a run, a "Relics: N" button. `R` opens a read-only overlay
of your currently-held relics (a run only); any key closes it.

`P` or `Esc` opens the pause menu; the same two keys close it again. `R` there asks for confirmation
before restarting the current level (`R` again confirms, `Esc` cancels), `S` (shown only between
waves) saves the run to disk and returns to the menu -- see [Save & resume](modes-and-progression.md#save--resume) -- `Q` quits.
Playing a level you're playtesting from the map editor adds one more option there: `E` stops the run
and takes you straight back to the editor, paint buffer untouched.

On the **Floor Cleared** screen, any key opens the reward screen (click a card to take it, then
Continue/Skip or Enter); on the **Shop** screen, click a card to
buy it (if you can afford it) and click Continue when you're done; on an **Event** or **Outpost**,
click one of the options shown, then any key moves on; **Treasure** resolves itself instantly and any
key continues from there. `Esc` quits from any of these, or from the main menu, game-over, or victory
screens (there's no pause menu to open on any of those). `R` restarts from the game-over screen, and
-- from the victory screen a Practice or playtested level can still reach -- advances to the next
level if there is one, otherwise replays the one you just won. `M` on either screen returns to the
main menu, e.g. to start a fresh run after a permadeath.

The level browser (`L`) has one extra toggle, reset every time you reopen it: `V` arms **Endless**
(Survival) mode for whichever level you pick next -- see [Practice, Difficulty, Endless, and Sandbox modes](modes-and-progression.md#practice-difficulty-endless-and-sandbox-modes) for what always applies regardless.
