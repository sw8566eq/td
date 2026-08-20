"""HUD, build menu, and full-screen overlay rendering.

Button hit-testing (get_clicked_tower_button) is kept as pure Rect geometry,
separate from drawing, so it's unit-testable without a display. The build
menu iterates TOWER_TYPES, so a new tower registered there appears in the
UI automatically.
"""

import inspect
import math
import os

import pygame

import settings
from enemy import ENEMY_TYPES
from tower import TOWER_TYPES
from waves import WaveState

ENEMY_ORDER = list(ENEMY_TYPES.keys())  # stable UI order = registry insertion order

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

    if subject is None:
        _draw_panel_hint(surface, small_font, x)
        return

    is_placed = not inspect.isclass(subject)
    tower_cls = type(subject) if is_placed else subject

    y = _draw_panel_header(surface, font, small_font, x, subject, is_placed, tower_cls, hovered_specialize_key)
    _draw_panel_stats(surface, small_font, x, y, subject, tower_cls, is_placed)

    if is_placed:
        _draw_panel_action_buttons(surface, small_font, subject, economy,
                                    upgrade_button_rect, specialize_button_rects, sell_button_rect)


def _draw_panel_hint(surface, small_font, x):
    y = PANEL_PADDING
    for line in ("Select a tower to build,", "or click a placed tower to", "see its stats, upgrade, or sell it."):
        hint = small_font.render(line, True, settings.COLOR_TEXT_DIM)
        surface.blit(hint, (x, y))
        y += PANEL_ROW_HEIGHT


def _draw_panel_header(surface, font, small_font, x, subject, is_placed, tower_cls, hovered_specialize_key):
    """Title, then either a placed tower's level/specialization line (plus
    a "choose a specialization" hint and the hovered option's description
    while eligible to) or a build-menu class's base cost. Returns the y
    position the stat rows should start at."""
    y = PANEL_PADDING
    title = font.render(tower_cls.display_name, True, settings.COLOR_TEXT)
    surface.blit(title, (x, y))
    y += 34

    if not is_placed:
        cost_text = small_font.render(f"Cost: {tower_cls.cost}", True, settings.COLOR_GOLD)
        surface.blit(cost_text, (x, y))
        return y + PANEL_ROW_HEIGHT + 6  # small gap before the stat rows

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
        # Reserved whether or not anything's hovered, so the stat rows
        # below don't jump up and down as the mouse moves.
        if hovered_specialize_key is not None:
            desc = tower_cls.SPECIALIZATIONS[hovered_specialize_key]["description"]
            desc_text = small_font.render(desc, True, settings.COLOR_TEXT)
            surface.blit(desc_text, (x, y))
        y += PANEL_ROW_HEIGHT

    return y + 6  # small gap before the stat rows


def _draw_panel_stats(surface, small_font, x, y, subject, tower_cls, is_placed):
    """Damage/Range/Fire rate (with a '-> value' preview of what the next
    upgrade would change while not yet maxed) plus the tower's own
    EXTRA_STATS."""
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


def _draw_panel_action_buttons(surface, small_font, subject, economy,
                                upgrade_button_rect, specialize_button_rects, sell_button_rect):
    """Upgrade (below MAX_LEVEL) or two Specialize choices (at MAX_LEVEL,
    unspecialized) -- never both, see ACTION_AREA_TOP -- plus Sell,
    always. `subject` is assumed to be a placed Tower instance."""
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
    _draw_centered_overlay(surface, font, small_font, "Tower Defense",
                            ["Press any key to start", "E -- Map Editor"], settings.COLOR_TEXT)


def draw_pause_menu(surface, font, small_font, is_custom_level=False):
    # Only darkens/centers over the play area (grid + HUD) -- the stats
    # panel stays visible and undimmed to its right. "Return to Editor"
    # only makes sense while playing a level that actually came from the
    # editor -- a built-in level has no corresponding in-progress paint
    # buffer to go back to.
    options = ["Esc / P -- Resume", "R -- Restart Level"]
    if is_custom_level:
        options.append("E -- Return to Map Editor")
    options.append("Q -- Quit")
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


# --- Map editor ---
#
# Reuses the exact same screen geometry as normal play (BUTTON_Y's toolbar
# row under the grid, ACTION_AREA_TOP's stacked slot in the sidebar) so no
# new layout constants are needed -- the editor and a playing Game just
# put different buttons in the same two established places.

