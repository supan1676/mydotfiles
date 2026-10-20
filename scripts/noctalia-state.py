#!/usr/bin/env python3
"""Selectively reconcile Noctalia's GUI state with this repository.

Noctalia loads hand-written config from ~/.config/noctalia/*.toml first and
then merges ~/.local/state/noctalia/settings.toml on top. That state file wins.
This helper only changes keys that belong to the lock-screen work:

  * remove Calendar widgets from lockscreen_widgets (tables + widget_order)
  * update existing lockscreen blur/tint keys
  * update a stale [wallpaper.default].path when that table exists
  * update a stale [theme] palette selection when that table exists

Everything else is preserved byte-for-byte, including comments outside the
edited table blocks. The file is parsed before and after editing, and the
write is atomic. It never deletes the state directory.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import sys
import tempfile
import time
import tomllib

HEADER_RE = re.compile(r"^\s*\[\[?(.+?)\]\]?\s*(?:#.*)?$")


def split_key(key: str) -> list[str]:
    """Split a dotted TOML table key, respecting quoted parts."""
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    for ch in key.strip():
        if quote is not None:
            if ch == quote:
                quote = None
            else:
                buf.append(ch)
        elif ch in ('"', "'"):
            quote = ch
        elif ch == ".":
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf).strip())
    return [p.strip().strip('"').strip("'") for p in parts]


def parse_tables(text: str):
    """Return (preamble_lines, blocks). A block is header + body lines."""
    lines = text.splitlines(keepends=True)
    preamble: list[str] = []
    blocks: list[dict] = []
    current: dict | None = None

    for line in lines:
        match = HEADER_RE.match(line.rstrip("\r\n"))
        if match:
            if current is not None:
                blocks.append(current)
            current = {
                "key": match.group(1).strip(),
                "parts": split_key(match.group(1)),
                "lines": [line],
            }
        elif current is None:
            preamble.append(line)
        else:
            current["lines"].append(line)

    if current is not None:
        blocks.append(current)
    return preamble, blocks


def block_text(block: dict) -> str:
    return "".join(block["lines"])


def indent_of(text: str) -> str:
    for line in text.splitlines():
        stripped = line.lstrip(" \t")
        if stripped and not stripped.startswith("#"):
            return line[: len(line) - len(stripped)]
    return "    "


def format_array(values: list[str], indent: str) -> str:
    if not values:
        return "[]"
    inner = indent + "    "
    body = "".join(f'{inner}"{value}",\n' for value in values)
    return "[\n" + body + indent + "]"


def replace_assignment(text: str, key: str, literal: str, add_if_missing: bool) -> tuple[str, bool]:
    """Replace one `key = value` line, preserving indentation and a trailing comment."""
    pattern = re.compile(
        rf"(?m)^([ \t]*{re.escape(key)}[ \t]*=[ \t]*)([^\r\n#]*)([ \t]*(?:#.*)?)(\r?)$"
    )
    match = pattern.search(text)
    if match:
        if match.group(2).strip() == literal.strip():
            return text, False
        new_line = match.group(1) + literal + match.group(3) + match.group(4)
        return text[: match.start()] + new_line + text[match.end() :], True

    if not add_if_missing:
        return text, False

    lines = text.splitlines(keepends=True)
    if not lines:
        return text, False
    indent = indent_of(text)
    newline = "\r\n" if lines[0].endswith("\r\n") else "\n"
    if not lines[0].endswith(("\n", "\r")):
        lines[0] += newline
    lines.insert(1, f"{indent}{key} = {literal}{newline}")
    return "".join(lines), True


def calendar_ids(data: dict) -> set[str]:
    lock = data.get("lockscreen_widgets", {})
    widgets = lock.get("widget", {}) if isinstance(lock, dict) else {}
    if not isinstance(widgets, dict):
        return set()
    found: set[str] = set()
    for widget_id, widget in widgets.items():
        if isinstance(widget, dict) and widget.get("type") == "calendar":
            found.add(str(widget_id))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", required=True, help="path to Noctalia settings.toml")
    parser.add_argument("--wallpaper", help="preferred wallpaper path")
    parser.add_argument("--blur", type=float, default=0.80, help="lock-screen blur (default 0.80)")
    parser.add_argument("--tint", type=float, default=0.45, help="lock-screen tint (default 0.45)")
    parser.add_argument("--dry-run", action="store_true", help="report changes without writing")
    parser.add_argument("--backup", action="store_true", help="keep a .bak copy next to settings.toml")
    args = parser.parse_args()

    path = os.path.abspath(os.path.expanduser(args.settings))
    if not os.path.isfile(path):
        print(f"[state] no settings file at {path}; nothing to migrate")
        return 0

    # Noctalia documents that a symlinked settings.toml is written through,
    # not replaced. Resolve the link so os.replace() updates the target.
    write_path = os.path.realpath(path)

    with open(path, "rb") as handle:
        original_bytes = handle.read()
    try:
        # utf-8-sig accepts both plain UTF-8 and a UTF-8 BOM. The BOM is not
        # reproduced when writing; the TOML content is unchanged otherwise.
        original_text = original_bytes.decode("utf-8-sig")
        data = tomllib.loads(original_text)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        print(f"[state] ERROR: cannot parse {path}: {exc}", file=sys.stderr)
        print("[state] state was NOT modified", file=sys.stderr)
        return 1

    cal_ids = calendar_ids(data)
    preamble, blocks = parse_tables(original_text)
    changes: list[str] = []

    kept_blocks: list[dict] = []
    removed_calendar_ids: set[str] = set()
    for block in blocks:
        parts = block["parts"]
        if parts[:2] == ["lockscreen_widgets", "widget"] and len(parts) >= 3 and parts[2] in cal_ids:
            removed_calendar_ids.add(parts[2])
            continue

        text = block_text(block)

        if parts == ["lockscreen_widgets"]:
            order_match = re.search(
                r"(?ms)^([ \t]*widget_order[ \t]*=[ \t]*)\[[^\]]*\]", text
            )
            if order_match:
                order = data.get("lockscreen_widgets", {}).get("widget_order", [])
                if not isinstance(order, list):
                    order = []
                new_order = [str(item) for item in order if str(item) not in cal_ids]
                if new_order != [str(item) for item in order]:
                    indent = order_match.group(1)[: len(order_match.group(1)) - len(order_match.group(1).lstrip(" \t"))]
                    replacement = order_match.group(1) + format_array(new_order, indent)
                    text = text[: order_match.start()] + replacement + text[order_match.end() :]
                    changes.append(
                        "removed calendar widget from widget_order "
                        f"({len(order) - len(new_order)} entr{'y' if len(order) - len(new_order) == 1 else 'ies'})"
                    )

        elif parts == ["lockscreen"]:
            text, changed = replace_assignment(text, "blur_intensity", f"{args.blur:.2f}", False)
            if changed:
                changes.append(f"set lockscreen.blur_intensity = {args.blur:.2f}")
            text, changed = replace_assignment(text, "tint_intensity", f"{args.tint:.2f}", False)
            if changed:
                changes.append(f"set lockscreen.tint_intensity = {args.tint:.2f}")
            if args.wallpaper:
                text, changed = replace_assignment(
                    text, "wallpaper", f'"{args.wallpaper}"', False
                )
                if changed:
                    changes.append("updated lockscreen.wallpaper")

        elif parts == ["wallpaper", "default"]:
            if args.wallpaper:
                text, changed = replace_assignment(
                    text, "path", f'"{args.wallpaper}"', False
                )
                if changed:
                    changes.append("updated wallpaper.default.path")

        elif parts == ["theme"]:
            text, changed = replace_assignment(text, "source", '"wallpaper"', False)
            if changed:
                changes.append("set theme.source = wallpaper")
            text, changed = replace_assignment(
                text, "wallpaper_scheme", '"m3-content"', False
            )
            if changed:
                changes.append("set theme.wallpaper_scheme = m3-content")

        block["lines"] = text.splitlines(keepends=True)
        kept_blocks.append(block)

    for widget_id in sorted(removed_calendar_ids):
        changes.append(f"removed calendar widget table: lockscreen_widgets.widget.{widget_id}")

    new_text = "".join(preamble) + "".join(block_text(block) for block in kept_blocks)

    if not changes:
        print(f"[state] {path}: no selective changes needed")
        return 0

    # Never write a file that would no longer parse.
    try:
        tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as exc:
        print(f"[state] ERROR: generated TOML is invalid: {exc}", file=sys.stderr)
        print("[state] state was NOT modified", file=sys.stderr)
        return 1

    print(f"[state] {path}")
    for change in changes:
        print(f"[state]   - {change}")

    if args.dry_run:
        print("[state] dry run: no changes written")
        return 0

    if args.backup:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = f"{write_path}.bak-{stamp}"
        counter = 1
        while os.path.exists(backup):
            backup = f"{write_path}.bak-{stamp}-{counter}"
            counter += 1
        shutil.copy2(write_path, backup)
        print(f"[state] backup: {backup}")

    directory = os.path.dirname(write_path) or "."
    mode = stat.S_IMODE(os.stat(write_path).st_mode)
    fd, temporary = tempfile.mkstemp(prefix=".settings.toml.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(new_text)
        try:
            os.chmod(temporary, mode)
        except OSError:
            pass
        os.replace(temporary, write_path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise

    print("[state] changes written atomically")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
