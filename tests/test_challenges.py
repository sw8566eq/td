"""Tests for the Proving Grounds -- run/challenges.py and how Game rolls,
enforces, rewards, saves and shows a challenge node's constraint."""

import json
import pathlib
import random

import pygame
import pytest
from conftest import clear_mouse_mock, finish_all_waves, make_game, mock_mouse_pos
from test_run import _begin_run_with_map

from core.game import GameState
from entities.tower import TOWER_TYPES
from persistence import save_state
from presentation import ui
from run import challenges, run_escalation
from run.challenges import CHALLENGES, ChallengeRoll


def _seed_with_challenge(game, key, node_types=("challenge", "combat"), **overrides):
    """A seed whose row-0 Proving Grounds rolls `key` -- searched, not
    hardcoded, so this doesn't depend on the rng stream's exact values."""
    for seed in range(300):
        run = _begin_run_with_map(game, list(node_types), seed=seed, lives=20, **overrides)
        if game._node_challenge(run, run.map.node("0-0")).challenge.key == key:
            return run
    raise AssertionError(f"no seed in range rolls {key}")


def _enter_challenge(game, key, **overrides):
    run = _seed_with_challenge(game, key, **overrides)
    game._enter_node("0-0")
    assert game.state == GameState.PLAYING
    return run


def _place(game, name):
    game.selected_tower_name = name
    for row in range(40):
        for col in range(60):
            if game._is_buildable_for(TOWER_TYPES[name], col, row) and game.try_place_tower(col, row):
                return True
    return False


def _clear_floor(game):
    finish_all_waves(game)
    game.update(dt=0.01)
    assert game.state == GameState.FLOOR_CLEARED


# --- The pure module ---

def test_every_challenge_is_described_and_keyed_consistently():
    for key, challenge in CHALLENGES.items():
        assert challenge.key == key and challenge.display_name and challenge.description


def test_roll_is_deterministic_and_draws_allowed_towers_after_the_challenge():
    first = challenges.roll_for_node(random.Random(5), ["a", "b", "c"])
    assert first == challenges.roll_for_node(random.Random(5), ["a", "b", "c"])
    # The challenge pick is the rng's first draw, whatever the candidates.
    assert first.challenge == challenges.roll_for_node(random.Random(5), []).challenge


def test_narrow_front_allows_exactly_its_count_and_never_restricts_a_small_pool():
    narrow = CHALLENGES["narrow_front"]
    rng = random.Random(0)
    for _ in range(20):
        roll = challenges.roll_for_node(rng, ["a", "b", "c", "d"])
        if roll.challenge is narrow:
            assert len(roll.allowed_towers) == narrow.allowed_tower_count
            assert roll.allowed_towers <= {"a", "b", "c", "d"}
    # roll_for_node with too few candidates leaves the build list open.
    for seed in range(60):
        roll = challenges.roll_for_node(random.Random(seed), ["a", "b"])
        assert roll.allowed_towers is None


def test_apply_to_escalation_scales_speed_and_gold_only():
    base = run_escalation.FloorEscalation(1.5, 1.0, 1.0, 1.2)
    result = challenges.apply_to_escalation(base, CHALLENGES["double_time"])
    assert result.enemy_speed_multiplier == pytest.approx(1.35)
    assert result.enemy_gold_multiplier == pytest.approx(1.5)
    assert (result.enemy_hp_multiplier, result.starting_gold_multiplier) == (1.5, 1.2)


def test_refusals_and_status_lines():
    names = {"a": "Alpha", "b": "Beta"}
    crew = ChallengeRoll(CHALLENGES["skeleton_crew"])
    assert challenges.placement_refusal(crew, "a", 3, names) is None
    assert "at most 4" in challenges.placement_refusal(crew, "a", 4, names)
    narrow = ChallengeRoll(CHALLENGES["narrow_front"], frozenset({"a", "b"}))
    assert challenges.placement_refusal(narrow, "a", 9, names) is None
    assert challenges.placement_refusal(narrow, "c", 0, names) == "Narrow Front: only Alpha and Beta can be built"
    assert challenges.upgrade_refusal(crew) is None
    assert challenges.upgrade_refusal(ChallengeRoll(CHALLENGES["no_upgrades"])) is not None
    assert narrow.summary(names).endswith("Allowed: Alpha, Beta.")
    assert challenges.status_line(crew, 2, 0, False) == "Skeleton Crew: 2/4 towers"
    assert challenges.status_line(narrow, 0, 0, False) == "Narrow Front: 2 types"
    gate = ChallengeRoll(CHALLENGES["glass_gate"])
    assert challenges.status_line(gate, 0, 1, False) == "Glass Gate: 1/3 leaks"
    assert challenges.status_line(gate, 0, 4, True) == "Glass Gate: FAILED"
    assert challenges.status_line(ChallengeRoll(CHALLENGES["fog_of_war"]), 0, 0, False) == "Fog of War"
    assert challenges.bonus_shop_currency(4) > challenges.bonus_shop_currency(0) > 0


