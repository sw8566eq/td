"""Tests for Commander abilities -- run/abilities.py's registry and each
ability's own effect, plus Game.activate_ability/fire_ability, the wave-
counted cooldown, the sidebar button and F hotkey, targeting mode, saves
and the Daily Run."""

import pygame
import pytest
from conftest import clear_mouse_mock, mock_mouse_pos, spy_on_audio, start_first_floor

from core.game import GameState
from entities.enemy import BossEnemy, FlyingEnemy, GruntEnemy
from entities.tower import TOWER_TYPES
from persistence import save_state
from presentation import ui
from progression import service_record
from run import abilities
from run.abilities import ABILITIES
from run.commanders import COMMANDERS, DEFAULT_COMMANDER
from support import settings

FIELD_POINT = (200, 200)


def _enemy(cls=GruntEnemy, x=0.0, y=0.0):
    return cls([pygame.Vector2(x, y), pygame.Vector2(x + 500, y)], wave_number=1)


def _floor_as(game, commander):
    return start_first_floor(game, seed=1, commander=commander)


def _place(game, name):
    anchor = game.placement_anchor_at(*_buildable_px(game), TOWER_TYPES[name])
    game.economy.gold = 10_000
    game.selected_tower_name = name
    assert game.try_place_tower(*anchor)
    game.selected_tower_name = None
    return game.towers[-1]


def _buildable_px(game):
    n = settings.SUBTILES_PER_TILE
    for row in range(settings.GRID_ROWS):
        for col in range(settings.GRID_COLS):
            if game.grid.is_buildable(col * n, row * n) and not any(
                    tower.contains_point((col * settings.TILE_SIZE + 4, row * settings.TILE_SIZE + 4))
                    for tower in game.towers):
                return col * settings.TILE_SIZE + settings.TILE_SIZE // 2, row * settings.TILE_SIZE + settings.TILE_SIZE // 2
    raise AssertionError("no buildable cell")


# --- The registry ---


def test_every_commander_names_a_real_ability_and_each_is_distinct():
    keys = [commander.ability for commander in COMMANDERS.values()]
    assert all(key in ABILITIES for key in keys)
    assert len(set(keys)) == len(keys)


def test_every_ability_is_well_formed():
    for key, ability in ABILITIES.items():
        assert ability.key == key
        assert ability.display_name and ability.description
        assert ability.cooldown_waves >= 1
        assert not ability.targeted or ability.radius > 0
        assert ability.duration == 0 or ability.tower_buff is not None
        # The button's title must fit it.
        pygame.font.init()
        assert pygame.font.SysFont(None, 22).size(f"F: {ability.display_name}")[0] < ui.ACTION_BUTTON_WIDTH


def test_thunderhead_targets_the_toughest_enemies_deterministically():
    enemies = [_enemy() for _ in range(10)]
    for index, enemy in enumerate(enemies):
        enemy.hp = 10 + index
    picked = abilities.thunderhead_targets(enemies)
    assert len(picked) == abilities.THUNDERHEAD_TARGETS
    assert [enemy.hp for enemy in picked] == sorted((10 + i for i in range(10)), reverse=True)[:8]


# --- Each ability's effect ---


def test_hold_the_gate_blocks_the_next_leaks_this_floor(game):
    run = _floor_as(game, "warden")
    lives = game.economy.lives
    game.activate_ability()
    assert run.ability_charges == abilities.HOLD_THE_GATE_CHARGES
    assert run.ability_cooldown == abilities.HOLD_THE_GATE_COOLDOWN
    for _ in range(abilities.HOLD_THE_GATE_CHARGES):
        game._lose_a_life()
    assert game.economy.lives == lives
    game._lose_a_life()
    assert game.economy.lives == lives - 1


def test_hold_the_gate_charges_reset_with_every_fight_load(game):
    run = _floor_as(game, "warden")
    game.activate_ability()
    game.state = GameState.PAUSED  # the pause menu's Restart
    game.reset()
    assert run.ability_charges == 0
    assert run.ability_cooldown == abilities.HOLD_THE_GATE_COOLDOWN  # a restart never refunds it


def test_hold_the_gate_is_refused_while_the_gate_is_already_fully_held(game):
    run = _floor_as(game, "warden")
    run.ability_charges = abilities.HOLD_THE_GATE_CHARGES
    game.activate_ability()
    assert run.ability_cooldown == 0
    assert any("already held" in toast.text for toast in game.achievement_toasts)


