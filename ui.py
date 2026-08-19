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

# Upgrade/Specialize and Sell sit stacked in a fixed spot in the stats
# panel, comfortably below the tallest stats block any tower type
# currently renders (title + level row + 3 base stats + up to 2
# EXTRA_STATS rows), so none of them have to be laid out relative to
# content that varies by tower/selection. A tower is either upgradeable
# (below MAX_LEVEL -- one Upgrade button) or specializable (at MAX_LEVEL,
# unspecialized -- two stacked Specialize choices) or neither of those,
# never more than one of the two, so they share the same top slot.
# Sell's position is fixed at the bottom of that slot regardless of which
# (if either) of those is currently showing above it.
ACTION_BUTTON_WIDTH = 200
ACTION_BUTTON_HEIGHT = 36
ACTION_BUTTON_GAP = 10
ACTION_AREA_TOP = 260
SELL_BUTTON_TOP = ACTION_AREA_TOP + 2 * (ACTION_BUTTON_HEIGHT + ACTION_BUTTON_GAP)


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


def _action_button_rect(top):
    x = settings.PLAY_WIDTH + (settings.PANEL_WIDTH - ACTION_BUTTON_WIDTH) // 2
    return pygame.Rect(x, top, ACTION_BUTTON_WIDTH, ACTION_BUTTON_HEIGHT)


def build_upgrade_button_rect():
    """Rect for the stats panel's 'Upgrade' button -- fixed position
    within the panel (see ACTION_AREA_TOP), horizontally centered, so
    it stays put regardless of which tower's stats are shown above it.
    Only meaningful (and only drawn/clickable) while the panel's subject
    is a placed, not-yet-maxed tower -- see draw_tower_stats_panel and
    Game._handle_click."""
    return _action_button_rect(ACTION_AREA_TOP)


def build_specialize_button_rects():
    """Two rects for the two specialization choices offered once a placed
    tower hits MAX_LEVEL, stacked in the same action-button slot Upgrade
    normally occupies -- mutually exclusive with it, since a tower is
    never both upgradeable and specializable at once. Only meaningful
    (and only drawn/clickable) while the panel's subject is a placed
    tower eligible to specialize -- see draw_tower_stats_panel and
    Game._handle_click."""
    top_a = ACTION_AREA_TOP
    top_b = ACTION_AREA_TOP + ACTION_BUTTON_HEIGHT + ACTION_BUTTON_GAP
    return _action_button_rect(top_a), _action_button_rect(top_b)


def build_sell_button_rect():
    """Rect for the stats panel's 'Sell' button -- fixed position within
    the panel (see SELL_BUTTON_TOP), horizontally centered, so it stays
    put regardless of which tower's stats are currently shown above it.
    Only meaningful (and only drawn/clickable) while the panel's subject
    is a placed tower -- see draw_tower_stats_panel and Game._handle_click."""
    return _action_button_rect(SELL_BUTTON_TOP)


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
    gold_display = "unlimited" if economy.unlimited_gold else str(economy.gold)
    gold_text = font.render(f"Gold: {gold_display}", True, settings.COLOR_GOLD)
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
        return  # nothing left to skip to/start

    # The same button doubles as "Start" before wave 1 (which waits for
    # the player rather than auto-starting on a timer -- see WaveManager)
    # and "Skip" for every between-waves countdown after that.
    if wave_manager.state == WaveState.AWAITING_START:
        countdown_text = font.render("Ready to start", True, settings.COLOR_TEXT)
        button_label, clickable = "Start", True
    elif wave_manager.state == WaveState.BETWEEN_WAVES:
        seconds_left = max(0, math.ceil(wave_manager.between_wave_timer))
        countdown_text = font.render(f"Next wave in {seconds_left}s", True, settings.COLOR_TEXT)
        button_label, clickable = "Skip", True
    else:
        countdown_text = font.render("Wave in progress", True, settings.COLOR_TEXT_DIM)
        button_label, clickable = "Skip", False
    countdown_rect = countdown_text.get_rect(midbottom=(skip_button_rect.centerx, skip_button_rect.top - 6))
    surface.blit(countdown_text, countdown_rect)

    button_color = settings.COLOR_BUTTON if clickable else settings.COLOR_BUTTON_DISABLED
    pygame.draw.rect(surface, button_color, skip_button_rect, border_radius=6)
    label = font.render(button_label, True, settings.COLOR_TEXT)
    surface.blit(label, label.get_rect(center=skip_button_rect.center))


def draw_footprint_preview(surface, grid, anchor_col, anchor_row, buildable):
    """Outline of the tile-sized footprint a tower would occupy if placed
    at subtile anchor (anchor_col, anchor_row) -- lets the player see the
    footprint move in fine (sub-tile) increments while hovering the grid,
    colored by whether it's currently buildable."""
    rect = pygame.Rect(
        anchor_col * grid.subtile_size, anchor_row * grid.subtile_size,
        grid.tile_size, grid.tile_size,
    )
    color = settings.COLOR_FOOTPRINT_VALID if buildable else settings.COLOR_FOOTPRINT_INVALID
    pygame.draw.rect(surface, color, rect, width=2)


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