def test_every_sidebar_status_line_fits_the_sidebar(game):
    width = ui.settings.PANEL_WIDTH - 2 * ui.PANEL_PADDING
    for challenge in CHALLENGES.values():
        roll = ChallengeRoll(challenge, frozenset({"a", "b"}) if challenge.allowed_tower_count else None)
        for failed in (False, True):
            text = challenges.status_line(roll, 4, 3, failed)
            assert game.small_font.size(text)[0] <= width, text
    assert ui.CHALLENGE_STATUS_Y > ui.SELL_BUTTON_TOP + ui.ACTION_BUTTON_HEIGHT  # clear of the stats panel


# --- Game: rolling and showing it ---

def test_only_challenge_nodes_roll_a_challenge_and_the_map_tooltip_names_it(game):
    run = _seed_with_challenge(game, "skeleton_crew")
    assert game._node_challenge(run, run.map.node("1-0")) is None
    assert set(game.map_node_challenges) == {"0-0"}
    text = game.map_node_challenges["0-0"]
    assert text.startswith("Skeleton Crew:")
    title, body = ui.map_node_tooltip_lines(game.small_font, run.map.node("0-0"), challenge_text=text)
    assert title == "Proving Grounds"
    assert any("Skeleton Crew" in line for line in body)
    mock_mouse_pos(game.map_node_rects["0-0"].center)
    try:
        game.render()  # the hovered tooltip draws
    finally:
        clear_mouse_mock()


def test_narrow_front_tooltip_lists_the_allowed_towers(game):
    run = _seed_with_challenge(game, "narrow_front")
    roll = game._node_challenge(run, run.map.node("0-0"))
    assert roll.allowed_towers is not None and len(roll.allowed_towers) == 2
    for name in roll.allowed_towers:
        assert TOWER_TYPES[name].display_name in game.map_node_challenges["0-0"]


def test_challenge_is_armed_for_the_fight_and_cleared_for_practice(game):
    _enter_challenge(game, "fog_of_war")
    assert game.active_challenge.challenge.key == "fog_of_war"
    assert game.renderer._challenge_status_text() == ["Proving Grounds", "Fog of War"]
    game.load_level(1, sandbox=True)
    assert game.active_challenge is None


# --- Game: each constraint's enforcement ---

def test_skeleton_crew_blocks_a_fifth_tower_and_says_why(game):
    _enter_challenge(game, "skeleton_crew")
    game.economy.unlimited_gold = True
    for _ in range(4):
        assert _place(game, "basic")
    toasts_before = len(game.achievement_toasts)
    assert not _place(game, "basic")
    assert len(game.towers) == 4
    assert any("at most 4" in toast.text for toast in game.achievement_toasts[toasts_before:])
    # A repeat refusal doesn't stack a second identical toast.
    count = sum("at most 4" in toast.text for toast in game.achievement_toasts)
    assert not _place(game, "basic")
    assert sum("at most 4" in toast.text for toast in game.achievement_toasts) == count
    # Selling one frees a slot again.
    game.try_sell_tower(game.towers[0])
    assert _place(game, "basic")


def test_narrow_front_only_builds_its_allowed_types(game):
    run = _enter_challenge(game, "narrow_front")
    game.economy.unlimited_gold = True
    allowed = game.active_challenge.allowed_towers
    blocked = [name for name in run.unlocked_towers if name not in allowed]
    assert blocked
    assert not _place(game, blocked[0])
    assert any("only" in toast.text for toast in game.achievement_toasts)
    assert _place(game, min(allowed))


def test_no_upgrades_blocks_upgrading_and_specializing(game):
    _enter_challenge(game, "no_upgrades")
    game.economy.unlimited_gold = True
    assert _place(game, "basic")
    tower = game.towers[0]
    assert not game.try_upgrade_tower(tower)
    assert tower.level == 1
    assert any("no upgrades" in toast.text for toast in game.achievement_toasts)
    key = next(iter(tower.SPECIALIZATIONS))
    while tower.level < tower.MAX_LEVEL:
        tower.upgrade()
    assert not game.try_specialize_tower(tower, key)
    assert tower.specialization is None


def test_plain_fights_still_upgrade(game):
    _begin_run_with_map(game, ["combat", "combat"], lives=20)
    game._enter_node("0-0")
    game.economy.unlimited_gold = True
    assert _place(game, "basic")
    assert game.try_upgrade_tower(game.towers[0])


def test_other_challenges_still_upgrade(game):
    _enter_challenge(game, "skeleton_crew")
    game.economy.unlimited_gold = True
    assert _place(game, "basic")
    assert game.try_upgrade_tower(game.towers[0])