def test_hold_the_gate_still_counts_a_proving_grounds_leak(game):
    run = _floor_as(game, "warden")
    run.ability_charges = 1

    class _Challenge:
        leak_limit = 5
        display_name = "Glass Gate"

    game.active_challenge = type("Active", (), {"challenge": _Challenge()})()
    game._lose_a_life()
    assert run.challenge_leaks == 1
    assert run.ability_charges == 0


def test_toxic_downpour_aims_then_poisons_only_enemies_in_its_radius(game):
    run = _floor_as(game, "alchemist")
    near, far, boss = _enemy(x=200, y=200), _enemy(x=700, y=500), _enemy(BossEnemy, x=220, y=200)
    game.enemies = [near, far, boss]

    game.activate_ability()
    assert game.ability_targeting and run.ability_cooldown == 0  # aiming, not yet spent
    game._handle_click(FIELD_POINT)

    assert not game.ability_targeting
    assert run.ability_cooldown == abilities.TOXIC_DOWNPOUR_COOLDOWN
    assert near.poison_damage_per_tick == pytest.approx(near.max_hp * abilities.TOXIC_DOWNPOUR_HP_FRACTION_PER_TICK)
    assert boss.poison_damage_per_tick == pytest.approx(
        boss.max_hp * abilities.TOXIC_DOWNPOUR_BOSS_HP_FRACTION_PER_TICK)
    assert far.poison_time_remaining == 0
    assert game.towers == []  # the aiming click never builds


def test_toxic_downpour_on_empty_ground_is_refused_and_stays_aimed(game):
    run = _floor_as(game, "alchemist")
    game.enemies = [_enemy(x=900, y=500)]
    game.activate_ability()
    game._handle_click(FIELD_POINT)
    assert game.ability_targeting
    assert run.ability_cooldown == 0


@pytest.mark.parametrize("cancel", ["right_click", "escape", "hotkey", "button"])
def test_targeting_can_be_cancelled_without_spending_the_ability(game, cancel):
    run = _floor_as(game, "alchemist")
    game.enemies = [_enemy(x=200, y=200)]
    game.activate_ability()
    assert game.ability_targeting
    if cancel == "right_click":
        game._handle_right_click()
    elif cancel == "escape":
        game._handle_keydown(pygame.K_ESCAPE)
    elif cancel == "hotkey":
        game._handle_keydown(pygame.K_f)
    else:
        game._handle_click(game.ability_button_rect.center)
    assert not game.ability_targeting
    assert game.state == GameState.PLAYING  # Esc backed out of aiming, it didn't pause
    assert run.ability_cooldown == 0


def test_a_click_off_the_field_while_aiming_does_not_fire(game):
    run = _floor_as(game, "alchemist")
    game.enemies = [_enemy(x=200, y=200)]
    game.activate_ability()
    game._handle_click((settings.PLAY_WIDTH + 5, 5))
    assert game.ability_targeting and run.ability_cooldown == 0


def test_called_shot_doubles_basic_and_sniper_damage_while_it_runs(game):
    _floor_as(game, "marksman")
    basic, sniper, frost = _place(game, "basic"), _place(game, "sniper"), _place(game, "frost")
    before = {tower: tower.effective_damage() for tower in (basic, sniper, frost)}
    game.enemies = [_enemy(x=-5000, y=-5000)]
    game.state = GameState.PLAYING

    game.activate_ability()
    game.update(0.01)

    assert basic.effective_damage() == pytest.approx(before[basic] * abilities.CALLED_SHOT_DAMAGE_MULTIPLIER)
    assert sniper.effective_damage() == pytest.approx(before[sniper] * abilities.CALLED_SHOT_DAMAGE_MULTIPLIER)
    assert frost.effective_damage() == pytest.approx(before[frost])

    game.update(abilities.CALLED_SHOT_DURATION)
    game.update(0.01)
    assert game.ability_timer == 0
    assert basic.effective_damage() == pytest.approx(before[basic])


def test_called_shot_with_no_enemies_is_refused(game):
    run = _floor_as(game, "marksman")
    game.enemies = []
    game.activate_ability()
    assert run.ability_cooldown == 0 and game.ability_timer == 0


def test_rapid_repairs_speeds_every_tower_and_repairs_barricades(game):
    _floor_as(game, "engineer")
    basic = _place(game, "basic")
    barricade = type("Barricade", (), {"max_hp": 90.0, "hp": 10.0})()
    game.towers.append(barricade)
    abilities.ABILITIES["rapid_repairs"].use(game, None)
    assert barricade.hp == barricade.max_hp
    game.towers.remove(barricade)

    before = basic.effective_fire_rate()
    game.activate_ability()
    game.update(0.01)
    assert basic.effective_fire_rate() == pytest.approx(before * abilities.RAPID_REPAIRS_FIRE_RATE_MULTIPLIER)


