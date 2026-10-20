#!/usr/bin/env bash
# ==============================================================================
# toggle-phase.sh - switch between the two Niri appearance phases
#
# Phase 1: repo-default  opacity 0.90, blur passes 6, offset 4.0,
#                        noise 0.03, saturation 1.2
# Phase 2: personal      opacity 0.75, blur passes 2, offset 3.0,
#                        noise 0.03, saturation 1.0, corner radius 20
#
# Both phase files contain the same application and Noctalia layer rules.
# Only rules.kdl is replaced. Display, input, keybinds, autostart, wallpaper,
# and Noctalia state are never touched by this script.
#
# Usage:
#   ./toggle-phase.sh status
#   ./toggle-phase.sh personal
#   ./toggle-phase.sh repo-default
# ==============================================================================

set -Eeuo pipefail

CFG_DIR="$HOME/.config/niri/cfg"
TARGET_RULES="$CFG_DIR/rules.kdl"
PHASE_PERSONAL="$CFG_DIR/rules-personal.kdl"
PHASE_REPO_DEFAULT="$CFG_DIR/rules-repo-default.kdl"
STATE_ROOT="${XDG_STATE_HOME:-$HOME/.local/state}/niri-dots"
PHASE_MARKER="$STATE_ROOT/phase"
BACKUP_ROOT="$STATE_ROOT/backups"

MODE="${1:-status}"
STAGE_DIR=""
BACKUP_DIR=""
TARGET_TMP=""

log()  { printf '%s\n' "$*"; }
err()  { printf 'ERROR: %s\n' "$*" >&2; }

die() {
    err "$*"
    exit 1
}

usage() {
    cat <<'EOF'
Usage: ./toggle-phase.sh <command>

Commands:
  status          Show the active phase and its key values (default)
  personal        Switch to Phase 2 (your personal appearance)
  repo-default    Switch to Phase 1 (repository defaults)

Aliases:
  phase2, 2       personal
  phase1, 1, repo, default
                  repo-default
EOF
}

cleanup() {
    [ -z "$TARGET_TMP" ] || rm -f -- "$TARGET_TMP"
    [ -z "$STAGE_DIR" ] || rm -rf -- "$STAGE_DIR"
}
trap cleanup EXIT

# Remove comments and insignificant whitespace so a file with a different
# header comment still compares equal to its phase source.
semantic_copy() {
    local source_file="$1"
    local destination_file="$2"
    python3 - "$source_file" "$destination_file" <<'PYEOF'
import re
import sys

source, destination = sys.argv[1], sys.argv[2]
lines = []
with open(source, "r", encoding="utf-8") as handle:
    for raw in handle:
        line = raw.split("//", 1)[0].rstrip()
        if line.strip():
            lines.append(re.sub(r"\s+", " ", line.strip()))
with open(destination, "w", encoding="utf-8", newline="\n") as handle:
    handle.write("\n".join(lines) + "\n")
PYEOF
}

show_values() {
    local file="$1"
    log "  Key values in $file:"
    grep -E '^[[:space:]]*(passes|offset|noise|saturation|opacity|geometry-corner-radius)[[:space:]]' "$file" \
        | sed 's/^/    /' || true
}

show_status() {
    [ -f "$TARGET_RULES" ] || die "no $TARGET_RULES; run ./apply-dots.sh first"
    command -v python3 >/dev/null 2>&1 || die "python3 is required for status"
    command -v cmp >/dev/null 2>&1 || die "cmp is required for status"

    local compare_dir
    compare_dir="$(mktemp -d "${TMPDIR:-/tmp}/mydotfiles-phase-status.XXXXXX")"
    # shellcheck disable=SC2064
    trap "rm -rf -- '$compare_dir'; cleanup" EXIT

    semantic_copy "$TARGET_RULES" "$compare_dir/active"
    semantic_copy "$PHASE_PERSONAL" "$compare_dir/personal"
    semantic_copy "$PHASE_REPO_DEFAULT" "$compare_dir/repo-default"

    local detected="custom/modified"
    if cmp -s "$compare_dir/active" "$compare_dir/personal"; then
        detected="personal (Phase 2)"
    elif cmp -s "$compare_dir/active" "$compare_dir/repo-default"; then
        detected="repo-default (Phase 1)"
    fi

    log "Active appearance phase: $detected"
    if [ -f "$PHASE_MARKER" ]; then
        log "Stored phase marker:     $(tr -d '[:space:]' < "$PHASE_MARKER")"
        local stored
        stored="$(tr -d '[:space:]' < "$PHASE_MARKER" || true)"
        case "$stored:$detected" in
            personal:personal*|repo-default:repo-default*) ;;
            "") ;;
            *) log "WARNING: marker and rules.kdl disagree; run ./toggle-phase.sh <phase> to resynchronize." ;;
        esac
    else
        log "Stored phase marker:     (none)"
    fi

    show_values "$TARGET_RULES"
    log ""
    log "Switch with: ./toggle-phase.sh personal"
    log "             ./toggle-phase.sh repo-default"
    rm -rf -- "$compare_dir"
    trap cleanup EXIT
}

case "$MODE" in
    status)
        show_status
        exit 0
        ;;
    personal|phase2|2)
        PHASE_FILE="$PHASE_PERSONAL"
        PHASE_NAME="personal"
        PHASE_LABEL="Phase 2 (Personal Preferences)"
        ;;
    repo-default|repo|default|phase1|1)
        PHASE_FILE="$PHASE_REPO_DEFAULT"
        PHASE_NAME="repo-default"
        PHASE_LABEL="Phase 1 (Repository Default)"
        ;;
    -h|--help|help)
        usage
        exit 0
        ;;
    *)
        usage >&2
        die "unknown command '$MODE'"
        ;;
