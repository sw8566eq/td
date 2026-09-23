"""Persisted, player-rebindable key bindings -- but only for a curated
subset of actions, not every hardcoded pygame.K_* check in
input_handler.py. See CLAUDE.md's "Key bindings are curated, not
repo-wide" for the actual reasoning; the short version: several keys
(Escape, and the state-dependent meaning of R/P/S) already carry
different logical roles depending on game state, and untangling every one
of those into its own remappable action was explicitly scoped out in
favor of just the handful of actions a player would plausibly want to
rebind for ergonomics -- PLAYING's pause/skip-wave/time-scale/open-relics,
plus the map editor's undo/redo.

Mirrors player_settings.py's own JSON persistence shape closely: one
file, a defensive load falling back to DEFAULT_BINDINGS on a missing,
corrupt, or semantically-invalid file rather than crashing.
"""

import json

import pygame

from persistence.json_io import load_json_with_fallback, module_relative_path

SCHEMA_VERSION = 1
BINDINGS_PATH = module_relative_path(__file__, "keybindings.json")

# Two disjoint groups, each read from exactly one game state (PLAYING_
# ACTIONS from GameState.PLAYING, EDITOR_ACTIONS from EDITOR/WAVE_EDITOR --
# see input_handler.py's _handle_keydown) -- find_conflict() below only
# ever needs to check within one group, never across both, since two
# actions in different groups are never dispatched from the same keydown
# in the first place.
PLAYING_ACTIONS = ("pause", "skip_wave", "time_scale_1", "time_scale_2", "time_scale_3", "open_relics")
EDITOR_ACTIONS = ("editor_undo", "editor_redo")
ACTION_ORDER = (*PLAYING_ACTIONS, *EDITOR_ACTIONS)

ACTION_LABELS = {
    "pause": "Pause",
    "skip_wave": "Skip Wave / Start",
    "time_scale_1": "Time Scale x1",
    "time_scale_2": "Time Scale x2",
    "time_scale_3": "Time Scale x3",
    "open_relics": "Open Relics",
    "editor_undo": "Editor Undo",
    "editor_redo": "Editor Redo",
}

# Every binding is a (key, mods) pair -- mods is a bitmask of the
# KMOD_CTRL/KMOD_SHIFT/KMOD_ALT "family" bits (never a raw L/R-specific
# bit, see normalize_mods below) that must be held for the binding to
# match, or 0 if no modifier is required. This one shape is what lets
# editor_undo/editor_redo's Ctrl+Z/Ctrl+Y defaults round-trip through the
# exact same registry as every plain, unmodified action instead of
# needing a separate "combo" concept bolted on.
DEFAULT_BINDINGS = {
    "pause": (pygame.K_p, 0),
    "skip_wave": (pygame.K_SPACE, 0),
    "time_scale_1": (pygame.K_1, 0),
    "time_scale_2": (pygame.K_2, 0),
    "time_scale_3": (pygame.K_3, 0),
    "open_relics": (pygame.K_r, 0),
    "editor_undo": (pygame.K_z, pygame.KMOD_CTRL),
    "editor_redo": (pygame.K_y, pygame.KMOD_CTRL),
}

# Escape is never assignable to any action here -- it drives fixed back/
# cancel/quit navigation in every single game state (see
# input_handler.py's own _handle_keydown), so binding it to, say,
# skip_wave would make skip_wave unreachable (Escape's own hardcoded
# check runs first and always wins) without actually freeing Escape's own
# behavior -- a rebind that looks like it worked but silently doesn't.
RESERVED_KEYS = frozenset({pygame.K_ESCAPE})

# Pure modifier keys never complete a capture on their own -- pressing
# Ctrl while lining up a Ctrl+Z rebind fires a KEYDOWN for K_LCTRL first;
# the capture UI (input_handler.py's _handle_keybinds_keydown) waits for
# the *next* key instead of binding an action to "Ctrl" by itself.
MODIFIER_KEY_CODES = frozenset({
    pygame.K_LCTRL, pygame.K_RCTRL, pygame.K_LSHIFT, pygame.K_RSHIFT,
    pygame.K_LALT, pygame.K_RALT, pygame.K_LMETA, pygame.K_RMETA,
    pygame.K_LGUI, pygame.K_RGUI, pygame.K_MODE, pygame.K_NUMLOCK, pygame.K_CAPSLOCK,
})


