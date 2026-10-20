# Runs

How a run works: Commanders, the branching map, acts, bosses and the run economy.

[Back to the guide](README.md)

## Runs

Press any unbound key at the main menu, then pick a **Commander**. Each
one sets your three starter towers and a signature starting relic: **The Warden** (Basic, Cannon,
Frost; survives one killing blow per run) is always available; **The Alchemist** (Basic, Poison,
Frost; venom-coated shots and two starting potions), **The Marksman** (Basic, Sniper, Frost; more crits)
**The Engineer** (Basic, Cannon, Support; Basic starts forged, cheaper upgrades), **The
Stormcaller** (Basic, Lightning, Frost; Lightning starts forged and hits harder), **The Trapmaster**
(Basic, Spike Trap, Tar Pit; Spike Trap starts forged, traps hit slowed enemies harder) and **The Skywatch**
(Basic, Harpoon, Cannon; Harpoon starts forged, grounded flyers stay down longer) unlock as you play.
Every Commander also has one signature **ability**, fired mid-fight with the sidebar button or **F**;
once used it recharges after a few cleared waves (shown on the button), so the only decision is when:

| Commander | Ability | Effect | Recharge |
|---|---|---|---|
| The Warden | Hold the Gate | The next 3 enemies to leak this floor cost no lives | 3 waves |
| The Alchemist | Toxic Downpour | Aim it: enemies within 110px are poisoned for 6% max HP/s for 6s (1% vs bosses) | 2 waves |
| The Marksman | Called Shot | Basic and Sniper deal double damage for 6s | 2 waves |
| The Engineer | Rapid Repairs | Every tower fires 40% faster for 8s; every Barricade repaired | 3 waves |
| The Stormcaller | Thunderhead | Lightning strikes the 8 toughest enemies for 35% max HP (6% vs bosses) | 2 waves |
| The Trapmaster | Caltrops | Every ground enemy slowed to 45% speed for 6s | 2 waves |
| The Skywatch | Downdraft | Every flyer grounded and slowed to 70% speed for 6s | 2 waves |

An aimed ability (Toxic Downpour) shows its radius at the cursor; click the field to fire, or
right-click/Esc to cancel. The Daily Run always uses The Warden, and starts with that day's **modifiers** -- one trophy relic,
one curse, and one module fitted to a starter tower, the same for everyone.

Before the map, **Orders from Command** offer one requisition -- pick one: a
relic, supplies (+15 shop currency, +3 lives), a forged tower plus a potion, or a dark bargain (two
relics and a curse).

