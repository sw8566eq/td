"""WaveManager: spawn timing and wave progression for the active level.

Reads the active level's wave_specs (a list of {enemy_type_name: count}
dicts, one per wave) and looks each name up in ENEMY_TYPES -- this logic is
identical whether a wave has one species or five, so mixed-species,
hand-authored levels need zero changes here.

Takes the live enemy list as a parameter on update() rather than owning it,
so Game stays the single source of truth for "what enemies exist" and
WaveManager stays trivially testable with fake enemy stand-ins.
"""

import settings
from enemy import ENEMY_TYPES


class WaveState:
    BETWEEN_WAVES = "between_waves"
    SPAWNING = "spawning"
    DONE = "done"


class WaveManager:
    def __init__(self, level, waypoints_px, spawn_interval=settings.SPAWN_INTERVAL,
                 between_wave_delay=settings.BETWEEN_WAVE_DELAY):
        self.level = level
        self.waypoints_px = waypoints_px
        self.spawn_interval = spawn_interval
        self.between_wave_delay = between_wave_delay

        self.wave_index = 0  # 0-based index into level.wave_specs
        self.state = WaveState.BETWEEN_WAVES
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
        """Let the player skip the between-waves countdown early."""
        if self.state == WaveState.BETWEEN_WAVES:
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
                spawned.append(enemy_cls(self.waypoints_px, self.current_wave_number))
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
