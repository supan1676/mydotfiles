#!/usr/bin/env bash
# ==============================================================================
# apply-dots.sh - Safe Deployment & Validation Script for ASUS TUF Gaming F15
# Distribution: CachyOS (Arch Linux) | WM: Niri 26.04 | Shell: Noctalia v5.2.1
#
# v2 (verified against niri-wm/niri wiki + docs.noctalia.dev, Oct 2026):
#   - FIX: the old `cp -r repo/x/.config/x ~/.config/` NESTED the repo into
#     itself when ~/.config/x already existed (~/.config/niri/niri/...), so a
#     re-run silently deployed nothing. Each target dir is now replaced
#     cleanly (old copy is in the timestamped backup).
#   - FIX: Noctalia state cleanup no longer needs the pip `toml` module
#     (stdlib-only), reports honestly what it did, and removes ONLY the stale
#     [lockscreen_widgets] section from settings.toml (with a backup copy).
#     GUI state in settings.toml overrides config.toml - that override is why
#     the old calendar kept coming back.
#   - NEW: calls `noctalia msg config-reload` so a running shell picks up the
#     new config.toml live (documented Noctalia v5 IPC).
#   - Exit code is non-zero if either validator fails.
# ==============================================================================

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DATE="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$HOME/config-backup/auto-apply-$BACKUP_DATE"

echo "=========================================================="
echo "  Deploying Niri + Noctalia Dotfiles (ASUS TUF Gaming F15)"
echo "=========================================================="
echo "Repository source: $REPO_DIR"
echo "Target backup:     $BACKUP_DIR"
echo ""

# 1. Create safety backup of existing configs
echo "[1/6] Creating backup of current configs..."
mkdir -p "$BACKUP_DIR"
for cfg in niri noctalia kitty fish fastfetch; do
    if [ -d "$HOME/.config/$cfg" ]; then
        cp -a "$HOME/.config/$cfg" "$BACKUP_DIR/"
        echo "  Backed up ~/.config/$cfg -> $BACKUP_DIR/$cfg"
    fi
done

# Also backup Noctalia state if present
if [ -d "$HOME/.local/state/noctalia" ]; then
    mkdir -p "$BACKUP_DIR/local-state-noctalia"
    cp -a "$HOME/.local/state/noctalia" "$BACKUP_DIR/local-state-noctalia/"
    echo "  Backed up ~/.local/state/noctalia -> $BACKUP_DIR/local-state-noctalia/"
fi

# 2. Deploy dotfiles into ~/.config (REPLACE, never merge/nest)
echo ""
echo "[2/6] Deploying configurations to ~/.config/..."
mkdir -p "$HOME/.config"

# replace_dir <repo-relative-src> <target-name>
# The old contents are safely stored in the backup from step 1.
replace_dir() {
    local src="$REPO_DIR/$1"
    local dst="$HOME/.config/$2"
    rm -rf "$dst"
    cp -a "$src" "$dst"
    echo "  Deployed ~/.config/$2 (replaced)"
}

replace_dir "niri/.config/niri"          "niri"
replace_dir "noctalia/.config/noctalia"  "noctalia"
replace_dir "kitty/.config/kitty"        "kitty"
replace_dir "fastfetch/.config/fastfetch" "fastfetch"

# For fish: copy config.fish and conf.d only - NEVER touch the user's
# fish_variables (the repo copy contains the author's pure-prompt uvars and
# is kept for reference only).
mkdir -p "$HOME/.config/fish/conf.d"
cp "$REPO_DIR/fish/.config/fish/config.fish" "$HOME/.config/fish/config.fish"
if [ -f "$REPO_DIR/fish/.config/fish/conf.d/uv.env.fish" ]; then
    cp "$REPO_DIR/fish/.config/fish/conf.d/uv.env.fish" "$HOME/.config/fish/conf.d/"
fi
echo "  Deployed fish (config.fish + conf.d; fish_variables left untouched)"

# Clean up any stray corrupted filename with a literal trailing backslash
# (created by an earlier mis-quoted shell command on the Linux side).
if [ -e "$HOME/.config/niri/cfg/rules.kdl\\" ]; then
    rm -f "$HOME/.config/niri/cfg/rules.kdl\\"
    echo "  Removed stray file: ~/.config/niri/cfg/rules.kdl\\"
fi

# 3. Deploy wallpapers (repo set only; personal files in the folder are kept)
echo ""
echo "[3/6] Deploying wallpapers..."
WALLPAPER_DIR="$HOME/Pictures/Wallpapers/niri-noctalia-dots"
mkdir -p "$WALLPAPER_DIR"
cp -a "$REPO_DIR/wallpapers/." "$WALLPAPER_DIR/"
echo "  Copied wallpapers to $WALLPAPER_DIR"

