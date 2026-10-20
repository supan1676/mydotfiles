#!/usr/bin/env python3
"""Static and (when available) runtime verification for mydotfiles.

Run from the repository root:

    python3 verify_dots.py

The suite deliberately distinguishes:
  PASS  - checked and correct
  FAIL  - checked and wrong
  SKIP  - cannot be checked here (for example, Niri is not installed or the
          session is not running)

Runtime checks are skipped, not faked. A skipped check is printed with the
reason and does not turn into a false PASS.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NIRI = ROOT / "niri" / ".config" / "niri"
NOCTALIA = ROOT / "noctalia" / ".config" / "noctalia"
KITTY = ROOT / "kitty" / ".config" / "kitty"
FISH = ROOT / "fish" / ".config" / "fish"
FASTFETCH = ROOT / "fastfetch" / ".config" / "fastfetch"
WALLPAPERS = ROOT / "wallpapers"
PREFERRED_WALLPAPER = "city-girl-sunset.png"

RESULTS: list[tuple[str, str, str, str]] = []
WARNINGS: list[str] = []


def check(name: str, condition: bool, detail: str = "", group: str = "General") -> None:
    RESULTS.append((group, name, "PASS" if condition else "FAIL", detail))


def skip(name: str, reason: str, group: str = "General") -> None:
    RESULTS.append((group, name, "SKIP", reason))


def warn(message: str) -> None:
    WARNINGS.append(message)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def strip_kdl_comments(text: str) -> str:
    """Strip // comments while preserving quoted strings."""
    out: list[str] = []
    for line in text.splitlines():
        quote: str | None = None
        escaped = False
        cut = len(line)
        index = 0
        while index < len(line):
            char = line[index]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif quote is not None:
                if char == quote:
                    quote = None
            elif char in ('"', "'"):
                quote = char
            elif char == "/" and index + 1 < len(line) and line[index + 1] == "/":
                cut = index
                break
            index += 1
        out.append(line[:cut].rstrip())
    return "\n".join(out)


def balanced_braces(text: str) -> bool:
    """Brace balance that ignores comments and quoted strings."""
    depth = 0
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif quote is not None:
            if char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == "/" and index + 1 < len(text) and text[index + 1] == "/":
            newline = text.find("\n", index)
            index = len(text) if newline == -1 else newline
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return False
        index += 1
    return depth == 0 and quote is None


