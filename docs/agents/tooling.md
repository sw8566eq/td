# Tooling: lint, coverage, type checking, tests

Lint/coverage config, the incremental strict-mypy list, how the test suite is laid out, and the
dev-only tools under `tools/`.

## Lint and coverage

`ruff` (lint) and `pytest-cov` are configured in `pyproject.toml`'s `[tool.ruff]`/`[tool.coverage.run]`
sections -- no formatter yet (a real `ruff format` pass on this codebase's own established style
reformats 73 of the ~82 tracked files, since its compact one-line registry entries rely on trailing
commas ruff format's line-fitting logic doesn't preserve; not worth that scale of mechanical churn).
`pytest-cov`'s own floor (`--cov-fail-under=98`, see AGENTS.md's Commands) was picked with real headroom below the
measured 98.68% -- 99% already fails today with zero slack -- enough that ordinary future work
shouldn't flake CI while still catching a genuine coverage regression. `entities/tower.py`'s
per-file `RUF012` ignore is deliberate: every `Tower` subclass's class-level `EXTRA_STATS`/
`SPECIALIZATIONS` dicts are read-only content tables (see [enemies.md](enemies.md) "Content is registries, not conditionals"), never mutated at runtime, which is exactly what that rule can't tell apart from a genuine
mutable-default footgun.

## Type checking is incremental, not repo-wide

`[tool.mypy]` in `pyproject.toml` is deliberately
permissive project-wide (`disallow_untyped_defs`/`check_untyped_defs` both `false`) since most of
this codebase -- pygame-facing code especially -- has no type hints yet; a `[[tool.mypy.overrides]]`
block opts specific modules into strict checking (`disallow_untyped_defs`/`disallow_incomplete_defs`/
`check_untyped_defs`/`warn_return_any` all `true`) as they get annotated, one at a time, rather than
annotating the whole codebase in one pass. `run/relics.py`/`run/run_map.py`/`run/events.py`/`run/shop.py` are the
first four: small, pygame-free, and already the most heavily-commented "content is data" modules in
the codebase, so typing their registries/functions was mostly transcribing what the docstrings
already said -- annotating them also caught one genuine pre-existing bug apiece in `run/relics.py`'s
`RelicModifiers` dataclass (`poison_effect`/`chain_effect`/`slow_effect`/`mark_effect: tuple = None`
and `knockback_effect: float = None` were all typed as required, non-`Optional` fields defaulting to
`None` -- mypy's `assignment` check catches exactly this class of "the type hint lied" bug, which
nothing else in this codebase's tooling would have). `follow_imports = "silent"` (also project-wide)
is what keeps checking one of these four from also re-reporting pre-existing errors in whatever
*they* import that isn't itself annotated (`run/relics.py` -> `progression/meta_progression.py`, `run/shop.py`/
`run/events.py` -> `run/card_pool.py` -> `entities/tower.py`, ...) -- without it, annotating one small module could
fail CI over an unrelated error several imports away, in a file nobody's touched yet. A parameter
typed against another module's dataclass (`run: RunState` in all three of `relics.relic_offer`/
`shop.build_offer`/`events.resolve_event_option`) is a real top-level import now (`run/run_state.py` was
annotated in a later pass -- see below -- and doesn't import any of these three back, so there's no
actual cycle); it started out imported under `if TYPE_CHECKING:` instead, back when `run/run_state.py`
itself was still unannotated, the standard shape for a type-only import when the imported module
isn't itself part of the strict-checked set yet. `rng_sampling.sample_up_to` -- the one shared helper
all three of `relics.relic_offer`/`run_map.generate_run_map`/`card_pool.draft_offer` call into -- is
fully typed too, via a PEP 695 generic (`def sample_up_to[T](...)`, not `typing.TypeVar`,
since `ruff`'s `UP047` prefers the newer syntax at this project's `target-version = "py313"`): left
untyped, every annotated caller's own `return sample_up_to(...)` would still resolve to `Any`
regardless of how carefully the caller itself was annotated, defeating the point.

