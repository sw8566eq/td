"""Swappable colors for everything that tells the player something through
color alone -- the Accessibility screen's "Colorblind palette" toggle.

One indirection, not scattered ifs: every gameplay-critical draw call reads
its color from `active()` (a `Palette`) instead of a `settings.COLOR_*`
constant, and `set_active(key)` swaps the whole set at once. The `"default"`
palette is built from those same `settings.COLOR_*` constants, so with the
toggle off every pixel is what it was before this module existed.

The `"colorblind"` palette is built on the Okabe-Ito set (blue/orange/
yellow/vermillion/reddish purple), chosen with a Machado et al. 2009
deuteranopia/protanopia simulation rather than by eye: the default map
nodes' closest simulated pair was Event vs Proving Grounds (27.5 apart) and
Outpost vs Treasure (35.8); every node pair here stays over 50 apart under
both simulations. See
docs/agents/presentation.md "Accessibility: palettes and reduced effects".

The active palette is module state, like `effects._text_cache`: entity
`draw()` methods have no `Game` to read a setting from. `Game` sets it once
at construction (from player settings) and again whenever the toggle flips.
Anything that caches pixels drawn with a palette color must put
`active_key()` (or the color itself) in its cache key.
"""

from dataclasses import dataclass, field

from support import settings

Color = tuple[int, int, int]


@dataclass(frozen=True)
class Palette:
    display_name: str
    # Placement footprint outline: buildable vs not.
    footprint_valid: Color
    footprint_invalid: Color
    # Lives text, a Mortar's dead-zone ring, the build menu's "blocked by a
    # Proving Grounds rule" strike-through, death poofs, damage numbers and
    # other "bad news" text.
    danger: Color
    # Enemy health bar (and a Barricade's bar background).
    hp_bar_bg: Color
    hp_bar_fill: Color
    # A Boss's damage-reduction (armor) ring vs its enrage ring.
    armor_ring: Color
    enrage_ring: Color
    # The sidebar's Proving Grounds status lines.
    challenge_status: Color
    # Run map node fills, keyed by node type, plus the unreachable fill.
    node_colors: dict[str, Color] = field(default_factory=dict)
    node_locked: Color = settings.COLOR_NODE_LOCKED


PALETTES: dict[str, Palette] = {
    "default": Palette(
        display_name="Default",
        footprint_valid=settings.COLOR_FOOTPRINT_VALID,
        footprint_invalid=settings.COLOR_FOOTPRINT_INVALID,
        danger=settings.COLOR_LIVES,
        hp_bar_bg=settings.COLOR_ENEMY_HP_BAR_BG,
        hp_bar_fill=settings.COLOR_ENEMY_HP_BAR_FILL,
        armor_ring=settings.COLOR_GOLD,
        enrage_ring=settings.COLOR_ENEMY_ENRAGE_RING,
        challenge_status=settings.COLOR_NODE_CHALLENGE,
        node_colors={
            "combat": settings.COLOR_NODE_COMBAT, "elite": settings.COLOR_NODE_ELITE,
            "shop": settings.COLOR_NODE_SHOP, "event": settings.COLOR_NODE_EVENT,
            "rest": settings.COLOR_NODE_REST, "treasure": settings.COLOR_NODE_TREASURE,
            "armory": settings.COLOR_NODE_ARMORY, "challenge": settings.COLOR_NODE_CHALLENGE,
            "boss": settings.COLOR_NODE_BOSS,
        },
        node_locked=settings.COLOR_NODE_LOCKED,
    ),
    "colorblind": Palette(
        display_name="Colorblind",
        footprint_valid=(86, 180, 233),     # Okabe-Ito sky blue
        footprint_invalid=(213, 94, 0),     # vermillion
        danger=(213, 94, 0),
        hp_bar_bg=(40, 40, 48),             # neutral dark, not a dark red
        hp_bar_fill=(240, 228, 66),         # yellow -- far from the blue shield bar too
        armor_ring=settings.COLOR_GOLD,
        enrage_ring=(204, 121, 167),        # reddish purple
        challenge_status=(230, 159, 0),     # orange
        node_colors={
            "combat": (213, 94, 0), "elite": (204, 121, 167),
            "shop": (0, 114, 178), "event": (240, 228, 66),
            "rest": (0, 158, 115), "treasure": (230, 159, 0),
            "armory": (86, 180, 233), "challenge": (235, 235, 235),
            "boss": (15, 15, 15),
        },
        node_locked=settings.COLOR_NODE_LOCKED,
    ),
}

DEFAULT_PALETTE = "default"
COLORBLIND_PALETTE = "colorblind"

_active_key = DEFAULT_PALETTE


def set_active(key: str) -> bool:
    """Make `key` the active palette. An unknown key (a hand-edited
    settings file) is ignored and returns False."""
    global _active_key
    if key not in PALETTES:
        return False
    _active_key = key
    return True


def active_key() -> str:
    return _active_key


def active() -> Palette:
    return PALETTES[_active_key]


def node_color(node_type: str) -> Color:
    return active().node_colors[node_type]


# Perceived-brightness cut-off above which a label drawn on a filled color
# switches from white to dark text, so a glyph stays readable on the
# colorblind palette's near-white and yellow nodes. No default node is
# this bright, so the default palette's labels are unchanged.
LIGHT_FILL_THRESHOLD = 200


def is_light(color: Color) -> bool:
    red, green, blue = color[:3]
    return 0.299 * red + 0.587 * green + 0.114 * blue > LIGHT_FILL_THRESHOLD