EDITOR_TOOL_LABELS = {
    "paint": "Paint",
    "erase": "Erase",
    "spawn": "Spawn",
    "goal": "Goal",
}
EDITOR_TOOL_ORDER = list(EDITOR_TOOL_LABELS.keys())

EDITOR_ACTION_LABELS = {
    "load": "Load Map...",
    "waves": "Edit Waves ->",
    "back": "Back to Menu",
}
EDITOR_ACTION_ORDER = list(EDITOR_ACTION_LABELS.keys())


def build_editor_tool_rects():
    """Rects for each editor tool's button, in the same toolbar row the
    build menu's tower buttons occupy during normal play."""
    rects = {}
    x = BUTTON_MARGIN
    for name in EDITOR_TOOL_ORDER:
        rects[name] = pygame.Rect(x, BUTTON_Y, BUTTON_SIZE, BUTTON_SIZE)
        x += BUTTON_SIZE + BUTTON_MARGIN
    return rects


def get_clicked_editor_tool(pos, tool_rects):
    """Return the editor tool name whose button contains pos, or None."""
    for name, rect in tool_rects.items():
        if rect.collidepoint(pos):
            return name
    return None


def build_editor_action_rects():
    """Rects for Playtest/Save/Back, stacked in the same fixed sidebar
    slot the tower stats panel's action buttons use."""
    rects = {}
    top = ACTION_AREA_TOP
    for name in EDITOR_ACTION_ORDER:
        rects[name] = _action_button_rect(top)
        top += ACTION_BUTTON_HEIGHT + ACTION_BUTTON_GAP
    return rects


def get_clicked_editor_action(pos, action_rects):
    """Return the editor action name whose button contains pos, or None."""
    for name, rect in action_rects.items():
        if rect.collidepoint(pos):
            return name
    return None


def draw_editor_screen(surface, assets, font, small_font, editor, tool_rects, action_rects):
    surface.fill(settings.COLOR_BG)
    _draw_editor_grid(surface, assets, small_font, editor)
    _draw_editor_toolbar(surface, small_font, editor, tool_rects)
    _draw_editor_path_sidebar(surface, font, small_font, editor, action_rects)


def _cell_center(editor, cell):
    col, row = cell
    return (
        col * editor.tile_size + editor.tile_size // 2,
        row * editor.tile_size + editor.tile_size // 2,
    )


def _draw_editor_grid(surface, assets, small_font, editor, active_spawn=None):
    """The path/spawn/goal/junction preview shared by both editor screens.
    Spawns are numbered (stable sort order by cell) so a multi-spawn
    level's spawns have a consistent, referenceable identity across both
    screens; `active_spawn`, when given (only the wave editor has one),
    gets a highlight ring -- see Game._handle_wave_editor_click, which is
    what clicking a spawn marker there actually changes."""
    for row in range(editor.rows):
        for col in range(editor.cols):
            cell = (col, row)
            name = "tile_path" if cell in editor.path_cells else "tile_grass"
            sprite = assets.get(name, (editor.tile_size, editor.tile_size))
            surface.blit(sprite, (col * editor.tile_size, row * editor.tile_size))

    for cell in editor.junctions:
        _draw_editor_marker(surface, editor, cell, settings.COLOR_EDITOR_JUNCTION, radius_fraction=0.18)

    for number, cell in enumerate(sorted(editor.spawn_cells), start=1):
        _draw_editor_marker(surface, editor, cell, settings.COLOR_EDITOR_SPAWN, radius_fraction=0.32)
        if cell == active_spawn:
            _draw_active_spawn_ring(surface, editor, cell)
        label = small_font.render(str(number), True, settings.COLOR_TEXT)
        surface.blit(label, label.get_rect(center=_cell_center(editor, cell)))

    for cell in editor.goal_cells:
        _draw_editor_marker(surface, editor, cell, settings.COLOR_EDITOR_GOAL, radius_fraction=0.32)


def _draw_editor_marker(surface, editor, cell, color, radius_fraction):
    pygame.draw.circle(surface, color, _cell_center(editor, cell), int(editor.tile_size * radius_fraction))


def _draw_active_spawn_ring(surface, editor, cell):
    radius = int(editor.tile_size * 0.42)
    pygame.draw.circle(surface, settings.COLOR_TEXT, _cell_center(editor, cell), radius, width=3)


