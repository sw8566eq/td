# UI and input

## Key remapping is curated, not repo-wide

`persistence/keybindings.py` lets the player rebind a small, deliberately-chosen subset of actions --
`PLAYING_ACTIONS` (`pause`/`skip_wave`/`time_scale_1`/`time_scale_2`/`time_scale_3`/`open_relics`)
and `EDITOR_ACTIONS` (`editor_undo`/`editor_redo`) -- not every hardcoded `pygame.K_*` check
`core/input_handler.py`'s `_handle_keydown` makes. The reason it's a subset: several keys there already
carry *different logical meanings* depending on game state (`Escape` alone means quit, back,
cancel-a-pending-confirm, or resume depending on which state reads it; `R`/`P`/`S` each carry 2-3
meanings of their own), and a real remapping system would mean splitting each of those into
separate logical actions per state rather than one action per physical key -- scoped out in favor of
just the actions a player would plausibly want to rebind for ergonomics. `Escape` itself is never
remappable at all (`keybindings.RESERVED_KEYS`) -- it drives fixed back/cancel/quit navigation in
every single state, so assigning it to some other action would make that action unreachable (Escape's
own hardcoded check always runs first and wins) without actually freeing Escape's own behavior.

Every binding is a `(key, mods)` pair, `mods` a bitmask of only the three "family" bits
(`KMOD_CTRL`/`KMOD_SHIFT`/`KMOD_ALT`) a binding requires, 0 meaning "no modifier" -- one shape for
both a plain action and `editor_undo`/`editor_redo`'s Ctrl+Z/Ctrl+Y defaults, rather than a separate
"combo" concept bolted on. `keybindings.normalize_mods()` collapses `pygame.key.get_mods()`'s
left/right-specific bits down to those three canonical ones (so a binding captured with the right
Ctrl still matches a later press of the left Ctrl); `keybindings.matches(binding, key, mods)` is what
every dispatch site (`core/input_handler.py`'s `PLAYING`/`_handle_editor_undo_redo_keydown` branches) and
the capture UI both call, and mirrors each action's own pre-remapping behavior exactly: an
unmodified binding matches on the key alone regardless of whatever else is incidentally held (Space
still skips the wave delay whether or not Shift happens to be down too, same as before this module
existed), a modified one only needs its required bits present, not an exact match (same as the
original `mods & pygame.KMOD_CTRL` check for Ctrl+Z/Ctrl+Y).

`PLAYING_ACTIONS`/`EDITOR_ACTIONS` are two disjoint groups because they're read from two disjoint
game states (`PLAYING`, and `EDITOR`/`WAVE_EDITOR`) -- `keybindings.find_conflict()` (what
`Game.rebind_action()` calls before accepting a new binding) only ever checks for a clash within one
group, never across both, since two actions in different groups can never actually collide at
dispatch time regardless of whether they happen to share a key. `Game.rebind_action(action, key,
mods)` rejects (leaving the existing binding untouched, `self.keybind_message` set to say why) a
reserved key or an in-group conflict, same "click does nothing" precedent `try_place_tower`'s own
unbuildable-spot case sets -- except this one does set a message either way, since `GameState.
KEYBINDS` has nothing else on screen to explain *why* a click didn't do what was expected.

`PLAYING`'s own "pause" action needed one extra piece of symmetry beyond a plain dispatch-site swap:
`Escape`'s own fixed pause behavior stays completely separate from the "pause" *action* (Escape
always pauses regardless of what's bound), but the action itself is one *toggle* -- so
`core/input_handler.py`'s `PAUSED` branch checks the exact same `keybindings.matches(game.keybindings
["pause"], ...)` the `PLAYING` branch does for its own P-to-resume equivalent, not a second hardcoded
`pygame.K_p`. Get this wrong and rebinding "pause" away from P lets a player pause with their new key
but never un-pause with it (only the stale default P, or Escape, would still resume) -- a half-migrated
toggle. `ui.draw_pause_menu`'s own "Esc / P -- Resume" hint takes a `pause_key_label` param
(`ui.binding_display_string(game.keybindings["pause"])`, rendered fresh every frame) for the same
reason -- a hardcoded "P" in that hint would go stale the moment a player actually rebinds it.

`GameState.KEYBINDS` (reached via a "Keybinds..." button on the Settings screen, drawn to the right
of "Back to Menu" rather than as a 10th entry in `SETTINGS_OPTION_ORDER`'s own stacked column, which
would run past the bottom of the fixed 1200x704 canvas -- same "own small rect, not part of that
column" shape `build_volume_button_rects` already uses) is one row per `keybindings.ACTION_ORDER`
action, each a button showing its current binding; clicking one starts "listening"
(`Game.keybind_listening_for`), and the next keydown is captured as that action's new binding
(`core/input_handler.py`'s `_handle_keybinds_keydown`) -- a bare modifier keydown (`keybindings.
MODIFIER_KEY_CODES`) doesn't complete a capture on its own (waiting for the real key it's meant to
combine with), and Escape cancels the capture instead of ever being captured itself. A Reset button
restores `keybindings.DEFAULT_BINDINGS` wholesale. Persisted the same way as every other small
on-disk JSON state file (see that section below) -- `persistence/keybindings.py`'s own `load_bindings`/
`save_bindings`, injectable via `Game(keybindings_path=...)` exactly like `settings_path` etc., so
tests and the `run-td` skill's driver never touch the real repo-root `keybindings.json`.

## Stats panel subject resolution, and a click-routing gotcha

`Game._stats_panel_subject()` resolves what the sidebar shows, in priority order: the tower
currently under the mouse > a tower pinned open by clicking it (`self.selected_tower`, persists
after the mouse moves away) > the tower type currently selected to build > nothing. `render()` and
`_handle_click()` both call it, so the panel and its action buttons (Upgrade / two Specialize
choices / Sell, built by `ui.build_*_button_rect()`) always agree on which tower they act on.

Upgrade and the first Specialize button **intentionally share the same `Rect`** (`presentation/ui.py`,
`ACTION_AREA_TOP`) -- a tower is never both upgradeable and specializable at once, so they occupy
the same panel slot. `Game._handle_click` resolves a click there by the subject's *actual state*
(maxed or not), not by which `if` happens to run first -- get that backwards and a maxed tower's
click silently falls into `try_upgrade_tower` (a no-op once maxed) instead of specializing, which
is exactly the bug the regression tests around `ACTION_AREA_TOP`/`build_specialize_button_rects`
in `test_ui.py`/`test_game.py` exist to catch.

## HUD layout: top strip vs. bottom row

`presentation/ui.py`'s HUD bar splits into two vertical bands: a top strip (`HUD_TOP_STRIP_HEIGHT`, 32px) for
controls whose position shouldn't depend on how many tower buttons are registered (`build_speed_
button_rect`/`build_relics_button_rect`/`build_skip_button_rect`, all right-aligned there in that
order), and a bottom row for the tower build-menu buttons (left, `build_button_rects`) and the
Gold/Lives/Wave text (right, starting at `draw_hud`'s own `info_x`, which grows with however many
buttons are actually drawn). The wave-countdown caption and Skip/Start button used to live in the
*bottom* row instead, at a fixed position anchored to `settings.PLAY_WIDTH` regardless of the tower
count -- which meant they were on an unavoidable collision course with `info_x` once the roster grew
long enough, and a baseline screenshot of the pre-batch (10-tower) commit confirmed they already
*were* colliding there, unnoticed, before the relic-and-tower batch that added Overload Cannon/Siphon
Tower ever started. (Two of that batch's own sessions each independently shrank `BUTTON_SIZE` as an
honest, partial fix for a symptom they didn't know was a much older, structural bug.) Fixed by moving
the countdown caption and Skip/Start button into the top strip -- the countdown text now sits to the
button's *left* (`midright` anchor), not above it, since a top-strip button has no headroom above it
to float a caption over without spilling onto the grid -- which is what let the bottom row's
`BUTTON_SIZE`/`BUTTON_MARGIN` (44/8, sized against the 12-tower roster's own worst-case Gold/Lives/
Wave text width, e.g. `"Gold: unlimited   Shop: 999"`, with real headroom to spare) become the *only*
constraint on fitting the button row, rather than also needing to dodge a fixed-position control in
the same row. `test_ui.py`'s `test_hud_gold_lives_wave_text_fits_before_the_play_area_edge` is the
regression test for the actual constraint this fixes, checked against `TOWER_ORDER`'s full length --
distinct from the older, narrower `test_skip_button_does_not_overlap_the_tower_build_buttons`, which
only ever checked the skip button's own `Rect` against the button row's `Rect`s and would never have
caught text silently overflowing past both of them.

## Compendium

`GameState.COMPENDIUM` (`K` from MENU) lists every relic/boss relic/curse/potion/commander/elite affix.
`ui.compendium_rows(small_font)` builds `(kind, name, detail)` rows straight from the registries
(wrapping needs the live font, so `Game._enter_compendium` builds them on entry); it borrows the
Unlocks screen's layout constants, back button and `unlocks_max_scroll`, since it's the same shape
of scrolling list.
