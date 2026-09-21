"""Game's achievement/meta-progression/toast-recording methods, extracted
into their own module -- the third slice of game.py's own god-object
decomposition (see renderer.py/input_handler.py for the first two, and
CLAUDE.md's own note on the shape this pattern follows).

Unlike input_handler.py's own extraction, which orphaned 3 delegators
because every caller of a moved method had itself also moved (see
CLAUDE.md's own documented gotcha), this slice's real callers --
Game.try_place_tower/try_upgrade_tower/try_specialize_tower, update()'s own
kill/wave/level-clear hooks, _advance_run_floor, _record_run_permadeath,
_handle_boss_defeated -- all stay on Game. So Game keeps a one-line
delegator only for the 5 methods with a real external caller or a direct
test reference (_record_level_cleared/_record_achievement/
_record_meta_progress/_queue_meta_unlock_toasts/_queue_toast); the other
two (_record_progress_counter/_queue_achievement_toasts, called only by
methods that moved here too) have no Game-level shim at all -- the same
"private helper, no delegator" shape renderer.py's own
_render_placement_preview already established. No coverage was orphaned by
this move, so no new regression tests were needed for the extraction
itself.

ProgressTracker holds a `game` reference rather than being handed each
piece of state it needs individually, same reasoning as
Renderer/InputHandler -- these 7 methods together read
game.sandbox/current_level_id/economy.lives/progress_path/
achievements_path/meta_progression_path, and write only
game.achievement_toasts (via _queue_toast) plus game.audio.play(...).
"""

import achievements
import effects
import meta_progression
import progress
import relics
import settings
from levels import LEVELS
from tower import TOWER_TYPES


class ProgressTracker:
    def __init__(self, game):
        self.game = game

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
        game = self.game
        if game.sandbox:
            return
        if isinstance(game.current_level_id, int):
            cleared = progress.mark_level_cleared(
                game.current_level_id, game.economy.lives, game.progress_path,
            )
            self._queue_achievement_toasts(achievements.set_counter(
                "distinct_levels_cleared", len(cleared), game.achievements_path,
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
        if self.game.sandbox:
            return
        queue_toasts_fn(bump_fn(counter_name, amount, path))

    def _record_achievement(self, counter_name, amount=1):
        """Bump `counter_name` by `amount` (see achievements.py) and queue
        a toast for anything newly unlocked -- called from every Game-
        level event an achievement can key off (try_place_tower/
        try_upgrade_tower/try_specialize_tower and update()'s kill/wave/
        level-clear hooks)."""
        game = self.game
        self._record_progress_counter(
            achievements.bump, game.achievements_path, self._queue_achievement_toasts, counter_name, amount,
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
        game = self.game
        self._record_progress_counter(
            meta_progression.bump, game.meta_progression_path, self._queue_meta_unlock_toasts, counter_name, amount,
        )

    def _queue_meta_unlock_toasts(self, newly_unlocked_keys):
        """Same toast presentation _queue_achievement_toasts uses, for
        meta_progression.py's own unlock registries instead of
        achievements.ACHIEVEMENTS -- names whatever a card unlock actually
        grants (read off TOWER_TYPES/relics.RELICS/LEVELS, since none of
        MetaUnlock/RelicMetaUnlock/LevelMetaUnlock carry a display_name of
        their own -- see meta_progression.py's own docstring) rather than
        the registry entry's own key. meta_progression.bump() draws newly-
        unlocked keys from all three registries at once (see its own
        ALL_UNLOCKS), so this checks each in turn rather than assuming
        every key is a tower unlock."""
        for key in newly_unlocked_keys:
            if key in meta_progression.META_UNLOCKS:
                unlock = meta_progression.META_UNLOCKS[key]
                self._queue_toast(f"New tower unlocked: {TOWER_TYPES[unlock.tower_name].display_name}!")
            elif key in meta_progression.RELIC_META_UNLOCKS:
                unlock = meta_progression.RELIC_META_UNLOCKS[key]
                self._queue_toast(f"New relic unlocked: {relics.RELICS[unlock.relic_key].display_name}!")
            else:
                unlock = meta_progression.LEVEL_META_UNLOCKS[key]
                self._queue_toast(f"New level unlocked: {LEVELS[unlock.level_id].name}!")

    def _queue_toast(self, text):
        """Queue one rising/fading toast, stacked below however many are
        already queued this frame so several landing at once (e.g. an
        achievement and a meta-progression unlock on the same event) read
        as distinct lines rather than overlapping illegibly. Shared by
        _queue_achievement_toasts/_queue_meta_unlock_toasts above -- both
        just name what got unlocked, the presentation is identical."""
        game = self.game
        y = 40 + 24 * len(game.achievement_toasts)
        game.achievement_toasts.append(effects.FloatingText(
            (settings.PLAY_WIDTH // 2, y), text, lifetime=3.0, rise_speed=8.0, color=settings.COLOR_GOLD,
        ))
        game.audio.play("achievement_toast")