def _draw_editor_toolbar(surface, small_font, editor, tool_rects):
    hud_rect = pygame.Rect(0, settings.SCREEN_HEIGHT - settings.HUD_HEIGHT,
                            settings.PLAY_WIDTH, settings.HUD_HEIGHT)
    pygame.draw.rect(surface, settings.COLOR_HUD_BG, hud_rect)

    for name, rect in tool_rects.items():
        color = settings.COLOR_BUTTON_SELECTED if name == editor.active_tool else settings.COLOR_BUTTON
        pygame.draw.rect(surface, color, rect, border_radius=6)
        label = small_font.render(EDITOR_TOOL_LABELS[name], True, settings.COLOR_TEXT)
        surface.blit(label, label.get_rect(center=rect.center))


def _draw_editor_path_sidebar(surface, font, small_font, editor, action_rects):
    panel_rect = pygame.Rect(settings.PLAY_WIDTH, 0, settings.PANEL_WIDTH, settings.SCREEN_HEIGHT)
    pygame.draw.rect(surface, settings.COLOR_HUD_BG, panel_rect)
    pygame.draw.line(surface, settings.COLOR_BUTTON, (panel_rect.left, 0), (panel_rect.left, panel_rect.height), width=2)
    x = panel_rect.x + PANEL_PADDING

    title = font.render("Map Editor", True, settings.COLOR_TEXT)
    surface.blit(title, (x, PANEL_PADDING))

    # Gates "Edit Waves" below, so the status shown here is path validity
    # alone -- wave_problems are irrelevant until the player gets there
    # (a fresh editor's one empty wave would otherwise show as an error
    # here before the player has had any chance to touch it).
    path_ok = editor.path_is_valid()
    status_color = settings.COLOR_GOLD if path_ok else settings.COLOR_LIVES
    status_lines = ["Path ready -- edit waves next!"] if path_ok else editor.path_problems
    y = PANEL_PADDING + 40
    for line in status_lines[:6]:  # panel has finite room; the rest are still in path_problems
        for wrapped in _wrap_text(line, small_font, settings.PANEL_WIDTH - 2 * PANEL_PADDING):
            text = small_font.render(wrapped, True, status_color)
            surface.blit(text, (x, y))
            y += PANEL_ROW_HEIGHT

    for name, rect in action_rects.items():
        # "load"/"back" always work; moving on to wave editing needs a valid path first.
        enabled = path_ok if name == "waves" else True
        color = settings.COLOR_BUTTON if enabled else settings.COLOR_BUTTON_DISABLED
        pygame.draw.rect(surface, color, rect, border_radius=6)
        label = small_font.render(EDITOR_ACTION_LABELS[name], True, settings.COLOR_TEXT)
        surface.blit(label, label.get_rect(center=rect.center))


# --- Wave editor ---
#
# A second screen reached from the map editor once its path is valid (see
# EDITOR_ACTION_LABELS["waves"]) -- same PLAY_WIDTH/PANEL_WIDTH geometry,
# just with wave-selector tabs in the toolbar row instead of path tools,
# and per-species +/- rows plus Playtest/Save/Back-to-Path in the sidebar
# instead of the path tools' status text and Edit-Waves/Back-to-Menu.

WAVE_TAB_SIZE = 48
WAVE_TAB_MARGIN = 8
WAVE_TAB_Y = settings.SCREEN_HEIGHT - settings.HUD_HEIGHT + (settings.HUD_HEIGHT - WAVE_TAB_SIZE) // 2

WAVE_UNIT_ROWS_TOP = 100
WAVE_UNIT_ROW_HEIGHT = 32
WAVE_UNIT_STEP_BUTTON_SIZE = 24

WAVE_EDITOR_ACTION_LABELS = {
    "playtest": "Playtest",
    "save": "Save",
    "back": "Back to Path",
}
WAVE_EDITOR_ACTION_ORDER = list(WAVE_EDITOR_ACTION_LABELS.keys())


