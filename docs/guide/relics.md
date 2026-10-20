# Relics

Run-wide passive modifiers, trophy relics and curses.

[Back to the guide](README.md)

## Relics

A relic is a passive, run-wide modifier drafted from Shop/Treasure/Event nodes -- everything from "+20 gold at the start of every floor" to relics that make one specific
tower's own signature mechanic (Basic's crit, Sniper's execute, Frost's slow, Poison's DoT,
Knockback's shove) hit harder, a handful of combo relics that reward running two or three towers'
mechanics together (bonus damage against an enemy that's simultaneously Marked *and* Slowed, say, or
all three of Marked/Slowed/Poisoned at once), and one that boosts damage against Boss-tier enemies
specifically. Almost none of them are gated behind an account-wide unlock -- see `run/relics.py` for the
full registry and [Meta-progression](modes-and-progression.md#meta-progression) for the handful that are. Press `R` while playing a run
floor to bring up a read-only overlay of every relic you're currently holding.

**Trophy relics** are their own tier, only ever offered when you beat an act's boss: big upsides with a
real cost attached -- Overcharged Core (+30% damage, but Outposts can't heal), Gilded Ledger (+60
gold every floor, but no shop currency from clears), Sealed Cask (+20% fire rate, but no new potions),
Siege Engine (+25% range, but faster enemies), and Reckless Arsenal (more damage and fire rate, but
lose 5 lives).

**Curses** are the flip side: relics with only downsides (pricier upgrades, less starting gold,
shorter range, slower towers, faster enemies, a worse Shop). You never draft one -- a few Events
offer a bigger-than-usual reward with a curse attached (Forbidden Tome, Gilded Coffer). Lift one at
a Shop ("Remove a curse", once per visit) or at the Cleansing Spring event.

## Construction relics

**Earthworks** (Barricades get 50% more hit points), **Forward Observer** (the Mortar's dead zone is
half as wide), **Quick-Release Mounts** (towers whose type has a module fire 10% faster) and
**Watchtowers** (towers on high ground deal 15% more damage).

**Ambush** makes enemies held at a Barricade take 25% more damage from everything, and **Incendiary
Shells** makes every Mortar shell leave burning ground for 3 seconds. Pair those with slows: **Flashpoint**
doubles burning ground's damage on slowed enemies, and **Kill Corridor** gives traps +50% against them.

## Placement relics

Two relics reward opposite ways of building: **Combined Arms** (+5% damage for each *different* tower
type within reach, up to +25% -- mix your towers together) and **Lone Sentinel** (+30% damage for a
tower with no other tower nearby -- spread them out). Like the density relics, they're worked out when
a tower is placed or sold, and shown in each tower's damage.
