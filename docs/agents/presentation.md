# Visual effects, audio, assets

The drain-a-per-frame-event-list idiom that keeps simulation code free of presentation, then audio
(`SoundManager`) and sprites (`AssetManager`).

## Visual effects: the drain-a-per-frame-event-list idiom

`entities/effects.py` holds small, short-lived, data-parametrized visual effects -- `FloatingText` (a
rising, fading damage-number popup) and `ExpandingRing` (a growing, fading ring, reused for both a
splash-blast flash and an enemy death poof via different constructor args, the same "one class,
several constructor-arg shapes" spirit as `Projectile` itself). Both are spawned via the same
idiom: the thing that actually causes the effect (`Enemy.damage_events`, a list of raw damage
amounts appended in `take_damage()` and cleared every frame; `Projectile.impact_events`, one
`(impact_pos, splash_radius_or_None)` tuple appended once per resolved hit in `_resolve_hit()`,
counted once per *projectile* the same way `shots_hit` already is) has zero knowledge of
`entities/effects.py` at all -- `Game.update()` is the one place that drains each per-frame list into an
owned, aged-and-pruned effect list (`self.damage_numbers`/`self.impact_effects`) every frame, in
each case *before* whatever produced the event (a dead enemy, a dead projectile) is actually
removed, so a killing blow's own popup/flash still spawns at the position it landed rather than
being silently dropped. Adding a new transient visual effect anywhere in this codebase means
following this same three-step shape: a class in `entities/effects.py`, a per-frame event list on whatever
produces the event, and one drain site in `Game.update()` -- never a new effect spawned directly
from inside `Enemy`/`Projectile`/`Tower`, which would couple simulation logic to rendering. The
idiom generalizes past rendering too: `SiphonTower.pending_siphon_gold` (see [towers.md](towers.md)
"Siphon Tower's damage-to-gold mechanic") is the same three-step shape applied to a real gameplay value instead of a visual
one -- a per-tower accumulator populated with zero knowledge of `Economy`, drained by `Game.update()`
into `self.economy.add_gold()` every frame.

## Audio

### `SoundManager`: logical names, files or synthesis

`presentation/audio.py` mirrors `presentation/assets.py` closely (read that module's own docstring first): every sound is
referenced elsewhere by a logical name (`"tower_placed"`, `"enemy_killed"`, ...), never a file
path. `SoundManager` (constructed once on `Game` as `self.audio`, right after `self.assets`,
reusing `assets.DEFAULT_ASSET_ROOT` directly rather than recomputing the same path a second way --
both modules' files live in the same directory, so it's the identical root) looks the name up in
`SOUND_MANIFEST` for a relative path under `assets/sfx/` plus a fallback synthesis recipe -- a
tuple of `SynthSpec` "notes" (waveform, an optional linear frequency sweep, a simple
attack/decay/sustain/release envelope) -- if the file exists it's loaded and decoded by SDL exactly
like a real sprite; otherwise it's synthesized in pure Python (`array`/`math`/`random`, no numpy)
into a raw PCM buffer handed to `pygame.mixer.Sound(buffer=...)`. This is audio's counterpart to
`AssetManager`'s colored-rect placeholders -- a deliberately "chiptune" aesthetic matching the
game's own placeholder-shape visual style, not an attempt at realism -- and the same "dropping a
real file in is a files-only change" precedent applies to `assets/sfx/`. Synthesized sounds are
cached per `SoundManager` instance for the process's own lifetime, never written to disk --
`assets/sfx/` stays empty except its own `.gitkeep` until a human drops real files in, exactly like
every other `assets/` subfolder. Like `AssetManager`, `get()` itself stays lazy (synthesizes/loads a
cue on its own first request), but `SoundManager.preload_all()` exists to pay every cue's one-time
synthesis cost up front instead, on demand -- a rare cue (`"boss_defeated"`, played once per run at
a dramatic moment) landing its own ~15-20ms of synthesis as a frame hitch on exactly the frame it
needs to play cleanly would be the worst possible time for that cost. `main.py` (a real launch
only) calls it once, right after constructing `Game()` and before `game.run()` starts the frame
loop, so play sees a warm cache before combat ever starts. It's deliberately *not* called from
`SoundManager.__init__`/`Game.__init__` themselves, though -- every test's own `Game()`/
`playing_game` fixture (and the `run-td` skill's own driver) also constructs a real `Game()`, many
times over, with no use for a warm cache; folding preloading into construction itself would make
every one of those pay the full ~100ms manifest-wide synthesis cost too, for no benefit any of them
can use -- measured to nearly triple the whole test suite's wall time for exactly that reason.

### Mixer format, missing devices and channel count

Unlike a placeholder `Surface`, a synthesized sound's raw bytes are coupled to the mixer's *actual*
initialized sample format -- `pygame.mixer.get_init()`'s own return (frequency/size/channels), not
necessarily what `Game.__init__` requested it with -- so `SoundManager` reads that back once at
construction and builds a matching encoder (bit depth, signedness, channel count) generically
rather than assuming one fixed shape (`audio._encoder_for`). An unrecognized format disables
*synthesis only*; a real on-disk file still plays regardless, since SDL decodes those independently
of anything this module builds by hand. `pygame.mixer.init()` itself is wrapped in a `try`/`except`
in `Game.__init__`, same "fall back gracefully rather than crash" spirit as `AssetManager`'s own
placeholder fallback -- a machine with genuinely no audio device (not even a dummy/null one
configured) leaves the game fully playable with sound silently, permanently disabled for that
session; `SoundManager` itself independently checks `pygame.mixer.get_init()` right after, so it
finds out the mixer never came up regardless of which branch ran, with no result needing to thread
through from `Game.__init__`. `SoundManager.__init__` also raises `pygame.mixer.set_num_channels()`
from SDL_mixer's default of 8 to `audio.NUM_CHANNELS` (32) itself, right there rather than at
whichever call site happens to construct it -- a busy board can have well over a dozen towers
firing, several projectiles resolving, and an enemy dying all in the same frame, and `Sound.play()`
simply drops a cue rather than stealing a channel once every one is already busy, so every
`SoundManager` gets this fix for free regardless of construction path (`Game.__init__`, a test, ...)
rather than needing each caller to remember the extra call.

### Which events play sounds

`Tower.FIRE_SOUND` (a single logical-name string, the same shape as `sprite_name`, not a registry
like `EXTRA_STATS`/`SPECIALIZATIONS`, since a tower only ever has one fire cue) names which cue a
tower's own shot plays; a couple of subclasses override the base class's generic default to group
towers into a few audibly distinct families rather than one bespoke sound per tower type
(`CannonTower`'s heavier thump, `LightningTower`'s zap) -- `SupportTower` sets it to `None`
(defense in depth; it never attacks at all, so it never reaches the code path below regardless).
`Tower.fired_this_frame` extends the *spirit* of the drain-a-per-frame-event-list idiom above to
sound, but as a plain bool rather than a list: set once per successful shot in `update()` (the
exact spot `shots_fired` increments), read and reset by `Game.update()`'s existing two-pass tower
loop into a `self.audio.play(tower.FIRE_SOUND)` call. A bool, not a list, because one `update()`
call can structurally fire at most once -- unlike `Enemy.damage_events`/`Projectile.impact_events`,
there's nothing here that could ever accumulate more than one same-frame entry to iterate, so a
list would only add an allocate/iterate/clear cost every frame for every tower with nothing to show
for it. Every other cue reuses an event list or call site this codebase already had for an
unrelated reason, rather than any new
plumbing into `Tower`/`Enemy`/`WaveManager` themselves (same "never call out to a presentation
concern from inside simulation code" rule the visual-effects idiom already establishes): enemy-hit
(small vs. splash, keyed off `splash_radius is not None`) and enemy-killed ride
`Projectile.impact_events`/the existing death-poof `ExpandingRing` spawn site; wave start is a new
before/after check on `WaveManager.state` transitioning into `SPAWNING`, mirroring the existing
`current_wave_number`/`authored_waves_cleared` before/after checks right next to it in
`Game.update()` (catches wave 1 via `skip_delay()`, every later authored wave, and every
endless-generated wave uniformly, since `_begin_wave()` is the only place that state is ever
entered); tower placed/upgraded/specialized/sold, floor cleared, boss defeated, game over/victory,
a Shop-purchased relic or plain tower unlock, and a Treasure/Random-Event-granted relic or tower
(the latter two resolved inside `events.resolve_event_option`, which can't call back into `Game` --
see its own docstring -- so `Game._resolve_event_choice` plays the matching cue itself, off that
function's own `{"relic": key}`/`{"tower": name}` return, rather than inheriting one from
`_grant_relic`/`_try_buy_shop_item` the way the Shop and Treasure paths do) all play from whichever
`Game`-level method already owned that event. Achievement/meta-progression unlocks share one cue
via `_queue_toast()`'s own single choke point, which also means a boss-defeat frame layers its own
dedicated fanfare underneath that same generic toast ding -- accepted as reasonable layering, not a
bug. Every failure path (an unaffordable purchase, an unbuildable placement, ...) stays exactly as
silent as it already was -- no new "denied" sound anywhere, mirroring each of those methods'
existing silent-no-op precedent.

### Sound settings

`GameState.SETTINGS`'s "Sound: On/Off" row is `self.sound_enabled`, persisted via
`persistence/player_settings.py` exactly like `fullscreen` (`Game.set_sound_enabled()` mirrors
`set_fullscreen()`'s own shape: mutate, apply -- `self.audio.set_enabled()` -- save). A "Volume: N%"
control sits inline on that same row (-/+ buttons, `SOUND_VOLUME_STEP`-sized 10% steps) --
`Game.adjust_sound_volume(direction)` calls `set_sound_volume()`, which clamps to `[0.0, 1.0]`,
applies it via `self.audio.set_volume()` (pushed onto every already-cached `Sound` immediately, and
to new ones as `get()` loads/synthesizes them), and persists it the same `_save_player_settings()`
way `set_fullscreen()`/`set_sound_enabled()` already do.

## Assets

Every sprite is referenced elsewhere by a logical name (`"tower_basic"`, `"enemy_grunt"`, ...),
never a file path. `AssetManager` (`presentation/assets.py`) looks the name up in `SPRITE_MANIFEST` for a
relative path + fallback color/shape; if the file exists under `asset_root` (default
`DEFAULT_ASSET_ROOT`, an `assets/` folder resolved relative to `presentation/assets.py`'s own location, not the
process's current working directory -- see [release.md](release.md) "Why `--onedir`, never `--onefile`" for why that distinction matters
for a packaged build) it loads and scales that, otherwise it synthesizes a placeholder (rounded
rect / circle with an outline at normal sizes, a plain flat fill below ~12px so tiny sprites like
the map's subtile mosaic don't collapse into a dot). Dropping in real art is a files-only change --
no code changes unless filenames differ from the manifest.

## Render caches

A few things drawn in large numbers every frame are cached. Each cache's key covers everything its
drawing reads, so a cache hit gives exactly the pixels a fresh draw would. `tests/test_render_caches.py`
compares the bytes, and `tools/perf_bench.py`'s `frame` hash checks a whole board (see
[tooling.md](tooling.md) "Performance bench (`tools/perf_bench.py`)").

- **Damage-number and toast text** (`effects._text_cache`): `FloatingText`'s rendered surface is keyed
  by `(font, text, color)` and shared between labels. Nothing invalidates an entry, because a label's
  text never changes. The surface is shared, so `draw()` sets its alpha right before each blit and
  nothing may draw onto it. The key holds the `Font` object itself, not `id(font)`, so a font from an
  earlier `Game` can't alias a new one. The whole cache is cleared once it reaches `_TEXT_CACHE_LIMIT`
  entries.
- **Impact rings** (`effects._ring_cache`): `ExpandingRing`'s per-frame ring surface is keyed by
  `(radius, width, color, alpha)`. Rings of one kind share a duration and frames share a dt, so keys
  recur. The cache is cleared at `_RING_CACHE_LIMIT`.
- **Coverage overlay** (`ui._coverage_overlay_cache`): the V overlay's full-screen ring layer is kept with
  its key: the target surface size plus every tower's `(center, int(effective_range()) or None,
  int(MIN_RANGE) or None)` in list order, plus `palette.active_key()` (the dead-zone ring uses the palette). The layer is redrawn when that key changes, which happens when a
  tower is placed, sold or moved, or an aura, relic or high-ground bonus changes a ring's integer radius.
  The resonance link lines are drawn on top every frame, uncached.
- **Dim overlays** (`ui._dim_overlay_cache`, older): the solid backdrop behind menus, keyed by size.

Colors in these keys must be hashable (tuples, as every `settings.COLOR_*` is). A `pygame.Color` would
raise.

## Accessibility: palettes and reduced effects

The Settings screen's "Accessibility..." button (right of the last Window row, above "Keybinds...")
opens `GameState.ACCESSIBILITY` (`ui.draw_accessibility_screen`; Esc or its Back button returns to
Settings). It has two toggles and a live preview drawn in the active palette.

**Colorblind palette.** `support/palette.py` holds a `PALETTES` registry of `Palette` dataclasses.
Each one names the colors that tell the player something on their own: placement footprint valid/
invalid, the `danger` color (lives text, a Mortar's dead-zone ring, the build menu's Proving Grounds
strike-through, death poofs, damage numbers, editor errors, the Game Over title), enemy health bar
fill/background, boss armor/enrage rings, the Proving Grounds status lines and every map node fill.
Draw code reads `palette.active()` (or `palette.node_color(node_type)`) instead of a
`settings.COLOR_*` constant. To add a palette, add one registry entry. To make another color
switchable, add a field and read it at draw time. Never branch on the palette key.

- `"default"` is built from the `settings.COLOR_*` constants, so with the toggle off every pixel is
  unchanged.
- `"colorblind"` uses the Okabe-Ito set: footprint sky blue (86, 180, 233) vs vermillion
  (213, 94, 0), danger vermillion, a yellow (240, 228, 66) health fill on a neutral dark background,
  a reddish-purple enrage ring, and one Okabe-Ito hue per map node. Proving Grounds is near-white and
  the boss near-black. The colors were picked with a Machado et al. 2009 deuteranopia/protanopia
  simulation. Under the default palette, Event vs Proving Grounds sat 27.5 apart and Outpost vs
  Treasure 35.8. Under this one, every node pair stays above 50 in both simulations.
- A label on a node fill that `palette.is_light()` reports as bright (perceived brightness above
  `LIGHT_FILL_THRESHOLD`) is drawn dark. No default node is that bright.

The active palette is module state, because entity `draw()` methods have no `Game`.
`SettingsManager.__init__` applies the saved key on every `Game()`, so tests can't leak a palette
into each other. The setting is `Game.palette`, persisted as the `"palette"` key in
`player_settings.json`. An unknown key falls back to `"default"`.

**Cache rule.** A render cache that holds palette-colored pixels must key on the color itself or on
`palette.active_key()`. `effects._text_cache` and `_ring_cache` already key on color. The coverage
overlay cache adds `palette.active_key()` to its key (see "Render caches"). A `FloatingText` resolves
its default color when it spawns, so a label already on screen keeps its color through a switch.

**Reduce effects** (`Game.reduce_effects`, persisted as `"reduce_effects"`): `Renderer` passes
`effects.REDUCED_EFFECTS_ALPHA` as the `alpha_scale` argument to every impact ring and damage number
`draw()`. Alpha is part of `_ring_cache`'s key, so dimmed and full rings never share a surface.
Toasts are drawn by their own loop and stay at full strength. The game has no screen shake or
full-screen flash, so dimming is the whole toggle.

**Larger UI text was not added.** Every screen in `presentation/ui.py` lays out against fixed pixel
constants sized for the current fonts, and many rows already fill their space at 1200x704. Bigger
fonts would need each screen's layout reworked and checked.
