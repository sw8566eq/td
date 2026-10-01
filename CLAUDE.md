# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
It is kept short on purpose. The detailed architecture notes live in `docs/claude/` (see the index
below). **Before you change a subsystem, read its chunk.** Those files explain the reasoning behind
the code: invariants, past bugs, and why things are built the way they are.

## Commands

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python main.py                     # run the game
python main.py --unlimited-gold    # debug flag -- every purchase always succeeds, gold never spent
python main.py --editor            # launch straight into the map editor (also reachable via E from the menu)

pytest                             # full suite
pytest tests/test_run.py           # one file
pytest tests/test_grid.py::test_non_path_cell_is_buildable   # one test
pytest -v --cov=. --cov-report=term-missing --cov-fail-under=98   # what CI runs (.github/workflows/tests.yml)

ruff check .                       # lint -- also what CI runs, gates the same workflow

mypy run/relics.py run/run_map.py run/events.py run/shop.py support/rng_sampling.py run/difficulty.py world/economy.py progression/run_history.py persistence/json_io.py progression/threshold_unlocks.py progression/meta_progression.py run/run_state.py run/card_pool.py run/run_escalation.py progression/progress.py progression/achievements.py run/rewards.py run/potions.py run/ascension.py run/commanders.py run/elite_affixes.py   # type check -- only the modules annotated so far; also what CI runs

pyinstaller --onedir --name td --add-data "assets:assets" main.py   # build a Linux release binary locally -- see docs/claude/release.md
```

CI (`.github/workflows/tests.yml`, and `release.yml` again before building) runs `ruff check .`, the
strict mypy module list above, and pytest with `--cov-fail-under=98`. The mypy list is kept by hand in
four places: `pyproject.toml`'s `[[tool.mypy.overrides]]`, the Commands block above, `tests.yml`, and
`release.yml`. When you annotate a new module, add it to all four (see `docs/claude/tooling.md`).

## Must-know rules

- **The game is a roguelike deckbuilder. The run loop is the main loop.** Playing a level on its own
  is Practice (always `sandbox=True`, earns nothing). See `run-loop.md` and `run-map.md`.
- **Content is registries, not conditionals.** `TOWER_TYPES`, `ENEMY_TYPES`, `LEVELS`, `RELICS`,
  `EVENTS`, `ACHIEVEMENTS` and `META_UNLOCKS` are `{key: ...}` dicts. To add content, write a new
  class or entry plus one registry line. Never add branches to the code that consumes a registry.
- **Imports are always fully qualified** (`from entities.tower import TOWER_TYPES`), never relative.
  Every package sits exactly one level under the repo root. `json_io.module_relative_path()` depends
  on that depth.
- **`Game._load_level_object()` is the one place every level load goes through.**
- **Simulation code never calls presentation code or `Economy`.** `Tower`/`Enemy`/`Projectile` add
  entries to per-frame event lists, and `Game.update()` drains them (see `presentation.md`).
- **Progress, achievement and meta-progression counters are bumped only from `Game`.** Never bump
  them from `Tower`/`Enemy`/`Economy`, because resuming a save would count them twice. Sandbox never
  records progress.
- **A new relic field that `Tower.update()` tags onto projectiles needs a matching copy in
  `OverloadCannonTower.update()`'s duplicate block** (see `towers.md`).
- **Run RNG is re-derived on demand** with `Game._run_rng(run, stream, key)`, keyed by node id, never
  by row number. No RNG state is ever serialized.
- Tests run headless (SDL dummy driver, set in `tests/conftest.py`). Inject every on-disk JSON path
  (`Game(progress_path=..., ...)`) so tests never touch real player files.

## Architecture docs index (`docs/claude/`)

Some cross-references point to a section by name: `see "Some Section" above/below` inside these
files, or `see CLAUDE.md's "Some Section"` in code comments. That section is now a `## Some Section`
heading in one of the files below. Run `grep -rn "## Some Section" docs/claude` to find it.

| File | Read when touching |
|---|---|
| [tooling.md](docs/claude/tooling.md) | ruff/coverage config, the history of the incremental mypy passes and how to extend the list, how the test suite is laid out |
| [core-game.md](docs/claude/core-game.md) | folder layout, `Game`, and its pieces split out into `Renderer`/`InputHandler`/`ProgressTracker`; toasts |
| [run-loop.md](docs/claude/run-loop.md) | `RunState`, `start_new_run`, node flow, floor clear/permadeath, `_run_rng`, Daily Run |
| [relics.md](docs/claude/relics.md) | `run/relics.py`: every relic batch, the effect shapes, `compose_relic_modifiers` stacking rules |
| [run-map.md](docs/claude/run-map.md) | `run/run_map.py`, the node types (Combat/Elite/Shop/Event/Rest/Treasure/Boss), map screen |
| [economy-shop.md](docs/claude/economy-shop.md) | battle gold vs shop currency, `run/shop.py`, `--unlimited-gold` |
| [enemies.md](docs/claude/enemies.md) | registries, Boss/FinalBoss mechanics, `IS_BOSS`, Mark, Corrosive Poison shield bypass |
| [grid-paths.md](docs/claude/grid-paths.md) | tile vs subtile coords, footprints, path topology (forest rule), `sample_route` |
| [editor.md](docs/claude/editor.md) | map editor, wave editor, custom level files, level browser/thumbnails/scrolling |
| [towers.md](docs/claude/towers.md) | leveling/specialization, Support two-pass update, Overload Cannon, Siphon, spatial-index targeting, results table |
| [ui-input.md](docs/claude/ui-input.md) | keybindings, stats panel click-routing, HUD top strip vs bottom row |
| [waves-difficulty.md](docs/claude/waves-difficulty.md) | `WaveManager` states, endless mode, difficulty, Sandbox/Practice, settings screen |
| [persistence.md](docs/claude/persistence.md) | `json_io`, progress/achievements/meta-progression/run history/save-state/keybindings files |
| [presentation.md](docs/claude/presentation.md) | visual effects drain idiom, audio/`SoundManager`, `AssetManager` |
| [release.md](docs/claude/release.md) | PyInstaller `--onedir` release workflow |

When you add or change architecture notes, put them in the matching chunk, not in this file.
