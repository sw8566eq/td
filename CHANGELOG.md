# Changelog

Notable player-facing and structural changes, tagged release by tagged release. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/); this project doesn't yet promise strict
semver meaning, just ascending `vX.Y.Z` tags via `.github/workflows/release.yml`.

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
