#!/usr/bin/env python3
"""
verify_dots.py - Automated Test and Verification Suite
Tests all configuration files in niri-noctalia-dots for syntax, schema compatibility,
hardware adaptations for ASUS TUF Gaming F15, and Noctalia v5.2.1 requirements.
"""

import os
import glob
import json
import re
import tomllib
import sys

results = []

def test(name, condition, details=""):
    results.append((name, bool(condition), details))

print("==========================================================")
print("  Running Full Dotfiles Verification & Test Suite")
print("==========================================================")
print()

# ----------------------------------------------------------------------
# 1. Niri Configuration Suite
# ----------------------------------------------------------------------
cfg_dir = os.path.join("niri", ".config", "niri")

# 1.1 config.kdl
with open(os.path.join(cfg_dir, "config.kdl"), "r", encoding="utf-8") as f:
    config_kdl = f.read()

test("Niri config.kdl includes all 8 cfg modules",
     all(f'./cfg/{m}.kdl' in config_kdl for m in [
         "animation", "autostart", "keybinds", "input", "display", "layout", "rules", "misc"
     ]))

test("Niri output eDP-1 set to 1920x1080@144.003",
     "1920x1080@144.003" in config_kdl)

test("Niri output eDP-1 scale 1.0, transform normal, position x=0 y=0",
     'scale 1.0' in config_kdl and 'transform "normal"' in config_kdl and 'position x=0 y=0' in config_kdl)

test("Old 1366x768 resolution eliminated from config.kdl",
     "1366x768" not in config_kdl)

test("Duplicate prefer-no-csd eliminated from config.kdl",
     config_kdl.count("prefer-no-csd") == 0)

# 1.2 cfg/misc.kdl
with open(os.path.join(cfg_dir, "cfg", "misc.kdl"), "r", encoding="utf-8") as f:
    misc_kdl = f.read()

test("misc.kdl has prefer-no-csd exactly once",
     misc_kdl.count("prefer-no-csd") == 1)

test("misc.kdl conflicting duplicate blur block removed",
     "blur {" not in misc_kdl)

test("misc.kdl has Wayland environment variables and Noctalia activation debug",
     'XDG_CURRENT_DESKTOP "niri"' in misc_kdl and 'honor-xdg-activation-with-invalid-serial' in misc_kdl)

# 1.3 cfg/input.kdl
with open(os.path.join(cfg_dir, "cfg", "input.kdl"), "r", encoding="utf-8") as f:
    input_kdl = f.read()

test("input.kdl trackpoint removed (ASUS TUF has no TrackPoint)",
     "trackpoint" not in input_kdl)

test("input.kdl touchpad tap & natural-scroll configured",
     "tap" in input_kdl and "natural-scroll" in input_kdl)

# 1.4 cfg/rules.kdl (Phase 1 active)
with open(os.path.join(cfg_dir, "cfg", "rules.kdl"), "r", encoding="utf-8") as f:
    rules_kdl = f.read()

test("rules.kdl has Phase 1 blur (passes 6, offset 4.0, noise 0.03, saturation 1.2)",
     "passes 6" in rules_kdl and "offset 4.0" in rules_kdl and "noise 0.03" in rules_kdl and "saturation 1.2" in rules_kdl)

test("rules.kdl has Phase 1 global opacity 0.90",
     "opacity 0.90" in rules_kdl)

test("rules.kdl Noctalia settings window set to floating (1080x850)",
     'match app-id="dev.noctalia.Noctalia"' in rules_kdl and "open-floating true" in rules_kdl and "fixed 1080" in rules_kdl)

test("rules.kdl has noctalia-window-switcher blur layer-rule",
     'match namespace="noctalia-window-switcher"' in rules_kdl)

test("rules.kdl has application rules for Firefox, Discord, Nautilus, mpv/vlc",
     'match app-id="firefox"' in rules_kdl and 'match app-id="discord"' in rules_kdl and
     'match app-id="org.gnome.Nautilus"' in rules_kdl and 'match app-id="mpv"' in rules_kdl)

