"""The electrical editor's parameter file: presets/el_parameters.json (one home for every user-adjustable value), loaded and
checked here.

Layout: sections -> {label, mark, source, values -> {key: {value, label, unit?, mark?, source?}}}. A value without its own mark or
source has its section's. The page reads the same file (embedded as JSON) and builds its colours and line widths from it.

contrast() is the WCAG 2.1 contrast ratio; contrast_problems() lists every symbol / link / marker / selection colour of both
palettes that has less than contrast_min (3:1, non-text contrast) against its palette's background.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re

from vpt import PRESETS, SCHEMAS

PRESET = PRESETS / "el_parameters.json"
SCHEMA = SCHEMAS / "el_parameters.schema.json"
OTHER_PRESETS = {"el_rules_at.json": PRESETS / "el_rules_at.json", "el_page.json": PRESETS / "el_page.json",
                 "el_symbols_at.json": PRESETS / "el_symbols_at.json", "el_layout.schema.json": SCHEMAS / "el_layout.schema.json"}
# values the page applies at once when edited in the Parameters panel; the rest (the suggestion geometry and the examples) is
# computed in Python when the plan file is exported, so an edit takes effect after the plan is exported again
LIVE_SECTIONS = ("snap", "page", "colours_screen", "colours_print", "drawing_screen", "drawing_print", "screen_lines", "print_lines")
LIVE_RULES = ("hint_switch_near_door_m",)
PALETTES = ("colours_screen", "colours_print")
COLOUR_KEYS = ("licht", "schalter", "steckdosen", "kueche", "daten", "sicherheit", "verteiler", "link", "marker", "marker_hit",
               "selection", "connect_allowed", "connect_source")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def load(path: pathlib.Path = PRESET) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def sha256(path: pathlib.Path = PRESET) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def load_schema(path: pathlib.Path = SCHEMA) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def dump(p: dict) -> str:
    """The text the page's Save / Copy parameters writes (same layout: 2-space JSON, UTF-8, a final newline)."""
    return json.dumps(p, ensure_ascii=False, indent=2) + "\n"


def schema_problems(p, schema: dict | None = None) -> list[str]:
    from vpt import el_layout
    return el_layout.validate(p, schema or load_schema())


def check_file(text: str, current: dict | None = None) -> tuple[str, str]:
    """May this text be loaded as the page's parameters? ("match" | "different" | "could-not-tell", why); the page's Load
    parameters gives the same three outcomes. match: valid, same id, the same sections, values and rules as this page knows (the
    values may differ). different: a valid parameter file of another id, or with other sections / values / rules. could-not-tell:
    not JSON, not valid against the schema, or values that break the rules (contrast, ranges)."""
    cur = current or load()
    try:
        p = json.loads(text)
    except (json.JSONDecodeError, TypeError) as e:
        return "could-not-tell", f"not JSON ({e})"
    sp = schema_problems(p)
    if sp:
        return "could-not-tell", f"not a valid parameter file ({len(sp)} problem(s), first: {sp[0]})"
    if p["id"] != cur["id"]:
        return "different", f"parameters of another page ({p['id']}), not {cur['id']}"
    shape = lambda q: ({s: sorted(v["values"]) for s, v in q["sections"].items()}, sorted(q["rules"]["definitions"]),
                       sorted(r["id"] for r in q["rules"]["rule_sets"]))
    if shape(p) != shape(cur):
        return "different", "other sections, values or rules than this page knows"
    vp = validate(p)
    if vp:
        return "could-not-tell", f"values break the rules ({len(vp)} problem(s), first: {vp[0]})"
    return "match", "valid; same id and parameters"


def single_home_problems(p: dict | None = None, others: dict | None = None) -> list[str]:
    """A parameter's key or a palette colour that also appears in another electrical preset: a second home (the test fails).
    others: {file name: parsed JSON} (default: OTHER_PRESETS)."""
    p = p or load()
    others = others if others is not None else {n: json.loads(f.read_text(encoding="utf-8")) for n, f in OTHER_PRESETS.items()}
    keys = {k for s in p["sections"].values() for k in s["values"]} | set(p["rules"]["definitions"]) | {"default_rule_set", "rule_sets", "colour"}
    keys -= {"background"}
    colours = {v["value"].lower() for n in PALETTES for v in p["sections"][n]["values"].values()}
    out = []

    def walk(x, name, path):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in keys and not (path.endswith(".properties") or path.endswith(".$defs")):
                    out.append(f"{name}: {path}.{k} (a parameter: its home is el_parameters.json)")
                walk(v, name, f"{path}.{k}")
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, name, f"{path}[{i}]")
        elif isinstance(x, str) and x.lower() in colours:
            out.append(f"{name}: {path} = {x} (a palette colour: its home is el_parameters.json)")
    for name, obj in others.items():
        walk(obj, name, "$")
    return out


