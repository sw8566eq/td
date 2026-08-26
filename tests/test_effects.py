import pygame

from effects import FloatingText


def _font():
    # Called fresh inside each test that needs it, not once at import time --
    # test_assets.py's own tests call pygame.quit() (deinitializing every
    # subsystem, font included), and that can run before these tests if
    # this module simply relied on an import-time pygame.font.init().
    pygame.font.init()
    return pygame.font.SysFont(None, 16)


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


def test_draw_blits_something_onto_the_surface():
    surface = pygame.Surface((100, 100))
    surface.fill((0, 0, 0))
    text = FloatingText((50, 50), "7", color=(255, 255, 255))

    text.draw(surface, _font())

    assert surface.get_at((50, 50)) != (0, 0, 0, 255)  # something was actually blitted


def test_draw_is_a_no_op_once_dead():
    surface = pygame.Surface((100, 100))
    surface.fill((0, 0, 0))
    text = FloatingText((50, 50), "7", lifetime=0.1)
    text.update(dt=0.2)  # now dead
    assert text.dead

    text.draw(surface, _font())

    assert surface.get_at((50, 50)) == (0, 0, 0, 255)  # nothing drawn -- early return
