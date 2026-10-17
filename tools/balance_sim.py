"""Balance simulator -- a competent bot plays whole runs, for real.

Unlike tools/flow_check.py (invulnerable, random choices: does the state
machine hold up?) this plays to win, with real battle gold and real lives,
and reports where runs die. It is a dev-only measuring stick for difficulty
tuning, excluded from coverage like the rest of tools/, and writes nothing
outside a temp directory (each Game is built by tests/conftest.make_game).

The policy, in brief (see docs/agents/tooling.md "Balance simulator"):

* Placement: every path cell gets a traffic weight from sampled enemy
  routes (merge points carry more routes), tilted toward the late part of
  each route. A spot's value is the weight it covers, with diminishing
  returns on cells other towers already cover, so later towers spread to
  uncovered lanes instead of stacking on one choke.
* Spending: every decision tick it compares "new tower T at its best spot"
  with "upgrade/specialize tower X" by estimated power gained per gold,
  with a bonus for a role the board lacks (anti-air when flyers come, slow,
  splash) and a mild penalty for repeating a type. It keeps a small reserve
  once the fight is under way and banks gold through the last wave.
* Potions and the Commander's ability: offensive ones when leaks start or
  a boss pushes deep, Mending Salve when low, Liquid Gold at the start of
  a floor.
* Between fights: map nodes scored by lives and shop currency (Outpost
  when hurt, Elite only when healthy), relics always, tower cards for a
  missing role, Outposts heal when hurt else forge the most-used tower.

    python tools/balance_sim.py                    # 8 seeds x every Commander
    python tools/balance_sim.py --seeds 20 --jobs 6
    python tools/balance_sim.py --account fresh    # a brand-new account's pools
    python tools/balance_sim.py --json out.json    # also dump every run record
    python tools/balance_sim.py --set run.run_escalation.ELITE_HP_MULTIPLIER=1.15   # try a knob
    python tools/balance_sim.py --calibrate        # re-measure CALIBRATED_POWER_PER_GOLD
"""

import argparse
import collections
import json
import os
import pathlib
import random
import statistics
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

STEP = 1 / 20
DECISION_INTERVAL = 0.5
FIGHT_LIMIT_SECONDS = 2400
ENDLESS_LIMIT_SECONDS = 9000  # the final boss's endless tail grows every wave, so it gets longer
ENDLESS_WAVE_CAP = 40  # stop the final boss's endless tail here and call it "survived long"
RESERVE_AFTER_WAVE_ONE = 15
EARLY_CALLS = True
# Calibrated battle-gold income counts as this much damage per gold: income
# arrives over the whole floor and only becomes damage once it's spent.
INCOME_WEIGHT = 15.0
LATE_ROUTE_TILT = 0.8  # route weight runs 1.0 at the spawn to 1.0 + this at the goal
COVER_DIMINISH = 0.3  # a cell already covered n times counts 1 / (1 + n * this)
ROLE_BONUS = 1.8
SAVE_FOR_BEST = 0.4  # buy the best affordable action if it's at least this good, relative to the best
REPEAT_PENALTY = 1.0
OFFENSIVE_POTIONS = ("fire_bomb", "venom_vial", "frost_flask", "smoke_bomb", "marking_dust", "overclock_elixir",
                     "tether_flare")
OPENING_POTIONS = ("liquid_gold",)  # drunk the moment a floor loads
BUILT_POTIONS = ("field_promotion",)  # drunk once the opening board is down
REPAIR_POTIONS = ("mortar_mix",)


# --- Tower knowledge -------------------------------------------------------

def _hits_flying(cls):
    value = None
    for klass in cls.__mro__:
        if "can_target_flying" in klass.__dict__:
            value = klass.__dict__["can_target_flying"]
            break
    return value is True  # Cannon's property means "only with a relic"


def roles_of(cls):
    roles = set()
    if cls.IS_SUPPORT or not cls.ATTACKS:
        return {"support"} if cls.IS_SUPPORT else {"wall"}
    if _hits_flying(cls):
        roles.add("air")
    if getattr(cls, "slow_factor", None):
        roles.add("slow")
    if getattr(cls, "splash_radius", 0) or getattr(cls, "chain_range", 0):
        roles.add("splash")
    return roles


def is_amplifier(cls):
    return bool(getattr(cls, "slow_factor", None) or getattr(cls, "mark_damage_multiplier", 0))


def _type_key(cls):
    from entities.tower import TOWER_TYPES
    return next((key for key, klass in TOWER_TYPES.items() if klass is cls), None)


# Measured by `--calibrate` (marginal damage per gold of one more level-1
# tower on a reference board); rerun it after changing tower stats. The bot
# reads it as each type's damage-per-gold prior.
CALIBRATED_POWER_PER_GOLD = {
    "basic": (20.6, 0.87), "cannon": (17.8, 0.35), "frost": (4.0, 0.12), "knockback": (8.4, 0.22),
    "lightning": (17.7, 0.43), "sniper": (16.7, 0.76), "poison": (17.6, 0.57), "siphon": (3.9, 2.03),
    "support": (-0.2, 0.01), "beam": (15.5, 0.67), "beacon": (4.0, 0.08), "overload_cannon": (10.2, 0.34),
    "mortar": (11.5, 0.46), "barricade": (-2.5, 0.21), "spike_trap": (12.3, 0.21), "tar_pit": (5.9, 0.48),
    "harpoon": (8.4, 0.38),
}


