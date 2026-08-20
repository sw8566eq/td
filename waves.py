"""WaveManager: spawn timing and wave progression for the active level.

Reads the active level's wave_specs (a list of {enemy_type_name: count}
dicts, one per wave) and looks each name up in ENEMY_TYPES -- this logic is
identical whether a wave has one species or five, so mixed-species,
hand-authored levels need zero changes here.

Takes the live enemy list as a parameter on update() rather than owning it,
so Game stays the single source of truth for "what enemies exist" and
WaveManager stays trivially testable with fake enemy stand-ins.

A level's path can branch/merge across multiple spawns (see pathing.py), so
there's no single fixed route to hand every enemy -- each spawned enemy
gets its own concrete route, sampled fresh from the level's path topology
(pathing.sample_route), starting from a randomly chosen spawn cell. Enemy
itself is unaware any of this happened -- it just walks whatever flat pixel
waypoint list it's constructed with, same as always.
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
        self._spawn_queue = []  # one Enemy subclass per remaining spawn this wave

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
        instances this tick (usually 0 or 1)."""
        spawned = []

        if self.state == WaveState.BETWEEN_WAVES:
            self.between_wave_timer -= dt
            if self.between_wave_timer <= 0:
                self._begin_wave()

        elif self.state == WaveState.SPAWNING:
            self.spawn_timer -= dt
            just_spawned = False
            if self.spawn_timer <= 0 and self._spawn_queue:
                enemy_cls = self._spawn_queue.pop(0)
                spawned.append(self._spawn_enemy(enemy_cls))
                self.spawn_timer = self.spawn_interval
                just_spawned = True

            # Don't clear-check on the same tick a spawn happens: the
            # caller (Game) hasn't added this tick's `spawned` enemies to
            # `active_enemies` yet -- that only happens after update()
            # returns -- so checking now would see a stale, too-short list
            # and could advance the wave before the enemy just spawned is
            # ever counted as active.
            if not just_spawned and not self._spawn_queue and not active_enemies:
                self._advance_after_clear()

        return spawned

    def _spawn_enemy(self, enemy_cls):
        """Build one enemy of `enemy_cls`, routed along a fresh sample
        through the level's path topology -- a random spawn cell (evenly
        chosen when the level has more than one), then a weighted-random
        route to a goal through any branches along the way (see
        pathing.sample_route). Enemy itself just gets the resulting flat
        pixel waypoint list, same as it always has."""
        spawn_cell = self.rng.choice(self.level.spawn_cells)
        route_cells = pathing.sample_route(self.topology, spawn_cell, self.level.branch_weights, self.rng)
        waypoints_px = [self.cell_to_pixel(col, row) for col, row in route_cells]
        return enemy_cls(waypoints_px, self.current_wave_number)

    def _begin_wave(self):
        wave_spec = self.level.wave_specs[self.wave_index]
        self._spawn_queue = [
            ENEMY_TYPES[enemy_name]
            for enemy_name, count in wave_spec.items()
            for _ in range(count)
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