### Extending the strict list

1. Annotate the module fully (`disallow_untyped_defs` etc. apply to it once listed).
2. Add it to all four copies of the list: `pyproject.toml`'s `[[tool.mypy.overrides]]` `module`
   list, AGENTS.md's Commands block, `.github/workflows/tests.yml`, and
   `.github/workflows/release.yml`. `tests/test_agent_docs.py` fails if they disagree.
3. Expect any unannotated helper whose result the module returns directly to need typing too (a
   `warn_return_any` / `no-any-return` error), the same way `sample_up_to` and
   `json_io.load_json_with_fallback` did. `follow_imports = "silent"` hides an unannotated callee's
   *own* errors, not that.

### History of the strict passes

The first pass is described above; the later ones, kept for the bugs they caught:

**Second pass.** It added five more modules: `support/rng_sampling.py` (already fully typed per the paragraph
above, just missing from the override list until now -- zero new annotation work), `run/difficulty.py`
(a typed `@dataclass DifficultyMode` already; just needed `DIFFICULTY_MODES`/`DIFFICULTY_ORDER`/
`DEFAULT_DIFFICULTY` themselves annotated), `world/economy.py` (plain `int`/`bool` signatures throughout,
its own docstring already said "pure Python, no pygame dependency"), `progression/run_history.py`, and
`persistence/json_io.py` -- the last one a genuine prerequisite, not an independent addition: annotating
`run_history.load_run_history() -> dict[int, int]` to `return load_json_with_fallback(...)` directly
surfaced a *fresh* `no-any-return` error, because `persistence/json_io.py` itself was still unannotated --
`follow_imports = "silent"` only suppresses re-reporting an unannotated callee's own errors, it
doesn't stop `warn_return_any` from firing when a strict function's return is directly the result of
an untyped call. This is the identical problem `sample_up_to` above already solves for
`run/relics.py`/`run/run_map.py`/`run/events.py`/`run/shop.py`; `json_io.load_json_with_fallback` needed the same PEP
695 generic treatment (`def load_json_with_fallback[T](path, transform: Callable[[Any], T], default:
Callable[[], T]) -> T`) for the same reason -- whenever a newly-annotated module's own return
expression is directly the result of calling an unannotated shared helper, expect to have to type
that helper too, not just the module on top.

**Third pass.** It added `progression/threshold_unlocks.py`/`progression/meta_progression.py`/`run/run_state.py`/`run/card_pool.py` --
this one edited already-strict files too, not just added new ones. `progression/threshold_unlocks.py` is generic
across `achievements.Achievement`/`progression/meta_progression.py`'s `MetaUnlock`/`RelicMetaUnlock`/
`LevelMetaUnlock`, none of which it can import without a cycle (`progression/achievements.py` already imports
*it*) -- typed structurally instead, via a `ThresholdUnlockEntry(Protocol)` (`counter: str`,
`goal: int`) and a `CountersState(TypedDict)`, with its `registry` parameters typed `Mapping[str,
ThresholdUnlockEntry]`, not `dict` -- `dict`'s invariance would otherwise reject
`meta_progression.ALL_UNLOCKS`'s own `dict[str, MetaUnlock | RelicMetaUnlock | LevelMetaUnlock]`.
Annotating `meta_progression.unlocked_relic_pool()` surfaced an over-widened parameter in the
already-strict `relics._default_relic_pool` (typed `str | None` even though `relic_offer()` always
coalesces `None` away with `meta_progression_path or meta_progression.META_PROGRESSION_PATH` before
ever calling it -- fixed to plain `str`; `card_pool._default_unlocked_pool` had the identical
coalesce-then-call shape and got the same fix, rather than reflexively copying the wrong one).
`run/run_state.py` had a genuine "type lied" bug, the same class v0.3.0's `RelicModifiers` catch was:
`current_node_id: str = None` was a required field silently defaulting to `None` -- fixed to
`str | None = None`, with `assert self.current_node_id is not None` added to `current_level_id`/
`current_row` to narrow it back down before indexing into the map (`core/game.py`'s own
`_available_node_ids` already treated it as Optional via `if run.current_node_id is None:`, so this
was never hypothetical -- just previously an uncaught `KeyError(None)` waiting to happen instead of a
clear assertion). Once `run/run_state.py` itself was annotated, `run/relics.py`/`run/shop.py`/`run/events.py`'s own
`if TYPE_CHECKING: from run_state import RunState` guards became unnecessary busywork -- no import
cycle actually exists (`run/run_state.py` only reaches `run/run_map.py`/`world/levels.py`/`support/rng_sampling.py`), so all
three now import `RunState` for real, same as any other cross-module type.

