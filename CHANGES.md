# Changes made in this verification pass (16 Oct 2026)

Verified against: niri-wm/niri wiki (26.04 schema) and docs.noctalia.dev
(noctalia v5 lockscreen-widgets / desktop-widgets / date-format-tokens / IPC docs).

## Fixes applied in this pass

1. **`noctalia/.config/noctalia/config.toml`**
   - `format` is now a **single-quoted** TOML string: `'{:%H\n%M\n%A\n%-d %b}'`.
     Noctalia's date formatter needs the *literal* two characters `\n` to draw a
     line break (see docs: Date format tokens). The previous double-quoted
     string turned `\n` into a raw newline before Noctalia saw it.
     All tokens verified: %H, %M, %A, %-d (no padding, glibc modifier), %b.
   - Added `layout = "compact"` to the login box (documented v5 setting:
     "slim password row" - matches the wanted compact password input).

2. **`apply-dots.sh` (v2)**
   - **Critical fix:** `cp -r repo/x/.config/x ~/.config/` **nests** the repo
     into itself when `~/.config/x` already exists (`~/.config/niri/niri/...`),
     silently deploying nothing on re-runs. Now every target dir is replaced
     cleanly after the backup step.
   - State cleanup no longer needs the pip `toml` module (stdlib-only Python),
     no longer prints a fake success line, backs up `settings.toml` first, and
     removes ONLY the stale `[lockscreen_widgets]` section (the calendar came
     from GUI state in `~/.local/state/noctalia/settings.toml`, which **wins
     over config.toml** - that is why it kept coming back).
   - Now calls `noctalia msg config-reload` (documented v5 IPC) so a running
     shell picks up new config without logging out.
   - Non-zero exit code when a validator fails; reloads happen only after both
     validators pass.

3. **`toggle-phase.sh` (v2)**
   - The old "revert" ran `git checkout` on `~/.config/niri/cfg/rules.kdl`,
     which is not a git repo - a failed validation left the broken rules active
     while claiming success. Now a real `.phase-backup` is restored on failure
     and the script exits non-zero.

4. **`fish/.config/fish/conf.d/uv.env.fish`**
   - Guards the `source` with `test -f` so fish doesn't print an error on every
     new shell when uv is not installed.

## Verified correct, unchanged

- `niri/config.kdl` - `mode "1920x1080@144.003"` (string form is valid niri
  syntax; refresh must match `niri msg outputs` exactly), no duplicate
  `prefer-no-csd`, 8 includes all resolve.
- `cfg/misc.kdl` - the repo's original **duplicate** top-level `blur` block was
  correctly removed earlier (niri: "most sections cannot be repeated"). The one
  remaining `blur` lives in `rules.kdl`. All remaining keys are valid 26.04
  options (`screenshot-path null`, `environment`, `cursor`, `debug
  honor-xdg-activation-with-invalid-serial`, `hotkey-overlay`).
- `cfg/rules.kdl` (+ both phase files) - top-level `blur {}` and per-rule
  `background-effect { blur/xray }` are the official niri 26.04 blur syntax;
  the Noctalia layer-rule namespace regex and the `noctalia-window-switcher`
  rule are **verbatim from the official Noctalia niri docs**; opacity 0.90 =
  Phase 1 as requested. Phase files are toggle-only assets (not `include`d by
  niri) - that is by design.
- `cfg/keybinds.kdl` - the `switch-events { lid-close { spawn "noctalia" "msg"
  "session" "lock-and-suspend"; } }` block is **verbatim from the official
  Noctalia docs** (Laptop section); `session lock-and-suspend` is a documented
  IPC command. `lock_before_suspend = true` additionally covers logind's own
  lid-close suspend.
- `cfg/input.kdl` (trackpoint removal is harmless), `display.kdl`, `layout.kdl`
  (`struts` verified), `animation.kdl` (all animation names verified).
- `kitty/kitty.conf` - corrupted double-include line already fixed; font
  enabled; `background_opacity 0.2899` is the AUTHOR's real value (the earlier
  report claiming 0.85 was wrong - 0.2899 is the repository default look).
- `fastfetch/config.jsonc` - trailing-colon color strings fixed; dtime has a
  Btrfs birth-time fallback. Parses as valid JSON.
- `fish/fish_variables` - author's machine state (pure-prompt uvars); kept for
  reference only. `apply-dots.sh` never deploys it (your own stays intact).

## Deploy & verify (run on the CachyOS side, in fish or bash)

```bash
cd ~/niri-noctalia-dots
./apply-dots.sh                 # backup -> deploy -> validate -> live reload
noctalia msg session lock        # visually check the lock screen
noctalia msg lockscreen-widgets-edit   # editor overlay should now appear
./toggle-phase.sh personal      # only after Phase 1 looks right
```

If the lock screen still shows the old calendar after `apply-dots.sh` +
`noctalia msg config-reload`, log out and back in once (a running Noctalia can
rewrite its state from memory).
