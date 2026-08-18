"""Gold and lives tracking. Pure Python -- no pygame dependency -- so it's
trivially unit-testable."""


class Economy:
    def __init__(self, starting_gold, starting_lives):
        self.gold = starting_gold
        self.lives = starting_lives

    def can_afford(self, cost):
        return self.gold >= cost

    def spend(self, amount):
        if not self.can_afford(amount):
            return False
        self.gold -= amount
        return True

    def add_gold(self, amount):
        self.gold += amount

    def lose_life(self, amount=1):
        self.lives = max(0, self.lives - amount)

    @property
    def is_out_of_lives(self):
        return self.lives <= 0
