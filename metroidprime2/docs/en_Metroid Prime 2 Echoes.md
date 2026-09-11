# Metroid Prime 2: Echoes

## Where is the settings page?

The player options page for this game contains all the options you need to configure and export a config file.

## What does randomization do to this game?

All 119 item pickup locations across Aether -- Temple Grounds, Agon Wastes, Torvus Bog, Sanctuary Fortress, the
Sky Temple, and their corrupted Dark Aether counterparts -- are shuffled among all the games in the multiworld.
Beams, visors, suits, movement upgrades, ammo expansions, energy tanks, Sky Temple Keys, and the three sets of
Dark Temple Keys may be found in any player's world, and this world's own pickups may hold items belonging to any
other player.

Elevators, translator gate colors, and door locks are left in their vanilla configuration in this version of the
apworld; only the items sitting at pickup locations are randomized. The starting room is also vanilla (Temple
Grounds - Landing Site).

## What is the goal of Metroid Prime 2: Echoes when randomized?

Defeat Dark Samus at the Sky Temple Gateway, the same final encounter as the base game. Reaching it still requires
collecting the Sky Temple Keys and fighting through Aether with whatever items logic has placed along the way.

The "Sky Temple Keys" option controls how the 9 keys are handled:

- A number from 0 to 9 puts that many keys into the general item pool (shuffled like any other progression item)
  and pre-collects the rest at the start of the game. 9 (the default) behaves like a normal item; 0 starts with
  every key already collected.
- **All Bosses** pre-places one key on each of the 9 boss/guardian pickup locations (the 6 sub-guardians plus the
  3 dark temple guardians) instead of shuffling them into the pool.
- **All Guardians** pre-places keys 1-3 on the 3 dark temple guardians (Amorbis, Chykka, Quadraxis) and
  pre-collects keys 4-9.

Keys placed this way (All Bosses / All Guardians) are recorded in the spoiler log.

## What does the logic that places my items know about?

Reachability is computed from Randovania's Metroid Prime 2: Echoes logic database -- the same data the standalone
Randovania randomizer uses -- so routes that Randovania considers legal (including glitch/trick routes, when
enabled) are also legal here. Two options tune how aggressive that logic is:

- **Trick Level** (and 25 individual per-trick overrides, grouped under "Tricks" on the options page) controls
  which non-standard techniques -- out-of-bounds movement, damage boosting, wall boosts, extended dashes, and so
  on -- logic is allowed to require in order to reach a location. Each trick can be left at "Use global setting"
  to follow the overall Trick Level, or set to its own difficulty independently.
- **Damage Strictness** (strict / medium / lenient) scales how much incoming damage logic assumes a damaging area
  deals before requiring an Energy Tank or suit upgrade to cross it. Medium is the default and matches
  Randovania's own starter preset.

**Energy Per Tank**, **Dark Aether Damage**, and **Dark Suit Damage** further tune the numbers that feed into the
damage logic above and into the patched game itself, so what the game actually does to your health always matches
what logic assumed.

## How do items get delivered to me?

Every item you or another player collect for this world -- including your own local items -- is granted by the
Metroid Prime 2: Echoes client a moment after it registers on the server, not directly in-game at the moment of
pickup. Collecting a pickup in-game only reports the check to the server; the client then applies the resulting
inventory changes (yours and everyone else's) on its next sync, roughly every half second, while it stays
connected to both Dolphin and the multiworld server.

Because of this, capacity-only items are tracked cumulatively rather than granted piece by piece: for example, if
you receive a Missile Expansion before you have found your Missile Launcher, it is remembered and its capacity is
added in once the Launcher itself is received. The same idea applies to Seeker Launcher, Power Bomb Expansions,
and the beam ammo expansions.

Because delivery depends on the client, **the client must remain connected and running (with Dolphin open) to
receive items**; nothing is delivered while it is disconnected, though everything you're owed is delivered as
soon as it reconnects.

## Can I teleport to the starting room?

Yes, as long as the `warp_to_start` option is enabled (it is by default):

1. Step onto any Save Station.
2. When prompted to save, choose **No**.
3. Hold **L** and **R** while choosing No.

A message appears and you are returned to the starting room (Samus' ship in
Landing Site) a few seconds later. Choosing No without holding L+R does
nothing unusual -- you get the normal "Game was not saved" message.

## What are the known limitations of this randomizer?

- Damage logic is evaluated per damaging edge, independently, rather than as a cumulative trip like Randovania's
  own generator considers. This makes some multi-room dark-world traversals slightly more permissive here than in
  a comparable Randovania seed with the same settings.
- The client detects collected pickups by polling the game's memory roughly twice a second. If two different
  pickups are collected within about half a second of each other, the client can only see the most recent one and
  may briefly miscount which locations were checked; both checks are still eventually recorded correctly once the
  ambiguity is detected, but you may see a warning in the client log when this happens.
- Only NTSC-U and PAL GameCube releases of Metroid Prime 2: Echoes are supported. The Japanese release is not
  supported, nor is any Wii/Trilogy version.
- On macOS, the Dolphin memory connection is best-effort: reading and writing Dolphin's emulated memory works the
  same way it does for other MultiworldGG Dolphin-based games, but is less consistently reliable there than on
  Windows or Linux.

## How are items and locations named?

Locations are named `<Region>: <Area> - <Node>`, for example `Temple Grounds: Hive Chamber A - Pickup (Missile)`,
identifying exactly where in Aether the pickup sits. Items use their in-game names directly (`Dark Beam`, `Super
Missile`, `Energy Tank`, `Sky Temple Key 3`, and so on); progressive items appear as `Progressive Suit` and
`Progressive Grapple` when their respective options are enabled.