def est_power(cls):
    """A level-1 tower's value in rough damage-per-second units: the
    calibrated table when the type is in it, else a formula from its stats."""
    if cls.IS_SUPPORT or not cls.ATTACKS:
        return 0.0
    name = _type_key(cls)
    if name in CALIBRATED_POWER_PER_GOLD:
        damage, income = CALIBRATED_POWER_PER_GOLD[name]
        return max(0.5, damage + INCOME_WEIGHT * income) * cls.cost / 80
    dps = cls.damage * cls.fire_rate
    if getattr(cls, "splash_radius", 0):
        dps *= 2.0
    if getattr(cls, "chain_range", 0):
        dps *= 2.5
    if getattr(cls, "poison_damage_per_tick", 0):
        dps += cls.poison_damage_per_tick / cls.poison_tick_interval * 1.5
    if getattr(cls, "max_ramp_multiplier", 0):
        dps *= 1.8
    if getattr(cls, "slow_factor", None):
        dps += 9.0
    if getattr(cls, "mark_damage_multiplier", 0):
        dps += 9.0
    if getattr(cls, "knockback_duration", 0):
        dps += 5.0
    if getattr(cls, "siphon_gold_fraction", 0):
        dps *= 1.4
    return max(dps, 3.0)


# --- One floor ---------------------------------------------------------------

