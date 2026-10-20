# Changes made in the verification and reliability pass

**Date:** 20 Oct 2026

This pass replaces several unsafe assumptions from the earlier "verified"
state. The most important correction is that the previous scripts used
`niri msg reload-config`, which is not a valid command, and then hid the
failure. That is fixed in both scripts.

> **Runtime status:** the repository was audited and edited in a non-Linux
> working copy. Niri, Noctalia, and Fish were not available there, so
> `niri validate`, `noctalia config validate`, `fish -n`, the live reload, and
> the visual lock screen were **not executed**. They must be run on the
> CachyOS machine. The static verifier reports those checks as `SKIP`, never
> as `PASS`.

## 1. Correct reload command and honest failure handling

**Files:** `apply-dots.sh`, `toggle-phase.sh`

- Replaced `niri msg reload-config` with the real IPC action:
  `niri msg action load-config-file`.
- Removed `|| true` from the reload path. A failed Niri reload now exits
  non-zero.
- `apply-dots.sh` no longer prints "Deployment complete" after a failed
  reload. It prints the actual Niri and Noctalia reload status.
- `toggle-phase.sh` restores the previous `rules.kdl` and phase marker if the
  reload fails, then attempts to reload the restored config.

## 2. Staged deployment, complete backup, and automatic rollback

**File:** `apply-dots.sh`

- Preflight now checks required files, required commands, the `eDP-1`
  display contract, the absence of `1366x768`, and exactly one active blur
  block **before** writing anything.
- The complete configuration is copied to a temporary staging directory and
  validated with `niri validate --config` and
  `noctalia config validate <staged-dir>`.
- The Noctalia state migration is also exercised read-only before deployment.
- Backups are unique directories under
  `~/.local/state/niri-dots/backups/`, created with `mktemp -d` and mode 700.
  They include `~/.config/{niri,noctalia,kitty,fish,fastfetch}` plus
  Noctalia's `settings.toml` and `state.toml`.
- Backup success is verified before deployment continues.
- Existing files are merged, not delete-replaced, so unrelated user files and
  Noctalia palettes/plugins are preserved.
- Fish deployment still copies only `config.fish` and
  `conf.d/uv.env.fish`; `fish_variables` is never deployed.
- Wallpapers are installed with no-clobber behavior, so an existing personal
  file with the same name is preserved.
- A failed copy, validation, state migration, or reload triggers rollback from
  the verified backup. Newly created files are removed and modified files are
  restored.
- Added `--dry-run`, `--no-reload`, and `--phase` options.

## 3. Phase preservation and safe switching

**Files:** `apply-dots.sh`, `toggle-phase.sh`,
`niri/.config/niri/cfg/rules.kdl`

- The active phase is stored in `~/.local/state/niri-dots/phase`.
- `apply-dots.sh` preserves that marker instead of always resetting to Phase 1.
- A fresh clone defaults to **personal (Phase 2)**, as approved.
- The active `rules.kdl` was changed from Phase 1 to Phase 2 (opacity 0.75,
  blur passes 2, offset 3.0, noise 0.03, saturation 1.0, radius 20).
- `toggle-phase.sh` now:
  - supports `status`, `personal`, and `repo-default` (plus aliases);
  - stages the full Niri config and validates before replacing;
  - compares phase files semantically, so a different header comment does not
    count as a different phase;
  - backs up `rules.kdl` and the phase marker in a unique directory;
  - replaces `rules.kdl` atomically;
  - validates again at the real path;
  - uses `niri msg action load-config-file` and fails loudly;
  - does not run `git checkout`;
  - never touches display, input, keybinds, autostart, wallpaper, or Noctalia
    state.

## 4. Selective Noctalia state management

**Files:** `scripts/noctalia-state.py` (new), `apply-dots.sh`

The previous script removed the entire `[lockscreen_widgets]` section from
`~/.local/state/noctalia/settings.toml`. That could discard unrelated widget
layout and styling. The new helper:

- removes only Calendar widget tables and Calendar entries from
  `widget_order`;
- preserves the clock, login box, grid, schema version, and all unrelated
  state;
- updates `[lockscreen]` blur to 0.80 and tint to 0.45 only when those keys
  already exist;
- updates a stale lock-screen wallpaper path or palette only when those keys
  already exist;
- parses the state with `tomllib` before and after editing;
- writes atomically;
- handles a symlinked `settings.toml` by writing through to the target;
- never deletes the state directory.

The apply script backs up the state before migration. If migration fails,
deployment rolls back.

## 5. Lock-screen and theme values

