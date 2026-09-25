"""Game's Settings/Display/Audio/Keybindings-persistence methods, extracted
into their own module -- the fourth slice of game.py's own god-object
decomposition (see renderer.py/input_handler.py/progress_tracker.py for the
first three, and CLAUDE.md's own note on the shape this pattern follows).

Same "only a real external caller or a direct test reference gets a
Game-level delegator" rule progress_tracker.py's own docstring already
argues for: of these 14 methods, 3 (apply_display_mode, _save_player_
settings, _save_keybindings) are called only by their own cluster siblings
and get no Game-level delegator at all; the other 11 keep one. No coverage
was orphaned by this move (every one of the 3 non-delegated methods is still
reached indirectly through a sibling that does have one), so no new
regression tests were needed for the extraction itself.

Unlike the 3 prior slices (all constructed late in Game.__init__, once
everything they read already exists), this cluster's own state is loaded
from disk and its display mode applied *before* pygame.display.set_caption()
and before self.clock/self.renderer/self.input_handler/self.progress_tracker
even exist -- so SettingsManager is constructed early, interleaved with
pygame.init(), not batched with the other three near the end of
Game.__init__. Its own __init__ does what Game.__init__ used to do inline
(load player_settings/keybindings, set the 8 non-screen attributes) and
finishes by calling its own apply_display_mode() to create game.screen,
preserving the exact original ordering (settings/keybindings loaded, then
pygame.init(), then the display created, then pygame.display.set_caption()).

SettingsManager holds a `game` reference rather than being handed each piece
of state individually, same reasoning as Renderer/InputHandler/
ProgressTracker -- these methods read/write game.fullscreen/sound_enabled/
sound_volume/difficulty/window_size/keybindings/keybind_message/
keybind_listening_for/time_scale/screen. TIME_SCALES/SOUND_VOLUME_STEP
deliberately stay as Game class attributes, not moved here
(tests/test_game.py references game.SOUND_VOLUME_STEP directly) -- every
method below reads game.TIME_SCALES/game.SOUND_VOLUME_STEP through
self.game, not a bare self.*, the one genuinely new wrinkle relative to the
3 prior slices, none of which needed to reference an owning-class constant.
"""

import pygame

from persistence import keybindings, player_settings
from run import difficulty


