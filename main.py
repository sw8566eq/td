"""Entry point.

--unlimited-gold is a debug flag: every purchase (placing, upgrading, or
specializing a tower) always succeeds and gold is never actually spent --
see Economy.unlimited_gold.
"""

import argparse

from game import Game


def parse_args():
    parser = argparse.ArgumentParser(description="Tower Defense")
    parser.add_argument(
        "--unlimited-gold", action="store_true",
        help="Debug flag: never run out of gold.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    Game(unlimited_gold=args.unlimited_gold).run()