def build_wave_tab_rects(wave_count):
    """One rect per wave (0-based index keys), left to right, plus two
    more entries keyed "add"/"remove" following them in the same flowing
    row -- same layout approach as build_button_rects()."""
    rects = {}
    x = BUTTON_MARGIN
    for index in range(wave_count):
        rects[index] = pygame.Rect(x, WAVE_TAB_Y, WAVE_TAB_SIZE, WAVE_TAB_SIZE)
        x += WAVE_TAB_SIZE + WAVE_TAB_MARGIN
    x += WAVE_TAB_MARGIN  # a little extra breathing room before add/remove
    for key in ("add", "remove"):
        rects[key] = pygame.Rect(x, WAVE_TAB_Y, WAVE_TAB_SIZE, WAVE_TAB_SIZE)
        x += WAVE_TAB_SIZE + WAVE_TAB_MARGIN
    return rects


def get_clicked_wave_tab(pos, tab_rects):
    """Return the clicked entry's key -- an int wave index, or "add"/
    "remove" -- or None."""
    for key, rect in tab_rects.items():
        if rect.collidepoint(pos):
            return key
    return None


def build_wave_unit_rects():
    """Two small +/- rects per registered enemy type (ENEMY_ORDER),
    stacked in the wave editor's sidebar, keyed (enemy_name, "minus"/"plus")."""
    rects = {}
    minus_x = settings.PLAY_WIDTH + settings.PANEL_WIDTH - 2 * PANEL_PADDING - 2 * WAVE_UNIT_STEP_BUTTON_SIZE - 6
    plus_x = minus_x + WAVE_UNIT_STEP_BUTTON_SIZE + 6
    y = WAVE_UNIT_ROWS_TOP
    for name in ENEMY_ORDER:
        rects[(name, "minus")] = pygame.Rect(minus_x, y, WAVE_UNIT_STEP_BUTTON_SIZE, WAVE_UNIT_STEP_BUTTON_SIZE)
        rects[(name, "plus")] = pygame.Rect(plus_x, y, WAVE_UNIT_STEP_BUTTON_SIZE, WAVE_UNIT_STEP_BUTTON_SIZE)
        y += WAVE_UNIT_ROW_HEIGHT
    return rects


def get_clicked_wave_unit_button(pos, unit_rects):
    """Return the (enemy_name, "minus"|"plus") key whose button contains
    pos, or None."""
    for key, rect in unit_rects.items():
        if rect.collidepoint(pos):
            return key
    return None


def build_wave_editor_action_rects():
    """Rects for Playtest/Save/Back to Path, stacked in the same fixed
    sidebar slot the path editor's own action buttons use."""
    rects = {}
    top = ACTION_AREA_TOP
    for name in WAVE_EDITOR_ACTION_ORDER:
        rects[name] = _action_button_rect(top)
        top += ACTION_BUTTON_HEIGHT + ACTION_BUTTON_GAP
    return rects


def get_clicked_wave_editor_action(pos, action_rects):
    """Return the wave editor action name whose button contains pos, or None."""
    for name, rect in action_rects.items():
        if rect.collidepoint(pos):
            return name
    return None


def draw_wave_editor_screen(surface, assets, font, small_font, editor, tab_rects, unit_rects,
                             action_rects, last_saved_path=None):
    surface.fill(settings.COLOR_BG)
    # Read-only path preview, for context -- clicking a spawn marker in it
    # is exactly what changes which spawn's counts the sidebar below
    # shows/edits (see Game._handle_wave_editor_click).
    _draw_editor_grid(surface, assets, small_font, editor, active_spawn=editor.active_spawn_cell)
    _draw_wave_tabs(surface, small_font, editor, tab_rects)
    _draw_wave_editor_sidebar(surface, font, small_font, editor, unit_rects, action_rects, last_saved_path)


def _draw_wave_tabs(surface, small_font, editor, tab_rects):
    hud_rect = pygame.Rect(0, settings.SCREEN_HEIGHT - settings.HUD_HEIGHT,
                            settings.PLAY_WIDTH, settings.HUD_HEIGHT)
    pygame.draw.rect(surface, settings.COLOR_HUD_BG, hud_rect)

    for index, _wave in enumerate(editor.wave_specs):
        rect = tab_rects[index]
        color = settings.COLOR_BUTTON_SELECTED if index == editor.active_wave_index else settings.COLOR_BUTTON
        pygame.draw.rect(surface, color, rect, border_radius=6)
        label = small_font.render(str(index + 1), True, settings.COLOR_TEXT)
        surface.blit(label, label.get_rect(center=rect.center))

    for key, symbol in (("add", "+"), ("remove", "-")):
        rect = tab_rects[key]
        pygame.draw.rect(surface, settings.COLOR_BUTTON, rect, border_radius=6)
        label = small_font.render(symbol, True, settings.COLOR_TEXT)
        surface.blit(label, label.get_rect(center=rect.center))


