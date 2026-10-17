# Waves, difficulty, Sandbox/Practice, settings

`WaveManager`'s state machine and endless mode, difficulty multipliers, Sandbox and Practice, and
the Settings screen.

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
"Difficulty modes, Sandbox/Practice mode, and player settings").

## Endless mutators

`run/endless_mutators.py` (strict-mypy) -- the final boss floor's score chase. `MUTATORS` is a
registry of plain-data `EndlessMutator`s: stat multipliers (hp/speed/breach), an additive regen
fraction, a burrow flag, a `SpeciesSwap` (every Nth eligible enemy in a spawn's queue becomes another
species -- Skyborne to `flying`, Shielded Ranks to `shielded`; bosses, the target species and, when
`ground_only`, flyers are skipped), a count multiplier, and per-spawn escorts (Escort's Tank).
`compose(keys)` folds the active list into one frozen `MutatorEffects` (multipliers multiply, regen
and escorts add, burrowing ORs, swaps apply in draw order).

**Cadence and draws.** `mutator_count(endless_cleared)` is `endless_cleared // MUTATOR_CADENCE`.
Draw `i` uses `Game._run_rng(run, "mutator", f"{node.id}:{i}")` and picks from the mutators not yet
active (`roll_mutator`), so all of them show once before any repeats, and after that only the
`repeatable` ones (plain multipliers) are drawn again. The count follows *this fight's* endless waves
(`Game._fight_endless_waves_cleared`, the wave index minus `LEVELS`' authored count), not the run's
best `RunState.endless_waves_cleared`, so a restart starts the mutators over.

**Nothing is stored.** `Game._apply_endless_mutators(run, node, announce=False)` re-derives the list
and sets `Game.active_mutators` (the sidebar reads it) plus `WaveManager.mutators`. It runs on every
fight load (`_load_combat_node`), on resume (`resume_saved_run`, after `wave_manager.restore`, since
the count comes from the restored wave index), and from `_update_endless_score` on each wave clear
with `announce=True`. Only that path toasts each new mutator and pays its bounty
(`BOUNTY_LIVES`/`BOUNTY_GOLD` into the live `Economy`), so a resume never pays it twice. Not the final
floor: `active_mutators` is `[]` and `WaveManager.mutators` is `None`.

**Where they apply.** `WaveManager._wave_queues` builds each spawn's name queue for `_begin_wave` and
for `next_wave_preview` (so the HUD's "Next:" line shows the mutated wave). With mutators set, it
uses `MutatorEffects.transform_composition`. Mutators reshape the *queue*, never
`level.wave_specs`, so `_default_endless_wave` keeps compounding off un-mutated waves (a stored Swarm
would compound itself every wave). `apply_spawn_multipliers` applies the stat half after the floor
multipliers and the boss affix's traits. It also covers splitter children and summons. HP also scales
a Shielded enemy's shield, regen adds to a Lich-style affix's, and breach multiplies the instance's
`BREACH_MULTIPLIER`.

**Shown.** The sidebar lists them in the Proving Grounds status rows (`ui.mutator_list_lines`, a
header plus wrapped `summary_names`, "Swarm x2" for repeats), growing upward. The final boss is never
a Proving Grounds fight, so the rows are free. A hovered potion's description moves above the block.
The deepest count, `mutator_count(run.endless_waves_cleared)`, shows in `ui.run_summary_lines` ("N
mutators faced") and is recorded as the optional `endless_mutators` run-history field.

## Calling the next wave early

`WaveManager.skip_delay()` returns the seconds of a real between-waves countdown it cut short (0.0 for
wave 1's `AWAITING_START`, which has no countdown, and while a wave is spawning). The Skip button and
the `skip_wave` key both go through `Game.call_next_wave()`, which pays
`Game.early_call_bonus(seconds)` battle gold (`int(seconds * settings.EARLY_CALL_GOLD_PER_SECOND)`, times any
Signal Horn-style relic) and shows it as a gold `FloatingText`
over the Skip button. WaveManager never touches `Economy` itself. The HUD caption
(`ui._draw_wave_countdown_and_skip`) computes the same number so the reward shows before the click.
Calling `skip_delay()` directly (tests, `tools/`) pays nothing.

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
Practice mode (see the next paragraph) absorbed that entirely -- picking any level to play always loads
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
half-wired (see [persistence.md](persistence.md) "`progression/progress.py`" for what survived).

The `GameState.SETTINGS` screen (`S` from the menu) is where `fullscreen` and `difficulty` actually
get changed (`ui.draw_settings_screen`/`get_clicked_settings_option`); both persist immediately on
change via `player_settings.save_settings()` rather than only on quit, the same "write through
immediately" choice `progress.mark_level_cleared()` and the achievement/meta-progression/save-state
modules all make too (see [persistence.md](persistence.md)). Its "Accessibility..." button (right of the last
Window row) opens `GameState.ACCESSIBILITY`, which holds the Colorblind palette and Reduce effects
toggles. See [presentation.md](presentation.md) "Accessibility: palettes and reduced effects".