class FloorBot:
    def __init__(self, game, rng):
        from entities.tower import TOWER_TYPES
        from world import pathing
        self.game = game
        self.types = TOWER_TYPES
        grid = game.grid
        level = game.level
        topo = game.wave_manager.topology
        spawn_counts = collections.Counter()
        flyers = 0
        for wave in level.wave_specs:
            for cell, comp in wave.items():
                spawn_counts[cell] += sum(comp.values())
                flyers += comp.get("flying", 0)
        self.has_flyers = flyers > 0
        weight = collections.Counter()
        samples = 12
        for spawn in level.spawn_cells:
            share = max(1, spawn_counts.get(spawn, 1))
            for _ in range(samples):
                route = pathing.sample_route(topo, spawn, level.branch_weights, rng)
                n = max(1, len(route) - 1)
                for i, cell in enumerate(route):
                    weight[cell] += share / samples * (1.0 + LATE_ROUTE_TILT * i / n)
        self.cells = list(weight)
        self.cell_weight = [weight[c] for c in self.cells]
        self.cell_px = [grid.tile_to_pixel_center(*c) for c in self.cells]
        self.cover = [0] * len(self.cells)
        per_tile = grid.subtiles_per_tile
        step = max(1, per_tile // 2)
        self.ground_anchors = [(col, row) for row in range(0, grid.sub_rows, step) for col in range(0, grid.sub_cols, step)]
        self.path_anchors = [(col * per_tile, row * per_tile) for col, row in self.cells]
        self._cover_cache = {}
        self._ideal_cache = {}
        self.tower_cells = {}  # id(tower) -> covered cell indices
        self.start_lives = game.economy.lives
        self.potion_cooldown = 0.0

    # coverage

    def _covered(self, cls, anchor, reach=None):
        footprint = self.game._footprint_for(cls)
        reach = reach if reach is not None else max(cls.range, 40)
        key = (anchor, footprint, round(reach), cls.MIN_RANGE)
        hit = self._cover_cache.get(key)
        if hit is None:
            pos = self.game.grid.anchor_to_pixel_center(*anchor, footprint_subtiles=footprint)
            lo, hi = cls.MIN_RANGE, reach
            hit = [i for i, p in enumerate(self.cell_px) if lo <= pos.distance_to(p) <= hi]
            self._cover_cache[key] = hit
        return hit

    def _spot_value(self, cells):
        return sum(self.cell_weight[i] / (1 + COVER_DIMINISH * self.cover[i]) for i in cells)

    def best_spot(self, cls):
        anchors = self.path_anchors if cls.PLACEMENT == "path" else self.ground_anchors
        # A slow or a mark only pays off where other towers already shoot,
        # so it chases existing coverage instead of avoiding it.
        amplifier = is_amplifier(cls)
        best = None
        for anchor in anchors:
            cells = self._covered(cls, anchor)
            if not cells:
                continue
            if amplifier:
                value = sum(self.cell_weight[i] * (0.3 + self.cover[i]) for i in cells)
            else:
                value = self._spot_value(cells)
            if best is not None and value <= best[1]:
                continue
            if self.game._is_buildable_for(cls, *anchor):
                best = (anchor, value)
        return best

    def _register(self, tower):
        cells = self._covered(type(tower), (tower.anchor_col, tower.anchor_row), reach=max(tower.range, 40))
        old = self.tower_cells.get(id(tower), [])
        for i in old:
            self.cover[i] -= 1
        for i in cells:
            self.cover[i] += 1
        self.tower_cells[id(tower)] = cells

    # spending

    def _role_mult(self, cls, counts):
        roles = roles_of(cls)
        attackers = sum(n for name, n in counts.items() if self.types[name].ATTACKS and not self.types[name].IS_SUPPORT)
        have = collections.Counter()
        for name, n in counts.items():
            for role in roles_of(self.types[name]):
                have[role] += n
        mult = 1.0
        if "air" in roles and self.has_flyers and have["air"] < 2:
            mult *= ROLE_BONUS
        if "slow" in roles and attackers >= 2 and have["slow"] < 1 + attackers // 6:
            mult *= ROLE_BONUS
        if "splash" in roles and attackers >= 1 and have["splash"] < 1 + attackers // 4:
            mult *= ROLE_BONUS
        return mult

    def _ideal(self, cls):
        """The best undiminished spot value `cls` could have on this map --
        what a spot's value is measured against, so a long-range tower isn't
        credited for covering path it can't shoot fast enough to use."""
        key = (cls.range, cls.MIN_RANGE, cls.PLACEMENT, self.game._footprint_for(cls))
        if key not in self._ideal_cache:
            anchors = self.path_anchors if cls.PLACEMENT == "path" else self.ground_anchors
            self._ideal_cache[key] = max(
                (sum(self.cell_weight[i] for i in self._covered(cls, a)) for a in anchors), default=1.0,
            ) or 1.0
        return self._ideal_cache[key]

    def _tower_power(self, tower):
        """A placed tower's current value: its type's power, its level, and
        how much of its ideal coverage it still has to itself."""
        cls = type(tower)
        cells = self.tower_cells.get(id(tower), [])
        spot = sum(self.cell_weight[i] / (1 + COVER_DIMINISH * max(0, self.cover[i] - 1)) for i in cells)
        level = tower._multiplier_table_for("damage")[tower.level]
        return est_power(cls) * level * min(1.0, spot / self._ideal(cls))

    def options(self):
        """Every affordable-or-not action as (value per gold, cost, action),
        best first."""
        game = self.game
        by_name = collections.Counter(_type_key(type(t)) for t in game.towers)
        attackers = [t for t in game.towers if t.ATTACKS and not t.IS_SUPPORT]
        opts = []
        for name in game._active_tower_names():
            cls = self.types[name]
            if cls.IS_SUPPORT:
                spot = self._best_support_spot(cls)
                if spot:
                    opts.append((spot[1] / cls.cost, cls.cost, ("place", name, spot[0])))
                continue
            if not cls.ATTACKS:  # Barricade: one, once the board can shoot what it holds
                if by_name[name] >= 1 or len(attackers) < 3:
                    continue
                spot = self.best_spot_for_wall(cls)
                if spot:
                    opts.append((spot[1] / cls.cost, cls.cost, ("place", name, spot[0])))
                continue
            spot = self.best_spot(cls)
            if spot is None:
                continue
            share = min(1.0, spot[1] / self._ideal(cls)) if not is_amplifier(cls) else 1.0
            value = est_power(cls) * share * self._role_mult(cls, by_name) * REPEAT_PENALTY ** by_name[name]
            opts.append((value / cls.cost, cls.cost, ("place", name, spot[0])))
        for t in attackers:
            base = self._tower_power(t)
            cost = t.upgrade_cost()
            if cost:
                mults = t._multiplier_table_for("damage")
                gain = mults[t.level + 1] / mults[t.level] - 1 + 0.1  # + the range bump
                opts.append((base * gain / cost, cost, ("upgrade", t)))
            elif t.can_specialize:
                key = self._spec_key(t)
                cost = t.specialization_cost()
                opts.append((base * 0.3 / cost, cost, ("specialize", t, key)))
        opts.sort(key=lambda o: -o[0])
        return opts

    def _spec_key(self, tower):
        def score(spec):
            m = spec["stat_multipliers"]
            return m.get("damage", 1) * m.get("fire_rate", 1) * (m.get("range", 1) ** 0.5)
        return max(tower.SPECIALIZATIONS, key=lambda k: score(tower.SPECIALIZATIONS[k]))

    def _best_support_spot(self, cls):
        best = None
        attackers = [t for t in self.game.towers if t.ATTACKS and not t.IS_SUPPORT]
        footprint = self.game._footprint_for(cls)
        for anchor in self.ground_anchors:
            pos = self.game.grid.anchor_to_pixel_center(*anchor, footprint_subtiles=footprint)
            near = [t for t in attackers if pos.distance_to(t.pos) <= cls.range]
            if not near:
                continue
            value = (cls.buff_damage_multiplier - 1) * sum(self._tower_power(t) for t in near)
            if (best is None or value > best[1]) and self.game._is_buildable_for(cls, *anchor):
                best = (anchor, value)
        return best

    def best_spot_for_wall(self, cls):
        best = None
        for anchor, cell_index in zip(self.path_anchors, range(len(self.cells)), strict=True):
            if self.cell_weight[cell_index] <= 0:
                continue
            # Holding enemies where the board shoots: worth a share of the
            # firepower covering that cell.
            shooters = [t for t in self.game.towers if cell_index in self.tower_cells.get(id(t), ())]
            value = 0.3 * sum(self._tower_power(t) for t in shooters)
            if (best is None or value > best[1]) and self.game._is_buildable_for(cls, *anchor):
                best = (anchor, value)
        return best

    def spend(self, reserve=0):
        """Buy actions best-first. If the best is out of reach, buy the best
        affordable one when it's nearly as good, else save toward the best.
        An action the floor refuses (a Proving Grounds constraint) is skipped."""
        game = self.game
        refused = set()
        for _ in range(40):
            opts = [o for o in self.options() if self._key(o[2]) not in refused]
            if not opts:
                return
            budget = game.economy.gold - reserve
            pick = next((o for o in opts if o[1] <= budget), None)
            if pick is None or pick[0] < SAVE_FOR_BEST * opts[0][0]:
                return
            if not self._do(pick[2]):
                refused.add(self._key(pick[2]))

    @staticmethod
    def _key(action):
        return (action[0], action[1] if action[0] == "place" else id(action[1]))

    def _do(self, action):
        game = self.game
        if action[0] == "place":
            _, name, anchor = action
            game.selected_tower_name = name
            before = len(game.towers)
            if not game.try_place_tower(*anchor) or len(game.towers) == before:
                return False
            self._register(game.towers[-1])
            return True
        if action[0] == "upgrade":
            ok = game.try_upgrade_tower(action[1])
        else:
            ok = game.try_specialize_tower(action[1], action[2])
        if ok:
            self._register(action[1])
        return ok

    # potions

    def use_ability(self):
        """Fire the Commander's ability when it's charged -- aimed, if it
        needs aiming, at the enemy furthest along its route."""
        game = self.game
        ability = getattr(game, "current_ability", None)
        if ability is None or game.active_run.ability_cooldown > 0 or not game.enemies:
            return
        lead = max(game.enemies, key=lambda e: e.wp_index / max(1, len(e.waypoints)))
        game.fire_ability((lead.pos.x, lead.pos.y) if ability.targeted else None)

    def use_potions(self, dt):
        game = self.game
        run = game.active_run
        self.potion_cooldown = max(0.0, self.potion_cooldown - dt)
        if not run.potions or self.potion_cooldown > 0:
            return
        from run import potions
        lives = game.economy.lives

        def usable(key):
            potion = potions.POTIONS[key]
            if potion.needs_enemies and not game.enemies:
                return False
            return potion.usable is None or potion.usable(game)

        def drink(slot, cooldown):
            game.use_potion(slot)
            self.potion_cooldown = cooldown

        for slot, key in enumerate(run.potions):
            timely = key in OPENING_POTIONS or key in REPAIR_POTIONS or (key in BUILT_POTIONS and game.towers)
            if timely and usable(key):
                return drink(slot, 1.0)
            if key == "mending_salve" and lives <= max(4, self.start_lives // 4):
                return drink(slot, 1.0)
        if not game.enemies:
            return
        deep = sum(1 for e in game.enemies if e.wp_index / max(1, len(e.waypoints)) > 0.6)
        boss_deep = any(e.IS_BOSS and e.wp_index / max(1, len(e.waypoints)) > 0.45 for e in game.enemies)
        lost = self.start_lives - lives
        if deep >= 5 or boss_deep or (lost >= 2 and deep >= 2) or lives <= 3:
            self.use_ability()
            for slot, key in enumerate(run.potions):
                if key in OFFENSIVE_POTIONS and usable(key):
                    return drink(slot, 4.0)


def play_floor(game, rng, stats):
    """Fight the loaded floor to a clear, a death, or (final boss) the endless
    cap. Returns True if it hit FIGHT_LIMIT_SECONDS instead."""
    from core.game import GameState
    from entities.waves import WaveState
    bot = FloorBot(game, rng)
    run = game.active_run
    bot.use_potions(0)
    bot.spend()
    game.wave_manager.skip_delay()
    elapsed = 0.0
    next_decision = 0.0
    authored = len(game.level.wave_specs)
    lives_at_wave_start = game.economy.lives
    wave_seen = 0
    limit = ENDLESS_LIMIT_SECONDS if run.is_final_floor else FIGHT_LIMIT_SECONDS
    while game.state == GameState.PLAYING and elapsed < limit:
        wm = game.wave_manager
        if wm.wave_index != wave_seen:
            wave_seen = wm.wave_index
            clean_wave = game.economy.lives >= lives_at_wave_start
            lives_at_wave_start = game.economy.lives
            bot.spend(reserve=RESERVE_AFTER_WAVE_ONE)
            # A clean wave and a board that has spent its gold: call the next
            # one early for the bonus, the way a confident player would.
            if clean_wave and wm.state == WaveState.BETWEEN_WAVES and EARLY_CALLS:
                game.call_next_wave()
        if elapsed >= next_decision:
            next_decision = elapsed + DECISION_INTERVAL
            bot.use_potions(DECISION_INTERVAL)
            # Bank the rest (it converts to shop currency) only once the last
            # authored wave is fully out and nothing has leaked this wave.
            banking = (not run.is_final_floor and wm.wave_index >= authored - 1
                       and not wm._has_queued_enemies() and game.economy.lives >= lives_at_wave_start)
            if not banking:
                bot.spend(reserve=RESERVE_AFTER_WAVE_ONE if wm.wave_index >= 1 else 0)
        game.update(STEP)
        elapsed += STEP
        if run.is_final_floor and run.endless_waves_cleared >= ENDLESS_WAVE_CAP:
            break
    for tower in game.towers + game.sold_towers:
        name = _type_key(type(tower)) or type(tower).__name__
        stats["damage"][name] += tower.damage_dealt
        stats["kills"][name] += tower.kills
        stats["built"][name] += 1
    return elapsed >= limit


# --- Between fights ----------------------------------------------------------

NODE_SCORES = {"treasure": 6, "event": 2.6, "armory": 2.4, "combat": 2.0}


def pick_node(game, rng):
    run = game.active_run
    lives = run.lives
    healthy = run.lives_captured and lives >= 14
    scored = []
    for node_id in game._available_node_ids():
        node = run.map.node(node_id)
        t = node.node_type
        if t == "rest":
            score = 7 if lives < 14 else 1.5
        elif t == "shop":
            score = 4.5 if run.shop_currency >= 18 else 1.2
        elif t == "elite":
            score = 3.2 if healthy else 0.3
        elif t == "challenge":
            score = 2.8 if healthy else 0.5
        else:
            score = NODE_SCORES.get(t, 2)
        scored.append((score + rng.random() * 0.3, node_id))
    return max(scored)[1]


def _tower_card_value(game, name, memory):
    from entities.tower import TOWER_TYPES
    run = game.active_run
    cls = TOWER_TYPES[name]
    held_roles = collections.Counter(r for n in run.unlocked_towers for r in roles_of(TOWER_TYPES[n]))
    value = est_power(cls) / cls.cost * 10
    for role in roles_of(cls):
        if role in ("air", "slow", "splash") and held_roles[role] == 0:
            value += 4
        if role == "support" and len(run.unlocked_towers) >= 4 and held_roles["support"] == 0:
            value += 2
    if not cls.ATTACKS and not cls.IS_SUPPORT:
        value = 0.5
    return value


def pick_reward(game, memory):
    cards = game._reward_cards()
    run = game.active_run
    best_tower = None
    for i, (kind, key) in enumerate(cards):
        if kind in ("relic", "potion", "module"):
            game._take_reward_card(i)
    for i, (kind, _key) in enumerate(cards):
        if kind == "challenge_relic":  # a pick-one relic row: the first is as good a guess as any
            game._take_reward_card(i)
            break
    boss = [(i, key) for i, (kind, key) in enumerate(cards) if kind == "boss_relic"]
    if boss:
        from run import relics
        def boss_score(key):
            relic = relics.RELICS[key]
            score = 3.0
            if relic.blocks_shop_income:
                score -= 1.5
            if relic.blocks_rest_heal:
                score -= 1.0 if run.lives >= 15 else 2.5
            if relic.blocks_potions:
                score -= 0.5
            if relic.starting_lives_bonus < 0:
                score -= 0.2 * -relic.starting_lives_bonus
            return score
        i, _ = max(boss, key=lambda pair: boss_score(pair[1]))
        game._take_reward_card(i)
    for i, (kind, key) in enumerate(cards):
        if kind == "tower":
            value = _tower_card_value(game, key, memory)
        elif kind == "forge":
            value = 2.5 + memory["placed"].get(key, 0) * 0.1
        else:
            continue
        if best_tower is None or value > best_tower[0]:
            best_tower = (value, i)
    if best_tower:
        game._take_reward_card(best_tower[1])
    game._leave_reward_screen()


def shop(game, memory):
    from run import relics
    run = game.active_run
    if relics.held_curses(run):
        game._try_remove_curse()
    order = sorted(
        range(len(game.draft_choices)),
        key=lambda i: (game.draft_choices[i].kind != "relic",
                       -(_tower_card_value(game, game.draft_choices[i].key, memory)
                         if game.draft_choices[i].kind == "tower" else 0)),
    )
    for i in order:
        item = game.draft_choices[i]
        if item.kind == "tower" and _tower_card_value(game, item.key, memory) < 4 and len(run.unlocked_towers) >= 5:
            continue
        game._try_buy_shop_item(i)
    game._try_buy_shop_potion()
    game._try_buy_shop_module()
    game._finish_node(run.current_node_id)


def pick_event_option(game):
    run = game.active_run
    best = None
    for i, option in enumerate(game.event_options):
        if not game._can_afford_event_option(option):
            continue
        score = 0.0
        score += 3.0 * option.grant_relic + 2.5 * option.extra_relic + 4.0 * option.grant_boss_relic
        score += 1.6 * option.unlock_random_tower + 1.5 * option.forge_random_tower + 0.8 * option.grant_potion
        score += 1.5 * option.grant_module + option.tower_xp / 60
        score += option.shop_currency_delta / 8
        life_value = 0.6 if run.lives < 12 else 0.25
        score += option.lives_delta * life_value
        score -= 2.5 * option.add_curse - 2.0 * option.remove_curse
        score -= 2.5 * option.relic_cost + 0.8 * option.potion_cost
        if best is None or score > best[0]:
            best = (score, i)
    return best[1] if best else 0


def rest(game, memory):
    run = game.active_run
    if run.lives < 15 and not game.rest_heal_blocked:
        game._choose_rest_option(0)
        return
    if game.rest_smith_choices:
        game._choose_rest_option(1)
        choices, _ = game.rest_picker()
        game._forge_tower(max(choices, key=lambda n: memory["placed"].get(n, 0)))
        return
    if game.rest_drill_choices:
        game._choose_rest_option(2)
        choices, _ = game.rest_picker()
        game._drill_tower(max(choices, key=lambda n: memory["placed"].get(n, 0)))
        return
    game._choose_rest_option(3)


# --- One run -----------------------------------------------------------------

def _prepare_account(tmp, account):
    if account != "veteran":
        return
    from progression import meta_progression
    state = {"counters": {}, "unlocked": set(meta_progression.ALL_UNLOCKS)}
    meta_progression.save_meta_progression(state, str(tmp / "meta_progression.json"))


def play_run(seed, commander, account="veteran"):
    from conftest import make_game

    from core.game import GameState
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="td-balance-"))
    _prepare_account(tmp, account)
    game = make_game(tmp)
    for hook in ("_record_achievement", "_record_achievement_max", "_record_level_cleared"):
        setattr(game, hook, lambda *args, **kwargs: None)
    rng = random.Random(f"bot:{seed}")
    game.start_new_run(seed=seed, commander=commander)
    game._enter_blessing()
    stats = {"damage": collections.Counter(), "kills": collections.Counter(), "built": collections.Counter()}
    endless_stats = {key: collections.Counter() for key in stats}
    memory = {"placed": collections.Counter()}
    floors = []
    outcome = None
    timeouts = 0
    for _tick in range(2000):
        st = game.state
        run = game.active_run
        if st == GameState.MAP:
            game._enter_node(pick_node(game, rng))
        elif st == GameState.EVENT:
            if game.event_phase == "choose":
                game._resolve_event_choice(pick_event_option(game))
            else:
                game._leave_event()
        elif st == GameState.PLAYING:
            node = run.map.node(run.current_node_id)
            lives_before = run.lives if run.lives_captured else game.economy.lives
            # The endless final boss is tallied apart: its unbounded tail would
            # otherwise swamp every other floor's tower shares.
            timeouts += play_floor(game, rng, endless_stats if run.is_final_floor else stats)
            for t in game.towers:
                memory["placed"][_type_key(type(t))] += 1
            died = game.state == GameState.GAME_OVER
            floors.append({
                "act": run.act + 1, "row": node.row, "depth": run.depth_of(node.row), "type": node.node_type,
                "level": node.level_id, "lives_before": lives_before,
                "lives_after": 0 if died else game.economy.lives,
                "gold_left": game.economy.gold, "died": died,
            })
            if died:
                outcome = "died"
                break
            if run.is_final_floor:
                outcome = "endless-cap" if run.endless_waves_cleared >= ENDLESS_WAVE_CAP else "endless-timeout"
                break
        elif st == GameState.FLOOR_CLEARED:
            game._enter_reward_screen()
        elif st == GameState.REWARD:
            pick_reward(game, memory)
        elif st == GameState.DRAFT:
            shop(game, memory)
        elif st == GameState.REST:
            if game.rest_phase == "choose":
                rest(game, memory)
            else:
                game._finish_node(run.current_node_id)
        elif st == GameState.ARMORY:
            best = max(range(len(game.armory_offers)),
                       key=lambda i: memory["placed"].get(game.armory_offers[i][1], 0))
            game._take_armory_offer(best)
        elif st == GameState.TREASURE:
            game._finish_node(run.current_node_id)
        elif st == GameState.GAME_OVER:
            outcome = "died"
            break
        else:
            outcome = f"unexpected:{st.name}"
            break
    run = game.active_run
    return {
        "seed": seed, "commander": commander, "outcome": outcome or "tick-limit",
        "act_reached": run.act + 1, "floors": floors, "endless_waves": run.endless_waves_cleared,
        "boss_defeated": run.boss_defeated, "relics": len(run.relics), "towers": list(run.unlocked_towers),
        "damage": dict(stats["damage"]), "kills": dict(stats["kills"]), "built": dict(stats["built"]),
        "timeouts": timeouts,
    }


