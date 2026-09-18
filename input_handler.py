"""Game's own raw-input dispatch, extracted into its own module -- the
second cut of game.py's god-object decomposition (see renderer.py's own
module docstring for the first, and CLAUDE.md's architecture section for
both).

The boundary drawn here mirrors Renderer's: InputHandler owns "translate
a raw pygame event (a key, a click position, a wheel delta) into a
decision," and calls back out to Game for every actual state mutation
(`try_place_tower`, `set_fullscreen`, `_enter_node`, ...) -- the "existing
action methods" every one of these already called before this move, now
just reached via `game.` instead of `self.`. Methods that take an
*already-resolved* semantic value instead of raw input -- `_handle_editor_
action(action)`, `_handle_wave_editor_action(action)`, `_handle_editor_
undo_redo_action(action)`, and every `_enter_*_node`/`_resolve_*`/
`_rebuild_*_rects` business-logic method -- deliberately stay on `Game`
itself, not here: they're the "do the thing" half a raw-input handler
resolves into, and several of them are also called from places that have
nothing to do with a live pygame event (e.g. `_rebuild_wave_unit_rects`
from entering the wave editor screen in the first place).

Every method moved here calls only *other methods on this same class*
when referring to another item from this list (e.g. `_handle_click`
calling `self._handle_panel_action_click`) -- confirmed by checking every
internal caller before the move, every one of these 21 methods is only
ever invoked by another one of the 21, never from anywhere else in
game.py. Everything else reached via `game.`.

GameState is imported lazily, inside whichever method needs it, rather
than at module level -- Game constructs an InputHandler(self) (see Game.
__init__), so a top-level `from game import GameState` here would be a
circular import evaluated before GameState is even defined, same
reasoning renderer.py's own docstring gives.
"""

import pygame

import difficulty
import settings
import ui
from editor import SHAPE_TOOLS


