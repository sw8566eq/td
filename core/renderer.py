"""Game.render() and its one drawing helper, extracted into their own
module -- the first cut of game.py's own god-object decomposition (see
CLAUDE.md's own note on why `render()` was the slice picked to go
first). Both methods only ever read Game's state and delegate to ui.py's
drawing functions; the only state either one ever *writes* is
Game._last_panel_subject, a value Game._handle_panel_action_click (still
on Game itself, since it also drives real gold-spending actions) reads
back afterward -- see CLAUDE.md's "Stats panel subject resolution"
section for why that one field has to be set here, at render time, rather
than recomputed at click time.

Renderer holds a `game` reference rather than being handed each piece of
state it needs individually -- render() alone reads on the order of 40
distinct Game attributes/methods across its own per-state dispatch, so a
narrower constructor parameter list would just be the same coupling
spelled out longhand, not less of it. Every hit-testing/query helper
render() calls (_hovered_tower, _stats_panel_subject, ...) stays on Game
itself rather than moving here, since Game._handle_click/
_handle_panel_action_click read those exact same methods to resolve what
a click should act on -- CLAUDE.md is explicit that the panel and its
action buttons must always agree on which tower they mean, which is only
guaranteed by both sides sharing one method, not two copies kept in sync
by hand.

GameState is imported lazily, inside render() itself, rather than at
module level -- Game constructs a Renderer(self) (see Game.__init__), so
a top-level `from game import GameState` here would be a circular import
(game.py -> renderer.py -> game.py) evaluated before GameState even
exists yet, partway through game.py's own module-level execution.
Deferred until render() actually runs, well after both modules have
finished loading, there's nothing left to cycle on.
"""

import pygame

from entities.tower import TOWER_TYPES
from presentation import ui
from support import settings


