from datetime import date

import daily_challenge


def test_todays_seed_is_deterministic_for_a_given_date():
    assert daily_challenge.todays_seed(date(2026, 9, 3)) == 20260903
    assert daily_challenge.todays_seed(date(2026, 9, 3)) == daily_challenge.todays_seed(date(2026, 9, 3))


def test_todays_seed_differs_across_dates():
    assert daily_challenge.todays_seed(date(2026, 9, 3)) != daily_challenge.todays_seed(date(2026, 9, 4))
