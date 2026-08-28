"""Small, self-contained visual-feedback effects -- currently just floating
damage numbers. Same spirit as Projectile: a single data-parametrized class
rather than one type per caller, updated/drawn by Game alongside everything
else that lives for a few frames and then goes away.
"""

import pygame

import settings


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
        if self.dead:
            return
        alpha = max(0, min(255, int(255 * (1 - self.age / self.lifetime))))
        rendered = font.render(self.text, True, self.color)
        rendered.set_alpha(alpha)
        surface.blit(rendered, rendered.get_rect(center=(int(self.pos.x), int(self.pos.y))))


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
