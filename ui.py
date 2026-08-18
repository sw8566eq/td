"""HUD, build menu, and full-screen overlay rendering.

Button hit-testing (get_clicked_tower_button) is kept as pure Rect geometry,
separate from drawing, so it's unit-testable without a display. The build
menu iterates TOWER_TYPES, so a new tower registered there appears in the
UI automatically.
"""

import inspect
import math

import pygame

import settings
from tower import TOWER_TYPES
from waves import WaveState

BUTTON_SIZE = 72
BUTTON_MARGIN = 12
BUTTON_Y = settings.SCREEN_HEIGHT - settings.HUD_HEIGHT + (settings.HUD_HEIGHT - BUTTON_SIZE) // 2

PANEL_PADDING = 16
PANEL_ROW_HEIGHT = 22

TOWER_ORDER = list(TOWER_TYPES.keys())  # stable UI order = registry insertion order

SKIP_BUTTON_WIDTH = 100
SKIP_BUTTON_HEIGHT = 36
SKIP_BUTTON_MARGIN = 16


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


def build_skip_button_rect():
    """Rect for the 'Skip' button that forces the next wave to start,
    anchored to the HUD's bottom-right corner (independent of how many
    tower buttons are registered on the left). Anchored to PLAY_WIDTH, not
    the full (wider, panel-including) SCREEN_WIDTH, so it stays within the
    HUD bar under the grid rather than drifting under the stats panel."""
    hud_top = settings.SCREEN_HEIGHT - settings.HUD_HEIGHT
    x = settings.PLAY_WIDTH - SKIP_BUTTON_WIDTH - SKIP_BUTTON_MARGIN
    y = hud_top + settings.HUD_HEIGHT - SKIP_BUTTON_HEIGHT - 10
    return pygame.Rect(x, y, SKIP_BUTTON_WIDTH, SKIP_BUTTON_HEIGHT)


def draw_hud(surface, assets, font, small_font, economy, wave_manager, button_rects,
             skip_button_rect, selected_tower_name):
    # Only as wide as the grid above it (PLAY_WIDTH), not the full window --
    # the stats panel to its right draws itself separately.
    hud_rect = pygame.Rect(0, settings.SCREEN_HEIGHT - settings.HUD_HEIGHT,
                            settings.PLAY_WIDTH, settings.HUD_HEIGHT)
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

    _draw_wave_countdown_and_skip(surface, small_font, wave_manager, skip_button_rect)


def _draw_wave_countdown_and_skip(surface, font, wave_manager, skip_button_rect):
    if wave_manager.all_waves_complete:
        return  # nothing left to skip to

    can_skip = wave_manager.state == WaveState.BETWEEN_WAVES
    if can_skip:
        seconds_left = max(0, math.ceil(wave_manager.between_wave_timer))
        countdown_text = font.render(f"Next wave in {seconds_left}s", True, settings.COLOR_TEXT)
    else:
        countdown_text = font.render("Wave in progress", True, settings.COLOR_TEXT_DIM)
    countdown_rect = countdown_text.get_rect(midbottom=(skip_button_rect.centerx, skip_button_rect.top - 6))
    surface.blit(countdown_text, countdown_rect)

    button_color = settings.COLOR_BUTTON if can_skip else settings.COLOR_BUTTON_DISABLED
    pygame.draw.rect(surface, button_color, skip_button_rect, border_radius=6)
    label = font.render("Skip", True, settings.COLOR_TEXT)
    surface.blit(label, label.get_rect(center=skip_button_rect.center))


def draw_range_preview(surface, tower_cls, pixel_pos):
    pygame.draw.circle(
        surface, settings.COLOR_RANGE_PREVIEW,
        (int(pixel_pos[0]), int(pixel_pos[1])), tower_cls.range, width=1,
    )


def draw_tower_range_preview(surface, tower):
    """Range ring(s) around a placed `tower`, shown while hovering it: its
    current range (thin white, same style as the placement preview) and,
    if it can still be upgraded, what its range would grow to after one
    more upgrade (thicker gold) -- so the size increase is visible before
    you commit. Just the one ring once the tower is maxed, since there's
    nothing left to preview."""
    center = (int(tower.pos.x), int(tower.pos.y))
    pygame.draw.circle(surface, settings.COLOR_RANGE_PREVIEW, center, int(tower.range), width=1)
    if not tower.is_max_level:
        pygame.draw.circle(surface, settings.COLOR_GOLD, center, int(tower.range_after_next_upgrade()), width=2)