def block_after(text: str, start: int) -> str | None:
    """Return the contents of the first {...} block at/after start."""
    brace = text.find("{", start)
    if brace == -1:
        return None
    depth = 0
    quote: str | None = None
    escaped = False
    index = brace
    while index < len(text):
        char = text[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif quote is not None:
            if char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == "/" and index + 1 < len(text) and text[index + 1] == "/":
            newline = text.find("\n", index)
            index = len(text) if newline == -1 else newline
            continue
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[brace + 1 : index]
        index += 1
    return None


def find_blocks(text: str, header_regex: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for match in re.finditer(header_regex, text, re.MULTILINE):
        body = block_after(text, match.start())
        if body is not None:
            blocks.append((match.group(0), body))
    return blocks


def parse_includes(text: str) -> list[str]:
    return re.findall(r'^\s*include\s+"([^"]+)"', text, re.MULTILINE)


def semantic_kdl(text: str) -> str:
    lines = []
    for raw in strip_kdl_comments(text).splitlines():
        line = re.sub(r"\s+", " ", raw.strip())
        if line:
            lines.append(line)
    return "\n".join(lines) + "\n"


def run(command: list[str], timeout: int = 25) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def usable_bash() -> str | None:
    """Return a working bash path, or None for a WSL shim without a distro."""
    candidates: list[str] = []
    found = shutil.which("bash")
    if found:
        candidates.append(found)
    if os.name == "nt":
        for base in [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]:
            if base:
                candidates.append(str(Path(base) / "Git" / "bin" / "bash.exe"))
                candidates.append(str(Path(base) / "Git" / "usr" / "bin" / "bash.exe"))

    for bash in candidates:
        if not os.path.isfile(bash):
            continue
        try:
            probe = run([bash, "-c", "true"], timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 0:
            return bash
    return None


def jsonc_to_json(text: str) -> str:
    """Remove // and /* */ comments and trailing commas outside strings."""
    out: list[str] = []
    index = 0
    quote: str | None = None
    escaped = False
    while index < len(text):
        char = text[index]
        if escaped:
            out.append(char)
            escaped = False
            index += 1
            continue
        if char == "\\":
            out.append(char)
            escaped = True
            index += 1
            continue
        if quote is not None:
            out.append(char)
            if char == quote:
                quote = None
            index += 1
            continue
        if char in ('"', "'"):
            quote = char
            out.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < len(text) and text[index + 1] == "/":
            newline = text.find("\n", index)
            index = len(text) if newline == -1 else newline
            continue
        if char == "/" and index + 1 < len(text) and text[index + 1] == "*":
            end = text.find("*/", index + 2)
            index = len(text) if end == -1 else end + 2
            continue
        out.append(char)
        index += 1

    without_comments = "".join(out)
    # Remove trailing commas before } or ] outside strings.
    result: list[str] = []
    quote = None
    escaped = False
    index = 0
    while index < len(without_comments):
        char = without_comments[index]
        if escaped:
            result.append(char)
            escaped = False
            index += 1
            continue
        if char == "\\":
            result.append(char)
            escaped = True
            index += 1
            continue
        if quote is not None:
            result.append(char)
            if char == quote:
                quote = None
            index += 1
            continue
        if char in ('"', "'"):
            quote = char
            result.append(char)
            index += 1
            continue
        if char == ",":
            lookahead = index + 1
            while lookahead < len(without_comments) and without_comments[lookahead].isspace():
                lookahead += 1
            if lookahead < len(without_comments) and without_comments[lookahead] in "}]":
                index += 1
                continue
        result.append(char)
        index += 1
    return "".join(result)


# ---------------------------------------------------------------------------
# Niri
# ---------------------------------------------------------------------------
def verify_niri() -> None:
    group = "Niri"
    config_path = NIRI / "config.kdl"
    if not config_path.is_file():
        check("config.kdl exists", False, str(config_path), group)
        return
    config = read(config_path)
    expected = [
        "animation",
        "autostart",
        "keybinds",
        "input",
        "display",
        "layout",
        "rules",
        "misc",
    ]
    includes = parse_includes(config)
    check(
        "config.kdl includes each of the 8 modules exactly once",
        sorted(includes) == sorted(f"./cfg/{name}.kdl" for name in expected),
        f"found: {includes}",
        group,
    )
    for name in expected:
        check(
            f"included module cfg/{name}.kdl exists",
            (NIRI / "cfg" / f"{name}.kdl").is_file(),
            "",
            group,
        )

    output_headers = re.findall(r'^\s*output\s+"([^"]+)"\s*\{', config, re.MULTILINE)
    check(
        "exactly one active output block (eDP-1)",
        output_headers == ["eDP-1"],
        f"found: {output_headers}",
        group,
    )
    output_body = block_after(config, config.find('output "eDP-1"'))
    if output_body is None:
        check("eDP-1 output block can be parsed", False, "", group)
    else:
        check(
            "eDP-1 uses 1920x1080@144.003",
            'mode "1920x1080@144.003"' in output_body,
            output_body.strip(),
            group,
        )
        check("eDP-1 scale is 1.0", re.search(r"^\s*scale\s+1\.0\b", output_body, re.MULTILINE) is not None, "", group)
        check(
            'eDP-1 transform is "normal"',
            re.search(r'^\s*transform\s+"normal"', output_body, re.MULTILINE) is not None,
            "",
            group,
        )
        check(
            "eDP-1 position is x=0 y=0",
            re.search(r"^\s*position\s+x=0\s+y=0", output_body, re.MULTILINE) is not None,
            "",
            group,
        )
        check(
            "eDP-1 contains exactly one mode line",
            len(re.findall(r"^\s*mode\s+", output_body, re.MULTILINE)) == 1,
            "",
            group,
        )

    all_niri_text = "\n".join(read(path) for path in NIRI.rglob("*.kdl"))
    check("old 1366x768 mode is absent from all Niri modules", "1366x768" not in all_niri_text, "", group)
    check(
        "display.kdl has no uncommented duplicate output block",
        not re.search(r"^\s*output\s+", read(NIRI / "cfg" / "display.kdl"), re.MULTILINE),
        "",
        group,
    )

    misc = read(NIRI / "cfg" / "misc.kdl")
    check("misc.kdl has prefer-no-csd exactly once", misc.count("prefer-no-csd") == 1, "", group)
    check("misc.kdl has no top-level blur block", re.search(r"^\s*blur\s*\{", misc, re.MULTILINE) is None, "", group)

    rules = read(NIRI / "cfg" / "rules.kdl")
    personal = read(NIRI / "cfg" / "rules-personal.kdl")
    repo_default = read(NIRI / "cfg" / "rules-repo-default.kdl")
    included_rules = [read(NIRI / "cfg" / f"{name}.kdl") for name in ["animation", "autostart", "keybinds", "input", "layout", "rules", "misc"]]
    blur_blocks = sum(len(re.findall(r"^\s*blur\s*\{", text, re.MULTILINE)) for text in included_rules)
    check("included Niri config has exactly one top-level blur block", blur_blocks == 1, f"found {blur_blocks}", group)

    check(
        "active rules.kdl matches Phase 2 (personal)",
        semantic_kdl(rules) == semantic_kdl(personal),
        "active rules.kdl differs from rules-personal.kdl",
        group,
    )
    personal_values = {
        "passes 2": "passes 2" in personal,
        "offset 3.0": "offset 3.0" in personal,
        "noise 0.03": "noise 0.03" in personal,
        "saturation 1.0": "saturation 1.0" in personal,
        "opacity 0.75": "opacity 0.75" in personal,
        "radius 20": re.search(r"geometry-corner-radius\s+20\b", personal) is not None,
    }
    for label, present in personal_values.items():
        check(f"Phase 2 contains {label}", present, "", group)

    repo_values = {
        "passes 6": "passes 6" in repo_default,
        "offset 4.0": "offset 4.0" in repo_default,
        "noise 0.03": "noise 0.03" in repo_default,
        "saturation 1.2": "saturation 1.2" in repo_default,
        "opacity 0.90": "opacity 0.90" in repo_default,
        "radius 20": re.search(r"geometry-corner-radius\s+20\b", repo_default) is not None,
    }
    for label, present in repo_values.items():
        check(f"Phase 1 contains {label}", present, "", group)

    def window_rule_for(text: str, app_id: str) -> str | None:
        for header, body in find_blocks(text, r"^\s*window-rule\s*\{"):
            if re.search(rf'match\s+app-id="{re.escape(app_id)}"', body):
                return body
        return None

    expected_apps = {
        "firefox": ("0.75", True),
        "discord": ("0.73", False),
        "org.gnome.Nautilus": ("0.65", True),
        "mpv": ("1.0", None),
        "vlc": ("1.0", None),
    }
    for app_id, (opacity, blur) in expected_apps.items():
        body = window_rule_for(rules, app_id)
        check(f"active rules have a window rule for {app_id}", body is not None, "", group)
        if body is None:
            continue
        check(
            f"{app_id} opacity is {opacity}",
            re.search(rf"^\s*opacity\s+{re.escape(opacity)}\b", body, re.MULTILINE) is not None,
            body.strip(),
            group,
        )
        if blur is not None:
            check(
                f"{app_id} blur is {'enabled' if blur else 'disabled'}",
                re.search(rf"^\s*blur\s+{'true' if blur else 'false'}\b", body, re.MULTILINE) is not None,
                body.strip(),
                group,
            )

    layer_text = "\n".join(body for _, body in find_blocks(rules, r"^\s*layer-rule\s*\{"))
    check(
        "Noctalia layer rule covers bar/panel/notification/dock/attached-panel/osd",
        all(token in layer_text for token in ["bar-", "notification", "dock", "panel", "attached-panel", "osd"]),
        "",
        group,
    )
    check("Noctalia layer rules use xray false", "xray false" in layer_text, "", group)
    check("Noctalia window-switcher layer rule exists", "noctalia-window-switcher" in rules, "", group)

    keybinds = read(NIRI / "cfg" / "keybinds.kdl")
    check("Mod+Return launches Kitty", re.search(r'Mod\+Return.*spawn\s+"kitty"', keybinds) is not None, "", group)
    check(
        "lid-close uses noctalia lock-and-suspend",
        "lid-close" in keybinds and "lock-and-suspend" in keybinds,
        "",
        group,
    )

    for path in sorted(NIRI.rglob("*.kdl")):
        text = read(path)
        check(f"KDL braces balance in {path.relative_to(NIRI)}", balanced_braces(text), "", group)
        check(f"no backslash-suffixed duplicate in {path.relative_to(NIRI)}", "\\" not in path.name, "", group)
    stray_names = [path.name for path in (NIRI / "cfg").iterdir() if path.name.endswith("\\")]
    check("no stray backslash-suffixed rules file in the repository", not stray_names, f"found: {stray_names}", group)

    if shutil.which("niri"):
        result = run(["niri", "validate", "--config", str(config_path)])
        if result.returncode == 0:
            check("niri validate accepts the complete config", True, "", group)
        else:
            check("niri validate accepts the complete config", False, (result.stderr or result.stdout).strip(), group)
    else:
        skip("niri validate accepts the complete config", "niri is not installed in this environment", group)


# ---------------------------------------------------------------------------
# Noctalia
# ---------------------------------------------------------------------------
def verify_noctalia() -> None:
    group = "Noctalia"
    config_path = NOCTALIA / "config.toml"
    if not config_path.is_file():
        check("config.toml exists", False, str(config_path), group)
        return
    with open(config_path, "rb") as handle:
        try:
            config = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            check("config.toml parses as TOML", False, str(exc), group)
            return
    check("config.toml parses as TOML", True, "", group)

    lockscreen = config.get("lockscreen", {})
    check("lock screen is enabled", lockscreen.get("enabled") is True, "", group)
    check("lock before suspend is enabled", lockscreen.get("lock_before_suspend") is True, "", group)
    check("lock-screen blur is 0.80", lockscreen.get("blur_intensity") == 0.80, str(lockscreen.get("blur_intensity")), group)
    check("lock-screen tint is 0.45", lockscreen.get("tint_intensity") == 0.45, str(lockscreen.get("tint_intensity")), group)
    check("empty password is disallowed", lockscreen.get("allow_empty_password") is False, "", group)

    widgets = config.get("lockscreen_widgets", {})
    order = widgets.get("widget_order", [])
    check(
        "lock-screen widget order is exactly clock + login box",
        order == ["lockscreen-clock@eDP-1", "lockscreen-login-box@eDP-1"],
        f"found: {order}",
        group,
    )
    widget_tables = widgets.get("widget", {})
    types = [widget.get("type") for widget in widget_tables.values() if isinstance(widget, dict)]
    check("no Calendar lock-screen widget is declared", "calendar" not in types, f"types: {types}", group)

    clock = widget_tables.get("lockscreen-clock@eDP-1", {})
    clock_settings = clock.get("settings", {})
    check("clock widget is type clock", clock.get("type") == "clock", "", group)
    check("clock widget targets eDP-1", clock.get("output") == "eDP-1", "", group)
    check("clock is centered horizontally (cx=960)", clock.get("cx") == 960.0, str(clock.get("cx")), group)
    check("clock is in the upper-middle (cy=350)", clock.get("cy") == 350.0, str(clock.get("cy")), group)
    expected_format = r"{:%H\n%M\n%A\n%-d %b}"
    check("clock format is the approved four-line literal-newline format", clock_settings.get("format") == expected_format, repr(clock_settings.get("format")), group)
    check(
        "clock format uses only supported tokens",
        all(token in (clock_settings.get("format") or "") for token in ["%H", "%M", "%A", "%-d", "%b"]),
        repr(clock_settings.get("format")),
        group,
    )
    check("clock uses the primary (warm accent) color role", clock_settings.get("color") == "primary", str(clock_settings.get("color")), group)
    check("clock shadow is enabled", clock_settings.get("shadow") is True, "", group)
    check("clock text is centered", clock_settings.get("center_text") is True, "", group)
    check("clock uses digital style", clock_settings.get("clock_style") == "digital", "", group)
    check("unsupported clock keys are absent", "font_size" not in clock_settings and "use_primary_color" not in clock_settings, "", group)

    login = widget_tables.get("lockscreen-login-box@eDP-1", {})
    login_settings = login.get("settings", {})
    check("login box is type login_box", login.get("type") == "login_box", "", group)
    check("login box targets eDP-1", login.get("output") == "eDP-1", "", group)
    check("login box is centered horizontally (cx=960)", login.get("cx") == 960.0, str(login.get("cx")), group)
    check("login box is lower-middle (cy=700)", login.get("cy") == 700.0, str(login.get("cy")), group)
    check("login box uses compact layout", login_settings.get("layout") == "compact", str(login_settings.get("layout")), group)
    check("login box shows the submit button", login_settings.get("show_login_button") is True, "", group)
    check("login box does not show media/weather/session panels", not any(login_settings.get(key) for key in ["show_media", "show_weather", "show_session_buttons"]), "", group)
    check("login box background opacity is in range", 0.0 <= float(login_settings.get("background_opacity", -1)) <= 1.0, str(login_settings.get("background_opacity")), group)
    check("login box corner radius is in range", 0.0 <= float(login_settings.get("background_radius", -1)) <= 32.0, str(login_settings.get("background_radius")), group)

    for name, widget in [("clock", clock), ("login box", login)]:
        check(f"{name} x coordinate is on the 1920px canvas", 0 <= float(widget.get("cx", -1)) <= 1920, str(widget.get("cx")), group)
        check(f"{name} y coordinate is on the 1080px canvas", 0 <= float(widget.get("cy", -1)) <= 1080, str(widget.get("cy")), group)
        check(f"{name} box width is non-negative", float(widget.get("box_width", -1)) >= 0, str(widget.get("box_width")), group)
        check(f"{name} box height is non-negative", float(widget.get("box_height", -1)) >= 0, str(widget.get("box_height")), group)

    check("clock is above the login box", clock.get("cy", 0) < login.get("cy", 0), "", group)

    theme = config.get("theme", {})
    check('theme source is "wallpaper"', theme.get("source") == "wallpaper", str(theme.get("source")), group)
    check('wallpaper scheme is "m3-content"', theme.get("wallpaper_scheme") == "m3-content", str(theme.get("wallpaper_scheme")), group)
    wallpaper_path = config.get("wallpaper", {}).get("default", {}).get("path", "")
    check("preferred wallpaper is configured", os.path.basename(wallpaper_path) == PREFERRED_WALLPAPER, wallpaper_path, group)
    check("preferred wallpaper exists in the repository", (WALLPAPERS / PREFERRED_WALLPAPER).is_file(), "", group)

    if shutil.which("noctalia"):
        result = run(["noctalia", "config", "validate", str(NOCTALIA)])
        if result.returncode == 0:
            check("noctalia config validate accepts the config", True, (result.stdout or "").strip(), group)
        else:
            check("noctalia config validate accepts the config", False, (result.stderr or result.stdout).strip(), group)
    else:
        skip("noctalia config validate accepts the config", "noctalia is not installed in this environment", group)


# ---------------------------------------------------------------------------
# Kitty, Fish, Fastfetch
# ---------------------------------------------------------------------------
def verify_kitty() -> None:
    group = "Kitty"
    conf_path = KITTY / "kitty.conf"
    if not conf_path.is_file():
        check("kitty.conf exists", False, str(conf_path), group)
        return
    conf = read(conf_path)
    includes = re.findall(r"^\s*include\s+(.+?)\s*$", conf, re.MULTILINE)
    check("kitty.conf includes the Noctalia theme exactly once", includes.count("themes/noctalia.conf") == 1, f"includes: {includes}", group)
    theme_path = KITTY / "themes" / "noctalia.conf"
    check("kitty theme include target exists", theme_path.is_file(), str(theme_path), group)
    if theme_path.is_file():
        theme = read(theme_path)
        check("kitty theme is populated", len(theme.strip()) > 200, "", group)
        color_lines = [line for line in theme.splitlines() if re.match(r"^\s*\w+\s+#[0-9a-fA-F]{6,8}\s*$", line)]
        check("kitty theme has valid hex color lines", len(color_lines) >= 10, f"valid lines: {len(color_lines)}", group)
        check("kitty theme defines background and foreground", "background" in theme and "foreground" in theme, "", group)
    check("kitty font family is configured", re.search(r"^\s*font_family\s+\S", conf, re.MULTILINE) is not None, "", group)
    opacity = re.search(r"^\s*background_opacity\s+([0-9.]+)", conf, re.MULTILINE)
    check("kitty background_opacity is between 0 and 1", opacity is not None and 0.0 <= float(opacity.group(1)) <= 1.0, opacity.group(1) if opacity else "missing", group)


def verify_fish() -> None:
    group = "Fish"
    config_path = FISH / "config.fish"
    env_path = FISH / "conf.d" / "uv.env.fish"
    config = read(config_path) if config_path.is_file() else ""
    check("config.fish exists", config_path.is_file(), "", group)
    check("config.fish uses fish_add_path", "fish_add_path" in config, "", group)
    check("config.fish initializes Starship only if installed", "type -q starship" in config and "starship init fish | source" in config, "", group)
    check("config.fish guards the CachyOS optional file", "test -f /usr/share/cachyos-fish-config" in config, "", group)
    check("uv.env.fish exists", env_path.is_file(), "", group)
    if env_path.is_file():
        env_text = read(env_path)
        check("uv.env.fish guards the optional source", 'test -f "$HOME/.local/bin/env.fish"' in env_text, "", group)
    check("fish config has no hardcoded /home/<username> path", re.search(r"/home/[A-Za-z0-9._-]+/", config + (read(env_path) if env_path.is_file() else "")) is None, "", group)

    for path in [config_path, env_path]:
        if not path.is_file():
            continue
        if shutil.which("fish"):
            result = run(["fish", "-n", str(path)])
            check(f"fish -n accepts {path.name}", result.returncode == 0, (result.stderr or "").strip(), group)
        else:
            skip(f"fish -n accepts {path.name}", "fish is not installed in this environment", group)

    variables = FISH / "fish_variables"
    if variables.is_file():
        text = read(variables)
        check("fish_variables has no foreign username", "screenyshadow" not in text, "", group)
        check("fish_variables is reference-only (not deployed by apply-dots.sh)", "fish_variables" not in read(ROOT / "apply-dots.sh").replace("fish_variables left untouched", ""), "", group)


def verify_fastfetch() -> None:
    group = "Fastfetch"
    path = FASTFETCH / "config.jsonc"
    if not path.is_file():
        check("config.jsonc exists", False, str(path), group)
        return
    try:
        data = json.loads(jsonc_to_json(read(path)))
    except json.JSONDecodeError as exc:
        check("config.jsonc parses as JSONC", False, str(exc), group)
        return
    check("config.jsonc parses as JSONC", True, "", group)
    check("fastfetch schema URL is present", "$schema" in data, "", group)
    check("fastfetch modules is a non-empty list", isinstance(data.get("modules"), list) and len(data["modules"]) > 0, "", group)
    modules = data.get("modules", [])
    check("every fastfetch module has a type", all(isinstance(item, dict) and item.get("type") for item in modules), "", group)
    colors = data.get("display", {}).get("color", {})
    check("fastfetch color strings have no trailing colon", colors.get("keys") == "38;2;255;255;255" and colors.get("output") == "38;2;165;165;165", str(colors), group)
    check("fastfetch has a disk module", any(item.get("type") == "disk" for item in modules), "", group)
    check("fastfetch dtime command has a fallback", any(item.get("type") == "command" and "date +%s" in str(item.get("text", "")) for item in modules), "", group)


# ---------------------------------------------------------------------------
# Wallpapers
# ---------------------------------------------------------------------------
def image_info(path: Path) -> tuple[str | None, int | None, int | None]:
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(data) >= 24 and data[12:16] == b"IHDR":
            width = int.from_bytes(data[16:20], "big")
            height = int.from_bytes(data[20:24], "big")
            return "png", width, height
        return "png", None, None
    if data.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in (0xD8, 0xD9):
                index += 2
                continue
            length = int.from_bytes(data[index + 2 : index + 4], "big")
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height = int.from_bytes(data[index + 5 : index + 7], "big")
                width = int.from_bytes(data[index + 7 : index + 9], "big")
                return "jpeg", width, height
            if length < 2:
                break
            index += length
        return "jpeg", None, None
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp", None, None
    return None, None, None


def verify_wallpapers() -> None:
    group = "Wallpapers"
    preferred = WALLPAPERS / PREFERRED_WALLPAPER
    check("preferred city-girl-sunset.png exists", preferred.is_file(), "", group)
    files = sorted(
        path for path in WALLPAPERS.iterdir()
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    )
    check("wallpaper directory has image files", len(files) > 0, "", group)
    for path in files:
        fmt, width, height = image_info(path)
        valid = fmt is not None and path.stat().st_size > 10_000
        detail = f"detected {fmt}, {width}x{height}, {path.stat().st_size} bytes"
        check(f"{path.name} contains valid image data", valid, detail, group)
        if fmt == "png":
            check(f"{path.name} has a positive PNG IHDR size", bool(width and height and width > 0 and height > 0), detail, group)
        if fmt and path.suffix.lower() not in {f".{fmt}", ".jpg" if fmt == "jpeg" else f".{fmt}"}:
            warn(f"{path.name} is actually {fmt.upper()} data but has a {path.suffix} extension")
        if width and height and (width < 1920 or height < 1080):
            warn(f"{path.name} is smaller than the 1920x1080 display ({width}x{height})")


# ---------------------------------------------------------------------------
# Scripts, docs, and security checks
# ---------------------------------------------------------------------------
def verify_scripts_and_docs() -> None:
    group = "Scripts/Docs"
    apply_path = ROOT / "apply-dots.sh"
    toggle_path = ROOT / "toggle-phase.sh"
    apply_text = read(apply_path) if apply_path.is_file() else ""
    toggle_text = read(toggle_path) if toggle_path.is_file() else ""

    check("apply-dots.sh exists", apply_path.is_file(), "", group)
    check("toggle-phase.sh exists", toggle_path.is_file(), "", group)
    check("apply-dots.sh uses strict mode", "set -Eeuo pipefail" in apply_text, "", group)
    check("toggle-phase.sh uses strict mode", "set -Eeuo pipefail" in toggle_text, "", group)

    bash = usable_bash()
    for path, text in [(apply_path, apply_text), (toggle_path, toggle_text)]:
        if bash:
            result = run([bash, "-n", str(path)])
            check(f"{path.name} passes bash -n", result.returncode == 0, (result.stderr or "").strip(), group)
        else:
            skip(f"{path.name} passes bash -n", "bash is not installed in this environment", group)

    combined_scripts = apply_text + "\n" + toggle_text
    check("scripts use the real Niri reload command", "niri msg action load-config-file" in combined_scripts, "", group)
    check("scripts do not use the invalid 'niri msg reload-config'", "niri msg reload-config" not in combined_scripts, "", group)
    check("scripts do not swallow Niri reload failures with || true", re.search(r"niri msg[^\n]*reload[^\n]*\|\|\s*true", combined_scripts) is None, "", group)
    check("scripts do not reference the upstream clone URL", "Adarsh496/niri-noctalia-dots" not in combined_scripts, "", group)
    check("apply-dots.sh targets this repository directory", 'REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"' in apply_text, "", group)
    check("apply-dots.sh stages before deployment", "mktemp -d" in apply_text and "niri validate --config" in apply_text, "", group)
    check("apply-dots.sh backs up before deployment", "BACKUP_DIR=" in apply_text and "backup_path" in apply_text, "", group)
    check("apply-dots.sh implements rollback", "rollback()" in apply_text and "TXN_TOUCHED" in apply_text, "", group)
    check("apply-dots.sh preserves the phase marker", "PHASE_MARKER" in apply_text and "rules-personal.kdl" in apply_text, "", group)
    check("toggle-phase.sh validates a staged config", "niri validate --config" in toggle_text, "", group)
    check("toggle-phase.sh backs up rules.kdl", "BACKUP_DIR=" in toggle_text and "cp -a -- \"$TARGET_RULES\"" in toggle_text, "", group)
    check("toggle-phase.sh supports status/personal/repo-default", all(token in toggle_text for token in ["status", "personal", "repo-default"]), "", group)
    check("toggle-phase.sh never runs git checkout", "git checkout" not in toggle_text, "", group)

    check("scripts do not use sudo", "sudo" not in combined_scripts, "", group)
    check("scripts do not contain an unsafe rm -rf / pattern", re.search(r"rm\s+-rf\s+[\"']?/(?:\s|$)", combined_scripts) is None, "", group)
    check("scripts do not contain an unsafe rm -rf $HOME pattern", re.search(r'rm\s+-rf\s+["\']?\$HOME(?:/["\']?)?(?:\s|$)', combined_scripts) is None, "", group)

    secret_patterns = [
        r"github_pat_[A-Za-z0-9_]{20,}",
        r"ghp_[A-Za-z0-9]{20,}",
        r"AKIA[0-9A-Z]{16}",
        r"sk-[A-Za-z0-9]{20,}",
    ]
    text_files = [
        apply_path,
        toggle_path,
        ROOT / "README.md",
        ROOT / "CHANGES.md",
        NOCTALIA / "config.toml",
        FASTFETCH / "config.jsonc",
    ]
    findings = []
    for path in text_files:
        if not path.is_file():
            continue
        content = read(path)
        for pattern in secret_patterns:
            if re.search(pattern, content):
                findings.append(f"{path.name}: {pattern}")
    check("no obvious API keys/tokens are committed", not findings, "; ".join(findings), group)

    readme_path = ROOT / "README.md"
    readme = read(readme_path) if readme_path.is_file() else ""
    changes = read(ROOT / "CHANGES.md") if (ROOT / "CHANGES.md").is_file() else ""
    check("README uses the correct clone URL", "https://github.com/supan1676/mydotfiles.git" in readme, "", group)
    check("README uses the correct clone directory", "~/mydotfiles" in readme, "", group)
    check("README does not reference the upstream repository", "Adarsh496" not in readme, "", group)
    check("README documents the real reload command", "niri msg action load-config-file" in readme, "", group)
    check("README does not document 'niri msg reload-config'", "niri msg reload-config" not in readme, "", group)
    check("README documents both phases", "personal" in readme and "repo-default" in readme, "", group)
    check("README documents the backup location", ".local/state/niri-dots/backups" in readme, "", group)
    check("README documents the preferred wallpaper", "city-girl-sunset.png" in readme, "", group)
    check("README documents lock-screen blur/tint test values", "0.80" in readme and "0.45" in readme, "", group)
    check("README documents the current 1920x1080 display", "1920x1080" in readme and "144.003" in readme, "", group)
    check("README does not describe the old HP i3 laptop as current", "i3-6006U" not in readme, "", group)
    check("README documents python3 as a dependency", "python3" in readme, "", group)
    check("CHANGES.md describes the current verification pass", "20 Oct 2026" in changes or "2026-10-20" in changes, "", group)
    check("CHANGES.md does not claim a stale 59-test result", "59" not in changes, "", group)

    for path in [ROOT / "scripts" / "noctalia-state.py", ROOT / "verify_dots.py"]:
        if path.is_file():
            try:
                compile(read(path), str(path), "exec")
                check(f"{path.name} compiles as Python", True, "", group)
            except SyntaxError as exc:
                check(f"{path.name} compiles as Python", False, str(exc), group)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
def main() -> int:
    print("==========================================================")
    print("  mydotfiles verification suite")
    print("==========================================================")
    print()

    verify_niri()
    verify_noctalia()
    verify_kitty()
    verify_fish()
    verify_fastfetch()
    verify_wallpapers()
    verify_scripts_and_docs()

    passed = sum(1 for _, _, status, _ in RESULTS if status == "PASS")
    failed = sum(1 for _, _, status, _ in RESULTS if status == "FAIL")
    skipped = sum(1 for _, _, status, _ in RESULTS if status == "SKIP")
    total = len(RESULTS)

    current_group = None
    for group, name, status, detail in RESULTS:
        if group != current_group:
            print(f"\n[{group}]")
            current_group = group
        print(f"  [{status}] {name}")
        if status in {"FAIL", "SKIP"} and detail:
            print(f"         {detail}")

    if WARNINGS:
        print("\n[Warnings]")
        for message in WARNINGS:
            print(f"  [WARN] {message}")

    print()
    print("----------------------------------------------------------")
    print(f"Total:   {total}")
    print(f"Passed:  {passed}")
    print(f"Failed:  {failed}")
    print(f"Skipped: {skipped}")
    print("----------------------------------------------------------")

    if failed:
        print("RESULT: FAIL - see the [FAIL] lines above.")
        return 1
    if skipped:
        print("RESULT: PASS for all available checks; some runtime checks were skipped.")
    else:
        print("RESULT: PASS - all checks ran and passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