def apply_overrides(overrides):
    """`--set module.NAME=value` experiments, applied inside each worker
    before it builds a Game (e.g. run.run_escalation._HP_GROWTH_PER_FLOOR=0.1)."""
    import ast
    import importlib
    for item in overrides:
        target, raw = item.split("=", 1)
        module, attr = target.rsplit(".", 1)
        setattr(importlib.import_module(module), attr, ast.literal_eval(raw))


def _play_star(args):
    *job, overrides = args
    apply_overrides(overrides)
    return play_run(*job)


# --- Calibration -------------------------------------------------------------

CALIBRATION_LEVELS = (3, 8)  # a winding single lane, and two lanes with flyers
CALIBRATION_HP = 3.0  # tough enough that the reference board leaks, soft enough that kills (and overkill) happen
CALIBRATION_REFERENCE = ("basic", "basic", "basic")
CALIBRATION_SEEDS = (0, 1)


def _calibration_damage(level_id, extra, seed):
    """Total damage a reference board (plus `extra`, one level-1 tower placed
    by the bot's own spot choice) deals to a level's authored waves of
    near-unkillable enemies."""
    from conftest import make_game

    from core.game import GameState
    from entities.tower import TOWER_TYPES
    game = make_game(pathlib.Path(tempfile.mkdtemp(prefix="td-balance-")))
    from world.levels import LEVELS
    game._load_level_object(LEVELS[level_id], sandbox=True, rng=random.Random(f"calibrate:{level_id}:{seed}"))
    game.state = GameState.PLAYING
    game.wave_manager.enemy_hp_multiplier = CALIBRATION_HP
    bot = FloorBot(game, random.Random(seed))
    for name in CALIBRATION_REFERENCE + ((extra,) if extra else ()):
        cls = TOWER_TYPES[name]
        if cls.IS_SUPPORT:
            spot = bot._best_support_spot(cls)
        elif not cls.ATTACKS:
            spot = bot.best_spot_for_wall(cls)
        else:
            spot = bot.best_spot(cls)
        if spot:
            bot._do(("place", name, spot[0]))
    elapsed = 0.0
    gold_before = game.economy.gold
    while not game.wave_manager.all_waves_complete and elapsed < 400:
        game.wave_manager.skip_delay()
        game.update(STEP)
        elapsed += STEP
    while game.enemies and elapsed < 600:
        game.update(STEP)
        elapsed += STEP
    gold = game.economy.gold - gold_before  # nothing dies, so only Siphon-style income moves this
    return sum(t.damage_dealt for t in game.towers), gold