# 1.5 cfg/rules-personal.kdl (Phase 2 available)
with open(os.path.join(cfg_dir, "cfg", "rules-personal.kdl"), "r", encoding="utf-8") as f:
    rules_personal = f.read()

test("rules-personal.kdl preserved for Phase 2 (opacity 0.75, passes 2, offset 3.0)",
     "opacity 0.75" in rules_personal and "passes 2" in rules_personal and "offset 3.0" in rules_personal)

# 1.6 cfg/keybinds.kdl
with open(os.path.join(cfg_dir, "cfg", "keybinds.kdl"), "r", encoding="utf-8") as f:
    keybinds_kdl = f.read()

test("keybinds.kdl terminal title corrected to Kitty",
     'Open Terminal: Kitty' in keybinds_kdl)

test("keybinds.kdl has laptop lid switch-events (lock-and-suspend)",
     "switch-events" in keybinds_kdl and "lid-close" in keybinds_kdl and "lock-and-suspend" in keybinds_kdl)

# 1.7 All KDL files brace balancing
kdl_files = glob.glob(os.path.join(cfg_dir, "**", "*.kdl"), recursive=True)
for kpath in kdl_files:
    with open(kpath, "r", encoding="utf-8") as f:
        c = f.read()
    bname = os.path.relpath(kpath, cfg_dir)
    test(f"KDL syntax balance in {bname}", c.count("{") == c.count("}"))

# ----------------------------------------------------------------------
# 2. Noctalia Configuration Suite
# ----------------------------------------------------------------------
toml_path = os.path.join("noctalia", ".config", "noctalia", "config.toml")
with open(toml_path, "rb") as f:
    noctalia_toml = tomllib.load(f)

test("Noctalia config.toml parsed cleanly as valid TOML", bool(noctalia_toml))

lockscreen = noctalia_toml.get("lockscreen", {})
test("Lockscreen enabled with blur 0.5 & tint 0.3",
     lockscreen.get("enabled") is True and lockscreen.get("blur_intensity") == 0.5 and lockscreen.get("tint_intensity") == 0.3)

test("Lock Before Suspend enabled", lockscreen.get("lock_before_suspend") is True)

lockscreen_widgets = noctalia_toml.get("lockscreen_widgets", {})
widget_order = lockscreen_widgets.get("widget_order", [])

test("Widget order contains only clock and login_box (NO calendar)",
     widget_order == ["lockscreen-clock@eDP-1", "lockscreen-login-box@eDP-1"])

clock_widget = lockscreen_widgets.get("widget", {}).get("lockscreen-clock@eDP-1", {})
test("Clock coordinates centered for 1080p (cx=960.0, cy=350.0)",
     clock_widget.get("cx") == 960.0 and clock_widget.get("cy") == 350.0)

clock_settings = clock_widget.get("settings", {})
test("Clock format token is {:%H\\n%M\\n%A\\n%-d %b} (hours, minutes, weekday, date)",
     clock_settings.get("format") == r"{:%H\n%M\n%A\n%-d %b}")

test("Unsupported clock keys (use_primary_color, font_size) removed",
     "use_primary_color" not in clock_settings and "font_size" not in clock_settings)

test("Clock widget center_text, shadow, color configured",
     clock_settings.get("center_text") is True and clock_settings.get("shadow") is True and clock_settings.get("color") == "primary")

login_widget = lockscreen_widgets.get("widget", {}).get("lockscreen-login-box@eDP-1", {})
test("Login box coordinates centered for 1080p (cx=960.0, cy=700.0)",
     login_widget.get("cx") == 960.0 and login_widget.get("cy") == 700.0)

login_settings = login_widget.get("settings", {})
test("Login box has show_login_button = true for warm checkmark submit button",
     login_settings.get("show_login_button") is True)

# ----------------------------------------------------------------------
# 3. Kitty Configuration Suite
# ----------------------------------------------------------------------
kitty_path = os.path.join("kitty", ".config", "kitty", "kitty.conf")
with open(kitty_path, "r", encoding="utf-8") as f:
    kitty_conf = f.read()

