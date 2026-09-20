# Changelog

Notable player-facing and structural changes, tagged release by tagged release. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/); this project doesn't yet promise strict
semver meaning, just ascending `vX.Y.Z` tags via `.github/workflows/release.yml`.

## [Unreleased]

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
