#!/usr/bin/env bash
# ==============================================================================
# apply-dots.sh - deploy this repository's Niri + Noctalia configuration
#
# Design goals:
#   1. Never touch the live configuration until the staged configuration has
#      passed validation.
#   2. Back up every file we may change, in a unique directory, before writing.
#   3. Preserve the user's active appearance phase instead of resetting it.
#   4. Roll back automatically if deployment, validation, or reload fails.
#   5. Report reload failures honestly (no "success" after a failed command).
#
# Usage:
#   ./apply-dots.sh                 # deploy, preserving the active phase
#   ./apply-dots.sh --phase personal
#   ./apply-dots.sh --phase repo-default
#   ./apply-dots.sh --dry-run       # validate/stage only; change nothing
#   ./apply-dots.sh --no-reload     # deploy; reload on next login
#   ./apply-dots.sh --help
#
# The default phase on a fresh clone is "personal" (Phase 2).
# ==============================================================================

set -Eeuo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
STATE_ROOT="${XDG_STATE_HOME:-$HOME/.local/state}/niri-dots"
PHASE_MARKER="$STATE_ROOT/phase"
BACKUP_ROOT="$STATE_ROOT/backups"
DEFAULT_PHASE="personal"

PREFERRED_WALLPAPER="$HOME/Pictures/Wallpapers/niri-noctalia-dots/city-girl-sunset.png"
WALLPAPER_SOURCE="$REPO_DIR/wallpapers/city-girl-sunset.png"

PHASE=""
DRY_RUN=false
NO_RELOAD=false
ROLLBACK_READY=false
STAGE_DIR=""
BACKUP_DIR=""
PYTHON_BIN=""

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
log()  { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
err()  { printf 'ERROR: %s\n' "$*" >&2; }

die() {
    err "$*"
    exit 1
}

usage() {
    cat <<'EOF'
Usage: ./apply-dots.sh [options]

Options:
  --phase <personal|repo-default>  Force an appearance phase for this run.
  --dry-run                         Validate and stage only; change nothing.
  --no-reload                       Deploy; do not reload the running session.
  -h, --help                        Show this help.

The active phase is stored in:
  ~/.local/state/niri-dots/phase

If no stored phase exists, "personal" is used. Re-running the script does not
reset your phase. Backups are stored under:
  ~/.local/state/niri-dots/backups/
EOF
}

# ---------------------------------------------------------------------------
# Phase handling
# ---------------------------------------------------------------------------
normalize_phase() {
    case "$1" in
        personal|phase2|2)      printf 'personal\n' ;;
        repo-default|repo|default|phase1|1) printf 'repo-default\n' ;;
        *) die "unknown phase '$1' (use personal or repo-default)" ;;
    esac
}

phase_file() {
    case "$1" in
        personal)     printf '%s\n' "$REPO_DIR/niri/.config/niri/cfg/rules-personal.kdl" ;;
        repo-default) printf '%s\n' "$REPO_DIR/niri/.config/niri/cfg/rules-repo-default.kdl" ;;
        *) die "internal error: unknown phase '$1'" ;;
    esac
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --phase)
            [ "$#" -ge 2 ] || die "--phase requires an argument"
            PHASE="$2"
            shift 2
            ;;
        --phase=*)
            PHASE="${1#--phase=}"
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --no-reload)
            NO_RELOAD=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "unknown argument '$1' (try --help)"
            ;;
    esac
done

if [ -n "$PHASE" ]; then
    PHASE="$(normalize_phase "$PHASE")"
elif [ -f "$PHASE_MARKER" ]; then
    STORED_PHASE="$(tr -d '[:space:]' < "$PHASE_MARKER" || true)"
    if [ -n "$STORED_PHASE" ]; then
        PHASE="$(normalize_phase "$STORED_PHASE")"
    else
        PHASE="$DEFAULT_PHASE"
    fi
else
    PHASE="$DEFAULT_PHASE"
fi
PHASE_FILE="$(phase_file "$PHASE")"

