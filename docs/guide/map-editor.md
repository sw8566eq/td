# Map editor

Paint your own levels, write their waves, and share them.

[Back to the guide](README.md)

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

The **High** tool paints high ground (the +20%-range raised tiles, see [Tower placement](towers.md#tower-placement)). Start a
drag on plain ground to raise tiles, or on high ground to lower them. High ground can't go on the
path: painting path over a raised tile flattens it, and Erase clears it too. It's saved in the level
file, copied by Copy/Paste and covered by Undo/Redo. Older level files without it still load.

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
`persistence/persistence.py`) under a name slugged from the level's name -- the
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
