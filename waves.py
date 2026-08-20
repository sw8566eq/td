"""WaveManager: spawn timing and wave progression for the active level.

Reads the active level's wave_specs (a list of {spawn_cell: {enemy_type_name:
count}} dicts, one per wave -- see levels.py) and looks each name up in
ENEMY_TYPES -- this logic is identical whether a wave has one species or
five, or one spawn or several, so mixed-species, multi-spawn, hand-authored
levels need zero changes here.

Takes the live enemy list as a parameter on update() rather than owning it,
so Game stays the single source of truth for "what enemies exist" and
WaveManager stays trivially testable with fake enemy stand-ins.

Waves are a level-wide timeline (one wave_index, one BETWEEN_WAVES
countdown, shared by every spawn), but each wave's composition is per-spawn
-- which spawn a given enemy comes from is decided once, when the per-spawn
queues are built in _begin_wave(), not randomly at spawn time. A level's
path can still branch/merge past that starting spawn (see pathing.py), so
each enemy's own route is sampled fresh from the level's path topology
(pathing.sample_route) once it's actually spawned. Enemy itself is unaware
any of this happened -- it just walks whatever flat pixel waypoint list
it's constructed with, same as always.

Every spawn advances in lockstep, one spawn_interval "round" at a time: the
1st enemy from every spawn that has one goes out together, then the 2nd
from every spawn that still has one, and so on -- not one spawn's whole
queue draining before the next spawn's even starts. A spawn with fewer
enemies queued for the wave just stops contributing to later rounds once
its own queue empties, while any spawns with more left keep going.
"""

import random

import settings
import pathing
from enemy import ENEMY_TYPES


class WaveState:
    AWAITING_START = "awaiting_start"
    BETWEEN_WAVES = "between_waves"
    SPAWNING = "spawning"
    DONE = "done"


class WaveManager:
    def __init__(self, level, cell_to_pixel, spawn_interval=settings.SPAWN_INTERVAL,
                 between_wave_delay=settings.BETWEEN_WAVE_DELAY, rng=None):
        self.level = level
        # (col, row) -> pixel Vector2-like; Grid.tile_to_pixel_center in
        # practice, injected rather than requiring a live Grid so tests can
        # pass a plain lambda.
        self.cell_to_pixel = cell_to_pixel
        self.topology = pathing.PathTopology(level.path_cells, level.spawn_cells, level.goal_cells)
        self.rng = rng or random.Random()
        self.spawn_interval = spawn_interval
        self.between_wave_delay = between_wave_delay

        self.wave_index = 0  # 0-based index into level.wave_specs
        # Wave 1 doesn't auto-start on a timer like every wave after it
        # does -- it waits for the player to explicitly start it (the
        # same "Skip" button doubles as "Start" for this one case; see
        # skip_delay()), so the player gets a beat to place towers first.
        self.state = WaveState.AWAITING_START
        self.between_wave_timer = between_wave_delay
        self.spawn_timer = 0.0
        self._spawn_queues = []  # [(spawn_cell, [Enemy subclass, ...]), ...] -- one queue per spawn this wave

        self.all_waves_complete = False

    @property
    def current_wave_number(self):
        """1-based wave number, for display and enemy per-wave scaling."""
        return self.wave_index + 1

    @property
    def total_waves(self):
        return len(self.level.wave_specs)

    def skip_delay(self):
        """Let the player start the first wave early (from
        AWAITING_START) or skip the between-waves countdown early (from
        BETWEEN_WAVES) -- both just zero out the countdown and let the
        normal update() flow begin the wave on the next tick."""
        if self.state == WaveState.AWAITING_START:
            self.state = WaveState.BETWEEN_WAVES
            self.between_wave_timer = 0.0
        elif self.state == WaveState.BETWEEN_WAVES:
            self.between_wave_timer = 0.0

    def update(self, dt, active_enemies):
        """Advance timers/state. Returns a list of newly-spawned Enemy
        instances this tick -- usually 0 or 1, but one per still-active
        spawn (see _spawn_next_round) when a multi-spawn wave's spawns are
        advancing in lockstep."""
        spawned = []

        if self.state == WaveState.BETWEEN_WAVES:
            self.between_wave_timer -= dt
            if self.between_wave_timer <= 0:
                self._begin_wave()

        elif self.state == WaveState.SPAWNING:
            self.spawn_timer -= dt
            just_spawned = False
            if self.spawn_timer <= 0 and self._has_queued_enemies():
                spawned.extend(self._spawn_next_round())
                self.spawn_timer = self.spawn_interval
                just_spawned = True

            # Don't clear-check on the same tick a spawn happens: the
            # caller (Game) hasn't added this tick's `spawned` enemies to
            # `active_enemies` yet -- that only happens after update()
            # returns -- so checking now would see a stale, too-short list
            # and could advance the wave before the enemies just spawned
            # are ever counted as active.
            if not just_spawned and not self._has_queued_enemies() and not active_enemies:
                self._advance_after_clear()

        return spawned

    def _has_queued_enemies(self):
        return any(queue for _spawn_cell, queue in self._spawn_queues)

    def _spawn_next_round(self):
        """One enemy from every spawn queue that still has one left, all
        on this same tick -- this is what keeps the Nth enemy from each
        spawn emerging at the same moment, rather than one spawn's whole
        queue draining before the next spawn's even starts. A spawn whose
        queue already ran out this wave simply sits this (and every later)
        round out; it doesn't hold the others back or get padded with
        empty turns."""
        spawned = []
        for spawn_cell, queue in self._spawn_queues:
            if queue:
                enemy_cls = queue.pop(0)
                spawned.append(self._spawn_enemy(spawn_cell, enemy_cls))
        return spawned

    def _spawn_enemy(self, spawn_cell, enemy_cls):
        """Build one enemy of `enemy_cls` starting at `spawn_cell`, routed
        along a fresh sample through the level's path topology -- a
        weighted-random route to a goal through any branches along the way
        (see pathing.sample_route). Enemy itself just gets the resulting
        flat pixel waypoint list, same as it always has."""
        route_cells = pathing.sample_route(self.topology, spawn_cell, self.level.branch_weights, self.rng)
        waypoints_px = [self.cell_to_pixel(col, row) for col, row in route_cells]
        return enemy_cls(waypoints_px, self.current_wave_number)

    def _begin_wave(self):
        wave_spec = self.level.wave_specs[self.wave_index]  # {spawn_cell: {enemy_name: count}}
        # Sorted by spawn cell for a deterministic, stable round order --
        # matching the same sort order the editor numbers spawn markers by
        # (see ui.py's _draw_editor_grid) -- rather than depending on
        # whatever order the dict happened to be built/loaded in.
        self._spawn_queues = [
            (spawn_cell, [
                ENEMY_TYPES[enemy_name]
                for enemy_name, count in composition.items()
                for _ in range(count)
            ])
            for spawn_cell, composition in sorted(wave_spec.items())
        ]
        self.spawn_timer = 0.0
        self.state = WaveState.SPAWNING

    def _advance_after_clear(self):
        if self.wave_index >= self.total_waves - 1:
            self.state = WaveState.DONE
            self.all_waves_complete = True
        else:
            self.wave_index += 1
            self.state = WaveState.BETWEEN_WAVES
            self.between_wave_timer = self.between_wave_delay