# 4. Synchronize Noctalia lock screen state
echo ""
echo "[4/6] Updating Noctalia lock screen state..."
# Noctalia v5 loads ~/.config/noctalia/*.toml first, then merges
# ~/.local/state/noctalia/settings.toml ON TOP (GUI state wins). If the state
# file still holds a [lockscreen_widgets] section (e.g. the old calendar
# widget added from the GUI), it overrides our config.toml no matter what we
# deploy. Remove exactly that section, keep everything else, back up first.
STATE_FILE="$HOME/.local/state/noctalia/settings.toml"
if [ -f "$STATE_FILE" ]; then
    cp "$STATE_FILE" "$STATE_FILE.bak-$BACKUP_DATE"
    PY_BIN="$(command -v python3 || command -v python || true)"
    if [ -n "$PY_BIN" ]; then
        "$PY_BIN" - "$STATE_FILE" <<'PYEOF' || echo "  WARNING: state cleanup failed - inspect $STATE_FILE manually"
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    lines = f.readlines()

out, inside, removed = [], False, 0
for line in lines:
    stripped = line.strip()
    if stripped.startswith("["):
        # New TOML table header - only keep dropping lines while we are inside
        # a [lockscreen_widgets] or [lockscreen_widgets.*] table.
        inside = stripped.startswith("[lockscreen_widgets")
    if inside:
        removed += 1
    else:
        out.append(line)

if removed:
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(out)
    print("  Removed stale [lockscreen_widgets] from settings.toml (%d lines)" % removed)
    print("  The clock + login box from config.toml now take effect")
else:
    print("  settings.toml has no [lockscreen_widgets] override - nothing to clean")
PYEOF
    else
        echo "  WARNING: no python3 found - left $STATE_FILE untouched."
    fi
else
    echo "  No $STATE_FILE present (fresh install) - nothing to clean"
fi

# 5. Run validators
echo ""
echo "[5/6] Validating configurations..."
NIRI_VALID=true
NOCTALIA_VALID=true

if command -v niri >/dev/null 2>&1; then
    echo "  Running: niri validate"
    if niri validate; then
        echo "  [OK] Niri configuration is valid"
    else
        echo "  [ERROR] Niri validation failed! Review ~/.config/niri/"
        NIRI_VALID=false
    fi
else
    echo "  [SKIP] 'niri' binary not found in PATH"
fi

if command -v noctalia >/dev/null 2>&1; then
    echo "  Running: noctalia config validate"
    if noctalia config validate; then
        echo "  [OK] Noctalia configuration is valid"
    else
        echo "  [ERROR] Noctalia config validation failed! Review ~/.config/noctalia/config.toml"
        NOCTALIA_VALID=false
    fi
else
    echo "  [SKIP] 'noctalia' binary not found in PATH"
fi

# 6. Apply live reload & theme if the shells are actually running
echo ""
echo "[6/6] Reloading live desktop..."
if [ "$NIRI_VALID" = true ] && command -v niri >/dev/null 2>&1 \
   && command -v pgrep >/dev/null 2>&1 && pgrep -x niri >/dev/null 2>&1; then
    niri msg reload-config || true
    echo "  Reloaded Niri configuration"
else
    echo "  Niri not running (or validation failed) - config applies on next login"
fi

if [ "$NOCTALIA_VALID" = true ] && command -v noctalia >/dev/null 2>&1 \
   && command -v pgrep >/dev/null 2>&1 && pgrep -x noctalia >/dev/null 2>&1; then
    noctalia msg config-reload 2>/dev/null \
        || echo "  (config-reload unsupported by this build - restart Noctalia to pick up config)"
    PREF_WP="$WALLPAPER_DIR/city-girl-sunset.png"
    if [ -f "$PREF_WP" ]; then
        noctalia msg wallpaper-set "$PREF_WP" 2>/dev/null || true
    fi
    noctalia msg color-scheme-set wallpaper m3-content 2>/dev/null || true
    echo "  Applied config reload, wallpaper, and theme (wallpaper m3-content)"
else
    echo "  Noctalia not running (or validation failed) - starts fresh on next login"
fi

echo ""
echo "=========================================================="
echo "  Deployment complete!"
echo "=========================================================="
echo "Active: Phase 1 - repository default (opacity 0.90, blur"
echo "passes 6). NOTE: this script always resets rules.kdl to Phase 1."
echo "Your personal look:  ./toggle-phase.sh personal"
echo "Test the lock screen:  noctalia msg session lock"
echo "=========================================================="

if [ "$NIRI_VALID" = true ] && [ "$NOCTALIA_VALID" = true ]; then
    exit 0
else
    echo "One or more validators FAILED - configs were deployed but NOT reloaded."
    exit 1
fi
