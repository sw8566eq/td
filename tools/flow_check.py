"""Flow check -- a scripted, end-to-end run through every screen of a run.

A bot plays whole runs headless (one per Commander): it picks map nodes at
random, builds and upgrades towers in fights, takes rewards, shops, resolves
Events, uses Outposts (Rest/Forge/Drill/Move on), Armories and Treasures,
and saves now and then -- invulnerable in fights, since this checks that the
run's state machine never crashes or gets stuck (act transitions, trophy
rewards, the endless final boss), not balance. Dev-only, excluded from
coverage; writes nothing outside a temp directory.

    python tools/flow_check.py          # one run per Commander
    python tools/flow_check.py 12       # twelve runs (Commanders cycle)
"""

import collections
import os
import pathlib
import random
import sys
import tempfile
import traceback

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "tools"))

import pygame
from conftest import make_game
from tower_bench import _candidate_anchors, _coverage

from core.game import GameState
from entities.tower import TOWER_TYPES


def play(seed, commander):
    rng = random.Random(seed)
    game = make_game(pathlib.Path(tempfile.mkdtemp()))
    game.start_new_run(seed=seed, commander=commander)
    seen = collections.Counter()
    for tick in range(200000):
        st = game.state; seen[st.name] += 1
        if st == GameState.MAP:
            avail = list(game._available_node_ids())
            if not avail: return seen, "stuck-map"
            game._enter_node(rng.choice(avail))
        elif st == GameState.EVENT:
            if game.event_phase == "choose":
                game._resolve_event_choice(rng.randrange(len(game.event_options)))
            else:
                game._leave_event() if game.event_is_blessing else game._finish_node(game.active_run.current_node_id)
        elif st == GameState.PLAYING:
            game.economy.invulnerable = True  # exercise the flow, not the balance
            game.economy.gold += 50
            if not game.towers:
                path_points = [game.grid.tile_to_pixel_center(*c) for c in game.grid.path_cells]
                names = [n for n in game._active_tower_names() if TOWER_TYPES[n].ATTACKS]
                for i in range(14):
                    name = names[i % len(names)]
                    cls = TOWER_TYPES[name]; game.selected_tower_name = name
                    for anchor in sorted(_candidate_anchors(game, cls), key=lambda a: -_coverage(game, cls, a, path_points))[:80]:
                        if game.try_place_tower(*anchor):
                            break
                for t in list(game.towers):
                    while game.try_upgrade_tower(t): pass
            for _ in range(60):
                game.wave_manager.skip_delay(); game.update(1/20)
                if game.state != GameState.PLAYING: break
            if game.active_run.is_final_floor and game.wave_manager.wave_index > 12:
                return seen, f"reached endless, act {game.active_run.act+1}"
        elif st == GameState.FLOOR_CLEARED:
            game._handle_keydown(pygame.K_SPACE)
        elif st == GameState.REWARD:
            cards = game._reward_cards()
            for i in range(len(cards)):
                if game._reward_card_available(i) and rng.random() < 0.7:
                    game._take_reward_card(i)
            game._leave_reward_screen()
        elif st == GameState.DRAFT:
            if game.draft_choices: game._try_buy_shop_item(0)
            game._try_buy_shop_module(); game._try_buy_shop_potion()
            game._finish_node(game.active_run.current_node_id)
        elif st == GameState.REST:
            if game.rest_phase == "choose":
                game._choose_rest_option(rng.choice([0, 1, 2, 3]))
                if game.rest_phase in ("smith", "drill"):
                    choices, _ = game.rest_picker()
                    (game._drill_tower if game.rest_phase == "drill" else game._forge_tower)(choices[0])
            else:
                game._finish_node(game.active_run.current_node_id)
        elif st == GameState.ARMORY:
            game._take_armory_offer(0)
        elif st == GameState.TREASURE:
            game._finish_node(game.active_run.current_node_id)
        elif st == GameState.GAME_OVER:
            return seen, f"game over act {game.active_run.act+1} floors {game.active_run.floors_cleared}"
        else:
            return seen, f"unexpected state {st.name}"
        if game.can_save_run() and rng.random() < 0.01:
            game.save_run()
        game.render() if tick % 50 == 0 else None
    return seen, "tick limit"

if __name__ == "__main__":
    from run.commanders import COMMANDER_ORDER
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else len(COMMANDER_ORDER)
    crashed = False
    for seed in range(runs):
        commander = COMMANDER_ORDER[seed % len(COMMANDER_ORDER)]
        try:
            seen, outcome = play(seed, commander)
            print(seed, commander, outcome, dict(seen))
        except Exception:  # noqa: BLE001 -- reporting any crash is this tool's whole job
            print(seed, commander, "CRASH")
            traceback.print_exc(limit=6)
            crashed = True
    sys.exit(1 if crashed else 0)