**File:** `noctalia/.config/noctalia/config.toml`

- Lock-screen blur intensity changed from `0.50` to **`0.80`**.
- Lock-screen tint intensity changed from `0.30` to **`0.45`**.
- Added declarative theme defaults:
  - `[theme] source = "wallpaper"`;
  - `[theme] wallpaper_scheme = "m3-content"`.
- Added `[wallpaper.default] path` pointing to
  `~/Pictures/Wallpapers/niri-noctalia-dots/city-girl-sunset.png`.
- Kept the approved clock format
  `'{:%H\n%M\n%A\n%-d %b}'`, clock/login positions, compact login layout, and
  the absence of a Calendar widget.
- These values were checked against the current Noctalia v5+ documentation:
  `clock` and `login_box` widget types, `layout = "compact"`, `color`,
  `shadow`, `center_text`, `show_login_button`, and literal `\n` in date
  formats are documented as valid.

## 6. Verification suite

**File:** `verify_dots.py`

The old suite could report an all-green result while missing real failures. It
checked substrings, brace counts, and file sizes. The new suite adds, among
other checks:

- all eight Niri includes exist, are expected, and appear exactly once;
- exactly one active `eDP-1` output block with the correct mode, scale,
  transform, and position;
- exactly one top-level blur block across the included files;
- active `rules.kdl` matches the personal phase semantically;
- both phase files contain their expected values;
- per-app opacity/blur rules for Firefox, Discord, Nautilus, mpv, and VLC;
- Noctalia TOML parses, widget order is clock + login box only, and no Calendar
  type is declared;
- clock format/tokens/color/shadow and login-box compact layout;
- theme source, wallpaper scheme, and preferred wallpaper;
- Kitty include target exists and theme colors are valid hex;
- Fish guards optional files and initializes Starship;
- Fastfetch JSONC parses with comments/trailing commas;
- wallpapers contain actual PNG/JPEG/WebP data (not just a large file);
- `bash -n`, script strict mode, staging, backup, rollback, phase marker, and
  the correct reload command;
- no `sudo`, no upstream clone URL, and no obvious committed secrets;
- README/CHANGES commands and paths match the scripts.

Runtime checks are reported as `SKIP` when the tool is unavailable. The suite
does not claim a live lock-screen test.

## 7. Documentation

**Files:** `README.md`, `CHANGES.md`

- Replaced the upstream clone URL with
  `https://github.com/supan1676/mydotfiles.git` and `~/mydotfiles`.
- Replaced the old HP i3-6006U description with the ASUS TUF F15 hardware.
- Documented the 1920×1080 @ 144.003 Hz display contract.
- Documented the staged install flow, dependencies, dry run, phase switching,
  backup locations, and manual rollback.
- Documented the lock-screen target, blur/tint test values, wallpaper, editor
  command, state precedence, and the warning that testing locks the session.
- Documented the real reload commands and the Noctalia state caveat.
- Marked the screenshots as legacy 1366×768 previews.
- Noted that `12.png`, `18.png`, and `30.png` contain JPEG/WebP data despite
  their `.png` names. They were not renamed without approval.

## 8. Known limitations and next runtime checks

These are intentionally **not** claimed as verified:

1. `niri validate`, `noctalia config validate`, and `fish -n` have not run in
   this environment.
2. The live reload and lock-screen appearance have not been tested.
3. Nautilus, Firefox, Discord, mpv, and VLC app-ids should be confirmed with
   `niri msg windows` on the actual session.
4. Noctalia's running state may still contain GUI overrides outside the
   Calendar/blur/tint/wallpaper keys changed by the helper. Inspect
   `~/.local/state/noctalia/settings.toml` after a test lock.
5. The legacy screenshot is 1366×768 and does not prove the 1080p layout.
6. `niri-noctalia-dots-fixed.tar.gz` is an obsolete archive and is not used by
   the installer.

## Deploy and verify on CachyOS

```bash
cd ~/mydotfiles

./apply-dots.sh --dry-run          # no changes
./apply-dots.sh                    # backup -> stage -> validate -> deploy -> reload
./toggle-phase.sh status           # should report personal (Phase 2)
python3 verify_dots.py             # runtime checks run when tools are present

niri msg outputs                   # eDP-1 @ 1920x1080 144.003
niri msg windows                   # real app-ids

# Only after saving work and confirming you can unlock:
noctalia msg session lock
```

If the lock screen is wrong, unlock with your password, inspect the state file,
and restore the apply backup. Do not delete the entire Noctalia state directory.