log "=========================================================="
log "  Deploying mydotfiles (Niri 26.04 + Noctalia v5)"
log "=========================================================="
log "Repository source: $REPO_DIR"
log "Active phase:      $PHASE"
log "Mode:              $([ "$DRY_RUN" = true ] && echo 'dry run (no changes)' || echo 'deploy')"
log ""

# ---------------------------------------------------------------------------
# Preflight: required files and commands are checked before any backup/write
# ---------------------------------------------------------------------------
log "[1/8] Preflight checks..."

REQUIRED_FILES=(
    "niri/.config/niri/config.kdl"
    "niri/.config/niri/cfg/animation.kdl"
    "niri/.config/niri/cfg/autostart.kdl"
    "niri/.config/niri/cfg/display.kdl"
    "niri/.config/niri/cfg/input.kdl"
    "niri/.config/niri/cfg/keybinds.kdl"
    "niri/.config/niri/cfg/layout.kdl"
    "niri/.config/niri/cfg/misc.kdl"
    "niri/.config/niri/cfg/rules.kdl"
    "niri/.config/niri/cfg/rules-personal.kdl"
    "niri/.config/niri/cfg/rules-repo-default.kdl"
    "noctalia/.config/noctalia/config.toml"
    "kitty/.config/kitty/kitty.conf"
    "kitty/.config/kitty/themes/noctalia.conf"
    "fish/.config/fish/config.fish"
    "fish/.config/fish/conf.d/uv.env.fish"
    "fastfetch/.config/fastfetch/config.jsonc"
    "scripts/noctalia-state.py"
    "wallpapers/city-girl-sunset.png"
)

for relative in "${REQUIRED_FILES[@]}"; do
    [ -f "$REPO_DIR/$relative" ] || die "missing required file: $relative"
done
[ -f "$PHASE_FILE" ] || die "missing phase file: $PHASE_FILE"

for command_name in niri noctalia python3 cp mv rm mkdir mktemp find grep date tr sed basename dirname; do
    command -v "$command_name" >/dev/null 2>&1 \
        || die "required command not found: $command_name"
done
PYTHON_BIN="$(command -v python3)"

# The display contract for this repository. Fail before deployment rather than
# installing a config that names the wrong panel or refresh rate.
grep -Eq '^[[:space:]]*output[[:space:]]+"eDP-1"' "$REPO_DIR/niri/.config/niri/config.kdl" \
    || die 'config.kdl does not define output "eDP-1"'
grep -Fq 'mode "1920x1080@144.003"' "$REPO_DIR/niri/.config/niri/config.kdl" \
    || die 'config.kdl is missing mode "1920x1080@144.003"'
if grep -Fq '1366x768' "$REPO_DIR/niri/.config/niri/config.kdl"; then
    die 'config.kdl still contains the old 1366x768 mode'
fi

# Verify the source uses exactly one top-level blur block in the active rules.
BLUR_COUNT="$(grep -Ec '^[[:space:]]*blur[[:space:]]*\{' "$REPO_DIR/niri/.config/niri/cfg/rules.kdl" || true)"
[ "$BLUR_COUNT" = "1" ] || die "active rules.kdl must contain exactly one top-level blur block (found $BLUR_COUNT)"

# Validate the Noctalia TOML before touching anything.
"$PYTHON_BIN" - "$REPO_DIR/noctalia/.config/noctalia/config.toml" <<'PYEOF'
import sys
import tomllib

path = sys.argv[1]
with open(path, "rb") as handle:
    tomllib.load(handle)
PYEOF

[ "$DRY_RUN" = true ] || log "  Required files and commands: OK"

# ---------------------------------------------------------------------------
# Stage the exact configuration that will be deployed
# ---------------------------------------------------------------------------
log ""
log "[2/8] Staging configuration in a temporary directory..."
STAGE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mydotfiles-stage.XXXXXX")"
cleanup() {
    if [ -n "${STAGE_DIR:-}" ] && [ -d "$STAGE_DIR" ]; then
        rm -rf -- "$STAGE_DIR"
    fi
}
trap cleanup EXIT