def draw_tower_stats_panel(surface, font, small_font, subject, economy, upgrade_button_rect,
                            specialize_button_rects, sell_button_rect, hovered_specialize_key=None):
    """The sidebar to the right of the play area. `subject` is either:
      - a Tower *class* (the build menu's currently selected type -- shows
        its base, level-1 stats), or
      - a Tower *instance* (a placed tower, either hovered or clicked to
        stay pinned open -- shows its live stats, with a '-> value'
        preview of what upgrading would change; an Upgrade button below
        MAX_LEVEL, or two Specialize choices once at MAX_LEVEL and not
        yet specialized (hovering one shows its description via
        `hovered_specialize_key`); and a Sell button), or
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
        for line in ("Select a tower to build,", "or click a placed tower to", "see its stats, upgrade, or sell it."):
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
        level_line = f"Level {subject.level}/{tower_cls.MAX_LEVEL}"
        if subject.specialization is not None:
            spec_name = tower_cls.SPECIALIZATIONS[subject.specialization]["display_name"]
            level_line += f" -- {spec_name}"
        level_text = small_font.render(level_line, True, settings.COLOR_TEXT_DIM)
        surface.blit(level_text, (x, y))
        y += PANEL_ROW_HEIGHT
        if subject.can_specialize:
            hint = small_font.render("Choose a specialization:", True, settings.COLOR_TEXT_DIM)
            surface.blit(hint, (x, y))
            y += PANEL_ROW_HEIGHT
            # Reserved whether or not anything's hovered, so the stat
            # rows below don't jump up and down as the mouse moves.
            if hovered_specialize_key is not None:
                desc = tower_cls.SPECIALIZATIONS[hovered_specialize_key]["description"]
                desc_text = small_font.render(desc, True, settings.COLOR_TEXT)
                surface.blit(desc_text, (x, y))
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

    if not is_placed:
        return

    def action_button(rect, text, affordable):
        color = settings.COLOR_BUTTON if affordable else settings.COLOR_BUTTON_DISABLED
        pygame.draw.rect(surface, color, rect, border_radius=6)
        label = small_font.render(text, True, settings.COLOR_GOLD)
        surface.blit(label, label.get_rect(center=rect.center))

    if not subject.is_max_level:
        cost = subject.upgrade_cost()
        action_button(upgrade_button_rect, f"Upgrade ({cost}g)", economy.can_afford(cost))
    elif subject.can_specialize:
        cost = subject.specialization_cost()
        for rect, (key, spec) in zip(specialize_button_rects, subject.SPECIALIZATIONS.items()):
            action_button(rect, f"{spec['display_name']} ({cost}g)", economy.can_afford(cost))

    action_button(sell_button_rect, f"Sell (+{subject.sell_value()}g)", True)


def _draw_centered_overlay(surface, font, small_font, title, subtitle, title_color, width=None):
    """`subtitle` is a single string, or a list of strings each rendered
    on its own line below the title (used by the pause menu's option
    list) -- an empty string/list draws no subtitle at all."""
    if width is None:
        width = settings.SCREEN_WIDTH
    overlay = pygame.Surface((width, settings.SCREEN_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 170))
    surface.blit(overlay, (0, 0))

    title_text = font.render(title, True, title_color)
    title_rect = title_text.get_rect(center=(width // 2, settings.SCREEN_HEIGHT // 2 - 20))
    surface.blit(title_text, title_rect)

    lines = [subtitle] if isinstance(subtitle, str) else subtitle
    y = title_rect.bottom + 20
    for line in lines:
        if not line:
            continue
        line_text = small_font.render(line, True, settings.COLOR_TEXT_DIM)
        line_rect = line_text.get_rect(center=(width // 2, y))
        surface.blit(line_text, line_rect)
        y += line_text.get_height() + 6


def draw_menu_screen(surface, font, small_font):
    surface.fill(settings.COLOR_BG)
    _draw_centered_overlay(surface, font, small_font, "Tower Defense", "Press any key to start", settings.COLOR_TEXT)


def draw_pause_menu(surface, font, small_font):
    # Only darkens/centers over the play area (grid + HUD) -- the stats
    # panel stays visible and undimmed to its right.
    options = ["Esc / P -- Resume", "R -- Restart Level", "Q -- Quit"]
    _draw_centered_overlay(surface, font, small_font, "Paused", options,
                            settings.COLOR_TEXT, width=settings.PLAY_WIDTH)


def draw_game_over_screen(surface, font, small_font):
    _draw_centered_overlay(surface, font, small_font, "Game Over", "Press R to restart",
                            settings.COLOR_LIVES, width=settings.PLAY_WIDTH)


def draw_victory_screen(surface, font, small_font, has_next_level=False):
    if has_next_level:
        title, subtitle = "Level Complete!", "Press R for the next level"
    else:
        title, subtitle = "Victory!", "Press R to play again"
    _draw_centered_overlay(surface, font, small_font, title, subtitle,
                            settings.COLOR_GOLD, width=settings.PLAY_WIDTH)