That generates a **branching map** -- six rows of nodes, shown to you in full from the start, no fog
of war. The build menu shows only your three starter towers at first; more join your run from
rewards, the Shop, and Events (and the full pool grows as you unlock towers -- see
[Meta-progression](modes-and-progression.md#meta-progression)).

Row 0 is always three Combat choices -- your very first click always starts a real fight. From
there, click any node connected to the one you just cleared to move on. Most rows are a mix of six
node types:

- **Combat** -- a normal tower-defense floor.
- **Elite** -- a harder floor that pays out more shop currency on clear (and drops a relic). Each
  Elite also rolls an **affix** you can see by hovering it on the map: **Swift** (faster enemies),
  **Hulking** (tougher but slower), **Swarming** (half again as many, each a bit weaker), or
  **Gilded** (tougher, but they drop much more gold), **Regenerating** (enemies heal over time),
  **Armored** (enemies take less damage from every hit), **Tunneling** (ground enemies burrow under
  traps and Barricades), **Siegebreakers** (they batter Barricades harder), **Jammers** (every spawn
  sends a tower-jamming Disruptor each wave), **Phalanx** (a Bulwark escort each wave, and tougher
  enemies), or **Windborne** (every third ground enemy flies instead).
- **Shop** -- spend shop currency on towers and relics (see [The Shop and two currencies](#the-shop-and-two-currencies)).
- **Event** -- a short prompt with 2-3 honestly-described options (gain currency, lose a relic for a
  bigger reward, unlock a tower early, heal, ...) -- never a hidden-odds gamble.
- **Outpost** -- a choice: **Rest** to heal some lives back, **Drill** one tower type's crews (+60
  veterancy experience), **Move on**, or **Forge** one of your
  towers -- every copy of it you place for the rest of the run starts at level 2, for free (marked
  with a `+` on its build button).
- **Treasure** -- a guaranteed shop-currency payout plus a guaranteed relic pick.
- **Armory** -- choose one of three tower modules, each for a different tower type you hold, free.
- **Proving Grounds** -- an optional fight under one constraint, shown on the map before you commit:
  **Skeleton Crew** (at most 4 towers), **No Upgrades**, **Narrow Front** (only two of your tower
  types may be built), **Double Time** (enemies 35% faster, 50% more gold), **Glass Gate** (only 3
  lives at stake -- a 4th leak costs nothing but fails the challenge) or **Fog of War** (no wave
  preview, no range rings). Win without breaking it for a pick of 1 of 2 bonus relics plus extra
  shop currency; break it and the fight carries on as a normal one. Never on a run's first rows.

The final row is always a single **Boss** node, and a run is **three acts** -- three maps back to
back. Beating Act 1's or Act 2's boss clears it like any floor, then lets you
pick one of three trophy relics (plus a potion) and moves you on to the next act's fresh map, healing
10 lives on the way. Every act is harder than the last: escalation keeps counting rows across acts,
so Act 2's first fight is tougher than Act 1's boss. **Act 3's boss** loads in Endless mode from the
very start, so its waves never run out and there's no "you won the run" screen -- while the boss
itself is still alive it periodically reinforces (or, on the other boss level, shields itself), and
defeating it just means the fight keeps going, now boss-free, for score. Every 5 endless waves you
clear, an **endless mutator** joins the fight and stays for the rest of it, stacking with the ones
before: Swarm (+30% enemies), Ironclad (+25% HP), Gale (+15% speed), Skyborne (every 4th ground enemy
flies), Tunnelers (ground enemies burrow), Siege (Barricades battered twice as hard), Regrowth (1% HP
regen per second), Shielded Ranks (every 4th ground enemy shielded) or Escort (a Tank per spawn each
wave). Each one is announced with a toast, listed in the sidebar, and pays a bounty of +1 life and +60
battle gold; the Run Over recap and Run History count how many you faced. A run ends only by
**permadeath** -- losing your last life -- which records the run (`progression/run_history.py`,
keyed by seed, keeping your best result) and banks its progress toward the next one.

Clearing a Combat, Elite, or act Boss floor's waves shows a **Floor Cleared** results screen, then
the reward screen (see [Rewards and potions](#rewards-and-potions)), then returns you to the map to pick your next
node. The final boss never reaches that screen -- it's Endless from the start, so its waves never
technically finish; every other node type resolves in its own screen instead and returns
you to the map the same way.

Three things make each floor harder than the last: the level itself gets more complex the deeper the
row, a per-floor **escalation** multiplies enemy HP/speed/gold reward on top of your difficulty
setting (`run/run_escalation.py` -- floor 0 is exactly 1.0x, so a run's first floor plays identically to
that level in Practice), and an Elite/Boss node layers a further bump of its own on top of that.

`D` from the menu starts the **Daily Run** -- the same thing, seeded off today's UTC date, so
everyone gets the identical map, offers, and events today. Its difficulty is pinned to Normal
regardless of your own setting, so scores are comparable.

## The Shop and two currencies

A run tracks two currencies that never convert into each other. **Battle gold** is what places,
upgrades, and sells towers mid-floor -- it resets fresh at the start of every floor rather than
carrying forward, so hoarding it into a fight you've already won is wasted... unless you convert it:
clearing a floor turns whatever gold you still had left into **shop currency**, which persists for
the whole run and is the only thing that buys anything at a Shop node.

A Shop visit offers a small mix of tower cards and relic cards together; buy as many (or as few) as
you like, then click Continue. Prices go up a little with every purchase made in that same visit, so
there's a real choice in what to prioritize, not just "buy everything eventually."

## Rewards and potions

Every fight you win opens a **Spoils of battle** screen: pick one of up to three
free tower cards to add to your run (or skip them), and Elite fights also drop a free relic. Deeper
fights sometimes offer a tower already **forged** (`FREE +`), and once you've collected every tower
you can, the row offers **forge cards** for towers you hold instead.

Rewards can also include a **potion** -- a single-use consumable (ordinary fights sometimes drop one). You hold up
to three, shown at the bottom of the sidebar during a fight; click one to use it. Fire Bomb blasts
every enemy on the field, Frost Flask slows them all, Marking Dust makes them take extra damage,
Liquid Gold gives battle gold, Mending Salve restores lives, and Overclock Elixir makes every tower
fire faster for a few seconds, Smoke Screen shoves every enemy back, and Venom Vial poisons them all.
Potions carry between floors until used. Every Shop also has a potion stand selling one potion per
visit, and three relics build around them: Bandolier (+1 slot), Field Medic Kit (+1 life per
potion drunk), and Brewmaster's Kit (every won fight's reward includes a potion).

## Bosses

Every act's boss is one of nine named bosses with its own twist: The Juggernaut (tougher enemies), The
Broodmother (bigger swarms), The Warlord (faster enemies), The Lich (regenerating, slightly faster
enemies), The Golden Tyrant (sturdier enemies that drop double gold), The Undermine (every ground enemy burrows),
The Battering Ram (wall-breakers), The Static Throne (the boss itself jams every tower it passes, with
Disruptor escorts) and The Iron Phalanx (Bulwark escorts, a boss that shields the enemies around it, and
tougher enemies). The map title tells you which
one is waiting at the top of the act, so you can draft toward it.

## Gauntlet

Defeating a run's final (Act 3) boss unlocks **Gauntlet 1**; defeating it again at your highest Gauntlet unlocks
the next one, up to 10. Each level keeps every rule below it and adds one more: tougher Elites, more
enemy HP, less starting gold per floor, tougher bosses, weaker Outposts, fewer starting lives,
faster enemies, pricier Shops, one fewer tower on each reward screen, and finally even more enemy HP.
Once you've unlocked one, the main menu shows an Gauntlet selector -- Left/Right to choose. Daily
Runs are always played at Gauntlet 0 so scores stay comparable.