def normalize_mods(raw_mods):
    """Collapse pygame.key.get_mods()'s left/right-specific bits (KMOD_
    LCTRL vs KMOD_RCTRL, ...) down to the three "family" bits this module
    stores and matches against -- so a binding captured with the right
    Ctrl held still matches a later press of the left Ctrl, and vice
    versa. Bitwise AND against the combined KMOD_CTRL/SHIFT/ALT constants
    already works for detection regardless of which side is held (each is
    itself defined as LEFT | RIGHT), but the *stored* value still needs
    to be one of these three canonical bits to compare equal to itself
    across two different physical keys."""
    normalized = 0
    if raw_mods & pygame.KMOD_CTRL:
        normalized |= pygame.KMOD_CTRL
    if raw_mods & pygame.KMOD_SHIFT:
        normalized |= pygame.KMOD_SHIFT
    if raw_mods & pygame.KMOD_ALT:
        normalized |= pygame.KMOD_ALT
    return normalized


def matches(binding, key, mods):
    """True if a live (key, mods) keydown satisfies `binding` (a (key,
    required_mods) pair from a bindings dict). A binding with no required
    modifier matches on the key alone, regardless of whatever else is
    incidentally held -- the same permissive behavior every one of these
    actions' hardcoded `pygame.K_*` checks already had before this
    module existed (e.g. Space triggering skip_delay() whether or not
    Shift happens to be down too). A binding that does require a modifier
    only needs those specific bits present, not an exact match -- mirrors
    the original `mods & pygame.KMOD_CTRL` check for Ctrl+Z/Ctrl+Y, which
    likewise never cared whether Shift was also held."""
    bound_key, required_mods = binding
    if key != bound_key:
        return False
    if required_mods:
        return (mods & required_mods) == required_mods
    return True


def group_of(action):
    return PLAYING_ACTIONS if action in PLAYING_ACTIONS else EDITOR_ACTIONS


def find_conflict(bindings, action, key, mods):
    """The other action already bound to the exact same (key, mods)
    within `action`'s own group (see PLAYING_ACTIONS/EDITOR_ACTIONS
    above), or None. Only ever checked within one group -- a same-key
    clash across groups can never actually collide at dispatch time,
    since the two groups are read from disjoint game states."""
    for other in group_of(action):
        if other != action and bindings[other] == (key, mods):
            return other
    return None


def is_reserved(key):
    return key in RESERVED_KEYS


def _coerce_binding(value, default):
    """A corrupt/hand-edited/missing entry (wrong shape, non-int members)
    falls back to that action's own default -- same defensive spirit as
    player_settings.py's own _coerce_window_size, just per-entry instead
    of for the whole file at once."""
    try:
        key, mods = int(value[0]), int(value[1])
        return (key, mods)
    except (TypeError, ValueError, IndexError, KeyError):
        return default


def _merge_with_defaults(data):
    raw_bindings = data.get("bindings", {})
    if not isinstance(raw_bindings, dict):
        raw_bindings = {}
    return {
        action: _coerce_binding(raw_bindings.get(action), default)
        for action, default in DEFAULT_BINDINGS.items()
    }


def load_bindings(path=BINDINGS_PATH):
    """The saved bindings dict ({action: (key, mods)}), or a fresh copy of
    DEFAULT_BINDINGS if the file doesn't exist yet or fails to parse."""
    return load_json_with_fallback(path, _merge_with_defaults, lambda: dict(DEFAULT_BINDINGS))


def save_bindings(bindings, path=BINDINGS_PATH):
    data = {
        "schema_version": SCHEMA_VERSION,
        "bindings": {action: list(binding) for action, binding in bindings.items()},
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
