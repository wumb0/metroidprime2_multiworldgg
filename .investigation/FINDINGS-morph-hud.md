# Morph Ball HUD / Dark Visor crash — investigation findings (2026-11-19)

Symptom (TODO verbatim): emerging from Morph Ball and switching to Dark Visor *before the HUD
loads* crashes; often preceded by a stuck Morph Ball HUD (ball HUD stays up while standing, or
standing HUD takes many seconds).

## What was done
- Extracted `main.dol` (NTSC `echoes.iso` + PAL) into this directory via
  `open_prime_rando.patcher_editor` (see `extract_dol.py` note: `IsoFileProvider` +
  `PatcherEditor(...).dol.dol_file.getvalue()`; plain-offset ISO parsing is unreliable here —
  the disc's FST region is not where naive header math points).
- Disassembled the visor/morph state machine with capstone (`dol.py`).

## Established facts (NTSC addresses)
- `CPlayerState` (pointer at `CPlayer+0x1314`): `+0x30` current visor, `+0x34` transitioning-to
  visor; `CPlayer::StartTransitionToVisor` = 0x80085314 (sets +0x34),
  `CPlayer::ResetVisor` = 0x80085334 (forces both to 0 + reset float +0x50).
  OPR patches these for the starting-visor feature (`dol_patching/echoes/dol_patches.py`).
- `CPlayer::SetMorphMode` = 0x80016a14: stores morph mode `CPlayer+0x38c`, flag `+0x169`,
  updates `CPlayerGunController` (0x800c13ec). EnterMorphBallState = 0x80184118 (calls
  `StartTransitionToVisor(state, 0)` at +0xec — ball forces visor 0, matching OPR's patch site).
- Visor **input** handler ≈ 0x800174f4: refuses a visor change while `CPlayer+0x38c != 0`
  (in ball) and while a player-state transition is pending — i.e. **the gate is purely
  player-side**. Nothing here consults HUDController state.
- HUD module ≈ 0x8006B000-0x80071000 (`display_hud_memo` 0x8006B3C8): HUD *polls*
  `CPlayer+0x38c` (morph) — dense cluster of readers in this region — so HUD frame updates are
  async/poll-driven relative to player state.
- HUD is frame-based (`CGuiSys`): `FRME_SamusHud1Combat` (one frame shared by Combat, **Dark**
  and Echo visors), `FRME_SamusHud1Ball` (morph ball HUD) — per EchoesWidescreenHUD. Frame
  swaps load resources asynchronously.
- Game option `hud_lag` (`CGameOptions` flag bit, see OPR `dol_patching/echoes/game_options.py`
  `_FLAGS_ORDER[0]`, default **True**) — the game's own HUD-delays feature. Our patcher_runner
  does **not** patch game options today, so our seeds run vanilla defaults (hud_lag ON), same
  as vanilla.

## "Only in OPR-patched games" — patch-surface audit (2026-11-19)
User: vanilla does NOT hang; OPR-patched games DO. Audited every DOL site the MWGG
patch path (`patcher.patch_iso`/`apply_dol_patches`, the NEW flow — MWGG never calls
`legacy_patcher.patch_dol`) writes, against the disassembled NTSC main.dol:
- `apply_starting_visor_patch` (ResetVisor/EnterMorphBallState+0xE8/constructors):
  **NOT applied in MWGG** — legacy-only path. Vanilla visor code is intact in our games.
  (Even in standalone it's byte-equal no-ops for Combat default, plus one latent quirk:
  the clean-constructor rewrite overwrites `lfs f0,-0x77f0(r2)` whose value vanilla later
  stores via `stfs f0,0x48(r30)` — f0 ends up as whatever `health_info_constructor` left.)
- `inventory_slot`: frees `kInventorySlotToItemType` (0x803ACAE0, 0x35 words) into the data
  cave and rewrites `load_scan_tree_inventory_slot_usage` (0x8020ED98) to the new byte array.
  Whole-DOL xref scan: **0x8020EDA0 is the table's ONLY consumer** → no dangling references.
- `apply_remote_execution_patch`: **replaces `update_hint_state` 0x80038020 wholesale** with
  the remote-exec stub (idle → early return; vanilla hint/string-ref body NEVER runs; on
  pending op: cutscene check CStateManager+0x16FC, `icbi` self-mod loop, falls into the
  externally-written body at 0x80038020+N). This is the only per-frame semantic hijack of
  game code in the whole patch set — and MWGG runs remote bodies from the client (warps,
  grants) through it. Prime suspect for making an engine race fatal.
- Other writes are map-screen/door-color/beam-cost/options/health-constant/vfx territory.
**Decisive cheap test**: standalone OPR dev + default patches + practice mod (free Dark
Visor) → repro attempt. Hangs → OPR patch layer (remote-exec hijack) — upstream-reportable.
Doesn't → MWGG-specific delta (world paks, cave content, client's remote-op traffic).

## Root-cause pattern (high confidence for the window; one link unproven)
On un-morph the player state flips to standing immediately and visor input unlocks
(0x800174f4 guards), while the HUD is still asynchronously swapping `SamusHud1Ball` →
`SamusHud1Combat`. A Dark Visor press in that window delivers a visor-change to a HUD that is
mid frame-swap of the very same shared frame; the HUD ends up in the broken "ball HUD stuck"
state and the next visor touch wedges it.
**IMPORTANT (user correction 2026-11-19): the game HANGS — it does not crash, and Dolphin
writes no panic log.** A silent hang points at a **spin/busy-wait** (or a wedged state whose
completion notification never fires), not a null deref — consistent with code waiting on a
frame-load/transition-completion flag that the dropped swap never sets. This also means the
exact hang site is trivially obtainable (see fix step 2) instead of needing a crash dump.
`hud_lag=True` is the plausible factor that stretches the window to "many seconds".

## Fix options — updated 2026-11-19 from game-machine feedback
- **HUD Lag OFF: does not help** ("the game still crashes with hud_lag off") → option 1 below is
  dead; the engine race is not mitigated by game options.
- **No Dolphin debugger UI available on the user's build** (no View → Open Debugger / Code) →
  capture goes through our own **`.investigation/hang_probe.py`** (dolphin-memory-engine;
  `hook()`/`read_word` API v1.3.1): dumps CPlayer morph mode (+0x38c), in-ball flag (+0x169),
  CPlayerState visor fields (+0x30/+0x34/+0x50), HUDController singleton (*0x803B1F30) fields
  +0x6b4/0x788/0x7f4/0x800 + first 0x60 bytes. Memory reads work during a guest hang (host
  alive). Procedure: run once standing, once in ball, then 2-3x ~1s apart *while hung*; the
  diff names the wedged flag and pins fix #2.
1. ~~A/B: HUD Lag Off~~ — tested, no effect.
2. **Robust DOL fix:** gate visor switching until HUD frame swap completes; the hang_probe diff
   identifies the flag to key it on.
3. (If they ever upgrade Dolphin: pause-at-hang PC via View → Code remains the strongest
   evidence, but is no longer required.)

## Manual test
Vanilla-repro module can't exist in the book (no grants involved); if fix 1 ships, MT
follow-up = enable `disable_hud_lag` and run the same spam — plus confirm option-menu HUD Lag
still behaves.

## Files
- `dol.py` — capstone helpers over the DOL (reads, disasm, bl-xref, pattern scan).
- `main.dol`, `main_pal.dol` — extracted images (do not commit).
