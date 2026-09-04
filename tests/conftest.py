"""Shared fixtures and helpers for the Game-level test modules.

Game() opens a real pygame window, so this module forces the SDL dummy
video driver before pygame ever gets touched -- these tests must be able
to run headless in CI/sandboxes with no real display, same as the manual
smoke tests this project has been relying on during development. Living in
conftest.py means that happens once, before any test module in this
directory is imported, rather than each of them having to remember to do
it first (test_assets.py still does its own, since it stands alone).

The Game-level tests are split across three modules by concern, all of
them drawing their fixtures from here: test_game.py (state machine, input
handling, the update loop, rendering -- also the editor's own render/event-
dispatch smoke tests, which stay grouped with the rest of update()/
handle_events()'s coverage rather than moving to test_game_editor.py's
click-by-click one), test_run.py (the roguelike run loop -- floors,
drafts, permadeath, meta-progression), and test_game_editor.py (the map
editor, wave editor, and level browser screens as driven by Game).
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402
import pytest  # noqa: E402

import settings  # noqa: E402
from game import Game, GameState  # noqa: E402
from levels import Level  # noqa: E402


def make_game(tmp_path, prefix="", **kwargs):
    """Construct a real Game() with every injectable path pinned under
    `tmp_path` -- progress/settings/achievements/save/meta_progression/
    run_history, all six, always together. Game writes real progress on any
    non-sandbox level/floor clear (see progress.py), real settings on
    set_fullscreen()/set_difficulty() (see player_settings.py), real
    achievement counters on nearly every tower/kill/wave/level event (see
    achievements.py), a real in-progress save on save_run() (see
    save_state.py), real meta-progression counters on nearly every
    roguelike-run event (see meta_progression.py), and a real run outcome on
    a run's game-over, Daily Run included (see run_history.py) -- missing
    even one of the six here silently falls back to that module's real
    repo-root file, which is exactly the bug this factory exists to make
    impossible to write by hand. `prefix` distinguishes two instances
    sharing one `tmp_path` (e.g. "hard_"/"easy_"); `kwargs` forwards to
    Game() itself (e.g. unlimited_gold=True). Callers still own pygame.quit()
    -- this returns a live Game, not a fixture, since a few tests construct
    more than one or need a kwarg the `game` fixture below doesn't take."""
    return Game(
        progress_path=tmp_path / f"{prefix}progress.json",
        settings_path=tmp_path / f"{prefix}player_settings.json",
        achievements_path=tmp_path / f"{prefix}achievements.json",
        save_path=tmp_path / f"{prefix}save_state.json",
        meta_progression_path=tmp_path / f"{prefix}meta_progression.json",
        run_history_path=tmp_path / f"{prefix}run_history.json",
        **kwargs,
    )


@pytest.fixture
def game(tmp_path):
    g = make_game(tmp_path)
    yield g
    pygame.quit()


@pytest.fixture
def playing_game(game):
    game.state = GameState.PLAYING
    return game


def find_buildable_anchor(game, *, adjacent_to_path=False):
    """A buildable placement anchor (tile-aligned, i.e. (col, row) *
    SUBTILES_PER_TILE); optionally one touching the path, for tests that
    care about tower coverage rather than just placement."""
    n = settings.SUBTILES_PER_TILE
    for row in range(settings.GRID_ROWS):
        for col in range(settings.GRID_COLS):
            if not game.grid.is_buildable(col * n, row * n):
                continue
            if not adjacent_to_path:
                return col * n, row * n
            for dc, dr in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                if game.grid.is_path(col + dc, row + dr):
                    return col * n, row * n
    raise AssertionError("no matching buildable cell found")


def cell_center_px(cell, tile_size=settings.TILE_SIZE):
    col, row = cell
    return col * tile_size + tile_size // 2, row * tile_size + tile_size // 2


def finish_all_waves(game):
    """Fake "the last wave's last enemy just died" -- what update()'s own
    win-check reads (`wave_manager.all_waves_complete and not enemies`).
    Callers still call game.update(dt) themselves afterward; this only sets
    up the precondition, since some tests want that as its own separate
    step (e.g. to assert nothing happened yet)."""
    game.wave_manager.all_waves_complete = True
    game.enemies = []


def make_custom_level(level_id="custom-slug", name="Custom Level"):
    return Level(
        id=level_id,
        name=name,
        path_cells=frozenset({(0, 0), (1, 0), (2, 0)}),
        spawn_cells=((0, 0),),
        goal_cells=((2, 0),),
        wave_specs=[{(0, 0): {"grunt": 2}}],
    )


_REAL_MOUSE_GET_POS = pygame.mouse.get_pos  # saved once, before anything monkeypatches it


def mock_mouse_pos(pos):
    """Context-manager-free mouse mock: pygame.mouse.set_pos() is inert
    under the headless dummy driver, so tests that need a specific hover
    position monkeypatch get_pos() directly instead."""
    pygame.mouse.get_pos = lambda: pos


def clear_mouse_mock():
    # Restore the real get_pos rather than del'ing the attribute -- del
    # would just remove it outright (mock_mouse_pos *replaces* the dict
    # entry, it doesn't shadow it), leaving pygame.mouse with no get_pos
    # at all for every test that runs after this one in the same session.
    pygame.mouse.get_pos = _REAL_MOUSE_GET_POS


_REAL_KEY_GET_MODS = pygame.key.get_mods  # saved once, before anything monkeypatches it


def mock_key_mods(mods):
    """Same idea as mock_mouse_pos -- pygame.key.get_mods() reads real
    global keyboard state, which a headless test can't hold Ctrl/Shift/etc.
    on, so tests needing a specific modifier state (Ctrl+Z/Ctrl+Y) mock it
    directly instead."""
    pygame.key.get_mods = lambda: mods


def clear_key_mods():
    pygame.key.get_mods = _REAL_KEY_GET_MODS
