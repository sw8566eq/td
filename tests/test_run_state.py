from run_map import MapNode, RunMap
from run_state import RunState

# A tiny, hand-built two-row map (not a real generate_run_map() output) --
# enough to exercise RunState's own properties without depending on the
# real map generator's randomness. Row 0: two combat nodes ("0-0"/"0-1").
# Row 1 (the boss row): one combat node ("1-0"), reachable from both.
_MAP = RunMap(
    rows=(
        (MapNode("0-0", row=0, col=0, node_type="combat", level_id=1),
         MapNode("0-1", row=0, col=1, node_type="combat", level_id=2)),
        (MapNode("1-0", row=1, col=0, node_type="combat", level_id=3),),
    ),
    edges={"0-0": ("1-0",), "0-1": ("1-0",)},
)


def _run(**overrides):
    kwargs = dict(
        seed=1234, map=_MAP, difficulty="normal",
        unlocked_towers=["basic", "cannon", "frost"], current_node_id="0-0",
    )
    kwargs.update(overrides)
    return RunState(**kwargs)


def test_defaults():
    run = _run()
    assert run.lives == 0
    assert run.shop_currency == 0
    assert run.floors_cleared == 0
    assert run.visited_node_ids == []
    assert run.relics == []
    assert run.is_daily is False
    assert run.has_spent_gold is False
    assert run.used_guardians_reprieve is False


def test_relics_default_is_not_shared_across_instances():
    # Regression guard: a plain `relics: list = []` default would share one
    # mutable list across every RunState -- field(default_factory=list) is
    # what run_state.py actually uses, this just proves it.
    a = _run()
    b = _run()
    a.relics.append("something")
    assert b.relics == []


def test_visited_node_ids_default_is_not_shared_across_instances():
    a = _run()
    b = _run()
    a.visited_node_ids.append("0-0")
    assert b.visited_node_ids == []


def test_current_level_id_reads_the_current_nodes_own_level_id():
    run = _run(current_node_id="0-1")
    assert run.current_level_id == 2
    run.current_node_id = "1-0"
    assert run.current_level_id == 3


def test_current_row_reads_the_current_nodes_own_row():
    run = _run(current_node_id="0-0")
    assert run.current_row == 0
    run.current_node_id = "1-0"
    assert run.current_row == 1


def test_is_final_floor_true_only_on_the_boss_node():
    run = _run(current_node_id="0-0")
    assert run.is_final_floor is False
    run.current_node_id = "0-1"
    assert run.is_final_floor is False
    run.current_node_id = "1-0"
    assert run.is_final_floor is True


def test_is_final_floor_true_for_a_single_row_map():
    single_row_map = RunMap(rows=((MapNode("0-0", row=0, col=0, node_type="combat", level_id=1),),), edges={})
    run = _run(map=single_row_map, current_node_id="0-0")
    assert run.is_final_floor is True


def test_floors_cleared_counts_only_visited_combat_and_elite_nodes():
    run = _run()
    assert run.floors_cleared == 0
    run.visited_node_ids = ["0-0"]
    assert run.floors_cleared == 1
    run.visited_node_ids = ["0-0", "1-0"]
    assert run.floors_cleared == 2


def test_floors_cleared_excludes_non_combat_node_visits():
    non_combat_map = RunMap(
        rows=(
            (MapNode("0-0", row=0, col=0, node_type="combat", level_id=1),),
            (MapNode("1-0", row=1, col=0, node_type="shop"),),
            (MapNode("2-0", row=2, col=0, node_type="combat", level_id=2),),
        ),
        edges={"0-0": ("1-0",), "1-0": ("2-0",)},
    )
    run = _run(map=non_combat_map, current_node_id="0-0")
    run.visited_node_ids = ["0-0", "1-0"]  # cleared the combat node, then just visited the shop

    assert run.floors_cleared == 1
