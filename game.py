"""Game state machine and main loop."""

import dataclasses
import random
import sys
from enum import Enum, auto

import pygame

import achievements
import card_pool
import daily_challenge
import difficulty
import effects
import events
import meta_progression
import persistence
import player_settings
import progress
import relics
import run_escalation
import run_history
import run_map
import save_state
import settings
import shop
import ui
from assets import AssetManager
from economy import Economy
from editor import SHAPE_TOOLS, Editor, EditorTool
from grid import Grid
from levels import LEVELS
from run_state import RunState
from tower import TOWER_TYPES
from waves import WaveManager, WaveState

# Independently-derived rng streams within one roguelike run (see
# Game._run_rng) -- distinct string labels, folded into the seed string
# alongside run.seed and whatever key identifies what's being loaded (a
# node id for most of these -- see _run_rng's own docstring for why a node
# id, not a row number, is what keeps two sibling nodes in the same row
# from drawing identically), so no two of these ever collide. Not the
# multiply-and-add integer scheme this used before floors became nodes:
# seed * stream + key degenerates to just `key` for every stream whenever
# seed == 0 (start_new_run(seed=0) is reachable directly, and even an
# unseeded run has roughly a 1-in-4.3e9 chance of drawing it), silently
# collapsing every stream onto the same sequence. A string seed has no such
# degenerate case -- see _run_rng.
_FLOOR_RNG_STREAM = "floor"
_DRAFT_RNG_STREAM = "draft"
_EVENT_RNG_STREAM = "event"  # which Event a node shows -- keyed on the node's own id
_EVENT_ITEM_RNG_STREAM = "event-item"  # an Event option's own relic/tower grant -- keyed on (node id, option key)
_TREASURE_RNG_STREAM = "treasure"  # a Treasure node's guaranteed relic pick -- keyed on the node's own id


class GameState(Enum):
    MENU = auto()
    PLAYING = auto()
    PAUSED = auto()
    GAME_OVER = auto()
    VICTORY = auto()
    EDITOR = auto()
    WAVE_EDITOR = auto()
    LEVEL_SELECT = auto()
    SETTINGS = auto()
    ACHIEVEMENTS = auto()
    HELP = auto()
    CREDITS = auto()
    # A roguelike run's own extra states -- VICTORY stays reserved for
    # classic/Practice play and editor playtests (self.active_run is None
    # there), since a run structurally never "wins": FLOOR_CLEARED shows a
    # non-final floor's results (same board frozen behind it VICTORY/GAME_
    # OVER already do), MAP is the run's own branching map (see run_map.py/
    # Game._enter_map), and DRAFT/EVENT/REST/TREASURE are its four
    # non-combat node types (a Combat/Elite node is just PLAYING -- see
    # Game._enter_node).
    #
    # DRAFT is a naming fossil, kept deliberately: this state (and
    # _handle_draft_click/draft_choices/draft_choice_rects/ui.draw_draft_
    # screen alongside it) used to be a single free pick from exactly one
    # card type, entered automatically after every floor clear. It's now a
    # priced, multi-purchase Shop offering both tower and relic cards
    # together (see shop.py/CLAUDE.md's "Two currencies" section), only
    # entered when the player picks a Shop node on the map (see Game.
    # _enter_shop_node) -- but renaming this whole family of identifiers
    # would touch this module, ui.py, and every test that exercises the
    # shop screen for no functional gain, the same "not worth the blast
    # radius" call save_state.py's own "session" naming already documents
    # making. The prose everywhere below says "shop"; the code still says
    # "draft."
    #
    # MAP/DRAFT/EVENT/REST/TREASURE are all full-screen states (like
    # LEVEL_SELECT/EDITOR -- see render()'s early-return block), not
    # overlays drawn atop a frozen board the way PAUSED/GAME_OVER/VICTORY/
    # FLOOR_CLEARED are: MAP can be shown before any floor of the run has
    # ever loaded (right after start_new_run(), before self.grid/self.
    # economy exist at all), so there's structurally no board to freeze
    # behind it -- the other three are reached from MAP and follow the
    # same full-screen convention for consistency, even on the rare node
    # sequence where a board technically still exists from an earlier
    # floor.
    FLOOR_CLEARED = auto()
    DRAFT = auto()
    MAP = auto()
    EVENT = auto()
    REST = auto()
    TREASURE = auto()