def test_thunderhead_strikes_for_a_fraction_of_max_hp_and_bosses_less(game):
    run = _floor_as(game, "stormcaller")
    grunt, boss = _enemy(), _enemy(BossEnemy)
    game.enemies = [grunt, boss]
    game.activate_ability()
    assert grunt.hp == pytest.approx(grunt.max_hp * (1 - abilities.THUNDERHEAD_HP_FRACTION))
    assert 0 < boss.max_hp - boss.hp <= boss.max_hp * abilities.THUNDERHEAD_BOSS_HP_FRACTION + 1e-6
    assert run.ability_cooldown == abilities.THUNDERHEAD_COOLDOWN
    assert game.impact_effects  # a flash on each struck enemy


def test_thunderhead_with_no_enemies_is_refused(game):
    run = _floor_as(game, "stormcaller")
    game.enemies = []
    game.activate_ability()
    assert run.ability_cooldown == 0


def test_caltrops_slows_ground_enemies_but_not_flyers_or_burrowers(game):
    run = _floor_as(game, "trapmaster")
    from entities.enemy import BurrowerEnemy

    grunt, flyer, burrower = _enemy(), _enemy(FlyingEnemy), _enemy(BurrowerEnemy)
    game.enemies = [grunt, flyer, burrower]
    game.activate_ability()
    assert grunt.slow_multiplier == abilities.CALTROPS_SLOW_FACTOR
    assert flyer.slow_multiplier == 1.0
    assert burrower.slow_multiplier == 1.0
    assert run.ability_cooldown == abilities.CALTROPS_COOLDOWN


def test_caltrops_with_only_flyers_is_refused(game):
    run = _floor_as(game, "trapmaster")
    game.enemies = [_enemy(FlyingEnemy)]
    game.activate_ability()
    assert run.ability_cooldown == 0


def test_downdraft_grounds_and_slows_every_flyer(game):
    run = _floor_as(game, "skywatch")
    flyer, grunt = _enemy(FlyingEnemy), _enemy()
    game.enemies = [flyer, grunt]
    game.activate_ability()
    assert flyer.ground_timer == abilities.DOWNDRAFT_DURATION
    assert flyer.slow_multiplier == abilities.DOWNDRAFT_SLOW_FACTOR
    assert grunt.slow_multiplier == 1.0
    assert run.ability_cooldown == abilities.DOWNDRAFT_COOLDOWN


def test_downdraft_with_no_flyers_is_refused(game):
    run = _floor_as(game, "skywatch")
    game.enemies = [_enemy()]
    game.activate_ability()
    assert run.ability_cooldown == 0
    assert any("No flyers" in toast.text for toast in game.achievement_toasts)


# --- Cooldown and recharge ---


def test_a_spent_ability_recharges_one_step_per_wave_cleared(game):
    run = _floor_as(game, "warden")
    game.activate_ability()
    assert run.ability_cooldown == 3
    game.activate_ability()  # still recharging: refused, toasted
    assert any("recharges in 3 more waves" in toast.text for toast in game.achievement_toasts)
    for expected in (2, 1, 0, 0):
        game._recharge_ability()
        assert run.ability_cooldown == expected
    assert any("is ready" in toast.text for toast in game.achievement_toasts)


def test_update_recharges_the_ability_when_a_wave_clears(game):
    run = _floor_as(game, "warden")
    run.ability_cooldown = 2
    game.wave_manager.skip_delay()
    game.enemies = []
    wave_before = game.wave_manager.current_wave_number
    for _ in range(20_000):
        game.update(1 / 30)
        game.enemies = []  # every spawn dies at once
        if game.wave_manager.current_wave_number > wave_before:
            break
    assert game.wave_manager.current_wave_number > wave_before
    assert run.ability_cooldown == 1


def test_the_cooldown_carries_across_floors(game):
    run = _floor_as(game, "warden")
    game.activate_ability()
    game._load_combat_node(run.map.node(run.current_node_id))
    assert run.ability_cooldown == abilities.HOLD_THE_GATE_COOLDOWN


def test_abilities_are_only_usable_mid_floor_in_a_run(game):
    game.state = GameState.PLAYING
    assert game.current_ability is None
    game.activate_ability()  # Practice/editor play: no Commander, no-op
    game.fire_ability(FIELD_POINT)

    run = _floor_as(game, "stormcaller")
    game.enemies = [_enemy()]
    game.state = GameState.PAUSED
    game.activate_ability()
    game.fire_ability(None)
    assert run.ability_cooldown == 0


