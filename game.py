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
    def __init__(self):
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
        )
        self.economy = Economy(level.starting_gold, level.starting_lives)
        self.wave_manager = WaveManager(level, self.grid.waypoints_px)

        self.enemies = []
        self.towers = []
        self.projectiles = []
        self.selected_tower_name = None

    def reset(self):
        self.load_level(self.current_level_id)
        self.state = GameState.MENU

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

    def _handle_keydown(self, key):
        if key == pygame.K_ESCAPE:
            self.running = False
            return

        if self.state == GameState.MENU:
            self.state = GameState.PLAYING
        elif self.state == GameState.PLAYING:
            if key == pygame.K_p:
                self.state = GameState.PAUSED
            elif key == pygame.K_SPACE:
                self.wave_manager.skip_delay()
        elif self.state == GameState.PAUSED:
            if key == pygame.K_p:
                self.state = GameState.PLAYING
        elif self.state in (GameState.GAME_OVER, GameState.VICTORY):
            if key == pygame.K_r:
                self.reset()
                self.state = GameState.PLAYING

    def _handle_click(self, pos):
        if self.state != GameState.PLAYING:
            return

        clicked_button = ui.get_clicked_tower_button(pos, self.button_rects)
        if clicked_button is not None:
            self.selected_tower_name = None if clicked_button == self.selected_tower_name else clicked_button
            return

        if self.skip_button_rect.collidepoint(pos):
            self.wave_manager.skip_delay()
            return

        if pos[1] >= settings.SCREEN_HEIGHT - settings.HUD_HEIGHT:
            return  # click landed in the HUD area but not on a button

        for tower in self.towers:
            if tower.contains_upgrade_badge(pos):
                self.try_upgrade_tower(tower)
                return

        if self.selected_tower_name is not None:
            col, row = self.grid.pixel_to_tile(*pos)
            self.try_place_tower(col, row)

    def try_place_tower(self, col, row):
        if not self.grid.is_buildable(col, row):
            return False

        tower_cls = TOWER_TYPES[self.selected_tower_name]
        if not self.economy.can_afford(tower_cls.cost):
            return False

        self.economy.spend(tower_cls.cost)
        pixel_pos = self.grid.tile_to_pixel_center(col, row)
        tower = tower_cls(col, row, pixel_pos)
        self.towers.append(tower)
        self.grid.occupy(col, row, tower)
        return True

    def try_upgrade_tower(self, tower):
        cost = tower.upgrade_cost()
        if cost is None or not self.economy.can_afford(cost):
            return False

        self.economy.spend(cost)
        tower.upgrade()
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
        if hovered_tower is not None:
            ui.draw_tower_range_preview(self.screen, hovered_tower)

        ui.draw_hud(
            self.screen, self.assets, self.font, self.small_font,
            self.economy, self.wave_manager, self.button_rects,
            self.skip_button_rect, self.selected_tower_name,
        )
        ui.draw_tower_stats_panel(
            self.screen, self.font, self.small_font, self._stats_panel_subject(hovered_tower),
        )

        if self.state == GameState.PAUSED:
            ui.draw_pause_overlay(self.screen, self.font, self.small_font)
        elif self.state == GameState.GAME_OVER:
            ui.draw_game_over_screen(self.screen, self.font, self.small_font)
        elif self.state == GameState.VICTORY:
            ui.draw_victory_screen(self.screen, self.font, self.small_font)

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
        col, row = self.grid.pixel_to_tile(*mouse_pos)
        preview_pos = self.grid.tile_to_pixel_center(col, row)
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
        """What the stats panel should show: a hovered placed tower takes
        priority; otherwise the tower type currently selected to build;
        otherwise None (panel shows a hint)."""
        if hovered_tower is not None:
            return hovered_tower
        if self.selected_tower_name is not None:
            return TOWER_TYPES[self.selected_tower_name]
        return None
