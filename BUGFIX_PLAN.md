# Code-review bugfix plan (2026-08-29 /code-review run)

Tracks the 15 findings from the `/code-review` run after merging all feature branches.
Each checkbox below becomes its own commit on `main`, with a regression test, so progress
survives even if the session gets interrupted mid-way (per-commit, not all-or-nothing).

Run `pytest -q` after every commit before moving on.

## Status

- [x] 1. `waves.py:245` -- final wave never increments `wave_index`, undercounts `waves_survived`.
      Fix: increment `wave_index` in `_advance_after_clear`'s non-endless DONE branch too.
- [ ] 2. `enemy.py:354` -- boss enrage can *reduce* speed on Hard once `speed` already exceeds
      `max_speed` (difficulty multiplier applied post-construction, never re-clamped).
      Fix: `WaveManager._spawn_enemy` clamps `enemy.speed` to `enemy.max_speed` after applying
      `enemy_speed_multiplier`, not just at `Enemy.__init__` time.
- [ ] 3. `game.py:71` -- `achievement_toasts` never reset in `_load_level_object`, can bleed
      into the next level. Fix: reset it alongside the other per-level lists.
- [ ] 4. `game.py:1087` -- `levels_cleared` achievement bump nested inside the built-in-only
      `isinstance(current_level_id, int)` guard, so custom levels never count.
      Fix: split the guard -- sandbox gates both, isinstance gates only `progress.mark_level_cleared`.
- [ ] 5. `achievements.py:65` -- `campaign_complete` keyed off a naive incrementing counter,
      gameable by replaying one already-cleared level repeatedly.
      Fix: new `achievements.set_counter()` (monotonic max, not +=) driven by
      `len(self.progress)` (distinct built-in levels, from `progress.py`'s own dict) instead.
- [ ] 6. `game.py:795` -- `if not self.sandbox:` hand-repeated at 6 call sites instead of once.
      Fix: move the guard inside `_record_achievement` itself.
- [ ] 7. `game.py:1017` -- duplicated `ExpandingRing` construction branches (splash vs. not).
      Fix: pick `(max_radius, duration)` once, single `.append()`.
      (Bundled with 3/4/5/6/9 below -- same `update()`/achievements region, one commit.)
- [ ] 8. `achievements.py:109` -- `bump()` does sync file I/O per kill; a multi-kill splash/chain
      hit does N round-trips in one frame.
      Fix: accumulate kills this frame in `update()`, one `_record_achievement("kills", n)` call.
- [ ] 9. `projectile.py:144` -- `damage_dealt` credited with nominal shot damage even when
      armor/shield absorbed part of it before HP.
      Fix: `Enemy.take_damage()`/`ShieldedEnemy`/`BossEnemy` all return the amount actually
      applied; `Projectile._apply_hit_effects` credits that instead of `self.damage`. Update
      `FakeEnemy`/`KillableFakeEnemy` test doubles in `tests/test_projectile.py` to match.
- [ ] 10. `game.py:363` -- corrupt-but-valid-JSON save crashes (`ValueError`/`KeyError`) on
      Continue instead of degrading gracefully, contradicting `load_run()`'s own docstring.
- [ ] 11. `game.py:371` -- `resume_saved_run()` zeroes every tower's lifetime stats and drops
      `sold_towers` entirely.
      Fix (bundled with 10 and 13): `save_state.save_run()` also serializes
      shots_fired/shots_hit/damage_dealt/kills and a `sold_towers` list; `resume_saved_run`
      restores both via a shared `_tower_from_save_data()` helper.
- [ ] 12. `game.py:371` (dup line ref) -- `resume_saved_run` duplicates `try_place_tower`'s
      construct-and-register sequence. Fix: shared `_register_tower()` helper.
- [ ] 13. `progress.py:20` -- the same "missing/corrupt JSON -> fallback" boilerplate hand-copied
      4x (progress.py, player_settings.py, achievements.py, save_state.py).
      Fix: new `json_io.load_json_with_fallback()` shared helper, all four delegate to it.
      Bundle with 10/11/12 since save_state.py is already being touched there.
- [ ] 14. `levels.py:246` -- Level 6 hand-builds its path inline instead of using this same diff's
      own `_multi_lane_level()` helper (used by Levels 7-9).
- [ ] 15. `game.py:1101` -- `has_saved_run()` stats the filesystem every render() frame on the
      menu. Fix: cache as `self.has_saved_run`, refreshed only at the 3 points that change it
      (save_run/resume_saved_run/_delete_save_if_this_run_was_resumed).

## Commit grouping (in order)

1. [x] waves.py wave_index fix (#1) + test
2. [ ] enemy speed-cap fix (#2) + test
3. [ ] achievements/update() region: #3, #4, #5, #6, #7, #8 + tests (biggest chunk)
4. [ ] damage_dealt accounting fix (#9) + enemy.py/projectile.py + test doubles
5. [ ] save/resume fixes: #10, #11, #12 + tests
6. [ ] json_io.py shared helper + #13 refactor (progress/player_settings/achievements/save_state)
7. [ ] levels.py Level 6 -> _multi_lane_level (#14)
8. [ ] has_saved_run caching (#15) + test

Delete this file once everything above is checked off and merged.
