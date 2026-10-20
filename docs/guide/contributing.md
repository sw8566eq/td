# Contributing

Adding content, running the tests, and where the art and sound come from. Architecture notes for coding agents (and humans) live in [`docs/agents/`](../agents/) -- start at [`AGENTS.md`](../../AGENTS.md).

[Back to the guide](README.md)

## Adding content

The game is built so new content is additive -- a new subclass or registry
entry, not a change to the systems that already work.

- **New tower**: subclass `Tower` in `entities/tower.py`, set its stats
  (`cost`/`range`/`damage`/`fire_rate`/`sprite_name`) and implement
  `create_projectile()`, then add it to `TOWER_TYPES`. It shows up in the
  build menu automatically. If it has its own special mechanic (splash,
  slow, knockback, ...), list it in `EXTRA_STATS` as
  `(label, attribute_name, format_function)` and it shows up in the stats
  panel automatically too. Override `SPECIALIZATIONS` with your own two named,
  mechanic-specific level-3 choices -- see how every current tower does this in `entities/tower.py` --
  rather than leaving it on the generic Power/Precision placeholder. A new tower not in
  `card_pool.STARTER_TOWERS` also needs a `MetaUnlock` entry (see the unlock bullet in this list) or it can never be offered.
- **New enemy**: subclass `Enemy` in `entities/enemy.py`, override its stats
  (`base_hp`, `base_speed`, `base_reward`, etc. -- or `update()`/
  `take_damage()` too, for something like a shielded unit or `BossEnemy`'s enrage/armor phase),
  then add it to `ENEMY_TYPES` under a short name. Reference that name from a level's
  `wave_specs` to use it.
- **New built-in level**: add a `Level(...)` entry to `LEVELS` in `world/levels.py` with its own path
  (`path_cells`/`spawn_cells`/`goal_cells` -- `pathing.path_cells_from_corners()` turns a terse
  ordered corner list into `path_cells` for a simple single-lane route; a branching/merging level
  unions several corner lists together instead), wave composition (`wave_specs`, a list of
  `{spawn_cell: {enemy_type_name: count}}` dicts -- one per wave, each spawn's own composition
  independent of any other spawn's), and starting gold/lives. `Grid`, `WaveManager`, and `Game` all
  consume whichever level is active generically, so this needs no other changes. Give its final wave
  a `"boss": 1` entry to match every other level. A player-made level doesn't need a registry entry
  at all -- see [Map editor](map-editor.md).
- **New achievement**: add an `Achievement(...)` entry to `ACHIEVEMENTS` in `progression/achievements.py`,
  keyed off one of the existing cumulative counters (`kills`, `towers_built`, `towers_maxed`,
  `towers_specialized`, `levels_cleared`, `distinct_levels_cleared`, `waves_survived`,
  `bosses_defeated`, `relics_collected`, `daily_runs_played`, `events_resolved`, `potions_used`,
`acts_cleared`, `towers_forged`, the max-only `ascension_reached`/`curses_held_at_once`, or a
  `f"{tower_name}_built"` counter for any `TOWER_TYPES` name) or a genuinely new one -- a new
  counter just needs one `Game._record_achievement(...)` call added at whatever point in `core/game.py`
  the event actually happens.
- **New relic**: add a `Relic(...)` entry to `RELICS` in `run/relics.py` with whichever modifier
  fields it sets; `compose_relic_modifiers()` folds every held relic together into one bundle that
  feeds a floor's `Economy`/`WaveManager`/tower construction alongside difficulty and escalation, so
  nothing else needs changing for a per-floor or per-tower effect. Most relics aren't unlock-gated --
  only a handful of the newest ones are, via `RELIC_META_UNLOCKS` in `progression/meta_progression.py`.
- **New tower/relic/level unlock**: add a `MetaUnlock`/`RelicMetaUnlock`/`LevelMetaUnlock` entry to
  `META_UNLOCKS`/`RELIC_META_UNLOCKS`/`LEVEL_META_UNLOCKS` in `progression/meta_progression.py`, pairing the
  tower name/relic key/level id with a threshold on one of the lifetime run counters
  (`total_floors_cleared`, `runs_played`, `runs_reached_endless`, `bosses_defeated`).
- **New Random Event**: add an `Event(...)` entry to `EVENTS` in `run/events.py` with a short prompt and
  2-3 `EventOption`s, each a fixed, honestly-described delta (currency, lives, a relic grant, a tower
  unlock, or giving up a relic already held) -- see the existing ones for the shape.

## Testing

Run the test suite with `pytest` (from the venv) -- it covers every module. The
`Game`-level tests are split three ways by concern: `tests/test_game.py` (state machine, click/key
handling, update loop, rendering), `tests/test_run.py` (the whole run lifecycle -- the branching map,
Shop, Events, Rest, Treasure, the boss floor, relics, permadeath, meta-progression, save/resume,
Daily Run, Practice), and `tests/test_game_editor.py` (the editor, wave editor, and level browser
screens). `Editor` itself is also tested directly in `tests/test_editor.py`. All of the `Game`-level
files share fixtures and helpers from `tests/conftest.py`, which is also where the SDL dummy video
driver gets forced before pygame is imported -- so `pytest` runs headless with no extra setup, in CI
or anywhere else. (`tests/test_assets.py` stands alone and does its own.)

## Layout

The window is `PLAY_WIDTH` (the grid + the HUD bar beneath it) plus a fixed `PANEL_WIDTH` stats
sidebar on the right (both in `support/settings.py`) -- the window was simply grown to fit the sidebar rather
than shrinking the grid. `ui.draw_tower_stats_panel()` reads a tower class's plain stats
(`cost`/`damage`/`range`/`fire_rate`) plus its `EXTRA_STATS` (see [Adding content](#adding-content)) to render the panel, so it
needs no changes for new tower types. Its Upgrade/Specialize/Sell buttons sit at fixed positions in
the panel regardless of which tower's stats are shown above them.

## Art

Tiles, towers and enemies use real CC0 art wherever a good match exists, and anything without a file falls back to a flat placeholder shape (see `SPRITE_MANIFEST` in `presentation/assets.py`). Projectiles stay placeholder on purpose. Two CC0 sources are in use:
- Kenney's ["Tower Defense (Top-Down)"](https://kenney.nl/assets/tower-defense-top-down) pack
  (kenney.nl), CC0 / public domain -- credit appreciated but not required.
- Huntrt's ["The Apocalypse Constructor"](https://opengameart.org/content/the-apocalypse-constructor-sprites-audios)
  (OpenGameArt.org), CC0.

Kenney's designs don't literally match this game's tower names, so sprites are assigned by shape and feel rather than by name. Enemies with no good Kenney match use tinted low-poly shapes cut from the Apocalypse Constructor's spritesheet. Projectiles render at 12x12px, where real sprites blur into the same blob as the flat-circle placeholder, so they aren't worth curating unless that size changes.

To fill in more of the manifest yourself: drop a CC0 pack's PNGs into the relevant `assets/`
subdirectory using the filenames listed in `SPRITE_MANIFEST` and the real art appears automatically,
no code changes needed (if a pack uses different filenames, just edit the path strings in that
manifest).

## Sound

Most sound cues are real audio (also from Huntrt's "The Apocalypse Constructor" pack above, CC0) --
tower fire (default/heavy/zap), enemy hit (small/splash)/killed, a life lost, tower placed/upgraded/
sold, wave start, game over, and a relic acquired. The rest (floor cleared, boss defeated,
victory, a tower unlocked in the Shop, an achievement toast) have no good match in that pack -- it's
built for combat/economy cues, not celebratory fanfares/chimes -- and still synthesize on the fly
into a small chiptune-style blip instead (see `presentation/audio.py`), matching the placeholder-shape visual
style rather than aiming for realism. Drop real files into `assets/sfx/` under the names in
`SOUND_MANIFEST` (in `presentation/audio.py`) and they'll play instead, no code changes needed. Toggle sound
entirely from Settings.