def _draw_wave_editor_sidebar(surface, font, small_font, editor, unit_rects, action_rects, last_saved_path=None):
    panel_rect = pygame.Rect(settings.PLAY_WIDTH, 0, settings.PANEL_WIDTH, settings.SCREEN_HEIGHT)
    pygame.draw.rect(surface, settings.COLOR_HUD_BG, panel_rect)
    pygame.draw.line(surface, settings.COLOR_BUTTON, (panel_rect.left, 0), (panel_rect.left, panel_rect.height), width=2)
    x = panel_rect.x + PANEL_PADDING

    title = font.render("Wave Editor", True, settings.COLOR_TEXT)
    surface.blit(title, (x, PANEL_PADDING))

    wave_label = small_font.render(
        f"Wave {editor.active_wave_index + 1} of {len(editor.wave_specs)}", True, settings.COLOR_TEXT_DIM,
    )
    surface.blit(wave_label, (x, PANEL_PADDING + 36))

    # Short by design -- guaranteed to fit the sidebar on one line without
    # needing _wrap_text -- since the map preview's highlight ring (see
    # _draw_active_spawn_ring) plus the numbered markers are what actually
    # tell a multi-spawn level's spawns apart; this is just confirmation.
    spawn_order = sorted(editor.spawn_cells)
    if editor.active_spawn_cell in spawn_order:
        spawn_number = spawn_order.index(editor.active_spawn_cell) + 1
        spawn_text = f"Spawn {spawn_number} of {len(spawn_order)}"
    else:
        spawn_text = "No spawn"
    spawn_label = small_font.render(spawn_text, True, settings.COLOR_TEXT_DIM)
    surface.blit(spawn_label, (x, PANEL_PADDING + 58))

    composition = editor.wave_specs[editor.active_wave_index].get(editor.active_spawn_cell, {})
    y = WAVE_UNIT_ROWS_TOP
    for name in ENEMY_ORDER:
        count = composition.get(name, 0)
        label = small_font.render(f"{name.capitalize()}: {count}", True, settings.COLOR_TEXT)
        surface.blit(label, (x, y + 4))
        for suffix, symbol in (("minus", "-"), ("plus", "+")):
            rect = unit_rects[(name, suffix)]
            pygame.draw.rect(surface, settings.COLOR_BUTTON, rect, border_radius=4)
            sym_text = small_font.render(symbol, True, settings.COLOR_TEXT)
            surface.blit(sym_text, sym_text.get_rect(center=rect.center))
        y += WAVE_UNIT_ROW_HEIGHT

    for name, rect in action_rects.items():
        # "back" always works; Playtest/Save need every wave to have units.
        enabled = editor.can_play() if name in ("playtest", "save") else True
        color = settings.COLOR_BUTTON if enabled else settings.COLOR_BUTTON_DISABLED
        pygame.draw.rect(surface, color, rect, border_radius=6)
        label = small_font.render(WAVE_EDITOR_ACTION_LABELS[name], True, settings.COLOR_TEXT)
        surface.blit(label, label.get_rect(center=rect.center))

    if last_saved_path is not None:
        # Tells the player where to actually find the file -- e.g. to
        # copy it somewhere and hand it to another player, since a saved
        # level is just a self-contained JSON file (see persistence.py).
        # Game never saves anywhere but persistence.LEVELS_DIR, so
        # hardcoding that directory name for display is accurate for any
        # path this ever actually gets -- last_saved_path only carries
        # the filename's worth of new information.
        saved_y = max(rect.bottom for rect in action_rects.values()) + 16
        saved_label = small_font.render("Saved to:", True, settings.COLOR_TEXT_DIM)
        surface.blit(saved_label, (x, saved_y))
        display_path = f"custom_levels/{os.path.basename(last_saved_path)}"
        for line_index, line in enumerate(_wrap_text(display_path, small_font, settings.PANEL_WIDTH - 2 * PANEL_PADDING)):
            text = small_font.render(line, True, settings.COLOR_GOLD)
            surface.blit(text, (x, saved_y + PANEL_ROW_HEIGHT * (line_index + 1)))