def test_double_time_speeds_enemies_and_raises_their_gold(game):
    run = _seed_with_challenge(game, "double_time")
    plain = _begin_run_with_map(game, ["combat", "combat"], seed=run.seed, lives=20)
    game._enter_node("0-0")
    speed, gold = game.wave_manager.enemy_speed_multiplier, game.wave_manager.enemy_gold_multiplier
    game.active_run = run
    game._enter_map()
    game._enter_node("0-0")
    assert plain is not run
    assert game.wave_manager.enemy_speed_multiplier == pytest.approx(speed * 1.35)
    assert game.wave_manager.enemy_gold_multiplier == pytest.approx(gold * 1.5)
    # ... and the map's threat readout already says so.
    assert game.map_node_threats["0-0"][1] == pytest.approx(game._node_threat(run, run.map.node("0-0"))[1])


def test_glass_gate_caps_lives_lost_and_fails_on_the_fourth_leak(game):
    run = _enter_challenge(game, "glass_gate")
    start = game.economy.lives
    for _ in range(3):
        game._lose_a_life()
    assert game.economy.lives == start - 3 and not run.challenge_failed
    game._lose_a_life()
    game._lose_a_life()
    assert game.economy.lives == start - 3  # the run loses at most 3 here
    assert run.challenge_failed and run.challenge_leaks == 5
    assert any("broken" in toast.text for toast in game.achievement_toasts)
    assert game.renderer._challenge_status_text() == ["Proving Grounds", "Glass Gate: FAILED"]


def test_a_leak_through_update_counts_against_glass_gate(game):
    run = _enter_challenge(game, "glass_gate")
    game.wave_manager.skip_delay()
    for _ in range(200):
        game.update(dt=0.05)
        if game.enemies:
            break
    assert game.enemies
    leaks_before = run.challenge_leaks  # nothing can have leaked this early
    assert leaks_before == 0
    game.enemies = game.enemies[:1]
    game.enemies[0].reached_goal = True
    game.update(dt=0.0)
    assert run.challenge_leaks == 1


def test_leaks_outside_a_challenge_cost_lives_as_usual(game):
    run = _begin_run_with_map(game, ["combat", "combat"], lives=20)
    game._enter_node("0-0")
    start = game.economy.lives
    for _ in range(5):
        game._lose_a_life()
    assert game.economy.lives == start - 5 and run.challenge_leaks == 0


def test_fog_of_war_hides_the_wave_preview_and_range_rings(game, monkeypatch):
    _enter_challenge(game, "fog_of_war")
    game.economy.unlimited_gold = True
    assert _place(game, "basic")
    previews, rings = [], []
    real_hud = ui.draw_hud
    monkeypatch.setattr(ui, "draw_hud", lambda *a, **k: previews.append(a[11]) or real_hud(*a, **k))
    monkeypatch.setattr(ui, "draw_tower_range_preview", lambda *a, **k: rings.append(a))
    monkeypatch.setattr(ui, "draw_range_preview", lambda *a, **k: rings.append(a))
    game.selected_tower = game.towers[0]
    game.selected_tower_name = "basic"
    mock_mouse_pos((10, 10))
    try:
        game.render()
    finally:
        clear_mouse_mock()
    assert previews == [None] and rings == []


def test_range_rings_show_outside_fog_of_war(game, monkeypatch):
    _enter_challenge(game, "skeleton_crew")
    game.economy.unlimited_gold = True
    assert _place(game, "basic")
    rings = []
    monkeypatch.setattr(ui, "draw_tower_range_preview", lambda *a, **k: rings.append(a))
    game.selected_tower = game.towers[0]
    game.render()
    assert rings


# --- Game: reward on success, forfeit on failure ---

def test_a_won_challenge_pays_currency_and_offers_a_relic_choice(game):
    run = _enter_challenge(game, "skeleton_crew")
    before = run.shop_currency
    _clear_floor(game)
    bonus = challenges.bonus_shop_currency(run.depth_of(0))
    assert run.shop_currency >= before + bonus
    assert any("Proving Grounds won" in toast.text for toast in game.achievement_toasts)
    from progression import achievements
    assert achievements.load_achievements(game.achievements_path)["counters"]["challenges_won"] == 1
    game._handle_keydown(pygame.K_SPACE)
    assert game.state == GameState.REWARD
    choices = game.reward.challenge_relic_choices
    assert len(choices) == challenges.RELIC_CHOICE_COUNT
    cards = game._reward_cards()
    indices = [i for i, (kind, _key) in enumerate(cards) if kind == "challenge_relic"]
    assert game.renderer._challenge_reward_note(run.map.node("0-0")).startswith("Proving Grounds won")
    game.render()
    game._take_reward_card(indices[0])
    assert cards[indices[0]][1] in run.relics
    assert not game._reward_card_available(indices[1])  # pick one
    game._take_reward_card(indices[1])
    assert cards[indices[1]][1] not in run.relics