def rows(p: dict | None = None) -> list[dict]:
    """Every parameter as a row (section, key, label, value, unit, mark, source, live), for the Documentation table."""
    p = p or load()
    out = []
    for sk, s in p["sections"].items():
        for k, v in s["values"].items():
            out.append({"section": s["label"], "key": f"{sk}.{k}", "label": v["label"], "value": v["value"], "unit": v.get("unit", ""),
                        "mark": v.get("mark", s["mark"]), "source": v.get("source", s["source"]), "live": sk in LIVE_SECTIONS})
    for rs in p["rules"]["rule_sets"]:
        for k, d in p["rules"]["definitions"].items():
            v = p["rules"]["values"][rs["id"]][k]
            out.append({"section": f"{p['rules']['label']}: {rs['name']}", "key": f"rules.{rs['id']}.{k}", "label": d["label"], "value": v["value"],
                        "unit": d["unit"], "mark": v.get("mark") or "", "source": v.get("source") or "", "live": k in LIVE_RULES})
    return out


def value(p: dict, section: str, key: str):
    return p["sections"][section]["values"][key]["value"]


def palette(p: dict, name: str) -> dict[str, str]:
    return {k: v["value"] for k, v in p["sections"][name]["values"].items()}


def _lin(c: float) -> float:
    c = c / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def blend(fg: str, bg: str, alpha: float) -> str:
    """fg drawn with opacity alpha over bg (sRGB channel mix, as a browser composites)."""
    f, b = fg.lstrip("#"), bg.lstrip("#")
    ch = [round(int(f[i:i + 2], 16) * alpha + int(b[i:i + 2], 16) * (1 - alpha)) for i in (0, 2, 4)]
    return "#" + "".join(f"{c:02x}" for c in ch)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def contrast_table(p: dict) -> list[tuple[str, str, str, str, float]]:
    """[(palette, key, colour, background, ratio)] for every checked colour; the marker is checked at its opacity."""
    out = []
    op = value(p, "screen_lines", "marker_opacity")
    for name in PALETTES:
        pal = palette(p, name)
        bg = pal["background"]
        for k in COLOUR_KEYS:
            c = pal[k]
            shown = blend(c, bg, op) if k == "marker" else c
            out.append((name, k, c, bg, contrast(shown, bg)))
    return out


def contrast_problems(p: dict) -> list[str]:
    lim = p["contrast_min"]
    return [f"{n}.{k} {c} on {bg}: {r:.2f} < {lim}" for n, k, c, bg, r in contrast_table(p) if r < lim]


def validate(p: dict) -> list[str]:
    """Problems of the parameter file (empty = clean): shape, colours, ranges, contrast."""
    out = []
    secs = p.get("sections") or {}
    for need in PALETTES + ("drawing_screen", "drawing_print", "screen_lines", "print_lines", "snap", "page"):
        if need not in secs:
            out.append(f"section {need} missing")
    if out:
        return out
    for sk, s in secs.items():
        for f in ("label", "mark", "source", "values"):
            if f not in s:
                out.append(f"section {sk}: {f} missing")
        for k, v in (s.get("values") or {}).items():
            if not isinstance(v, dict) or "value" not in v or "label" not in v:
                out.append(f"{sk}.{k}: needs value and label")
    for name in PALETTES:
        pal = palette(p, name)
        for k in ("background",) + COLOUR_KEYS:
            if not HEX.match(str(pal.get(k, ""))):
                out.append(f"{name}.{k}: not a #rrggbb colour")
    if out:
        return out
    for name in ("drawing_screen", "drawing_print"):
        for k, v in secs[name]["values"].items():
            if not (isinstance(v["value"], (int, float)) and 0 <= v["value"] <= 1):
                out.append(f"{name}.{k}: must be a number from 0 to 1")
    for k, v in secs["screen_lines"]["values"].items():
        vals = v["value"] if isinstance(v["value"], list) else [v["value"]]
        if not all(isinstance(x, (int, float)) and x > 0 for x in vals):
            out.append(f"screen_lines.{k}: must be positive")
    for sk in ("snap", "page"):
        for k, v in secs[sk]["values"].items():
            if not (isinstance(v["value"], (int, float)) and v["value"] > 0):
                out.append(f"{sk}.{k}: must be a positive number")
    if not (isinstance(p.get("contrast_min"), (int, float)) and p["contrast_min"] >= 3):
        out.append("contrast_min must be at least 3 (WCAG non-text contrast)")
    return out + contrast_problems(p)
