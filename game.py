"""Game state machine and main loop."""

import dataclasses
import sys
from enum import Enum, auto

import pygame

import achievements
import difficulty
import effects
import persistence
import player_settings
import progress
import save_state
import settings
import ui
from assets import AssetManager
from economy import Economy
from editor import SHAPE_TOOLS, Editor, EditorTool
from grid import Grid
from levels import LEVELS
from tower import TOWER_TYPES
from waves import WaveManager, WaveState


class GameState(Enum):
    MENU = auto()
    PLAYING = auto()
    PAUSED = auto()
    GAME_OVER = auto()
    VICTORY = auto()
    EDITOR = auto()
    WAVE_EDITOR = auto()
    LEVEL_SELECT = auto()
    SETTINGS = auto()
    ACHIEVEMENTS = auto()


class Game:
    # Simulation speed multipliers cycled through by the HUD's speed button
    # (or pressing 1/2/3 directly) -- see cycle_time_scale()/set_time_scale().
    TIME_SCALES = (1.0, 2.0, 3.0)

    def __init__(self, unlimited_gold=False, progress_path=None, settings_path=None,
                 achievements_path=None, save_path=None):
        self.unlimited_gold = unlimited_gold  # debug flag -- see main.py --unlimited-gold
        # A sticky player preference for the whole session, not reset by
        # reset()/load_level() -- same idea as unlimited_gold not being tied
        # to any one level. Unlike fullscreen/difficulty below, this one is
        # deliberately NOT persisted across sessions.
        self.time_scale = 1.0

        # Injectable path, same idea as persistence.save_level's own
        # `directory` param -- lets tests point this at a tmp_path instead
        # of ever touching the real repo-root progress.json. self.progress
        # is refreshed from disk in _enter_level_select() too (same
        # "always re-read" convention list_custom_levels() follows), not
        # just here.
        self.progress_path = progress_path or progress.PROGRESS_PATH
        self.progress = progress.load_progress(self.progress_path)

        # Same injectable-path convention as progress_path above.
        # achievements_state is re-read fresh whenever the Achievements
        # screen is (re-)entered (see _enter_achievements()), same "always
        # re-read" spirit as self.progress in _enter_level_select().
        self.achievements_path = achievements_path or achievements.ACHIEVEMENTS_PATH
        self.achievements_state = achievements.load_achievements(self.achievements_path)
        self.achievements_back_rect = ui.build_achievements_back_rect()
        # Newly-unlocked-achievement toasts -- see _record_achievement().
        self.achievement_toasts = []

        # Same injectable-path convention as progress_path/achievements_path
        # above. True only between resume_saved_run() and that resumed
        # run's own eventual GAME_OVER/VICTORY (see update()'s win/loss
        # branches) -- what actually gates deleting the save file once it's
        # been played out, so a fresh, unrelated session's own victory can
        # never delete some other still-valid in-progress save. Every
        # _load_level_object() call resets this to False first (see
        # there); resume_saved_run() is the one caller that sets it back to
        # True afterward.
        self.save_path = save_path or save_state.SAVE_PATH
        self._resumed_from_save = False

        # Persisted player preferences -- fullscreen and difficulty are the
        # first genuinely cross-session prefs this game has (unlike
        # time_scale/unlimited_gold above), so they're written through
        # immediately on change rather than only on quit -- see
        # set_fullscreen()/set_difficulty().
        self.settings_path = settings_path or player_settings.SETTINGS_PATH
        saved_settings = player_settings.load_settings(self.settings_path)
        self.fullscreen = saved_settings["fullscreen"]
        # Which difficulty.DIFFICULTY_MODES entry is currently active --
        # read at _load_level_object time, so changing it mid-level has no
        # effect until the next load_level()/reset() (same "applies on next
        # load" semantics unlimited_gold already has).
        self.difficulty = saved_settings["difficulty"]
        if self.difficulty not in difficulty.DIFFICULTY_MODES:
            self.difficulty = difficulty.DEFAULT_DIFFICULTY

        pygame.init()
        self.apply_display_mode()
        pygame.display.set_caption(settings.WINDOW_TITLE)
        self.clock = pygame.time.Clock()

        self.font = pygame.font.SysFont(None, 32)
        self.small_font = pygame.font.SysFont(None, 22)
        self.tiny_font = pygame.font.SysFont(None, 16)  # tower upgrade badges

        self.assets = AssetManager()
        self.settings_rects = ui.build_settings_rects()
        self.button_rects = ui.build_button_rects()
        self.skip_button_rect = ui.build_skip_button_rect()
        self.speed_button_rect = ui.build_speed_button_rect()
        self.targeting_button_rect = ui.build_targeting_button_rect()
        self.upgrade_button_rect = ui.build_upgrade_button_rect()
        self.specialize_button_rects = ui.build_specialize_button_rects()
        self.sell_button_rect = ui.build_sell_button_rect()

        # The editor instance persists for the whole session (not just
        # while GameState.EDITOR/WAVE_EDITOR is active) so leaving it to
        # playtest and coming back preserves whatever's been painted/
        # configured so far.
        self.editor = Editor()
        self.editor_tool_rects = ui.build_editor_tool_rects()
        self.editor_action_rects = ui.build_editor_action_rects()
        # Set by the wave editor's Save action -- shown in its sidebar so
        # the player knows where the file landed (custom_levels/), e.g. to
        # go find and share it with someone else.
        self.last_saved_path = None
        # Unlike the rect sets above, wave tabs depend on how many waves
        # currently exist, so they're rebuilt on demand (see
        # _wave_tab_rects()) rather than cached once here.
        self.wave_unit_rects = ui.build_wave_unit_rects()
        self.wave_editor_action_rects = ui.build_wave_editor_action_rects()

        # Rebuilt each time _enter_level_select() runs -- see there for why
        # (the custom-levels list on disk can change between visits).
        # level_select_rects also gets rebuilt on scroll (see
        # _scroll_level_select) -- unlike every other cached rect set in
        # Game, its row positions depend on scroll_offset, not just on
        # what's currently listed.
        self.level_select_entries = []
        self.level_select_rects = {}
        self.level_select_thumbnails = {}
        self.level_select_purpose = "play"  # or "edit" -- see _enter_level_select
        self.level_select_locked_ids = set()  # built-in ids not yet unlocked -- see _enter_level_select
        self.level_select_scroll_offset = 0
        # Toggled by V while browsing to play (not edit); a level picked
        # while armed loads in endless/survival mode -- see
        # _handle_level_select_click. Reset to False every time the
        # browser is (re-)entered, same as scroll_offset.
        self.level_select_endless_armed = False
        # Same idea as the endless toggle above, but for Sandbox/Creative
        # mode (B, also "play"-only) -- independently armable/combinable
        # with endless, since infinite lives plus escalating waves is a
        # legitimate "just mess around" combo, not a conflict.
        self.level_select_sandbox_armed = False
        self._custom_levels_by_id = {}

        self.state = GameState.MENU
        self.running = True

        self.current_level_id = 1
        self.load_level(self.current_level_id)

    def load_level(self, level_id, endless=False, sandbox=False):
        self._load_level_object(LEVELS[level_id], endless=endless, sandbox=sandbox)
        self.current_level_id = level_id

    def load_custom_level(self, level, endless=False, sandbox=False):
        """Load a Level that isn't in the LEVELS registry -- an
        editor-authored level, whether freshly painted or reloaded from
        disk (see persistence.py). current_level_id becomes None so
        has_next_level()/advance_or_replay_level() know there's no
        registry entry to advance through."""
        self._load_level_object(level, endless=endless, sandbox=sandbox)
        self.current_level_id = None

    def _load_level_object(self, level, endless=False, sandbox=False, difficulty_override=None):
        # Sticky for this level, same as current_level_id -- reset()/
        # advance_or_replay_level() read this back so replaying/advancing
        # out of an endless run doesn't silently drop back into a normal,
        # finite-waves one. sandbox follows the identical pattern (see
        # Economy construction below and the win-check in update()).
        self.endless = endless
        self.sandbox = sandbox
        # Every level load starts "not resumed" by default -- only
        # resume_saved_run() (the one caller that also passes
        # difficulty_override) sets this back to True, after this method
        # returns. This is what stops an unrelated fresh level load (picked
        # from the menu/level-select while an old save from a different,
        # abandoned run still sits on disk) from later deleting that
        # unrelated save on its own eventual victory/game-over.
        self._resumed_from_save = False
        if endless:
            # Endless mode appends newly-generated waves straight onto
            # wave_specs as the run continues (see WaveManager.
            # _advance_after_clear) -- level.wave_specs must be this
            # Game's own private list, never LEVELS' shared registry
            # entry (a module-level singleton every Game/test in the
            # process holds the same object for), or an endless run would
            # permanently leak generated waves into every future
            # non-endless playthrough of the same built-in level.
            level = dataclasses.replace(level, wave_specs=list(level.wave_specs))
        self.level = level
        self.grid = Grid(
            settings.GRID_COLS, settings.GRID_ROWS, settings.TILE_SIZE,
            level.path_cells, level.spawn_cells, level.goal_cells, level.blocked_cells,
            subtiles_per_tile=settings.SUBTILES_PER_TILE,
            subtile_gap=settings.SUBTILE_GAP,
            subtile_gap_alpha=settings.SUBTILE_GAP_ALPHA,
        )
        mode = difficulty.DIFFICULTY_MODES[difficulty_override or self.difficulty]
        self.economy = Economy(
            round(level.starting_gold * mode.starting_gold_multiplier),
            round(level.starting_lives * mode.starting_lives_multiplier),
            unlimited_gold=self.unlimited_gold or sandbox,
            invulnerable=sandbox,
        )
        self.wave_manager = WaveManager(
            level, self.grid.tile_to_pixel_center,
            enemy_hp_multiplier=mode.enemy_hp_multiplier,
            enemy_speed_multiplier=mode.enemy_speed_multiplier,
            enemy_gold_multiplier=mode.enemy_gold_multiplier,
            endless=endless,
        )

        self.enemies = []
        self.towers = []
        # A tower sold mid-level is removed from self.towers (see
        # try_sell_tower) but its lifetime stats still belong in this
        # level's post-level results table -- kept here purely so
        # _tower_results() can still find it. Never touched otherwise; a
        # sold tower is already fully inert once off the grid.
        self.sold_towers = []
        self.projectiles = []
        self.damage_numbers = []
        self.impact_effects = []
        self.selected_tower_name = None
        self.selected_tower = None  # placed Tower instance pinned open in the stats panel
        # Whatever the stats panel showed as of the last render() -- see
        # _handle_panel_action_click for why clicks must use this instead
        # of re-deriving the subject from the click-time mouse position.
        self._last_panel_subject = None

    def apply_display_mode(self, size=None):
        """(Re)create self.screen for the current self.fullscreen setting,
        at `size` pixels -- defaults to the configured settings.SCREEN_
        WIDTH/HEIGHT; only ever overridden by handle_events()'s
        pygame.VIDEORESIZE case, once the player has actually dragged a
        non-fullscreen window to a new size.

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
        needs no such teardown; the tradeoff is that dragging the window
        to a non-16:PLAY_WIDTH+PANEL_WIDTH:9-ish aspect ratio just shows
        more/less background (handled by re-running set_mode() at the new
        size on VIDEORESIZE, same as this method's own default case)
        rather than rescaling the content."""
        flags = pygame.RESIZABLE
        if self.fullscreen:
            flags |= pygame.FULLSCREEN
        self.screen = pygame.display.set_mode(size or (settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT), flags)

    def set_fullscreen(self, value):
        self.fullscreen = bool(value)
        self.apply_display_mode()
        self._save_player_settings()

    def set_difficulty(self, key):
        if key in difficulty.DIFFICULTY_MODES:
            self.difficulty = key
            self._save_player_settings()

    def _save_player_settings(self):
        player_settings.save_settings(
            {"fullscreen": self.fullscreen, "difficulty": self.difficulty}, self.settings_path,
        )

    def set_time_scale(self, scale):
        if scale in self.TIME_SCALES:
            self.time_scale = scale

    def cycle_time_scale(self):
        index = self.TIME_SCALES.index(self.time_scale)
        self.time_scale = self.TIME_SCALES[(index + 1) % len(self.TIME_SCALES)]

    def reset(self):
        if self.current_level_id is None:
            # custom level: nothing in LEVELS to re-look-up
            self._load_level_object(self.level, endless=self.endless, sandbox=self.sandbox)
        else:
            self.load_level(self.current_level_id, endless=self.endless, sandbox=self.sandbox)
        self.state = GameState.MENU

    def has_next_level(self):
        if not isinstance(self.current_level_id, int):
            return False  # a custom (non-registry) level has no "next" to advance to
        return (self.current_level_id + 1) in LEVELS

    def advance_or_replay_level(self):
        """Called on winning: move to the next level if the registry has
        one, else replay the current (final) level from scratch. A custom
        (non-registry) level never has a next level -- has_next_level()
        guards that -- so this always just replays it."""
        if self.has_next_level():
            self.current_level_id += 1
            self.load_level(self.current_level_id, endless=self.endless, sandbox=self.sandbox)
        elif self.current_level_id is None:
            self._load_level_object(self.level, endless=self.endless, sandbox=self.sandbox)
        else:
            self.load_level(self.current_level_id, endless=self.endless, sandbox=self.sandbox)

    # --- Save/resume a run in progress ---

    def can_save_run(self):
        """Whether the current run is at a point save_run() can capture --
        only between waves (AWAITING_START/BETWEEN_WAVES), never
        mid-SPAWNING or once DONE -- see save_state.py's module docstring
        and WaveManager.restore() for why."""
        return self.wave_manager.state in (WaveState.AWAITING_START, WaveState.BETWEEN_WAVES)

    def save_run(self):
        """Persist the current run to disk for the pause menu's "Save &
        Quit" -- a no-op (returns False) unless can_save_run()."""
        if not self.can_save_run():
            return False
        save_state.save_run(self, self.save_path)
        return True

    def resume_saved_run(self, save_data):
        """Restore a run saved via save_run()/save_state.save_run() --
        reconstructed via _load_level_object() directly (never load_level()'s
        LEVELS[id] re-lookup, even for a built-in level id), so an endless
        run's already-appended escalation waves -- baked into
        save_data["level"] by persistence.level_to_dict/level_from_dict --
        are never silently discarded back to the registry's original,
        un-extended wave list. current_level_id is restored explicitly
        afterward, since _load_level_object() itself doesn't touch it (see
        load_level()/load_custom_level(), the two normal callers that do).

        Towers are rebuilt via TOWER_TYPES directly and Tower.upgrade()/
        specialize() called the right number of times/with the right key --
        never through try_upgrade_tower()/try_specialize_tower() -- so
        resuming never re-charges gold or re-bumps achievement counters for
        progress the player already paid for and was already credited with
        once, back when it first happened."""
        level = save_data["level"]
        self._load_level_object(
            level, endless=save_data["endless"], sandbox=save_data["sandbox"],
            difficulty_override=save_data["difficulty"],
        )
        self.current_level_id = save_data["current_level_id"]
        self.wave_manager.restore(save_data["wave_index"], save_data["wave_state"], save_data["between_wave_timer"])
        self.economy.gold = save_data["gold"]
        self.economy.lives = save_data["lives"]

        for tower_data in save_data["towers"]:
            tower_cls = TOWER_TYPES[tower_data["type"]]
            anchor_col, anchor_row = tower_data["anchor_col"], tower_data["anchor_row"]
            pixel_pos = self.grid.anchor_to_pixel_center(anchor_col, anchor_row)
            tower = tower_cls(anchor_col, anchor_row, pixel_pos)
            for _ in range(tower_data["level"] - 1):
                tower.upgrade()
            if tower_data["specialization"] is not None:
                tower.specialize(tower_data["specialization"])
            tower.targeting_mode = tower_data["targeting_mode"]
            self.towers.append(tower)
            self.grid.occupy(anchor_col, anchor_row, tower)

        self._resumed_from_save = True  # see __init__'s comment on this flag
        self.state = GameState.PLAYING

    def _continue_saved_run(self):
        """The main menu's "Continue" -- a no-op (stays on MENU) if the
        save file is missing or has since become corrupt, same defensive
        spirit as every other on-disk-data load in this codebase."""
        save_data = save_state.load_run(self.save_path)
        if save_data is not None:
            self.resume_saved_run(save_data)

    def run(self):
        while self.running:
            dt = self.clock.tick(settings.FPS) / 1000.0
            self.handle_events()
            self.update(dt)
            self.render()
        pygame.quit()
        sys.exit()

    # --- Input ---

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                self._handle_keydown(event.key)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.state == GameState.EDITOR:
                    self._handle_editor_click(event.pos)
                elif self.state == GameState.WAVE_EDITOR:
                    self._handle_wave_editor_click(event.pos)
                elif self.state == GameState.LEVEL_SELECT:
                    self._handle_level_select_click(event.pos)
                elif self.state == GameState.SETTINGS:
                    self._handle_settings_click(event.pos)
                elif self.state == GameState.ACHIEVEMENTS:
                    self._handle_achievements_click(event.pos)
                else:
                    self._handle_click(event.pos)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                self._handle_right_click()
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.state == GameState.EDITOR:
                self._handle_editor_mouse_up(event.pos)
            elif event.type == pygame.MOUSEMOTION and self.state == GameState.EDITOR:
                self._handle_editor_motion(event.pos, event.buttons)
            elif event.type == pygame.MOUSEWHEEL and self.state == GameState.LEVEL_SELECT:
                self._scroll_level_select(event.y)
            elif event.type == pygame.VIDEORESIZE and not self.fullscreen:
                # Only while windowed -- a fullscreen window resizing away
                # from the desktop resolution isn't something the player
                # actually did (see apply_display_mode's docstring for what
                # this makes dragging a windowed edge actually do).
                self.apply_display_mode(event.size)

    def _handle_keydown(self, key):
        if self.state == GameState.MENU:
            if key == pygame.K_ESCAPE:
                self.running = False
            elif key == pygame.K_e:
                self.state = GameState.EDITOR
            elif key == pygame.K_l:
                self._enter_level_select()
            elif key == pygame.K_s:
                self.state = GameState.SETTINGS
            elif key == pygame.K_a:
                self._enter_achievements()
            elif key == pygame.K_c and save_state.has_saved_run(self.save_path):
                self._continue_saved_run()
            else:
                self.state = GameState.PLAYING
        elif self.state == GameState.SETTINGS:
            if key == pygame.K_ESCAPE:
                self.state = GameState.MENU
        elif self.state == GameState.ACHIEVEMENTS:
            if key == pygame.K_ESCAPE:
                self.state = GameState.MENU
        elif self.state == GameState.EDITOR:
            if key == pygame.K_ESCAPE:
                self.state = GameState.MENU
            else:
                self._handle_editor_undo_redo_keydown(key)
        elif self.state == GameState.WAVE_EDITOR:
            if key == pygame.K_ESCAPE:
                self.state = GameState.EDITOR  # one step back, same as the Back-to-Path button
            else:
                self._handle_editor_undo_redo_keydown(key)
        elif self.state == GameState.LEVEL_SELECT:
            if key == pygame.K_ESCAPE:
                # Back to wherever this screen was entered from -- the
                # menu's L, or the editor's Load Map... (see
                # _enter_level_select's purpose param).
                self.state = GameState.MENU if self.level_select_purpose == "play" else GameState.EDITOR
            elif key == pygame.K_v and self.level_select_purpose == "play":
                # Arms/disarms endless/survival mode for whichever level
                # gets picked next -- meaningless while browsing to load a
                # map into the editor (purpose="edit"), so a no-op there.
                self.level_select_endless_armed = not self.level_select_endless_armed
            elif key == pygame.K_b and self.level_select_purpose == "play":
                # Arms/disarms Sandbox/Creative mode, same idea as V above.
                self.level_select_sandbox_armed = not self.level_select_sandbox_armed
        elif self.state == GameState.PLAYING:
            if key in (pygame.K_p, pygame.K_ESCAPE):
                self.state = GameState.PAUSED
            elif key == pygame.K_SPACE:
                self.wave_manager.skip_delay()
            elif key == pygame.K_1:
                self.set_time_scale(1.0)
            elif key == pygame.K_2:
                self.set_time_scale(2.0)
            elif key == pygame.K_3:
                self.set_time_scale(3.0)
        elif self.state == GameState.PAUSED:
            if key in (pygame.K_p, pygame.K_ESCAPE):
                self.state = GameState.PLAYING
            elif key == pygame.K_r:
                self.reset()
                self.state = GameState.PLAYING
            elif key == pygame.K_e and self.current_level_id is None:
                # Only offered (see ui.draw_pause_menu) while playing a
                # custom level -- self.editor still has whatever was
                # playtested, untouched, so this is just "stop playing,"
                # not a reload.
                self.state = GameState.EDITOR
            elif key == pygame.K_s and self.can_save_run():
                self.save_run()
                self.state = GameState.MENU
            elif key == pygame.K_q:
                self.running = False
        elif self.state == GameState.GAME_OVER:
            if key == pygame.K_ESCAPE:
                self.running = False
            elif key == pygame.K_r:
                self.reset()
                self.state = GameState.PLAYING
        elif self.state == GameState.VICTORY:
            if key == pygame.K_ESCAPE:
                self.running = False
            elif key == pygame.K_r:
                self.advance_or_replay_level()
                self.state = GameState.PLAYING

    def _handle_right_click(self):
        if self.state != GameState.PLAYING:
            return
        self.selected_tower_name = None
        self.selected_tower = None

    def _handle_editor_undo_redo_keydown(self, key):
        """Ctrl+Z/Ctrl+Y -- shared by both editor screens' keydown handling
        (GameState.EDITOR and WAVE_EDITOR), since both mutate the same
        self.editor. Routes through _handle_editor_undo_redo_action() so
        there's exactly one place that actually calls undo()/redo(),
        regardless of whether it was a keypress or an action-button click."""
        mods = pygame.key.get_mods()
        if key == pygame.K_z and mods & pygame.KMOD_CTRL:
            self._handle_editor_undo_redo_action("undo")
        elif key == pygame.K_y and mods & pygame.KMOD_CTRL:
            self._handle_editor_undo_redo_action("redo")

    def _handle_editor_undo_redo_action(self, action):
        """"undo"/"redo" -- shared by both editor screens' action bars
        (see _handle_editor_action/_handle_wave_editor_action) and by
        _handle_editor_undo_redo_keydown above. Returns True if `action`
        was one of these two, so a caller chaining more action checks
        after this one knows whether it's already been handled."""
        if action == "undo":
            self.editor.undo()
            return True
        if action == "redo":
            self.editor.redo()
            return True
        return False

    # --- Map editor ---

    def _handle_editor_click(self, pos):
        tool = ui.get_clicked_editor_tool(pos, self.editor_tool_rects)
        if tool is not None:
            self.editor.set_tool(tool)
            return

        action = ui.get_clicked_editor_action(pos, self.editor_action_rects)
        if action is not None:
            self._handle_editor_action(action)
            return

        if self.editor.paste_pending:
            self.editor.paste_clipboard(self.editor.pixel_to_tile(*pos))
            self.editor.paste_pending = False
            return

        if self.editor.active_tool in SHAPE_TOOLS:
            # Preview-while-dragging tools: this click just starts the
            # drag -- see _handle_editor_motion/_handle_editor_mouse_up
            # for how it's previewed/committed.
            self.editor.begin_shape(self.editor.pixel_to_tile(*pos))
            return

        # Editor.paint_at() silently ignores a pixel outside the grid
        # (e.g. over the toolbar/sidebar, neither of which overlaps the
        # grid's own pixel range), so no further fencing is needed here.
        self.editor.paint_at(*pos)

    def _handle_editor_motion(self, pos, buttons):
        if not buttons[0]:  # left button not held -> nothing to drag
            return
        if self.editor.active_tool in SHAPE_TOOLS:
            self.editor.update_shape_preview(self.editor.pixel_to_tile(*pos))
        else:
            self.editor.paint_at(*pos)

    def _handle_editor_mouse_up(self, pos):
        """Ends whatever the left button was doing on the grid: a
        freeform drag-paint stroke (see Editor.begin_stroke(), called
        from _apply_tool() on the first cell of the stroke), or a Line/
        Rect/Select drag (committed here instead)."""
        if self.editor.active_tool in SHAPE_TOOLS:
            self.editor.commit_shape(self.editor.pixel_to_tile(*pos))
        else:
            self.editor.end_stroke()

    def _handle_editor_action(self, action):
        if action == "back":
            self.state = GameState.MENU
        elif action == "waves" and self.editor.path_is_valid():
            self.state = GameState.WAVE_EDITOR
        elif action == "load":
            self._enter_level_select(purpose="edit")
        elif action == "copy":
            self.editor.copy_selection()
        elif action == "paste":
            self.editor.paste_pending = True
        else:
            self._handle_editor_undo_redo_action(action)

    # --- Wave editor ---

    def _wave_tab_rects(self):
        """Rebuilt on demand rather than cached -- unlike every other rect
        set in Game, this one's shape depends on how many waves currently
        exist, which changes as the player adds/removes them."""
        return ui.build_wave_tab_rects(len(self.editor.wave_specs))

    def _handle_wave_editor_click(self, pos):
        tab = ui.get_clicked_wave_tab(pos, self._wave_tab_rects())
        if tab == "add":
            self.editor.add_wave()
            return
        if tab == "remove":
            self.editor.remove_wave()
            return
        if tab is not None:  # an int wave index
            self.editor.set_active_wave(tab)
            return

        unit_key = ui.get_clicked_wave_unit_button(pos, self.wave_unit_rects)
        if unit_key is not None:
            enemy_name, sign = unit_key
            self.editor.adjust_unit_count(enemy_name, +1 if sign == "plus" else -1)
            return

        action = ui.get_clicked_wave_editor_action(pos, self.wave_editor_action_rects)
        if action is not None:
            self._handle_wave_editor_action(action)
            return

        # Not on any button -- maybe a spawn marker in the read-only path
        # preview was clicked, switching which spawn's counts the +/-
        # buttons above now target. set_active_spawn() itself already
        # no-ops for a cell that isn't actually a spawn, so nothing here
        # needs to fence the click to "did it land on a real marker" first.
        self.editor.set_active_spawn(self.editor.pixel_to_tile(*pos))

    def _handle_wave_editor_action(self, action):
        if action == "back":
            self.state = GameState.EDITOR
        elif action == "playtest" and self.editor.can_play():
            self.load_custom_level(self.editor.to_level())
            self.state = GameState.PLAYING
        elif action == "save" and self.editor.can_play():
            self.last_saved_path = persistence.save_level(self.editor.to_level())
        else:
            self._handle_editor_undo_redo_action(action)

    # --- Level select ---

    def _enter_level_select(self, purpose="play"):
        """Rebuilds the level list from scratch every time this is
        entered (not just once in __init__) since the custom levels on
        disk can change between visits -- most obviously, right after
        saving one from the editor. Custom levels persist across game
        sessions too: they're read fresh from persistence.LEVELS_DIR here,
        the same directory Save writes to, so a level saved in an earlier
        run of the game shows up here just as readily as one saved this
        session.

        `purpose` is "play" (the menu's L -- picking a level starts
        playing it) or "edit" (the editor's Load Map... action -- picking
        a level loads it back into the editor for further editing
        instead; see _handle_level_select_click). Built-in levels have no
        corresponding file to reopen for editing, so "edit" only ever
        lists custom ones.

        Also refreshes self.progress from disk (same "always re-read"
        convention list_custom_levels() follows) and, for purpose="play"
        only, computes which built-in level ids are still locked -- a
        custom level is never locked, and "edit" never lists built-ins at
        all, so level_select_locked_ids is empty for both of those cases."""
        custom_levels = persistence.list_custom_levels()
        self._custom_levels_by_id = {level.id: level for level in custom_levels}
        self.progress = progress.load_progress(self.progress_path)

        if purpose == "edit":
            entries = [(level.id, level) for level in custom_levels]
            locked_ids = set()
        else:
            entries = [(level_id, level) for level_id, level in sorted(LEVELS.items())]
            entries += [(level.id, level) for level in custom_levels]
            locked_ids = {
                level_id for level_id in LEVELS
                if not progress.is_unlocked(level_id, LEVELS, self.progress)
            }

        self.level_select_entries = entries
        self.level_select_thumbnails = {key: ui.build_level_thumbnail(level) for key, level in entries}
        self.level_select_purpose = purpose
        self.level_select_locked_ids = locked_ids
        self.level_select_scroll_offset = 0  # always open scrolled to the top
        self.level_select_endless_armed = False  # always re-opens un-armed
        self.level_select_sandbox_armed = False  # same -- always re-opens un-armed
        self._rebuild_level_select_rects()
        self.state = GameState.LEVEL_SELECT

    def _rebuild_level_select_rects(self):
        """level_select_rects depends on scroll position, not just on
        what's listed -- called both here (from _enter_level_select) and
        after every scroll (_scroll_level_select) so it's never stale for
        the click handler or render() to read."""
        self.level_select_rects = ui.build_level_select_rects(
            self.level_select_entries, self.level_select_scroll_offset,
        )

    def _scroll_level_select(self, wheel_y):
        # pygame's MOUSEWHEEL.y is positive scrolling away from the
        # player (up the list -> less scroll_offset) and negative toward
        # them (down the list -> more) -- hence the sign flip.
        max_scroll = ui.level_select_max_scroll(len(self.level_select_entries))
        self.level_select_scroll_offset -= wheel_y * ui.LEVEL_SELECT_SCROLL_STEP
        self.level_select_scroll_offset = max(0, min(self.level_select_scroll_offset, max_scroll))
        self._rebuild_level_select_rects()

    def _handle_level_select_click(self, pos):
        # A row scrolled off the top/bottom still has a real (just
        # off-viewport) Rect -- see build_level_select_rects -- so a click
        # outside the visible list area must never match one.
        if not (ui.LEVEL_SELECT_TOP <= pos[1] <= ui.LEVEL_SELECT_BOTTOM):
            return
        key = ui.get_clicked_level_select_entry(pos, self.level_select_rects)
        if key is None:
            return
        if self.level_select_purpose == "edit":
            self.editor.load_level(self._custom_levels_by_id[key])
            self.state = GameState.EDITOR
        elif isinstance(key, int):
            if key in self.level_select_locked_ids:
                return  # locked -- stays on LEVEL_SELECT
            self.load_level(key, endless=self.level_select_endless_armed, sandbox=self.level_select_sandbox_armed)
            self.state = GameState.PLAYING
        else:
            self.load_custom_level(
                self._custom_levels_by_id[key],
                endless=self.level_select_endless_armed, sandbox=self.level_select_sandbox_armed,
            )
            self.state = GameState.PLAYING

    # --- Settings ---

    def _handle_settings_click(self, pos):
        option = ui.get_clicked_settings_option(pos, self.settings_rects)
        if option == "fullscreen":
            self.set_fullscreen(not self.fullscreen)
        elif option in difficulty.DIFFICULTY_MODES:
            self.set_difficulty(option)
        elif option == "back":
            self.state = GameState.MENU

    # --- Achievements ---

    def _enter_achievements(self):
        # Re-read fresh from disk every time -- same "always re-read"
        # convention _enter_level_select() follows for self.progress,
        # since an achievement can have unlocked since this screen was last
        # open (e.g. right after a victory earned one -- see update()'s
        # win-check).
        self.achievements_state = achievements.load_achievements(self.achievements_path)
        self.state = GameState.ACHIEVEMENTS

    def _handle_achievements_click(self, pos):
        if self.achievements_back_rect.collidepoint(pos):
            self.state = GameState.MENU

    def _delete_save_if_this_run_was_resumed(self):
        """Called from both of update()'s win/loss branches -- a resumed
        run that's been played out to a real conclusion has nothing left to
        "Continue" back into, so its save file shouldn't still be offered.
        Guarded on _resumed_from_save (see __init__'s comment on it) so a
        fresh, unrelated run reaching its own conclusion never deletes a
        different, still-valid save left over from some other abandoned
        run."""
        if self._resumed_from_save:
            save_state.delete_saved_run(self.save_path)
            self._resumed_from_save = False

    def _record_achievement(self, counter_name, amount=1):
        """Bump `counter_name` (see achievements.py) and queue a toast for
        anything newly unlocked -- called from every Game-level event an
        achievement can key off (see try_place_tower/try_upgrade_tower/
        try_specialize_tower and update()'s kill/wave/level-clear hooks),
        each already gated on `not self.sandbox` at the call site so a
        trivial sandbox run never counts toward real progress, same
        reasoning already applied to progress.mark_level_cleared."""
        for key in achievements.bump(counter_name, amount, self.achievements_path):
            achievement = achievements.ACHIEVEMENTS[key]
            # Stacked toasts offset by however many are already queued, so
            # several unlocks landing the same frame (e.g. crossing two
            # kill thresholds on one death) read as distinct lines rather
            # than overlapping illegibly.
            y = 40 + 24 * len(self.achievement_toasts)
            self.achievement_toasts.append(effects.FloatingText(
                (settings.PLAY_WIDTH // 2, y), f"Achievement unlocked: {achievement.display_name}",
                lifetime=3.0, rise_speed=8.0, color=settings.COLOR_GOLD,
            ))

    def _handle_click(self, pos):
        if self.state != GameState.PLAYING:
            return

        clicked_button = ui.get_clicked_tower_button(pos, self.button_rects)
        if clicked_button is not None:
            self.selected_tower_name = None if clicked_button == self.selected_tower_name else clicked_button
            self.selected_tower = None  # switching to build mode drops any pinned placed-tower panel
            return

        if self.skip_button_rect.collidepoint(pos):
            self.wave_manager.skip_delay()
            return

        if self.speed_button_rect.collidepoint(pos):
            self.cycle_time_scale()
            return

        if self._handle_panel_action_click(pos):
            return

        if pos[0] >= settings.PLAY_WIDTH:
            return  # click landed in the stats panel but not on a button

        if pos[1] >= settings.SCREEN_HEIGHT - settings.HUD_HEIGHT:
            return  # click landed in the HUD area but not on a button

        for tower in self.towers:
            if tower.contains_upgrade_badge(pos):
                self.try_upgrade_tower(tower)
                return

        for tower in self.towers:
            if tower.contains_point(pos):
                self.selected_tower = tower  # pin it open in the stats panel
                return

        if self.selected_tower_name is not None:
            anchor_col, anchor_row = self.grid.placement_anchor(*pos)
            self.try_place_tower(anchor_col, anchor_row)
        else:
            self.selected_tower = None  # clicked empty ground -> deselect

    def _handle_panel_action_click(self, pos):
        """Handles a click on the stats panel's Upgrade/Specialize/Sell
        buttons. Returns True if `pos` was on one of them -- whether or
        not it actually did anything, e.g. an unaffordable upgrade still
        "belongs" to that button rather than falling through to the grid
        underneath it -- so the caller knows to stop processing this click.

        Uses self._last_panel_subject (what render() last showed) rather
        than re-deriving the subject from _hovered_tower() at click time:
        by the time the mouse is actually over one of these buttons, it's
        no tower's tile_rect() ever reaches the panel to check -- so a
        fresh lookup here always reads as "not hovering anything" and
        silently falls back to whatever else is pinned/selected, which
        can easily be a *different* tower than the one whose button the
        player is actually looking at and clicking."""
        subject = self._last_panel_subject
        is_tower = subject in self.towers  # not a build-menu class or None

        if self.targeting_button_rect.collidepoint(pos):
            # The row isn't drawn for a support tower (see
            # ui.draw_tower_stats_panel's IS_SUPPORT guard), but this
            # Rect still occupies that screen position regardless of
            # subject -- without this guard, a click there while a
            # support tower is pinned/hovered would silently cycle an
            # attribute (targeting_mode) it inherits but never reads.
            if is_tower and not type(subject).IS_SUPPORT:
                subject.cycle_targeting_mode()
            return True

        if self.upgrade_button_rect.collidepoint(pos):
            if is_tower and not subject.is_max_level:
                self.try_upgrade_tower(subject)
                return True
            # Falls through rather than returning when there's no upgrade
            # to make: this rect is intentionally shared with the first
            # Specialize button (see ui.build_specialize_button_rects --
            # Upgrade and Specialize are mutually exclusive states), so a
            # maxed, specializable tower's click here needs to reach the
            # specialize handling below instead of silently doing nothing.

        for index, rect in enumerate(self.specialize_button_rects):
            if not rect.collidepoint(pos):
                continue
            if is_tower and subject.can_specialize:
                keys = list(subject.SPECIALIZATIONS.keys())
                if index < len(keys):
                    self.try_specialize_tower(subject, keys[index])
            return True

        if self.sell_button_rect.collidepoint(pos):
            if is_tower:
                self.try_sell_tower(subject)
            return True

        return False

    def try_place_tower(self, anchor_col, anchor_row):
        if self.selected_tower_name is None:
            return False
        if not self.grid.is_buildable(anchor_col, anchor_row):
            return False

        tower_cls = TOWER_TYPES[self.selected_tower_name]
        if not self.economy.can_afford(tower_cls.cost):
            return False

        self.economy.spend(tower_cls.cost)
        pixel_pos = self.grid.anchor_to_pixel_center(anchor_col, anchor_row)
        tower = tower_cls(anchor_col, anchor_row, pixel_pos)
        self.towers.append(tower)
        self.grid.occupy(anchor_col, anchor_row, tower)
        if not self.sandbox:
            self._record_achievement("towers_built")
        return True

    def try_upgrade_tower(self, tower):
        if tower not in self.towers:
            return False
        cost = tower.upgrade_cost()
        if cost is None or not self.economy.can_afford(cost):
            return False

        self.economy.spend(cost)
        tower.upgrade()
        # Fires exactly once per tower, the moment it actually reaches
        # MAX_LEVEL -- try_upgrade_tower's own cost-is-None guard above
        # already stops this method from ever being reached again for an
        # already-maxed tower, so there's no risk of over-counting on a
        # later no-op call.
        if not self.sandbox and tower.is_max_level:
            self._record_achievement("towers_maxed")
        return True

    def try_specialize_tower(self, tower, key):
        if tower not in self.towers:
            return False
        if not tower.can_specialize or key not in tower.SPECIALIZATIONS:
            return False
        cost = tower.specialization_cost()
        if not self.economy.can_afford(cost):
            return False

        self.economy.spend(cost)
        tower.specialize(key)
        if not self.sandbox:
            self._record_achievement("towers_specialized")
        return True

    def try_sell_tower(self, tower):
        if tower not in self.towers:
            return False

        self.economy.add_gold(tower.sell_value())
        self.towers.remove(tower)
        self.sold_towers.append(tower)  # see _tower_results()
        self.grid.remove(tower.anchor_col, tower.anchor_row)
        if self.selected_tower is tower:
            self.selected_tower = None
        return True

    def _tower_results(self):
        return ui.compute_tower_results(self.towers + self.sold_towers)

    # --- Update ---

    def update(self, dt):
        if self.state != GameState.PLAYING:
            return

        # Real wall-clock dt still drives self.clock.tick(FPS) in run(), so
        # frame pacing/FPS is unaffected -- only simulated time speeds up.
        dt = dt * self.time_scale

        for enemy in self.enemies:
            enemy.update(dt)

        # Two passes: every tower's aura buff is reset before any tower
        # (support or attacking) does its own per-frame work, so which
        # order Game happens to iterate self.towers in can never matter --
        # a support tower later in the list still gets to (re-)buff a
        # tower earlier in the list within the same frame.
        for tower in self.towers:
            tower.reset_aura()
        for tower in self.towers:
            tower.update(dt, self.enemies, self.projectiles, self.towers)

        for projectile in self.projectiles:
            projectile.update(dt, self.enemies)

        # Drained here, before dead projectiles are pruned below -- same
        # per-frame-event-list idiom as enemy.damage_events -> damage_
        # numbers just below: an impact is recorded the instant a shot
        # resolves (see Projectile._resolve_hit), so this always catches it
        # before the projectile itself disappears.
        for projectile in self.projectiles:
            for impact_pos, splash_radius in projectile.impact_events:
                if splash_radius:
                    # Sized to the blast's real splash_radius, so the ring
                    # actually shows what it hit -- not just that it hit.
                    self.impact_effects.append(effects.ExpandingRing(
                        impact_pos, max_radius=splash_radius, duration=0.4,
                        color=settings.COLOR_RANGE_PREVIEW,
                    ))
                else:
                    self.impact_effects.append(effects.ExpandingRing(
                        impact_pos, max_radius=14, duration=0.25,
                        color=settings.COLOR_RANGE_PREVIEW,
                    ))
            projectile.impact_events.clear()
        self.projectiles = [p for p in self.projectiles if not p.dead]

        # Drained here -- while dead enemies are still in self.enemies with
        # a valid pos, before the alive-filter loop below removes them --
        # so a killing blow's own damage number still gets a floating text
        # at the spot it landed rather than being silently dropped.
        for enemy in self.enemies:
            for amount in enemy.damage_events:
                self.damage_numbers.append(effects.FloatingText(enemy.pos, str(round(amount))))
            enemy.damage_events.clear()
        for text in self.damage_numbers:
            text.update(dt)
        self.damage_numbers = [t for t in self.damage_numbers if not t.dead]

        for ring in self.impact_effects:
            ring.update(dt)
        self.impact_effects = [r for r in self.impact_effects if not r.dead]

        for toast in self.achievement_toasts:
            toast.update(dt)
        self.achievement_toasts = [t for t in self.achievement_toasts if not t.dead]

        still_alive = []
        for enemy in self.enemies:
            if enemy.is_dead:
                self.economy.add_gold(enemy.gold_reward)
                if not self.sandbox:
                    self._record_achievement("kills")
                # A small death poof, same spot the killing blow's own
                # damage number is spawned from -- reads enemy.pos before
                # this enemy is dropped from self.enemies just below.
                self.impact_effects.append(effects.ExpandingRing(
                    enemy.pos, max_radius=enemy.radius * 1.8, duration=0.3, color=settings.COLOR_LIVES,
                ))
            elif enemy.reached_goal:
                self.economy.lose_life()
            else:
                still_alive.append(enemy)
        self.enemies = still_alive

        # Compared before/after to detect a wave actually clearing this
        # tick (WaveManager._advance_after_clear bumping wave_index) --
        # counts a survived wave whether it came from the level's own
        # authored waves or an endless-generated one, without adding any
        # Game/persistence coupling into waves.py itself.
        wave_number_before_update = self.wave_manager.current_wave_number
        self.enemies.extend(self.wave_manager.update(dt, self.enemies))
        if not self.sandbox and self.wave_manager.current_wave_number > wave_number_before_update:
            self._record_achievement("waves_survived")

        if self.economy.is_out_of_lives:
            self.state = GameState.GAME_OVER
            self._delete_save_if_this_run_was_resumed()
        elif self.wave_manager.all_waves_complete and not self.enemies:
            self.state = GameState.VICTORY
            # A built-in level's progress is gated by real clears -- a
            # sandbox run (unlimited gold, invulnerable) trivializes
            # winning, so it shouldn't count as one, same reasoning that
            # already keeps an endless run's all_waves_complete from ever
            # firing at all.
            if isinstance(self.current_level_id, int) and not self.sandbox:
                self.progress = progress.mark_level_cleared(
                    self.current_level_id, self.economy.lives, self.progress_path,
                )
                self._record_achievement("levels_cleared")
            self._delete_save_if_this_run_was_resumed()

    # --- Render ---

    def render(self):
        self.screen.fill(settings.COLOR_BG)

        if self.state == GameState.MENU:
            ui.draw_menu_screen(self.screen, self.font, self.small_font,
                                 save_state.has_saved_run(self.save_path))
            pygame.display.flip()
            return

        if self.state == GameState.SETTINGS:
            ui.draw_settings_screen(
                self.screen, self.font, self.small_font, self.settings_rects,
                self.fullscreen, self.difficulty,
            )
            pygame.display.flip()
            return

        if self.state == GameState.ACHIEVEMENTS:
            ui.draw_achievements_screen(
                self.screen, self.font, self.small_font,
                self.achievements_state["unlocked"], self.achievements_state["counters"],
                self.achievements_back_rect,
            )
            pygame.display.flip()
            return

        if self.state == GameState.EDITOR:
            ui.draw_editor_screen(
                self.screen, self.assets, self.font, self.small_font,
                self.editor, self.editor_tool_rects, self.editor_action_rects,
            )
            pygame.display.flip()
            return

        if self.state == GameState.WAVE_EDITOR:
            ui.draw_wave_editor_screen(
                self.screen, self.assets, self.font, self.small_font,
                self.editor, self._wave_tab_rects(), self.wave_unit_rects, self.wave_editor_action_rects,
                self.last_saved_path,
            )
            pygame.display.flip()
            return

        if self.state == GameState.LEVEL_SELECT:
            ui.draw_level_select_screen(
                self.screen, self.font, self.small_font,
                self.level_select_entries, self.level_select_rects, self.level_select_thumbnails,
                self.level_select_purpose, self.level_select_scroll_offset,
                self.level_select_locked_ids, self.level_select_endless_armed,
                self.level_select_sandbox_armed,
            )
            pygame.display.flip()
            return

        self.grid.draw(self.screen, self.assets)
        for tower in self.towers:
            tower.draw(self.screen, self.assets, self.tiny_font)
        for enemy in self.enemies:
            enemy.draw(self.screen, self.assets)
        for projectile in self.projectiles:
            projectile.draw(self.screen, self.assets)
        for ring in self.impact_effects:
            ring.draw(self.screen)
        for text in self.damage_numbers:
            text.draw(self.screen, self.tiny_font)

        self._render_placement_preview()
        hovered_tower = self._hovered_tower()
        panel_subject = self._stats_panel_subject(hovered_tower)
        self._last_panel_subject = panel_subject  # see _handle_panel_action_click
        if panel_subject in self.towers:  # a placed tower (hovered, or pinned via selected_tower)
            ui.draw_tower_range_preview(self.screen, panel_subject)

        ui.draw_hud(
            self.screen, self.assets, self.font, self.small_font,
            self.economy, self.wave_manager, self.button_rects,
            self.skip_button_rect, self.selected_tower_name,
            self.time_scale, self.speed_button_rect,
            self.wave_manager.next_wave_preview(),
        )
        ui.draw_tower_stats_panel(
            self.screen, self.font, self.small_font, panel_subject, self.economy,
            self.targeting_button_rect,
            self.upgrade_button_rect, self.specialize_button_rects, self.sell_button_rect,
            self._hovered_specialize_key(panel_subject),
        )
        for toast in self.achievement_toasts:
            toast.draw(self.screen, self.small_font)

        if self.state == GameState.PAUSED:
            ui.draw_pause_menu(self.screen, self.font, self.small_font,
                                self.current_level_id is None, self.can_save_run())
        elif self.state == GameState.GAME_OVER:
            ui.draw_game_over_screen(self.screen, self.font, self.small_font, self._tower_results())
        elif self.state == GameState.VICTORY:
            ui.draw_victory_screen(self.screen, self.font, self.small_font, self.has_next_level(),
                                    self._tower_results())

        pygame.display.flip()

    def _render_placement_preview(self):
        if self.selected_tower_name is None:
            return
        mouse_pos = pygame.mouse.get_pos()
        if mouse_pos[1] >= settings.SCREEN_HEIGHT - settings.HUD_HEIGHT:
            return
        if mouse_pos[0] >= settings.PLAY_WIDTH:
            return  # hovering the stats panel, not the grid
        tower_cls = TOWER_TYPES[self.selected_tower_name]
        anchor_col, anchor_row = self.grid.placement_anchor(*mouse_pos)
        preview_pos = self.grid.anchor_to_pixel_center(anchor_col, anchor_row)
        buildable = self.grid.is_buildable(anchor_col, anchor_row)
        ui.draw_footprint_preview(self.screen, self.grid, anchor_col, anchor_row, buildable)
        ui.draw_range_preview(self.screen, tower_cls, preview_pos)

    def _hovered_tower(self):
        """The placed tower currently under the mouse (anywhere on its
        tile, not just its '+' badge), or None. Shared by the range-ring
        hover preview and the stats panel so both always agree on which
        tower is "hot". Clicking to actually upgrade still requires the
        (smaller) badge specifically -- see contains_upgrade_badge()."""
        mouse_pos = pygame.mouse.get_pos()
        for tower in self.towers:
            if tower.contains_point(mouse_pos):
                return tower
        return None

    def _hovered_specialize_key(self, panel_subject):
        """Which of panel_subject's SPECIALIZATIONS the mouse is
        currently over (its Specialize button in the stats panel), or
        None -- lets the panel show that option's description text while
        it's hovered. Only meaningful while the panel is actually showing
        a specializable tower's choice buttons."""
        if panel_subject not in self.towers or not panel_subject.can_specialize:
            return None
        mouse_pos = pygame.mouse.get_pos()
        keys = list(panel_subject.SPECIALIZATIONS.keys())
        for index, rect in enumerate(self.specialize_button_rects):
            if index < len(keys) and rect.collidepoint(mouse_pos):
                return keys[index]
        return None

    def _stats_panel_subject(self, hovered_tower):
        """What the stats panel should show, in priority order: a hovered
        placed tower (a quick peek at whatever's under the mouse right
        now); otherwise a placed tower the player clicked to pin open
        (self.selected_tower -- stays shown even once the mouse moves
        away, until something else replaces or clears it); otherwise the
        tower type currently selected to build; otherwise None (panel
        shows a hint)."""
        if hovered_tower is not None:
            return hovered_tower
        if self.selected_tower is not None:
            return self.selected_tower
        if self.selected_tower_name is not None:
            return TOWER_TYPES[self.selected_tower_name]
        return None