LEVEL_SELECT_ROW_HEIGHT = 88
LEVEL_SELECT_ROW_GAP = 12
LEVEL_SELECT_TOP = 100
# Leaves room below the last row for the "Esc -- Back to ..." hint --
# the scrollable viewport is everything between this and LEVEL_SELECT_TOP.
LEVEL_SELECT_BOTTOM = settings.SCREEN_HEIGHT - 60
LEVEL_SELECT_ROW_PADDING = 10
LEVEL_SELECT_SCROLL_STEP = LEVEL_SELECT_ROW_HEIGHT + LEVEL_SELECT_ROW_GAP  # one row per wheel click

# 15:9 -- exactly GRID_COLS:GRID_ROWS -- so the thumbnail's cells are
# square, same as the real grid's, just tiny.
LEVEL_THUMBNAIL_WIDTH = 120
LEVEL_THUMBNAIL_HEIGHT = 72


def level_select_content_height(entry_count):
    """Total stacked height of `entry_count` rows, gaps included (but not
    a trailing gap after the last one)."""
    if entry_count == 0:
        return 0
    return entry_count * (LEVEL_SELECT_ROW_HEIGHT + LEVEL_SELECT_ROW_GAP) - LEVEL_SELECT_ROW_GAP


def level_select_max_scroll(entry_count):
    """How far the list can scroll before the last row reaches the bottom
    of the viewport -- 0 once everything already fits without scrolling."""
    overflow = level_select_content_height(entry_count) - (LEVEL_SELECT_BOTTOM - LEVEL_SELECT_TOP)
    return max(0, overflow)


def build_level_select_rects(entries, scroll_offset=0):
    """One rect per (key, level) entry in `entries`, stacked top to
    bottom and shifted up by `scroll_offset` pixels, keyed by `key` -- an
    int for a built-in LEVELS id or a str slug for a saved custom level's
    id (see persistence.py). A row scrolled above LEVEL_SELECT_TOP or
    below LEVEL_SELECT_BOTTOM still gets a real (if useless) Rect here --
    callers doing hit-testing against a scrolled list should fence `pos`
    to that viewport themselves first; see Game._handle_level_select_click."""
    rects = {}
    y = LEVEL_SELECT_TOP - scroll_offset
    for key, _level in entries:
        rects[key] = pygame.Rect(60, y, settings.PLAY_WIDTH - 120, LEVEL_SELECT_ROW_HEIGHT)
        y += LEVEL_SELECT_ROW_HEIGHT + LEVEL_SELECT_ROW_GAP
    return rects


def get_clicked_level_select_entry(pos, rects):
    """Return the entry key whose row contains pos, or None."""
    for key, rect in rects.items():
        if rect.collidepoint(pos):
            return key
    return None


def build_level_thumbnail(level, width=LEVEL_THUMBNAIL_WIDTH, height=LEVEL_THUMBNAIL_HEIGHT):
    """A small static rendering of `level`'s path -- a ground fill, path
    cells highlighted, spawn (green)/goal (gold) dots -- scaled to fit a
    (width, height) surface, so the level browser shows what a map
    actually looks like rather than just its name. Plain Rect/circle
    drawing rather than real sprites, same placeholder spirit as
    AssetManager's own fallback shapes and appropriate at this scale
    regardless of whether an art pack is installed."""
    surface = pygame.Surface((width, height))
    surface.fill(settings.COLOR_THUMBNAIL_GROUND)
    cell_w = width / settings.GRID_COLS
    cell_h = height / settings.GRID_ROWS

    for col, row in level.path_cells:
        cell_rect = pygame.Rect(round(col * cell_w), round(row * cell_h), math.ceil(cell_w), math.ceil(cell_h))
        surface.fill(settings.COLOR_THUMBNAIL_PATH, cell_rect)

    dot_radius = max(2, int(min(cell_w, cell_h) * 0.6))
    for cells, color in (
        (level.spawn_cells, settings.COLOR_EDITOR_SPAWN),
        (level.goal_cells, settings.COLOR_EDITOR_GOAL),
    ):
        for col, row in cells:
            center = (round((col + 0.5) * cell_w), round((row + 0.5) * cell_h))
            pygame.draw.circle(surface, color, center, dot_radius)

    return surface