test("kitty.conf corrupted duplicate include line removed",
     "include themes/noctalia.confinclude themes/noctalia.conf" not in kitty_conf)

test("kitty.conf cleanly includes themes/noctalia.conf",
     kitty_conf.count("include themes/noctalia.conf") == 1)

test("kitty.conf has JetBrainsMono Nerd Font enabled",
     "font_family JetBrainsMono Nerd Font" in kitty_conf and "# font_family" not in kitty_conf)

test("kitty themes/noctalia.conf theme file exists and is populated",
     os.path.isfile(os.path.join("kitty", ".config", "kitty", "themes", "noctalia.conf")) and
     os.path.getsize(os.path.join("kitty", ".config", "kitty", "themes", "noctalia.conf")) > 200)

# ----------------------------------------------------------------------
# 4. Fish Configuration Suite
# ----------------------------------------------------------------------
fish_cfg_path = os.path.join("fish", ".config", "fish", "config.fish")
with open(fish_cfg_path, "r", encoding="utf-8") as f:
    config_fish = f.read()

test("config.fish adds ~/.local/bin to path",
     "fish_add_path" in config_fish and "$HOME/.local/bin" in config_fish)

test("config.fish initializes Starship prompt",
     "starship init fish" in config_fish)

fish_var_path = os.path.join("fish", ".config", "fish", "fish_variables")
with open(fish_var_path, "r", encoding="utf-8") as f:
    fish_vars = f.read()

test("fish_variables does not contain foreign username screenyshadow",
     "screenyshadow" not in fish_vars)

# ----------------------------------------------------------------------
# 5. Fastfetch Configuration Suite
# ----------------------------------------------------------------------
ff_path = os.path.join("fastfetch", ".config", "fastfetch", "config.jsonc")
with open(ff_path, "r", encoding="utf-8") as f:
    ff_lines = [l for l in f if not l.strip().startswith("//")]
    ff_json = json.loads("".join(ff_lines))

test("Fastfetch config.jsonc parsed cleanly as valid JSON", bool(ff_json))

colors = ff_json.get("display", {}).get("color", {})
test("Fastfetch color escape strings have no trailing colons",
     colors.get("keys") == "38;2;255;255;255" and colors.get("output") == "38;2;165;165;165")

# ----------------------------------------------------------------------
# 6. Wallpapers Suite
# ----------------------------------------------------------------------
wp_dir = "wallpapers"
wallpapers = [
    "12.png", "18.png", "30.png", "blue-girl.png", "central.png",
    "city-girl-sunset.png", "city-girl.png", "cyan-girl.png", "wallhaven-8g5p52_3840x2160.png"
]
for wp in wallpapers:
    wpp = os.path.join(wp_dir, wp)
    test(f"Wallpaper {wp} exists and is valid", os.path.isfile(wpp) and os.path.getsize(wpp) > 50000)

# ----------------------------------------------------------------------
# 7. Deployment & Toggle Scripts Suite
# ----------------------------------------------------------------------
test("apply-dots.sh exists and is non-empty",
     os.path.isfile("apply-dots.sh") and os.path.getsize("apply-dots.sh") > 1000)

test("toggle-phase.sh exists and is non-empty",
     os.path.isfile("toggle-phase.sh") and os.path.getsize("toggle-phase.sh") > 500)

# ----------------------------------------------------------------------
# Summary Report
# ----------------------------------------------------------------------
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
failed = total - passed

print(f"Total Tests Run: {total}")
print(f"Passed:         {passed}")
print(f"Failed:         {failed}")
print()

for name, ok, details in results:
    badge = "[PASS]" if ok else "[FAIL]"
    print(f"  {badge} {name}")
    if not ok and details:
        print(f"         Detail: {details}")

print()
if failed == 0:
    print("ALL TESTS PASSED! All configuration files are verified and ready for deployment.")
    sys.exit(0)
else:
    print(f"WARNING: {failed} tests failed.")
    sys.exit(1)
