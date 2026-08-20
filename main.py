"""Entry point.

--unlimited-gold is a debug flag: every purchase (placing, upgrading, or
specializing a tower) always succeeds and gold is never actually spent --
see Economy.unlimited_gold.

--editor launches straight into the map editor (GameState.EDITOR) instead
of the main menu -- the same screen reachable in-game by pressing E from
the menu, just skipping that step.
"""

import argparse

from game import Game, GameState


def parse_args():
    parser = argparse.ArgumentParser(description="Tower Defense")
    parser.add_argument(
        "--unlimited-gold", action="store_true",
        help="Debug flag: never run out of gold.",
    )
    parser.add_argument(
        "--editor", action="store_true",
        help="Launch directly into the map editor.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    game = Game(unlimited_gold=args.unlimited_gold)
    if args.editor:
        game.state = GameState.EDITOR
    game.run()
