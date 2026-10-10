# Metroid Prime 2: Echoes

## Where is the settings page?

The player options page for this game contains all the options you need to configure and export a config file.

## What does randomization do to this game?

All 119 item pickup locations across Aether -- Temple Grounds, Agon Wastes, Torvus Bog, Sanctuary Fortress, the
Sky Temple, and their corrupted Dark Aether counterparts -- are shuffled among all the games in the multiworld.
Beams, visors, suits, movement upgrades, ammo expansions, energy tanks, Sky Temple Keys, and the three sets of
Dark Temple Keys may be found in any player's world, and this world's own pickups may hold items belonging to any
other player.

The starting room is vanilla (Temple Grounds - Landing Site) unless the `starting_room` option says otherwise:

- **Vanilla** (default): always Temple Grounds - Landing Site, matching every seed generated before this option
  existed.
- **Save Stations**: one of the 18 save-station rooms across the whole game (9 in light regions, 9 in dark).
- **Anywhere**: one of 272 rooms -- every room Randovania's logic database considers a valid starting location
  (162 light / 110 dark), including rooms you'd normally only reach via a boss arena or a one-way drop.

`starting_room_light_world_only` narrows either non-vanilla pool down to light-region rooms only. A dark-region
start otherwise means taking Dark Aether damage every second from the moment the game begins, until a suit or a
safe zone is reached, so it can be an immediately dangerous opening.

## Traps

With `trap_percentage` above 0, some of the Missile Expansions in the pool are replaced by traps: items that do
something bad when you receive them. Logic never relies on them and enough Missile Expansions always remain.
`trap_weights` chooses which traps appear, and `trap_disguise` makes the ones in your own world look like ordinary
pickups until you receive them.

- **Damage Trap**: removes a random share of your maximum energy, between `damage_trap_min_percent` and
  `damage_trap_max_percent` (25% to 75% by default). It can never kill you; it leaves you at 1 energy at worst.
- **Ammo Depletion Trap**: sets your Missiles, Power Bombs, Dark Ammo and Light Ammo to 0. Your capacities are
  unchanged, so any ammo you pick up afterwards works normally.
- **Freeze Trap**: for `freeze_trap_duration` seconds (two minutes by default) you are frozen in ice at random
  moments, for 4 to 6 seconds each time by default (`freeze_trap_min_seconds` / `freeze_trap_max_seconds`), as ice
  attacks do. Mashing jump breaks a freeze early. A second Freeze Trap
  received meanwhile extends the time.

A trap takes effect a moment after it is received, once the game is not in a cutscene, and traps received together
are applied one at a time. Reconnecting or reloading a save never repeats a trap you have already suffered. A Freeze
Trap's remaining time is lost if you restart the client partway through it.

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

The "Sky Temple Keys Required" option separately controls how many of the 9 keys must actually be held to unlock
the Sky Temple Gateway's ring of columns and proceed to Dark Samus -- a real difficulty reduction, not just a
relocation. With the default "Sky Temple Keys" of 9 (every key a normal pickup) and "Sky Temple Keys Required" at,
say, 6, only 6 of the 9 key locations ever need to be found before the Gateway opens; the other 3 keys still exist
and can still be found, they simply stop being necessary. Vanilla (and this option's default) requires all 9. A
value higher than however many keys "Sky Temple Keys" actually makes obtainable is clamped down to that count,
since it's impossible to hold more keys than exist.

### Sky Temple Key hints

The 9 Luminoth pillars in Sky Temple Gateway can tell you where each Sky Temple Key actually is, controlled by the
"Sky Temple Key Hints" option:

- **Scanned** (default): scan a pillar to see where that key is -- your own world or another player's -- and the
  hint is sent to the multiworld server for everyone to see, the same as any other in-game hint. Nothing is
  reported to the server until the scan actually finishes; a partial scan tells you nothing.
- **Precollected**: every key's hint is already known and sent to the server as soon as the game begins, without
  needing to scan anything.
- **Disabled**: the pillars' text is replaced with a generic "lost somewhere in Aether" message instead of a real
  hint, since the vanilla riddles describe vanilla key locations and would be misleading once keys are shuffled.

### Translator lore hints

The 22 colored Luminoth lore holograms scattered across the light regions can also each point at one progression
item, controlled by the "Translator Lore Hints" option:

- **My Items** (default): each hologram names where one of your own progression items is, in any player's world.
- **Any**: the pool also includes other players' progression items that landed in your own world.
- **Off**: holograms keep their vanilla lore text; nothing is hinted.

You need the hologram's translator to read it. Bulk items such as expansions are never hinted, and each item is
hinted at most once. Same as the Sky Temple Key pillars, scanning a hologram to completion sends the hint to the
multiworld server.
Your own Sky Temple Keys are left to the pillars above and never duplicated here, unless "Sky Temple Key Hints" is
Disabled. If there are fewer eligible items than holograms, the extras just say there's nothing more to tell.

The "Translator Lore Randomization" option can also give each hologram a random translator color instead of its
region's usual one. The hologram and its glow are recolored to match, so you can still see which translator you need.

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

A message appears and you are returned to the starting room (Samus' ship in Landing Site, or wherever
`starting_room` chose) a few seconds later. Choosing No without holding L+R does nothing unusual -- you get the
normal "Game was not saved" message. This works from any of the 18 Save Stations regardless of which room
`starting_room` actually picked, even if that room has no Save Station of its own.

## Is there a spring ball?

Yes, if the `spring_ball` option is enabled. Once you have Morph Ball Bombs, pressing the button chosen by
`spring_ball_button` (C-Stick up by default) while rolling on the ground in Morph Ball jumps as high as a bomb jump,
without laying a bomb. Holding the button keeps jumping each time you land, after a short cooldown. It doesn't work
in mid-air, on Spider Ball tracks or during Screw Attack. Logic never requires it.

## Do I have to scan elevators before using them?

Not by default. With `pre_scan_elevators` enabled (the default), every elevator starts pre-scanned so you can step
onto the platform and go without scanning the hologram pillar first. Disable it to require the scan, as in vanilla.
This is purely cosmetic -- elevators are never logically gated on Scan Visor either way.

## Can I move while scanning?

Not by default. With `move_while_scanning` enabled, you can move around freely while Scan Visor is locked onto a
scan point, instead of the game freezing you in place for the duration of the scan. This is purely cosmetic --
logic never assumes you can move during a scan either way.

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