def _calibrate_one(name):
    from entities.tower import TOWER_TYPES
    damage = income = 0.0
    trials = [(level_id, seed) for level_id in CALIBRATION_LEVELS for seed in CALIBRATION_SEEDS]
    for level_id, seed in trials:
        with_dmg, with_gold = _calibration_damage(level_id, name, seed)
        ref_dmg, ref_gold = _calibration_damage(level_id, None, seed)
        damage += with_dmg - ref_dmg
        income += with_gold - ref_gold
    cost = TOWER_TYPES[name].cost
    return name, (round(damage / len(trials) / cost, 1), round(income / len(trials) / cost, 2))


def calibrate(jobs):
    """Marginal damage (and battle-gold income) per gold of one more level-1
    tower of each type on top of a fixed reference board -- slows, marks,
    buffs and walls show up as extra damage the *other* towers deal. Paste
    the printed table into CALIBRATED_POWER_PER_GOLD."""
    from entities.tower import TOWER_TYPES
    with ProcessPoolExecutor(jobs) as pool:
        results = dict(pool.map(_calibrate_one, list(TOWER_TYPES)))
    print("marginal damage / income per gold (one level-1 tower added to 3 Basics):")
    for name, (damage, income) in sorted(results.items(), key=lambda kv: -kv[1][0]):
        print(f"  {name:16} {damage:7.1f} {income:6.2f}")
    print("CALIBRATED_POWER_PER_GOLD = {" + ", ".join(f'"{k}": {v}' for k, v in results.items()) + "}")