def draw_level_select_screen(surface, font, small_font, entries, rects, thumbnails,
                              purpose="play", scroll_offset=0):
    """`purpose` is "play" (the menu's `L` -- built-ins and custom levels
    both listed, picking one starts playing it) or "edit" (the map
    editor's "Load Map..." -- only custom levels listed, since a built-in
    one has no corresponding file to reopen for editing; picking one
    loads it into the editor instead -- see Game._handle_level_select_click).

    More rows than fit the viewport (LEVEL_SELECT_TOP..LEVEL_SELECT_BOTTOM)
    scroll with the mouse wheel (see Game._scroll_level_select) rather
    than running off-screen unreachably -- rects/scroll_offset are
    expected to already agree (both built from the same scroll position;
    see Game._level_select_rects), this just clips the drawing and shows
    a hint when there's more list than fits either direction."""
    surface.fill(settings.COLOR_BG)
    title_text = "Load a Map to Edit" if purpose == "edit" else "Select a Level"
    title = font.render(title_text, True, settings.COLOR_TEXT)
    surface.blit(title, title.get_rect(midtop=(settings.SCREEN_WIDTH // 2, 30)))

    if not entries:
        empty_text = "No custom levels saved yet." if purpose == "edit" else "No levels available."
        hint = small_font.render(empty_text, True, settings.COLOR_TEXT_DIM)
        surface.blit(hint, hint.get_rect(center=(settings.SCREEN_WIDTH // 2, LEVEL_SELECT_TOP + 20)))

    viewport = pygame.Rect(0, LEVEL_SELECT_TOP, settings.SCREEN_WIDTH, LEVEL_SELECT_BOTTOM - LEVEL_SELECT_TOP)
    previous_clip = surface.get_clip()
    surface.set_clip(viewport)

    for key, level in entries:
        rect = rects[key]
        if not rect.colliderect(viewport):
            continue  # scrolled fully out of view -- nothing to draw
        pygame.draw.rect(surface, settings.COLOR_BUTTON, rect, border_radius=6)

        thumbnail = thumbnails.get(key)
        text_x = rect.left + LEVEL_SELECT_ROW_PADDING
        if thumbnail is not None:
            thumb_rect = thumbnail.get_rect(midleft=(text_x, rect.centery))
            surface.blit(thumbnail, thumb_rect)
            pygame.draw.rect(surface, settings.COLOR_BG, thumb_rect, width=1)
            text_x = thumb_rect.right + LEVEL_SELECT_ROW_PADDING

        # A custom level's id is a str slug (see persistence.py); a
        # built-in one's is the int key it's registered under in LEVELS.
        # purpose == "edit" never lists a built-in at all (see
        # Game._enter_level_select), so the "(custom)" tag would just be
        # redundant noise there -- every row already is one.
        if purpose == "edit" or isinstance(key, int):
            label = level.name
        else:
            label = f"{level.name} (custom)"
        text = small_font.render(label, True, settings.COLOR_TEXT)
        surface.blit(text, text.get_rect(midleft=(text_x, rect.centery)))

    surface.set_clip(previous_clip)

    max_scroll = level_select_max_scroll(len(entries))
    if max_scroll > 0:
        if scroll_offset > 0:
            more_above = small_font.render("^ more above", True, settings.COLOR_TEXT_DIM)
            surface.blit(more_above, more_above.get_rect(midtop=(settings.SCREEN_WIDTH // 2, LEVEL_SELECT_TOP + 4)))
        if scroll_offset < max_scroll:
            more_below = small_font.render("v more below -- scroll for more", True, settings.COLOR_TEXT_DIM)
            surface.blit(more_below, more_below.get_rect(midbottom=(settings.SCREEN_WIDTH // 2, LEVEL_SELECT_BOTTOM - 4)))

    back_text = "Esc -- Back to Editor" if purpose == "edit" else "Esc -- Back to Menu"
    hint = small_font.render(back_text, True, settings.COLOR_TEXT_DIM)
    surface.blit(hint, (60, settings.SCREEN_HEIGHT - 40))


def _wrap_text(text, font, max_width):
    """Greedy word-wrap of `text` to fit within max_width pixels for
    `font` -- validation messages are free-form and can run long."""
    words = text.split(" ")
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.size(candidate)[0] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines
