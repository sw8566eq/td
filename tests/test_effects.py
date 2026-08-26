import pygame

from effects import FloatingText


def test_update_ages_and_rises():
    text = FloatingText((100, 100), "5", lifetime=1.0, rise_speed=40.0)

    text.update(dt=0.5)

    assert text.age == 0.5
    assert text.pos.y == 100 - 40.0 * 0.5
    assert not text.dead


def test_dead_once_age_reaches_lifetime():
    text = FloatingText((0, 0), "5", lifetime=0.8)

    text.update(dt=0.8)

    assert text.dead


def test_not_dead_just_before_lifetime_elapses():
    text = FloatingText((0, 0), "5", lifetime=0.8)

    text.update(dt=0.79)

    assert not text.dead


def test_pos_starts_at_the_given_position():
    text = FloatingText((12, 34), "10")

    assert text.pos == pygame.Vector2(12, 34)
