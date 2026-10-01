# Waves, difficulty, Sandbox/Practice, settings

## Waves

`WaveManager` (`entities/waves.py`) is a small state machine: `AWAITING_START` -> `BETWEEN_WAVES` ->
`SPAWNING` -> (loop) -> `DONE`. Wave 1 starts in `AWAITING_START` and never advances on its own --
`skip_delay()` (the HUD's Start/Skip button, or `Space`) is what moves it to `BETWEEN_WAVES` with
the timer zeroed, same as skipping any later between-wave countdown. Every wave after the first
auto-counts down `between_wave_delay` as normal.

**Endless (Survival) mode** is the same state machine with one exit removed: constructed with
`endless=True`, `WaveManager._advance_after_clear()` never transitions to `DONE` once the last
authored wave clears -- instead it calls `endless_wave_generator(level, next_wave_number)` (default
`_default_endless_wave`: take the *immediately preceding* wave's own per-spawn composition and bump
every count by `max(1, count // 4)`) and appends the result onto `level.wave_specs`, so growth
compounds off whatever the last wave actually was rather than the level's original final wave --
unbounded escalation, not a curve that flattens out. `all_waves_complete` staying permanently
`False` is what keeps `Game.update()`'s win-check from ever firing for a genuine endless run (it
only ever reaches `GAME_OVER`). Because `WaveManager.level` and `Game.level` are the *same object*,
appending a generated wave would otherwise permanently leak it into the shared `LEVELS` registry
singleton for a built-in level -- `Game._load_level_object` sidesteps this with
`dataclasses.replace(level, wave_specs=list(level.wave_specs))` whenever `endless=True`, so every
endless run gets its own private wave list to grow. `Game.level_select_endless_armed` (toggled by
`V` while browsing to play, reset every time the browser reopens) is what threads `endless=True`
into whichever level gets picked next; it's independent of, and combinable with, Sandbox mode (see
below).

## Difficulty modes, Sandbox/Practice mode, and player settings

`run/difficulty.py`'s `DIFFICULTY_MODES` registry (easy/normal/hard, same `{key: ...}` shape as every
other registry in this codebase) is a bundle of multipliers -- `enemy_hp_multiplier`/
`enemy_speed_multiplier`/`enemy_gold_multiplier`/`starting_gold_multiplier`/
`starting_lives_multiplier` -- composed as an *extra* factor on top of `Enemy`'s own existing
per-wave scaling math, never replacing it. `"normal"` is every multiplier at `1.0`, so picking it is
byte-for-byte the pre-difficulty behavior -- neither `Enemy` nor `Economy` needed any changes to
support this; `WaveManager._spawn_enemy` (enemy stats, applied post-construction) and
`Game._load_level_object` (starting gold/lives) are the only two application points. The active
difficulty is a **sticky, cross-session player preference** (`self.difficulty`, persisted via
`persistence/player_settings.py`), read at `_load_level_object` time -- changing it mid-level has no effect
until the next level load, the same "applies on next load" precedent `unlimited_gold` already set.

**Sandbox/Creative mode** is a player-reachable, per-level alternative to the CLI-only
`--unlimited-gold` debug flag, threaded through `load_level`/`load_custom_level`/
`_load_level_object` exactly parallel to `endless` above (a sticky `self.sandbox`). It used to be
its own independent level-select toggle (`B`, alongside `V`'s endless toggle); the run loop's
Practice mode (below) absorbed that entirely -- picking any level to play always loads
`sandbox=True` now, unconditionally, so there is no `B` key or `level_select_sandbox_armed` flag
left to arm it separately. It sets both `Economy.unlimited_gold` and a new `Economy.invulnerable`
(`lose_life()` becomes a no-op, `is_out_of_lives` stays `False` regardless of `self.lives`,
mirroring `unlimited_gold`'s "never actually deducted" precedent rather than a decrement-then-clamp
`presentation/ui.py` would then have to also mask). A sandbox win intentionally does *not* record progress or
bump any achievement/meta-progression counter -- trivializing victory shouldn't trivialize real
progress -- the same reasoning that already keeps a genuine endless run's `all_waves_complete` from
ever firing at all. `Game._record_level_cleared()`'s own `if self.sandbox: return` is the one gate
for the `progression/progress.py` half; `_record_achievement`/`_record_meta_progress` share a second one inside
`_record_progress_counter()`, the helper both delegate to, rather than either repeating it at its
own call sites. `_record_run_permadeath()` carries a third, separate `if self.sandbox: return` of
its own -- its `run_history.record_run_result()` call has no sandbox awareness to delegate to, so
this one guard can't be folded into the shared helper the other two use.

**Practice mode** is what absorbed "play a level standalone": `LEVEL_SELECT`'s play purpose always
loads `sandbox=True`. That's a deliberate design position, not an implementation detail -- real
progress comes only from playing a run, so a standalone level is explicitly a place to experiment
and earns nothing. It's also what retired `progress.is_unlocked()`: with no progress to gate on and
no gate to apply it to, sequential campaign unlocking was removed outright rather than left
half-wired (see the `progression/progress.py` bullet below for what survived).

The `GameState.SETTINGS` screen (`S` from the menu) is where `fullscreen` and `difficulty` actually
get changed (`ui.draw_settings_screen`/`get_clicked_settings_option`); both persist immediately on
change via `player_settings.save_settings()` rather than only on quit, the same "write through
immediately" choice `progress.mark_level_cleared()` and the achievement/meta-progression/save-state
modules below all make too.
