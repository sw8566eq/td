# Changelog

Notable player-facing and structural changes, tagged release by tagged release. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/); this project doesn't yet promise strict
semver meaning, just ascending `vX.Y.Z` tags via `.github/workflows/release.yml`.

## [Unreleased]

### Added

- Real art for the last 2 towers (Siphon, Overload Cannon) and all 7 remaining enemy species
  (`boss`/`shielded`/`splitter`/`splitter_child`/`healer`/`final_boss`/`final_boss_shielded`) --
  tiles, towers, and enemies are now fully covered (only projectiles, at a fixed 12x12px, stay
  placeholder -- confirmed via a real render-size comparison that real art blurs into an
  indistinguishable blob there). Source: Kenney's "Tower Defense (Top-Down)" pack for the 2 towers,
  Huntrt's CC0 "The Apocalypse Constructor" (OpenGameArt.org) for the 7 enemies (tinted/outlined from
  its silhouette spritesheet, since it ships as plain white shapes).
- Real audio for 13 of 18 sound cues (also from "The Apocalypse Constructor"), replacing the
  synthesized chiptune blip for tower fire, enemy hit/killed, life lost, tower placed/upgraded/sold,
  wave start, game over, and relic acquired. The remaining 5 (floor cleared, boss defeated, victory,
  tower unlocked in the Shop, achievement toast) have no fitting cue in that pack and stay
  synthesized.
- Credits screen and README updated to name both CC0 sources now in use.

- Two new menu screens for data that was already being tracked but never had a viewer: **Run
  History** (every seed you've played and its best floors-cleared result, sorted best-first) and
  **Unlocks** (a live checklist of every account-wide tower/relic/level/Shop unlock, showing
  progress toward whichever's still locked).
- 8 new achievements (11 -> 19): collecting relics across your runs, playing Daily Runs, resolving
  Random Events, and placing a Siphon Tower or Overload Cannon for the first time.
- A **Run Guide** screen, reached from Help, explaining the run's own branching-map node types
  (Combat/Elite/Shop/Event/Rest/Treasure/Boss) and the 5 status effects (Marked/Slowed/Poisoned/
  Shielded/Knockback) for players who want more than the Help screen's own controls-only reference.
- A real MIT license (see `LICENSE`) and a real Credits screen, replacing a long-standing
  "License: TBD." placeholder -- Credits now also properly attributes the bundled Kenney CC0 art.

### Fixed

- Endless mode's final-boss species (`FinalBossEnemy`/`FinalBossShieldedEnemy`) no longer multiplies
  without limit deep in a boss floor's endless tail -- both mechanics (periodic reinforcement
  summons, a self-shield pulse) are live and recurring, not a one-time stat bump, so an unbounded
  count would have made a long endless run on a boss floor field an ever-growing swarm of
  simultaneous final bosses. Every other species still escalates without limit, exactly as
  endless mode's own design intends.
- A real, previously-uncaught layout bug: a scrollable list's "more above"/"more below" hint used to
  render directly inside the same viewport as its rows, visually colliding with whatever row
  happened to land in that same handful of pixels. Fixed across every scrollable screen (Run
  History, Unlocks, the retrofitted Achievements screen) by reserving a small margin exclusively
  for hints, kept structurally separate from the row-drawing viewport.

### Engineering

- `game.py` decomposition, phase 4: the Settings/Display/Audio/Keybindings cluster extracted into
  `SettingsManager` (`settings_manager.py`), following the same one-line-delegator shape as the
  three prior extractions (`Renderer`, `InputHandler`, `ProgressTracker`).
- `release.yml` now runs the same `ruff`/`mypy`/coverage-floor gate `tests.yml` already runs on
  every push/PR, not just a bare test run, before building a release binary.
- A generic scrollable-list helper (`ui.list_max_scroll`, `InputHandler._scroll_list`) factored out
  of level-select's and the wave editor's own previously-independent copies of the same scroll math,
  now shared by both of those plus the three screens above.

## [0.5.0] - 2026-09-22

### Added

- Two new towers: **Overload Cannon** (charges for several seconds locked onto one target, then
  fires a single massive burst -- an interrupted charge is lost outright, no partial credit) and
  **Siphon** (converts a fraction of damage dealt into battle gold, the first tower whose own
  mechanic generates economy from damage rather than kills). Both gated behind their own
  meta-progression unlock, same as every prior non-starter tower.
- 13 new relics (61 -> 74): Cannon's first-ever fully exclusive pair (can now target flying
  enemies; 40% faster projectiles), a dedicated launch pair for each of the two new towers, a
  damage bonus against Boss-tier enemies, the triple-status capstone (bonus damage against an enemy
  simultaneously Marked, Slowed, *and* Poisoned), a third density-archetype relic (fire rate instead
  of damage) and a third last-stand relic (range), and three round-out relics closing an
  economy-safety-net gap and two enemy-counterplay gaps (reduced Splitter-child HP, slower Healer
  healing).
