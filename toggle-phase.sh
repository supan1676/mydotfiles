#!/usr/bin/env bash
# ==============================================================================
# toggle-phase.sh - Switch between Phase 1 (Repo Default) and Phase 2 (Personal)
#
# v2: the old version "reverted" with `git checkout` on
# ~/.config/niri/cfg/rules.kdl, which is NOT inside a git repository, so a
# failed validation left the broken rules.kdl active while claiming success.
# Now a real backup file is restored, and the script exits non-zero on failure.
#
# Phase 1 (rules-repo-default.kdl): opacity 0.90, blur passes 6 / offset 4.0 /
#   noise 0.03 / saturation 1.2  (repository README default)
# Phase 2 (rules-personal.kdl):    opacity 0.75, blur passes 2 / offset 3.0 /
#   noise 0.03 / saturation 1.0, corner radius 20 (personal preferences)
# Both keep the same app rules: Firefox 0.75 blur on, Discord 0.73 blur off,
# Nautilus 0.65 blur on, mpv/VLC 1.0, Noctalia surfaces blur on / xray off.
# ==============================================================================

set -euo pipefail

CFG_DIR="$HOME/.config/niri/cfg"
TARGET_RULES="$CFG_DIR/rules.kdl"

MODE="${1:-status}"

case "$MODE" in
    "repo"|"default"|"phase1"|"1")
        PHASE_FILE="$CFG_DIR/rules-repo-default.kdl"
        echo "Switching to Phase 1 (Repository Default):"
        echo "  opacity 0.90 | blur passes 6, offset 4.0, noise 0.03, saturation 1.2"
        ;;
    "personal"|"phase2"|"2")
        PHASE_FILE="$CFG_DIR/rules-personal.kdl"
        echo "Switching to Phase 2 (Personal Preferences):"
        echo "  opacity 0.75 | blur passes 2, offset 3.0, noise 0.03, saturation 1.0"
        echo "  corner radius 20 | app overrides: Firefox 0.75 blur on, Discord 0.73 blur off,"
        echo "  Nautilus 0.65 blur on, mpv/VLC 1.0"
        ;;
    "status"|*)
        echo "Usage: $0 [default|personal]"
        echo ""
        if [ -f "$TARGET_RULES" ]; then
            echo "Current ~/.config/niri/cfg/rules.kdl settings:"
            grep -E "passes |^    opacity" "$TARGET_RULES" | head -n 3
        else
            echo "No rules.kdl found - run ./apply-dots.sh first."
        fi
        exit 0
        ;;
esac

if [ ! -f "$TARGET_RULES" ]; then
    echo "ERROR: $TARGET_RULES not found. Run ./apply-dots.sh first."
    exit 1
fi
if [ ! -f "$PHASE_FILE" ]; then
    echo "ERROR: $PHASE_FILE not found. Run ./apply-dots.sh first."
    exit 1
fi

# Real safety backup of the currently active rules
BACKUP_RULES="$TARGET_RULES.phase-backup"
cp "$TARGET_RULES" "$BACKUP_RULES"

cp "$PHASE_FILE" "$TARGET_RULES"
echo ""

echo "Validating Niri config..."
if command -v niri >/dev/null 2>&1 && niri validate; then
    echo "[OK] Validation passed."
    rm -f "$BACKUP_RULES"
    if command -v pgrep >/dev/null 2>&1 && pgrep -x niri >/dev/null 2>&1; then
        niri msg reload-config
        echo "[OK] Niri reloaded."
    fi
else
    echo "[ERROR] Validation failed! Restoring previous rules.kdl..."
    mv "$BACKUP_RULES" "$TARGET_RULES"
    echo "Restored the previous rules.kdl. Fix the phase file and retry."
    exit 1
fi
