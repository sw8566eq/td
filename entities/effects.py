"""Small, self-contained visual-feedback effects -- currently just floating
damage numbers. Same spirit as Projectile: a single data-parametrized class
rather than one type per caller, updated/drawn by Game alongside everything
else that lives for a few frames and then goes away.
"""

import pygame

from support import settings

# Rendered label surfaces, keyed by (font, text, color). A damage number's
# text never changes after construction, and late endless waves keep
# hundreds alive at once (mostly the same few strings), so re-rendering
# every label every frame was the single biggest render cost. A cached
# surface is shared between labels: draw() sets its alpha right before each
# blit, so the shared alpha never leaks from one label into another. Keyed
# by the Font object itself (not id()), so a font from an earlier Game can
# never alias a new one; cleared wholesale once it reaches the limit, which
# a real session only does if it sees that many distinct strings.
_TEXT_CACHE_LIMIT = 1024
_text_cache = {}


def _text_entry(font, text, color):
    """(surface, half_width, half_height) for a cached label -- see
    _text_cache. The halves are what Rect(center=...) would subtract."""
    key = (font, text, color)
    entry = _text_cache.get(key)
    if entry is None:
        if len(_text_cache) >= _TEXT_CACHE_LIMIT:
            _text_cache.clear()
        surface = font.render(text, True, color)
        width, height = surface.get_size()
        entry = (surface, width // 2, height // 2)
        _text_cache[key] = entry
    return entry


class FloatingText:
    """A short-lived label that rises and fades -- used for the damage
    number popup shown where a hit landed. update(dt) ages it and moves it
    upward; draw() fades it out over its lifetime rather than popping out of
    existence, so even a burst of several (a splash hit, or a chain) reads
    as distinct events rather than a single blink."""

    def __init__(self, pos, text, lifetime=0.8, rise_speed=40.0, color=settings.COLOR_LIVES):
        self.pos = pygame.Vector2(pos)
        self.text = text
        self.lifetime = lifetime
        self.rise_speed = rise_speed
        self.color = color
        self.age = 0.0

    @property
    def dead(self):
        return self.age >= self.lifetime

    def update(self, dt):
        self.age += dt
        self.pos.y -= self.rise_speed * dt

    def draw(self, surface, font):
        # Written flat (no `dead` property, no Rect) -- a late endless wave
        # draws thousands of these a frame. Same pixels as the
        # get_rect(center=...) placement it replaced.
        age, lifetime = self.age, self.lifetime
        if age >= lifetime:
            return
        rendered, half_width, half_height = _text_entry(font, self.text, self.color)
        rendered.set_alpha(max(0, min(255, int(255 * (1 - age / lifetime)))))
        pos = self.pos
        surface.blit(rendered, (int(pos.x) - half_width, int(pos.y) - half_height))


class GroundFire:
    """A burning patch left by an Incendiary Shells-style Mortar impact:
    every ground enemy inside `radius` takes `dps` per second until it
    burns out. Simulation state, ticked by Game._update_ground_fires; it
    only draws itself."""

    def __init__(self, pos, radius, dps, duration, source=None):
        self.pos = pos
        self.radius = radius
        self.dps = dps
        self.time_left = duration
        self.duration = duration
        self.source = source  # the Mortar that fired it -- credited with damage/kills

    @property
    def dead(self):
        return self.time_left <= 0

    def draw(self, surface):
        alpha = int(90 * max(0.0, self.time_left / self.duration)) + 30
        size = int(self.radius * 2)
        patch = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.circle(patch, (255, 120, 30, alpha), (size // 2, size // 2), int(self.radius))
        surface.blit(patch, (int(self.pos.x - self.radius), int(self.pos.y - self.radius)))


class ExpandingRing:
    """A short-lived ring that grows from start_radius to max_radius and
    fades out -- the same "age it, fade it, then it's dead" shape as
    FloatingText, just drawn as a growing circle outline instead of rising
    text. One data-parametrized class, reused for two different combat
    "juice" moments (see Game.update()'s draining of Projectile.
    impact_events and its alive-filter loop's death-poof spawn) rather than
    a separate class per use, same spirit as Projectile itself: a small
    death poof (small max_radius, short duration) and a splash-blast flash
    sized to the projectile's own splash_radius are just different
    constructor args on this one class."""

    def __init__(self, pos, max_radius, duration=0.35, start_radius=4.0, color=(255, 255, 255), width=2):
        self.pos = pygame.Vector2(pos)
        self.max_radius = max_radius
        self.duration = duration
        self.start_radius = start_radius
        self.color = color
        self.width = width
        self.age = 0.0

    @property
    def dead(self):
        return self.age >= self.duration

    @property
    def _progress(self):
        return 0.0 if self.duration <= 0 else min(1.0, self.age / self.duration)

    def update(self, dt):
        self.age += dt

    def draw(self, surface):
        if self.dead:
            return
        radius = int(self.start_radius + (self.max_radius - self.start_radius) * self._progress)
        if radius <= 0:
            return
        alpha = max(0, min(255, int(255 * (1 - self._progress))))
        # pygame.draw.circle has no alpha of its own -- draw onto a small
        # SRCALPHA surface sized just for this ring and blit that, same
        # workaround FloatingText avoids needing only because font.render()
        # already returns an alpha-capable Surface.
        diameter = radius * 2 + self.width
        ring_surface = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
        center = (diameter // 2, diameter // 2)
        pygame.draw.circle(ring_surface, (*self.color, alpha), center, radius, width=self.width)
        surface.blit(ring_surface, ring_surface.get_rect(center=(int(self.pos.x), int(self.pos.y))))
