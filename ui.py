"""HUD, build menu, and full-screen overlay rendering.

Button hit-testing (get_clicked_tower_button) is kept as pure Rect geometry,
separate from drawing, so it's unit-testable without a display. The build
menu iterates TOWER_TYPES, so a new tower registered there appears in the
UI automatically.
"""

import pygame

import settings
from tower import TOWER_TYPES

BUTTON_SIZE = 72
BUTTON_MARGIN = 12
BUTTON_Y = settings.SCREEN_HEIGHT - settings.HUD_HEIGHT + (settings.HUD_HEIGHT - BUTTON_SIZE) // 2

TOWER_ORDER = list(TOWER_TYPES.keys())  # stable UI order = registry insertion order


def build_button_rects():
    """Rects for each tower's build-menu button, keyed by registry name."""
    rects = {}
    x = BUTTON_MARGIN
    for name in TOWER_ORDER:
        rects[name] = pygame.Rect(x, BUTTON_Y, BUTTON_SIZE, BUTTON_SIZE)
        x += BUTTON_SIZE + BUTTON_MARGIN
    return rects


def get_clicked_tower_button(pos, button_rects):
    """Return the tower registry name whose button contains pos, or None."""
    for name, rect in button_rects.items():
        if rect.collidepoint(pos):
            return name
    return None


def draw_hud(surface, assets, font, small_font, economy, wave_manager, button_rects, selected_tower_name):
    hud_rect = pygame.Rect(0, settings.SCREEN_HEIGHT - settings.HUD_HEIGHT,
                            settings.SCREEN_WIDTH, settings.HUD_HEIGHT)
    pygame.draw.rect(surface, settings.COLOR_HUD_BG, hud_rect)

    for name, rect in button_rects.items():
        tower_cls = TOWER_TYPES[name]
        affordable = economy.can_afford(tower_cls.cost)
        if name == selected_tower_name:
            color = settings.COLOR_BUTTON_SELECTED
        elif affordable:
            color = settings.COLOR_BUTTON
        else:
            color = settings.COLOR_BUTTON_DISABLED
        pygame.draw.rect(surface, color, rect, border_radius=6)

        icon_size = BUTTON_SIZE - 20
        icon = assets.get(tower_cls.sprite_name, (icon_size, icon_size))
        icon_rect = icon.get_rect(center=(rect.centerx, rect.centery - 8))
        surface.blit(icon, icon_rect)

        cost_text = small_font.render(str(tower_cls.cost), True, settings.COLOR_TEXT)
        cost_rect = cost_text.get_rect(center=(rect.centerx, rect.bottom - 10))
        surface.blit(cost_text, cost_rect)

    info_x = BUTTON_MARGIN + len(TOWER_ORDER) * (BUTTON_SIZE + BUTTON_MARGIN) + 20
    gold_text = font.render(f"Gold: {economy.gold}", True, settings.COLOR_GOLD)
    lives_text = font.render(f"Lives: {economy.lives}", True, settings.COLOR_LIVES)
    if wave_manager.all_waves_complete:
        wave_label = "All waves cleared!"
    else:
        wave_label = f"Wave {wave_manager.current_wave_number}/{wave_manager.total_waves}"
    wave_text = font.render(wave_label, True, settings.COLOR_TEXT)

    surface.blit(gold_text, (info_x, hud_rect.y + 8))
    surface.blit(lives_text, (info_x, hud_rect.y + 36))
    surface.blit(wave_text, (info_x, hud_rect.y + 64))


def draw_range_preview(surface, tower_cls, pixel_pos):
    pygame.draw.circle(
        surface, settings.COLOR_RANGE_PREVIEW,
        (int(pixel_pos[0]), int(pixel_pos[1])), tower_cls.range, width=1,
    )


def _draw_centered_overlay(surface, font, small_font, title, subtitle, title_color):
    overlay = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 170))
    surface.blit(overlay, (0, 0))

    title_text = font.render(title, True, title_color)
    title_rect = title_text.get_rect(center=(settings.SCREEN_WIDTH // 2, settings.SCREEN_HEIGHT // 2 - 20))
    surface.blit(title_text, title_rect)

    if subtitle:
        subtitle_text = small_font.render(subtitle, True, settings.COLOR_TEXT_DIM)
        subtitle_rect = subtitle_text.get_rect(center=(settings.SCREEN_WIDTH // 2, settings.SCREEN_HEIGHT // 2 + 20))
        surface.blit(subtitle_text, subtitle_rect)


def draw_menu_screen(surface, font, small_font):
    surface.fill(settings.COLOR_BG)
    _draw_centered_overlay(surface, font, small_font, "Tower Defense", "Press any key to start", settings.COLOR_TEXT)


def draw_pause_overlay(surface, font, small_font):
    _draw_centered_overlay(surface, font, small_font, "Paused", "Press P to resume", settings.COLOR_TEXT)


def draw_game_over_screen(surface, font, small_font):
    _draw_centered_overlay(surface, font, small_font, "Game Over", "Press R to restart", settings.COLOR_LIVES)


def draw_victory_screen(surface, font, small_font):
    _draw_centered_overlay(surface, font, small_font, "Victory!", "Press R to play again", settings.COLOR_GOLD)