mkdir -p "$STAGE_DIR/niri" "$STAGE_DIR/noctalia" "$STAGE_DIR/kitty" "$STAGE_DIR/fastfetch" "$STAGE_DIR/fish"
cp -a -- "$REPO_DIR/niri/.config/niri/." "$STAGE_DIR/niri/"
cp -a -- "$REPO_DIR/noctalia/.config/noctalia/." "$STAGE_DIR/noctalia/"
cp -a -- "$REPO_DIR/kitty/.config/kitty/." "$STAGE_DIR/kitty/"
cp -a -- "$REPO_DIR/fastfetch/.config/fastfetch/." "$STAGE_DIR/fastfetch/"
mkdir -p "$STAGE_DIR/fish/conf.d"
cp -a -- "$REPO_DIR/fish/.config/fish/config.fish" "$STAGE_DIR/fish/config.fish"
cp -a -- "$REPO_DIR/fish/.config/fish/conf.d/uv.env.fish" "$STAGE_DIR/fish/conf.d/uv.env.fish"

# The active phase is a whole-file replacement. This guarantees that there is
# exactly one blur block and no leftover keys from the other phase.
cp -a -- "$PHASE_FILE" "$STAGE_DIR/niri/cfg/rules.kdl"

log "  Running: niri validate --config <staged>/niri/config.kdl"
if ! niri validate --config "$STAGE_DIR/niri/config.kdl"; then
    die "staged Niri configuration failed validation; nothing was deployed"
fi
log "  [OK] Niri configuration is valid"

log "  Running: noctalia config validate <staged>/noctalia"
if ! noctalia config validate "$STAGE_DIR/noctalia"; then
    die "staged Noctalia configuration failed validation; nothing was deployed"
fi
log "  [OK] Noctalia configuration is valid"

# Plan the Noctalia state change (read-only). If the state file is malformed or
# the helper would fail, stop before backup/deployment.
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/noctalia"
STATE_FILE="$STATE_DIR/settings.toml"
STATE_PLAN="$STAGE_DIR/noctalia-state-plan.txt"
if [ -f "$STATE_FILE" ]; then
    if ! "$PYTHON_BIN" "$REPO_DIR/scripts/noctalia-state.py" \
        --settings "$STATE_FILE" \
        --wallpaper "$PREFERRED_WALLPAPER" \
        --blur 0.80 --tint 0.45 --dry-run > "$STATE_PLAN"; then
        die "Noctalia state preflight failed; nothing was deployed"
    fi
    sed 's/^/  /' "$STATE_PLAN"
else
    log "  No Noctalia settings.toml yet - config.toml defaults will apply"
    : > "$STATE_PLAN"
fi

if [ "$DRY_RUN" = true ]; then
    log ""
    log "Dry run complete: staged files validated, no live files changed."
    log "Backup would be written under: $BACKUP_ROOT/"
    exit 0
fi

# ---------------------------------------------------------------------------
# Backup: complete, unique, and verified before deployment
# ---------------------------------------------------------------------------
log ""
log "[3/8] Creating backup..."
mkdir -p "$BACKUP_ROOT"
chmod 700 "$BACKUP_ROOT" 2>/dev/null || true
BACKUP_DIR="$(mktemp -d "$BACKUP_ROOT/apply-$(date +%Y%m%d-%H%M%S).XXXXXX")"
chmod 700 "$BACKUP_DIR" 2>/dev/null || true
mkdir -p "$BACKUP_DIR/config" "$BACKUP_DIR/noctalia-state" "$BACKUP_DIR/rollback"

backup_path() {
    local source_path="$1"
    local relative_path="$2"
    local dereference="${3:-false}"

    if [ -e "$source_path" ] || [ -L "$source_path" ]; then
        mkdir -p -- "$(dirname -- "$BACKUP_DIR/$relative_path")"
        if [ "$dereference" = true ]; then
            cp -aL -- "$source_path" "$BACKUP_DIR/$relative_path" \
                || die "backup failed for $source_path"
        else
            cp -a -- "$source_path" "$BACKUP_DIR/$relative_path" \
                || die "backup failed for $source_path"
        fi
    fi
}

