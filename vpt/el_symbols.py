"""The symbol library of the electrical editor: presets/el_symbols_at.json (one home), loaded and checked here.

A library holds one or more symbol SETS (the page lets the user pick one; default_set first). A set names the standard it
claims, its edition, provenance and whether it was verified; each symbol has a code, German and English names, a category, the
target layer (one per category, "Elektro – <category>"), an SVG drawing (plain lines, arcs, rectangles, letters, in mm on the
storey sheet, insertion point 0,0, +y = wall side), a box (its extent, for picking and the print legend), the codes it may be
connected to (switch <-> light) and verified / verified_against.

validate() returns the list of problems (empty = clean). The editor build refuses a broken library (a missing name, an SVG
that does not parse, a raster image or external reference in a symbol, an unknown category or code, a symbol marked verified
without saying against what, an unverified set that does not say UNVERIFIED).
"""
from __future__ import annotations

import json
import pathlib
import re
from xml.etree import ElementTree as ET

from vpt import PRESETS

PRESET = PRESETS / "el_symbols_at.json"
SVG_NS = "http://www.w3.org/2000/svg"

SET_FIELDS = ("id", "version", "name_de", "name_en", "standard", "installation_standard", "edition", "provenance", "verified",
              "verified_against", "status", "units", "stroke_mm", "categories", "symbols")
SYMBOL_FIELDS = ("code", "name_de", "name_en", "category", "layer", "svg", "box", "connectable_to", "verified", "verified_against")
# plain vector elements only: no image, no use/href, no foreignObject, no script
ALLOWED_TAGS = {"line", "circle", "path", "rect", "polyline", "polygon", "ellipse", "text"}
ALLOWED_ATTRS = {"x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "d", "width", "height", "points", "fill", "stroke",
                 "font-size", "text-anchor", "font-family", "font-weight"}


def load(path: pathlib.Path = PRESET) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def default_set(lib: dict) -> dict:
    return next(s for s in lib["sets"] if s["id"] == lib["default_set"])


def layers(s: dict) -> list[str]:
    """The set's target layers, in category order (one per category that has symbols)."""
    out = []
    for c in s["categories"]:
        for x in s["symbols"]:
            if x["category"] == c["key"] and x["layer"] not in out:
                out.append(x["layer"])
    return out


def category(s: dict, key: str) -> dict:
    return next(c for c in s["categories"] if c["key"] == key)


def colour(s: dict, sym: dict, params: dict | None = None, palette: str = "colours_print") -> str:
    """The symbol's category colour from the parameter file (presets/el_parameters.json, the one home of the colours;
    default: the print palette, which the page's screen colours override)."""
    from vpt import el_params
    return el_params.palette(params or el_params.load(), palette)[sym["category"]]


def parse_fragment(svg: str, wrap: bool = True) -> ET.Element:
    """Parse a symbol's SVG (a fragment of elements, wrapped in <svg> to parse) or a whole <svg> (wrap=False)."""
    text = f'<svg xmlns="{SVG_NS}">{svg}</svg>' if wrap else svg
    if not wrap and "xmlns=" not in text.split(">", 1)[0]:
        text = text.replace("<svg", f'<svg xmlns="{SVG_NS}"', 1)
    return ET.fromstring(text)


def _svg_problems(code: str, svg: str) -> list[str]:
    try:
        root = parse_fragment(svg)
    except ET.ParseError as e:
        return [f"{code}: SVG does not parse ({e})"]
    out = []
    kids = list(root.iter())[1:]
    if not kids:
        out.append(f"{code}: SVG draws nothing")
    for e in kids:
        tag = e.tag.rsplit("}", 1)[-1]
        if tag not in ALLOWED_TAGS:
            out.append(f"{code}: SVG element <{tag}> not allowed (plain vector elements only: no image, use, script)")
        bad = sorted(a for a in e.attrib if a.rsplit("}", 1)[-1] not in ALLOWED_ATTRS)
        if bad:
            out.append(f"{code}: SVG attribute(s) {bad} not allowed")
    if re.search(r"(?:href|url\(|data:)", svg, re.I):
        out.append(f"{code}: SVG references something outside itself")
    return out