# --- Input and rendering ---


def test_f_hotkey_and_the_sidebar_button_both_activate(game):
    run = _floor_as(game, "stormcaller")
    played = spy_on_audio(game)
    game.enemies = [_enemy()]
    game._handle_keydown(pygame.K_f)
    assert run.ability_cooldown == abilities.THUNDERHEAD_COOLDOWN
    assert "potion_used" in played

    run.ability_cooldown = 0
    game.enemies = [_enemy()]
    game._handle_click(game.ability_button_rect.center)
    assert run.ability_cooldown == abilities.THUNDERHEAD_COOLDOWN


def test_using_an_ability_is_recorded_in_the_service_record(game):
    _floor_as(game, "stormcaller")
    game.enemies = [_enemy()]
    game.activate_ability()
    record = service_record.load_service_record(game.service_record_path)
    assert record.get(service_record.OVERALL, "", "abilities_used") == 1


def test_the_ability_button_sits_clear_of_the_panel_and_the_belt():
    button = ui.build_ability_button_rect()
    assert button.top > ui.build_sell_button_rect().bottom
    assert button.bottom < ui.CHALLENGE_STATUS_Y
    assert button.left >= settings.PLAY_WIDTH and button.right <= settings.SCREEN_WIDTH


def test_ability_status_text_covers_every_state():
    hold = ABILITIES["hold_the_gate"]
    assert ui.ability_status_text(hold, 0, 0, 0.0, False) == "Ready"
    assert ui.ability_status_text(hold, 2, 0, 0.0, False) == "Recharging: 2 waves"
    assert ui.ability_status_text(hold, 1, 0, 0.0, False) == "Recharging: 1 wave"
    assert ui.ability_status_text(hold, 3, 2, 0.0, False) == "2 leaks blocked left"
    assert ui.ability_status_text(hold, 3, 0, 4.25, False) == "Active: 4.2s"
    assert "right-click" in ui.ability_status_text(hold, 0, 0, 0.0, True)
    pygame.font.init()
    small = pygame.font.SysFont(None, 22)
    for text in ("Aim -- right-click cancels", "3 leaks blocked left", "Recharging: 3 waves"):
        assert small.size(ui.ability_status_text(hold, 0, 0, 0.0, True))[0] < ui.ACTION_BUTTON_WIDTH
        assert small.size(text)[0] < ui.ACTION_BUTTON_WIDTH


@pytest.mark.parametrize("commander", list(COMMANDERS))
def test_render_while_aiming_hovering_and_recharging_does_not_crash(game, commander):
    run = _floor_as(game, commander)
    game.enemies = [_enemy(x=200, y=200), _enemy(FlyingEnemy, x=200, y=200)]
    try:
        mock_mouse_pos(game.ability_button_rect.center)
        game.render()
        game.activate_ability()
        mock_mouse_pos(FIELD_POINT)
        game.render()
        run.ability_cooldown = 2
        game.ability_targeting = False
        game.render()
    finally:
        clear_mouse_mock()


# --- Saves and the Daily Run ---


def test_cooldown_and_charges_survive_a_save_and_resume(game):
    run = _floor_as(game, "warden")
    game.activate_ability()
    run.ability_charges = 2
    assert game.save_run()

    game.resume_saved_run(save_state.load_run(game.save_path))

    assert game.active_run.ability_cooldown == abilities.HOLD_THE_GATE_COOLDOWN
    assert game.active_run.ability_charges == 2


def test_an_old_save_without_ability_fields_loads_ready(game):
    _floor_as(game, "warden")
    data = save_state._run_to_dict(game.active_run)
    del data["ability_cooldown"], data["ability_charges"]
    run = save_state._run_from_dict(data)
    assert run.ability_cooldown == 0 and run.ability_charges == 0


@pytest.mark.parametrize("bad", [-1, "2", True, 1.5])
def test_a_save_with_a_bad_ability_cooldown_is_not_resumable(game, bad):
    run = _floor_as(game, "warden")
    run.ability_cooldown = bad
    game.save_run()
    assert save_state.load_run(game.save_path) is None


def test_a_daily_run_always_gets_the_default_commanders_ability_ready(game):
    game.start_new_run(is_daily=True, commander="stormcaller")
    run = game.active_run
    assert run.commander == DEFAULT_COMMANDER
    assert game.current_ability is ABILITIES[COMMANDERS[DEFAULT_COMMANDER].ability]
    assert run.ability_cooldown == 0 and run.ability_charges == 0