for config_name in niri noctalia kitty fish fastfetch; do
    source_dir="$HOME/.config/$config_name"
    if [ -d "$source_dir" ]; then
        mkdir -p -- "$BACKUP_DIR/config/$config_name"
        # The trailing "/." follows a top-level symlink (common with dotfile
        # managers) while "cp -a" still preserves symlinks inside the tree.
        cp -a -- "$source_dir/." "$BACKUP_DIR/config/$config_name/" \
            || die "backup failed for $source_dir"
    elif [ -e "$source_dir" ] || [ -L "$source_dir" ]; then
        backup_path "$source_dir" "config/$config_name"
    fi
done
backup_path "$STATE_FILE" "noctalia-state/settings.toml" true
backup_path "$STATE_DIR/state.toml" "noctalia-state/state.toml" true

# Verify that every existing target really made it into the backup.
for config_name in niri noctalia kitty fish fastfetch; do
    if [ -e "$HOME/.config/$config_name" ]; then
        [ -e "$BACKUP_DIR/config/$config_name" ] \
            || die "backup verification failed for ~/.config/$config_name"
    fi
done
if [ -f "$STATE_FILE" ]; then
    [ -f "$BACKUP_DIR/noctalia-state/settings.toml" ] \
        || die "backup verification failed for Noctalia settings.toml"
fi

log "  Backup verified: $BACKUP_DIR"
ROLLBACK_READY=true

# ---------------------------------------------------------------------------
# Rollback and deployment primitives
# ---------------------------------------------------------------------------
TXN_NEW="$BACKUP_DIR/rollback/new-files.txt"
TXN_TOUCHED="$BACKUP_DIR/rollback/touched-files.txt"
: > "$TXN_NEW"
: > "$TXN_TOUCHED"

rollback() {
    [ "$ROLLBACK_READY" = true ] || return 0

    err "Rolling back the failed deployment..."
    set +e

    # Restore files that existed before deployment. New files are removed.
    while IFS=$'\t' read -r backup_relative destination; do
        [ -n "$destination" ] || continue
        if [ -n "$backup_relative" ] && [ -e "$BACKUP_DIR/$backup_relative" ]; then
            mkdir -p -- "$(dirname -- "$destination")"
            cp -a -- "$BACKUP_DIR/$backup_relative" "$destination" \
                && log "  restored $destination" \
                || err "could not restore $destination"
        fi
    done < "$TXN_TOUCHED"

    while IFS= read -r destination; do
        [ -n "$destination" ] || continue
        rm -f -- "$destination" && log "  removed new file $destination"
    done < "$TXN_NEW"

    if [ -f "$BACKUP_DIR/noctalia-state/settings.toml" ]; then
        cp -aL -- "$BACKUP_DIR/noctalia-state/settings.toml" "$STATE_FILE" \
            && log "  restored $STATE_FILE" \
            || err "could not restore $STATE_FILE"
    fi

    # Ask the running session to reload the restored files. Failures here are
    # reported but cannot make the rollback worse.
    if niri msg version >/dev/null 2>&1; then
        niri msg action load-config-file >/dev/null 2>&1 \
            || err "Niri did not reload the restored configuration; log out or reload manually"
    fi
    if noctalia msg status >/dev/null 2>&1; then
        noctalia msg config-reload >/dev/null 2>&1 \
            || err "Noctalia did not reload the restored configuration; restart it manually"
    fi

    err "Rollback finished. Original files are in: $BACKUP_DIR"
    set -e
}

fail() {
    err "$*"
    rollback
    exit 1
}

deploy_file() {
    local source_file="$1"
    local destination="$2"
    local backup_relative="$3"

    mkdir -p -- "$(dirname -- "$destination")"
    if [ -e "$destination" ] || [ -L "$destination" ]; then
        printf '%s\t%s\n' "$backup_relative" "$destination" >> "$TXN_TOUCHED"
    else
        printf '%s\n' "$destination" >> "$TXN_NEW"
    fi
    cp -a -- "$source_file" "$destination" \
        || fail "could not deploy $destination"
}