def draw_tower_stats_panel(surface, font, small_font, subject):
    """The sidebar to the right of the play area. `subject` is either:
      - a Tower *class* (the build menu's currently selected type -- shows
        its base, level-1 stats), or
      - a Tower *instance* (a placed tower currently hovered for upgrade --
        shows its live stats, with a '-> value' preview of what upgrading
        would change), or
      - None (nothing selected/hovered -- shows a hint instead).
    Reads EXTRA_STATS off the tower class so a new tower type's special
    stats (splash, slow, knockback, ...) show up here with no changes to
    this function."""
    panel_rect = pygame.Rect(settings.PLAY_WIDTH, 0, settings.PANEL_WIDTH, settings.SCREEN_HEIGHT)
    pygame.draw.rect(surface, settings.COLOR_HUD_BG, panel_rect)
    pygame.draw.line(surface, settings.COLOR_BUTTON, (panel_rect.left, 0), (panel_rect.left, panel_rect.height), width=2)

    x = panel_rect.x + PANEL_PADDING
    y = PANEL_PADDING

    if subject is None:
        for line in ("Select a tower to build,", "or hover a placed tower's", "'+' badge, to see its stats."):
            hint = small_font.render(line, True, settings.COLOR_TEXT_DIM)
            surface.blit(hint, (x, y))
            y += PANEL_ROW_HEIGHT
        return

    is_placed = not inspect.isclass(subject)
    tower_cls = type(subject) if is_placed else subject

    title = font.render(tower_cls.display_name, True, settings.COLOR_TEXT)
    surface.blit(title, (x, y))
    y += 34

    if is_placed:
        level_text = small_font.render(f"Level {subject.level}/{tower_cls.MAX_LEVEL}", True, settings.COLOR_TEXT_DIM)
        surface.blit(level_text, (x, y))
        y += PANEL_ROW_HEIGHT
        if not subject.is_max_level:
            cost_text = small_font.render(f"Upgrade cost: {subject.upgrade_cost()}", True, settings.COLOR_GOLD)
            surface.blit(cost_text, (x, y))
            y += PANEL_ROW_HEIGHT
    else:
        cost_text = small_font.render(f"Cost: {tower_cls.cost}", True, settings.COLOR_GOLD)
        surface.blit(cost_text, (x, y))
        y += PANEL_ROW_HEIGHT
    y += 6  # small gap before the stat rows

    show_upgrade_preview = is_placed and not subject.is_max_level

    def stat_row(label, current, previewed=None, suffix=""):
        nonlocal y
        if previewed is not None and round(previewed, 2) != round(current, 2):
            value_str = f"{current:.1f}{suffix} -> {previewed:.1f}{suffix}"
        else:
            value_str = f"{current:.1f}{suffix}"
        row = small_font.render(f"{label}: {value_str}", True, settings.COLOR_TEXT)
        surface.blit(row, (x, y))
        y += PANEL_ROW_HEIGHT

    stat_row("Damage", subject.damage if is_placed else tower_cls.damage,
              subject.damage_after_next_upgrade() if show_upgrade_preview else None)
    stat_row("Range", subject.range if is_placed else tower_cls.range,
              subject.range_after_next_upgrade() if show_upgrade_preview else None)
    stat_row("Fire rate", subject.fire_rate if is_placed else tower_cls.fire_rate, suffix="/s")

    for label, attr_name, format_fn in tower_cls.EXTRA_STATS:
        value = getattr(subject if is_placed else tower_cls, attr_name)
        row = small_font.render(f"{label}: {format_fn(value)}", True, settings.COLOR_TEXT)
        surface.blit(row, (x, y))
        y += PANEL_ROW_HEIGHT


def _draw_centered_overlay(surface, font, small_font, title, subtitle, title_color, width=None):
    if width is None:
        width = settings.SCREEN_WIDTH
    overlay = pygame.Surface((width, settings.SCREEN_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 170))
    surface.blit(overlay, (0, 0))

    title_text = font.render(title, True, title_color)
    title_rect = title_text.get_rect(center=(width // 2, settings.SCREEN_HEIGHT // 2 - 20))
    surface.blit(title_text, title_rect)

    if subtitle:
        subtitle_text = small_font.render(subtitle, True, settings.COLOR_TEXT_DIM)
        subtitle_rect = subtitle_text.get_rect(center=(width // 2, settings.SCREEN_HEIGHT // 2 + 20))
        surface.blit(subtitle_text, subtitle_rect)


def draw_menu_screen(surface, font, small_font):
    surface.fill(settings.COLOR_BG)
    _draw_centered_overlay(surface, font, small_font, "Tower Defense", "Press any key to start", settings.COLOR_TEXT)


def draw_pause_overlay(surface, font, small_font):
    # Only darkens/centers over the play area (grid + HUD) -- the stats
    # panel stays visible and undimmed to its right.
    _draw_centered_overlay(surface, font, small_font, "Paused", "Press P to resume",
                            settings.COLOR_TEXT, width=settings.PLAY_WIDTH)


def draw_game_over_screen(surface, font, small_font):
    _draw_centered_overlay(surface, font, small_font, "Game Over", "Press R to restart",
                            settings.COLOR_LIVES, width=settings.PLAY_WIDTH)


def draw_victory_screen(surface, font, small_font):
    _draw_centered_overlay(surface, font, small_font, "Victory!", "Press R to play again",
                            settings.COLOR_GOLD, width=settings.PLAY_WIDTH)
