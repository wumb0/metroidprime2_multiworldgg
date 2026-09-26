# Setup Guide for Metroid Prime 2: Echoes MultiworldGG

This guide is meant to help you get up and running with the Metroid Prime 2: Echoes apworld for MultiworldGG.

## Requirements

- [MultiworldGG](https://github.com/MultiworldGG/MultiworldGG/releases), run from source on **Python 3.12 or
  3.13** for now (the game patcher this world depends on, open-prime-rando, is not yet available as part of a
  packaged/frozen MultiworldGG build).
- The [Dolphin Emulator](https://dolphin-emu.org/download/).
- An unmodified _Metroid Prime 2: Echoes_ (GameCube version) ISO file, **NTSC-U or PAL only**. This must be
  dumped from your own disc; compressed/derived formats such as RVZ, WIA, GCZ, CISO, or NKit are not accepted (see
  Troubleshooting below).
- The patcher library `open-prime-rando` and the `dolphin-memory-engine` package, which the client's ISO-patching
  step installs automatically the first time it runs. If you would rather install them yourself ahead of time (or
  need to troubleshoot a failed automatic install), run, inside the Python environment MultiWorldGG uses:

  ```
  pip install "open-prime-rando[nod]==0.20.1" "dolphin-memory-engine>=1.3.0"
  ```

## Configuring your YAML file

### What is a YAML file and why do I need one?

See the [basic multiworld setup guide](/tutorial/Archipelago/setup/en) for general information on how MultiworldGG
works and how to configure your personal options file.

### Where do I get a YAML file?

See the "Options" page for Metroid Prime 2: Echoes on the MultiworldGG website for the full list of available
options, or generate a template from the MultiworldGG Launcher.

The most important options to look at:

- **Sky Temple Keys** -- how the 9 Sky Temple Keys are handled (shuffled into the pool, pre-collected, or
  pre-placed on boss locations). See the game info page for details.
- **Progressive Suit** / **Progressive Grapple** -- combine Dark Suit + Light Suit, or Grapple Beam + Screw
  Attack, into two copies of a single progressive item.
- **Trick Level**, plus 25 individual **Trick: ...** options (grouped under "Tricks", collapsed by default) --
  control which non-standard techniques logic is allowed to require. Leaving a trick at "Use global setting" makes
  it follow the overall Trick Level; setting one individually overrides just that trick.
- **Damage Strictness**, **Energy Per Tank**, **Dark Aether Damage**, **Dark Suit Damage** -- tune how much energy
  logic requires before crossing damaging/dark-world areas, and how much damage those areas actually deal in the
  patched game.
- **Display Non-Local Items** -- whether pickups belonging to other players show a matching in-game model
  ("Match Game") or a generic model ("None").

### host.yaml settings

MultiworldGG's `host.yaml` gets a `metroidprime2_options` section (created the first time you interact with a
`.apmp2` file) with these keys:

- `rom_file` -- path to your vanilla NTSC-U or PAL _Metroid Prime 2: Echoes_ ISO. Used as the input to patching
  when no ISO is given directly on the client's command line.
- `emulator_settings.executable_path` -- path to your Dolphin executable.
- `emulator_settings.arguments` -- extra command-line arguments to pass to Dolphin.
- `emulator_settings.auto_start` -- if true (default), the client launches Dolphin with the patched ISO
  automatically after patching; if false, you start Dolphin and open the ISO yourself.
- `hud_settings.color` -- `"default"` (leave the HUD color as-is), `"custom"` (use `color_red`/`color_green`/
  `color_blue`, each 0-255), or a named color (`red`, `green`, `blue`, `violet`, `yellow`, `cyan`, `white`,
  `orange`, `pink`, `lime`, `teal`, `purple`).
- `suit_settings.varia_skin` / `dark_skin` / `light_skin` -- cosmetic suit model replacement, each one of
  `player1` (vanilla), `player2`, `player3`, or `player4`.

## Generating a Game

As usual, randomized MultiworldGG games with custom worlds must be generated locally -- see
[MultiworldGG Setup Guide: Generating a game - On your local installation](/tutorial/Archipelago/setup/en#on-your-local-installation).
This produces a `.zip` for the room host and, for each Metroid Prime 2: Echoes player, an `.apmp2` patch file.

## Connecting to a Room

You should have the `.apmp2` patch file that generation produced for your slot, plus the room's server address and
port from the host.

1. In the MultiworldGG Launcher, click `Open Patch File` and select your `.apmp2` file. The first time you do
   this, you'll be asked which program to open it with -- choose the **Metroid Prime 2 Client** launcher
   component (this is the same component MultiworldGG uses if it recognizes the `.apmp2` extension automatically
   afterward).
2. The client will install `open-prime-rando` and `dolphin-memory-engine` if they aren't already present, then
   patch your input ISO. **Patching takes a couple of minutes** -- it rewrites the entire disc image, not just a
   few bytes, so be patient and watch the client log for progress percentages.
3. The patched ISO is written next to your `.apmp2` file, with the same base name and a `.iso` extension (for
   example, `AP_1234567890123456789_P1.apmp2` produces `AP_1234567890123456789_P1.iso` in the same folder). If
   that file already exists, patching is skipped; use the client's `/export_iso` command (see below) to force a
   fresh patch.
4. If `emulator_settings.auto_start` is enabled (the default), Dolphin launches automatically with the patched
   ISO. Otherwise, open the patched ISO in Dolphin yourself.
5. Once the game is running, the client connects to Dolphin automatically via Dolphin's memory engine. No special
   Dolphin configuration is required -- just use a normal, unmodified Dolphin install with your (unmodified,
   NTSC-U/PAL) patched ISO. Enter the room's server address and port in the client and connect the way you would
   for any other MultiworldGG game.

## Client Commands

The Metroid Prime 2: Echoes client accepts the following commands in addition to the usual MultiworldGG client
commands:

- `/export_iso` -- deletes the existing patched ISO (if any) and regenerates it from the `.apmp2` file. Only
  works while disconnected from a running game.
- `/status` -- prints the current Dolphin connection state (not connected / connected but wrong game / connected
  but wrong seed / connected and waiting for a save / connected and in game).
- `/test_hud` -- queues a test HUD message to display in-game, to confirm the connection can write to the game.
- `/mp2_debug_inventory` -- prints the raw amount/capacity of every non-empty inventory slot, as read directly
  from game memory. Useful for diagnosing item-delivery issues. Requires `debug: true` (see below).
- `/deathlink` -- toggles DeathLink on/off for this client, overriding the room's default setting.
- `/test_deathlink [reason]` -- sends a test DeathLink to the rest of the group without touching in-game health,
  to verify the send/receive path end-to-end. Requires DeathLink to be enabled (see `/deathlink`), a
  connection to the server, and `debug: true` (see below).

`/mp2_debug_inventory` and `/test_deathlink` are disabled by default. To use them, set `debug: true` under
`metroidprime2_options` in your `host.yaml`:

```yaml
metroidprime2_options:
  debug: true
```

## Troubleshooting

- **"Connected to Dolphin, but it isn't running Metroid Prime 2: Echoes"** -- Dolphin is running a different
  game, or hasn't finished loading yet. Make sure the patched ISO (not the original) is what's loaded in Dolphin.
- **"Connected to Metroid Prime 2: Echoes, but it's running a different seed/uuid"** -- the ISO currently loaded
  in Dolphin was patched from a different `.apmp2` file (a different seed, or a different slot's patch) than the
  one this client instance was started with. Re-patch and load the matching ISO, or start the client with the
  correct `.apmp2` file.
- **Patching fails immediately with an unsupported-format error** -- the input ISO isn't a raw GameCube disc
  image. RVZ, WIA, GCZ, CISO, and NKit (`.nkit.iso`) images are all rejected; redump a plain ISO from your own
  disc. Compressed formats need to be decompressed/converted to a raw ISO first.
- **"The Japanese release of Metroid Prime 2: Echoes is not supported"** -- only NTSC-U and PAL GameCube ISOs
  work with this world; the Japanese release uses different code the patcher does not target.
- **Patching seems stuck** -- patching a full GameCube disc image normally takes a couple of minutes; check the
  client log for progress percentages before assuming it has hung.
- **Nothing happens when I collect an item / I'm not receiving items** -- confirm with `/status` that the client
  is connected and in-game, and remember that items (including your own) are delivered by the client roughly
  every half second rather than instantly on pickup; if the client isn't running and connected, nothing is
  delivered until it reconnects. `/mp2_debug_inventory` can help confirm whether a delivery actually landed in
  game memory.