def test_a_failed_challenge_forfeits_the_bonus_but_the_fight_goes_on(game):
    run = _enter_challenge(game, "glass_gate")
    for _ in range(4):
        game._lose_a_life()
    assert game.state == GameState.PLAYING  # the fight continues normally
    _clear_floor(game)
    assert not any("Proving Grounds won" in toast.text for toast in game.achievement_toasts)
    game._handle_keydown(pygame.K_SPACE)
    assert game.state == GameState.REWARD  # the ordinary tower cards are still on offer
    assert game.reward.challenge_relic_choices == ()
    assert game.renderer._challenge_reward_note(run.map.node("0-0")) == "Proving Grounds failed: no bonus this time"
    game.render()


def test_the_bonus_matches_a_plain_fight_plus_the_challenge_payout(game):
    run = _seed_with_challenge(game, "no_upgrades")
    game._enter_node("0-0")
    game.economy.gold = 0
    _clear_floor(game)
    with_bonus = run.shop_currency
    plain = _begin_run_with_map(game, ["combat", "combat"], seed=run.seed, lives=20)
    game._enter_node("0-0")
    game.economy.gold = 0
    _clear_floor(game)
    assert with_bonus - plain.shop_currency == challenges.bonus_shop_currency(0)


def test_a_restart_clears_a_broken_challenge(game):
    run = _enter_challenge(game, "glass_gate")
    for _ in range(4):
        game._lose_a_life()
    assert run.challenge_failed
    game.state = GameState.PAUSED
    game.reset()
    assert not run.challenge_failed and run.challenge_leaks == 0


# --- Save/resume ---

def test_mid_fight_save_keeps_the_challenge_and_its_leaks(game, tmp_path):
    run = _enter_challenge(game, "glass_gate")
    game._lose_a_life()
    game._lose_a_life()
    assert game.save_run()
    fresh = make_game(pathlib.Path(tmp_path))
    fresh.resume_saved_run(save_state.load_run(fresh.save_path))
    assert fresh.active_challenge == game.active_challenge
    assert fresh.active_run.challenge_leaks == 2
    assert run.challenge_leaks == 2


def test_map_checkpoint_resume_re_derives_the_same_challenge(game, tmp_path):
    run = _seed_with_challenge(game, "narrow_front")
    expected = game._node_challenge(run, run.map.node("0-0"))
    game._enter_node("0-0")  # autosaves the committed node
    fresh = make_game(pathlib.Path(tmp_path))
    fresh._continue_saved_run()
    assert fresh.state == GameState.PLAYING
    assert fresh.active_challenge == expected


def test_reward_screen_reopened_from_a_checkpoint_keeps_the_relic_choice(game, tmp_path):
    _enter_challenge(game, "skeleton_crew")
    _clear_floor(game)
    game._handle_keydown(pygame.K_SPACE)
    offered = game.reward
    fresh = make_game(pathlib.Path(tmp_path))
    fresh._continue_saved_run()
    assert fresh.state == GameState.REWARD and fresh.reward == offered
    assert fresh.reward.challenge_relic_choices


def test_older_saves_without_challenge_fields_still_load(game):
    _enter_challenge(game, "glass_gate")
    game.save_run()
    path = pathlib.Path(game.save_path)
    data = json.loads(path.read_text())
    del data["run"]["challenge_leaks"]
    del data["run"]["challenge_failed"]
    path.write_text(json.dumps(data))
    loaded = save_state.load_run(game.save_path)
    assert loaded["run"].challenge_leaks == 0 and loaded["run"].challenge_failed is False


@pytest.mark.parametrize("field, value", [("challenge_leaks", -1), ("challenge_leaks", "2"), ("challenge_failed", 1)])
def test_corrupt_challenge_fields_are_not_resumable(game, field, value):
    _enter_challenge(game, "glass_gate")
    game.save_run()
    path = pathlib.Path(game.save_path)
    data = json.loads(path.read_text())
    data["run"][field] = value
    path.write_text(json.dumps(data))
    assert save_state.load_run(game.save_path) is None




def test_skeleton_crew_greys_out_the_build_menu_once_full(game):
    _enter_challenge(game, "skeleton_crew")
    game.economy.gold = 10_000
    assert game.challenge_blocked_towers() == frozenset()
    while len(game.towers) < CHALLENGES["skeleton_crew"].max_towers:
        assert _place(game, "basic")
    assert game.challenge_blocked_towers() == frozenset(game.button_rects)
    game.render()


def test_no_challenge_blocks_nothing(game):
    _begin_run_with_map(game, ["combat"], seed=1, lives=20)
    game._enter_node("0-0")
    assert game.challenge_blocked_towers() == frozenset()