class InputHandler:
    def __init__(self, game):
        self.game = game

    def handle_events(self):
        from game import GameState  # see module docstring

        game = self.game
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                game.running = False
            elif event.type == pygame.KEYDOWN:
                self._handle_keydown(event.key)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if game.state == GameState.EDITOR:
                    self._handle_editor_click(event.pos)
                elif game.state == GameState.WAVE_EDITOR:
                    self._handle_wave_editor_click(event.pos)
                elif game.state == GameState.LEVEL_SELECT:
                    self._handle_level_select_click(event.pos)
                elif game.state == GameState.SETTINGS:
                    self._handle_settings_click(event.pos)
                elif game.state == GameState.ACHIEVEMENTS:
                    self._handle_achievements_click(event.pos)
                elif game.state == GameState.HELP:
                    self._handle_help_click(event.pos)
                elif game.state == GameState.CREDITS:
                    self._handle_credits_click(event.pos)
                elif game.state == GameState.DRAFT:
                    self._handle_draft_click(event.pos)
                elif game.state == GameState.MAP:
                    self._handle_map_click(event.pos)
                elif game.state == GameState.EVENT:
                    self._handle_event_click(event.pos)
                else:
                    # REST/TREASURE deliberately have no click handler of
                    # their own -- same "press any key" precedent FLOOR_
                    # CLEARED sets (see _handle_keydown), a click there
                    # just falls through here and no-ops (game.state !=
                    # PLAYING).
                    self._handle_click(event.pos)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                self._handle_right_click()
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and game.state == GameState.EDITOR:
                self._handle_editor_mouse_up(event.pos)
            elif event.type == pygame.MOUSEMOTION and game.state == GameState.EDITOR:
                self._handle_editor_motion(event.pos, event.buttons)
            elif event.type == pygame.MOUSEWHEEL and game.state == GameState.LEVEL_SELECT:
                self._scroll_level_select(event.y)
            elif event.type == pygame.MOUSEWHEEL and game.state == GameState.WAVE_EDITOR:
                self._scroll_wave_unit_list(event.y)
            elif event.type == pygame.VIDEORESIZE and not game.fullscreen:
                # Only while windowed -- a fullscreen window resizing away
                # from the desktop resolution isn't something the player
                # actually did (see apply_display_mode's docstring for what
                # this makes dragging a windowed edge actually do).
                # set_window_size() persists too, same as a Settings-screen
                # preset click, so an organic drag survives a relaunch just
                # the same. That does mean a full (tiny, un-fsync'd) JSON
                # rewrite on every intermediate size SDL reports while a
                # drag is in progress, not just once at the end -- a
                # deliberate choice, not an oversight: there's no distinct
                # "drag finished" event to defer to here, and debouncing
                # this write is not worth the added state for a save this
                # cheap.
                game.set_window_size(event.size)

    def _handle_keydown(self, key):
        from game import GameState  # see module docstring

        game = self.game
        if game.state == GameState.MENU:
            if key == pygame.K_ESCAPE:
                game.running = False
            else:
                # letter, not the raw pygame key constant, so this stays in
                # lockstep with ui.MENU_KEY_HINTS/MENU_KEY_LETTERS -- the
                # single source of truth for which keys the on-screen hint
                # list promises do something (see ui.py for why).
                letter = pygame.key.name(key)
                if letter == "c" and game.has_saved_run:
                    game._continue_saved_run()
                elif letter in ui.MENU_KEY_LETTERS:
                    if letter == "e":
                        game.state = GameState.EDITOR
                    elif letter == "l":
                        game._enter_level_select()
                    elif letter == "s":
                        game.state = GameState.SETTINGS
                    elif letter == "a":
                        game._enter_achievements()
                    elif letter == "h":
                        game.state = GameState.HELP
                    elif letter == "d":
                        game._start_daily_challenge()
                    elif letter == "b":
                        game.state = GameState.CREDITS
                else:
                    game.start_new_run()
        elif game.state in (GameState.SETTINGS, GameState.ACHIEVEMENTS,
                             GameState.HELP, GameState.CREDITS):
            # These four share nothing but "Esc goes back to the menu" --
            # each is otherwise driven entirely by its own click handler
            # (Settings/Achievements have real buttons; Help/Credits are
            # fully static). EDITOR isn't folded in here despite starting
            # with the identical check, since it has real key handling of
            # its own below Esc (see its own elif right after this one).
            if key == pygame.K_ESCAPE:
                game.state = GameState.MENU
        elif game.state == GameState.EDITOR:
            if key == pygame.K_ESCAPE:
                game.state = GameState.MENU
            else:
                self._handle_editor_undo_redo_keydown(key)
        elif game.state == GameState.WAVE_EDITOR:
            if key == pygame.K_ESCAPE:
                game.state = GameState.EDITOR  # one step back, same as the Back-to-Path button
            else:
                self._handle_editor_undo_redo_keydown(key)
        elif game.state == GameState.LEVEL_SELECT:
            if key == pygame.K_ESCAPE:
                # Back to wherever this screen was entered from -- the
                # menu's L, or the editor's Load Map... (see
                # _enter_level_select's purpose param).
                game.state = GameState.MENU if game.level_select_purpose == "play" else GameState.EDITOR
            elif key == pygame.K_v and game.level_select_purpose == "play":
                # Arms/disarms endless/survival mode for whichever level
                # gets picked next -- meaningless while browsing to load a
                # map into the editor (purpose="edit"), so a no-op there.
                game.level_select_endless_armed = not game.level_select_endless_armed
        elif game.state == GameState.PLAYING:
            if key in (pygame.K_p, pygame.K_ESCAPE):
                game.state = GameState.PAUSED
            elif key == pygame.K_SPACE:
                game.wave_manager.skip_delay()
            elif key == pygame.K_1:
                game.set_time_scale(1.0)
            elif key == pygame.K_2:
                game.set_time_scale(2.0)
            elif key == pygame.K_3:
                game.set_time_scale(3.0)
            elif key == pygame.K_r and game.active_run is not None:
                game.state = GameState.RELICS
        elif game.state == GameState.RELICS:
            # Nothing to confirm or lose here (unlike PAUSED's own R) --
            # any key dismisses it, Escape included. That's PAUSED's own
            # Escape/P-resumes shape, not FLOOR_CLEARED/REST's -- those two
            # special-case Escape to quit the app instead, which would be
            # bad UX here (there's a live board underneath, not a result
            # to leave); nothing else warrants special-casing Escape while
            # just glancing at your relics.
            game.state = GameState.PLAYING
        elif game.state == GameState.PAUSED:
            if game.pause_restart_confirm_pending:
                # Only R (confirm) or Esc (cancel, back to the normal pause
                # menu -- still PAUSED) do anything here; P is deliberately
                # not treated as a synonym for Esc, unlike the normal pause
                # menu's own Esc/P-both-resume shape, so a reflexive P
                # press mid-confirm can't be misread as "resume playing"
                # when nothing has actually been decided yet.
                if key == pygame.K_r:
                    game.reset()  # reset() itself still sees state == PAUSED here
                    game.state = GameState.PLAYING
                    game.pause_restart_confirm_pending = False
                elif key == pygame.K_ESCAPE:
                    game.pause_restart_confirm_pending = False
            elif key in (pygame.K_p, pygame.K_ESCAPE):
                game.state = GameState.PLAYING
            elif key == pygame.K_r:
                game.pause_restart_confirm_pending = True
            elif key == pygame.K_e and game.current_level_id is None:
                # Only offered (see ui.draw_pause_menu) while playing a
                # custom level -- game.editor still has whatever was
                # playtested, untouched, so this is just "stop playing,"
                # not a reload.
                game.state = GameState.EDITOR
            elif key == pygame.K_s and game.can_save_run():
                game.save_run()
                game.state = GameState.MENU
            elif key == pygame.K_q:
                game.running = False
        elif game.state == GameState.GAME_OVER:
            if key == pygame.K_ESCAPE:
                game.running = False
            elif key == pygame.K_r:
                game.reset()
                game.state = GameState.PLAYING
        elif game.state == GameState.VICTORY:
            if key == pygame.K_ESCAPE:
                game.running = False
            elif key == pygame.K_r:
                game.advance_or_replay_level()
                game.state = GameState.PLAYING
        elif game.state == GameState.FLOOR_CLEARED:
            # Escape quits, same as every other post-battle results screen
            # (VICTORY/GAME_OVER just above) -- any other key returns to
            # the map, same "press any key to continue" spirit as the
            # menu's own catch-all, since there's nothing to choose between
            # here (that's the map screen's job, entered next).
            if key == pygame.K_ESCAPE:
                game.running = False
            else:
                game._enter_map()
        elif game.state == GameState.MAP:
            # No keyboard equivalent for picking a node, same as the build
            # menu's own tower buttons -- but Escape should still quit, the
            # same as every other non-PLAYING screen offers.
            if key == pygame.K_ESCAPE:
                game.running = False
        elif game.state == GameState.DRAFT:
            # No keyboard equivalent for picking a card, same as the build
            # menu's own tower buttons -- but Escape should still quit, the
            # same as every other non-PLAYING screen offers, rather than
            # leaving this the one screen with no keyboard way out at all.
            if key == pygame.K_ESCAPE:
                game.running = False
        elif game.state == GameState.EVENT:
            # Escape quits, same as every other non-PLAYING screen; any
            # other key only does something once an option's been chosen
            # (see _handle_event_click's own "resolved" phase) -- no
            # keyboard equivalent for picking an option itself, same as
            # DRAFT above.
            if key == pygame.K_ESCAPE:
                game.running = False
            elif game.event_phase == "resolved":
                game._finish_node(game.active_run.current_node_id)
        elif game.state == GameState.REST:
            # A Rest node has nothing to choose -- it's already resolved
            # the instant it's entered (see _enter_rest_node) -- so any key
            # but Escape just continues, same "press any key" spirit as
            # FLOOR_CLEARED above.
            if key == pygame.K_ESCAPE:
                game.running = False
            else:
                game._finish_node(game.active_run.current_node_id)
        elif game.state == GameState.TREASURE:
            # Same "already resolved on entry, press any key to continue"
            # shape as REST above.
            if key == pygame.K_ESCAPE:
                game.running = False
            else:
                game._finish_node(game.active_run.current_node_id)

    def _handle_right_click(self):
        from game import GameState  # see module docstring

        game = self.game
        if game.state != GameState.PLAYING:
            return
        game.selected_tower_name = None
        game.selected_tower = None

    def _handle_editor_undo_redo_keydown(self, key):
        """Ctrl+Z/Ctrl+Y -- shared by both editor screens' keydown handling
        (GameState.EDITOR and WAVE_EDITOR), since both mutate the same
        game.editor. Routes through _handle_editor_undo_redo_action() so
        there's exactly one place that actually calls undo()/redo(),
        regardless of whether it was a keypress or an action-button click."""
        game = self.game
        mods = pygame.key.get_mods()
        if key == pygame.K_z and mods & pygame.KMOD_CTRL:
            game._handle_editor_undo_redo_action("undo")
        elif key == pygame.K_y and mods & pygame.KMOD_CTRL:
            game._handle_editor_undo_redo_action("redo")

    def _handle_editor_click(self, pos):
        game = self.game
        tool = ui.get_clicked_editor_tool(pos, game.editor_tool_rects)
        if tool is not None:
            game.editor.set_tool(tool)
            return

        action = ui.get_clicked_editor_action(pos, game.editor_action_rects)
        if action is not None:
            game._handle_editor_action(action)
            return

        if game.editor.paste_pending:
            game.editor.paste_clipboard(game.editor.pixel_to_tile(*pos))
            game.editor.paste_pending = False
            return

        if game.editor.active_tool in SHAPE_TOOLS:
            # Preview-while-dragging tools: this click just starts the
            # drag -- see _handle_editor_motion/_handle_editor_mouse_up
            # for how it's previewed/committed.
            game.editor.begin_shape(game.editor.pixel_to_tile(*pos))
            return

        # Editor.paint_at() silently ignores a pixel outside the grid
        # (e.g. over the toolbar/sidebar, neither of which overlaps the
        # grid's own pixel range), so no further fencing is needed here.
        game.editor.paint_at(*pos)

    def _handle_editor_motion(self, pos, buttons):
        game = self.game
        if not buttons[0]:  # left button not held -> nothing to drag
            return
        if game.editor.active_tool in SHAPE_TOOLS:
            game.editor.update_shape_preview(game.editor.pixel_to_tile(*pos))
        else:
            game.editor.paint_at(*pos)

    def _handle_editor_mouse_up(self, pos):
        """Ends whatever the left button was doing on the grid: a
        freeform drag-paint stroke (see Editor.begin_stroke(), called
        from _apply_tool() on the first cell of the stroke), or a Line/
        Rect/Select drag (committed here instead)."""
        game = self.game
        if game.editor.active_tool in SHAPE_TOOLS:
            game.editor.commit_shape(game.editor.pixel_to_tile(*pos))
        else:
            game.editor.end_stroke()

    def _handle_wave_editor_click(self, pos):
        game = self.game
        tab = ui.get_clicked_wave_tab(pos, game._wave_tab_rects())
        if tab == "add":
            game.editor.add_wave()
            return
        if tab == "remove":
            game.editor.remove_wave()
            return
        if tab is not None:  # an int wave index
            game.editor.set_active_wave(tab)
            return

        # A row scrolled above/below the visible list still has a real
        # (just off-viewport) Rect -- see build_wave_unit_rects -- so a
        # click outside the scrollable viewport must never match one, same
        # fence _handle_level_select_click applies to its own rows.
        unit_key = None
        if ui.WAVE_UNIT_ROWS_TOP <= pos[1] <= ui.WAVE_UNIT_ROWS_BOTTOM:
            unit_key = ui.get_clicked_wave_unit_button(pos, game.wave_unit_rects)
        if unit_key is not None:
            enemy_name, sign = unit_key
            game.editor.adjust_unit_count(enemy_name, +1 if sign == "plus" else -1)
            return

        action = ui.get_clicked_wave_editor_action(pos, game.wave_editor_action_rects)
        if action is not None:
            game._handle_wave_editor_action(action)
            return

        # Not on any button -- maybe a spawn marker in the read-only path
        # preview was clicked, switching which spawn's counts the +/-
        # buttons above now target. set_active_spawn() itself already
        # no-ops for a cell that isn't actually a spawn, so nothing here
        # needs to fence the click to "did it land on a real marker" first.
        game.editor.set_active_spawn(game.editor.pixel_to_tile(*pos))

    def _handle_level_select_click(self, pos):
        from game import GameState  # see module docstring

        game = self.game
        # A row scrolled off the top/bottom still has a real (just
        # off-viewport) Rect -- see build_level_select_rects -- so a click
        # outside the visible list area must never match one.
        if not (ui.LEVEL_SELECT_TOP <= pos[1] <= ui.LEVEL_SELECT_BOTTOM):
            return
        key = ui.get_clicked_level_select_entry(pos, game.level_select_rects)
        if key is None:
            return
        if game.level_select_purpose == "edit":
            game.editor.load_level(game._custom_levels_by_id[key])
            game.state = GameState.EDITOR
        elif isinstance(key, int):
            # Practice mode has no notion of a locked level (see
            # _enter_level_select) -- picking any built-in id always works.
            game.load_level(key, endless=game.level_select_endless_armed, sandbox=True)
            game.state = GameState.PLAYING
        else:
            game.load_custom_level(
                game._custom_levels_by_id[key],
                endless=game.level_select_endless_armed, sandbox=True,
            )
            game.state = GameState.PLAYING

    def _handle_settings_click(self, pos):
        from game import GameState  # see module docstring

        game = self.game
        # Checked before the SETTINGS_OPTION_ORDER-keyed lookup below --
        # the Volume -/+ buttons live in their own small rect dict, not
        # settings_rects, since they're a different shape (inline on the
        # Sound row, not part of the stacked column) than every other
        # Settings option -- see ui.build_volume_button_rects' own comment.
        volume_button = ui.get_clicked_volume_button(pos, game.volume_button_rects)
        if volume_button is not None:
            game.adjust_sound_volume(1 if volume_button == "up" else -1)
            return

        option = ui.get_clicked_settings_option(pos, game.settings_rects)
        if option == "fullscreen":
            game.set_fullscreen(not game.fullscreen)
        elif option == "sound":
            game.set_sound_enabled(not game.sound_enabled)
        elif option in difficulty.DIFFICULTY_MODES:
            game.set_difficulty(option)
        elif option in ui.WINDOW_SIZE_PRESETS:
            game.set_window_size(ui.WINDOW_SIZE_PRESETS[option])
        elif option == "back":
            game.state = GameState.MENU

    def _handle_static_screen_back_click(self, pos, back_rect):
        """Shared body for every full-screen "click the Back to Menu
        button" handler below -- kept as separate, per-screen public
        methods (rather than one handler threaded through handle_events'
        own click-routing table) so each stays independently named and
        directly callable, matching how Game's other per-state click
        handlers are organized."""
        from game import GameState  # see module docstring

        if back_rect.collidepoint(pos):
            self.game.state = GameState.MENU

    def _handle_achievements_click(self, pos):
        self._handle_static_screen_back_click(pos, self.game.achievements_back_rect)

    def _handle_help_click(self, pos):
        self._handle_static_screen_back_click(pos, self.game.help_back_rect)

    def _handle_credits_click(self, pos):
        self._handle_static_screen_back_click(pos, self.game.credits_back_rect)

    def _handle_map_click(self, pos):
        """A click on the map screen -- a silent no-op if it didn't land on
        a currently-available node, same "click does nothing" precedent
        try_place_tower's own unbuildable-spot case already sets."""
        game = self.game
        node_id = ui.get_clicked_map_node(pos, game.map_node_rects)
        if node_id is None or node_id not in game._available_node_ids():
            return
        game._enter_node(node_id)

    def _handle_draft_click(self, pos):
        """A click anywhere on the Shop screen -- either the Continue
        button (leave the shop and return to the map, buying nothing else)
        or one of this visit's item cards (attempt to buy it)."""
        game = self.game
        if game.shop_continue_button_rect.collidepoint(pos):
            game._finish_node(game.active_run.current_node_id)
            return
        index = ui.get_clicked_draft_choice(pos, game.draft_choice_rects)
        if index is None or index in game.shop_purchased_indices:
            return
        game._try_buy_shop_item(index)

    def _handle_event_click(self, pos):
        """A click on the Event screen -- in the "resolved" phase (an
        option's already been picked), any click moves on, same "press any
        key to continue" spirit FLOOR_CLEARED's own keydown handling uses;
        otherwise resolves whichever option (if any) was clicked."""
        game = self.game
        if game.event_phase == "resolved":
            game._finish_node(game.active_run.current_node_id)
            return
        index = ui.get_clicked_event_option(pos, game.event_option_rects)
        if index is None:
            return
        game._resolve_event_choice(index)

    def _handle_click(self, pos):
        from game import GameState  # see module docstring

        game = self.game
        if game.state != GameState.PLAYING:
            return

        clicked_button = ui.get_clicked_tower_button(pos, game.button_rects)
        if clicked_button is not None:
            game.selected_tower_name = None if clicked_button == game.selected_tower_name else clicked_button
            game.selected_tower = None  # switching to build mode drops any pinned placed-tower panel
            return

        if game.skip_button_rect.collidepoint(pos):
            game.wave_manager.skip_delay()
            return

        if game.speed_button_rect.collidepoint(pos):
            game.cycle_time_scale()
            return

        if game.active_run is not None and game.relics_button_rect.collidepoint(pos):
            game.state = GameState.RELICS
            return

        if self._handle_panel_action_click(pos):
            return

        if pos[0] >= settings.PLAY_WIDTH:
            return  # click landed in the stats panel but not on a button

        if pos[1] >= settings.SCREEN_HEIGHT - settings.HUD_HEIGHT:
            return  # click landed in the HUD area but not on a button

        for tower in game.towers:
            if tower.contains_upgrade_badge(pos):
                game.try_upgrade_tower(tower)
                return

        for tower in game.towers:
            if tower.contains_point(pos):
                game.selected_tower = tower  # pin it open in the stats panel
                return

        if game.selected_tower_name is not None:
            anchor_col, anchor_row = game.grid.placement_anchor(*pos, footprint_subtiles=game._current_footprint_subtiles())
            game.try_place_tower(anchor_col, anchor_row)
        else:
            game.selected_tower = None  # clicked empty ground -> deselect

    def _handle_panel_action_click(self, pos):
        """Handles a click on the stats panel's Upgrade/Specialize/Sell
        buttons. Returns True if `pos` was on one of them -- whether or
        not it actually did anything, e.g. an unaffordable upgrade still
        "belongs" to that button rather than falling through to the grid
        underneath it -- so the caller knows to stop processing this click.

        Uses game._last_panel_subject (what render() last showed) rather
        than re-deriving the subject from game._hovered_tower() at click
        time: by the time the mouse is actually over one of these buttons,
        it's no tower's tile_rect() ever reaches the panel to check -- so a
        fresh lookup here always reads as "not hovering anything" and
        silently falls back to whatever else is pinned/selected, which
        can easily be a *different* tower than the one whose button the
        player is actually looking at and clicking."""
        game = self.game
        subject = game._last_panel_subject
        is_tower = subject in game.towers  # not a build-menu class or None

        if game.targeting_button_rect.collidepoint(pos):
            # The row isn't drawn for a support tower (see
            # ui.draw_tower_stats_panel's IS_SUPPORT guard), but this
            # Rect still occupies that screen position regardless of
            # subject -- without this guard, a click there while a
            # support tower is pinned/hovered would silently cycle an
            # attribute (targeting_mode) it inherits but never reads.
            if is_tower and not type(subject).IS_SUPPORT:
                subject.cycle_targeting_mode()
            return True

        if game.upgrade_button_rect.collidepoint(pos):  # noqa: SIM102 -- kept nested, see the fallthrough comment below
            if is_tower and not subject.is_max_level:
                game.try_upgrade_tower(subject)
                return True
            # Falls through rather than returning when there's no upgrade
            # to make: this rect is intentionally shared with the first
            # Specialize button (see ui.build_specialize_button_rects --
            # Upgrade and Specialize are mutually exclusive states), so a
            # maxed, specializable tower's click here needs to reach the
            # specialize handling below instead of silently doing nothing.

        for index, rect in enumerate(game.specialize_button_rects):
            if not rect.collidepoint(pos):
                continue
            if is_tower and subject.can_specialize:
                keys = list(subject.SPECIALIZATIONS.keys())
                if index < len(keys):
                    game.try_specialize_tower(subject, keys[index])
            return True

        if game.sell_button_rect.collidepoint(pos):
            if is_tower:
                game.try_sell_tower(subject)
            return True

        return False

    def _scroll_level_select(self, wheel_y):
        # pygame's MOUSEWHEEL.y is positive scrolling away from the
        # player (up the list -> less scroll_offset) and negative toward
        # them (down the list -> more) -- hence the sign flip.
        game = self.game
        max_scroll = ui.level_select_max_scroll(len(game.level_select_entries))
        game.level_select_scroll_offset -= wheel_y * ui.LEVEL_SELECT_SCROLL_STEP
        game.level_select_scroll_offset = max(0, min(game.level_select_scroll_offset, max_scroll))
        game._rebuild_level_select_rects()

    def _scroll_wave_unit_list(self, wheel_y):
        # Same sign flip as _scroll_level_select -- pygame's MOUSEWHEEL.y is
        # positive scrolling away from the player (up the list -> less
        # scroll_offset) and negative toward them (down the list -> more).
        game = self.game
        max_scroll = ui.wave_unit_max_scroll(len(ui.ENEMY_ORDER))
        game.wave_unit_scroll_offset -= wheel_y * ui.WAVE_UNIT_SCROLL_STEP
        game.wave_unit_scroll_offset = max(0, min(game.wave_unit_scroll_offset, max_scroll))
        game._rebuild_wave_unit_rects()