- Real CC0 art (Kenney's "Tower Defense (Top-Down)" pack) for all tiles and the original 10 towers,
  plus 4 of 11 enemy species -- the rest still render as placeholder shapes; see README for how to
  drop in more without touching code.
- The Shop offers a 3rd relic slot once `total_floors_cleared` reaches 100 -- deliberately the
  longest chase in the whole meta-progression system.
- The account-wide unlock curve extended further: `seismic_slam` (Knockback's 2nd exclusive relic)
  at 75 floors cleared, a second gated level ("Double Confluence") at 25 runs played.

### Fixed

- A real, previously-uncaught HUD layout bug: the wave-countdown caption and Start/Skip button lived
  in the same bottom row as the Gold/Lives/Wave text and the tower build-menu buttons, at a
  screen-relative (not tower-count-relative) position -- already colliding, unnoticed, at the
  original 10-tower roster before either new tower above ever shipped. Fixed by moving the countdown
  caption and Skip/Start button into the HUD's top strip alongside the speed/relics toggles.
- Draft-screen layout bugs caught by live testing: a 5-card offer (reachable once the 3rd relic slot
  above unlocks) overflowed the screen at the old fixed card width, and relic titles were never
  wrapped or width-constrained at all, so a long one could already overflow a card even at 2 relics.

### Engineering

- `game.py` decomposition, phase 3: the achievement/meta-progression/toast-recording group extracted
  into `ProgressTracker` (`progress_tracker.py`), following the same one-line-delegator shape as the
  two prior extractions (`Renderer`, `InputHandler`).
- Incremental `mypy` adoption continues: `run_escalation.py`/`progress.py`/`achievements.py` are now
  strictly type-checked too (16 modules total).
- README.md and CLAUDE.md brought back in sync with everything above (relic/tower/test counts, two
  new architecture sections for the new towers' mechanics, the HUD fix's own design rationale) --
  both had drifted since v0.4.0.

## [0.4.0] - 2026-09-20

### Added

- Two more relics join the account-wide meta-progression chase: `frostbitten_mark` (gated behind
  50 total floors cleared) and `plague_mark` (20 runs played) -- the highest-power relics in the
  registry (1.35x cross-status combo multipliers), joining `flak_rounds`/`breach_charges`/
  `containment_charges` as long-tail unlocks. `chill_rot`, the third relic in that same batch,
  stays ungated on purpose so the cross-status mechanic itself is still reachable early.

### Engineering

- CI now enforces a coverage floor (`--cov-fail-under=98`) instead of reporting-only -- the measured
  baseline was 98.68%, so this closes out a previously-open decision with real headroom rather than
  flaking on ordinary future work.
- `requirements.txt` dependencies now have upper bounds (one major above whatever's currently
  installed; `ruff` is pre-1.0, so its ceiling is `<1`) instead of open-ended `>=` floors -- a
  maintenance guard-rail against a future major-version bump silently breaking CI, not a version
  change (every bound is already satisfied by what's installed today).
- Incremental `mypy` adoption continues: `rng_sampling.py`/`difficulty.py`/`economy.py`/
  `run_history.py`/`json_io.py` are now strictly type-checked too (9 modules total). `json_io.py`
  turned out to be a prerequisite, not an independent addition -- annotating `run_history.py`
  surfaced a fresh `no-any-return` error the moment its own return expression called into
  `json_io.py`'s still-unannotated `load_json_with_fallback`, the same "Any laundering" problem
  `rng_sampling.sample_up_to` already solved for the first four modules.
- Incremental `mypy` adoption, round three: `threshold_unlocks.py`/`meta_progression.py`/
  `run_state.py`/`card_pool.py` (13 modules total now). Caught a real "type lied" bug in
  `run_state.RunState.current_node_id` (typed as required but silently defaulting to `None`, the
  same class of bug v0.3.0's mypy work caught in `RelicModifiers`) and an over-widened
  `str | None` parameter in the already-strict `relics._default_relic_pool` that should always have
  been plain `str`. `relics.py`/`shop.py`/`events.py` also drop their `TYPE_CHECKING`-only `RunState`
  import in favor of a real one, now that `run_state.py` itself is annotated and no cycle exists.
- Closed out the long-standing 3-lane row-3 difficulty open question with an honest inconclusive
  result rather than a guessed constant change: a scripted headless-combat harness couldn't isolate
  "3-lane structural difficulty" from the bot's own strategic weaknesses (every scenario lost,
  2-lane controls included), so `run_escalation.py`'s docstring now records the attempt and
  recommends a human-supervised playtest next.

## [0.3.0] - 2026-09-19

### Added

- First-run onboarding hints: map-screen guidance for a player's whole first run, a tower-placement
  banner until the account's first-ever real-run placement, and a full stats preview on hover for an
  unselected build-menu tower (previously required clicking it first).
- A volume slider (10% steps, alongside the existing Sound on/off toggle) and a colorblind-safety
  pass on the placeholder palette, verified with an actual deuteranopia/protanopia simulation.
- A Keybinds screen (Settings -> Keybinds...) for rebinding a curated set of actions -- Pause, Skip
  Wave, the three time-scale keys, Open Relics, and the map editor's Undo/Redo -- click a row, press
  a key. Escape always stays fixed as back/cancel/quit, by design; see CLAUDE.md's "Key remapping is
  curated, not repo-wide" for why only these actions and not every key in the game.

### Engineering

- `game.py` decomposition, phase 1 and 2: `render()` extracted into `Renderer` (`renderer.py`), and
  every input-handling method (`handle_events`, `_handle_keydown`, the `_handle_*_click` family, the
  scroll handlers) extracted into `InputHandler` (`input_handler.py`). `Game` itself keeps a one-line
  delegator per moved method, so no test call site needed to change.
- A broad-phase spatial index (`spatial_index.py`) for tower targeting -- `Tower.acquire_target()`
  no longer has to scan every live enemy on every shot, narrowing the scan to enemies near enough to
  plausibly be in range instead. Benchmarked ~3-4x faster at 1k-20k synthetic enemies, addressing
  what endless mode's unbounded enemy growth was always going to make felt eventually.
- Incremental `mypy` adoption started: `relics.py`/`run_map.py`/`events.py`/`shop.py` are the first
  four modules fully type-annotated and gated in CI, under a project-wide-permissive/per-module-strict
  config (see CLAUDE.md's "Type checking is incremental, not repo-wide"). Caught one genuine
  pre-existing bug in the process -- several `RelicModifiers` fields were typed as required but
  defaulted to `None`.
- README rewritten to match the branching-map run loop and shipped content (towers/levels/
  achievements/events/relics counts, the two-currency Shop, boss mechanics) -- it had drifted behind
  since the roguelike overhaul.

## [0.1.0] - 2026-09-17

First tagged release -- everything below already existed on `main` before this tag; this entry
exists to give the first Linux binary release a starting point to describe.

### Added

- Roguelike run loop: a seeded, fully-visible branching map (6 rows) of Combat, Elite, Shop,
  Event, Rest, Treasure, and a final Boss node, played with a small drafted pool of towers.
- Two-currency economy: per-floor battle gold (resets every floor) plus a persistent shop
  currency, banked from a floor's own escalating-price Shop and leftover gold on clear.
- 61 relics spanning per-floor, per-tower, escalating, conditionally-revocable, and live-reactive
  effect shapes.
- 10 towers, 10 enemy species (including two boss species with distinct late-run mechanics: one
  summons reinforcements, the other periodically self-shields), 15 levels plus 2 dedicated boss
  levels.
- 16 honestly-described Random Events, plus Rest and Treasure nodes.
- Meta-progression: cross-run tower/relic/level unlocks, 11 achievements, per-seed run history
  (best floors cleared), and Daily Runs.
- Easy/Normal/Hard difficulty, Sandbox/Practice mode, and Endless (Survival) mode with unbounded
  wave escalation.
- A full in-game map editor: freeform path painting with undo/redo and shape tools, copy/paste,
  a per-spawn wave editor, and save/load of custom levels.
- Save/resume for an in-progress session between waves.
- Synthesized chiptune audio and placeholder sprite art -- see README for how to drop in real
  assets later without touching code.

### Engineering

- `ruff` linting and `pytest-cov` coverage reporting added to CI (99% line coverage across the
  1650-test suite as of this tag).