esac

[ "$#" -le 1 ] || die "too many arguments; use one phase command at a time"
[ -f "$TARGET_RULES" ] || die "$TARGET_RULES not found; run ./apply-dots.sh first"
[ -f "$PHASE_FILE" ] || die "$PHASE_FILE not found; run ./apply-dots.sh first"
command -v python3 >/dev/null 2>&1 || die "python3 is required"
command -v cmp >/dev/null 2>&1 || die "cmp is required"
command -v niri >/dev/null 2>&1 || die "niri is required to validate the phase"

log "Switching to $PHASE_LABEL..."
show_values "$PHASE_FILE"

# ---------------------------------------------------------------------------
# Stage the full Niri config with the candidate phase and validate it before
# replacing anything in ~/.config.
# ---------------------------------------------------------------------------
STAGE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mydotfiles-phase.XXXXXX")"
mkdir -p "$STAGE_DIR/niri"
cp -a -- "$HOME/.config/niri/." "$STAGE_DIR/niri/"
cp -a -- "$PHASE_FILE" "$STAGE_DIR/niri/cfg/rules.kdl"

semantic_copy "$TARGET_RULES" "$STAGE_DIR/active.norm"
semantic_copy "$PHASE_FILE" "$STAGE_DIR/candidate.norm"
if cmp -s "$STAGE_DIR/active.norm" "$STAGE_DIR/candidate.norm"; then
    log "This phase is already active. No file changes are needed."
    mkdir -p "$STATE_ROOT"
    printf '%s\n' "$PHASE_NAME" > "$PHASE_MARKER"
    log "Phase marker synchronized: $PHASE_MARKER"
    exit 0
fi

log "Validating staged Niri configuration..."
if ! niri validate --config "$STAGE_DIR/niri/config.kdl"; then
    die "candidate phase failed validation; the active config was not changed"
fi
log "  [OK] Candidate phase is valid"

# ---------------------------------------------------------------------------
# Back up the current rules and marker, then replace rules.kdl atomically.
# ---------------------------------------------------------------------------
mkdir -p "$BACKUP_ROOT"
chmod 700 "$BACKUP_ROOT" 2>/dev/null || true
BACKUP_DIR="$(mktemp -d "$BACKUP_ROOT/phase-$(date +%Y%m%d-%H%M%S).XXXXXX")"
chmod 700 "$BACKUP_DIR" 2>/dev/null || true
cp -a -- "$TARGET_RULES" "$BACKUP_DIR/rules.kdl" \
    || die "could not back up the current rules.kdl"
if [ -f "$PHASE_MARKER" ]; then
    cp -a -- "$PHASE_MARKER" "$BACKUP_DIR/phase-marker" \
        || die "could not back up the phase marker"
fi
log "Backup: $BACKUP_DIR"

TARGET_TMP="$CFG_DIR/.rules.kdl.tmp.$$"
cp -a -- "$PHASE_FILE" "$TARGET_TMP" || die "could not create the temporary rules file"
mv -f -- "$TARGET_TMP" "$TARGET_RULES" || die "could not replace rules.kdl"
TARGET_TMP=""

# Validate the file at its real location, including all includes in config.kdl.
if ! niri validate; then
    err "deployed rules.kdl failed validation; restoring the previous phase"
    cp -a -- "$BACKUP_DIR/rules.kdl" "$TARGET_RULES"
    if [ -f "$BACKUP_DIR/phase-marker" ]; then
        cp -a -- "$BACKUP_DIR/phase-marker" "$PHASE_MARKER"
    else
        rm -f -- "$PHASE_MARKER"
    fi
    if niri msg version >/dev/null 2>&1; then
        niri msg action load-config-file >/dev/null 2>&1 \
            || err "could not reload the restored config; reload manually"
    fi
    exit 1
fi
log "  [OK] Deployed rules.kdl is valid"

# ---------------------------------------------------------------------------
# Reload only when Niri is running, and fail loudly if the reload fails.
# ---------------------------------------------------------------------------
if niri msg version >/dev/null 2>&1; then
    if reload_output="$(niri msg action load-config-file 2>&1)"; then
        log "  [OK] Niri reloaded with: niri msg action load-config-file"
        [ -z "$reload_output" ] || log "       $reload_output"
    else
        err "Niri reload failed: ${reload_output:-niri msg action load-config-file returned non-zero}"
        err "Restoring the previous phase because the running config was not reloaded."
        cp -a -- "$BACKUP_DIR/rules.kdl" "$TARGET_RULES"
        if [ -f "$BACKUP_DIR/phase-marker" ]; then
            cp -a -- "$BACKUP_DIR/phase-marker" "$PHASE_MARKER"
        else
            rm -f -- "$PHASE_MARKER"
        fi
        if niri msg action load-config-file >/dev/null 2>&1; then
            err "Previous phase restored and reloaded."
        else
            err "Previous phase restored on disk, but it could not be reloaded. Reload manually."
        fi
        exit 1
    fi
else
    log "  Niri is not running; the phase will be active on next login."
fi

# Record the phase only after the file is valid and (when applicable) reloaded.
mkdir -p "$STATE_ROOT"
printf '%s\n' "$PHASE_NAME" > "$PHASE_MARKER"
log ""
log "Active phase: $PHASE_NAME"
log "Backup:       $BACKUP_DIR"
log "Marker:       $PHASE_MARKER"
log "The display, input, keybinds, autostart, wallpaper, and Noctalia state were not changed."