class Renderer:
    def __init__(self, game):
        self.game = game

    def render(self):
        from core.game import GameState  # see module docstring

        game = self.game
        game.screen.fill(settings.COLOR_BG)

        if game.state == GameState.MENU:
            ui.draw_menu_screen(game.screen, game.font, game.small_font, game.has_saved_run)
            pygame.display.flip()
            return

        if game.state == GameState.SETTINGS:
            ui.draw_settings_screen(
                game.screen, game.font, game.small_font, game.settings_rects,
                game.fullscreen, game.sound_enabled, game.difficulty, game.window_size,
                game.sound_volume, game.volume_button_rects, game.keybinds_entry_button_rect,
            )
            pygame.display.flip()
            return

        if game.state == GameState.KEYBINDS:
            ui.draw_keybinds_screen(
                game.screen, game.font, game.small_font, game.keybind_row_rects,
                game.keybindings, game.keybind_listening_for, game.keybind_message,
                game.keybinds_reset_rect, game.keybinds_back_rect,
            )
            pygame.display.flip()
            return

        if game.state == GameState.ACHIEVEMENTS:
            ui.draw_achievements_screen(
                game.screen, game.font, game.small_font,
                game.achievements_state["unlocked"], game.achievements_state["counters"],
                game.achievements_scroll_offset, game.achievements_back_rect,
            )
            pygame.display.flip()
            return

        if game.state == GameState.RUN_HISTORY:
            ui.draw_run_history_screen(
                game.screen, game.font, game.small_font,
                game.run_history_state, game.run_history_scroll_offset, game.run_history_back_rect,
            )
            pygame.display.flip()
            return

        if game.state == GameState.UNLOCKS:
            ui.draw_unlocks_screen(
                game.screen, game.font, game.small_font,
                game.unlocks_state["unlocked"], game.unlocks_state["counters"],
                game.unlocks_scroll_offset, game.unlocks_back_rect,
            )
            pygame.display.flip()
            return

        if game.state == GameState.HELP:
            ui.draw_help_screen(
                game.screen, game.font, game.small_font, game.help_back_rect, game.run_guide_entry_button_rect,
            )
            pygame.display.flip()
            return

        if game.state == GameState.RUN_GUIDE:
            ui.draw_run_guide_screen(game.screen, game.font, game.small_font, game.run_guide_back_rect)
            pygame.display.flip()
            return

        if game.state == GameState.CREDITS:
            ui.draw_credits_screen(game.screen, game.font, game.small_font, game.credits_back_rect)
            pygame.display.flip()
            return

        if game.state == GameState.EDITOR:
            ui.draw_editor_screen(
                game.screen, game.assets, game.font, game.small_font,
                game.editor, game.editor_tool_rects, game.editor_action_rects,
                game.import_status_message, game.import_status_is_error,
            )
            pygame.display.flip()
            return

        if game.state == GameState.WAVE_EDITOR:
            ui.draw_wave_editor_screen(
                game.screen, game.assets, game.font, game.small_font,
                game.editor, game._wave_tab_rects(), game.wave_unit_rects, game.wave_editor_action_rects,
                game.last_saved_path, game.wave_unit_scroll_offset,
            )
            pygame.display.flip()
            return

        if game.state == GameState.LEVEL_SELECT:
            ui.draw_level_select_screen(
                game.screen, game.font, game.small_font,
                game.level_select_entries, game.level_select_rects, game.level_select_thumbnails,
                game.level_select_purpose, game.level_select_scroll_offset, game.level_select_endless_armed,
            )
            pygame.display.flip()
            return

        # MAP/DRAFT/EVENT/REST/TREASURE are all full-screen, board-less
        # states now (see GameState's own comment on why) -- each guarded
        # on active_run is not None the same way FLOOR_CLEARED's own
        # overlay below still is: active_run is None only ever happens by
        # force-setting state directly (e.g. the render() smoke test's
        # blanket sweep across every GameState), in which case falling
        # through to the normal board/HUD/panel drawing below (with no
        # overlay on top) is fine; crashing on it wouldn't be.
        if game.state == GameState.MAP and game.active_run is not None:
            run = game.active_run
            # lives/shop_currency are meaningless before the run's very
            # first node has ever loaded (run.lives is still its 0
            # placeholder -- see RunState's own docstring) -- None hides
            # the readout entirely rather than showing a misleading
            # "Lives: 0" before any floor has actually been played.
            has_played_a_node = run.current_node_id is not None
            ui.draw_map_screen(
                game.screen, game.font, game.small_font, run.map, game.map_node_rects,
                run.current_node_id, run.visited_node_ids, game._available_node_ids(),
                game._hovered_map_node(),
                run.lives if has_played_a_node else None,
                run.shop_currency if has_played_a_node else None,
                first_run=game._map_is_first_run,
            )
            pygame.display.flip()
            return

        if game.state == GameState.DRAFT and game.active_run is not None:
            ui.draw_draft_screen(
                game.screen, game.font, game.small_font,
                game.draft_choices, game.draft_choice_rects, game._hovered_draft_choice(),
                game.shop_purchased_indices, game.active_run.shop_currency,
                game.shop_continue_button_rect, game.economy.unlimited_gold,
                game._shop_price_multiplier(),
            )
            pygame.display.flip()
            return

        if game.state == GameState.EVENT and game.active_run is not None:
            ui.draw_event_screen(
                game.screen, game.font, game.small_font, game.current_event, game.event_options,
                game.event_option_rects,
                game._hovered_event_option(), game.event_phase, game.event_chosen_option, game.event_resolution,
            )
            pygame.display.flip()
            return

        if game.state == GameState.REST and game.active_run is not None:
            ui.draw_rest_screen(
                game.screen, game.font, game.small_font, game.rest_heal_amount, game.active_run.lives,
            )
            pygame.display.flip()
            return

        if game.state == GameState.TREASURE and game.active_run is not None:
            ui.draw_treasure_screen(
                game.screen, game.font, game.small_font,
                game.treasure_granted_relic, game.treasure_granted_currency,
            )
            pygame.display.flip()
            return

        game.grid.draw(game.screen, game.assets)
        for tower in game.towers:
            tower.draw(game.screen, game.assets, game.tiny_font)
        for enemy in game.enemies:
            enemy.draw(game.screen, game.assets)
        for projectile in game.projectiles:
            projectile.draw(game.screen, game.assets)
        for ring in game.impact_effects:
            ring.draw(game.screen)
        for text in game.damage_numbers:
            text.draw(game.screen, game.tiny_font)

        self._render_placement_preview()
        hovered_tower = game._hovered_tower()
        panel_subject = game._stats_panel_subject(hovered_tower)
        game._last_panel_subject = panel_subject  # see _handle_panel_action_click
        if panel_subject in game.towers:  # a placed tower (hovered, or pinned via selected_tower)
            ui.draw_tower_range_preview(game.screen, panel_subject)

        # "Floor N/M" -- same 1-based node.row+1 / final_row_index+1 shape
        # FLOOR_CLEARED's own screen already uses, just also shown live
        # during PLAYING itself now, not only between floors.
        floor_label = (
            f"Floor {game.active_run.current_row + 1}/{game.active_run.map.final_row_index + 1}"
            if game.active_run is not None else None
        )
        ui.draw_hud(
            game.screen, game.assets, game.font, game.small_font,
            game.economy, game.wave_manager, game.button_rects,
            game.skip_button_rect, game.selected_tower_name,
            game.time_scale, game.speed_button_rect,
            game.wave_manager.next_wave_preview(),
            shop_currency=game.active_run.shop_currency if game.active_run is not None else None,
            relics_button_rect=game.relics_button_rect,
            relic_count=len(game.active_run.relics) if game.active_run is not None else None,
            floor_label=floor_label,
            boss_defeated=game.active_run.boss_defeated if game.active_run is not None else False,
        )
        if game._show_first_placement_hint and not game.towers:
            ui.draw_first_placement_hint(game.screen, game.small_font)
        ui.draw_tower_stats_panel(
            game.screen, game.font, game.small_font, panel_subject, game.economy,
            game.targeting_button_rect,
            game.upgrade_button_rect, game.specialize_button_rects, game.sell_button_rect,
            game._hovered_specialize_key(panel_subject),
        )
        for toast in game.achievement_toasts:
            toast.draw(game.screen, game.small_font)

        if game.state == GameState.PAUSED:
            ui.draw_pause_menu(game.screen, game.font, game.small_font,
                                game.current_level_id is None, game.can_save_run(),
                                game.pause_restart_confirm_pending,
                                ui.binding_display_string(game.keybindings["pause"]))
        elif game.state == GameState.RELICS and game.active_run is not None:
            # active_run is None only ever happens by force-setting state
            # directly (e.g. the render() smoke test's blanket sweep across
            # every GameState) -- real gameplay only ever reaches RELICS
            # via the HUD button/R, both gated on active_run already.
            ui.draw_relics_overlay(game.screen, game.font, game.small_font, game.active_run.relics)
        elif game.state == GameState.GAME_OVER:
            ui.draw_game_over_screen(game.screen, game.font, game.small_font, game._cached_tower_results)
        elif game.state == GameState.VICTORY:
            ui.draw_victory_screen(game.screen, game.font, game.small_font, game.has_next_level(),
                                    game._cached_tower_results)
        elif game.state == GameState.FLOOR_CLEARED and game.active_run is not None:
            # active_run is None only ever happens by force-setting state
            # directly (e.g. the render() smoke test's blanket sweep across
            # every GameState) -- real gameplay only ever reaches
            # FLOOR_CLEARED via _advance_run_floor, which requires one.
            # Drawing nothing for that otherwise-unreachable combination is
            # fine; crashing on it wouldn't be. Kept as a frozen-board
            # overlay (unlike MAP/DRAFT/EVENT/REST/TREASURE above) since
            # it's always reached immediately from real combat on a board
            # that still exists -- see GameState's own comment on this
            # split.
            node = game.active_run.map.node(game.active_run.current_node_id)
            ui.draw_floor_cleared_screen(
                game.screen, game.font, game.small_font,
                node.row + 1, game.active_run.map.final_row_index + 1,
                game._cached_tower_results,
            )

        pygame.display.flip()

    def _render_placement_preview(self):
        game = self.game
        if game.selected_tower_name is None:
            return
        mouse_pos = pygame.mouse.get_pos()
        if mouse_pos[1] >= settings.SCREEN_HEIGHT - settings.HUD_HEIGHT:
            return
        if mouse_pos[0] >= settings.PLAY_WIDTH:
            return  # hovering the stats panel, not the grid
        tower_cls = TOWER_TYPES[game.selected_tower_name]
        footprint_subtiles = game._current_footprint_subtiles()
        anchor_col, anchor_row = game.grid.placement_anchor(*mouse_pos, footprint_subtiles=footprint_subtiles)
        preview_pos = game.grid.anchor_to_pixel_center(anchor_col, anchor_row, footprint_subtiles=footprint_subtiles)
        buildable = game.grid.is_buildable(anchor_col, anchor_row, footprint_subtiles=footprint_subtiles)
        ui.draw_footprint_preview(game.screen, game.grid, anchor_col, anchor_row, buildable, footprint_subtiles=footprint_subtiles)
        ui.draw_range_preview(game.screen, tower_cls, preview_pos)
