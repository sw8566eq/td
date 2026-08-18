from economy import Economy


def test_starts_with_given_gold_and_lives():
    economy = Economy(starting_gold=150, starting_lives=20)
    assert economy.gold == 150
    assert economy.lives == 20


def test_can_afford():
    economy = Economy(starting_gold=50, starting_lives=20)
    assert economy.can_afford(50)
    assert economy.can_afford(49)
    assert not economy.can_afford(51)


def test_spend_deducts_gold_when_affordable():
    economy = Economy(starting_gold=100, starting_lives=20)
    assert economy.spend(60) is True
    assert economy.gold == 40


def test_spend_fails_and_leaves_gold_unchanged_when_unaffordable():
    economy = Economy(starting_gold=30, starting_lives=20)
    assert economy.spend(31) is False
    assert economy.gold == 30


def test_add_gold():
    economy = Economy(starting_gold=10, starting_lives=20)
    economy.add_gold(25)
    assert economy.gold == 35


def test_lose_life_floors_at_zero():
    economy = Economy(starting_gold=0, starting_lives=2)
    economy.lose_life()
    assert economy.lives == 1
    economy.lose_life(5)
    assert economy.lives == 0
    assert economy.is_out_of_lives


def test_is_out_of_lives_false_while_lives_remain():
    economy = Economy(starting_gold=0, starting_lives=1)
    assert not economy.is_out_of_lives
