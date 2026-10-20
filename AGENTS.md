# AGENTS.md

Guidance for coding agents (Claude Code, Codex, and others) working in this repository. `CLAUDE.md`
imports this file, so this is the single source of truth. Keep it short: detailed architecture notes
live in [`docs/agents/`](docs/agents/), one file per subsystem (see "Architecture docs" below).

**Before you change a subsystem, read its doc.** The docs explain why the code is shaped the way it is:
the invariants, the past bugs, and the trade-offs. You can't get that from reading the code alone.

## What this project is

A pygame tower-defense game built as a roguelike deckbuilder. `python main.py` is the entry point. The
source lives in eight domain packages one level under the repo root (`core/`, `entities/`, `world/`,
`run/`, `progression/`, `persistence/`, `presentation/`, `support/`). See
[core-game.md](docs/agents/core-game.md) "Organized into folders".

## Commands

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python main.py                     # run the game
python main.py --unlimited-gold    # debug flag -- every purchase always succeeds, gold never spent
python main.py --editor            # launch straight into the map editor (also reachable via E from the menu)

pytest                             # full suite (~11s, headless)
pytest tests/test_run.py           # one file
pytest tests/test_grid.py::test_non_path_cell_is_buildable   # one test
pytest -v --cov=. --cov-report=term-missing --cov-fail-under=98   # what CI runs

ruff check .                       # lint -- CI gate

mypy run/relics.py run/run_map.py run/events.py run/shop.py support/rng_sampling.py run/difficulty.py world/economy.py progression/run_history.py persistence/json_io.py progression/threshold_unlocks.py progression/meta_progression.py run/run_state.py run/card_pool.py run/run_escalation.py progression/progress.py progression/achievements.py run/rewards.py run/potions.py run/ascension.py run/commanders.py run/elite_affixes.py run/veterancy.py run/modules.py progression/hints.py progression/service_record.py run/challenges.py run/endless_mutators.py run/abilities.py support/palette.py   # strict type check -- only the annotated modules; CI gate

python tools/flow_check.py         # end-to-end bot run per Commander; run after changing node types, reward/act flow or save state
python tools/tower_bench.py        # dev-only tower balance bench
python tools/perf_bench.py         # dev-only frame-time bench + determinism fingerprint; run before/after a perf change
python tools/balance_sim.py        # dev-only competent-bot run simulator; run after a difficulty/wave tuning change

