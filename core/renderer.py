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
from run import potions, relics, shop
from support import settings


class Renderer:
    def __init__(self, game):
        self.game = game

    def render(self):
        from core.game import GameState  # see module docstring

        game = self.game
        game.screen.fill(settings.COLOR_BG)

        if game.state == GameState.MENU:
            ui.draw_menu_screen(game.screen, game.font, game.small_font, game.has_saved_run,
                                game.selected_ascension, game.highest_ascension)
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
                ui.run_history_lines(game.run_history_state, game.run_history_records),
                game.run_history_scroll_offset, game.run_history_back_rect,
            )
            pygame.display.flip()
            return

        if game.state == GameState.COMPENDIUM:
            ui.draw_compendium_screen(
                game.screen, game.font, game.small_font, game.compendium_rows,
                game.compendium_scroll_offset, game.unlocks_back_rect,
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
                back_to_map=game.help_return_state == GameState.MAP, bindings=game.keybindings,
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
        relics_over_map = game.state == GameState.RELICS and game.relics_return_state == GameState.MAP
        if (game.state == GameState.MAP or relics_over_map) and game.active_run is not None:
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
                first_run=game._map_is_first_run, ascension_level=run.ascension, act_number=run.act + 1,
                node_affixes=game.map_node_affixes, relic_count=len(run.relics), node_threats=game.map_node_threats,
                relics_key_label=ui.binding_display_string(game.keybindings["open_relics"]),
                potion_names=[potions.POTIONS[key].display_name for key in run.potions],
            )
            if relics_over_map:
                ui.draw_relics_overlay(game.screen, game.font, game.small_font, run.relics,
                                       width=settings.SCREEN_WIDTH)
            self._draw_toasts()
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
            if game.shop_potion is not None:
                ui.draw_shop_potion_button(
                    game.screen, game.small_font, game.shop_potion_rect, game.shop_potion,
                    game._shop_potion_price(), game.shop_potion_bought, game._can_buy_shop_potion(),
                    hovered=game.shop_potion_rect.collidepoint(pygame.mouse.get_pos()),
                )
            curses = relics.held_curses(game.active_run)
            if curses or game.shop_curse_removed:
                ui.draw_shop_remove_curse_button(
                    game.screen, game.small_font, game.shop_remove_curse_rect, game._curse_removal_price(),
                    has_curse=bool(curses), used=game.shop_curse_removed,
                    affordable=shop.can_afford(game.active_run.shop_currency, game._curse_removal_price(),
                                               game.economy.unlimited_gold),
                )
            self._draw_toasts()
            pygame.display.flip()
            return

        if game.state == GameState.COMMANDER_SELECT:
            ui.draw_commander_select_screen(
                game.screen, game.font, game.small_font, game.commander_rects, game._hovered_commander(),
                game.commander_unlocked, game.commander_counters,
            )
            self._draw_toasts()
            pygame.display.flip()
            return

        if game.state == GameState.REWARD and game.active_run is not None:
            node = game.active_run.map.node(game.active_run.current_node_id)
            ui.draw_reward_screen(
                game.screen, game.font, game.small_font, game._reward_cards(), game.reward_rects,
                game._hovered_reward_card(), game.reward_claimed_indices,
                [game._reward_card_available(i) for i in range(len(game.reward_rects))],
                game.shop_continue_button_rect, is_elite=node.node_type == "elite", is_boss=node.node_type == "boss",
                forged_names=game.reward.forged_tower_choices,
                # Sealed Cask blocks new potions outright -- "FULL" would be a lie.
                potion_unavailable_tag="SEALED" if potions.potions_blocked(game.active_run) else "FULL",
            )
            self._draw_toasts()
            pygame.display.flip()
            return

        if game.state == GameState.EVENT and game.active_run is not None:
            ui.draw_event_screen(
                game.screen, game.font, game.small_font, game.current_event, game.event_options,
                game.event_option_rects,
                game._hovered_event_option(), game.event_phase, game.event_chosen_option, game.event_resolution,
                affordable=[game._can_afford_event_option(option) for option in game.event_options],
                status_line=self._run_status_line(),
            )
            self._draw_toasts()
            pygame.display.flip()
            return

        if game.state == GameState.REST and game.active_run is not None:
            ui.draw_rest_screen(
                game.screen, game.font, game.small_font, game.rest_phase, game.rest_heal_amount,
                game.active_run.lives, game.rest_option_rects, game.rest_smith_choices, game.rest_smith_rects,
                game.rest_back_rect, game.rest_forged_tower, game._hovered_rest_rect_index(),
                heal_blocked=game.rest_heal_blocked, moved_on=game.rest_moved_on,
            )
            self._draw_toasts()
            pygame.display.flip()
            return

        if game.state == GameState.TREASURE and game.active_run is not None:
            ui.draw_treasure_screen(
                game.screen, game.font, game.small_font,
                game.treasure_granted_relic, game.treasure_granted_currency,
            )
            self._draw_toasts()
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
            f"Act {game.active_run.act + 1}  Floor {game.active_run.current_row + 1}/{game.active_run.map.final_row_index + 1}"
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
            forged_towers=game.active_run.forged_towers if game.active_run is not None else (),
            endless_waves=game.active_run.endless_waves_cleared if game.active_run is not None else 0,
        )
        if game._show_first_placement_hint and not game.towers:
            ui.draw_first_placement_hint(game.screen, game.small_font)
        ui.draw_tower_stats_panel(
            game.screen, game.font, game.small_font, panel_subject, game.economy,
            game.targeting_button_rect,
            game.upgrade_button_rect, game.specialize_button_rects, game.sell_button_rect,
            game._hovered_specialize_key(panel_subject),
        )
        if game.active_run is not None:
            ui.draw_potion_belt(
                game.screen, game.font, game.small_font, game.active_run.potions, game.potion_slot_rects,
                game._hovered_potion_slot(), game.overclock_timer, self._run_modifiers_text(),
            )
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
            ui.draw_game_over_screen(
                game.screen, game.font, game.small_font, game._cached_tower_results,
                ui.run_summary_lines(game.active_run) if game.active_run is not None else None,
            )
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
                act_cleared=game.active_run.act + 1 if node.node_type == "boss" else None,
            )

        # Drawn last, on top of any overlay -- a toast is most often queued
        # by the very event that raises FLOOR_CLEARED/GAME_OVER (a floor
        # clear's meta-unlock, a permadeath's runs_played unlock).
        self._draw_toasts()
        pygame.display.flip()

    def _run_status_line(self):
        """"Lives / Shop currency / Potions" for the Event screen, whose
        options cost exactly those -- the same readout the map shows."""
        run = self.game.active_run
        return (f"Lives: {run.lives}   Shop currency: {round(run.shop_currency)}   "
                f"Potions: {len(run.potions)}/{potions.slot_count(run)}   Relics: {len(run.relics)}")

    def _run_modifiers_text(self):
        """"Ascension N, <Affix> elite" for the sidebar -- whichever of the
        two apply to this floor, or None. Kept off the HUD's Wave line,
        which has no room left with a full 12-tower build menu."""
        run = self.game.active_run
        parts = []
        if run.ascension:
            parts.append(f"Ascension {run.ascension}")
        if run.current_node_id is not None:
            affix = self.game._elite_affix(run, run.map.node(run.current_node_id))
            if affix is not None:
                parts.append(f"{affix.display_name} elite")
        return ", ".join(parts) or None

    def _draw_toasts(self):
        """Achievement/unlock toasts -- shared by the board and by every
        full-screen run state (MAP/DRAFT/EVENT/REST/TREASURE), since relic,
        event, and floor-clear unlocks are all queued from outside combat."""
        game = self.game
        for toast in game.achievement_toasts:
            # A dark backing plate, so a toast stays legible over whatever
            # screen title or map node it happens to land on.
            if not toast.dead:
                plate = pygame.Rect((0, 0), game.small_font.size(toast.text)).inflate(16, 6)
                plate.center = (int(toast.pos.x), int(toast.pos.y))
                backing = pygame.Surface(plate.size, pygame.SRCALPHA)
                alpha = max(0, min(200, int(200 * (1 - toast.age / toast.lifetime))))
                backing.fill((*settings.COLOR_BG, alpha))
                game.screen.blit(backing, plate)
            toast.draw(game.screen, game.small_font)

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
