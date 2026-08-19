"""Game state machine and main loop."""

import sys
from enum import Enum, auto

import pygame

import settings
import ui
from assets import AssetManager
from economy import Economy
from grid import Grid
from levels import LEVELS
from tower import TOWER_TYPES
from waves import WaveManager


class GameState(Enum):
    MENU = auto()
    PLAYING = auto()
    PAUSED = auto()
    GAME_OVER = auto()
    VICTORY = auto()


class Game:
    def __init__(self, unlimited_gold=False):
        self.unlimited_gold = unlimited_gold  # debug flag -- see main.py --unlimited-gold

        pygame.init()
        self.screen = pygame.display.set_mode((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT))
        pygame.display.set_caption(settings.WINDOW_TITLE)
        self.clock = pygame.time.Clock()

        self.font = pygame.font.SysFont(None, 32)
        self.small_font = pygame.font.SysFont(None, 22)
        self.tiny_font = pygame.font.SysFont(None, 16)  # tower upgrade badges

        self.assets = AssetManager()
        self.button_rects = ui.build_button_rects()
        self.skip_button_rect = ui.build_skip_button_rect()
        self.upgrade_button_rect = ui.build_upgrade_button_rect()
        self.specialize_button_rects = ui.build_specialize_button_rects()
        self.sell_button_rect = ui.build_sell_button_rect()

        self.state = GameState.MENU
        self.running = True

        self.current_level_id = 1
        self.load_level(self.current_level_id)

    def load_level(self, level_id):
        level = LEVELS[level_id]
        self.level = level
        self.grid = Grid(
            settings.GRID_COLS, settings.GRID_ROWS, settings.TILE_SIZE,
            level.waypoints_tiles, level.blocked_cells,
            subtiles_per_tile=settings.SUBTILES_PER_TILE,
            subtile_gap=settings.SUBTILE_GAP,
            subtile_gap_alpha=settings.SUBTILE_GAP_ALPHA,
        )
        self.economy = Economy(level.starting_gold, level.starting_lives, unlimited_gold=self.unlimited_gold)
        self.wave_manager = WaveManager(level, self.grid.waypoints_px)

        self.enemies = []
        self.towers = []
        self.projectiles = []
        self.selected_tower_name = None
        self.selected_tower = None  # placed Tower instance pinned open in the stats panel

    def reset(self):
        self.load_level(self.current_level_id)
        self.state = GameState.MENU

    def has_next_level(self):
        return (self.current_level_id + 1) in LEVELS

    def advance_or_replay_level(self):
        """Called on winning: move to the next level if the registry has
        one, else replay the current (final) level from scratch."""
        if self.has_next_level():
            self.current_level_id += 1
        self.load_level(self.current_level_id)

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
                self._handle_click(event.pos)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                self._handle_right_click()

    def _handle_keydown(self, key):
        if self.state == GameState.MENU:
            if key == pygame.K_ESCAPE:
                self.running = False
            else:
                self.state = GameState.PLAYING
        elif self.state == GameState.PLAYING:
            if key in (pygame.K_p, pygame.K_ESCAPE):
                self.state = GameState.PAUSED
            elif key == pygame.K_SPACE:
                self.wave_manager.skip_delay()
        elif self.state == GameState.PAUSED:
            if key in (pygame.K_p, pygame.K_ESCAPE):
                self.state = GameState.PLAYING
            elif key == pygame.K_r:
                self.reset()
                self.state = GameState.PLAYING
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

        if self.upgrade_button_rect.collidepoint(pos):
            subject = self._stats_panel_subject(self._hovered_tower())
            if subject in self.towers and not subject.is_max_level:
                self.try_upgrade_tower(subject)
                return
            # Falls through rather than returning when there's no
            # upgrade to make: this rect is intentionally shared with the
            # first Specialize button (see ui.build_specialize_button_rects
            # -- Upgrade and Specialize are mutually exclusive states), so
            # a maxed, specializable tower's click here needs to reach the
            # specialize handling below instead of silently doing nothing.

        for index, rect in enumerate(self.specialize_button_rects):
            if not rect.collidepoint(pos):
                continue
            subject = self._stats_panel_subject(self._hovered_tower())
            if subject in self.towers and subject.can_specialize:
                keys = list(subject.SPECIALIZATIONS.keys())
                if index < len(keys):
                    self.try_specialize_tower(subject, keys[index])
            return

        if self.sell_button_rect.collidepoint(pos):
            subject = self._stats_panel_subject(self._hovered_tower())
            if subject in self.towers:  # a placed tower, not a build-menu class or None
                self.try_sell_tower(subject)
            return

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

    def try_place_tower(self, anchor_col, anchor_row):
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
        return True

    def try_upgrade_tower(self, tower):
        cost = tower.upgrade_cost()
        if cost is None or not self.economy.can_afford(cost):
            return False

        self.economy.spend(cost)
        tower.upgrade()
        return True

    def try_specialize_tower(self, tower, key):
        if not tower.can_specialize or key not in tower.SPECIALIZATIONS:
            return False
        cost = tower.specialization_cost()
        if not self.economy.can_afford(cost):
            return False

        self.economy.spend(cost)
        tower.specialize(key)
        return True

    def try_sell_tower(self, tower):
        if tower not in self.towers:
            return False

        self.economy.add_gold(tower.sell_value())
        self.towers.remove(tower)
        self.grid.remove(tower.anchor_col, tower.anchor_row)
        if self.selected_tower is tower:
            self.selected_tower = None
        return True

    # --- Update ---

    def update(self, dt):
        if self.state != GameState.PLAYING:
            return

        for enemy in self.enemies:
            enemy.update(dt)

        for tower in self.towers:
            tower.update(dt, self.enemies, self.projectiles)

        for projectile in self.projectiles:
            projectile.update(dt, self.enemies)
        self.projectiles = [p for p in self.projectiles if not p.dead]

        still_alive = []
        for enemy in self.enemies:
            if enemy.is_dead:
                self.economy.add_gold(enemy.gold_reward)
            elif enemy.reached_goal:
                self.economy.lose_life()
            else:
                still_alive.append(enemy)
        self.enemies = still_alive

        self.enemies.extend(self.wave_manager.update(dt, self.enemies))

        if self.economy.is_out_of_lives:
            self.state = GameState.GAME_OVER
        elif self.wave_manager.all_waves_complete and not self.enemies:
            self.state = GameState.VICTORY

    # --- Render ---

    def render(self):
        self.screen.fill(settings.COLOR_BG)

        if self.state == GameState.MENU:
            ui.draw_menu_screen(self.screen, self.font, self.small_font)
            pygame.display.flip()
            return

        self.grid.draw(self.screen, self.assets)
        for tower in self.towers:
            tower.draw(self.screen, self.assets, self.tiny_font)
        for enemy in self.enemies:
            enemy.draw(self.screen, self.assets)
        for projectile in self.projectiles:
            projectile.draw(self.screen, self.assets)

        self._render_placement_preview()
        hovered_tower = self._hovered_tower()
        panel_subject = self._stats_panel_subject(hovered_tower)
        if panel_subject in self.towers:  # a placed tower (hovered, or pinned via selected_tower)
            ui.draw_tower_range_preview(self.screen, panel_subject)

        ui.draw_hud(
            self.screen, self.assets, self.font, self.small_font,
            self.economy, self.wave_manager, self.button_rects,
            self.skip_button_rect, self.selected_tower_name,
        )
        ui.draw_tower_stats_panel(
            self.screen, self.font, self.small_font, panel_subject, self.economy,
            self.upgrade_button_rect, self.specialize_button_rects, self.sell_button_rect,
        )

        if self.state == GameState.PAUSED:
            ui.draw_pause_menu(self.screen, self.font, self.small_font)
        elif self.state == GameState.GAME_OVER:
            ui.draw_game_over_screen(self.screen, self.font, self.small_font)
        elif self.state == GameState.VICTORY:
            ui.draw_victory_screen(self.screen, self.font, self.small_font, self.has_next_level())

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
