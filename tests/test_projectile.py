import pygame

from projectile import Projectile


class FakeEnemy:
    def __init__(self, pos, is_dead=False, speed=50.0):
        self.pos = pygame.Vector2(pos)
        self.is_dead = is_dead
        self.speed = speed
        self.damage_taken = 0
        self.slow_applied = None
        self.knockback_applied = None

    def take_damage(self, amount):
        self.damage_taken += amount

    def apply_slow(self, factor, duration):
        self.slow_applied = (factor, duration)

    def apply_knockback(self, distance):
        self.knockback_applied = distance


def test_direct_hit_damages_only_the_target():
    target = FakeEnemy((0, 0))
    bystander = FakeEnemy((1, 1))
    projectile = Projectile(pos=(0, 0), target=target, speed=1000, damage=10)

    projectile.update(dt=1.0, enemies=[target, bystander])

    assert target.damage_taken == 10
    assert bystander.damage_taken == 0
    assert projectile.dead


def test_projectile_homes_toward_target_before_impact():
    target = FakeEnemy((100, 0))
    projectile = Projectile(pos=(0, 0), target=target, speed=10, damage=10)

    projectile.update(dt=1.0, enemies=[target])

    assert not projectile.dead
    assert target.damage_taken == 0
    assert projectile.pos.x == 10


def test_splash_damages_everyone_within_radius_including_target():
    target = FakeEnemy((0, 0))
    in_radius = FakeEnemy((10, 0))
    out_of_radius = FakeEnemy((1000, 0))
    projectile = Projectile(pos=(0, 0), target=target, speed=1000, damage=15, splash_radius=20)

    projectile.update(dt=1.0, enemies=[target, in_radius, out_of_radius])

    assert target.damage_taken == 15
    assert in_radius.damage_taken == 15
    assert out_of_radius.damage_taken == 0


def test_slow_effect_applied_on_direct_hit():
    target = FakeEnemy((0, 0))
    projectile = Projectile(
        pos=(0, 0), target=target, speed=1000, damage=4, slow_effect=(0.5, 2.0),
    )

    projectile.update(dt=1.0, enemies=[target])

    assert target.slow_applied == (0.5, 2.0)


def test_target_dying_before_impact_makes_projectile_a_dud():
    target = FakeEnemy((100, 0), is_dead=True)
    projectile = Projectile(pos=(0, 0), target=target, speed=10, damage=10)

    projectile.update(dt=1.0, enemies=[target])

    assert projectile.dead
    assert target.damage_taken == 0


def test_knockback_pushes_target_back_by_its_speed_times_duration():
    target = FakeEnemy((0, 0), speed=80.0)
    projectile = Projectile(
        pos=(0, 0), target=target, speed=1000, damage=6, knockback_duration=1.5,
    )

    projectile.update(dt=1.0, enemies=[target])

    assert target.knockback_applied == 80.0 * 1.5


def test_no_knockback_call_when_duration_is_zero():
    target = FakeEnemy((0, 0))
    projectile = Projectile(pos=(0, 0), target=target, speed=1000, damage=6)

    projectile.update(dt=1.0, enemies=[target])

    assert target.knockback_applied is None


def test_splash_knockback_applies_to_every_enemy_hit():
    target = FakeEnemy((0, 0), speed=50.0)
    in_radius = FakeEnemy((10, 0), speed=100.0)
    projectile = Projectile(
        pos=(0, 0), target=target, speed=1000, damage=5,
        splash_radius=20, knockback_duration=2.0,
    )

    projectile.update(dt=1.0, enemies=[target, in_radius])

    assert target.knockback_applied == 50.0 * 2.0
    assert in_radius.knockback_applied == 100.0 * 2.0
