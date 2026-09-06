"""Gold and lives tracking. Pure Python -- no pygame dependency -- so it's
trivially unit-testable."""


class Economy:
    def __init__(self, starting_gold, starting_lives, unlimited_gold=False, invulnerable=False):
        self.gold = starting_gold
        self.lives = starting_lives
        # Debug flag (see main.py --unlimited-gold): every purchase always
        # succeeds and gold is never actually deducted, rather than
        # inflating the displayed total -- ui.py shows "Gold: unlimited"
        # instead of a number while this is set.
        self.unlimited_gold = unlimited_gold
        # Sandbox/Creative mode (see Game's sandbox param): a leaked enemy
        # never actually costs a life, same "never actually deducted"
        # precedent as unlimited_gold above rather than draining lives and
        # masking it -- ui.py shows "Lives: infinity" instead of a number
        # while this is set.
        self.invulnerable = invulnerable

    def can_afford(self, cost):
        return self.unlimited_gold or self.gold >= cost

    def spend(self, amount):
        if not self.can_afford(amount):
            return False
        if not self.unlimited_gold:
            self.gold -= amount
        return True

    def add_gold(self, amount):
        self.gold += amount

    def lose_life(self, amount=1):
        if self.invulnerable:
            return
        self.lives = max(0, self.lives - amount)

    @property
    def is_out_of_lives(self):
        return not self.invulnerable and self.lives <= 0

    @property
    def is_on_last_life(self):
        """True once lives is down to its last one -- the single answer
        to "is this run on its last life", shared by two independent
        relics that each ask it their own way (Game._lose_a_life's
        Guardian's Reprieve interception, Game.update()'s Last Stand
        Charm check) so a future tuning change to the threshold can't
        leave them silently disagreeing."""
        return self.lives <= 1