pyinstaller --onedir --name td --add-data "assets:assets" main.py   # local Linux release build -- see docs/agents/release.md
```

## CI gates

`.github/workflows/tests.yml` (every push/PR) and `release.yml` (before building a `v*` tag) both run
`ruff check .`, the strict mypy module list above, and pytest with `--cov-fail-under=98`.

The mypy module list is kept by hand in **four places**: `pyproject.toml`'s
`[[tool.mypy.overrides]]`, the Commands block above, `tests.yml`, and `release.yml`.
`tests/test_agent_docs.py` fails if they drift apart. When you annotate a new module, add it to all
four (see [tooling.md](docs/agents/tooling.md) "Extending the strict list").

## Git workflow

- `main` is the only long-lived branch. Feature branches and PRs target it, and release tags are cut
  from it. (The old `overhaul/roguelike-deckbuilder` working branch was folded into `main`.)
- `.claude/` (local skills and settings) is gitignored on purpose. Never commit it.

## Must-know rules

- **The game is a roguelike deckbuilder, and the run loop is the main loop.** Playing a level on its
  own is Practice (always `sandbox=True`, earns nothing). See [run-loop.md](docs/agents/run-loop.md)
  and [run-map.md](docs/agents/run-map.md).
- **Towers are the cards. There is no card deck.** Never add a deck, hand or energy system, and never
  copy Slay the Spire's names or mechanics one-to-one.
- **Player-facing names differ from some code identifiers.** The code names are kept for save
  compatibility:

  | Code identifier | Player-facing name |
  |---|---|
  | `ascension` | Gauntlet |
  | `is_boss_relic` | trophy relic |
  | `rest` node / Smith | Outpost / Forge |
  | `BLESSING` | Orders from Command |
  | `COMPENDIUM` | Field Manual |
  | `potion_belt` | Bandolier |
  | `GameState.DRAFT` | the Shop screen |

- **Content is registries, not conditionals.** `TOWER_TYPES`, `ENEMY_TYPES`, `LEVELS`, `RELICS`
  (curses and boss relics included, via flags), `EVENTS`, `POTIONS`, `COMMANDERS`, `AFFIXES`,
  `MODULES`, `RESONANCES`, `ASCENSION_LEVELS` (a tuple), `ACHIEVEMENTS` and the `*_META_UNLOCKS` are
  `{key: ...}` dicts. To add content, write a new class or entry plus one registry line. Never add
  branches to the code that consumes a registry.
- **Imports are always fully qualified** (`from entities.tower import TOWER_TYPES`), never relative.
  Every package sits exactly one level under the repo root, and `json_io.module_relative_path()`
  depends on that depth.
- **`Game._load_level_object()` is the one place every level load goes through.**
- **Simulation code never calls presentation code or `Economy`.** `Tower`/`Enemy`/`Projectile` append
  to per-frame event lists, and `Game.update()` drains them (see
  [presentation.md](docs/agents/presentation.md) "Visual effects").
- **Progress, achievement and meta-progression counters are bumped only from `Game`.** Never bump them
  from `Tower`/`Enemy`/`Economy`, because resuming a save would count them twice. Sandbox never
  records progress.
- **A new relic field that `Tower.update()` tags onto projectiles needs a matching copy in
  `OverloadCannonTower.update()`'s duplicate block** (see [towers.md](docs/agents/towers.md)
  "Overload Cannon's charge-and-burst cycle").
- **Runs autosave on every map visit and node entry** (`save_state.save_map_checkpoint`). A choice that
  resolves on a node commits it (`Game._commit_node`), so Continue can't reopen it. See
  [persistence.md](docs/agents/persistence.md) "Map checkpoints (autosave)".
- **Run RNG is re-derived on demand** with `Game._run_rng(run, stream, key)`, keyed by node id, never by
  row number. No RNG state is ever serialized. New draws go *after* existing ones on a stream, so
  existing seeds keep their offers.
- **Tests run headless** (SDL dummy driver, set in `tests/conftest.py`). Inject every on-disk JSON path
  (`Game(progress_path=..., ...)`) so tests never touch real player files.

## Architecture docs

| Doc | Read before touching |
|---|---|
| [core-game.md](docs/agents/core-game.md) | folder layout, `Game`, its `Renderer`/`InputHandler`/`ProgressTracker` slices, toasts, Field Notes hints |
| [run-loop.md](docs/agents/run-loop.md) | `RunState`, `start_new_run`, node flow, floor clear/permadeath, `_run_rng`, Daily Run, acts, Ascension, Commanders |
| [run-map.md](docs/agents/run-map.md) | `run/run_map.py`, node types (Combat/Elite/Shop/Event/Rest/Treasure/Boss/Armory/Proving Grounds), map screen, rewards, potions, elite affixes, the opening blessing |
| [relics.md](docs/agents/relics.md) | `run/relics.py`: effect shapes, `compose_relic_modifiers` stacking rules, tower-exclusive relics, curses, boss relics |
| [economy-shop.md](docs/agents/economy-shop.md) | battle gold vs shop currency, `run/shop.py`, `--unlimited-gold` |
| [towers.md](docs/agents/towers.md) | leveling/specialization, Support two-pass update, Overload Cannon, Siphon, targeting index, results table, veterancy, traps, modules, Barricade, resonances, Harpoon, Brazier cone attacks |
| [enemies.md](docs/agents/enemies.md) | registries, boss mechanics, `IS_BOSS`, Mark, Corrosive Poison, Sappers/Burrowers, knockback resistance, poison credit, Burning |
| [waves-difficulty.md](docs/agents/waves-difficulty.md) | `WaveManager` states, endless mode, difficulty, Sandbox/Practice, settings screen |
| [grid-paths.md](docs/agents/grid-paths.md) | tile vs subtile coords, footprints, path topology (forest rule), `sample_route` |
| [ui-input.md](docs/agents/ui-input.md) | keybindings, stats panel click-routing, HUD layout, Field Manual, Service Record, relics overlay |
| [editor.md](docs/agents/editor.md) | map editor, wave editor, custom level files, level browser |
| [persistence.md](docs/agents/persistence.md) | `json_io`, progress/achievements/meta-progression/run history/service record/save-state/keybindings files |
| [presentation.md](docs/agents/presentation.md) | visual-effects drain idiom, audio/`SoundManager`, `AssetManager` |
| [tooling.md](docs/agents/tooling.md) | ruff/coverage config, incremental mypy, test layout, dev tools |
| [release.md](docs/agents/release.md) | PyInstaller `--onedir` release workflow |

## Keeping these docs healthy

- Put new architecture notes in the matching doc under a `##` heading, not in this file.
- Cross-reference a section as ``[<file>.md](<file>.md) "Heading"`` inside `docs/agents/`, or as
  `docs/agents/<file>.md "Heading"` from code comments. Never write "see X above/below": sections move.
- Name things (`Game._construct_tower`) rather than citing line numbers, which go stale.
- Don't hard-code registry sizes ("74 relics"). The registry is the source of truth.
- `tests/test_agent_docs.py` checks that every doc is indexed here, that every quoted cross-reference
  resolves to a real heading, and that the four mypy lists match.