deploy_tree() {
    local source_dir="$1"
    local destination_dir="$2"
    local backup_name="$3"
    local file_list="$BACKUP_DIR/rollback/files.txt"

    find "$source_dir" \( -type f -o -type l \) -print0 > "$file_list" \
        || fail "could not enumerate $source_dir"
    while IFS= read -r -d '' source_file; do
        local relative="${source_file#"$source_dir"/}"
        deploy_file "$source_file" "$destination_dir/$relative" "config/$backup_name/$relative"
    done < "$file_list"
}

# ---------------------------------------------------------------------------
# Deploy (merge repo files into the target; do not delete unrelated files)
# ---------------------------------------------------------------------------
log ""
log "[4/8] Deploying configuration files..."

deploy_tree "$STAGE_DIR/niri" "$HOME/.config/niri" "niri"
deploy_tree "$STAGE_DIR/noctalia" "$HOME/.config/noctalia" "noctalia"
deploy_tree "$STAGE_DIR/kitty" "$HOME/.config/kitty" "kitty"
deploy_tree "$STAGE_DIR/fastfetch" "$HOME/.config/fastfetch" "fastfetch"

mkdir -p "$HOME/.config/fish/conf.d"
deploy_file "$STAGE_DIR/fish/config.fish" "$HOME/.config/fish/config.fish" "config/fish/config.fish"
deploy_file "$STAGE_DIR/fish/conf.d/uv.env.fish" "$HOME/.config/fish/conf.d/uv.env.fish" "config/fish/conf.d/uv.env.fish"
log "  Fish: config.fish + conf.d/uv.env.fish (fish_variables left untouched)"

# Remove a stale, literally backslash-suffixed filename from an old typo, but
# back it up first. This is the only deliberate deletion in the script.
STRAY_RULES="$HOME/.config/niri/cfg/rules.kdl\\"
if [ -e "$STRAY_RULES" ]; then
    backup_path "$STRAY_RULES" "config/niri/cfg/rules.kdl-stray"
    printf 'config/niri/cfg/rules.kdl-stray\t%s\n' "$STRAY_RULES" >> "$TXN_TOUCHED"
    rm -f -- "$STRAY_RULES"
    log "  Removed stray file: $STRAY_RULES (backed up)"
fi

# Wallpapers: never overwrite a same-named personal file. New files are
# recorded so rollback can remove them if deployment later fails.
log ""
log "[5/8] Installing missing wallpapers..."
mkdir -p "$HOME/Pictures/Wallpapers/niri-noctalia-dots"
while IFS= read -r -d '' wallpaper; do
    name="$(basename -- "$wallpaper")"
    destination="$HOME/Pictures/Wallpapers/niri-noctalia-dots/$name"
    if [ ! -e "$destination" ]; then
        cp -a -- "$wallpaper" "$destination" || fail "could not install wallpaper $name"
        printf '%s\n' "$destination" >> "$TXN_NEW"
        log "  installed $name"
    fi
done < <(find "$REPO_DIR/wallpapers" -maxdepth 1 -type f -print0)

[ -f "$PREFERRED_WALLPAPER" ] || fail "preferred wallpaper is missing: $PREFERRED_WALLPAPER"

# ---------------------------------------------------------------------------
# Noctalia state: selective migration only
# ---------------------------------------------------------------------------
log ""
log "[6/8] Reconciling Noctalia lock-screen state..."
if [ -f "$STATE_FILE" ]; then
    if ! "$PYTHON_BIN" "$REPO_DIR/scripts/noctalia-state.py" \
        --settings "$STATE_FILE" \
        --wallpaper "$PREFERRED_WALLPAPER" \
        --blur 0.80 --tint 0.45; then
        fail "Noctalia state migration failed"
    fi
else
    log "  No state file to migrate"
fi

# Re-validate the live files after deployment. This catches a copy problem or
# an unexpected merge with an existing file.
log ""
log "[7/8] Re-validating deployed configuration..."
if ! niri validate; then
    fail "deployed Niri configuration failed validation"
