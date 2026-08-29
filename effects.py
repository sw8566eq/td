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