def validate(lib: dict) -> list[str]:
    problems: list[str] = []
    sets = lib.get("sets") or []
    if not sets:
        return ["no symbol set"]
    if lib.get("default_set") not in {s.get("id") for s in sets}:
        problems.append(f"default_set {lib.get('default_set')!r} is not a set id")
    if len({s.get("id") for s in sets}) != len(sets):
        problems.append("duplicate set id")
    for s in sets:
        sid = s.get("id", "?")
        problems += [f"set {sid}: missing {f}" for f in SET_FIELDS if f not in s]
        if s.get("verified") is not True and s.get("verified_against") is not None:
            problems.append(f"set {sid}: verified_against given but verified is not true")
        if s.get("verified") is True and not s.get("verified_against"):
            problems.append(f"set {sid}: marked verified without verified_against")
        if s.get("verified") is not True and "UNVERIFIED" not in (s.get("status") or ""):
            problems.append(f"set {sid}: unverified set must say UNVERIFIED in its status")
        cats = {c.get("key") for c in s.get("categories") or []}
        codes = [x.get("code") for x in s.get("symbols") or []]
        if len(set(codes)) != len(codes):
            problems.append(f"set {sid}: duplicate symbol code")
        layer_of: dict = {}
        for x in s.get("symbols") or []:
            code = x.get("code", "?")
            problems += [f"set {sid} symbol {code}: missing {f}" for f in SYMBOL_FIELDS
                         if f not in x or x[f] in ("", None) and f != "verified_against"]
            if x.get("category") not in cats:
                problems.append(f"set {sid} symbol {code}: unknown category {x.get('category')!r}")
            if x.get("category") in layer_of and layer_of[x["category"]] != x.get("layer"):
                problems.append(f"set {sid} symbol {code}: layer {x.get('layer')!r} differs from its category's layer {layer_of[x['category']]!r}")
            layer_of.setdefault(x.get("category"), x.get("layer"))
            if not str(x.get("layer", "")).startswith("Elektro"):
                problems.append(f"set {sid} symbol {code}: layer must be an Elektro layer")
            if "svg" in x:
                problems += [f"set {sid} symbol {p}" for p in _svg_problems(code, x["svg"])]
            box = x.get("box")
            if not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box) and box[2] > 0 and box[3] > 0):
                problems.append(f"set {sid} symbol {code}: box must be [x, y, width>0, height>0]")
            for c in x.get("connectable_to") or []:
                if c not in codes:
                    problems.append(f"set {sid} symbol {code}: connectable_to names unknown code {c!r}")
            if x.get("verified") is not s.get("verified") and x.get("verified") is True:
                problems.append(f"set {sid} symbol {code}: verified symbol in an unverified set")
            if x.get("verified") is True and not x.get("verified_against"):
                problems.append(f"set {sid} symbol {code}: marked verified without verified_against")
            if x.get("verified") is not True and x.get("verified_against") is not None:
                problems.append(f"set {sid} symbol {code}: verified_against given but verified is not true")
    return problems


def preview_svg(s: dict, sym: dict, size_px: int = 28, cls: str = "el-prev", params: dict | None = None) -> str:
    """A small stand-alone <svg> of one symbol (palette, Documentation, print legend). Its colour attribute is the print colour;
    the class el-c-<category> lets the page's generated style give it the screen colour."""
    x, y, w, h = sym["box"]
    m = max(w, h)
    vb = f"{x + w / 2 - m / 2:g} {y + h / 2 - m / 2:g} {m:g} {m:g}"
    col = colour(s, sym, params)
    return (f'<svg class="{cls}" viewBox="{vb}" width="{size_px}" height="{size_px}" aria-hidden="true" focusable="false">'
            f'<g class="el-symg el-c-{sym["category"]}" fill="none" stroke="{col}" color="{col}" stroke-width="{s["stroke_mm"]}" '
            f'stroke-linecap="round">{sym["svg"]}</g></svg>')