fi
log "  [OK] Niri configuration is valid"
if ! noctalia config validate; then
    fail "deployed Noctalia configuration failed validation"
fi
log "  [OK] Noctalia configuration is valid"

# ---------------------------------------------------------------------------
# Reload: only report success when the command actually succeeded
# ---------------------------------------------------------------------------
log ""
log "[8/8] Reloading live desktop..."
LIVE_OK=true
NIRI_STATUS="not attempted"
NOCTALIA_STATUS="not attempted"

if [ "$NO_RELOAD" = true ]; then
    NIRI_STATUS="skipped (--no-reload)"
    NOCTALIA_STATUS="skipped (--no-reload)"
    log "  --no-reload: configuration applies on next login"
elif niri msg version >/dev/null 2>&1; then
    if reload_output="$(niri msg action load-config-file 2>&1)"; then
        NIRI_STATUS="reloaded"
        log "  [OK] Niri reloaded with: niri msg action load-config-file"
        [ -z "$reload_output" ] || log "       $reload_output"
    else
        fail "Niri reload failed: ${reload_output:-niri msg action load-config-file returned non-zero}"
    fi
else
    NIRI_STATUS="not running - applies next login"
    log "  Niri is not running in this session; it will load the config next login"
fi

if [ "$NO_RELOAD" = true ]; then
    :
elif noctalia msg status >/dev/null 2>&1; then
    if reload_output="$(noctalia msg config-reload 2>&1)"; then
        NOCTALIA_STATUS="config reloaded"
        log "  [OK] Noctalia config reloaded"
        [ -z "$reload_output" ] || log "       $reload_output"
    else
        fail "Noctalia config reload failed: ${reload_output:-noctalia msg config-reload returned non-zero}"
    fi

    if [ -f "$PREFERRED_WALLPAPER" ]; then
        if wallpaper_output="$(noctalia msg wallpaper-set "$PREFERRED_WALLPAPER" 2>&1)"; then
            log "  [OK] Wallpaper set to city-girl-sunset.png"
            [ -z "$wallpaper_output" ] || log "       $wallpaper_output"
        else
            LIVE_OK=false
            err "Noctalia wallpaper-set failed: ${wallpaper_output:-unknown error}"
            NOCTALIA_STATUS="$NOCTALIA_STATUS; wallpaper FAILED"
        fi
    fi

    if scheme_output="$(noctalia msg color-scheme-set wallpaper m3-content 2>&1)"; then
        log "  [OK] Color scheme set to wallpaper / m3-content"
        [ -z "$scheme_output" ] || log "       $scheme_output"
    else
        LIVE_OK=false
        err "Noctalia color-scheme-set failed: ${scheme_output:-unknown error}"
        NOCTALIA_STATUS="$NOCTALIA_STATUS; color scheme FAILED"
    fi
else
    NOCTALIA_STATUS="not running - applies next login"
    log "  Noctalia is not running in this session; it will load the config next login"
fi

# Record the phase only after the deployment and any requested reload succeeded.
mkdir -p "$STATE_ROOT"
printf '%s\n' "$PHASE" > "$PHASE_MARKER"

log ""
log "=========================================================="
if [ "$LIVE_OK" = true ]; then
    log "  Deployment complete"
else
    log "  Deployment completed with live-apply errors"
fi
log "=========================================================="
log "Active phase:      $PHASE"
log "Niri reload:       $NIRI_STATUS"
log "Noctalia reload:   $NOCTALIA_STATUS"
log "Backup:            $BACKUP_DIR"
log "Phase marker:      $PHASE_MARKER"
log ""
log "Next checks:"
log "  niri msg outputs                  # confirm eDP-1 @ 1920x1080 144.003 Hz"
log "  niri msg windows                  # confirm real app-ids"
log "  ./toggle-phase.sh status          # confirm the active phase"
log "  noctalia msg session lock         # test the lock screen (locks the session)"
log "=========================================================="

if [ "$LIVE_OK" != true ]; then
    exit 1
fi
exit 0