class Game:
    # Simulation speed multipliers cycled through by the HUD's speed button
    # (or pressing 1/2/3 directly) -- see cycle_time_scale()/set_time_scale().
    TIME_SCALES = (1.0, 2.0, 3.0)

    def __init__(self, unlimited_gold=False, progress_path=None, settings_path=None,
                 achievements_path=None, save_path=None,
                 meta_progression_path=None, run_history_path=None):
        self.unlimited_gold = unlimited_gold  # debug flag -- see main.py --unlimited-gold
        # A sticky player preference for the whole session, not reset by
        # reset()/load_level() -- same idea as unlimited_gold not being tied
        # to any one level. Unlike fullscreen/difficulty below, this one is
        # deliberately NOT persisted across sessions.
        self.time_scale = 1.0

        # Injectable path, same idea as persistence.save_level's own
        # `directory` param -- lets tests point this at a tmp_path instead
        # of ever touching the real repo-root progress.json. Written by
        # _record_level_cleared() on every non-sandbox level/floor clear --
        # a run's own floor clear is the common case now, a classic/
        # Practice/playtest VICTORY the other. No in-memory cache of it is
        # kept on Game itself (unlike achievements_state/has_saved_run
        # below): nothing else on Game ever reads it back, Practice mode
        # least of all -- it no longer gates anything (see
        # _enter_level_select) -- so there's nothing for a cached copy to
        # go stale for.
        self.progress_path = progress_path or progress.PROGRESS_PATH

        # Same injectable-path convention as progress_path above.
        # achievements_state is re-read fresh whenever the Achievements
        # screen is (re-)entered (see _enter_achievements()), same "always
        # re-read" spirit persistence.list_custom_levels() follows for the
        # level browser's own custom-level listing.
        self.achievements_path = achievements_path or achievements.ACHIEVEMENTS_PATH
        self.achievements_state = achievements.load_achievements(self.achievements_path)
        self.achievements_back_rect = ui.build_achievements_back_rect()
        self.help_back_rect = ui.build_help_back_rect()
        self.credits_back_rect = ui.build_credits_back_rect()
        # Newly-unlocked-achievement toasts -- see _record_achievement().
        self.achievement_toasts = []

        # Same injectable-path convention as progress_path/achievements_path
        # above. True only between resume_saved_run() and that resumed
        # run's own eventual GAME_OVER/VICTORY (see update()'s win/loss
        # branches) -- what actually gates deleting the save file once it's
        # been played out, so a fresh, unrelated session's own victory can
        # never delete some other still-valid in-progress save. An explicit
        # parameter on _load_level_object() (default False) rather than set
        # after the fact -- resume_saved_run() is the one caller that
        # passes True; _load_combat_node() passes whatever this already
        # was, unaffected by its own node-to-node _load_level_object()
        # calls (see that method's own comment for why).
        self.save_path = save_path or save_state.SAVE_PATH
        self._resumed_from_save = False

        # Same injectable-path convention as the paths above. Neither needs
        # an eagerly-loaded cached copy on Game the way achievements_state
        # does -- there's no browse screen for either yet, only the read/
        # write call sites in _record_meta_progress/_advance_run_floor/
        # update()'s permadeath branch and card_pool.draft_offer's own
        # default pool, each of which reads fresh at the point it matters.
        self.meta_progression_path = meta_progression_path or meta_progression.META_PROGRESSION_PATH
        self.run_history_path = run_history_path or run_history.RUN_HISTORY_PATH
        # The active roguelike run, or None outside of one (classic/
        # Practice play, a map-editor playtest -- a Daily Run is still a
        # real run, see _start_daily_challenge). Same reset-inside-
        # _load_level_object shape as _resumed_from_save above --
        # _load_combat_node() is the one caller that sets it back
        # afterward, once per combat/elite node, so a run's own lives
        # survive across each floor's fresh _load_level_object() call.
        self.active_run = None
        # This shop visit's own offer (see _enter_shop_node) -- only
        # meaningful while self.state == GameState.DRAFT, rebuilt from
        # scratch every time that screen is (re-)entered, same "computed
        # fresh, not a persistent cache" spirit as level_select_entries.
        # draft_choices is a list of shop.ShopItem now (each carrying its
        # own kind -- "tower"/"relic" -- rather than one shared kind for the
        # whole screen, since a shop visit mixes both); draft_choice_rects
        # is one Rect per item, same length/order. shop_purchased_indices
        # tracks which of this visit's items are already bought (so a
        # second click on one is a no-op and price_for's escalation knows
        # how many purchases deep this visit is) -- reset every time
        # _enter_shop_node runs, same as the offer itself.
        self.draft_choices = []
        self.draft_choice_rects = []
        self.shop_purchased_indices = set()
        self.shop_continue_button_rect = ui.build_shop_continue_button_rect()

        # The run's own branching map screen (see run_map.py/_enter_map) --
        # rebuilt fresh every time that screen is (re-)entered, same
        # "computed fresh" spirit as draft_choices above (unlike level_
        # select_rects, a run's own map never scrolls -- see ui.py's own
        # layout comment -- so there's no separate _rebuild_map_rects
        # needed for a scroll event, just the one rebuild on entry).
        self.map_node_rects = {}
        # A Random Event node's own two-phase state (see _enter_event_node/
        # _handle_event_click): "choose" while the options are still on
        # offer, "resolved" once one's been picked -- current_event/
        # event_option_rects are only meaningful in the first phase,
        # event_chosen_option/event_resolution only in the second.
        self.current_event = None
        self.event_option_rects = []
        self.event_phase = "choose"
        self.event_chosen_option = None
        self.event_resolution = None
        # A Rest node's own result, for GameState.REST's static screen to
        # show -- set once, by _enter_rest_node, the instant the node
        # auto-resolves (there's no player choice to make on this screen,
        # unlike Event/Shop).
        self.rest_heal_amount = 0
        # A Treasure node's own result, for GameState.TREASURE's static
        # screen to show -- set once, by _enter_treasure_node, the instant
        # the node auto-resolves. treasure_granted_relic is None once every
        # relic is already held (see run_map.treasure_shop_currency_for_row's
        # own docstring) -- the currency half of a Treasure's reward never
        # degrades the same way.
        self.treasure_granted_relic = None
        self.treasure_granted_currency = 0
        # Cached rather than re-stat()'d on every render() frame while
        # sitting on the menu -- refreshed only at the 3 points that
        # actually change it: save_run(), resume_saved_run() (no change --
        # the file is still on disk until the run concludes), and
        # _delete_save_if_this_run_was_resumed().
        self.has_saved_run = save_state.has_saved_run(self.save_path)

        # Persisted player preferences -- fullscreen and difficulty were the
        # first genuinely cross-session prefs this game had (unlike
        # time_scale/unlimited_gold above), so they're written through
        # immediately on change rather than only on quit -- see
        # set_fullscreen()/set_difficulty()/set_window_size().
        self.settings_path = settings_path or player_settings.SETTINGS_PATH
        saved_settings = player_settings.load_settings(self.settings_path)
        self.fullscreen = saved_settings["fullscreen"]
        # Windowed size -- read here so the very first apply_display_mode()
        # call below already restores it (today's actual prior behavior:
        # dragging the window to a new size was never persisted across a
        # relaunch at all; see set_window_size()/the VIDEORESIZE handler
        # for how this now stays current, preset click or organic drag
        # alike). Meaningless while fullscreen, same as a drag already
        # being ignored there -- see apply_display_mode's own docstring.
        self.window_size = tuple(saved_settings["window_size"])
        # Which difficulty.DIFFICULTY_MODES entry is currently active --
        # read at _load_level_object time, so changing it mid-level has no
        # effect until the next load_level()/reset() (same "applies on next
        # load" semantics unlimited_gold already has).
        self.difficulty = saved_settings["difficulty"]
        if self.difficulty not in difficulty.DIFFICULTY_MODES:
            self.difficulty = difficulty.DEFAULT_DIFFICULTY

        pygame.init()
        self.apply_display_mode()
        pygame.display.set_caption(settings.WINDOW_TITLE)
        self.clock = pygame.time.Clock()

        self.font = pygame.font.SysFont(None, 32)
        self.small_font = pygame.font.SysFont(None, 22)
        self.tiny_font = pygame.font.SysFont(None, 16)  # tower upgrade badges

        self.assets = AssetManager()
        self.settings_rects = ui.build_settings_rects()
        self.button_rects = ui.build_button_rects()
        self.skip_button_rect = ui.build_skip_button_rect()
        self.speed_button_rect = ui.build_speed_button_rect()
        self.targeting_button_rect = ui.build_targeting_button_rect()
        self.upgrade_button_rect = ui.build_upgrade_button_rect()
        self.specialize_button_rects = ui.build_specialize_button_rects()
        self.sell_button_rect = ui.build_sell_button_rect()

        # The editor instance persists for the whole session (not just
        # while GameState.EDITOR/WAVE_EDITOR is active) so leaving it to
        # playtest and coming back preserves whatever's been painted/
        # configured so far.
        self.editor = Editor()
        self.editor_tool_rects = ui.build_editor_tool_rects()
        self.editor_action_rects = ui.build_editor_action_rects()
        # Set by the wave editor's Save action -- shown in its sidebar so
        # the player knows where the file landed (custom_levels/), e.g. to
        # go find and share it with someone else.
        self.last_saved_path = None
        # Set by the path editor's Import Level... action (see
        # _import_level_from_path()) -- shown in its own sidebar the same
        # spirit as last_saved_path above, just success/failure instead of
        # always-success.
        self.import_status_message = None
        self.import_status_is_error = False
        # Unlike the rect sets above, wave tabs depend on how many waves
        # currently exist, so they're rebuilt on demand (see
        # _wave_tab_rects()) rather than cached once here. wave_unit_rects
        # also gets rebuilt on scroll (see _scroll_wave_unit_list) -- same
        # "row positions depend on scroll_offset too" shape as
        # level_select_rects below, since ENEMY_ORDER can outgrow the
        # sidebar's fixed vertical budget.
        self.wave_unit_scroll_offset = 0
        self._rebuild_wave_unit_rects()
        self.wave_editor_action_rects = ui.build_wave_editor_action_rects()

        # Rebuilt each time _enter_level_select() runs -- see there for why
        # (the custom-levels list on disk can change between visits).
        # level_select_rects also gets rebuilt on scroll (see
        # _scroll_level_select) -- unlike every other cached rect set in
        # Game, its row positions depend on scroll_offset, not just on
        # what's currently listed.
        self.level_select_entries = []
        self.level_select_rects = {}
        self.level_select_thumbnails = {}
        self.level_select_purpose = "play"  # or "edit" -- see _enter_level_select
        self.level_select_scroll_offset = 0
        # Toggled by V while browsing to play (not edit); a level picked
        # while armed loads in endless/survival mode -- see
        # _handle_level_select_click. Reset to False every time the
        # browser is (re-)entered, same as scroll_offset. Sandbox itself is
        # no longer a separate toggle here -- purpose="play" always loads a
        # level in Practice/sandbox mode (see _handle_level_select_click),
        # so it's always on and combinable with Survival for free.
        self.level_select_endless_armed = False
        self._custom_levels_by_id = {}

        # Gates R's actual reset() call behind one extra confirming press
        # while PAUSED -- an in-progress run/Practice/playtest floor is
        # genuinely losable state, unlike GAME_OVER/VICTORY's own R (see
        # _handle_keydown's PAUSED branch), so only PAUSED needs this. Only
        # ever set True from inside that same PAUSED branch, and always
        # cleared again by the very next R (confirms, also resets state to
        # PLAYING) or Escape (cancels) before PAUSED can be left any other
        # way -- so, unlike GameState.EVENT's own event_phase, there's no
        # stale-leftover-value case to guard against on (re-)entry.
        self.pause_restart_confirm_pending = False

        self.state = GameState.MENU
        self.running = True

        self.current_level_id = 1
        self.load_level(self.current_level_id)

    def load_level(self, level_id, endless=False, sandbox=False):
        self._load_level_object(LEVELS[level_id], endless=endless, sandbox=sandbox)
        self.current_level_id = level_id

    def load_custom_level(self, level, endless=False, sandbox=False):
        """Load a Level that isn't in the LEVELS registry -- an
        editor-authored level, whether freshly painted or reloaded from
        disk (see persistence.py). current_level_id becomes None so
        has_next_level()/advance_or_replay_level() know there's no
        registry entry to advance through."""
        self._load_level_object(level, endless=endless, sandbox=sandbox)
        self.current_level_id = None

    def _active_tower_names(self):
        """Which TOWER_TYPES names the build menu should currently offer --
        a run's own drafted pool while one is active (a Daily Run is still
        a real run, see _start_daily_challenge), every registered tower
        otherwise (classic/Practice play, a map-editor playtest)."""
        return self.active_run.unlocked_towers if self.active_run is not None else ui.TOWER_ORDER

    def _rebuild_button_rects(self):
        """Rebuilds self.button_rects off _active_tower_names() -- same
        "rebuilt on demand when the underlying data changes" precedent
        level_select_rects/wave_unit_rects already establish, rather than a
        one-time __init__ cache. _load_level_object() itself calls this
        unconditionally right after setting self.active_run (see its own
        `active_run` parameter) -- correct for every loader that funnels
        through it, whether that's None (load_level/load_custom_level,
        reset()/advance_or_replay_level()'s own direct calls for a
        custom/playtested level, never part of a run) or a real RunState
        (_load_combat_node/resume_saved_run, which both pass their run
        straight through instead of restoring it and calling this a second
        time)."""
        self.button_rects = ui.build_button_rects(self._active_tower_names())

    def start_new_run(self, seed=None, is_daily=False):
        """Start a new roguelike run: a full branching map generated once
        (run_map.generate_run_map), a starter tower pool (card_pool.
        STARTER_TOWERS), and no current node yet -- the player's first act
        is picking one of the map's row-0 nodes (see _enter_map/_enter_
        node), not an automatic floor 0 load the way a flat floor_sequence
        used to allow. `seed` is overridable (_start_daily_challenge passes
        one derived from today's date; tests want determinism).

        `is_daily` pins the run's own difficulty to "normal" rather than
        snapshotting the player's own live sticky preference, so every
        player's Daily Run score is comparable regardless of their own
        difficulty setting -- the same fairness _start_daily_challenge
        already guaranteed back when it built a Daily Challenge by calling
        _load_level_object(..., difficulty_override="normal") directly,
        now snapshotted onto the run itself instead (same "snapshot once
        at start, don't re-read the live preference mid-run" precedent
        save_state.py's own resumed-run difficulty already follows).

        Explicitly resets _resumed_from_save -- unlike every other
        _load_level_object() call this run will ever make (all routed
        through _load_combat_node(), which deliberately preserves this flag
        across its own calls, see that method's own comment), starting a
        brand new run here genuinely is the "unrelated fresh session"
        case _load_level_object()'s own reset exists for, whether or not a
        previously-resumed run is still technically active_run at this
        exact moment (e.g. saved-and-returned-to-menu, then started a
        different run without ever concluding the resumed one) -- that
        older run's own save file must stay resumable, not get deleted
        out from under it by this new, unrelated run's own eventual
        conclusion."""
        self._resumed_from_save = False
        seed = seed if seed is not None else random.Random().getrandbits(32)
        self.active_run = RunState(
            seed=seed, map=run_map.generate_run_map(random.Random(seed)),
            difficulty="normal" if is_daily else self.difficulty,
            unlocked_towers=list(card_pool.STARTER_TOWERS), is_daily=is_daily,
        )
        self._enter_map()

    def _floor_load_context(self, run, node):
        """The (relic_modifiers, escalation, rng) triple _load_level_object()
        needs to load `node` (a combat/elite MapNode) of `run` -- shared by
        _load_combat_node() (a normal node transition, or a mid-run restart
        of the current node -- see reset()) and resume_saved_run() (which
        needs the identical derivation for whatever node the resumed run
        was already on), so the two don't independently re-derive the same
        three values and risk drifting apart if a future change alters
        what a node-load needs derived from a RunState. escalation is
        keyed on the node's row (the depth value a branching map's
        escalation math uses -- see RunState.current_row), bumped further
        by run_escalation.apply_elite_multiplier for an Elite node."""
        escalation = run_escalation.escalation_for_floor(node.row)
        if node.node_type == "elite":
            escalation = run_escalation.apply_elite_multiplier(escalation)
        return (
            relics.compose_relic_modifiers(run.relics, node.row, run.has_spent_gold),
            escalation,
            self._run_rng(run, _FLOOR_RNG_STREAM, node.id),
        )

    def _run_rng(self, run, stream, key):
        # A node's own routing rng, that node's own shop offer, an Event's
        # own pick/item-grant, and a Treasure's own relic pick are all
        # deterministically re-derived from (run.seed, key) rather than
        # carried as one continuously-consumed random.Random across the
        # run, so resuming a saved run needs no RNG state serialized at all
        # -- just re-derive the same object the same way on load (see
        # resume_saved_run(), the other caller that needs this before
        # self.active_run is even set, which is why `run` is taken as a
        # parameter here instead of read off self.active_run). `stream`
        # (one of the _*_RNG_STREAM string constants above) keeps the
        # several derived streams from colliding despite often being seeded
        # off the same (seed, key) pair. `key` is a node's own id (a
        # string, unique within the run's map) for everything but a Shop's
        # per-visit offer and an Event option's own item grant, which fold
        # in one further piece of identity (see _enter_shop_node/
        # _resolve_event_choice) -- critically, this must never be a bare
        # row number: two sibling nodes in the same row would otherwise
        # derive byte-identical rng, silently defeating branching (both
        # forks of a choice would route/offer identically).
        return random.Random(f"{run.seed}:{stream}:{key}")

    def _load_combat_node(self, node):
        """Load `node` (a Combat/Elite MapNode) of self.active_run. Resets
        everything via _load_level_object exactly like any other level
        load -- towers, the grid, and wave state are always rebuilt fresh
        per floor, the same way a deckbuilder run doesn't carry board
        state between combats. Only the run's own lives carry across node
        loads (the run's very first resolved node is the one exception:
        RunState starts with lives=0 as a placeholder, captured for real
        from that node's own freshly-loaded Economy just below -- the same
        starting_lives every other level load already uses, just also
        saved off for every later node to carry forward). Battle gold is
        never carried -- every node's Economy gets a fresh starting_gold
        via _load_level_object's own construction (relic-adjustable via
        starting_gold_multiplier the same as any other floor), same as if
        this were the very first floor of the run every time; see
        CLAUDE.md's "Two currencies" section for why. The map's boss node
        (the only node in its final row) always loads endless=True (see
        WaveManager's own endless tail) -- a run only ever ends by
        permadeath, never by "finishing" the boss floor; see update()'s
        win-check for the other half of that.

        `run` is passed straight through to _load_level_object()'s own
        `active_run` parameter -- see its docstring for why that already
        builds the correct, run-narrowed button menu in its one
        _rebuild_button_rects() call, with nothing left for this method to
        restore or rebuild itself afterward.

        Also doubles as the restart path for the current node of an active
        run (see reset()) -- called again with the same node it's already
        on, which is exactly "reload this floor from scratch" since
        run.lives (what a non-first node restores from) doesn't change
        again until either this floor actually clears (see
        _advance_run_floor) or its own next shop visit picks a one-time
        relic bonus (_apply_one_time_relic_bonus) -- neither reachable
        mid-floor.

        _resumed_from_save is passed straight through as-is (see
        _load_level_object's own `resumed_from_save` parameter) -- unlike
        start_new_run(), which explicitly resets it since starting a
        brand new run always is the "unrelated fresh session" case that
        flag exists to catch, this method is never that: it always
        continues whatever run is already active, resumed or not, so
        whatever this flag already was stays exactly as it was.

        Assumes run.current_node_id is already set to node.id (see
        _enter_node, which sets it before dispatching here; reset()'s own
        restart path leaves it untouched since it's already correct)."""
        run = self.active_run
        relic_modifiers, escalation, rng = self._floor_load_context(run, node)
        self._load_level_object(
            LEVELS[node.level_id], endless=run.is_final_floor,
            difficulty_override=run.difficulty, rng=rng, escalation=escalation, relic_modifiers=relic_modifiers,
            active_run=run, resumed_from_save=self._resumed_from_save,
        )
        self.current_level_id = node.level_id
        if not run.visited_node_ids:
            run.lives = self.economy.lives
        else:
            self.economy.lives = run.lives
        # gold_per_floor_bonus is meant to apply on top of every floor's
        # freshly-constructed starting gold -- added here rather than
        # folded into _load_level_object's own Economy construction, since
        # it's a flat bonus, not part of the starting-gold formula itself
        # (see relic_modifiers.starting_gold_multiplier, which IS folded in
        # there instead). Unlike gold itself, there's no "first node"
        # special case left to worry about here now that gold never
        # carries forward -- every floor gets this bonus exactly once, the
        # instant it loads.
        self.economy.add_gold(relic_modifiers.gold_per_floor_bonus)
        self.state = GameState.PLAYING

    def _advance_run_floor(self):
        """One combat/elite node of self.active_run just cleared (see
        update()'s win-check) -- carry lives forward, mark the node
        visited, convert this floor's own leftover battle gold into shop
        currency (see shop.income_for_floor; battle gold itself is never
        carried, see _load_combat_node), and show the floor-cleared results
        screen. self.towers/self.economy are still this just-cleared
        floor's own live state at this point (the map isn't shown again
        until the player leaves this results screen -- see _enter_map),
        so _tower_results() still has something real to show, and self.
        economy.gold here is genuinely this floor's own final leftover
        amount, not yet reset for the next one."""
        run = self.active_run
        node = run.map.node(run.current_node_id)
        run.lives = self.economy.lives
        run.visited_node_ids.append(node.id)
        run.shop_currency += shop.income_for_floor(
            node.row, self.economy.gold, is_elite=node.node_type == "elite",
        )
        self._record_meta_progress("total_floors_cleared")
        self._cache_tower_results()
        self.state = GameState.FLOOR_CLEARED

    def _record_run_permadeath(self):
        """self.active_run just ended by permadeath -- the only way a run
        ever ends (the map's boss node always loads endless=True, so
        all_waves_complete structurally can't fire for it either -- see
        _load_combat_node's docstring). Same shape as _advance_run_floor: one
        helper update()'s win/loss branches each delegate a run-specific
        multi-step side effect to, rather than growing update() itself.
        floors_cleared doubles as the run's own score, a simple,
        monotonic count -- a Daily Run needs no special handling here
        either, it's just self.active_run with is_daily set.

        Sandbox-gated up front, same as every other real-progress recorder
        in this codebase (_record_achievement/_record_meta_progress/
        _record_level_cleared) -- no normal UI path can currently combine
        an active run with sandbox=True (Practice never starts a run, and
        start_new_run never sets sandbox), but resume_saved_run() restores
        both fields independently off a save file with nothing enforcing
        that they can't both be set, so this stays consistent with its
        siblings rather than silently recording a trivialized run's
        outcome if that combination is ever reachable."""
        if self.sandbox:
            return
        run_history.record_run_result(self.active_run.seed, self.active_run.floors_cleared, self.run_history_path)
        self._record_meta_progress("runs_played")
        if self.active_run.is_final_floor:
            self._record_meta_progress("runs_reached_endless")

    # --- The run's own branching map ---

    def _enter_map(self):
        """(Re-)enter the run's branching map screen -- called once from
        start_new_run() (before any node has ever been picked) and again
        from _finish_node() every time a node's own resolution completes.
        Rebuilds map_node_rects fresh every time, same "computed fresh, not
        a persistent cache" spirit as draft_choices -- there's nothing
        about the map's own layout that ever changes mid-run (unlike
        level_select_rects, this never needs a separate rebuild-on-scroll
        step; see ui.py's own layout comment for why this screen never
        scrolls)."""
        self.map_node_rects = ui.build_map_node_rects(self.active_run.map)
        self.state = GameState.MAP

    def _available_node_ids(self):
        """Which node ids the player can currently click into from the map
        screen -- the map's own row-0 nodes if nothing's been picked yet,
        else whatever the current node's own edges point to. The single
        source of truth both _handle_map_click's legality check and ui.
        draw_map_screen's "available" visual state read from, so the two
        can't drift on what's actually clickable."""
        run = self.active_run
        if run.current_node_id is None:
            return run.map.start_node_ids
        return run.map.edges.get(run.current_node_id, ())

    def _handle_map_click(self, pos):
        """A click on the map screen -- a silent no-op if it didn't land on
        a currently-available node, same "click does nothing" precedent
        try_place_tower's own unbuildable-spot case already sets."""
        node_id = ui.get_clicked_map_node(pos, self.map_node_rects)
        if node_id is None or node_id not in self._available_node_ids():
            return
        self._enter_node(node_id)

    def _enter_node(self, node_id):
        """Commit to `node_id` as the run's new current node and dispatch
        to whichever node type it is. Sets run.current_node_id before
        dispatching -- every _enter_*_node method below (and _load_combat_
        node, via _floor_load_context/RunState.current_row) reads it
        already set, rather than each one setting it independently."""
        run = self.active_run
        run.current_node_id = node_id
        node = run.map.node(node_id)
        if node.node_type in ("combat", "elite"):
            self._load_combat_node(node)
        elif node.node_type == "shop":
            self._enter_shop_node(node)
        elif node.node_type == "event":
            self._enter_event_node(node)
        elif node.node_type == "rest":
            self._enter_rest_node(node)
        elif node.node_type == "treasure":
            self._enter_treasure_node(node)

    def _finish_node(self, node_id):
        """Shared terminal step for every non-combat node's own resolution
        (Shop's Continue button, an Event's chosen option, Rest/Treasure's
        auto-resolve) -- mark it visited and return to the map. A combat/
        elite node's own clear already appends its own id in
        _advance_run_floor, so this is never called for those (there's no
        separate "leave the results screen" step distinct from pressing
        any key on FLOOR_CLEARED, which goes straight to _enter_map)."""
        self.active_run.visited_node_ids.append(node_id)
        self._enter_map()

    def _enter_shop_node(self, node):
        """Enter the Shop screen for `node` (see GameState.DRAFT's own
        naming note for why the code still says "draft") -- computes this
        visit's offer (both tower and relic cards together, see shop.
        build_offer) and switches to GameState.DRAFT. Resolves the node
        immediately, with no shop at all, only if that offer comes back
        completely empty (both pools exhausted -- every tower unlocked and
        every relic held), same as the old draft screen's own empty-offer
        skip."""
        run = self.active_run
        rng = self._run_rng(run, _DRAFT_RNG_STREAM, node.id)
        self.draft_choices = shop.build_offer(rng, run, meta_progression_path=self.meta_progression_path)
        if not self.draft_choices:
            self._finish_node(node.id)
            return
        self.draft_choice_rects = ui.build_draft_choice_rects(len(self.draft_choices))
        self.shop_purchased_indices = set()
        self.state = GameState.DRAFT

    def _handle_draft_click(self, pos):
        """A click anywhere on the Shop screen -- either the Continue
        button (leave the shop and return to the map, buying nothing else)
        or one of this visit's item cards (attempt to buy it)."""
        if self.shop_continue_button_rect.collidepoint(pos):
            self._finish_node(self.active_run.current_node_id)
            return
        index = ui.get_clicked_draft_choice(pos, self.draft_choice_rects)
        if index is None or index in self.shop_purchased_indices:
            return
        self._try_buy_shop_item(index)

    def _try_buy_shop_item(self, index):
        """Attempt to buy this visit's item at `index` -- a silent no-op if
        it's unaffordable, same "click does nothing" precedent try_place_
        tower's own unbuildable-spot case already sets, rather than a
        rejection the player has to notice and dismiss. Price escalates
        with how many items this same visit has already bought (see shop.
        price_for) -- self.unlimited_gold/sandbox's own "every purchase
        always succeeds, nothing actually deducted" precedent (see
        economy.py's own docstring) covers shop currency the same way it
        already covers battle gold, via self.economy.unlimited_gold, which
        is already exactly `self.unlimited_gold or sandbox`. Routed through
        shop.can_afford (the same check ui.draw_draft_screen renders a card
        as affordable with) rather than reimplementing it here, so the two
        can't drift."""
        run = self.active_run
        item = self.draft_choices[index]
        price = shop.price_for(item, len(self.shop_purchased_indices))
        unlimited = self.economy.unlimited_gold
        if not shop.can_afford(run.shop_currency, price, unlimited):
            return
        if not unlimited:
            run.shop_currency -= price
        if item.kind == "relic":
            self._grant_relic(item.key)
        else:
            run.unlocked_towers.append(item.key)
        self.shop_purchased_indices.add(index)

    def _grant_relic(self, relic_key):
        """Add `relic_key` to the active run's relics and apply its
        one-time bonus, if it has one (see _apply_one_time_relic_bonus) --
        the one choke point every relic-granting path (a Shop purchase, a
        Treasure node's guaranteed pick) routes through, so a future
        relic-granting path can't forget the one-time half of this
        pairing. events.resolve_event_option grants its own Random Event
        relics independently (see that function's own comment for why it
        can't call back into Game)."""
        self.active_run.relics.append(relic_key)
        self._apply_one_time_relic_bonus(relics.RELICS[relic_key])

    def _enter_event_node(self, node):
        """Enter the Random Event screen for `node` -- picks one Event
        (see events.pick_event) deterministically from this node's own id,
        so the same seed always shows the same event at the same node."""
        run = self.active_run
        rng = self._run_rng(run, _EVENT_RNG_STREAM, node.id)
        self.current_event = events.pick_event(rng)
        self.event_option_rects = ui.build_event_option_rects(len(self.current_event.options))
        self.event_phase = "choose"
        self.event_chosen_option = None
        self.event_resolution = None
        self.state = GameState.EVENT

    def _handle_event_click(self, pos):
        """A click on the Event screen -- in the "resolved" phase (an
        option's already been picked), any click moves on, same "press any
        key to continue" spirit FLOOR_CLEARED's own keydown handling uses;
        otherwise resolves whichever option (if any) was clicked."""
        if self.event_phase == "resolved":
            self._finish_node(self.active_run.current_node_id)
            return
        index = ui.get_clicked_event_option(pos, self.event_option_rects)
        if index is None:
            return
        self._resolve_event_choice(index)

    def _resolve_event_choice(self, index):
        run = self.active_run
        node_id = run.current_node_id
        option = self.current_event.options[index]
        # Keyed on the option actually chosen (not the event itself, and
        # not just the node) -- see events.resolve_event_option's own
        # docstring for why only the branch actually taken needs to be
        # reproducible.
        item_rng = self._run_rng(run, _EVENT_ITEM_RNG_STREAM, f"{node_id}:{option.key}")
        self.event_resolution = events.resolve_event_option(
            run, option, item_rng, meta_progression_path=self.meta_progression_path,
        )
        self.event_chosen_option = option
        self.event_phase = "resolved"

    def _enter_rest_node(self, node):
        """A Rest node auto-resolves the instant it's entered -- no player
        choice to make, unlike Shop/Event -- healing run.lives by run_map.
        heal_amount_for_row(node.row) and showing a static confirmation
        screen (see ui.draw_rest_screen)."""
        heal = run_map.heal_amount_for_row(node.row)
        self.active_run.lives += heal
        self.rest_heal_amount = heal
        self.state = GameState.REST

    def _enter_treasure_node(self, node):
        """A Treasure node auto-resolves the instant it's entered -- a
        guaranteed shop-currency payout (run_map.treasure_shop_currency_
        for_row) plus one guaranteed relic pick, degrading gracefully to
        currency-only once every relic is already held (relics.
        relic_offer's own empty-once-exhausted precedent, same as a Shop
        offer can run dry -- see _enter_shop_node)."""
        run = self.active_run
        currency = run_map.treasure_shop_currency_for_row(node.row)
        run.shop_currency += currency
        self.treasure_granted_currency = currency
        rng = self._run_rng(run, _TREASURE_RNG_STREAM, node.id)
        picks = relics.relic_offer(rng, run, count=1)
        self.treasure_granted_relic = picks[0] if picks else None
        if picks:
            self._grant_relic(picks[0])
        self.state = GameState.TREASURE

    def _scaled_starting_gold(self, level, mode, extra_multiplier=1.0):
        """`level.starting_gold` scaled by `mode.starting_gold_multiplier`
        and `extra_multiplier` (a relic's own starting_gold_multiplier, see
        RelicModifiers) -- the exact formula _load_level_object() uses to
        construct every floor's own fresh starting Economy.
        `extra_multiplier` is folded into the same single `round()` call
        rather than applied as a separate step afterward, so the result
        matches what a single combined multiplier would have rounded to,
        not round(round(x) * y) double-rounding to a different result."""
        return round(level.starting_gold * mode.starting_gold_multiplier * extra_multiplier)

    def _apply_one_time_relic_bonus(self, relic):
        """Sturdy Gate (relics.py's own RelicModifiers docstring for the
        full reasoning) can structurally never be bought before the run's
        very first node clears -- the earliest possible shop visit (or
        Treasure node) is reached from the map only after that, by which
        point that first node's own Economy is long gone and every later
        node's lives comes from the run's own carried-forward value
        instead (see _load_combat_node). Baking the bonus into Economy
        construction the way every other relic modifier works would make
        it permanently inert no matter when it's picked -- so instead,
        apply it directly onto the run's carried lives the instant the card
        is picked. War Chest used to need this same treatment for gold, but
        no longer does -- see relics.py's own module docstring for why its
        starting_gold_multiplier is a normal per-floor RelicModifiers field
        now instead."""
        self.active_run.lives += relic.starting_lives_bonus

    def _load_level_object(self, level, endless=False, sandbox=False, difficulty_override=None, rng=None,
                            escalation=run_escalation.FloorEscalation(), relic_modifiers=relics.RelicModifiers(),
                            active_run=None, resumed_from_save=False):
        # Sticky for this level, same as current_level_id -- reset()/
        # advance_or_replay_level() read this back so replaying/advancing
        # out of an endless run doesn't silently drop back into a normal,
        # finite-waves one. sandbox follows the identical pattern (see
        # Economy construction below and the win-check in update()).
        self.endless = endless
        self.sandbox = sandbox
        # Stored (not just used inline below for WaveManager's own
        # enemy_gold/speed_multiplier kwargs) so _construct_tower can read
        # whatever this floor's relics resolve to when building a fresh
        # tower -- see its own comment for which fields that means today.
        self.relic_modifiers = relic_modifiers
        # False (the default) for every loader except _load_combat_node/
        # resume_saved_run, mirroring active_run just below -- taken as an
        # explicit parameter, not set after the fact, so resume_saved_run()
        # can pass resumed_from_save=True directly instead of having to
        # overwrite it right after this call returns. This is what stops
        # an unrelated fresh level load (picked from the menu/level-select
        # while an old save from a different, abandoned run still sits on
        # disk) from later deleting that unrelated save on its own
        # eventual victory/game-over.
        self._resumed_from_save = resumed_from_save
        # None (the default) for every loader except _load_combat_node/
        # resume_saved_run, the two callers that actually have a RunState
        # to thread through -- taking it as a parameter here, rather than
        # every caller setting self.active_run and re-calling
        # _rebuild_button_rects() itself afterward, is what lets the one
        # _rebuild_button_rects() call below always build the *correct*
        # menu the first time, no separate "narrow it back down" pass
        # needed anywhere.
        self.active_run = active_run
        # Resets the build menu to active_run's own drafted pool, or every
        # registered tower when there's no run (classic/Practice play, a
        # map-editor playtest) -- see _active_tower_names(). Centralizing
        # this here, rather than requiring every individual loader to
        # remember its own call, is what covers reset()/
        # advance_or_replay_level()'s own direct _load_level_object() calls
        # (a custom/editor-playtested level, never part of a run) for free.
        self._rebuild_button_rects()
        if endless:
            # Endless mode appends newly-generated waves straight onto
            # wave_specs as the run continues (see WaveManager.
            # _advance_after_clear) -- level.wave_specs must be this
            # Game's own private list, never LEVELS' shared registry
            # entry (a module-level singleton every Game/test in the
            # process holds the same object for), or an endless run would
            # permanently leak generated waves into every future
            # non-endless playthrough of the same built-in level.
            level = dataclasses.replace(level, wave_specs=list(level.wave_specs))
        self.level = level
        self.grid = Grid(
            settings.GRID_COLS, settings.GRID_ROWS, settings.TILE_SIZE,
            level.path_cells, level.spawn_cells, level.goal_cells, level.blocked_cells,
            subtiles_per_tile=settings.SUBTILES_PER_TILE,
            subtile_gap=settings.SUBTILE_GAP,
            subtile_gap_alpha=settings.SUBTILE_GAP_ALPHA,
        )
        # escalation/relic_modifiers both default to a no-op (safe as literal
        # defaults -- both are frozen/immutable) unless a caller passes a
        # real one -- only _load_combat_node does, since only it knows which
        # node of a run this is and what relics that run has drafted.
        # Composed into the same construction `mode`'s own multipliers
        # already occupy, same "extra factor, never replacing" rule
        # difficulty.py's own docstring states. gold_per_floor_bonus is the
        # one relic_modifiers field NOT applied here -- _load_combat_node
        # adds it after this method returns, see its own comment, since it's
        # meant to apply on
        # top of every floor's economy, not just what's constructed fresh
        # here. relic_modifiers has no starting_lives field at all, since a
        # relic can never be held this early (see Game._apply_one_time_
        # relic_bonus, where sturdy_gate's own one-time bonus is applied
        # instead, directly onto the run's carried lives at the moment the
        # card is drafted) -- starting_gold_multiplier has no such
        # restriction, since battle gold is rebuilt fresh from this same
        # construction every floor, not just floor 0.
        mode = difficulty.DIFFICULTY_MODES[difficulty_override or self.difficulty]
        self.economy = Economy(
            self._scaled_starting_gold(level, mode, relic_modifiers.starting_gold_multiplier),
            round(level.starting_lives * mode.starting_lives_multiplier),
            unlimited_gold=self.unlimited_gold or sandbox,
            invulnerable=sandbox,
        )
        self.wave_manager = WaveManager(
            level, self.grid.tile_to_pixel_center,
            enemy_hp_multiplier=mode.enemy_hp_multiplier * escalation.enemy_hp_multiplier,
            enemy_speed_multiplier=(
                mode.enemy_speed_multiplier * escalation.enemy_speed_multiplier
                * relic_modifiers.enemy_speed_multiplier
            ),
            enemy_gold_multiplier=(
                mode.enemy_gold_multiplier * escalation.enemy_gold_multiplier * relic_modifiers.enemy_gold_multiplier
            ),
            endless=endless,
            rng=rng,
        )

        self.enemies = []
        self.towers = []
        # A tower sold mid-level is removed from self.towers (see
        # try_sell_tower) but its lifetime stats still belong in this
        # level's post-level results table -- kept here purely so
        # _tower_results() can still find it. Never touched otherwise; a
        # sold tower is already fully inert once off the grid.
        self.sold_towers = []
        # render()'s own snapshot of _tower_results(), taken once by
        # _cache_tower_results() at the moment GAME_OVER/VICTORY/
        # FLOOR_CLEARED is actually entered -- reset to empty here purely
        # so a fresh level never has a stale table left over from
        # whatever was last shown before it, same spirit as sold_towers
        # above (it's always overwritten again before anything reads it
        # for real, since every path into one of those three states goes
        # through _cache_tower_results() first).
        self._cached_tower_results = []
        self.projectiles = []
        self.damage_numbers = []
        self.impact_effects = []
        # A toast still queued the instant a level ends (e.g. an
        # achievement unlocked on the killing blow of the last wave) would
        # otherwise keep rising/fading on top of whatever loads next.
        self.achievement_toasts = []
        self.selected_tower_name = None
        self.selected_tower = None  # placed Tower instance pinned open in the stats panel
        # Whatever the stats panel showed as of the last render() -- see
        # _handle_panel_action_click for why clicks must use this instead
        # of re-deriving the subject from the click-time mouse position.
        self._last_panel_subject = None

    def apply_display_mode(self, size=None):
        """(Re)create self.screen for the current self.fullscreen setting,
        at `size` pixels -- defaults to self.window_size (the persisted
        windowed size, itself defaulting to settings.SCREEN_WIDTH/HEIGHT --
        see player_settings.DEFAULTS). Overridden explicitly by
        set_window_size() (a Settings-screen preset click) and by
        handle_events()'s pygame.VIDEORESIZE case (an organic drag) --
        both also update self.window_size itself, so the *next* bare call
        here (e.g. toggling fullscreen back off) still lands on whatever
        size the player last actually chose, not silently back to the
        hardcoded default.

        pygame.SCALED (rendering at a fixed logical resolution, letterboxed
        by SDL to whatever physical size the window becomes) was the first
        choice here -- every Rect/pygame.mouse.get_pos() call in ui.py/
        game.py would have kept working unmodified, since pygame reports
        mouse coordinates in logical space under SCALED. Dropped: SCALED
        allocates an SDL renderer, and constructing a second Game in the
        same process without an intervening pygame.quit() -- which several
        tests do, and which is otherwise perfectly safe -- fails with
        "failed to create renderer" under the SDL dummy video driver this
        whole suite runs under. Plain RESIZABLE has no such renderer and
        needs no such teardown; the tradeoff is that dragging the window
        to a non-16:PLAY_WIDTH+PANEL_WIDTH:9-ish aspect ratio just shows
        more/less background (handled by re-running set_mode() at the new
        size on VIDEORESIZE, same as this method's own default case)
        rather than rescaling the content."""
        flags = pygame.RESIZABLE
        if self.fullscreen:
            flags |= pygame.FULLSCREEN
        self.screen = pygame.display.set_mode(size or self.window_size, flags)

    def set_fullscreen(self, value):
        self.fullscreen = bool(value)
        self.apply_display_mode()
        self._save_player_settings()

    def set_difficulty(self, key):
        if key in difficulty.DIFFICULTY_MODES:
            self.difficulty = key
            self._save_player_settings()

    def set_window_size(self, size):
        """A Settings-screen preset click -- see the VIDEORESIZE handler in
        handle_events() for the other way self.window_size changes (an
        organic drag), which persists through this same field/save call."""
        if self.fullscreen:
            return  # meaningless while fullscreen, same as a drag already being ignored there
        self.window_size = tuple(size)
        self.apply_display_mode(self.window_size)
        self._save_player_settings()

    def _save_player_settings(self):
        player_settings.save_settings(
            {
                "fullscreen": self.fullscreen,
                "difficulty": self.difficulty,
                "window_size": list(self.window_size),
            },
            self.settings_path,
        )

    def set_time_scale(self, scale):
        if scale in self.TIME_SCALES:
            self.time_scale = scale

    def cycle_time_scale(self):
        index = self.TIME_SCALES.index(self.time_scale)
        self.time_scale = self.TIME_SCALES[(index + 1) % len(self.TIME_SCALES)]

    def reset(self):
        """Restart whatever's currently loaded, exactly as it was when
        this load began -- the pause menu's "Restart Level" (still alive)
        and the game-over screen's "Restart" (see _handle_keydown's own
        two K_r call sites, the only two callers).

        Mid-run and still alive (state == PAUSED, checked directly rather
        than via some indirect proxy like the economy's own is_out_of_lives
        -- self.state hasn't been reassigned to PLAYING yet at this point,
        both callers do that themselves right after reset() returns, so it
        still reliably reflects which of the two ever calls this), this
        restarts the run's own current node (_load_combat_node(run.map.
        node(run.current_node_id)) -- same run, same floor, fresh towers/
        enemies/economy for that floor, drafted pool/relics/carried
        gold-lives all untouched) rather than silently discarding the whole
        run the way a bare _load_level_object() call would (see its own
        active_run parameter, reset to None on every call unless a caller
        passes one through explicitly). A run that's already ended by
        permadeath (state == GAME_OVER, since _record_run_permadeath never
        clears active_run) has nothing left to restart *into*: the run's
        outcome is already recorded, so resurrecting it here would let a
        player undo their own death for free. That falls through to the
        same plain, run-less reload every other reset() has always done,
        same as classic/Practice/playtest play. Only ever reachable with the
        current node still a combat/elite one -- PAUSED is only reachable
        from PLAYING, which only a combat/elite node's own load ever
        enters, so run.map.node(run.current_node_id) is always a node
        _load_combat_node can actually handle."""
        if self.active_run is not None and self.state == GameState.PAUSED:
            # _load_combat_node() already sets self.state = PLAYING itself
            # -- left alone here rather than clobbered by the trailing MENU
            # assignment below, which is only ever right for the two
            # classic-reload branches. Harmless for reset()'s own two real
            # callers either way (both reassign PLAYING themselves right
            # after this returns, regardless of which branch ran), but a
            # caller that doesn't -- a direct call, the way this method's
            # own tests exercise it -- deserves the state this branch
            # actually produced, not a state it never was.
            run = self.active_run
            self._load_combat_node(run.map.node(run.current_node_id))
        else:
            if self.current_level_id is None:
                # custom level: nothing in LEVELS to re-look-up
                self._load_level_object(self.level, endless=self.endless, sandbox=self.sandbox)
            else:
                self.load_level(self.current_level_id, endless=self.endless, sandbox=self.sandbox)
            self.state = GameState.MENU

    def has_next_level(self):
        if not isinstance(self.current_level_id, int):
            return False  # a custom (non-registry) level has no "next" to advance to
        return (self.current_level_id + 1) in LEVELS

    def advance_or_replay_level(self):
        """Called on winning: move to the next level if the registry has
        one, else replay the current (final) level from scratch. A custom
        (non-registry) level never has a next level -- has_next_level()
        guards that -- so this always just replays it."""
        if self.has_next_level():
            self.current_level_id += 1
            self.load_level(self.current_level_id, endless=self.endless, sandbox=self.sandbox)
        elif self.current_level_id is None:
            self._load_level_object(self.level, endless=self.endless, sandbox=self.sandbox)
        else:
            self.load_level(self.current_level_id, endless=self.endless, sandbox=self.sandbox)

    # --- Save/resume a run in progress ---

    def can_save_run(self):
        """Whether the current run is at a point save_run() can capture --
        only between waves (AWAITING_START/BETWEEN_WAVES), never
        mid-SPAWNING or once DONE -- see save_state.py's module docstring
        and WaveManager.restore() for why."""
        return self.wave_manager.state in (WaveState.AWAITING_START, WaveState.BETWEEN_WAVES)

    def save_run(self):
        """Persist the current run to disk for the pause menu's "Save &
        Quit" -- a no-op (returns False) unless can_save_run()."""
        if not self.can_save_run():
            return False
        save_state.save_run(self, self.save_path)
        self.has_saved_run = True
        return True

    def resume_saved_run(self, save_data):
        """Restore a run saved via save_run()/save_state.save_run() --
        reconstructed via _load_level_object() directly (never load_level()'s
        LEVELS[id] re-lookup, even for a built-in level id), so an endless
        run's already-appended escalation waves -- baked into
        save_data["level"] by persistence.level_to_dict/level_from_dict --
        are never silently discarded back to the registry's original,
        un-extended wave list. current_level_id is restored explicitly
        afterward, since _load_level_object() itself doesn't touch it (see
        load_level()/load_custom_level(), the two normal callers that do).

        Towers are rebuilt via TOWER_TYPES directly and Tower.upgrade()/
        specialize() called the right number of times/with the right key --
        never through try_upgrade_tower()/try_specialize_tower() -- so
        resuming never re-charges gold or re-bumps achievement counters for
        progress the player already paid for and was already credited with
        once, back when it first happened. Lifetime shots/damage/kills
        stats and sold_towers are restored too (see _tower_from_save_data),
        so a level's post-level results table still reflects everything
        that happened before the save, not just what happens after.

        A resumed run's escalation/relic_modifiers/rng are re-derived here
        via the same _floor_load_context() _load_combat_node() itself calls
        for that same node -- WaveManager's own multipliers (enemy_hp/speed/
        gold) and its routing rng are never touched by wave_manager.
        restore() below (that only restores wave_index/state/between_wave_
        timer), so leaving these three at _load_level_object()'s own
        no-op defaults would silently understate this floor's difficulty/
        gold and make its enemy routing merely unseeded (rather than
        deterministic) for the rest of the floor, only self-correcting
        once the *next* node's own _load_combat_node() call gets it right.
        Re-deriving the rng this way reproduces what a *fresh* load of
        this floor would draw, not necessarily what an uninterrupted
        playthrough already would have consumed by save time -- no rng
        state is serialized (see _run_rng's own docstring for why), so a
        save taken after some waves have already drawn from this floor's
        rng resumes at that rng's own start, not wherever those draws had
        already left it; later waves can route differently post-resume
        than they would have without one. relic_modifiers.gold_per_floor_
        bonus is the one exception deliberately NOT re-applied here
        (unlike _load_combat_node's own call) -- it was already added
        once, back when this floor was first entered, and that's already
        baked into save_data["gold"] below; re-adding it here would
        double it."""
        level = save_data["level"]
        # save_data["run"] is None for a save with no active run (classic/
        # Practice/editor-playtest play, or one taken before this key
        # existed -- see save_state.py's own docstring) -- passed straight
        # through to _load_level_object()'s own `active_run` parameter
        # either way, same as _load_combat_node() does, so its one
        # _rebuild_button_rects() call already builds the correct menu
        # (every tower, or just this run's drafted pool) with nothing left
        # for resume_saved_run() to restore or rebuild itself afterward.
        run = save_data.get("run")
        if run is not None:
            node = run.map.node(run.current_node_id)
            relic_modifiers, escalation, rng = self._floor_load_context(run, node)
            # The run's own pinned difficulty, not save_data["difficulty"]
            # (save_run() writes that from the same source, but reading it
            # straight off the already-reconstructed RunState here doesn't
            # depend on that -- see save_state.py's own comment on why the
            # top-level field can't just be the live, sticky game.difficulty).
            difficulty_override = run.difficulty
        else:
            relic_modifiers = relics.RelicModifiers()
            escalation = run_escalation.FloorEscalation()
            rng = None
            difficulty_override = save_data["difficulty"]
        self._load_level_object(
            level, endless=save_data["endless"], sandbox=save_data["sandbox"],
            difficulty_override=difficulty_override, rng=rng,
            escalation=escalation, relic_modifiers=relic_modifiers, active_run=run,
            resumed_from_save=True,
        )
        self.current_level_id = save_data["current_level_id"]
        self.wave_manager.restore(save_data["wave_index"], save_data["wave_state"], save_data["between_wave_timer"])
        self.economy.gold = save_data["gold"]
        self.economy.lives = save_data["lives"]

        for tower_data in save_data["towers"]:
            self._register_tower(self._tower_from_save_data(tower_data))
        for tower_data in save_data.get("sold_towers", []):
            self.sold_towers.append(self._tower_from_save_data(tower_data))
        self._recompute_tower_density_bonuses()  # once, after every restored tower is in place

        self.state = GameState.PLAYING

    def _start_daily_challenge(self, seed=None):
        """Start today's Daily Run -- a roguelike run seeded off today's
        UTC date (daily_challenge.todays_seed()) instead of a random one,
        so every player sees the exact same branching map and shop offers
        today and their own skill/picks are the only variable.
        Genuinely just a run otherwise -- see start_new_run's own
        docstring for what is_daily=True actually does."""
        seed = seed if seed is not None else daily_challenge.todays_seed()
        self.start_new_run(seed=seed, is_daily=True)

    def _tower_from_save_data(self, tower_data):
        """Reconstruct one Tower from save_state.py's per-tower dict --
        level/specialization/targeting mode and lifetime stat counters
        applied in the same order they were originally reached, via
        Tower.upgrade()/specialize() directly (see resume_saved_run's own
        docstring for why). Used for both a still-placed tower
        (resume_saved_run registers it onto self.towers/the grid itself)
        and a sold one (self.sold_towers only -- never registered onto
        the grid, since it no longer occupies any space). `.get(...)`
        defaults on the stat counters/sold_towers keep an older save file
        from before these existed resumable rather than KeyError-ing."""
        tower_cls = TOWER_TYPES[tower_data["type"]]
        tower = self._construct_tower(tower_cls, tower_data["anchor_col"], tower_data["anchor_row"])
        for _ in range(tower_data["level"] - 1):
            tower.upgrade()
        if tower_data["specialization"] is not None:
            tower.specialize(tower_data["specialization"])
        tower.targeting_mode = tower_data["targeting_mode"]
        tower.shots_fired = tower_data.get("shots_fired", 0)
        tower.shots_hit = tower_data.get("shots_hit", 0)
        tower.damage_dealt = tower_data.get("damage_dealt", 0.0)
        tower.kills = tower_data.get("kills", 0)
        return tower

    def _continue_saved_run(self):
        """The main menu's "Continue" -- a no-op (stays on MENU) if the
        save file is missing or has since become corrupt, same defensive
        spirit as every other on-disk-data load in this codebase."""
        save_data = save_state.load_run(self.save_path)
        if save_data is not None:
            self.resume_saved_run(save_data)

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
                if self.state == GameState.EDITOR:
                    self._handle_editor_click(event.pos)
                elif self.state == GameState.WAVE_EDITOR:
                    self._handle_wave_editor_click(event.pos)
                elif self.state == GameState.LEVEL_SELECT:
                    self._handle_level_select_click(event.pos)
                elif self.state == GameState.SETTINGS:
                    self._handle_settings_click(event.pos)
                elif self.state == GameState.ACHIEVEMENTS:
                    self._handle_achievements_click(event.pos)
                elif self.state == GameState.HELP:
                    self._handle_help_click(event.pos)
                elif self.state == GameState.CREDITS:
                    self._handle_credits_click(event.pos)
                elif self.state == GameState.DRAFT:
                    self._handle_draft_click(event.pos)
                elif self.state == GameState.MAP:
                    self._handle_map_click(event.pos)
                elif self.state == GameState.EVENT:
                    self._handle_event_click(event.pos)
                else:
                    # REST/TREASURE deliberately have no click handler of
                    # their own -- same "press any key" precedent FLOOR_
                    # CLEARED sets (see _handle_keydown), a click there
                    # just falls through here and no-ops (self.state !=
                    # PLAYING).
                    self._handle_click(event.pos)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                self._handle_right_click()
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.state == GameState.EDITOR:
                self._handle_editor_mouse_up(event.pos)
            elif event.type == pygame.MOUSEMOTION and self.state == GameState.EDITOR:
                self._handle_editor_motion(event.pos, event.buttons)
            elif event.type == pygame.MOUSEWHEEL and self.state == GameState.LEVEL_SELECT:
                self._scroll_level_select(event.y)
            elif event.type == pygame.MOUSEWHEEL and self.state == GameState.WAVE_EDITOR:
                self._scroll_wave_unit_list(event.y)
            elif event.type == pygame.VIDEORESIZE and not self.fullscreen:
                # Only while windowed -- a fullscreen window resizing away
                # from the desktop resolution isn't something the player
                # actually did (see apply_display_mode's docstring for what
                # this makes dragging a windowed edge actually do).
                # set_window_size() persists too, same as a Settings-screen
                # preset click, so an organic drag survives a relaunch just
                # the same. That does mean a full (tiny, un-fsync'd) JSON
                # rewrite on every intermediate size SDL reports while a
                # drag is in progress, not just once at the end -- a
                # deliberate choice, not an oversight: there's no distinct
                # "drag finished" event to defer to here, and debouncing
                # this write is not worth the added state for a save this
                # cheap.
                self.set_window_size(event.size)

    def _handle_keydown(self, key):
        if self.state == GameState.MENU:
            if key == pygame.K_ESCAPE:
                self.running = False
            else:
                # letter, not the raw pygame key constant, so this stays in
                # lockstep with ui.MENU_KEY_HINTS/MENU_KEY_LETTERS -- the
                # single source of truth for which keys the on-screen hint
                # list promises do something (see ui.py for why).
                letter = pygame.key.name(key)
                if letter == "c" and self.has_saved_run:
                    self._continue_saved_run()
                elif letter in ui.MENU_KEY_LETTERS:
                    if letter == "e":
                        self.state = GameState.EDITOR
                    elif letter == "l":
                        self._enter_level_select()
                    elif letter == "s":
                        self.state = GameState.SETTINGS
                    elif letter == "a":
                        self._enter_achievements()
                    elif letter == "h":
                        self.state = GameState.HELP
                    elif letter == "d":
                        self._start_daily_challenge()
                    elif letter == "b":
                        self.state = GameState.CREDITS
                else:
                    self.start_new_run()
        elif self.state in (GameState.SETTINGS, GameState.ACHIEVEMENTS,
                             GameState.HELP, GameState.CREDITS):
            # These four share nothing but "Esc goes back to the menu" --
            # each is otherwise driven entirely by its own click handler
            # (Settings/Achievements have real buttons; Help/Credits are
            # fully static). EDITOR isn't folded in here despite starting
            # with the identical check, since it has real key handling of
            # its own below Esc (see its own elif right after this one).
            if key == pygame.K_ESCAPE:
                self.state = GameState.MENU
        elif self.state == GameState.EDITOR:
            if key == pygame.K_ESCAPE:
                self.state = GameState.MENU
            else:
                self._handle_editor_undo_redo_keydown(key)
        elif self.state == GameState.WAVE_EDITOR:
            if key == pygame.K_ESCAPE:
                self.state = GameState.EDITOR  # one step back, same as the Back-to-Path button
            else:
                self._handle_editor_undo_redo_keydown(key)
        elif self.state == GameState.LEVEL_SELECT:
            if key == pygame.K_ESCAPE:
                # Back to wherever this screen was entered from -- the
                # menu's L, or the editor's Load Map... (see
                # _enter_level_select's purpose param).
                self.state = GameState.MENU if self.level_select_purpose == "play" else GameState.EDITOR
            elif key == pygame.K_v and self.level_select_purpose == "play":
                # Arms/disarms endless/survival mode for whichever level
                # gets picked next -- meaningless while browsing to load a
                # map into the editor (purpose="edit"), so a no-op there.
                self.level_select_endless_armed = not self.level_select_endless_armed
        elif self.state == GameState.PLAYING:
            if key in (pygame.K_p, pygame.K_ESCAPE):
                self.state = GameState.PAUSED
            elif key == pygame.K_SPACE:
                self.wave_manager.skip_delay()
            elif key == pygame.K_1:
                self.set_time_scale(1.0)
            elif key == pygame.K_2:
                self.set_time_scale(2.0)
            elif key == pygame.K_3:
                self.set_time_scale(3.0)
        elif self.state == GameState.PAUSED:
            if self.pause_restart_confirm_pending:
                # Only R (confirm) or Esc (cancel, back to the normal pause
                # menu -- still PAUSED) do anything here; P is deliberately
                # not treated as a synonym for Esc, unlike the normal pause
                # menu's own Esc/P-both-resume shape, so a reflexive P
                # press mid-confirm can't be misread as "resume playing"
                # when nothing has actually been decided yet.
                if key == pygame.K_r:
                    self.reset()  # reset() itself still sees state == PAUSED here
                    self.state = GameState.PLAYING
                    self.pause_restart_confirm_pending = False
                elif key == pygame.K_ESCAPE:
                    self.pause_restart_confirm_pending = False
            elif key in (pygame.K_p, pygame.K_ESCAPE):
                self.state = GameState.PLAYING
            elif key == pygame.K_r:
                self.pause_restart_confirm_pending = True
            elif key == pygame.K_e and self.current_level_id is None:
                # Only offered (see ui.draw_pause_menu) while playing a
                # custom level -- self.editor still has whatever was
                # playtested, untouched, so this is just "stop playing,"
                # not a reload.
                self.state = GameState.EDITOR
            elif key == pygame.K_s and self.can_save_run():
                self.save_run()
                self.state = GameState.MENU
            elif key == pygame.K_q:
                self.running = False
        elif self.state == GameState.GAME_OVER:
            if key == pygame.K_ESCAPE:
                self.running = False
            elif key == pygame.K_r:
                self.reset()
                self.state = GameState.PLAYING
        elif self.state == GameState.VICTORY:
            if key == pygame.K_ESCAPE:
                self.running = False
            elif key == pygame.K_r:
                self.advance_or_replay_level()
                self.state = GameState.PLAYING
        elif self.state == GameState.FLOOR_CLEARED:
            # Escape quits, same as every other post-battle results screen
            # (VICTORY/GAME_OVER just above) -- any other key returns to
            # the map, same "press any key to continue" spirit as the
            # menu's own catch-all, since there's nothing to choose between
            # here (that's the map screen's job, entered next).
            if key == pygame.K_ESCAPE:
                self.running = False
            else:
                self._enter_map()
        elif self.state == GameState.MAP:
            # No keyboard equivalent for picking a node, same as the build
            # menu's own tower buttons -- but Escape should still quit, the
            # same as every other non-PLAYING screen offers.
            if key == pygame.K_ESCAPE:
                self.running = False
        elif self.state == GameState.DRAFT:
            # No keyboard equivalent for picking a card, same as the build
            # menu's own tower buttons -- but Escape should still quit, the
            # same as every other non-PLAYING screen offers, rather than
            # leaving this the one screen with no keyboard way out at all.
            if key == pygame.K_ESCAPE:
                self.running = False
        elif self.state == GameState.EVENT:
            # Escape quits, same as every other non-PLAYING screen; any
            # other key only does something once an option's been chosen
            # (see _handle_event_click's own "resolved" phase) -- no
            # keyboard equivalent for picking an option itself, same as
            # DRAFT above.
            if key == pygame.K_ESCAPE:
                self.running = False
            elif self.event_phase == "resolved":
                self._finish_node(self.active_run.current_node_id)
        elif self.state == GameState.REST:
            # A Rest node has nothing to choose -- it's already resolved
            # the instant it's entered (see _enter_rest_node) -- so any key
            # but Escape just continues, same "press any key" spirit as
            # FLOOR_CLEARED above.
            if key == pygame.K_ESCAPE:
                self.running = False
            else:
                self._finish_node(self.active_run.current_node_id)
        elif self.state == GameState.TREASURE:
            # Same "already resolved on entry, press any key to continue"
            # shape as REST above.
            if key == pygame.K_ESCAPE:
                self.running = False
            else:
                self._finish_node(self.active_run.current_node_id)

    def _handle_right_click(self):
        if self.state != GameState.PLAYING:
            return
        self.selected_tower_name = None
        self.selected_tower = None

    def _handle_editor_undo_redo_keydown(self, key):
        """Ctrl+Z/Ctrl+Y -- shared by both editor screens' keydown handling
        (GameState.EDITOR and WAVE_EDITOR), since both mutate the same
        self.editor. Routes through _handle_editor_undo_redo_action() so
        there's exactly one place that actually calls undo()/redo(),
        regardless of whether it was a keypress or an action-button click."""
        mods = pygame.key.get_mods()
        if key == pygame.K_z and mods & pygame.KMOD_CTRL:
            self._handle_editor_undo_redo_action("undo")
        elif key == pygame.K_y and mods & pygame.KMOD_CTRL:
            self._handle_editor_undo_redo_action("redo")

    def _handle_editor_undo_redo_action(self, action):
        """"undo"/"redo" -- shared by both editor screens' action bars
        (see _handle_editor_action/_handle_wave_editor_action) and by
        _handle_editor_undo_redo_keydown above. Returns True if `action`
        was one of these two, so a caller chaining more action checks
        after this one knows whether it's already been handled."""
        if action == "undo":
            self.editor.undo()
            return True
        if action == "redo":
            self.editor.redo()
            return True
        return False

    # --- Map editor ---

    def _handle_editor_click(self, pos):
        tool = ui.get_clicked_editor_tool(pos, self.editor_tool_rects)
        if tool is not None:
            self.editor.set_tool(tool)
            return

        action = ui.get_clicked_editor_action(pos, self.editor_action_rects)
        if action is not None:
            self._handle_editor_action(action)
            return

        if self.editor.paste_pending:
            self.editor.paste_clipboard(self.editor.pixel_to_tile(*pos))
            self.editor.paste_pending = False
            return

        if self.editor.active_tool in SHAPE_TOOLS:
            # Preview-while-dragging tools: this click just starts the
            # drag -- see _handle_editor_motion/_handle_editor_mouse_up
            # for how it's previewed/committed.
            self.editor.begin_shape(self.editor.pixel_to_tile(*pos))
            return

        # Editor.paint_at() silently ignores a pixel outside the grid
        # (e.g. over the toolbar/sidebar, neither of which overlaps the
        # grid's own pixel range), so no further fencing is needed here.
        self.editor.paint_at(*pos)

    def _handle_editor_motion(self, pos, buttons):
        if not buttons[0]:  # left button not held -> nothing to drag
            return
        if self.editor.active_tool in SHAPE_TOOLS:
            self.editor.update_shape_preview(self.editor.pixel_to_tile(*pos))
        else:
            self.editor.paint_at(*pos)

    def _handle_editor_mouse_up(self, pos):
        """Ends whatever the left button was doing on the grid: a
        freeform drag-paint stroke (see Editor.begin_stroke(), called
        from _apply_tool() on the first cell of the stroke), or a Line/
        Rect/Select drag (committed here instead)."""
        if self.editor.active_tool in SHAPE_TOOLS:
            self.editor.commit_shape(self.editor.pixel_to_tile(*pos))
        else:
            self.editor.end_stroke()

    def _handle_editor_action(self, action):
        if action == "back":
            self.state = GameState.MENU
        elif action == "waves" and self.editor.path_is_valid():
            self.wave_unit_scroll_offset = 0  # always open scrolled to the top
            self._rebuild_wave_unit_rects()
            self.state = GameState.WAVE_EDITOR
        elif action == "load":
            self._enter_level_select(purpose="edit")
        elif action == "import":
            self._import_level()
        elif action == "copy":
            self.editor.copy_selection()
        elif action == "paste":
            self.editor.paste_pending = True
        else:
            self._handle_editor_undo_redo_action(action)

    def _import_level(self):
        """OS-dialog wrapper around _import_level_from_path() below --
        imports tkinter lazily, inside this method rather than at module
        top, so headless test/CI environments never need a working Tk
        install just to import game.py at all (this method itself has no
        test coverage for the same reason; only _import_level_from_path()
        does -- see tests). Cancelling the dialog (an empty path) is a
        silent no-op, same as any other cancelled OS file picker."""
        import tkinter
        from tkinter import filedialog

        root = tkinter.Tk()
        root.withdraw()  # no blank Tk window behind the picker
        path = filedialog.askopenfilename(filetypes=[("Level JSON", "*.json")])
        root.destroy()
        if not path:
            return
        if self._import_level_from_path(path):
            # Re-reads custom_levels/ fresh (see _enter_level_select's own
            # docstring), so the just-imported file shows up immediately.
            self._enter_level_select(purpose="edit")

    def _import_level_from_path(self, path, directory=None):
        """Testable core of Import Level...: validate `path` as a level
        file and copy it into custom_levels/ (or `directory`, injectable
        the same way persistence.save_level's own `directory` param is --
        lets tests point this at a tmp_path instead of ever touching the
        real repo-root custom_levels/). Reuses the exact same validation
        persistence.list_custom_levels() already relies on
        (Level.__post_init__, triggered via persistence.load_level_file())
        rather than re-deriving it, and persistence.save_level() for the
        copy itself, which re-slugifies the filename and handles collisions
        the same way Save already does for an editor-authored level.
        Returns True on success; sets import_status_message/
        import_status_is_error either way for the editor sidebar to show."""
        try:
            level = persistence.load_level_file(path)
        except (OSError, ValueError, KeyError, TypeError):
            # Short and fixed-length by design -- the sidebar has very
            # little vertical room this low in the panel (see
            # ui._draw_editor_path_sidebar), and an arbitrary level name or
            # error detail could wrap far enough to run off the bottom.
            self.import_status_message = "Import failed."
            self.import_status_is_error = True
            return False
        persistence.save_level(level, directory=directory or persistence.LEVELS_DIR)
        self.import_status_message = "Level imported."
        self.import_status_is_error = False
        return True

    # --- Wave editor ---

    def _wave_tab_rects(self):
        """Rebuilt on demand rather than cached -- unlike every other rect
        set in Game, this one's shape depends on how many waves currently
        exist, which changes as the player adds/removes them."""
        return ui.build_wave_tab_rects(len(self.editor.wave_specs))

    def _rebuild_wave_unit_rects(self):
        """wave_unit_rects depends on scroll position, not just on
        ENEMY_ORDER -- called both here (from __init__/entering the wave
        editor) and after every scroll (_scroll_wave_unit_list) so it's
        never stale for the click handler or render() to read. Mirrors
        _rebuild_level_select_rects exactly."""
        self.wave_unit_rects = ui.build_wave_unit_rects(self.wave_unit_scroll_offset)

    def _scroll_wave_unit_list(self, wheel_y):
        # Same sign flip as _scroll_level_select -- pygame's MOUSEWHEEL.y is
        # positive scrolling away from the player (up the list -> less
        # scroll_offset) and negative toward them (down the list -> more).
        max_scroll = ui.wave_unit_max_scroll(len(ui.ENEMY_ORDER))
        self.wave_unit_scroll_offset -= wheel_y * ui.WAVE_UNIT_SCROLL_STEP
        self.wave_unit_scroll_offset = max(0, min(self.wave_unit_scroll_offset, max_scroll))
        self._rebuild_wave_unit_rects()

    def _handle_wave_editor_click(self, pos):
        tab = ui.get_clicked_wave_tab(pos, self._wave_tab_rects())
        if tab == "add":
            self.editor.add_wave()
            return
        if tab == "remove":
            self.editor.remove_wave()
            return
        if tab is not None:  # an int wave index
            self.editor.set_active_wave(tab)
            return

        # A row scrolled above/below the visible list still has a real
        # (just off-viewport) Rect -- see build_wave_unit_rects -- so a
        # click outside the scrollable viewport must never match one, same
        # fence _handle_level_select_click applies to its own rows.
        unit_key = None
        if ui.WAVE_UNIT_ROWS_TOP <= pos[1] <= ui.WAVE_UNIT_ROWS_BOTTOM:
            unit_key = ui.get_clicked_wave_unit_button(pos, self.wave_unit_rects)
        if unit_key is not None:
            enemy_name, sign = unit_key
            self.editor.adjust_unit_count(enemy_name, +1 if sign == "plus" else -1)
            return

        action = ui.get_clicked_wave_editor_action(pos, self.wave_editor_action_rects)
        if action is not None:
            self._handle_wave_editor_action(action)
            return

        # Not on any button -- maybe a spawn marker in the read-only path
        # preview was clicked, switching which spawn's counts the +/-
        # buttons above now target. set_active_spawn() itself already
        # no-ops for a cell that isn't actually a spawn, so nothing here
        # needs to fence the click to "did it land on a real marker" first.
        self.editor.set_active_spawn(self.editor.pixel_to_tile(*pos))

    def _handle_wave_editor_action(self, action):
        if action == "back":
            self.state = GameState.EDITOR
        elif action == "playtest" and self.editor.can_play():
            self.load_custom_level(self.editor.to_level())
            self.state = GameState.PLAYING
        elif action == "save" and self.editor.can_play():
            self.last_saved_path = persistence.save_level(self.editor.to_level())
        else:
            self._handle_editor_undo_redo_action(action)

    # --- Level select ---

    def _enter_level_select(self, purpose="play"):
        """Rebuilds the level list from scratch every time this is
        entered (not just once in __init__) since the custom levels on
        disk can change between visits -- most obviously, right after
        saving one from the editor. Custom levels persist across game
        sessions too: they're read fresh from persistence.LEVELS_DIR here,
        the same directory Save writes to, so a level saved in an earlier
        run of the game shows up here just as readily as one saved this
        session.

        `purpose` is "play" (the menu's L -- picking a level starts it in
        Practice mode) or "edit" (the editor's Load Map... action -- picking
        a level loads it back into the editor for further editing instead;
        see _handle_level_select_click). Built-in levels have no
        corresponding file to reopen for editing, so "edit" only ever
        lists custom ones.

        No level is ever locked here, for either purpose -- purpose="play"
        always starts a level in Practice/sandbox mode (see
        _handle_level_select_click), decoupled from progress.py's real-
        clears tracking the same way a custom level already always was.
        progress.py itself is untouched -- Game.load_level(sandbox=False)
        (what a real roguelike-run floor load, or a direct API/test call,
        still uses) keeps marking levels cleared exactly as before; this
        screen just has no notion of a lock to read that back into."""
        custom_levels = persistence.list_custom_levels()
        self._custom_levels_by_id = {level.id: level for level in custom_levels}

        if purpose == "edit":
            entries = [(level.id, level) for level in custom_levels]
        else:
            entries = [(level_id, level) for level_id, level in sorted(LEVELS.items())]
            entries += [(level.id, level) for level in custom_levels]

        self.level_select_entries = entries
        self.level_select_thumbnails = {key: ui.build_level_thumbnail(level) for key, level in entries}
        self.level_select_purpose = purpose
        self.level_select_scroll_offset = 0  # always open scrolled to the top
        self.level_select_endless_armed = False  # always re-opens un-armed
        self._rebuild_level_select_rects()
        self.state = GameState.LEVEL_SELECT

    def _rebuild_level_select_rects(self):
        """level_select_rects depends on scroll position, not just on
        what's listed -- called both here (from _enter_level_select) and
        after every scroll (_scroll_level_select) so it's never stale for
        the click handler or render() to read."""
        self.level_select_rects = ui.build_level_select_rects(
            self.level_select_entries, self.level_select_scroll_offset,
        )

    def _scroll_level_select(self, wheel_y):
        # pygame's MOUSEWHEEL.y is positive scrolling away from the
        # player (up the list -> less scroll_offset) and negative toward
        # them (down the list -> more) -- hence the sign flip.
        max_scroll = ui.level_select_max_scroll(len(self.level_select_entries))
        self.level_select_scroll_offset -= wheel_y * ui.LEVEL_SELECT_SCROLL_STEP
        self.level_select_scroll_offset = max(0, min(self.level_select_scroll_offset, max_scroll))
        self._rebuild_level_select_rects()

    def _handle_level_select_click(self, pos):
        # A row scrolled off the top/bottom still has a real (just
        # off-viewport) Rect -- see build_level_select_rects -- so a click
        # outside the visible list area must never match one.
        if not (ui.LEVEL_SELECT_TOP <= pos[1] <= ui.LEVEL_SELECT_BOTTOM):
            return
        key = ui.get_clicked_level_select_entry(pos, self.level_select_rects)
        if key is None:
            return
        if self.level_select_purpose == "edit":
            self.editor.load_level(self._custom_levels_by_id[key])
            self.state = GameState.EDITOR
        elif isinstance(key, int):
            # Practice mode has no notion of a locked level (see
            # _enter_level_select) -- picking any built-in id always works.
            self.load_level(key, endless=self.level_select_endless_armed, sandbox=True)
            self.state = GameState.PLAYING
        else:
            self.load_custom_level(
                self._custom_levels_by_id[key],
                endless=self.level_select_endless_armed, sandbox=True,
            )
            self.state = GameState.PLAYING

    # --- Settings ---

    def _handle_settings_click(self, pos):
        option = ui.get_clicked_settings_option(pos, self.settings_rects)
        if option == "fullscreen":
            self.set_fullscreen(not self.fullscreen)
        elif option in difficulty.DIFFICULTY_MODES:
            self.set_difficulty(option)
        elif option in ui.WINDOW_SIZE_PRESETS:
            self.set_window_size(ui.WINDOW_SIZE_PRESETS[option])
        elif option == "back":
            self.state = GameState.MENU

    # --- Achievements ---

    def _enter_achievements(self):
        # Re-read fresh from disk every time -- same "always re-read"
        # convention persistence.list_custom_levels() follows, since an
        # achievement can have unlocked since this screen was last open
        # (e.g. right after a victory earned one -- see update()'s
        # win-check).
        self.achievements_state = achievements.load_achievements(self.achievements_path)
        self.state = GameState.ACHIEVEMENTS

    def _handle_static_screen_back_click(self, pos, back_rect):
        """Shared body for every full-screen "click the Back to Menu
        button" handler below -- kept as separate, per-screen public
        methods (rather than one handler threaded through handle_events'
        own click-routing table) so each stays independently named and
        directly callable, matching how Game's other per-state click
        handlers are organized."""
        if back_rect.collidepoint(pos):
            self.state = GameState.MENU

    def _handle_achievements_click(self, pos):
        self._handle_static_screen_back_click(pos, self.achievements_back_rect)

    # --- Help / How to Play ---

    def _handle_help_click(self, pos):
        self._handle_static_screen_back_click(pos, self.help_back_rect)

    # --- Credits ---

    def _handle_credits_click(self, pos):
        self._handle_static_screen_back_click(pos, self.credits_back_rect)

    def _delete_save_if_this_run_was_resumed(self):
        """Called from both of update()'s win/loss branches -- a resumed
        run that's been played out to a real conclusion has nothing left to
        "Continue" back into, so its save file shouldn't still be offered.
        Guarded on _resumed_from_save (see __init__'s comment on it) so a
        fresh, unrelated run reaching its own conclusion never deletes a
        different, still-valid save left over from some other abandoned
        run."""
        if self._resumed_from_save:
            save_state.delete_saved_run(self.save_path)
            self._resumed_from_save = False
            self.has_saved_run = False

    def _record_level_cleared(self):
        """One level genuinely beaten -- called once, from update()'s own
        win-check, above the run-floor-clear/classic-VICTORY split (see
        that call site's own comment for why: a run never reaches VICTORY
        at all, so this used to live inline there alone and had quietly
        made progress.py -- and with it the "Campaign Complete"
        achievement -- unreachable in a normal playthrough).

        A single sandbox gate up front, same shape _record_achievement's
        own docstring argues for: a trivial sandbox run shouldn't earn
        real progress, and that's one policy, not two calls each
        remembering it independently. levels_cleared is still bumped for
        any level, built-in or custom; progress.py and the
        distinct_levels_cleared counter derived from it only make sense
        for a LEVELS registry entry (isinstance -- a custom editor-authored
        level has no registry id, and no fixed order among its peers to be
        "distinct" within)."""
        if self.sandbox:
            return
        if isinstance(self.current_level_id, int):
            cleared = progress.mark_level_cleared(
                self.current_level_id, self.economy.lives, self.progress_path,
            )
            self._queue_achievement_toasts(achievements.set_counter(
                "distinct_levels_cleared", len(cleared), self.achievements_path,
            ))
        self._record_achievement("levels_cleared")

    def _record_progress_counter(self, bump_fn, path, queue_toasts_fn, counter_name, amount):
        """The shared "sandbox-gated bump-and-toast" shape behind
        _record_achievement/_record_meta_progress below, which otherwise
        differ only in which module's own bump() they call, which path,
        and which toast-formatting method the newly-unlocked keys go
        through. Sandbox-gated once, here, rather than at each of those
        two call sites -- a trivial sandbox run shouldn't count toward
        real progress or expand what a future real run can draft, and
        that's one policy, not two independently-remembered ones."""
        if self.sandbox:
            return
        queue_toasts_fn(bump_fn(counter_name, amount, path))

    def _record_achievement(self, counter_name, amount=1):
        """Bump `counter_name` by `amount` (see achievements.py) and queue
        a toast for anything newly unlocked -- called from every Game-
        level event an achievement can key off (try_place_tower/
        try_upgrade_tower/try_specialize_tower and update()'s kill/wave/
        level-clear hooks)."""
        self._record_progress_counter(
            achievements.bump, self.achievements_path, self._queue_achievement_toasts, counter_name, amount,
        )

    def _queue_achievement_toasts(self, newly_unlocked_keys):
        """Queue one rising/fading toast per achievement key in
        `newly_unlocked_keys` (the return value of achievements.bump()/
        set_counter()) -- pulled out of _record_achievement so
        set_counter()-driven achievements (see the victory branch of
        update(), for "campaign_complete") can share the same toast
        presentation without going through bump()'s +1-per-event shape."""
        for key in newly_unlocked_keys:
            achievement = achievements.ACHIEVEMENTS[key]
            self._queue_toast(f"Achievement unlocked: {achievement.display_name}")

    def _record_meta_progress(self, counter_name, amount=1):
        """Same shape as _record_achievement, for meta_progression.py's own
        counters instead of achievements.py's -- bump `counter_name` and
        queue a toast for any tower newly unlocked into the account-wide
        draft pool."""
        self._record_progress_counter(
            meta_progression.bump, self.meta_progression_path, self._queue_meta_unlock_toasts, counter_name, amount,
        )

    def _queue_meta_unlock_toasts(self, newly_unlocked_keys):
        """Same toast presentation _queue_achievement_toasts uses, for
        meta_progression.META_UNLOCKS keys instead of achievements.
        ACHIEVEMENTS -- names the tower a card unlock actually grants
        (read off TOWER_TYPES, since a MetaUnlock has no display_name of
        its own -- see meta_progression.py's own docstring) rather than
        the registry entry's own key."""
        for key in newly_unlocked_keys:
            unlock = meta_progression.META_UNLOCKS[key]
            tower_display_name = TOWER_TYPES[unlock.tower_name].display_name
            self._queue_toast(f"New tower unlocked: {tower_display_name}!")

    def _queue_toast(self, text):
        """Queue one rising/fading toast, stacked below however many are
        already queued this frame so several landing at once (e.g. an
        achievement and a meta-progression unlock on the same event) read
        as distinct lines rather than overlapping illegibly. Shared by
        _queue_achievement_toasts/_queue_meta_unlock_toasts above -- both
        just name what got unlocked, the presentation is identical."""
        y = 40 + 24 * len(self.achievement_toasts)
        self.achievement_toasts.append(effects.FloatingText(
            (settings.PLAY_WIDTH // 2, y), text, lifetime=3.0, rise_speed=8.0, color=settings.COLOR_GOLD,
        ))

    def _handle_click(self, pos):
        if self.state != GameState.PLAYING:
            return

        clicked_button = ui.get_clicked_tower_button(pos, self.button_rects)
        if clicked_button is not None:
            self.selected_tower_name = None if clicked_button == self.selected_tower_name else clicked_button
            self.selected_tower = None  # switching to build mode drops any pinned placed-tower panel
            return

        if self.skip_button_rect.collidepoint(pos):
            self.wave_manager.skip_delay()
            return

        if self.speed_button_rect.collidepoint(pos):
            self.cycle_time_scale()
            return

        if self._handle_panel_action_click(pos):
            return

        if pos[0] >= settings.PLAY_WIDTH:
            return  # click landed in the stats panel but not on a button

        if pos[1] >= settings.SCREEN_HEIGHT - settings.HUD_HEIGHT:
            return  # click landed in the HUD area but not on a button

        for tower in self.towers:
            if tower.contains_upgrade_badge(pos):
                self.try_upgrade_tower(tower)
                return

        for tower in self.towers:
            if tower.contains_point(pos):
                self.selected_tower = tower  # pin it open in the stats panel
                return

        if self.selected_tower_name is not None:
            anchor_col, anchor_row = self.grid.placement_anchor(*pos, footprint_subtiles=self._current_footprint_subtiles())
            self.try_place_tower(anchor_col, anchor_row)
        else:
            self.selected_tower = None  # clicked empty ground -> deselect

    def _handle_panel_action_click(self, pos):
        """Handles a click on the stats panel's Upgrade/Specialize/Sell
        buttons. Returns True if `pos` was on one of them -- whether or
        not it actually did anything, e.g. an unaffordable upgrade still
        "belongs" to that button rather than falling through to the grid
        underneath it -- so the caller knows to stop processing this click.

        Uses self._last_panel_subject (what render() last showed) rather
        than re-deriving the subject from _hovered_tower() at click time:
        by the time the mouse is actually over one of these buttons, it's
        no tower's tile_rect() ever reaches the panel to check -- so a
        fresh lookup here always reads as "not hovering anything" and
        silently falls back to whatever else is pinned/selected, which
        can easily be a *different* tower than the one whose button the
        player is actually looking at and clicking."""
        subject = self._last_panel_subject
        is_tower = subject in self.towers  # not a build-menu class or None

        if self.targeting_button_rect.collidepoint(pos):
            # The row isn't drawn for a support tower (see
            # ui.draw_tower_stats_panel's IS_SUPPORT guard), but this
            # Rect still occupies that screen position regardless of
            # subject -- without this guard, a click there while a
            # support tower is pinned/hovered would silently cycle an
            # attribute (targeting_mode) it inherits but never reads.
            if is_tower and not type(subject).IS_SUPPORT:
                subject.cycle_targeting_mode()
            return True

        if self.upgrade_button_rect.collidepoint(pos):
            if is_tower and not subject.is_max_level:
                self.try_upgrade_tower(subject)
                return True
            # Falls through rather than returning when there's no upgrade
            # to make: this rect is intentionally shared with the first
            # Specialize button (see ui.build_specialize_button_rects --
            # Upgrade and Specialize are mutually exclusive states), so a
            # maxed, specializable tower's click here needs to reach the
            # specialize handling below instead of silently doing nothing.

        for index, rect in enumerate(self.specialize_button_rects):
            if not rect.collidepoint(pos):
                continue
            if is_tower and subject.can_specialize:
                keys = list(subject.SPECIALIZATIONS.keys())
                if index < len(keys):
                    self.try_specialize_tower(subject, keys[index])
            return True

        if self.sell_button_rect.collidepoint(pos):
            if is_tower:
                self.try_sell_tower(subject)
            return True

        return False

    def try_place_tower(self, anchor_col, anchor_row):
        if self.selected_tower_name is None:
            return False
        # Same authoritative-gate spirit as every other check in this
        # method (and as try_upgrade_tower/try_specialize_tower's own
        # independent re-validation of their business rules) -- a run's
        # drafted pool is real game state to enforce here, not just
        # something to trust the build menu already filtered. The build
        # menu's own click handler can in practice only ever set
        # selected_tower_name to a name ui.build_button_rects(
        # _active_tower_names()) actually drew a button for, so this
        # mainly guards against a future path setting it some other way.
        if self.selected_tower_name not in self._active_tower_names():
            return False
        if not self.grid.is_buildable(anchor_col, anchor_row, footprint_subtiles=self._current_footprint_subtiles()):
            return False

        tower_cls = TOWER_TYPES[self.selected_tower_name]
        if not self.economy.can_afford(tower_cls.cost):
            return False

        self._spend_gold(tower_cls.cost)
        tower = self._construct_tower(tower_cls, anchor_col, anchor_row)
        self._register_tower(tower)
        self._recompute_tower_density_bonuses()  # a new neighbor may affect others' counts too
        self._record_achievement("towers_built")
        return True

    def _construct_tower(self, tower_cls, anchor_col, anchor_row):
        """Build a fresh, level-1, unregistered `tower_cls` anchored at
        (anchor_col, anchor_row) -- shared by a fresh placement
        (try_place_tower, above) and rebuilding a tower from a save file
        (_tower_from_save_data, below), which then applies its own saved
        level/specialization/stats before the tower is ever registered.

        Also the one place every relic-driven, per-tower bonus gets
        resolved -- from self.relic_modifiers, itself re-derived fresh
        from the active run's relics on every floor load (see
        _load_level_object) -- and copied onto the new tower's own
        instance attributes (see Tower.__init__'s matching defaults).
        Both callers above go through here, so a fresh placement and a
        resumed tower can never disagree about what a held relic grants.
        footprint_subtiles has to be resolved *before* pixel_pos itself
        (a smaller footprint centers differently), unlike every other
        relic-driven attribute, which only needs to exist on the tower
        object once it already does."""
        footprint_subtiles = self._current_footprint_subtiles()
        pixel_pos = self.grid.anchor_to_pixel_center(anchor_col, anchor_row, footprint_subtiles=footprint_subtiles)
        tower = tower_cls(anchor_col, anchor_row, pixel_pos)
        tower.footprint_subtiles = footprint_subtiles
        tower.relic_range_bonus_multiplier = self.relic_modifiers.tower_range_multiplier
        tower.relic_fire_rate_bonus_multiplier = self.relic_modifiers.tower_fire_rate_multiplier
        tower.relic_poison_chance = self.relic_modifiers.poison_chance
        tower.relic_poison_effect = self.relic_modifiers.poison_effect
        tower.relic_crit_chance = self.relic_modifiers.crit_chance
        tower.relic_crit_damage_multiplier = self.relic_modifiers.crit_damage_multiplier
        tower.relic_damage_bonus_multiplier = self.relic_modifiers.tower_damage_multiplier
        tower.relic_chain_chance = self.relic_modifiers.chain_chance
        tower.relic_chain_effect = self.relic_modifiers.chain_effect
        tower.relic_last_stand_bonus_multiplier = self.relic_modifiers.last_stand_damage_multiplier
        tower.relic_upgrade_cost_multiplier = self.relic_modifiers.tower_upgrade_cost_multiplier
        tower.relic_sell_refund_bonus = self.relic_modifiers.sell_refund_bonus
        tower.relic_aura_range_bonus_multiplier = self.relic_modifiers.support_aura_range_multiplier
        tower.relic_aura_strength_bonus_multiplier = self.relic_modifiers.support_aura_strength_multiplier
        tower.relic_damage_vs_slowed_multiplier = self.relic_modifiers.damage_vs_slowed_multiplier
        tower.relic_slow_chance = self.relic_modifiers.slow_chance
        tower.relic_slow_effect = self.relic_modifiers.slow_effect
        tower.relic_poison_ignores_shield = self.relic_modifiers.poison_ignores_shield
        tower.relic_tower_density_radius = self.relic_modifiers.tower_density_radius
        tower.relic_tower_density_damage_bonus_per_neighbor = self.relic_modifiers.tower_density_damage_bonus_per_neighbor
        tower.relic_tower_density_damage_bonus_cap = self.relic_modifiers.tower_density_damage_bonus_cap
        tower.relic_last_stand_fire_rate_bonus_multiplier = self.relic_modifiers.last_stand_fire_rate_multiplier
        tower.relic_damage_vs_early_route_multiplier = self.relic_modifiers.damage_vs_early_route_multiplier
        tower.relic_damage_vs_high_hp_multiplier = self.relic_modifiers.damage_vs_high_hp_multiplier
        tower.relic_overkill_carry_fraction = self.relic_modifiers.overkill_carry_fraction
        return tower

    def _current_footprint_subtiles(self):
        """How many subtiles square a freshly-constructed tower's
        footprint spans this floor -- settings.SUBTILES_PER_TILE (one full
        tile) unless a Compact Framework-style relic shrinks it, clamped
        to settings.MIN_TOWER_FOOTPRINT_SUBTILES so a relic (or several
        summed together, see relics.compose_relic_modifiers) can never
        collapse it to zero or negative. The clamp lives here, not on
        RelicModifiers.tower_footprint_shrink itself, which stays a plain
        unclamped sum like every other composed field -- any other future
        reader of that raw field would need to remember this same clamp."""
        shrunk = settings.SUBTILES_PER_TILE - self.relic_modifiers.tower_footprint_shrink
        return max(settings.MIN_TOWER_FOOTPRINT_SUBTILES, shrunk)

    def _recompute_tower_density_bonuses(self):
        """Refresh every placed tower's own Overcrowded Circuits-style
        density bonus (Tower.set_nearby_tower_bonus(), which does its own
        neighbor scan over the list handed to it -- see that method's own
        docstring) -- called only from the handful of places self.towers
        itself changes (a placement, a sale, or restoring a whole save),
        not every frame from Game.update(): a Tower's own .pos is fixed
        once at construction and never moves, so nothing about any
        tower's neighbor count can change between one of those events and
        the next -- recomputing it 60x/sec regardless would just repeat
        an unchanged answer 59 times out of 60."""
        for tower in self.towers:
            tower.set_nearby_tower_bonus(self.towers)

    def _register_tower(self, tower):
        """Add an already-built tower to both self.towers and the grid --
        the exact registration step shared by try_place_tower (a freshly
        constructed tower) and resume_saved_run (a fully reconstructed
        one, already leveled/specialized), so the two can never quietly
        drift apart. A sold tower being restored from a save is the one
        case that deliberately skips this: it no longer occupies any
        space, so it only ever goes into self.sold_towers."""
        self.towers.append(tower)
        self.grid.occupy(tower.anchor_col, tower.anchor_row, tower, footprint_subtiles=tower.footprint_subtiles)

    def try_upgrade_tower(self, tower):
        if tower not in self.towers:
            return False
        cost = tower.upgrade_cost()
        if cost is None or not self.economy.can_afford(cost):
            return False

        self._spend_gold(cost)
        tower.upgrade()
        # Fires exactly once per tower, the moment it actually reaches
        # MAX_LEVEL -- try_upgrade_tower's own cost-is-None guard above
        # already stops this method from ever being reached again for an
        # already-maxed tower, so there's no risk of over-counting on a
        # later no-op call.
        if tower.is_max_level:
            self._record_achievement("towers_maxed")
        return True

    def try_specialize_tower(self, tower, key):
        if tower not in self.towers:
            return False
        if not tower.can_specialize or key not in tower.SPECIALIZATIONS:
            return False
        cost = tower.specialization_cost()
        if not self.economy.can_afford(cost):
            return False

        self._spend_gold(cost)
        tower.specialize(key)
        self._record_achievement("towers_specialized")
        return True

    def try_sell_tower(self, tower):
        if tower not in self.towers:
            return False

        self.economy.add_gold(tower.sell_value())
        self.towers.remove(tower)
        self.sold_towers.append(tower)  # see _tower_results()
        self.grid.remove(tower.anchor_col, tower.anchor_row)
        self._recompute_tower_density_bonuses()  # a removed neighbor may affect others' counts too
        if self.selected_tower is tower:
            self.selected_tower = None
        return True

    def _tower_results(self):
        return ui.compute_tower_results(self.towers + self.sold_towers)

    def _cache_tower_results(self):
        """Snapshot _tower_results() once, at the moment a results-showing
        screen (GAME_OVER/VICTORY/FLOOR_CLEARED) is actually entered, for
        render() to read on every frame that screen stays up instead of
        rebuilding and re-sorting the same, unchanging table every single
        frame -- self.towers/self.sold_towers can't change outside
        PLAYING (every place/upgrade/sell click handler is gated to it),
        so there's nothing for a cached copy to go stale against while
        one of these screens is shown. FLOOR_CLEARED especially: it's
        reachable up to once per floor now, far more often than GAME_OVER/
        VICTORY ever were before the run loop."""
        self._cached_tower_results = self._tower_results()

    # --- Update ---

    def _lose_a_life(self):
        """The one call site for losing a life to a leaked enemy --
        Guardian's Reprieve's interception point. If this run holds the
        relic, hasn't used its one-time save yet, isn't already
        invulnerable (sandbox/Creative mode -- nothing to save there,
        lives never actually drop anyway), and this loss would otherwise
        zero self.economy.lives out, spend the relic's charge instead of
        the life: lives is left exactly where it is (1) rather than
        calling lose_life() at all. Every other case falls straight
        through to a normal loss. Re-checking is_on_last_life fresh per
        call (not once per frame) correctly handles several enemies
        leaking on the same frame: the first one that would actually zero
        lives out consumes the charge, any others that frame proceed
        normally against the still-nonzero lives."""
        run = self.active_run
        if (
            run is not None and "guardians_reprieve" in run.relics
            and not run.used_guardians_reprieve and not self.economy.invulnerable
            and self.economy.is_on_last_life
        ):
            run.used_guardians_reprieve = True
            return
        self.economy.lose_life()

    def _spend_gold(self, amount):
        """The one choke point for actually spending gold -- every place
        that debits self.economy (try_place_tower/try_upgrade_tower/
        try_specialize_tower, the only three ways a player can spend gold
        today) routes through here instead of calling self.economy.spend()
        directly, so a future gold sink can't forget the second half of
        this pairing. Also flips Miser's Coffer's own gate (relics.py) --
        tracked unconditionally regardless of whether the relic is even
        held, rather than hooking Economy itself (which stays pure Python
        with no relic/game awareness per its own module docstring) --
        simplest, and reusable by any future relic wanting the same
        "before this run's first spend" gate."""
        self.economy.spend(amount)
        if self.active_run is not None:
            self.active_run.has_spent_gold = True

    def update(self, dt):
        if self.state != GameState.PLAYING:
            return

        # Real wall-clock dt still drives self.clock.tick(FPS) in run(), so
        # frame pacing/FPS is unaffected -- only simulated time speeds up.
        dt = dt * self.time_scale

        for enemy in self.enemies:
            enemy.update(dt, self.enemies)

        # Two passes: every tower's aura buff is reset before any tower
        # (support or attacking) does its own per-frame work, so which
        # order Game happens to iterate self.towers in can never matter --
        # a support tower later in the list still gets to (re-)buff a
        # tower earlier in the list within the same frame. A Last Stand
        # Charm-style relic's live check rides the same first pass --
        # it's one global condition (not a per-tower proximity check like
        # the aura), so no second full iteration is needed.
        last_stand_active = self.economy.is_on_last_life
        for tower in self.towers:
            tower.reset_aura()
            tower.set_last_stand_multiplier(last_stand_active)
        for tower in self.towers:
            tower.update(dt, self.enemies, self.projectiles, self.towers)

        for projectile in self.projectiles:
            projectile.update(dt, self.enemies)

        # Drained here, before dead projectiles are pruned below -- same
        # per-frame-event-list idiom as enemy.damage_events -> damage_
        # numbers just below: an impact is recorded the instant a shot
        # resolves (see Projectile._resolve_hit), so this always catches it
        # before the projectile itself disappears.
        for projectile in self.projectiles:
            for impact_pos, splash_radius in projectile.impact_events:
                # Sized to the blast's real splash_radius when there is
                # one, so the ring actually shows what it hit -- a small
                # fixed flash otherwise, just to mark a direct hit landed.
                max_radius, duration = (splash_radius, 0.4) if splash_radius else (14, 0.25)
                self.impact_effects.append(effects.ExpandingRing(
                    impact_pos, max_radius=max_radius, duration=duration,
                    color=settings.COLOR_RANGE_PREVIEW,
                ))
            projectile.impact_events.clear()
        self.projectiles = [p for p in self.projectiles if not p.dead]

        # Drained here -- while dead enemies are still in self.enemies with
        # a valid pos, before the alive-filter loop below removes them --
        # so a killing blow's own damage number still gets a floating text
        # at the spot it landed rather than being silently dropped.
        for enemy in self.enemies:
            for amount in enemy.damage_events:
                self.damage_numbers.append(effects.FloatingText(enemy.pos, str(round(amount))))
            enemy.damage_events.clear()
        for text in self.damage_numbers:
            text.update(dt)
        self.damage_numbers = [t for t in self.damage_numbers if not t.dead]

        for ring in self.impact_effects:
            ring.update(dt)
        self.impact_effects = [r for r in self.impact_effects if not r.dead]

        for toast in self.achievement_toasts:
            toast.update(dt)
        self.achievement_toasts = [t for t in self.achievement_toasts if not t.dead]

        still_alive = []
        kills_this_frame = 0
        for enemy in self.enemies:
            if enemy.is_dead:
                self.economy.add_gold(enemy.gold_reward)
                kills_this_frame += 1
                # A small death poof, same spot the killing blow's own
                # damage number is spawned from -- reads enemy.pos before
                # this enemy is dropped from self.enemies just below.
                self.impact_effects.append(effects.ExpandingRing(
                    enemy.pos, max_radius=enemy.radius * 1.8, duration=0.3, color=settings.COLOR_LIVES,
                ))
                # SplitterEnemy is the only species that ever populates
                # this -- empty for everything else, so extending
                # unconditionally needs no per-species special-casing (see
                # Enemy.pending_spawns).
                still_alive.extend(enemy.pending_spawns)
            elif enemy.reached_goal:
                self._lose_a_life()
            else:
                still_alive.append(enemy)
        self.enemies = still_alive
        if kills_this_frame:
            # One bump for however many enemies died this tick, not one
            # per enemy -- a splash/chain hit that kills several at once
            # would otherwise do that many separate load-mutate-save
            # round trips through achievements.json in a single frame.
            self._record_achievement("kills", kills_this_frame)

        # Compared before/after to detect a wave actually clearing this
        # tick (WaveManager._advance_after_clear bumping wave_index) --
        # counts a survived wave whether it came from the level's own
        # authored waves or an endless-generated one, without adding any
        # Game/persistence coupling into waves.py itself.
        wave_number_before_update = self.wave_manager.current_wave_number
        self.enemies.extend(self.wave_manager.update(dt, self.enemies))
        if self.wave_manager.current_wave_number > wave_number_before_update:
            self._record_achievement("waves_survived")

        if self.economy.is_out_of_lives:
            self.state = GameState.GAME_OVER
            self._cache_tower_results()
            self._delete_save_if_this_run_was_resumed()
            if self.active_run is not None:
                # A Daily Run is still just self.active_run with is_daily
                # set -- _record_run_permadeath() needs no special case for
                # it, same reasoning _start_daily_challenge's own docstring
                # gives.
                self._record_run_permadeath()
        elif self.wave_manager.all_waves_complete and not self.enemies:
            # One level genuinely beaten, on either path below -- recorded
            # once, here, above the split, rather than duplicated into both
            # branches (see _record_level_cleared's own docstring for why
            # this used to live inline in the VICTORY branch alone, which a
            # run never reaches).
            self._record_level_cleared()
            if self.active_run is not None:
                # A run's own floor-clear, not a classic-play VICTORY --
                # the map's boss node is always loaded endless=True (see
                # _load_combat_node), so all_waves_complete structurally
                # can never fire for it; this branch is only ever reached
                # by a non-final floor clearing.
                self._advance_run_floor()
            else:
                self.state = GameState.VICTORY
                self._cache_tower_results()
                self._delete_save_if_this_run_was_resumed()

    # --- Render ---

    def render(self):
        self.screen.fill(settings.COLOR_BG)

        if self.state == GameState.MENU:
            ui.draw_menu_screen(self.screen, self.font, self.small_font, self.has_saved_run)
            pygame.display.flip()
            return

        if self.state == GameState.SETTINGS:
            ui.draw_settings_screen(
                self.screen, self.font, self.small_font, self.settings_rects,
                self.fullscreen, self.difficulty, self.window_size,
            )
            pygame.display.flip()
            return

        if self.state == GameState.ACHIEVEMENTS:
            ui.draw_achievements_screen(
                self.screen, self.font, self.small_font,
                self.achievements_state["unlocked"], self.achievements_state["counters"],
                self.achievements_back_rect,
            )
            pygame.display.flip()
            return

        if self.state == GameState.HELP:
            ui.draw_help_screen(self.screen, self.font, self.small_font, self.help_back_rect)
            pygame.display.flip()
            return

        if self.state == GameState.CREDITS:
            ui.draw_credits_screen(self.screen, self.font, self.small_font, self.credits_back_rect)
            pygame.display.flip()
            return

        if self.state == GameState.EDITOR:
            ui.draw_editor_screen(
                self.screen, self.assets, self.font, self.small_font,
                self.editor, self.editor_tool_rects, self.editor_action_rects,
                self.import_status_message, self.import_status_is_error,
            )
            pygame.display.flip()
            return

        if self.state == GameState.WAVE_EDITOR:
            ui.draw_wave_editor_screen(
                self.screen, self.assets, self.font, self.small_font,
                self.editor, self._wave_tab_rects(), self.wave_unit_rects, self.wave_editor_action_rects,
                self.last_saved_path, self.wave_unit_scroll_offset,
            )
            pygame.display.flip()
            return

        if self.state == GameState.LEVEL_SELECT:
            ui.draw_level_select_screen(
                self.screen, self.font, self.small_font,
                self.level_select_entries, self.level_select_rects, self.level_select_thumbnails,
                self.level_select_purpose, self.level_select_scroll_offset, self.level_select_endless_armed,
            )
            pygame.display.flip()
            return

        # MAP/DRAFT/EVENT/REST/TREASURE are all full-screen, board-less
        # states now (see GameState's own comment on why) -- each guarded
        # on active_run is not None the same way FLOOR_CLEARED's own
        # overlay below still is: active_run is None only ever happens by
        # force-setting state directly (e.g. the render() smoke test's
        # blanket sweep across every GameState), in which case falling
        # through to the normal board/HUD/panel drawing below (with no
        # overlay on top) is fine; crashing on it wouldn't be.
        if self.state == GameState.MAP and self.active_run is not None:
            run = self.active_run
            # lives/shop_currency are meaningless before the run's very
            # first node has ever loaded (run.lives is still its 0
            # placeholder -- see RunState's own docstring) -- None hides
            # the readout entirely rather than showing a misleading
            # "Lives: 0" before any floor has actually been played.
            has_played_a_node = run.current_node_id is not None
            ui.draw_map_screen(
                self.screen, self.font, self.small_font, run.map, self.map_node_rects,
                run.current_node_id, run.visited_node_ids, self._available_node_ids(),
                self._hovered_map_node(),
                run.lives if has_played_a_node else None,
                run.shop_currency if has_played_a_node else None,
            )
            pygame.display.flip()
            return

        if self.state == GameState.DRAFT and self.active_run is not None:
            ui.draw_draft_screen(
                self.screen, self.font, self.small_font,
                self.draft_choices, self.draft_choice_rects, self._hovered_draft_choice(),
                self.shop_purchased_indices, self.active_run.shop_currency,
                self.shop_continue_button_rect, self.economy.unlimited_gold,
            )
            pygame.display.flip()
            return

        if self.state == GameState.EVENT and self.active_run is not None:
            ui.draw_event_screen(
                self.screen, self.font, self.small_font, self.current_event, self.event_option_rects,
                self._hovered_event_option(), self.event_phase, self.event_chosen_option, self.event_resolution,
            )
            pygame.display.flip()
            return

        if self.state == GameState.REST and self.active_run is not None:
            ui.draw_rest_screen(
                self.screen, self.font, self.small_font, self.rest_heal_amount, self.active_run.lives,
            )
            pygame.display.flip()
            return

        if self.state == GameState.TREASURE and self.active_run is not None:
            ui.draw_treasure_screen(
                self.screen, self.font, self.small_font,
                self.treasure_granted_relic, self.treasure_granted_currency,
            )
            pygame.display.flip()
            return

        self.grid.draw(self.screen, self.assets)
        for tower in self.towers:
            tower.draw(self.screen, self.assets, self.tiny_font)
        for enemy in self.enemies:
            enemy.draw(self.screen, self.assets)
        for projectile in self.projectiles:
            projectile.draw(self.screen, self.assets)
        for ring in self.impact_effects:
            ring.draw(self.screen)
        for text in self.damage_numbers:
            text.draw(self.screen, self.tiny_font)

        self._render_placement_preview()
        hovered_tower = self._hovered_tower()
        panel_subject = self._stats_panel_subject(hovered_tower)
        self._last_panel_subject = panel_subject  # see _handle_panel_action_click
        if panel_subject in self.towers:  # a placed tower (hovered, or pinned via selected_tower)
            ui.draw_tower_range_preview(self.screen, panel_subject)

        # "Floor N/M" -- same 1-based node.row+1 / final_row_index+1 shape
        # FLOOR_CLEARED's own screen already uses, just also shown live
        # during PLAYING itself now, not only between floors.
        floor_label = (
            f"Floor {self.active_run.current_row + 1}/{self.active_run.map.final_row_index + 1}"
            if self.active_run is not None else None
        )
        ui.draw_hud(
            self.screen, self.assets, self.font, self.small_font,
            self.economy, self.wave_manager, self.button_rects,
            self.skip_button_rect, self.selected_tower_name,
            self.time_scale, self.speed_button_rect,
            self.wave_manager.next_wave_preview(),
            shop_currency=self.active_run.shop_currency if self.active_run is not None else None,
            floor_label=floor_label,
        )
        ui.draw_tower_stats_panel(
            self.screen, self.font, self.small_font, panel_subject, self.economy,
            self.targeting_button_rect,
            self.upgrade_button_rect, self.specialize_button_rects, self.sell_button_rect,
            self._hovered_specialize_key(panel_subject),
        )
        for toast in self.achievement_toasts:
            toast.draw(self.screen, self.small_font)

        if self.state == GameState.PAUSED:
            ui.draw_pause_menu(self.screen, self.font, self.small_font,
                                self.current_level_id is None, self.can_save_run(),
                                self.pause_restart_confirm_pending)
        elif self.state == GameState.GAME_OVER:
            ui.draw_game_over_screen(self.screen, self.font, self.small_font, self._cached_tower_results)
        elif self.state == GameState.VICTORY:
            ui.draw_victory_screen(self.screen, self.font, self.small_font, self.has_next_level(),
                                    self._cached_tower_results)
        elif self.state == GameState.FLOOR_CLEARED and self.active_run is not None:
            # active_run is None only ever happens by force-setting state
            # directly (e.g. the render() smoke test's blanket sweep across
            # every GameState) -- real gameplay only ever reaches
            # FLOOR_CLEARED via _advance_run_floor, which requires one.
            # Drawing nothing for that otherwise-unreachable combination is
            # fine; crashing on it wouldn't be. Kept as a frozen-board
            # overlay (unlike MAP/DRAFT/EVENT/REST/TREASURE above) since
            # it's always reached immediately from real combat on a board
            # that still exists -- see GameState's own comment on this
            # split.
            node = self.active_run.map.node(self.active_run.current_node_id)
            ui.draw_floor_cleared_screen(
                self.screen, self.font, self.small_font,
                node.row + 1, self.active_run.map.final_row_index + 1,
                self._cached_tower_results,
            )

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
        footprint_subtiles = self._current_footprint_subtiles()
        anchor_col, anchor_row = self.grid.placement_anchor(*mouse_pos, footprint_subtiles=footprint_subtiles)
        preview_pos = self.grid.anchor_to_pixel_center(anchor_col, anchor_row, footprint_subtiles=footprint_subtiles)
        buildable = self.grid.is_buildable(anchor_col, anchor_row, footprint_subtiles=footprint_subtiles)
        ui.draw_footprint_preview(self.screen, self.grid, anchor_col, anchor_row, buildable, footprint_subtiles=footprint_subtiles)
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

    def _hovered_specialize_key(self, panel_subject):
        """Which of panel_subject's SPECIALIZATIONS the mouse is
        currently over (its Specialize button in the stats panel), or
        None -- lets the panel show that option's description text while
        it's hovered. Only meaningful while the panel is actually showing
        a specializable tower's choice buttons."""
        if panel_subject not in self.towers or not panel_subject.can_specialize:
            return None
        mouse_pos = pygame.mouse.get_pos()
        keys = list(panel_subject.SPECIALIZATIONS.keys())
        for index, rect in enumerate(self.specialize_button_rects):
            if index < len(keys) and rect.collidepoint(mouse_pos):
                return keys[index]
        return None

    def _hovered_draft_choice(self):
        """Index into self.draft_choices/draft_choice_rects the mouse is
        currently over, or None -- lets the draft screen highlight a card
        before it's clicked, same purpose _hovered_specialize_key serves
        for the stats panel's own choice buttons."""
        return ui.get_clicked_draft_choice(pygame.mouse.get_pos(), self.draft_choice_rects)

    def _hovered_map_node(self):
        """The map node id currently under the mouse, or None -- same
        "hover highlight uses the exact same lookup as the click handler"
        precedent _hovered_draft_choice sets."""
        return ui.get_clicked_map_node(pygame.mouse.get_pos(), self.map_node_rects)

    def _hovered_event_option(self):
        """Index into self.current_event.options/event_option_rects the
        mouse is currently over, or None -- same purpose _hovered_draft_
        choice serves for the Shop screen's own cards."""
        return ui.get_clicked_event_option(pygame.mouse.get_pos(), self.event_option_rects)

    def _stats_panel_subject(self, hovered_tower):
        """What the stats panel should show, in priority order: a hovered
        placed tower (a quick peek at whatever's under the mouse right
        now); otherwise a placed tower the player clicked to pin open
        (self.selected_tower -- stays shown even once the mouse moves
        away, until something else replaces or clears it); otherwise the
        tower type currently selected to build; otherwise None (panel
        shows a hint)."""
        if hovered_tower is not None:
            return hovered_tower
        if self.selected_tower is not None:
            return self.selected_tower
        if self.selected_tower_name is not None:
            return TOWER_TYPES[self.selected_tower_name]
        return None
