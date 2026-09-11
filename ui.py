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
from achievements import ACHIEVEMENT_ORDER, ACHIEVEMENTS
from difficulty import DIFFICULTY_MODES, DIFFICULTY_ORDER
from enemy import ENEMY_TYPES
from relics import RELICS
from shop import can_afford, price_for
from tower import TOWER_TYPES
from waves import WaveState

ENEMY_ORDER = list(ENEMY_TYPES.keys())  # stable UI order = registry insertion order

BUTTON_SIZE = 72
BUTTON_MARGIN = 12

# The HUD's top 32px is reserved for content that doesn't depend on how many
# tower buttons are registered -- the speed toggle (build_speed_button_rect)
# and the upcoming-wave preview text (_format_wave_preview) both draw here
# instead of squeezing into whatever horizontal gap happens to be left next
# to the tower buttons, which shrinks every time a new tower is added.
HUD_TOP_STRIP_HEIGHT = 32
HUD_BUTTON_ROW_HEIGHT = settings.HUD_HEIGHT - HUD_TOP_STRIP_HEIGHT
BUTTON_Y = (settings.SCREEN_HEIGHT - HUD_BUTTON_ROW_HEIGHT
            + (HUD_BUTTON_ROW_HEIGHT - BUTTON_SIZE) // 2)

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
# A placed tower's "Targeting: <Mode>" row (see build_targeting_button_rect)
# occupies the old ACTION_AREA_TOP slot; the Upgrade/Specialize/Sell block
# below it is pushed down by one more button-height-plus-gap to make room,
# same shared-geometry convention the editor/wave-editor action buttons
# below already reuse this constant for.
TARGETING_BUTTON_TOP = 260
ACTION_AREA_TOP = TARGETING_BUTTON_TOP + ACTION_BUTTON_HEIGHT + ACTION_BUTTON_GAP
SELL_BUTTON_TOP = ACTION_AREA_TOP + 2 * (ACTION_BUTTON_HEIGHT + ACTION_BUTTON_GAP)


def build_button_rects(tower_names=TOWER_ORDER):
    """Rects for each tower's build-menu button, keyed by registry name.
    `tower_names` defaults to every registered tower (classic/Practice
    play); a roguelike run passes its own RunState.unlocked_towers instead
    (see Game._active_tower_names/_rebuild_button_rects), restricting the
    menu to only the towers that run has drafted so far -- everything else
    about a button (its Rect shape, hit-testing, drawing) is unchanged
    regardless of which names it's built from."""
    rects = {}
    x = BUTTON_MARGIN
    for name in tower_names:
        rects[name] = pygame.Rect(x, BUTTON_Y, BUTTON_SIZE, BUTTON_SIZE)
        x += BUTTON_SIZE + BUTTON_MARGIN
    return rects


def _key_of_rect_containing(pos, rects):
    """The key of whichever `rects` dict entry contains `pos`, or None --
    every `get_clicked_*` button/row/tab lookup in this module is exactly
    this same "which Rect owns this point" query against a different
    dict, so they all delegate here instead of repeating the loop."""
    for key, rect in rects.items():
        if rect.collidepoint(pos):
            return key
    return None


def get_clicked_tower_button(pos, button_rects):
    """Return the tower registry name whose button contains pos, or None."""
    return _key_of_rect_containing(pos, button_rects)


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


SPEED_BUTTON_WIDTH = 84
SPEED_BUTTON_HEIGHT = 28


def build_speed_button_rect():
    """Rect for the HUD's speed-toggle button ('Speed: 1x', cycling to 2x/
    3x on click -- see Game.cycle_time_scale) -- right-aligned in the HUD's
    top strip (see HUD_TOP_STRIP_HEIGHT), independent of both the tower
    button row below it and the skip button, which lives in that row."""
    hud_top = settings.SCREEN_HEIGHT - settings.HUD_HEIGHT
    x = settings.PLAY_WIDTH - SPEED_BUTTON_WIDTH - BUTTON_MARGIN
    y = hud_top + (HUD_TOP_STRIP_HEIGHT - SPEED_BUTTON_HEIGHT) // 2
    return pygame.Rect(x, y, SPEED_BUTTON_WIDTH, SPEED_BUTTON_HEIGHT)


def _action_button_rect(top):
    x = settings.PLAY_WIDTH + (settings.PANEL_WIDTH - ACTION_BUTTON_WIDTH) // 2
    return pygame.Rect(x, top, ACTION_BUTTON_WIDTH, ACTION_BUTTON_HEIGHT)


def build_targeting_button_rect():
    """Rect for the stats panel's 'Targeting: <Mode>' row -- fixed position
    within the panel (see TARGETING_BUTTON_TOP), horizontally centered.
    Only meaningful (and only drawn/clickable) while the panel's subject is
    a placed tower -- see draw_tower_stats_panel and Game._handle_click."""
    return _action_button_rect(TARGETING_BUTTON_TOP)


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


def _format_currency(value, unlimited):
    """Shared "unlimited" display idiom for any gold-like value gated on
    Economy.unlimited_gold -- battle gold and shop currency both read this
    way (see draw_hud/draw_draft_screen) rather than each spelling out its
    own copy of the same ternary."""
    return "unlimited" if unlimited else str(value)


def draw_hud(surface, assets, font, small_font, economy, wave_manager, button_rects,
             skip_button_rect, selected_tower_name, time_scale, speed_button_rect,
             wave_preview=None, shop_currency=None, floor_label=None):
    # Only as wide as the grid above it (PLAY_WIDTH), not the full window --
    # the stats panel to its right draws itself separately.
    hud_rect = pygame.Rect(0, settings.SCREEN_HEIGHT - settings.HUD_HEIGHT,
                            settings.PLAY_WIDTH, settings.HUD_HEIGHT)
    pygame.draw.rect(surface, settings.COLOR_HUD_BG, hud_rect)

    _draw_speed_button(surface, small_font, speed_button_rect, time_scale)
    if wave_preview is not None:
        _draw_wave_preview(surface, small_font, hud_rect, wave_preview)

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

    # len(button_rects), not len(TOWER_ORDER) -- a roguelike run's build
    # menu shows only its own drafted subset (see build_button_rects), and
    # the gold/lives/wave text needs to sit right after however many
    # buttons are actually drawn, not always past all 9 registered towers.
    info_x = BUTTON_MARGIN + len(button_rects) * (BUTTON_SIZE + BUTTON_MARGIN) + 20
    gold_display = _format_currency(economy.gold, economy.unlimited_gold)
    gold_label = f"Gold: {gold_display}"
    # shop_currency is None outside of an active run (classic/Practice
    # play, an editor playtest) -- nothing to show there, since only a
    # run's own Shop screen (see draw_draft_screen) ever spends it. Shown
    # on the same line as battle gold, rather than a HUD row of its own,
    # since HUD_HEIGHT has no headroom left for a fourth line under Gold/
    # Lives/Wave (see settings.HUD_HEIGHT).
    if shop_currency is not None:
        shop_display = _format_currency(shop_currency, economy.unlimited_gold)
        gold_label += f"   Shop: {shop_display}"
    gold_text = font.render(gold_label, True, settings.COLOR_GOLD)
    lives_display = "infinite" if economy.invulnerable else str(economy.lives)
    lives_text = font.render(f"Lives: {lives_display}", True, settings.COLOR_LIVES)
    # floor_label ("Floor N/M") piggybacks onto the Wave line the same way
    # shop_currency piggybacks onto Gold above -- same "no headroom for a
    # fourth line" reason (see the comment there). None outside an active
    # run, same gate shop_currency uses.
    wave_label = _format_wave_label(wave_manager)
    if floor_label is not None:
        wave_label += f"   {floor_label}"
    wave_text = font.render(wave_label, True, settings.COLOR_TEXT)

    surface.blit(gold_text, (info_x, hud_rect.y + 8))
    surface.blit(lives_text, (info_x, hud_rect.y + 36))
    surface.blit(wave_text, (info_x, hud_rect.y + 64))

    _draw_wave_countdown_and_skip(surface, small_font, wave_manager, skip_button_rect)


def _format_wave_label(wave_manager):
    """The HUD's "Wave X/N" line -- pulled out as a pure function (like
    _format_wave_preview below) so its three cases are unit-testable
    without a display."""
    if wave_manager.all_waves_complete:
        return "All waves cleared!"
    if wave_manager.endless:
        # Never "x/N" here -- total_waves keeps growing as endless mode
        # generates more content, so a fixed-looking denominator would be
        # actively misleading about how many waves are actually left
        # (infinite, by design).
        return f"Wave {wave_manager.current_wave_number} (Endless)"
    return f"Wave {wave_manager.current_wave_number}/{wave_manager.total_waves}"


def _format_wave_preview(composition):
    """'Next: Grunt x8, Scout x5' -- ordered by ENEMY_ORDER (registry
    insertion order), not whatever order the dict happens to iterate in, so
    the same species always lines up in the same spot from wave to wave."""
    ordered_names = [name for name in ENEMY_ORDER if name in composition]
    parts = [f"{name.capitalize()} x{composition[name]}" for name in ordered_names]
    return "Next: " + ", ".join(parts)


def _draw_wave_preview(surface, font, hud_rect, wave_preview):
    text = _format_wave_preview(wave_preview)
    # Wrapped as a defensive cap, not because it's normally needed -- the
    # top strip has generous width (PLAY_WIDTH minus a small margin) well
    # beyond any realistic wave composition string.
    max_width = settings.PLAY_WIDTH - 2 * BUTTON_MARGIN
    y = hud_rect.y + 4
    for line in _wrap_text(text, font, max_width)[:2]:
        rendered = font.render(line, True, settings.COLOR_TEXT)
        surface.blit(rendered, (BUTTON_MARGIN, y))
        y += rendered.get_height() + 2


def _draw_speed_button(surface, font, speed_button_rect, time_scale):
    pygame.draw.rect(surface, settings.COLOR_BUTTON, speed_button_rect, border_radius=6)
    label = font.render(f"Speed: {time_scale:g}x", True, settings.COLOR_TEXT)
    surface.blit(label, label.get_rect(center=speed_button_rect.center))


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


def draw_footprint_preview(surface, grid, anchor_col, anchor_row, buildable, footprint_subtiles=None):
    """Outline of the footprint a tower would occupy if placed at subtile
    anchor (anchor_col, anchor_row) -- normally one tile's worth of area
    (grid.subtiles_per_tile), smaller for a relic-shrunk footprint (see
    Game._current_footprint_subtiles) -- lets the player see the footprint
    move in fine (sub-tile) increments while hovering the grid, colored by
    whether it's currently buildable."""
    size = grid.resolve_footprint_size(footprint_subtiles) * grid.subtile_size
    rect = pygame.Rect(anchor_col * grid.subtile_size, anchor_row * grid.subtile_size, size, size)
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


def draw_tower_stats_panel(surface, font, small_font, subject, economy, targeting_button_rect,
                            upgrade_button_rect, specialize_button_rects, sell_button_rect,
                            hovered_specialize_key=None):
    """The sidebar to the right of the play area. `subject` is either:
      - a Tower *class* (the build menu's currently selected type -- shows
        its base, level-1 stats), or
      - a Tower *instance* (a placed tower, either hovered or clicked to
        stay pinned open -- shows its live stats, with a '-> value'
        preview of what upgrading would change; a "Targeting: <Mode>" row
        that cycles targeting_mode on click; an Upgrade button below
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

    y = _draw_panel_header(surface, font, small_font, x, PANEL_PADDING, subject, is_placed,
                            tower_cls, hovered_specialize_key)
    _draw_panel_stats(surface, small_font, x, y, subject, tower_cls, is_placed)

    if is_placed:
        if not tower_cls.IS_SUPPORT:
            _draw_targeting_row(surface, small_font, subject, targeting_button_rect)
        _draw_panel_action_buttons(surface, small_font, subject, economy,
                                    upgrade_button_rect, specialize_button_rects, sell_button_rect)


def _draw_targeting_row(surface, small_font, subject, targeting_button_rect):
    """The "Targeting: <Mode>" button -- always shown for a placed tower
    (unlike Upgrade/Specialize, which are mutually exclusive with each
    other), since a tower's targeting mode is always choosable regardless
    of level."""
    pygame.draw.rect(surface, settings.COLOR_BUTTON, targeting_button_rect, border_radius=6)
    label = small_font.render(f"Targeting: {subject.targeting_mode.capitalize()}", True, settings.COLOR_TEXT)
    surface.blit(label, label.get_rect(center=targeting_button_rect.center))


def _draw_panel_hint(surface, small_font, x):
    y = PANEL_PADDING
    for line in ("Select a tower to build,", "or click a placed tower to", "see its stats, upgrade, or sell it."):
        hint = small_font.render(line, True, settings.COLOR_TEXT_DIM)
        surface.blit(hint, (x, y))
        y += PANEL_ROW_HEIGHT


def _draw_panel_header(surface, font, small_font, x, y, subject, is_placed, tower_cls, hovered_specialize_key):
    """Title, then either a placed tower's level/specialization line (plus
    a "choose a specialization" hint and the hovered option's description
    while eligible to) or a build-menu class's base cost. Returns the y
    position the stat rows should start at. `y` is the starting position
    (the sidebar panel always passes PANEL_PADDING; the draft screen's
    cards -- see _draw_draft_card -- pass their own rect's own top instead,
    which is the only reason this takes y as a parameter rather than
    hardcoding PANEL_PADDING itself like it used to)."""
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

    # A support tower never attacks -- Damage/Range/Fire rate would just
    # show a misleading "Damage: 0.0"/"Fire rate: 0.0/s" (and a "Range"
    # that's actually its buff radius, not an attack range). Its own
    # EXTRA_STATS (Damage buff / Range buff, see tower.SupportTower) are
    # its entire visible stat block instead.
    if not tower_cls.IS_SUPPORT:
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


# --- Run map screen (see run_map.py/Game._enter_map) ---
#
# Slay-the-Spire convention: the run's start (row 0) at the bottom, the boss
# (the final row) at the top. Full-screen, no side panel -- unlike gameplay,
# this screen has no board/HUD/stats panel to share space with (see
# GameState's own comment on why MAP is a full-screen state, not an overlay).

MAP_TOP = 90
MAP_BOTTOM = settings.SCREEN_HEIGHT - 60
MAP_NODE_RADIUS = 24
# Must match run_map.COLS -- how many columns a row's nodes are spread
# across. A plain duplicated layout constant (not imported from run_map.py)
# since ui.py otherwise has no reason to depend on that module at all -- the
# same "small numeric constants sometimes just agree by convention rather
# than by a shared import" spirit settings.py's own HUD_HEIGHT split
# (HUD_TOP_STRIP_HEIGHT + HUD_BUTTON_ROW_HEIGHT) already accepts.
MAP_COLS = 4

MAP_NODE_TYPE_LABELS = {
    "combat": "C", "elite": "E", "shop": "$", "event": "?", "rest": "+", "treasure": "T",
}
MAP_NODE_TYPE_COLORS = {
    "combat": settings.COLOR_NODE_COMBAT, "elite": settings.COLOR_NODE_ELITE,
    "shop": settings.COLOR_NODE_SHOP, "event": settings.COLOR_NODE_EVENT,
    "rest": settings.COLOR_NODE_REST, "treasure": settings.COLOR_NODE_TREASURE,
}


def build_map_node_rects(game_map):
    """One square Rect (MAP_NODE_RADIUS*2 per side, centered on where that
    node's circle draws) per MapNode in `game_map`, keyed by node id -- dict-
    keyed like build_level_select_rects, not list-indexed like
    build_draft_choice_rects, since a node's id is a stable identity across
    the whole run (unlike a per-visit shop offer's own cards). Rows are
    stacked bottom (row 0) to top (the boss); columns spread evenly across
    the full screen width. The run's map never scrolls (ROW_COUNT=6 rows
    comfortably fit MAP_TOP..MAP_BOTTOM at this spacing), so unlike level_
    select_rects there's no separate scroll-aware rebuild path needed."""
    row_count = len(game_map.rows)
    row_height = (MAP_BOTTOM - MAP_TOP) / (row_count - 1) if row_count > 1 else 0
    col_width = settings.SCREEN_WIDTH / (MAP_COLS + 1)
    rects = {}
    for row in game_map.rows:
        for node in row:
            rect = pygame.Rect(0, 0, MAP_NODE_RADIUS * 2, MAP_NODE_RADIUS * 2)
            rect.center = (round(col_width * (node.col + 1)), round(MAP_BOTTOM - node.row * row_height))
            rects[node.id] = rect
    return rects


def get_clicked_map_node(pos, node_rects):
    """Return the node id whose circle contains pos, or None."""
    return _key_of_rect_containing(pos, node_rects)


def draw_map_screen(surface, font, small_font, game_map, node_rects, current_node_id,
                     visited_node_ids, available_node_ids, hovered_node_id, lives=None, shop_currency=None):
    """The run's whole branching map, shown in full from the very first
    visit (see Game._enter_map) -- edges drawn first as plain lines, then
    every node as a filled, color-by-type circle, modulated by state:
    visited (dim, a checkmark), current (a bright ring), available (full
    color, hover-highlighted), or locked (desaturated, not yet reachable).
    `lives`/`shop_currency` are optional (None outside of an active run,
    same "nothing to show" spirit draw_hud's own shop_currency param
    follows) -- shown as a small readout up top since this screen has no
    HUD of its own to read them from otherwise."""
    surface.fill(settings.COLOR_BG)
    title = font.render("Choose your path", True, settings.COLOR_TEXT)
    surface.blit(title, title.get_rect(midtop=(settings.SCREEN_WIDTH // 2, 24)))

    if lives is not None and shop_currency is not None:
        info = small_font.render(f"Lives: {lives}   Shop currency: {shop_currency}", True, settings.COLOR_GOLD)
        surface.blit(info, info.get_rect(midtop=(settings.SCREEN_WIDTH // 2, 58)))

    for from_id, target_ids in game_map.edges.items():
        if from_id not in node_rects:
            continue
        start = node_rects[from_id].center
        for target_id in target_ids:
            if target_id in node_rects:
                pygame.draw.line(surface, settings.COLOR_NODE_EDGE, start, node_rects[target_id].center, width=2)

    for row in game_map.rows:
        for node in row:
            rect = node_rects[node.id]
            visited = node.id in visited_node_ids
            current = node.id == current_node_id
            available = node.id in available_node_ids
            base_color = MAP_NODE_TYPE_COLORS[node.node_type]
            fill_color = base_color if (visited or current or available) else settings.COLOR_NODE_LOCKED
            pygame.draw.circle(surface, fill_color, rect.center, MAP_NODE_RADIUS)
            border_color = settings.COLOR_BUTTON_SELECTED if (available and node.id == hovered_node_id) else settings.COLOR_TEXT
            pygame.draw.circle(surface, border_color, rect.center, MAP_NODE_RADIUS, width=3 if current else 1)

            label_color = settings.COLOR_TEXT_DIM if visited and not current else settings.COLOR_TEXT
            label = small_font.render(MAP_NODE_TYPE_LABELS[node.node_type], True, label_color)
            surface.blit(label, label.get_rect(center=rect.center))

    hint = small_font.render(
        "Click an available node to continue" if available_node_ids else "Nothing left to pick -- press any key",
        True, settings.COLOR_TEXT_DIM,
    )
    surface.blit(hint, hint.get_rect(midbottom=(settings.SCREEN_WIDTH // 2, settings.SCREEN_HEIGHT - 30)))
    esc_hint = small_font.render("Esc -- Quit", True, settings.COLOR_TEXT_DIM)
    surface.blit(esc_hint, (60, settings.SCREEN_HEIGHT - 40))


# --- Random Event / Rest / Treasure screens (the run map's other three
# non-combat, non-Shop node types -- see events.py/Game._enter_event_node/
# _enter_rest_node/_enter_treasure_node) ---

EVENT_OPTION_WIDTH = 480
EVENT_OPTION_HEIGHT = 100
EVENT_OPTION_GAP = 20
EVENT_OPTIONS_TOP = 300


def build_event_option_rects(count):
    """`count` rects for an Event screen's options, stacked in a centered
    vertical column -- mirrors build_draft_choice_rects' own per-visit,
    list-indexed shape (an Event's options aren't a stable identity across
    visits the way a map node's id is)."""
    x = (settings.SCREEN_WIDTH - EVENT_OPTION_WIDTH) // 2
    return [
        pygame.Rect(x, EVENT_OPTIONS_TOP + i * (EVENT_OPTION_HEIGHT + EVENT_OPTION_GAP),
                    EVENT_OPTION_WIDTH, EVENT_OPTION_HEIGHT)
        for i in range(count)
    ]


def get_clicked_event_option(pos, option_rects):
    """Return the index into `option_rects` (and the matching Event's own
    `options`) that pos landed on, or None."""
    for index, rect in enumerate(option_rects):
        if rect.collidepoint(pos):
            return index
    return None


def _describe_event_outcome(option, resolution):
    """Plain-text lines describing what `option` actually did, once
    resolved -- the currency/lives delta read straight off `option` itself
    (already applied to the run by the time this draws), plus whatever
    events.resolve_event_option's own `resolution` dict reports granting."""
    lines = []
    if option.shop_currency_delta:
        lines.append(f"Shop currency: {option.shop_currency_delta:+d}")
    if option.lives_delta:
        lines.append(f"Lives: {option.lives_delta:+d}")
    if resolution.get("relic"):
        lines.append(f"Gained relic: {RELICS[resolution['relic']].display_name}")
    if resolution.get("tower"):
        lines.append(f"Unlocked tower: {TOWER_TYPES[resolution['tower']].display_name}")
    return lines or ["Nothing else happened."]


def draw_event_screen(surface, font, small_font, event, option_rects, hovered_index, phase,
                       chosen_option=None, resolution=None):
    """`phase` is "choose" (the event's options are still on offer) or
    "resolved" (one's been picked -- `chosen_option`/`resolution` describe
    what happened; see Game._resolve_event_choice)."""
    surface.fill(settings.COLOR_BG)
    title = font.render(event.display_name, True, settings.COLOR_GOLD)
    surface.blit(title, title.get_rect(midtop=(settings.SCREEN_WIDTH // 2, 70)))

    y = 130
    for line in _wrap_text(event.prompt, small_font, EVENT_OPTION_WIDTH + 80):
        text = small_font.render(line, True, settings.COLOR_TEXT)
        surface.blit(text, text.get_rect(midtop=(settings.SCREEN_WIDTH // 2, y)))
        y += text.get_height() + 4

    if phase == "choose":
        for index, option in enumerate(event.options):
            rect = option_rects[index]
            fill_color = settings.COLOR_BUTTON_SELECTED if index == hovered_index else settings.COLOR_HUD_BG
            pygame.draw.rect(surface, fill_color, rect, border_radius=8)
            pygame.draw.rect(surface, settings.COLOR_BUTTON, rect, width=2, border_radius=8)
            label = small_font.render(option.label, True, settings.COLOR_GOLD)
            surface.blit(label, label.get_rect(midtop=(rect.centerx, rect.y + 10)))
            desc_y = rect.y + 10 + label.get_height() + 6
            for line in _wrap_text(option.description, small_font, rect.width - 24):
                desc = small_font.render(line, True, settings.COLOR_TEXT_DIM)
                surface.blit(desc, desc.get_rect(midtop=(rect.centerx, desc_y)))
                desc_y += desc.get_height() + 2
        bottom = option_rects[-1].bottom if option_rects else EVENT_OPTIONS_TOP
        hint = small_font.render("Choose one option above", True, settings.COLOR_TEXT_DIM)
        surface.blit(hint, hint.get_rect(midtop=(settings.SCREEN_WIDTH // 2, bottom + 20)))
    else:
        top = option_rects[0].y if option_rects else EVENT_OPTIONS_TOP
        chosen_label = small_font.render(f"You chose: {chosen_option.label}", True, settings.COLOR_GOLD)
        surface.blit(chosen_label, chosen_label.get_rect(midtop=(settings.SCREEN_WIDTH // 2, top)))
        summary_y = top + chosen_label.get_height() + 16
        for line in _describe_event_outcome(chosen_option, resolution or {}):
            text = small_font.render(line, True, settings.COLOR_TEXT)
            surface.blit(text, text.get_rect(midtop=(settings.SCREEN_WIDTH // 2, summary_y)))
            summary_y += PANEL_ROW_HEIGHT
        hint = small_font.render("Press any key or click to continue", True, settings.COLOR_TEXT_DIM)
        surface.blit(hint, hint.get_rect(midtop=(settings.SCREEN_WIDTH // 2, summary_y + 16)))

    esc_hint = small_font.render("Esc -- Quit", True, settings.COLOR_TEXT_DIM)
    surface.blit(esc_hint, (60, settings.SCREEN_HEIGHT - 40))


def draw_rest_screen(surface, font, small_font, heal_amount, lives_after):
    """A Rest node's static, already-resolved screen (see Game.
    _enter_rest_node -- there's no player choice here, unlike Event/Shop)."""
    surface.fill(settings.COLOR_BG)
    center_x = settings.SCREEN_WIDTH // 2
    mid_y = settings.SCREEN_HEIGHT // 2
    title = font.render("Rest Site", True, settings.COLOR_GOLD)
    surface.blit(title, title.get_rect(center=(center_x, mid_y - 50)))
    heal_line = small_font.render(f"You rest and recover {heal_amount} lives.", True, settings.COLOR_TEXT)
    surface.blit(heal_line, heal_line.get_rect(center=(center_x, mid_y)))
    lives_line = small_font.render(f"Lives: {lives_after}", True, settings.COLOR_LIVES)
    surface.blit(lives_line, lives_line.get_rect(center=(center_x, mid_y + 30)))
    hint = small_font.render("Press any key or click to continue", True, settings.COLOR_TEXT_DIM)
    surface.blit(hint, hint.get_rect(center=(center_x, mid_y + 70)))
    esc_hint = small_font.render("Esc -- Quit", True, settings.COLOR_TEXT_DIM)
    surface.blit(esc_hint, (60, settings.SCREEN_HEIGHT - 40))


def draw_treasure_screen(surface, font, small_font, granted_relic_key, granted_currency):
    """A Treasure node's static, already-resolved screen (see Game.
    _enter_treasure_node) -- granted_relic_key is None once every relic is
    already held (the currency half of a Treasure's reward never
    degrades the same way)."""
    surface.fill(settings.COLOR_BG)
    center_x = settings.SCREEN_WIDTH // 2
    mid_y = settings.SCREEN_HEIGHT // 2
    title = font.render("Treasure", True, settings.COLOR_GOLD)
    surface.blit(title, title.get_rect(center=(center_x, mid_y - 70)))
    currency_line = small_font.render(f"+{granted_currency} shop currency", True, settings.COLOR_GOLD)
    surface.blit(currency_line, currency_line.get_rect(center=(center_x, mid_y - 20)))

    if granted_relic_key is not None:
        relic = RELICS[granted_relic_key]
        relic_line = small_font.render(f"Relic: {relic.display_name}", True, settings.COLOR_TEXT)
        surface.blit(relic_line, relic_line.get_rect(center=(center_x, mid_y + 10)))
        desc_y = mid_y + 36
        for line in _wrap_text(relic.description, small_font, EVENT_OPTION_WIDTH):
            desc = small_font.render(line, True, settings.COLOR_TEXT_DIM)
            surface.blit(desc, desc.get_rect(center=(center_x, desc_y)))
            desc_y += desc.get_height() + 2
    else:
        none_line = small_font.render("(every relic is already held)", True, settings.COLOR_TEXT_DIM)
        surface.blit(none_line, none_line.get_rect(center=(center_x, mid_y + 10)))

    hint = small_font.render("Press any key or click to continue", True, settings.COLOR_TEXT_DIM)
    surface.blit(hint, hint.get_rect(center=(center_x, mid_y + 100)))
    esc_hint = small_font.render("Esc -- Quit", True, settings.COLOR_TEXT_DIM)
    surface.blit(esc_hint, (60, settings.SCREEN_HEIGHT - 40))


# --- Draft screen (a roguelike run's own Shop, entered via a map node -- see
# game.py's GameState.DRAFT for why the code still says "draft") ---

DRAFT_CARD_WIDTH = settings.PANEL_WIDTH  # matches the sidebar's own visual width
DRAFT_CARD_HEIGHT = 260
DRAFT_CARD_GAP = 24
DRAFT_CARDS_TOP = 200

SHOP_CONTINUE_BUTTON_WIDTH = 220
SHOP_CONTINUE_BUTTON_HEIGHT = 48


def build_shop_continue_button_rect():
    """Rect for the Shop screen's 'Continue' button (see Game._handle_
    draft_click) -- leaves the shop and loads the next floor without
    buying anything else this visit. Centered under the item cards, same
    "just a Rect, no state of its own" shape build_skip_button_rect
    already sets."""
    x = (settings.SCREEN_WIDTH - SHOP_CONTINUE_BUTTON_WIDTH) // 2
    y = DRAFT_CARDS_TOP + DRAFT_CARD_HEIGHT + 30
    return pygame.Rect(x, y, SHOP_CONTINUE_BUTTON_WIDTH, SHOP_CONTINUE_BUTTON_HEIGHT)


def build_draft_choice_rects(count):
    """`count` rects for the Shop screen's item choices, laid out as a
    centered horizontal row -- generalizes build_specialize_button_rects's
    fixed-2-rect pattern to however many items shop.build_offer actually
    returned (usually its own default count, but fewer once a run's tower/
    relic pools are nearly exhausted). Empty for count == 0 (nothing left
    to offer -- see Game._enter_draft, which skips this screen entirely in
    that case) since range(0) below already yields nothing."""
    total_width = count * DRAFT_CARD_WIDTH + (count - 1) * DRAFT_CARD_GAP
    start_x = (settings.SCREEN_WIDTH - total_width) // 2
    return [
        pygame.Rect(start_x + i * (DRAFT_CARD_WIDTH + DRAFT_CARD_GAP), DRAFT_CARDS_TOP,
                    DRAFT_CARD_WIDTH, DRAFT_CARD_HEIGHT)
        for i in range(count)
    ]


def get_clicked_draft_choice(pos, draft_choice_rects):
    """Index into `choices`/`draft_choice_rects` (see draw_draft_screen)
    the click landed on, or None -- draft_choice_rects is a list, not a
    dict keyed by name, since a shop visit's own tower and relic offers
    can each repeat a key across different visits (a still-unbought tower
    stays offerable next time); index is the only identifier guaranteed
    unique within one visit."""
    for index, rect in enumerate(draft_choice_rects):
        if rect.collidepoint(pos):
            return index
    return None


def _draw_card_frame(surface, small_font, rect, hovered, purchased, affordable, price):
    """The fill+border every shop card (tower or relic) shares, plus its
    price tag/SOLD badge -- pulled out so the two card kinds' own
    content-drawing can't drift apart on hover color/border width/radius,
    or on how a price renders, the way two independent copies of this
    would. Returns the x each card's own content should start drawing at."""
    fill_color = settings.COLOR_BUTTON_SELECTED if (hovered and not purchased) else settings.COLOR_HUD_BG
    pygame.draw.rect(surface, fill_color, rect, border_radius=8)
    border_color = settings.COLOR_BUTTON if (purchased or affordable) else settings.COLOR_BUTTON_DISABLED
    pygame.draw.rect(surface, border_color, rect, width=2, border_radius=8)

    if purchased:
        tag_text, tag_color = "SOLD", settings.COLOR_TEXT_DIM
    else:
        tag_text = str(price)
        tag_color = settings.COLOR_GOLD if affordable else settings.COLOR_TEXT_DIM
    tag = small_font.render(tag_text, True, tag_color)
    surface.blit(tag, tag.get_rect(topright=(rect.right - PANEL_PADDING, rect.y + PANEL_PADDING)))
    return rect.x + PANEL_PADDING


def _draw_draft_card(surface, font, small_font, rect, name, hovered, purchased, affordable, price):
    tower_cls = TOWER_TYPES[name]
    x = _draw_card_frame(surface, small_font, rect, hovered, purchased, affordable, price)
    # Reuses the sidebar's own class-subject header+stats rendering
    # verbatim (a shop card is exactly a build-menu selection's
    # not-yet-built display, just laid out in its own rect instead of the
    # fixed sidebar slot) -- see _draw_panel_header's own docstring for why
    # it takes y as a parameter rather than hardcoding PANEL_PADDING. Its
    # own "Cost: N" line is tower_cls.cost, the *battle gold* it'll take to
    # place once unlocked -- a different number from (and drawn well away
    # from) this card's own shop-currency price tag in the corner.
    y = _draw_panel_header(surface, font, small_font, x, rect.y + PANEL_PADDING,
                            tower_cls, False, tower_cls, None)
    _draw_panel_stats(surface, small_font, x, y, tower_cls, tower_cls, False)


def _draw_relic_card(surface, font, small_font, rect, key, hovered, purchased, affordable, price):
    relic = RELICS[key]
    x = _draw_card_frame(surface, small_font, rect, hovered, purchased, affordable, price)
    y = rect.y + PANEL_PADDING
    title = font.render(relic.display_name, True, settings.COLOR_TEXT)
    surface.blit(title, (x, y))
    y += 34

    max_width = DRAFT_CARD_WIDTH - 2 * PANEL_PADDING
    for line in _wrap_text(relic.description, small_font, max_width):
        line_text = small_font.render(line, True, settings.COLOR_TEXT_DIM)
        surface.blit(line_text, (x, y))
        y += PANEL_ROW_HEIGHT


def draw_draft_screen(surface, font, small_font, choices, draft_choice_rects, hovered_index,
                       purchased_indices, shop_currency, continue_button_rect, unlimited_gold=False):
    """`choices` is a list of shop.ShopItem, mixing both card kinds
    together now that one shop visit offers towers and relics at once (see
    shop.build_offer) -- each item carries its own `kind` ("tower"/
    "relic") rather than the whole screen sharing one, unlike the single-
    type draft this replaced. `draft_choice_rects` is one Rect per item,
    same length/order (see build_draft_choice_rects). `purchased_indices`
    is the set of indices already bought this visit (see Game._try_buy_
    shop_item) -- drawn as SOLD and greyed out rather than removed from
    the layout, so the row doesn't reflow while shopping. `unlimited_gold`
    (see economy.py's own docstring) makes every item read as affordable
    regardless of `shop_currency`, mirroring how it already does for
    battle gold in the build menu (see draw_hud). A full-screen state (see
    GameState's own comment on why), not an overlay on a frozen board the
    way draw_victory_screen/draw_game_over_screen still are -- a Shop visit
    is reached from the map now, not always immediately after a fresh
    floor clear, so there's no board behind it that's reliably still
    relevant. _draw_dim_overlay is still called for its dimmed-black
    backdrop look (now just over the plain COLOR_BG fill this screen
    starts with, rather than over a frozen board), keeping this screen's
    visual identity consistent with the run's other full-screen node
    screens (see draw_event_screen/draw_rest_screen/draw_treasure_screen)."""
    surface.fill(settings.COLOR_BG)
    _draw_dim_overlay(surface)

    title = font.render("Shop: spend shop currency on towers and relics", True, settings.COLOR_GOLD)
    surface.blit(title, title.get_rect(center=(settings.SCREEN_WIDTH // 2, DRAFT_CARDS_TOP - 40)))

    for index, item in enumerate(choices):
        purchased = index in purchased_indices
        # Every item still for sale costs the same "next purchase" price
        # right now -- price_for's escalation is keyed on how many this
        # visit has already bought in total, not on which item it is (see
        # Game._try_buy_shop_item, which computes the identical value at
        # the moment of an actual purchase).
        price = price_for(item, len(purchased_indices))
        affordable = can_afford(shop_currency, price, unlimited_gold)
        draw_card = _draw_relic_card if item.kind == "relic" else _draw_draft_card
        draw_card(surface, font, small_font, draft_choice_rects[index], item.key,
                  index == hovered_index, purchased, affordable, price)

    currency_display = _format_currency(shop_currency, unlimited_gold)
    currency_text = small_font.render(f"Shop currency: {currency_display}", True, settings.COLOR_GOLD)
    surface.blit(currency_text, currency_text.get_rect(
        midbottom=(settings.SCREEN_WIDTH // 2, continue_button_rect.y - 12)))

    pygame.draw.rect(surface, settings.COLOR_BUTTON, continue_button_rect, border_radius=6)
    continue_label = small_font.render("Continue", True, settings.COLOR_GOLD)
    surface.blit(continue_label, continue_label.get_rect(center=continue_button_rect.center))


# --- Floor Cleared screen (a roguelike run's own per-floor results) ---

def draw_floor_cleared_screen(surface, font, small_font, floor_number, floor_count, results=None):
    """floor_number/floor_count are 1-based ("Floor 2/6 cleared!") -- the
    run's own equivalent of draw_victory_screen, just without "next
    level"/"play again" framing since advancing goes to the draft screen
    (see draw_draft_screen above) instead of straight back into play."""
    _draw_overlay_with_results(
        surface, font, small_font, f"Floor {floor_number}/{floor_count} cleared!",
        "Press any key to continue", settings.COLOR_GOLD, results,
    )


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


_dim_overlay_cache = {}


def _draw_dim_overlay(surface, width=None):
    """The full-height, semi-transparent black backdrop every full-screen
    overlay in this module draws before its own content -- shared by
    _draw_centered_overlay below (menu/pause/victory/game-over/floor-
    cleared) and draw_draft_screen, so the two don't silently drift apart
    on how dim "dim" is. The backdrop itself never changes (solid black,
    alpha 170) for a given size, so it's built once per distinct
    (width, SCREEN_HEIGHT) and reused from _dim_overlay_cache rather than
    reallocated fresh every single frame one of these screens is shown --
    DRAFT/FLOOR_CLEARED especially, which can now stay up for many
    consecutive frames per floor, far more often than the comparatively
    rare MENU/PAUSED/VICTORY/GAME_OVER screens this was originally
    written for."""
    if width is None:
        width = settings.SCREEN_WIDTH
    key = (width, settings.SCREEN_HEIGHT)
    overlay = _dim_overlay_cache.get(key)
    if overlay is None:
        overlay = pygame.Surface(key, pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        _dim_overlay_cache[key] = overlay
    surface.blit(overlay, (0, 0))


def _draw_centered_overlay(surface, font, small_font, title, subtitle, title_color, width=None):
    """`subtitle` is a single string, or a list of strings each rendered
    on its own line below the title (used by the pause menu's option
    list) -- an empty string/list draws no subtitle at all. Returns the y
    position just past the last line drawn, so a caller (see
    draw_victory_screen/draw_game_over_screen) can layer more content
    (the post-level results table) below it without hardcoding its own
    guess at how tall the title+subtitle block turned out to be."""
    if width is None:
        width = settings.SCREEN_WIDTH
    _draw_dim_overlay(surface, width=width)

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
    return y


# Single source of truth for every letter GameState.MENU routes to
# something other than the default "start playing" catch-all -- paired
# with its on-screen hint label, in the same order the README/CLAUDE.md
# list them ("start / E / L / S / A / C"). Game._handle_keydown's MENU
# branch checks membership in MENU_KEY_LETTERS (derived below) before
# dispatching a letter to its own behavior, so a key can never end up
# routable there without also appearing in menu_options()'s hint list --
# this is exactly the pair of facts that once drifted apart (missing
# "L -- Level Browser" despite the L key itself always having worked);
# now a letter added to only one side either shows a hint for a key that
# does nothing, or does something with no hint promising it exists --
# both loud, easy-to-notice bugs instead of the original silent one.
# "C -- Continue" isn't listed here since it's conditional on
# Game.has_saved_run, handled separately by both sides below.
MENU_KEY_HINTS = [
    ("e", "Map Editor"),
    ("l", "Practice a Floor"),
    ("s", "Settings"),
    ("a", "Achievements"),
    ("h", "How to Play"),
    ("d", "Daily Run"),
]
MENU_KEY_LETTERS = frozenset(letter for letter, _label in MENU_KEY_HINTS)


def menu_options(has_saved_run=False):
    """The main menu's line-per-option hint list -- pulled out as its own
    pure function, rather than inlined in draw_menu_screen below, so it's
    unit-testable directly (see test_ui.py) and so it can share
    MENU_KEY_HINTS with Game._handle_keydown's own dispatch above rather
    than hand-listing the same letters a second time."""
    options = ["Press any key to start a run"]
    options += [f"{letter.upper()} -- {label}" for letter, label in MENU_KEY_HINTS]
    if has_saved_run:
        options.append("C -- Continue")
    return options


def draw_menu_screen(surface, font, small_font, has_saved_run=False):
    surface.fill(settings.COLOR_BG)
    options = menu_options(has_saved_run)
    _draw_centered_overlay(surface, font, small_font, "Tower Defense", options, settings.COLOR_TEXT)


# --- Settings screen ---

SETTINGS_BUTTON_WIDTH = 240
SETTINGS_BUTTON_HEIGHT = 44
SETTINGS_BUTTON_GAP = 16
SETTINGS_TOP = 160

# "fullscreen" toggles on/off; each difficulty.DIFFICULTY_ORDER key picks
# that difficulty.DIFFICULTY_MODES entry directly (so get_clicked_settings_
# option's result plugs straight into Game.set_difficulty with no
# translation); "back" returns to the menu.
SETTINGS_OPTION_ORDER = ["fullscreen", *DIFFICULTY_ORDER, "back"]


def _settings_button_rect(index):
    x = (settings.SCREEN_WIDTH - SETTINGS_BUTTON_WIDTH) // 2
    y = SETTINGS_TOP + index * (SETTINGS_BUTTON_HEIGHT + SETTINGS_BUTTON_GAP)
    return pygame.Rect(x, y, SETTINGS_BUTTON_WIDTH, SETTINGS_BUTTON_HEIGHT)


def build_settings_rects():
    """Rects for the Settings screen's buttons, keyed by option name -- see
    SETTINGS_OPTION_ORDER."""
    return {key: _settings_button_rect(index) for index, key in enumerate(SETTINGS_OPTION_ORDER)}


def get_clicked_settings_option(pos, settings_rects):
    """Return the settings option key whose button contains pos, or None."""
    return _key_of_rect_containing(pos, settings_rects)


def _draw_settings_button(surface, font, rect, label, selected):
    color = settings.COLOR_BUTTON_SELECTED if selected else settings.COLOR_BUTTON
    pygame.draw.rect(surface, color, rect, border_radius=6)
    text = font.render(label, True, settings.COLOR_TEXT)
    surface.blit(text, text.get_rect(center=rect.center))


def draw_settings_screen(surface, font, small_font, settings_rects, fullscreen, difficulty_key):
    surface.fill(settings.COLOR_BG)
    title = font.render("Settings", True, settings.COLOR_TEXT)
    surface.blit(title, title.get_rect(midtop=(settings.SCREEN_WIDTH // 2, 40)))

    fullscreen_label = f"Fullscreen: {'On' if fullscreen else 'Off'}"
    _draw_settings_button(surface, small_font, settings_rects["fullscreen"], fullscreen_label, fullscreen)

    for key in DIFFICULTY_ORDER:
        label = f"Difficulty: {DIFFICULTY_MODES[key].display_name}"
        _draw_settings_button(surface, small_font, settings_rects[key], label, key == difficulty_key)

    _draw_settings_button(surface, small_font, settings_rects["back"], "Back to Menu", False)

    hint = small_font.render("Esc -- Back to Menu", True, settings.COLOR_TEXT_DIM)
    surface.blit(hint, (60, settings.SCREEN_HEIGHT - 40))


# --- Achievements screen ---

ACHIEVEMENTS_TOP = 110
ACHIEVEMENT_ROW_HEIGHT = 34
ACHIEVEMENTS_BACK_BUTTON_WIDTH = 240
ACHIEVEMENTS_BACK_BUTTON_HEIGHT = 40
ACHIEVEMENTS_BACK_BUTTON_GAP = 24


def build_achievements_back_rect(achievement_count=len(ACHIEVEMENT_ORDER)):
    """Rect for the Achievements screen's single 'Back to Menu' button,
    stacked directly below the last achievement row -- the list is short
    and fixed (the registry doesn't change at runtime), so unlike the
    level-select browser this never needs to scroll."""
    x = (settings.SCREEN_WIDTH - ACHIEVEMENTS_BACK_BUTTON_WIDTH) // 2
    y = ACHIEVEMENTS_TOP + achievement_count * ACHIEVEMENT_ROW_HEIGHT + ACHIEVEMENTS_BACK_BUTTON_GAP
    return pygame.Rect(x, y, ACHIEVEMENTS_BACK_BUTTON_WIDTH, ACHIEVEMENTS_BACK_BUTTON_HEIGHT)


def draw_achievements_screen(surface, font, small_font, unlocked_keys, counters, back_rect):
    """`unlocked_keys` and `counters` are achievements.load_achievements()'s
    own "unlocked"/"counters" values -- read fresh whenever this screen is
    (re-)entered (see Game._enter_achievements()), same "always re-read,
    never a stale cached copy" spirit persistence.list_custom_levels()
    follows for the level browser. Every registry
    entry is always listed, in ACHIEVEMENT_ORDER (registry insertion order)
    -- a locked one shows its live progress toward its own goal rather than
    just "Locked", so the screen doubles as a progress tracker."""
    surface.fill(settings.COLOR_BG)
    title = font.render("Achievements", True, settings.COLOR_TEXT)
    surface.blit(title, title.get_rect(midtop=(settings.SCREEN_WIDTH // 2, 30)))

    y = ACHIEVEMENTS_TOP
    for key in ACHIEVEMENT_ORDER:
        achievement = ACHIEVEMENTS[key]
        if key in unlocked_keys:
            status, color = "Unlocked", settings.COLOR_GOLD
        else:
            progress_value = min(counters.get(achievement.counter, 0), achievement.goal)
            status, color = f"{progress_value}/{achievement.goal}", settings.COLOR_TEXT_DIM
        line = f"{achievement.display_name} -- {achievement.description} ({status})"
        text = small_font.render(line, True, color)
        surface.blit(text, text.get_rect(midtop=(settings.SCREEN_WIDTH // 2, y)))
        y += ACHIEVEMENT_ROW_HEIGHT

    pygame.draw.rect(surface, settings.COLOR_BUTTON, back_rect, border_radius=6)
    label = small_font.render("Back to Menu", True, settings.COLOR_TEXT)
    surface.blit(label, label.get_rect(center=back_rect.center))

    hint = small_font.render("Esc -- Back to Menu", True, settings.COLOR_TEXT_DIM)
    surface.blit(hint, (60, settings.SCREEN_HEIGHT - 40))


# --- Help / How to Play screen ---

HELP_TOP = 100
HELP_LINE_HEIGHT = 34
HELP_BACK_BUTTON_WIDTH = 240
HELP_BACK_BUTTON_HEIGHT = 40
HELP_BACK_BUTTON_GAP = 24

# A hand-written condensation of README.md's own "Controls" section -- kept
# in sync with it by hand (there's no test enforcing that, same as nothing
# enforces menu_options()/README.md staying in sync either) so a player
# never has to leave the game to learn what that section documents in full.
HELP_LINES = [
    "Menu: press any key to play -- E Editor, L Levels, S Settings, A Achievements",
    "Build: click a tower button, then click a buildable tile to place it",
    "Right-click clears your current selection without placing anything",
    "Click a tower to pin its stats -- Targeting / Upgrade / Sell in the sidebar",
    "Targeting cycles first / last / strongest / closest -- who gets shot",
    "At max level, Upgrade becomes two permanent Specialize choices",
    "Space (or the HUD button) starts the next wave or skips its countdown",
    "1 / 2 / 3 change simulation speed -- the frame rate itself stays the same",
    "P or Esc pauses -- R restarts, Q quits, S (between waves) saves & exits",
    "Practice (L): pick any floor solo, always Sandbox rules -- V also arms Endless mode",
]


def build_help_back_rect(line_count=len(HELP_LINES)):
    """Rect for the Help screen's single 'Back to Menu' button, stacked
    below the last line -- same layout idea as build_achievements_back_rect,
    since HELP_LINES is likewise a short, fixed list."""
    x = (settings.SCREEN_WIDTH - HELP_BACK_BUTTON_WIDTH) // 2
    y = HELP_TOP + line_count * HELP_LINE_HEIGHT + HELP_BACK_BUTTON_GAP
    return pygame.Rect(x, y, HELP_BACK_BUTTON_WIDTH, HELP_BACK_BUTTON_HEIGHT)


def draw_help_screen(surface, font, small_font, back_rect):
    """Static how-to-play screen -- HELP_LINES is a fixed, hand-written
    summary, not derived from any in-game state, so unlike Settings/
    Achievements there's nothing to read or re-read on entry (see
    Game._handle_keydown's HELP branch -- no _enter_help() needed)."""
    surface.fill(settings.COLOR_BG)
    title = font.render("How to Play", True, settings.COLOR_TEXT)
    surface.blit(title, title.get_rect(midtop=(settings.SCREEN_WIDTH // 2, 30)))

    y = HELP_TOP
    for line in HELP_LINES:
        text = small_font.render(line, True, settings.COLOR_TEXT)
        surface.blit(text, text.get_rect(midtop=(settings.SCREEN_WIDTH // 2, y)))
        y += HELP_LINE_HEIGHT

    pygame.draw.rect(surface, settings.COLOR_BUTTON, back_rect, border_radius=6)
    label = small_font.render("Back to Menu", True, settings.COLOR_TEXT)
    surface.blit(label, label.get_rect(center=back_rect.center))

    hint = small_font.render("Esc -- Back to Menu", True, settings.COLOR_TEXT_DIM)
    surface.blit(hint, (60, settings.SCREEN_HEIGHT - 40))


def draw_pause_menu(surface, font, small_font, is_custom_level=False, can_save=False):
    # Only darkens/centers over the play area (grid + HUD) -- the stats
    # panel stays visible and undimmed to its right. "Return to Editor"
    # only makes sense while playing a level that actually came from the
    # editor -- a built-in level has no corresponding in-progress paint
    # buffer to go back to. "Save & Quit" only makes sense between waves
    # (see Game.can_save_run()) -- there's no live enemy/projectile state
    # to resume back into mid-wave.
    options = ["Esc / P -- Resume", "R -- Restart Level"]
    if is_custom_level:
        options.append("E -- Return to Map Editor")
    if can_save:
        options.append("S -- Save & Quit")
    options.append("Q -- Quit")
    _draw_centered_overlay(surface, font, small_font, "Paused", options,
                            settings.COLOR_TEXT, width=settings.PLAY_WIDTH)


def _draw_overlay_with_results(surface, font, small_font, title, subtitle, title_color, results):
    """Shared by draw_game_over_screen/draw_victory_screen: the title +
    subtitle overlay (see _draw_centered_overlay), then the post-level
    results table stacked directly below wherever that overlay ended."""
    bottom = _draw_centered_overlay(surface, font, small_font, title, subtitle,
                                     title_color, width=settings.PLAY_WIDTH)
    draw_results_table(surface, small_font, results, bottom + 16, width=settings.PLAY_WIDTH)


def draw_game_over_screen(surface, font, small_font, results=None):
    _draw_overlay_with_results(surface, font, small_font, "Game Over", "Press R to restart",
                                settings.COLOR_LIVES, results)


def draw_victory_screen(surface, font, small_font, has_next_level=False, results=None):
    if has_next_level:
        title, subtitle = "Level Complete!", "Press R for the next level"
    else:
        title, subtitle = "Victory!", "Press R to play again"
    _draw_overlay_with_results(surface, font, small_font, title, subtitle, settings.COLOR_GOLD, results)


# --- Post-level results (per-tower damage/kills/accuracy) ---

RESULTS_ROW_HEIGHT = 22
RESULTS_MAX_ROWS = 6


def compute_tower_results(towers):
    """{display_name, shots_fired, shots_hit, damage_dealt, kills,
    accuracy} for every tower in `towers` (placed and sold alike -- see
    Game._tower_results), sorted by damage dealt descending. `accuracy` is
    None (not 0, not a ZeroDivisionError) for a tower that never fired --
    true of every Support tower (see tower.py's IS_SUPPORT), and of any
    attacking tower that just never got a shot off. Pure and
    display-agnostic, same spirit as WaveManager.next_wave_preview()."""
    rows = [{
        "display_name": tower.display_name,
        "shots_fired": tower.shots_fired,
        "shots_hit": tower.shots_hit,
        "damage_dealt": tower.damage_dealt,
        "kills": tower.kills,
        "accuracy": (tower.shots_hit / tower.shots_fired) if tower.shots_fired else None,
    } for tower in towers]
    return sorted(rows, key=lambda row: row["damage_dealt"], reverse=True)


def draw_results_table(surface, small_font, results, top_y, width=None):
    """A compact per-tower results table, drawn below the Victory/Game
    Over overlay's title and subtitle (see _draw_centered_overlay's
    return value). `results` is None or empty (e.g. a level with no
    towers ever placed) draws nothing at all. No scrolling machinery --
    realistic tower counts fit within RESULTS_MAX_ROWS rows, and anything
    beyond that collapses into a single "+N more" line instead, the same
    "finite room, note the overflow" spirit as the editor sidebar's own
    status_lines[:6] cap."""
    if not results:
        return
    if width is None:
        width = settings.PLAY_WIDTH
    center_x = width // 2

    header = small_font.render("Tower -- Damage / Kills / Accuracy", True, settings.COLOR_TEXT_DIM)
    surface.blit(header, header.get_rect(center=(center_x, top_y)))
    y = top_y + RESULTS_ROW_HEIGHT

    for row in results[:RESULTS_MAX_ROWS]:
        accuracy = "--" if row["accuracy"] is None else f"{round(row['accuracy'] * 100)}%"
        text = f"{row['display_name']}: {row['damage_dealt']:.0f} dmg / {row['kills']} kills / {accuracy}"
        line = small_font.render(text, True, settings.COLOR_TEXT)
        surface.blit(line, line.get_rect(center=(center_x, y)))
        y += RESULTS_ROW_HEIGHT

    remaining = len(results) - RESULTS_MAX_ROWS
    if remaining > 0:
        more = small_font.render(f"+{remaining} more", True, settings.COLOR_TEXT_DIM)
        surface.blit(more, more.get_rect(center=(center_x, y)))


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
    "line": "Line",
    "rect": "Rect",
    "select": "Select",
}
EDITOR_TOOL_ORDER = list(EDITOR_TOOL_LABELS.keys())

EDITOR_ACTION_LABELS = {
    "load": "Load Map...",
    "import": "Import Level...",
    "waves": "Edit Waves ->",
    "back": "Back to Menu",
    "undo": "Undo",
    "redo": "Redo",
    "copy": "Copy",
    "paste": "Paste",
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
    return _key_of_rect_containing(pos, tool_rects)


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
    return _key_of_rect_containing(pos, action_rects)


def draw_editor_screen(surface, assets, font, small_font, editor, tool_rects, action_rects,
                        import_status_message=None, import_status_is_error=False):
    surface.fill(settings.COLOR_BG)
    _draw_editor_grid(surface, assets, small_font, editor, pending_shape_cells=editor.pending_shape_cells())
    _draw_editor_toolbar(surface, small_font, editor, tool_rects)
    _draw_editor_path_sidebar(
        surface, font, small_font, editor, action_rects, import_status_message, import_status_is_error,
    )


def _cell_center(editor, cell):
    col, row = cell
    return (
        col * editor.tile_size + editor.tile_size // 2,
        row * editor.tile_size + editor.tile_size // 2,
    )


def _draw_editor_grid(surface, assets, small_font, editor, active_spawn=None, pending_shape_cells=frozenset()):
    """The path/spawn/goal/junction preview shared by both editor screens.
    Spawns are numbered (stable sort order by cell) so a multi-spawn
    level's spawns have a consistent, referenceable identity across both
    screens; `active_spawn`, when given (only the wave editor has one),
    gets a highlight ring -- see Game._handle_wave_editor_click, which is
    what clicking a spawn marker there actually changes. `pending_shape_
    cells` (only the path editor ever has any -- see Editor.pending_
    shape_cells()) is a translucent ghost overlay for an in-progress
    Line/Rect/Select drag, drawn over the tiles but under every marker."""
    for row in range(editor.rows):
        for col in range(editor.cols):
            cell = (col, row)
            name = "tile_path" if cell in editor.path_cells else "tile_grass"
            sprite = assets.get(name, (editor.tile_size, editor.tile_size))
            surface.blit(sprite, (col * editor.tile_size, row * editor.tile_size))

    if pending_shape_cells:
        overlay = pygame.Surface((editor.tile_size, editor.tile_size), pygame.SRCALPHA)
        overlay.fill((255, 255, 255, 90))
        for col, row in pending_shape_cells:
            surface.blit(overlay, (col * editor.tile_size, row * editor.tile_size))

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


def _draw_editor_path_sidebar(surface, font, small_font, editor, action_rects,
                               import_status_message=None, import_status_is_error=False):
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
    if editor.active_tool == "rect":
        # A freshly-stamped rectangle is always a closed loop (exactly the
        # shape validate_topology forbids) -- not a bug, but genuinely
        # non-obvious the first time; the fix is one Erase click on any
        # edge cell to open it into a valid corridor.
        status_lines = list(status_lines) + ["Rectangles start as a loop -- erase one cell to open it"]
    y = PANEL_PADDING + 40
    for line in status_lines[:6]:  # panel has finite room; the rest are still in path_problems
        for wrapped in _wrap_text(line, small_font, settings.PANEL_WIDTH - 2 * PANEL_PADDING):
            text = small_font.render(wrapped, True, status_color)
            surface.blit(text, (x, y))
            y += PANEL_ROW_HEIGHT

    for name, rect in action_rects.items():
        # "load"/"import"/"back" always work; moving on to wave editing needs a valid path first.
        enabled = path_ok if name == "waves" else True
        color = settings.COLOR_BUTTON if enabled else settings.COLOR_BUTTON_DISABLED
        pygame.draw.rect(surface, color, rect, border_radius=6)
        label = small_font.render(EDITOR_ACTION_LABELS[name], True, settings.COLOR_TEXT)
        surface.blit(label, label.get_rect(center=rect.center))

    if import_status_message is not None:
        # Same "result of the last action, shown below the action buttons"
        # spirit as the wave editor sidebar's "Saved to:" status (see
        # _draw_wave_editor_sidebar) -- success in gold, failure in the
        # same red the HUD's lives counter uses for "something's wrong."
        status_color = settings.COLOR_LIVES if import_status_is_error else settings.COLOR_GOLD
        status_y = max(rect.bottom for rect in action_rects.values()) + 16
        for line_index, line in enumerate(
            _wrap_text(import_status_message, small_font, settings.PANEL_WIDTH - 2 * PANEL_PADDING)
        ):
            text = small_font.render(line, True, status_color)
            surface.blit(text, (x, status_y + PANEL_ROW_HEIGHT * line_index))


# --- Wave editor ---
#
# A second screen reached from the map editor once its path is valid (see
# EDITOR_ACTION_LABELS["waves"]) -- same PLAY_WIDTH/PANEL_WIDTH geometry,
# just with wave-selector tabs in the toolbar row instead of path tools,
# and per-species +/- rows plus Playtest/Save/Back-to-Path in the sidebar
# instead of the path tools' status text and Edit-Waves/Back-to-Menu.

WAVE_TAB_SIZE = 48
WAVE_TAB_MARGIN = 8
WAVE_TAB_Y = (settings.SCREEN_HEIGHT - HUD_BUTTON_ROW_HEIGHT
              + (HUD_BUTTON_ROW_HEIGHT - WAVE_TAB_SIZE) // 2)

WAVE_UNIT_ROWS_TOP = 100
# Leaves room below the last visible row for the fixed Playtest/Save/Back
# action-button slot (ACTION_AREA_TOP) -- the scrollable viewport is
# everything between this and WAVE_UNIT_ROWS_TOP, same LEVEL_SELECT_TOP/
# LEVEL_SELECT_BOTTOM shape the level-select screen already uses for the
# identical "more entries than fit a fixed panel" problem (see
# level_select_max_scroll/build_level_select_rects/draw_level_select_screen,
# the exact template build_wave_unit_rects/_draw_wave_editor_sidebar below
# mirror). A previous version of this made WAVE_UNIT_ROW_HEIGHT hug the
# registry's size exactly (touching rows, no gap) to avoid ever needing to
# scroll -- but that's a fixed budget for what's fundamentally an
# unbounded-by-registry-size list (ENEMY_ORDER), and broke again the very
# next time a species was added. Scrolling is the actual fix; row spacing
# is back to a comfortable, fixed size regardless of how many species exist.
WAVE_UNIT_ROWS_BOTTOM = ACTION_AREA_TOP - 10
WAVE_UNIT_ROW_HEIGHT = 32
WAVE_UNIT_STEP_BUTTON_SIZE = 24
WAVE_UNIT_SCROLL_STEP = WAVE_UNIT_ROW_HEIGHT  # one row per wheel click

WAVE_EDITOR_ACTION_LABELS = {
    "playtest": "Playtest",
    "save": "Save",
    "back": "Back to Path",
    "undo": "Undo",
    "redo": "Redo",
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
    return _key_of_rect_containing(pos, tab_rects)


def wave_unit_content_height(entry_count):
    """Total stacked height of `entry_count` rows -- unlike
    level_select_content_height, there's no separate inter-row gap constant
    to subtract a trailing copy of (WAVE_UNIT_ROW_HEIGHT already is each
    row's full stride)."""
    return entry_count * WAVE_UNIT_ROW_HEIGHT


def wave_unit_max_scroll(entry_count):
    """How far the list can scroll before its last row reaches the bottom
    of the viewport -- 0 once every registered species already fits without
    scrolling. Mirrors level_select_max_scroll exactly."""
    overflow = wave_unit_content_height(entry_count) - (WAVE_UNIT_ROWS_BOTTOM - WAVE_UNIT_ROWS_TOP)
    return max(0, overflow)


def build_wave_unit_rects(scroll_offset=0):
    """Two small +/- rects per registered enemy type (ENEMY_ORDER), stacked
    in the wave editor's sidebar and shifted up by `scroll_offset` pixels,
    keyed (enemy_name, "minus"/"plus"). A row scrolled above
    WAVE_UNIT_ROWS_TOP or below WAVE_UNIT_ROWS_BOTTOM still gets a real (if
    useless) Rect here -- callers doing hit-testing against a scrolled list
    should fence `pos` to that viewport themselves first, same as
    build_level_select_rects' own docstring requires of its callers; see
    Game._handle_wave_editor_click."""
    rects = {}
    minus_x = settings.PLAY_WIDTH + settings.PANEL_WIDTH - 2 * PANEL_PADDING - 2 * WAVE_UNIT_STEP_BUTTON_SIZE - 6
    plus_x = minus_x + WAVE_UNIT_STEP_BUTTON_SIZE + 6
    y = WAVE_UNIT_ROWS_TOP - scroll_offset
    for name in ENEMY_ORDER:
        rects[(name, "minus")] = pygame.Rect(minus_x, y, WAVE_UNIT_STEP_BUTTON_SIZE, WAVE_UNIT_STEP_BUTTON_SIZE)
        rects[(name, "plus")] = pygame.Rect(plus_x, y, WAVE_UNIT_STEP_BUTTON_SIZE, WAVE_UNIT_STEP_BUTTON_SIZE)
        y += WAVE_UNIT_ROW_HEIGHT
    return rects


def get_clicked_wave_unit_button(pos, unit_rects):
    """Return the (enemy_name, "minus"|"plus") key whose button contains
    pos, or None."""
    return _key_of_rect_containing(pos, unit_rects)


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
    return _key_of_rect_containing(pos, action_rects)


def draw_wave_editor_screen(surface, assets, font, small_font, editor, tab_rects, unit_rects,
                             action_rects, last_saved_path=None, scroll_offset=0):
    surface.fill(settings.COLOR_BG)
    # Read-only path preview, for context -- clicking a spawn marker in it
    # is exactly what changes which spawn's counts the sidebar below
    # shows/edits (see Game._handle_wave_editor_click).
    _draw_editor_grid(surface, assets, small_font, editor, active_spawn=editor.active_spawn_cell)
    _draw_wave_tabs(surface, small_font, editor, tab_rects)
    _draw_wave_editor_sidebar(
        surface, font, small_font, editor, unit_rects, action_rects, last_saved_path, scroll_offset,
    )


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


def _draw_wave_editor_sidebar(surface, font, small_font, editor, unit_rects, action_rects,
                               last_saved_path=None, scroll_offset=0):
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

    viewport = pygame.Rect(0, WAVE_UNIT_ROWS_TOP, settings.SCREEN_WIDTH, WAVE_UNIT_ROWS_BOTTOM - WAVE_UNIT_ROWS_TOP)
    previous_clip = surface.get_clip()
    surface.set_clip(viewport)

    y = WAVE_UNIT_ROWS_TOP - scroll_offset
    for name in ENEMY_ORDER:
        row_rect = pygame.Rect(x, y, settings.PANEL_WIDTH - 2 * PANEL_PADDING, WAVE_UNIT_ROW_HEIGHT)
        if row_rect.colliderect(viewport):
            count = composition.get(name, 0)
            label = small_font.render(f"{name.capitalize()}: {count}", True, settings.COLOR_TEXT)
            surface.blit(label, (x, y + 4))
            for suffix, symbol in (("minus", "-"), ("plus", "+")):
                rect = unit_rects[(name, suffix)]
                pygame.draw.rect(surface, settings.COLOR_BUTTON, rect, border_radius=4)
                sym_text = small_font.render(symbol, True, settings.COLOR_TEXT)
                surface.blit(sym_text, sym_text.get_rect(center=rect.center))
        y += WAVE_UNIT_ROW_HEIGHT

    surface.set_clip(previous_clip)

    max_scroll = wave_unit_max_scroll(len(ENEMY_ORDER))
    if max_scroll > 0:
        if scroll_offset > 0:
            more_above = small_font.render("^ more", True, settings.COLOR_TEXT_DIM)
            surface.blit(more_above, more_above.get_rect(midtop=(panel_rect.centerx, WAVE_UNIT_ROWS_TOP + 2)))
        if scroll_offset < max_scroll:
            more_below = small_font.render("v more -- scroll", True, settings.COLOR_TEXT_DIM)
            surface.blit(more_below, more_below.get_rect(midbottom=(panel_rect.centerx, WAVE_UNIT_ROWS_BOTTOM - 2)))

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
    return _key_of_rect_containing(pos, rects)


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
                              purpose="play", scroll_offset=0, endless_armed=False):
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
    a hint when there's more list than fits either direction.

    No row is ever locked -- purpose="play" always starts a level in
    Practice mode (see Game._enter_level_select's own docstring), so every
    row draws the same way regardless of progress.

    `endless_armed` (only meaningful for purpose="play" -- see
    Game._handle_keydown's `V` handling) shows a small hint that picking a
    level next starts it in Survival mode instead of normally. purpose="play"
    itself always starts a level in Practice mode (unlimited gold, no life
    loss -- see Game._handle_level_select_click), shown as a static notice
    rather than a toggle since it's no longer optional."""
    surface.fill(settings.COLOR_BG)
    title_text = "Load a Map to Edit" if purpose == "edit" else "Select a Level"
    title = font.render(title_text, True, settings.COLOR_TEXT)
    surface.blit(title, title.get_rect(midtop=(settings.SCREEN_WIDTH // 2, 30)))

    if purpose == "play":
        survival_text = f"[V] Survival: {'On' if endless_armed else 'Off'}"
        survival_color = settings.COLOR_BUTTON_SELECTED if endless_armed else settings.COLOR_TEXT_DIM
        survival_label = small_font.render(survival_text, True, survival_color)
        surface.blit(survival_label, survival_label.get_rect(midtop=(settings.SCREEN_WIDTH // 2, 60)))

        practice_label = small_font.render(
            "Practice Mode -- unlimited gold, no life loss", True, settings.COLOR_TEXT_DIM,
        )
        surface.blit(practice_label, practice_label.get_rect(midtop=(settings.SCREEN_WIDTH // 2, 80)))

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