**Fourth pass.** It added `run/run_escalation.py`/`progression/progress.py`/`progression/achievements.py` -- all three pygame-free and
each needing only bare-function annotations, no dataclass fixes this time: `run/run_escalation.py`
already had a typed `@dataclass FloorEscalation`, so its four bare functions
(`_early_grace_factor`/`escalation_for_floor`/`apply_elite_multiplier`/`apply_boss_multiplier`) just
needed `int`/`FloorEscalation` signatures; `progression/progress.py` mirrors `progression/run_history.py`'s already-solved
`dict[int, int]`-via-`load_json_with_fallback` shape exactly, so it needed no fresh `json_io`-style
prerequisite of its own; `progression/achievements.py` mirrors `progression/meta_progression.py`'s own `Achievement`/
`load_*`/`bump()`/`set_counter()` shapes verbatim (both already share `progression/threshold_unlocks.py`'s
mechanics). `progression/achievements.py`'s one unannotated import, `levels.LEVELS` (used only via
`len(levels.LEVELS)` for the `campaign_complete` achievement's own goal), needed no attention: `len()`
always resolves to a concrete `int` regardless of its argument's own inferred type, unlike
`progression/run_history.py`'s old problem where an untyped call's return value was forwarded directly.

Later passes (`run/rewards.py`, `run/potions.py`, `run/ascension.py`, `run/commanders.py`,
`run/elite_affixes.py`, `run/veterancy.py`, `run/modules.py`) joined later, all small and pygame-free;
their reasoning lives in the commits that added them.

## Headless tests and suite layout

`Game()` and some `AssetManager` tests open a real pygame window, so the SDL dummy video driver is
forced before pygame is ever imported (`os.environ.setdefault("SDL_VIDEODRIVER", "dummy")`) --
once in `tests/conftest.py` for every `Game`-level module, and again in `tests/test_assets.py`,
which stands alone. `pytest` runs headless with no extra setup anywhere, including CI.

The `Game`-level tests are split three ways by concern, all drawing fixtures (`game`/
`playing_game`) and helpers (`find_buildable_anchor`, `cell_center_px`, `make_custom_level`, the
`mock_mouse_pos`/`mock_key_mods` pairs) from `tests/conftest.py`: `tests/test_game.py` (state
machine, input handling, the update loop, rendering), `tests/test_run.py` (the roguelike run
lifecycle end to end), and `tests/test_game_editor.py` (the map editor, wave editor, and level
browser screens as `Game` drives them). `Editor` itself is still tested directly in
`tests/test_editor.py`.

## Test teardown keeps the mixer alive

The `game` fixture tears down with `conftest.quit_pygame_keeping_the_mixer()` (display + font only),
not `pygame.quit()`: under SDL's dummy audio driver `pygame.mixer.quit()` blocks ~0.2s joining its
audio thread, which made a full run ~160s of mostly waiting; skipping it brings the suite to ~11s.
`Game()`'s own `pygame.mixer.init()` is a no-op once the mixer is up, so no test observes the
difference. Tests about the mixer's own init/failure paths still call `pygame.quit()` themselves.

## Tower bench (`tools/tower_bench.py`)

A dev-only balance check, excluded from coverage (`tools/*` in `[tool.coverage.run] omit`): each
attacking tower type gets the same gold on the same floor at Act 1/2/3 depth, placed greedily by path
coverage, then every wave runs headless (Game built via `tests/conftest.make_game` in a temp dir, so no
real player files are touched). Prints leaks and damage per act; `--budget`, `--level`, `--towers`,
`--extra`, `--reinvest` (spend kill gold on the cheapest upgrade, else another tower, every 0.5s).
It's a crude mono-tower model for spotting outliers -- it found the Knockback stun-lock
fixed by stagger resistance (see [enemies.md](enemies.md) "Knockback stagger resistance").

## Flow check (`tools/flow_check.py`)

A dev-only, end-to-end state-machine check (excluded from coverage): a bot plays one whole run per
Commander -- random map nodes, building/upgrading in fights, rewards, Shops, Events, Outposts
(Rest/Forge/Drill/Move on), Armories, Treasures, occasional saves -- invulnerable in fights so it reaches
every act and the endless final boss. Prints each run's outcome and screen counts; exits non-zero on a
crash. Run it after changing node types, reward/act flow or save state.

## Performance bench (`tools/perf_bench.py`)

A dev-only frame-time bench, excluded from coverage. It builds the heaviest board the game realistically
reaches: the final act's endless boss floor (level 9 by default, three spawns), 80 towers placed
round-robin over every type nearest the path, each upgraded to max and every other one specialized,
`unlimited_gold`, near-infinite lives, and the live enemy count topped up to `--enemies` (300) every
frame from every non-final-boss species. After `--warmup` frames (600) it times `--frames` frames
(300) of `Game.update(1/60)` and `Game.render()` separately and prints mean/median/p95 ms.
`--relics` holds every non-curse relic (crit, chain, overkill, poison spread, burning ground);
`--coverage` turns on the V overlay; `--profile update|render|both` dumps cProfile's top functions.

**Determinism check.** The global `random` module and the run are seeded, so every run of the same
arguments builds the same board. The last line prints two hashes: `fingerprint` (every enemy's
type/hp/position, every tower's damage/kills/shots, projectile positions, gold, lives, wave, effect
counts, and the `random` state) and `frame` (the last rendered frame's pixels). A performance change
must leave both unchanged for every flag combination. To compare, extract the old commit with
`git archive <sha> | tar -x -C <dir>`, copy the current `tools/perf_bench.py` into it, and run both
with `--check`.

**Numbers from the first optimization pass.** Best of five alternating runs (median ms per frame), on a
6-core machine under load, so treat them as relative:

| Scenario | update before | update after | render before | render after |
|---|---|---|---|---|
| default (300 enemies) | 2.56 | 2.03 | 4.49 | 3.77 |
| `--enemies 500` | 6.03 | 4.14 | 6.14 | 5.15 |
| `--relics` | 3.07 | 2.59 | 8.68 | 6.15 |
| `--coverage` | 3.15 | 2.30 | 8.96 | 5.09 |

What changed, with each step's measured effect on the default scenario (means, quieter machine):

- Damage-number text surfaces cached instead of `font.render()` per label per frame: render 4.79 -> 3.92 ms.
  This was the top render cost, since late boards keep 500-5000 labels alive.
- Healer heals, ground fires, splash hits and chain/bounce/overkill hops query the spatial index instead
  of scanning every enemy: update 2.88 -> 2.51 ms. `EnemySpatialIndex.near()` returning a list instead of a
  generator: 2.51 -> 2.13 ms. The healer loop was the top update cost, O(healers x enemies).
- Impact-ring surfaces cached: most of the `--relics` render gain (which has about 100 rings alive).
- The coverage overlay's full-screen ring layer is redrawn only when a ring changes: `--coverage` render
  roughly halved.

Still on the table, not done: the per-kill-frame `achievements.json` write (`_record_achievement("kills")`
does a load-mutate-save on every frame with a kill, about one frame in four on this bench) and the blits
themselves, which now dominate render.
