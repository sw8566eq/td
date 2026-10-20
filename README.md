# Tower Defense

[![Tests](https://github.com/sw8566eq/td/actions/workflows/tests.yml/badge.svg)](https://github.com/sw8566eq/td/actions/workflows/tests.yml)

A roguelike deckbuilder tower defense game built with Python + Pygame.

You don't pick a level and beat it -- you start a **run**: a seeded, fully-visible branching map of
floors (combat fights, a shop, random events, rest stops, treasure, and a final boss), played with a
small pool of towers you grow by **drafting** cards as you go. Lives carry from floor to floor; gold
resets fresh every floor, but whatever you don't spend converts into a second, persistent currency you
spend at the Shop. Enemies escalate as you descend, and losing your last life ends the run for good.
What you unlock along the way -- towers, relics, levels -- sticks around for every run after it.

## Play it

Grab a pre-built Linux binary from the [Releases page](https://github.com/sw8566eq/td/releases),
extract it and run `./td/td`. Keep the whole `td/` folder together: it bundles its own Python runtime
and assets, and your progress and saves are written there too.

Or run it from source:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

`--editor` launches straight into the map editor, and `--unlimited-gold` is a debug flag that makes
every purchase succeed without spending gold.

## How to play

- **Start a run** from the main menu and pick a **Commander**, which sets your three starter towers,
  a starting relic and a once-per-few-waves ability (`F`).
- **Pick a path** up the map. Each node is a fight, an Elite, a Shop, an Event, an Outpost, Treasure
  or more, and the last row is a boss. A run is three acts.
- **Defend each floor**: click a tower in the bottom bar, then click the map to place it. Click a
  placed tower to upgrade, specialize, move or sell it. `Space` starts or skips to the next wave.
- **Win fights to grow your run**: new towers, relics, potions and modules.
- **Lose your last life and the run is over**, but unlocks carry over to the next one.

`H` on the main menu opens an in-game How to Play screen, and `K` opens the Field Manual, which
describes every relic, potion and enemy.

## Learn more

The [player guide](docs/guide/README.md) covers everything in depth: [runs](docs/guide/runs.md),
[towers](docs/guide/towers.md), [relics](docs/guide/relics.md),
[enemies and levels](docs/guide/enemies-and-levels.md), [controls](docs/guide/controls.md),
[modes and progression](docs/guide/modes-and-progression.md) and the
[map editor](docs/guide/map-editor.md).

To add content or work on the code, start with [Contributing](docs/guide/contributing.md) and
[`AGENTS.md`](AGENTS.md). Run the tests with `pytest`.

## License

The game's code is MIT-licensed -- see [`LICENSE`](LICENSE). The bundled art and audio are separate
CC0 assets from Kenney and Huntrt (see [Art](docs/guide/contributing.md#art) and
[Sound](docs/guide/contributing.md#sound)).