class SettingsManager:
    def __init__(self, game):
        self.game = game

        # Persisted player preferences -- fullscreen and difficulty were the
        # first genuinely cross-session prefs this game had (unlike
        # time_scale/unlimited_gold, which stay on Game itself), so they're
        # written through immediately on change rather than only on quit --
        # see set_fullscreen()/set_difficulty()/set_window_size() below.
        saved_settings = player_settings.load_settings(game.settings_path)
        game.fullscreen = saved_settings["fullscreen"]
        game.sound_enabled = saved_settings["sound_enabled"]
        game.sound_volume = saved_settings["sound_volume"]
        # Windowed size -- read here so the very first apply_display_mode()
        # call below already restores it (today's actual prior behavior:
        # dragging the window to a new size was never persisted across a
        # relaunch at all; see set_window_size()/the VIDEORESIZE handler for
        # how this now stays current, preset click or organic drag alike).
        # Meaningless while fullscreen, same as a drag already being
        # ignored there -- see apply_display_mode's own docstring.
        game.window_size = tuple(saved_settings["window_size"])
        # Which difficulty.DIFFICULTY_MODES entry is currently active --
        # read at _load_level_object time, so changing it mid-level has no
        # effect until the next load_level()/reset() (same "applies on next
        # load" semantics unlimited_gold already has).
        game.difficulty = saved_settings["difficulty"]
        if game.difficulty not in difficulty.DIFFICULTY_MODES:
            game.difficulty = difficulty.DEFAULT_DIFFICULTY

        # Same injectable-path convention as settings_path, kept as a
        # genuinely separate file/module from player_settings.py rather
        # than one more key in that file's own dict -- see keybindings.py's
        # own docstring for why key remapping only covers this one small
        # registry of actions, not every input_handler.py keydown check.
        game.keybindings = keybindings.load_bindings(game.keybindings_path)
        # GameState.KEYBINDS' own transient UI state: which action (if any)
        # is currently waiting for its next keydown to become its new
        # binding, and the last outcome to show on screen ("Rebound.",
        # "Esc is reserved...", "Already used by ..."). Both reset fresh on
        # _enter_keybinds(), same "computed fresh, not left stale from a
        # previous visit" spirit as draft_choices/current_event on Game.
        game.keybind_listening_for = None
        game.keybind_message = None

        self.apply_display_mode()

    def apply_display_mode(self, size=None):
        """(Re)create game.screen for the current game.fullscreen setting,
        at `size` pixels -- defaults to game.window_size (the persisted
        windowed size, itself defaulting to settings.SCREEN_WIDTH/HEIGHT --
        see player_settings.DEFAULTS). Overridden explicitly by
        set_window_size() (a Settings-screen preset click) and by
        handle_events()'s pygame.VIDEORESIZE case (an organic drag) -- both
        also update game.window_size itself, so the *next* bare call here
        (e.g. toggling fullscreen back off) still lands on whatever size the
        player last actually chose, not silently back to the hardcoded
        default.

        pygame.SCALED (rendering at a fixed logical resolution, letterboxed
        by SDL to whatever physical size the window becomes) was the first
        choice here -- every Rect/pygame.mouse.get_pos() call in ui.py/
        game.py would have kept working unmodified, since pygame reports
        mouse coordinates in logical space under SCALED. Dropped: SCALED
        allocates an SDL renderer, and constructing a second Game in the
        same process without an intervening pygame.quit() -- which several
        tests do, and which is otherwise perfectly safe -- fails with
        "failed to create renderer" under the SDL dummy video driver this
        whole suite runs under. Plain RESIZABLE has no such renderer and
        needs no such teardown; the tradeoff is that dragging the window to
        a non-16:PLAY_WIDTH+PANEL_WIDTH:9-ish aspect ratio just shows
        more/less background (handled by re-running set_mode() at the new
        size on VIDEORESIZE, same as this method's own default case) rather
        than rescaling the content."""
        game = self.game
        flags = pygame.RESIZABLE
        if game.fullscreen:
            flags |= pygame.FULLSCREEN
        game.screen = pygame.display.set_mode(size or game.window_size, flags)

    def set_fullscreen(self, value):
        game = self.game
        game.fullscreen = bool(value)
        self.apply_display_mode()
        self._save_player_settings()

    def set_sound_enabled(self, value):
        game = self.game
        game.sound_enabled = bool(value)
        game.audio.set_enabled(game.sound_enabled)
        self._save_player_settings()

    def set_sound_volume(self, value):
        game = self.game
        game.sound_volume = max(0.0, min(1.0, value))
        game.audio.set_volume(game.sound_volume)
        self._save_player_settings()

    def adjust_sound_volume(self, direction):
        """direction is +1 or -1 -- one Settings-screen Volume -/+ click's
        worth of change, clamped by set_sound_volume itself so repeatedly
        clicking past either extreme is a harmless no-op rather than
        something this method also needs to guard against."""
        game = self.game
        self.set_sound_volume(game.sound_volume + direction * game.SOUND_VOLUME_STEP)

    def set_difficulty(self, key):
        game = self.game
        if key in difficulty.DIFFICULTY_MODES:
            game.difficulty = key
            self._save_player_settings()

    def set_window_size(self, size):
        """A Settings-screen preset click -- see the VIDEORESIZE handler in
        handle_events() for the other way game.window_size changes (an
        organic drag), which persists through this same field/save call."""
        game = self.game
        if game.fullscreen:
            return  # meaningless while fullscreen, same as a drag already being ignored there
        game.window_size = tuple(size)
        self.apply_display_mode(game.window_size)
        self._save_player_settings()

    def _save_player_settings(self):
        game = self.game
        player_settings.save_settings(
            {
                "fullscreen": game.fullscreen,
                "sound_enabled": game.sound_enabled,
                "sound_volume": game.sound_volume,
                "difficulty": game.difficulty,
                "window_size": list(game.window_size),
            },
            game.settings_path,
        )

    def _enter_keybinds(self):
        from core.game import GameState  # see module docstring

        game = self.game
        game.state = GameState.KEYBINDS
        game.keybind_listening_for = None
        game.keybind_message = None

    def rebind_action(self, action, key, mods):
        """Apply a captured (key, mods) as `action`'s new binding, or
        reject it -- leaving the existing binding untouched -- if the key
        is globally reserved (keybindings.RESERVED_KEYS) or already used by
        another action in the same dispatch group (keybindings.
        find_conflict); same "reject silently, don't crash" precedent
        Game.try_place_tower's own unbuildable-spot case sets, except this
        one does set a message (game.keybind_message) either way, since
        GameState.KEYBINDS has nothing else on screen to show the player
        *why* a click didn't do what they expected. Returns whether the
        rebind actually applied, mainly for tests."""
        game = self.game
        if keybindings.is_reserved(key):
            game.keybind_message = "Esc is reserved and can't be rebound."
            return False
        fixed_conflict = keybindings.fixed_key_conflict(action, key)
        if fixed_conflict is not None:
            game.keybind_message = f"Already used by the pause menu's {fixed_conflict}."
            return False
        conflict = keybindings.find_conflict(game.keybindings, action, key, mods)
        if conflict is not None:
            game.keybind_message = f"Already used by {keybindings.ACTION_LABELS[conflict]}."
            return False
        game.keybindings[action] = (key, mods)
        self._save_keybindings()
        game.keybind_message = f"{keybindings.ACTION_LABELS[action]} rebound."
        return True

    def reset_keybindings(self):
        game = self.game
        game.keybindings = dict(keybindings.DEFAULT_BINDINGS)
        self._save_keybindings()
        game.keybind_message = "Reset to defaults."

    def _save_keybindings(self):
        game = self.game
        keybindings.save_bindings(game.keybindings, game.keybindings_path)

    def set_time_scale(self, scale):
        game = self.game
        if scale in game.TIME_SCALES:
            game.time_scale = scale

    def cycle_time_scale(self):
        game = self.game
        index = game.TIME_SCALES.index(game.time_scale)
        game.time_scale = game.TIME_SCALES[(index + 1) % len(game.TIME_SCALES)]