# --- Report ------------------------------------------------------------------

def _pct(n, d):
    return f"{100 * n / d:5.1f}%" if d else "    -"


def report(records):
    n = len(records)
    lines = [f"runs: {n}"]
    reached = collections.Counter(r["act_reached"] for r in records)
    act2 = sum(1 for r in records if r["act_reached"] >= 2)
    act3 = sum(1 for r in records if r["act_reached"] >= 3)
    final_beaten = sum(1 for r in records if r["boss_defeated"])
    capped = sum(1 for r in records if r["outcome"] == "endless-cap")
    lines.append(f"cleared act 1: {_pct(act2, n)}   cleared act 2: {_pct(act3, n)}   "
                 f"beat final boss's authored waves: {_pct(final_beaten, n)}   "
                 f"survived {ENDLESS_WAVE_CAP} endless waves: {_pct(capped, n)}")
    endless = [r["endless_waves"] for r in records if r["act_reached"] == 3 and r["boss_defeated"]]
    if endless:
        lines.append(f"endless waves cleared (runs that beat the final boss): median {statistics.median(endless)}, "
                     f"max {max(endless)}")
    del reached

    lines.append("\nper Commander: act1 / act2 clear, median floors")
    by_cmd = collections.defaultdict(list)
    for r in records:
        by_cmd[r["commander"]].append(r)
    for cmd, rs in by_cmd.items():
        a2 = sum(1 for r in rs if r["act_reached"] >= 2)
        a3 = sum(1 for r in rs if r["act_reached"] >= 3)
        med = statistics.median(len(r["floors"]) for r in rs)
        lines.append(f"  {cmd:12} {_pct(a2, len(rs))} {_pct(a3, len(rs))}  {med}")

    lines.append("\ndeaths by run depth (act-row):")
    deaths = collections.Counter()
    for r in records:
        if r["outcome"] == "died" and r["floors"]:
            f = r["floors"][-1]
            deaths[(f["act"], f["row"])] += 1
    for key in sorted(deaths):
        lines.append(f"  act {key[0]} row {key[1]}: {deaths[key]:3d} {'#' * deaths[key]}")

    lines.append("\nper floor (act-row): fights, avg lives lost, death rate, avg gold left")
    per = collections.defaultdict(list)
    for r in records:
        for f in r["floors"]:
            per[(f["act"], f["row"])].append(f)
    for key in sorted(per):
        fs = per[key]
        lost = statistics.mean(f["lives_before"] - f["lives_after"] for f in fs)
        died = sum(f["died"] for f in fs)
        gold = statistics.mean(f["gold_left"] for f in fs if not f["died"]) if len(fs) > died else 0
        lines.append(f"  act {key[0]} row {key[1]}: {len(fs):4d}  {lost:5.1f}  {_pct(died, len(fs))}  {gold:6.0f}")

    lines.append("\nby node type: fights, avg lives lost, death rate")
    per_type = collections.defaultdict(list)
    for r in records:
        for f in r["floors"]:
            per_type[f["type"]].append(f)
    for key, fs in sorted(per_type.items()):
        lost = statistics.mean(f["lives_before"] - f["lives_after"] for f in fs)
        lines.append(f"  {key:8} {len(fs):4d}  {lost:5.1f}  {_pct(sum(f['died'] for f in fs), len(fs))}")

    lines.append("\nby level: fights, avg lives lost, death rate")
    per_level = collections.defaultdict(list)
    for r in records:
        for f in r["floors"]:
            per_level[f["level"]].append(f)
    for key, fs in sorted(per_level.items()):
        lost = statistics.mean(f["lives_before"] - f["lives_after"] for f in fs)
        lines.append(f"  {key:3}  {len(fs):4d}  {lost:5.1f}  {_pct(sum(f['died'] for f in fs), len(fs))}")

    lines.append("\ntowers (every floor but the endless final boss): built share, damage share, kill share, "
                 "damage per tower built")
    built = collections.Counter()
    damage = collections.Counter()
    kills = collections.Counter()
    for r in records:
        built.update(r["built"])
        damage.update(r["damage"])
        kills.update(r["kills"])
    tb, td, tk = sum(built.values()) or 1, sum(damage.values()) or 1, sum(kills.values()) or 1
    for name in sorted(built, key=lambda k: -built[k]):
        per_tower = damage[name] / built[name] if built[name] else 0
        lines.append(f"  {name:22} {_pct(built[name], tb)} {_pct(damage[name], td)} {_pct(kills[name], tk)}"
                     f"  {per_tower:8.0f}")
    timeouts = sum(r["timeouts"] for r in records)
    if timeouts:
        lines.append(f"\n(fights hitting the time limit: {timeouts})")
    odd = [r for r in records if r["outcome"] not in ("died", "endless-cap", "endless-timeout")]
    for r in odd:
        lines.append(f"!! seed {r['seed']} {r['commander']}: {r['outcome']}")
    return "\n".join(lines)


def main(argv=None):
    from run.commanders import COMMANDER_ORDER
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, default=8, help="seeds per Commander")
    parser.add_argument("--first-seed", type=int, default=0)
    parser.add_argument("--commanders", nargs="*", default=COMMANDER_ORDER)
    parser.add_argument("--account", choices=("veteran", "fresh"), default="veteran",
                        help="veteran: every meta unlock (full tower/relic/level pools); fresh: a new account")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--json", help="write every run record to this file")
    parser.add_argument("--set", action="append", default=[], metavar="MODULE.NAME=VALUE",
                        help="override a constant for an experiment (repeatable)")
    parser.add_argument("--calibrate", action="store_true", help="measure each tower's marginal damage per gold")
    args = parser.parse_args(argv)
    if args.calibrate:
        calibrate(args.jobs)
        return []
    jobs = [(seed, cmd, args.account, args.set) for seed in range(args.first_seed, args.first_seed + args.seeds)
            for cmd in args.commanders]
    if args.jobs > 1:
        with ProcessPoolExecutor(args.jobs) as pool:
            records = list(pool.map(_play_star, jobs))
    else:
        records = [_play_star(job) for job in jobs]
    print(report(records))
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(records, indent=1))
    return records


if __name__ == "__main__":
    main()
