"""Rooms, doors, walls and windows per storey of a DXF: the input for the electrical editor's placement suggestions and room lookup.

Everything drawing-specific is in presets/plan_extract.json (layer naming rule, which base names hold room labels, room
outlines, walls and doors, the door geometry limits). Model space only.

    layer_info(names, pre)   storey key, status (Abbruch / Neubau / None) and base name of every layer
    ingest(doc, pre)         texts, closed polygons, straight segments and door arcs of model space (INSERTs exploded;
                             content on layer 0 inside a block takes the INSERT's layer, as CAD does)
    assign(...)              the room of a point: (a) the smallest closed room outline around it that holds a label, else
                             (b) the nearest label within max_dist whose straight line to the point crosses no wall segment
    extract(doc, pre)        per storey: rooms, doors, walls, and the checks R1-R5

Rooms   id <storey>-R<n> in drawing order of the labels; name and area text; wet room flag; the outline: the smallest closed
        polygon around the label anchor that holds no other label of the storey, on the room_polygons layers, else on the
        extra_outline_layers; else "no outline: could not tell".
Doors   an ARC on a door layer whose radius and sweep are in the preset's ranges. Hinge = arc centre; width = radius. The
        closed leaf position (the opening) is the arc end WITHOUT a leaf line from the hinge, else the only end that touches
        a wall segment, else the end whose direction from the hinge runs along a nearby wall segment, else could not tell (both ends are then tried: the rooms are kept
        when both give the same pair). The rooms on the two sides of the opening are found with assign() at the probe
        distances; a side with no room is "no room (outside, or a space without a label)".
Walls   the straight pieces of the wall layers (excluded statuses left out); per room the segments running along its outline.
Windows groups of straight lines on the window layers (window_groups(): parallel lines across one wall, plus the short sill
        ends); the opening (window_opening()): along the group, the median start to the median end of its parallel lines; across,
        the middle of the wall. Id <storey>-F<n>; the wall pieces ending at the opening; the rooms on its two sides.
Readers for real drawings (preset keys; every default is the behaviour above, so the synthetic flat's plan file does not change):
    text_reader       "plain": ezdxf's fast plain_text(). "mtext_clean": ezdxf's full MTEXT parser, which reads the
                      non-breaking space \\~ inside formatting (the fast one drops it and what follows), after repairing a
                      size value without its leading zero (\\H.66x;); then a stacked superscript's caret dropped ('m2^' -> 'm2')
                      and spaces collapsed.
    room_label_rule   "every_text": every text with a name line is a room; a lone area text joins the nearest name text.
                      "area_with_name_above": only an area text makes a room: the name is the nearest text directly above it
                      (left edges within max_dx_heights text heights, top within max_dy_heights), or the line above the area
                      line of one multi-line MTEXT; anchor = the area text. Notes, dimensions and finishes on the label layer
                      are then not rooms; texts of a table (a header matching table_header_regex and the rows in its window)
                      never are.
    wall_reader       "exploded_lines": the LINE and LWPOLYLINE pieces of the wall layers, block content included.
                      "top_level_paths": every top-level entity of the wall layers (lines, polylines with their bulges, arcs,
                      circles, splines and HATCH boundaries) flattened into straight pieces within flatten_m; block content left
                      out (blocks on wall layers are often details or symbols, not walls).
Checks (match / different / could-not-tell; could-not-tell is never a match):
    R1 every room has an id and a storey      R2 every door connects at least one room (never a room to itself)
    R3 every room has an outline              R4 every door's swing is determined
    R5 every room with an outline has a wall segment along it
    R6 every window lies in a wall of a room (no window found: could not tell, the suggestions cannot keep clear of windows)
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from shapely import STRtree
from shapely.geometry import LineString, Point, Polygon

MATCH, DIFF, UNK = "match", "different", "could-not-tell"
NO_OUTLINE = "no outline: could not tell"
NO_ROOM = "no room (outside, or a space without a label)"
ALL = "all"


@dataclass
class Check:
    id: str
    title: str
    status: str
    detail: str
    items: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "status": self.status, "detail": self.detail, "items": self.items}


# ---- layers ----------------------------------------------------------------------------------------------------------------

def layer_info(names: list[str], pre: dict) -> dict[str, dict]:
    """{layer: {"storey", "status", "base"}}. When no layer matches the preset's rule, every layer belongs to storey 'all'
    with its own name as base; else a layer that does not match belongs to no storey (storey None)."""
    rx = re.compile(pre["layer_regex"])
    hits = {n: rx.match(n) for n in names}
    if not any(hits.values()):
        return {n: {"storey": ALL, "status": None, "base": n} for n in names}
    return {n: ({"storey": m.group("storey"), "status": m.groupdict().get("status"), "base": m.group("base")} if m
                else {"storey": None, "status": None, "base": n}) for n, m in hits.items()}


def storey_label(key: str, pre: dict) -> str:
    if key in (pre.get("storey_labels") or {}):
        return pre["storey_labels"][key]
    for p in pre.get("storey_label_patterns") or []:
        m = re.match(p["regex"], key)
        if m:
            return re.sub(r"\{(\d+)\}", lambda g: m.group(int(g.group(1))), p["label"])
    return key


# ---- ingest ----------------------------------------------------------------------------------------------------------------

def _explode(e, layer: str, depth: int = 0):
    """(entity, layer) of an entity and, for an INSERT, of its block content (recursively, layer 0 -> the INSERT's)."""
    if e.dxftype() != "INSERT":
        yield e, layer
        return
    if depth > 16:
        return
    try:
        parts = list(e.virtual_entities())
    except Exception:          # noqa: BLE001 - a block that cannot be exploded is skipped, not fatal
        return
    for v in parts:
        lay = v.dxf.get("layer", "0")
        yield from _explode(v, layer if lay == "0" else lay, depth + 1)


TEXT_READERS = ("plain", "mtext_clean")
LABEL_RULES = ("every_text", "area_with_name_above")
WALL_READERS = ("exploded_lines", "top_level_paths")


def options(pre: dict) -> dict:
    """The reader options of a preset with their defaults filled in: {"text_reader", "room_label_rule": {...}, "wall_reader": {...}}.
    A missing key is the default reader (an older preset keeps its behaviour); the distances have their one home in the
    preset (presets/plan_extract.json) and are required only by the reader that uses them. An unknown value or a missing
    distance raises ValueError, never a silent default."""
    tr = pre.get("text_reader", "plain")
    lr = dict({"rule": "every_text"}, **(pre.get("room_label_rule") or {}))
    wr = dict({"reader": "exploded_lines"}, **(pre.get("wall_reader") or {}))
    for what, val, allowed in (("text_reader", tr, TEXT_READERS), ("room_label_rule.rule", lr["rule"], LABEL_RULES),
                               ("wall_reader.reader", wr["reader"], WALL_READERS)):
        if val not in allowed:
            raise ValueError(f"preset {what} must be one of {', '.join(allowed)}, not {val!r}")
    need = ([("room_label_rule", lr, x) for x in ("max_dx_heights", "max_dy_heights", "table_window_right_heights",
                                                  "table_window_down_heights")] if lr["rule"] == "area_with_name_above" else [])
    need += [("wall_reader", wr, "flatten_m")] if wr["reader"] == "top_level_paths" else []
    missing = [f"{blk}.{x}" for blk, d, x in need if not isinstance(d.get(x), (int, float)) or d[x] <= 0]
    if missing:
        raise ValueError(f"preset needs a positive number for {', '.join(missing)}")
    return {"text_reader": tr, "room_label_rule": lr, "wall_reader": wr}


_MT_BARE_DOT = re.compile(r"(?<!\\)((?:\\\\)*)\\([HQTW])\.")   # \H.66x; -> \H0.66x; (an even run of backslashes is text)
_CARET = re.compile(r"(?<=\w)\^(?=\s|$)")                       # 'm2^': the caret ezdxf leaves after a stacked superscript


def mtext_clean(raw: str) -> str:
    """MTEXT content as plain text by ezdxf's full MTEXT parser (plain_mtext): the fast plain_text() of ezdxf 1.4 misreads the
    non-breaking space \\~ inside formatting (it drops the code and what follows: '5,00\\~m{...}' -> '5,00'). One code the full
    parser misreads is repaired first: a size value without its leading zero (\\H.66x; leaves '.66x;' in the text). Then the
    caret of a stacked superscript is dropped, non-breaking spaces become spaces, spaces are collapsed and empty lines
    dropped (a multi-line label stays multi-line)."""
    from ezdxf.tools.text import plain_mtext
    s = _MT_BARE_DOT.sub(lambda m: m.group(1) + "\\" + m.group(2) + "0.", raw)
    return clean_lines(plain_mtext(s, split=False))


def clean_lines(s: str) -> str:
    lines = (_CARET.sub("", re.sub(r"[ \t ]+", " ", ln)).strip() for ln in s.replace("\r", "").split("\n"))
    return "\n".join(ln for ln in lines if ln)


def _text_of(e, reader: str = "plain") -> tuple[str, tuple[float, float], float] | None:
    t = e.dxftype()
    if t == "MTEXT":
        p = e.dxf.insert
        txt = mtext_clean(e.text) if reader == "mtext_clean" else e.plain_text()
        return txt, (float(p.x), float(p.y)), float(e.dxf.get("char_height", 0) or 0)
    if t == "TEXT":
        p = e.dxf.align_point if e.dxf.hasattr("align_point") and (e.dxf.get("halign", 0) or e.dxf.get("valign", 0)) else e.dxf.insert
        txt = clean_lines(e.dxf.text) if reader == "mtext_clean" else e.dxf.text
        return txt, (float(p.x), float(p.y)), float(e.dxf.get("height", 0) or 0)
    return None


def text_box(e, text: str, x: float, y: float, h: float) -> tuple[float, float]:
    """(left, top) edge of a text, estimated without fonts and ignoring rotation: MTEXT from its attachment point (lines
    1.667 heights apart, width from the entity or 0.6 heights per character), TEXT from its alignment (baseline/bottom = top
    one height above)."""
    lines = text.split("\n") or [""]
    if e.dxftype() == "MTEXT":
        ap = int(e.dxf.get("attachment_point", 1) or 1)
        col, row = (ap - 1) % 3, (ap - 1) // 3
        tall = h * (1 + 1.667 * (len(lines) - 1) * float(e.dxf.get("line_spacing_factor", 1.0) or 1.0))
        wide = float(e.dxf.get("width", 0) or 0) or 0.6 * h * max(len(ln) for ln in lines)
        return x - (0.0, wide / 2, wide)[col], y + (0.0, tall / 2, tall)[row]
    col = {0: 0, 1: 1, 2: 2, 3: 0, 4: 1, 5: 0}.get(int(e.dxf.get("halign", 0) or 0), 0)
    wide = 0.6 * h * len(text)
    top = y if int(e.dxf.get("valign", 0) or 0) == 3 else (y + h / 2 if int(e.dxf.get("valign", 0) or 0) == 2 else y + h)
    return x - (0.0, wide / 2, wide)[col], top


def ingest(doc, info: dict[str, dict], text_reader: str = "plain") -> dict:
    """Model-space content by kind: texts [{text, x, y, h, left, top, layer}], polygons [{geom, layer, handle}], segments
    [{p, q, layer}], arcs [{hinge, a, b, r, sweep, layer, handle}] (world coordinates)."""
    from ezdxf.math import Vec3
    texts, polys, segs, arcs = [], [], [], []
    for top in doc.modelspace():
        for e, layer in _explode(top, top.dxf.get("layer", "0")):
            t = e.dxftype()
            handle = top.dxf.get("handle", "") or ""
            if t in ("MTEXT", "TEXT"):
                tx = _text_of(e, text_reader)
                if tx and tx[0].strip():
                    left, top_y = text_box(e, tx[0], tx[1][0], tx[1][1], tx[2])
                    texts.append({"text": tx[0], "x": tx[1][0], "y": tx[1][1], "h": tx[2], "left": left, "top": top_y, "layer": layer})
            elif t == "LINE":
                a, b = e.dxf.start, e.dxf.end
                if (a.x, a.y) != (b.x, b.y):
                    segs.append({"p": (float(a.x), float(a.y)), "q": (float(b.x), float(b.y)), "layer": layer})
            elif t == "LWPOLYLINE":
                pts = list(e.get_points("xyb"))
                ocs = e.ocs()
                w = [ocs.to_wcs(Vec3(x, y, 0)) for x, y, _ in pts]
                closed = bool(e.closed) or (len(w) > 2 and (w[0].x, w[0].y) == (w[-1].x, w[-1].y))
                pairs = list(zip(range(len(w)), range(1, len(w)))) + ([(len(w) - 1, 0)] if e.closed and len(w) > 2 else [])
                for i, j in pairs:
                    if not pts[i][2] and (w[i].x, w[i].y) != (w[j].x, w[j].y):
                        segs.append({"p": (float(w[i].x), float(w[i].y)), "q": (float(w[j].x), float(w[j].y)), "layer": layer})
                if closed and len(w) >= 3:
                    g = Polygon([(float(v.x), float(v.y)) for v in w])
                    if not g.is_valid:
                        g = g.buffer(0)
                    if not g.is_empty and g.area > 0:
                        polys.append({"geom": g, "layer": layer, "handle": handle})
            elif t == "ARC":
                sa = float(e.dxf.start_angle)
                sweep = (float(e.dxf.end_angle) - sa) % 360.0
                a, b = list(e.vertices([sa, sa + sweep]))
                c = e.ocs().to_wcs(e.dxf.center)
                arcs.append({"hinge": (float(c.x), float(c.y)), "a": (float(a.x), float(a.y)), "b": (float(b.x), float(b.y)),
                             "r": float(e.dxf.radius), "sweep": sweep, "layer": layer, "handle": handle})
    return {"texts": texts, "polygons": polys, "segments": segs, "arcs": arcs}


# ---- room logic ------------------------------------------------------------------------------------------------------------

def labels_of(texts: list[dict], area_re: re.Pattern, key: str, start: int = 1) -> list[dict]:
    """Room labels from label texts, numbered <key>-R<n> in drawing order. An MTEXT holds name and area text on its lines; a
    TEXT that is only an area text joins the nearest name text within three text heights."""
    named, areas = [], []
    for t in texts:
        lines = [x.strip() for x in t["text"].splitlines() if x.strip()]
        name = next((x for x in lines if not area_re.search(x)), None)
        area = next((x for x in lines if area_re.search(x)), None)
        (named if name else areas).append(dict(t, name=name, area_text=area))
    for a in areas:
        near = sorted(named, key=lambda n: math.dist((n["x"], n["y"]), (a["x"], a["y"])))
        if near and not near[0]["area_text"] and math.dist((near[0]["x"], near[0]["y"]), (a["x"], a["y"])) <= 3 * max(a["h"], near[0]["h"], 1e-9):
            near[0]["area_text"] = a["area_text"]
    return [{"id": f"{key}-R{n}", "storey": key, "label_no": n, "name": lab["name"], "area_text": lab["area_text"],
             "px": lab["x"], "py": lab["y"]} for n, lab in enumerate(named, start)]


def labels_area_first(texts: list[dict], area_re: re.Pattern, key: str, rule: dict, start: int = 1) -> list[dict]:
    """Room labels by the rule "area_with_name_above" (see the module docstring), numbered <key>-R<n>: first the multi-line
    texts holding name and area, then the single-line area texts, each in drawing order. A text is an area text when
    area_re matches at its start. Texts of a table are left out first: a header matching rule["table_header_regex"] and the
    texts whose left edge lies from one header height left of the header's to table_window_right_heights right of it and
    whose top lies up to table_window_down_heights below the header's."""
    hdr = re.compile(rule["table_header_regex"]) if rule.get("table_header_regex") else None
    heads = [t for t in texts if hdr and hdr.match(t["text"])]

    def in_table(t: dict) -> bool:
        for hd in heads:
            hh = hd["h"] or 1.0
            if (t is not hd and hd["left"] - hh <= t["left"] <= hd["left"] + rule["table_window_right_heights"] * hh
                    and 0 < hd["top"] - t["top"] <= rule["table_window_down_heights"] * hh):
                return True
        return False
    on = [t for t in texts if not any(t is hd for hd in heads) and not in_table(t)]
    found, multi = [], set()
    for i, t in enumerate(on):
        lines = [x.strip() for x in t["text"].split("\n")]
        for j in range(1, len(lines)):
            if area_re.match(lines[j]) and lines[j - 1] and not area_re.match(lines[j - 1]):
                found.append({"name": lines[j - 1], "area_text": lines[j], "x": t["x"], "y": t["y"]})
                multi.add(i)
                break
    singles = [t for i, t in enumerate(on) if i not in multi and "\n" not in t["text"]]
    for a in singles:
        if not area_re.match(a["text"]):
            continue
        h = a["h"] or 1.0
        above = [(n["top"] - a["top"], n) for n in singles if n is not a and not area_re.match(n["text"])
                 and abs(n["left"] - a["left"]) <= rule["max_dx_heights"] * h and 0 < n["top"] - a["top"] <= rule["max_dy_heights"] * h]
        name = min(above, key=lambda d: d[0])[1]["text"] if above else None
        found.append({"name": name, "area_text": a["text"], "x": a["x"], "y": a["y"]})
    return [{"id": f"{key}-R{n}", "storey": key, "label_no": n, "name": lab["name"], "area_text": lab["area_text"],
             "px": lab["x"], "py": lab["y"]} for n, lab in enumerate(found, start)]


def room_labels(texts: list[dict], area_re: re.Pattern, key: str, rule: dict) -> list[dict]:
    """The room labels of one storey by the preset's room_label_rule (options()["room_label_rule"])."""
    if rule["rule"] == "area_with_name_above":
        return labels_area_first(texts, area_re, key, rule)
    return labels_of(texts, area_re, key)


def wall_segments_top_level(doc, layers: set[str], flatten: float) -> list[dict]:
    """[{p, q, layer}]: the straight pieces of every top-level model-space entity on `layers` (wall_reader "top_level_paths"):
    lines, polylines (bulges as arcs), arcs, circles, ellipses, splines and HATCH boundary paths, flattened to within
    `flatten` drawing units. Block content is not read."""
    from ezdxf import path as ezpath
    out = []
    for e in doc.modelspace():
        layer = e.dxf.get("layer", "0")
        if layer not in layers:
            continue
        t = e.dxftype()
        try:
            if t == "HATCH":
                paths = list(ezpath.from_hatch(e))
            elif t in ("LINE", "ARC", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ELLIPSE", "SPLINE"):
                paths = [ezpath.make_path(e)]
            else:
                continue
        except (TypeError, ValueError):     # an entity ezdxf cannot turn into a path adds no wall piece
            continue
        for pth in paths:
            pts = [(float(v.x), float(v.y)) for v in pth.flattening(flatten)]
            out += [{"p": a, "q": b, "layer": layer} for a, b in zip(pts, pts[1:]) if a != b]
    return out


def assign(cx: float, cy: float, labels: list[dict], outlines: list, walls_tree, max_dist: float) -> tuple[str | None, str, str]:
    """(room id or None, method, note). labels: dicts with id, px, py (the label's anchor). outlines: shapely Polygons of the
    storey's closed room outlines. walls_tree: STRtree over the wall LineStrings or None."""
    pt = Point(cx, cy)
    inside = sorted((o for o in outlines if o.contains(pt)), key=lambda o: o.area)
    for o in inside:
        held = [lab for lab in labels if o.contains(Point(lab["px"], lab["py"]))]
        if held:
            lab = min(held, key=lambda lb: math.dist((cx, cy), (lb["px"], lb["py"])))
            return lab["id"], "outline", f"inside a closed room outline holding {len(held)} label(s)"
    blocked = 0
    for dist, lab in sorted(((math.dist((cx, cy), (lb["px"], lb["py"])), lb) for lb in labels), key=lambda t: t[0]):
        if dist > max_dist:
            break
        n_walls = (len(walls_tree.query(LineString([(cx, cy), (lab["px"], lab["py"])]), predicate="intersects"))
                   if walls_tree is not None else 0)
        if n_walls:
            blocked += 1
            continue
        return lab["id"], "nearest label", "nearest label, no wall in between" + (f"; {blocked} nearer label(s) behind a wall" if blocked else "")
    if not labels:
        return None, "none", "the storey has no room labels"
    return None, "none", f"no label within {max_dist:.6g} without a wall in between ({blocked} behind a wall)"


def room_outline(lab: dict, labels: list[dict], primary: list[dict], extra: list[dict]) -> dict | None:
    """The smallest polygon around the label anchor that holds no other label of the storey, from `primary` first, then
    `extra`. None when there is none."""
    pt = Point(lab["px"], lab["py"])
    for tier, polys in (("room_polygons", primary), ("extra_outline_layers", extra)):
        cands = [p for p in polys if p["geom"].contains(pt)
                 and sum(1 for o in labels if p["geom"].contains(Point(o["px"], o["py"]))) == 1]
        if cands:
            return dict(min(cands, key=lambda p: p["geom"].area), tier=tier)
    return None


def _exterior(g) -> list:
    if g.geom_type == "MultiPolygon":
        g = max(g.geoms, key=lambda q: q.area)
    return list(g.exterior.coords)


def _unit(v):
    n = math.hypot(*v)
    return (v[0] / n, v[1] / n) if n > 0 else (0.0, 0.0)


def closed_end(arc: dict, leaf_tree, leaf_geoms: list, wall_tree, wall_geoms: list, k: float, cfg: dict) -> tuple[str | None, str]:
    """Which end of the arc is the closed leaf position ('a' or 'b') and how it was found: 'leaf line' (a line from the hinge
    to the OTHER end exists: that is the open leaf), 'along a wall' (only this end's direction from the hinge runs parallel to
    a wall segment near the hinge), or (None, reason)."""
    h = arc["hinge"]
    tol = cfg["leaf_tol_m"] * k
    has_leaf = {}
    for end in ("a", "b"):
        p = arc[end]
        has_leaf[end] = False
        if leaf_tree is not None:
            for i in leaf_tree.query(Point(h).buffer(tol)).tolist():
                (x1, y1), (x2, y2) = leaf_geoms[i].coords[0], leaf_geoms[i].coords[-1]
                if ((math.dist((x1, y1), h) <= tol and math.dist((x2, y2), p) <= tol)
                        or (math.dist((x2, y2), h) <= tol and math.dist((x1, y1), p) <= tol)):
                    has_leaf[end] = True
                    break
    if has_leaf["a"] != has_leaf["b"]:
        return ("b" if has_leaf["a"] else "a"), "leaf line"
    why = "a leaf line to both ends" if has_leaf["a"] else "no leaf line from the hinge"
    if wall_tree is None:
        return None, why + "; no wall segments on this storey"
    # the closed end lies at the far edge of the opening, where the wall goes on; the open end stands in the room
    on_wall = {end: any(wall_geoms[i].distance(Point(arc[end])) <= tol for i in wall_tree.query(Point(arc[end]).buffer(tol)).tolist())
               for end in ("a", "b")}
    if on_wall["a"] != on_wall["b"]:
        return ("a" if on_wall["a"] else "b"), "end on a wall"
    near =[wall_geoms[i] for i in wall_tree.query(Point(h).buffer(cfg["wall_search_m"] * k)).tolist()
            if wall_geoms[i].length >= cfg["wall_min_len_m"] * k]
    s_tol = math.sin(math.radians(cfg["wall_angle_tol_deg"]))
    par = {}
    for end in ("a", "b"):
        u = _unit((arc[end][0] - h[0], arc[end][1] - h[1]))
        par[end] = any(abs(u[0] * w[1] - u[1] * w[0]) <= s_tol
                       for w in (_unit((g.coords[-1][0] - g.coords[0][0], g.coords[-1][1] - g.coords[0][1])) for g in near))
    if par["a"] != par["b"]:
        return ("a" if par["a"] else "b"), "along a wall"
    return None, why + ("; both ends run along a nearby wall" if par["a"] else f"; no wall segment within {cfg['wall_search_m']:g} m runs along either end")


def door_sides(arc: dict, closed: str, labels: list[dict], outlines: list, wall_tree, k: float, max_dist: float,
               probes: list[float]) -> dict:
    """The rooms on both sides of the opening when `closed` is the closed end: probe points from the middle of the opening,
    along the open leaf (the swing side, 'into') and against it ('from'); only labels on that side of the opening line count
    (a probe in the wall gap could otherwise see the room on the other side). Hinge side: left or right of a person walking
    through in the opening direction."""
    h, c = arc["hinge"], arc[closed]
    o = arc["b" if closed == "a" else "a"]
    q = ((h[0] + c[0]) / 2, (h[1] + c[1]) / 2)
    n = _unit((o[0] - h[0], o[1] - h[1]))
    out = {}
    for side, sgn in (("into", 1.0), ("from", -1.0)):
        out[side], out[side + "_method"] = None, "none"
        mine = [lb for lb in labels if sgn * ((lb["px"] - q[0]) * n[0] + (lb["py"] - q[1]) * n[1]) > 0]
        for d in probes:
            x, y = q[0] + sgn * n[0] * d * k, q[1] + sgn * n[1] * d * k
            rid, method, _ = assign(x, y, mine, outlines, wall_tree, max_dist)
            if rid:
                out[side], out[side + "_method"] = rid, method
                break
    left = (-n[1], n[0])
    out["hinge_side"] = "left" if (h[0] - q[0]) * left[0] + (h[1] - q[1]) * left[1] > 0 else "right"
    return out


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def window_groups(segs: list[tuple], k: float, cfg: dict) -> list[list[int]]:
    """Indices of segs [(p, q)] grouped into windows: parallel lines of at least min_width_m whose extents along each other
    overlap by at least half the shorter and that lie within max_depth_m across, plus lines within join_m of a group (the short
    sill ends; two short parallel ends of neighbouring windows never join them)."""
    n = len(segs)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    s_tol = math.sin(math.radians(cfg["parallel_deg"]))
    geo = [LineString([p, q]) for p, q in segs]
    dirs = [_unit((q[0] - p[0], q[1] - p[1])) for p, q in segs]
    lens = [math.dist(p, q) for p, q in segs]
    depth, join, long_ = cfg["max_depth_m"] * k, cfg["join_m"] * k, cfg["min_width_m"] * k
    for i in range(n):
        for j in range(i + 1, n):
            u, w = dirs[i], dirs[j]
            if abs(u[0] * w[1] - u[1] * w[0]) <= s_tol and min(lens[i], lens[j]) >= long_:
                p = segs[i][0]
                t = sorted(((x[0] - p[0]) * u[0] + (x[1] - p[1]) * u[1]) for x in segs[j])
                overlap = min(lens[i], t[1]) - max(0.0, t[0])
                mid = ((segs[j][0][0] + segs[j][1][0]) / 2, (segs[j][0][1] + segs[j][1][1]) / 2)
                off = abs((mid[0] - p[0]) * u[1] - (mid[1] - p[1]) * u[0])
                if overlap >= 0.5 * min(lens[i], lens[j]) and off <= depth:
                    parent[find(j)] = find(i)
            elif geo[i].distance(geo[j]) <= join:
                parent[find(j)] = find(i)
    out: dict[int, list[int]] = {}
    for i in range(n):
        out.setdefault(find(i), []).append(i)
    return sorted(out.values(), key=lambda g: g[0])


def window_opening(segs: list[tuple], idx: list[int], k: float, cfg: dict) -> dict | None:
    """The opening of one window group: {p, q (the opening line, in the middle of the wall), u, n, start, end, cmin, cmax, origin}
    (model units; u along, n across) or None when it has no line long enough."""
    longest = max(idx, key=lambda i: math.dist(*segs[i]))
    p0, q0 = segs[longest]
    u = _unit((q0[0] - p0[0], q0[1] - p0[1]))
    if u[0] < -1e-9 or (abs(u[0]) <= 1e-9 and u[1] < 0):      # a fixed direction: drawing order must not matter
        u = (-u[0], -u[1])
    n = (-u[1], u[0])
    o = p0
    s_tol = math.sin(math.radians(cfg["parallel_deg"]))
    par = []
    for i in idx:
        a, b = segs[i]
        w = _unit((b[0] - a[0], b[1] - a[1]))
        if abs(u[0] * w[1] - u[1] * w[0]) > s_tol:
            continue
        t = sorted(((x[0] - o[0]) * u[0] + (x[1] - o[1]) * u[1]) for x in (a, b))
        c = ((a[0] + b[0]) / 2 - o[0]) * n[0] + ((a[1] + b[1]) / 2 - o[1]) * n[1]
        par.append((t[0], t[1], c))
    if not par:
        return None
    start, end = _median([x[0] for x in par]), _median([x[1] for x in par])
    if end - start < cfg["min_width_m"] * k:
        return None
    et = cfg["edge_tol_m"] * k
    span = [x for x in par if abs(x[0] - start) <= et and abs(x[1] - end) <= et] or par
    cmin, cmax = min(x[2] for x in span), max(x[2] for x in span)
    cm = (cmin + cmax) / 2
    pt = lambda t, c: (o[0] + u[0] * t + n[0] * c, o[1] + u[1] * t + n[1] * c)
    return {"p": pt(start, cm), "q": pt(end, cm), "u": u, "n": n, "o": o, "start": start, "end": end, "cmin": cmin, "cmax": cmax}


def windows_of(segs: list[tuple], key: str, walls: list, wall_ids: list[str], labels: list[dict], outlines: list, wall_tree,
               k: float, max_dist: float, cfg: dict) -> tuple[list[dict], int]:
    """(windows, number of groups left out as narrower than min_width_m): per window its id <storey>-F<n> (top to bottom, left
    to right), the opening line p -> q in the middle of the wall, width and depth in metres, the wall pieces it sits in and
    the rooms on its two sides (a room on one side only: an outer wall)."""
    out, skipped = [], 0
    tol = cfg["wall_tol_m"] * k
    s_tol = math.sin(math.radians(cfg["parallel_deg"]))
    for g in window_groups(segs, k, cfg):
        op = window_opening(segs, g, k, cfg)
        if op is None:
            skipped += 1
            continue
        u, n, o = op["u"], op["n"], op["o"]
        along = lambda x: (x[0] - o[0]) * u[0] + (x[1] - o[1]) * u[1]
        across = lambda x: (x[0] - o[0]) * n[0] + (x[1] - o[1]) * n[1]
        ids = []
        for wid, wg in zip(wall_ids, walls):
            a, b = wg.coords[0], wg.coords[-1]
            w = _unit((b[0] - a[0], b[1] - a[1]))
            if abs(u[0] * w[1] - u[1] * w[0]) > s_tol:
                continue
            if not all(op["cmin"] - tol <= across(x) <= op["cmax"] + tol for x in (a, b)):
                continue
            if any(abs(along(x) - e) <= tol for x in (a, b) for e in (op["start"], op["end"])):
                ids.append(wid)
        mid = ((op["p"][0] + op["q"][0]) / 2, (op["p"][1] + op["q"][1]) / 2)
        half = (op["cmax"] - op["cmin"]) / 2
        rooms = []
        for sgn in (1.0, -1.0):
            mine = [lb for lb in labels if sgn * ((lb["px"] - mid[0]) * n[0] + (lb["py"] - mid[1]) * n[1]) > 0]
            for d in cfg["side_probe_m"]:
                x, y = mid[0] + sgn * n[0] * (half + d * k), mid[1] + sgn * n[1] * (half + d * k)
                rid, _, _ = assign(x, y, mine, outlines, wall_tree, max_dist)
                if rid:
                    if rid not in rooms:
                        rooms.append(rid)
                    break
        out.append({"storey": key, "p": [round(op["p"][0], 6), round(op["p"][1], 6)], "q": [round(op["q"][0], 6), round(op["q"][1], 6)],
                    "width_m": round((op["end"] - op["start"]) / k, 3), "depth_m": round((op["cmax"] - op["cmin"]) / k, 3),
                    "wall_ids": ids, "rooms": rooms, "note": "" if rooms else "no room found on either side within the probe distances"})
    out.sort(key=lambda w: (-round((w["p"][1] + w["q"][1]) / 2 / k, 1), (w["p"][0] + w["q"][0]) / 2))
    return [dict({"id": f"{key}-F{i}"}, **w) for i, w in enumerate(out, 1)], skipped


def checks_of(rooms: list[dict], doors: list[dict], windows: list[dict] | None = None) -> list[Check]:
    """R1-R6 (items carry ids, never a name)."""
    bad = [r for r in rooms if not r.get("id") or not r.get("storey")]
    r1 = Check("R1", "Every room has an id and a storey", UNK if not rooms else (DIFF if bad else MATCH),
               "no room label found: nothing to check" if not rooms else
               f"{len(rooms)} rooms: {len(rooms) - len(bad)} with id and storey, {len(bad)} without",
               [{"room": r.get("id") or "", "status": DIFF} for r in bad])
    lone = [d for d in doors if not d["rooms"]]
    same = [d for d in doors if d.get("opens_into") and d.get("opens_into") == d.get("opens_from")]
    bad2 = lone + same
    r2 = Check("R2", "Every door connects at least one room (and never a room to itself)", UNK if not doors else (DIFF if bad2 else MATCH),
               "no door swing found on the door layers: nothing to check" if not doors else
               f"{len(doors)} doors: {len(doors) - len(bad2)} connect at least one room, {len(lone)} connect none, {len(same)} the same room on both sides",
               [{"door": d["id"], "status": DIFF} for d in bad2])
    no = [r for r in rooms if not r["outline"]]
    r3 = Check("R3", "Every room has an outline", UNK if (no or not rooms) else MATCH,
               "no room: nothing to measure" if not rooms else f"{len(rooms) - len(no)} of {len(rooms)} rooms have an outline",
               [{"room": r["id"], "status": UNK} for r in no])
    und = [d for d in doors if d["closed_end"] is None]
    r4 = Check("R4", "Every door's swing is determined", UNK if (und or not doors) else MATCH,
               f"{len(und)} of {len(doors)} doors: swing could not be determined" if und else
               (f"every one of {len(doors)} doors has a determined swing" if doors else "no door found: nothing to check"),
               [{"door": d["id"], "reason": d["swing_note"], "status": UNK} for d in und])
    ol = [r for r in rooms if r["outline"]]
    nowall = [r for r in ol if not r["wall_ids"]]
    r5 = Check("R5", "Every room with an outline has a wall segment along it", UNK if (nowall or not ol) else MATCH,
               "no room has an outline: nothing to check" if not ol else
               f"{len(ol)} rooms with an outline: {len(ol) - len(nowall)} with wall segments along it",
               [{"room": r["id"], "status": UNK} for r in nowall])
    ws = windows or []
    lost = [w for w in ws if not w["rooms"]]
    r6 = Check("R6", "Every window lies in a wall of a room", UNK if (lost or not ws) else MATCH,
               "no window found on the window layers: the suggestions cannot keep clear of windows" if not ws else
               f"{len(ws)} windows: {len(ws) - len(lost)} in a wall of a room, {len(lost)} with no room on either side",
               [{"window": w["id"], "status": UNK} for w in lost])
    return [r1, r2, r3, r4, r5, r6]


# ---- the extraction ---------------------------------------------------------------------------------------------------------

def mm_per_unit(doc) -> float | None:
    """Millimetres per drawing unit from $INSUNITS (None when unitless or unknown)."""
    from ezdxf import units
    u = doc.units
    if not u:
        return None
    try:
        return units.conversion_factor(u, units.MM)
    except (KeyError, ValueError, TypeError):
        return None


def extract(doc, pre: dict) -> dict:
    """{"mm_per_unit", "k" (units per metre), "layers": layer_info, "storeys": [{key, label, layers, rooms, doors, walls,
    checks}], "status": PASS/FAIL/INDETERMINATE, "unknowns", "failures"}."""
    names = [lay.dxf.name for lay in doc.layers]
    info = layer_info(names, pre)
    mm = mm_per_unit(doc)
    out = {"mm_per_unit": mm, "k": None, "layers": info, "storeys": [], "status": "INDETERMINATE", "failures": [], "unknowns": []}
    if not mm:
        out["unknowns"].append("drawing units unknown ($INSUNITS unitless): distances in metres cannot be applied")
        return out
    k = 1000.0 / mm
    out["k"] = k
    opt = options(pre)
    ing = ingest(doc, info, opt["text_reader"])
    if opt["wall_reader"]["reader"] == "top_level_paths":
        wall_layers = {n for n, v in info.items() if v["base"] in pre["layers"]["walls"]}
        ing["segments"] = ([s for s in ing["segments"] if s["layer"] not in wall_layers]
                           + wall_segments_top_level(doc, wall_layers, opt["wall_reader"]["flatten_m"] * k))
    exclude = set(pre.get("exclude_status") or [])
    area_re = re.compile(pre["label_area_regex"])
    wet_re = re.compile(pre["wet_room_pattern"])
    L, dcfg, wcfg = pre["layers"], pre["doors"], pre["walls"]
    max_dist = pre["label_max_dist_m"] * k
    keys = sorted({v["storey"] for v in info.values() if v["storey"]})
    stat = lambda lay: (info.get(lay) or {}).get("status")
    base = lambda lay: (info.get(lay) or {}).get("base", lay)
    storey_of = lambda lay: (info.get(lay) or {}).get("storey")
    ok = lambda lay: stat(lay) not in exclude
    all_checks: list[Check] = []
    for key in keys:
        here = lambda lay: storey_of(lay) == key and ok(lay)
        labels = room_labels([t for t in ing["texts"] if here(t["layer"]) and base(t["layer"]) in L["room_labels"]], area_re, key,
                             opt["room_label_rule"])
        primary = [p for p in ing["polygons"] if here(p["layer"]) and base(p["layer"]) in L["room_polygons"]]
        extra = [p for p in ing["polygons"] if here(p["layer"]) and base(p["layer"]) in (pre.get("extra_outline_layers") or [])]
        wall_rows = [s for s in ing["segments"] if here(s["layer"]) and base(s["layer"]) in L["walls"]]
        walls = [LineString([s["p"], s["q"]]) for s in wall_rows]
        tree = STRtree(walls) if walls else None
        outlines = [p["geom"] for p in primary]
        wall_ids = [f"{key}-W{i}" for i in range(1, len(walls) + 1)]
        bounding: dict[int, list[str]] = {}
        rooms = []
        for lab in labels:
            o = room_outline(lab, labels, primary, extra)
            r = {"id": lab["id"], "storey": key, "label_no": lab["label_no"], "name": lab["name"], "area_text": lab["area_text"],
                 "wet": bool(lab["name"] and wet_re.match(lab["name"])), "anchor": [round(lab["px"], 6), round(lab["py"], 6)]}
            if o is None:
                r.update(outline=None, outline_note=NO_OUTLINE, area_outline_m2=None, wall_ids=[])
            else:
                g = o["geom"]
                ring = _exterior(g.simplify(pre["outline_simplify_m"] * k))
                r.update(outline=[[round(x, 6), round(y, 6)] for x, y in ring], outline_note=f"on {base(o['layer'])} ({o['tier']})",
                         area_outline_m2=round(g.area / (k * k), 3))
                band = g.boundary.buffer(wcfg["room_tol_m"] * k)
                ids = []
                if tree is not None:
                    for i in sorted(tree.query(band).tolist()):
                        seg = walls[i]
                        if seg.length > 0 and seg.intersection(band).length >= wcfg["min_overlap_share"] * seg.length:
                            ids.append(wall_ids[i])
                            bounding.setdefault(i, []).append(r["id"])
                r["wall_ids"] = ids
            r["doors"] = []
            rooms.append(r)
        walls_out = [{"id": wall_ids[i], "base": base(row["layer"]), "status": stat(row["layer"]) or "Bestand",
                      "p": [round(row["p"][0], 6), round(row["p"][1], 6)], "q": [round(row["q"][0], 6), round(row["q"][1], 6)],
                      "rooms": bounding.get(i, [])} for i, row in enumerate(wall_rows)]
        # doors
        r_lo, r_hi = dcfg["radius_m"]
        s_lo, s_hi = dcfg["sweep_deg"]
        skipped = Counter()
        mine = []
        for a in ing["arcs"]:
            if storey_of(a["layer"]) != key or base(a["layer"]) not in L["doors"]:
                continue
            if not ok(a["layer"]):
                skipped["excluded status"] += 1
            elif not (r_lo <= a["r"] / k <= r_hi):
                skipped["radius outside doors.radius_m"] += 1
            elif not (s_lo <= a["sweep"] <= s_hi):
                skipped["sweep outside doors.sweep_deg"] += 1
            else:
                mine.append(a)
        mine.sort(key=lambda a: (-round(a["hinge"][1] / k, 1), a["hinge"][0]))
        leaf = [LineString([s["p"], s["q"]]) for s in ing["segments"] if storey_of(s["layer"]) == key and base(s["layer"]) in L["doors"]]
        leaf_tree = STRtree(leaf) if leaf else None
        doors = []
        for n, a in enumerate(mine, 1):
            ce, how = closed_end(a, leaf_tree, leaf, tree, walls, k, dcfg)
            d = {"id": f"{key}-D{n}", "storey": key, "width_m": round(a["r"] / k, 3),
                 "hinge": [round(a["hinge"][0], 6), round(a["hinge"][1], 6)],
                 "ends": {e2: [round(a[e2][0], 6), round(a[e2][1], 6)] for e2 in ("a", "b")},
                 "closed_end": ce, "swing_method": how if ce else "could not tell", "swing_note": "" if ce else how}
            if ce is not None:
                sd = door_sides(a, ce, labels, outlines, tree, k, max_dist, dcfg["side_probe_m"])
                d.update(opens_into=sd["into"], opens_from=sd["from"], hinge_side=sd["hinge_side"])
                note = ""
            else:
                both = [door_sides(a, e2, labels, outlines, tree, k, max_dist, dcfg["side_probe_m"]) for e2 in ("a", "b")]
                pairs = [frozenset(x for x in (b2["into"], b2["from"]) if x) for b2 in both]
                if pairs[0] == pairs[1] and pairs[0]:
                    into = both[0]["into"] if both[0]["into"] == both[1]["into"] else None
                    d.update(opens_into=into, opens_from=None if into is None else both[0]["from"], hinge_side=None, rooms_both=sorted(pairs[0]))
                    note = "swing undetermined: both possible openings give the same rooms"
                else:
                    d.update(opens_into=None, opens_from=None, hinge_side=None)
                    note = "swing undetermined and the two possible openings give different rooms: rooms could not tell"
            rs = d.pop("rooms_both", None) or [x for x in (d.get("opens_into"), d.get("opens_from")) if x]
            d["rooms"] = rs
            d["leads_to"] = NO_ROOM if ce is not None and len(rs) == 1 else ""
            d["note"] = note or ("" if rs else "no room found on either side within the probe distances")
            doors.append(d)
        tol = dcfg["double_tol_m"] * k
        for i, d1 in enumerate(doors):
            for j in range(i + 1, len(doors)):
                d2 = doors[j]
                if d1["closed_end"] and d2["closed_end"] and math.dist(mine[i][d1["closed_end"]], mine[j][d2["closed_end"]]) <= tol:
                    d1["pair"], d2["pair"] = d2["id"], d1["id"]
        by_id = {r["id"]: r for r in rooms}
        for d in doors:
            for rid in d["rooms"]:
                other = [x for x in d["rooms"] if x != rid]
                by_id[rid]["doors"].append({"door": d["id"], "to": other[0] if other else (NO_ROOM if d["leads_to"] else "could not tell")})
        win_segs = [(s["p"], s["q"]) for s in ing["segments"] if here(s["layer"]) and base(s["layer"]) in (L.get("windows") or [])]
        windows, win_skipped = windows_of(win_segs, key, walls, wall_ids, labels, outlines, tree, k, max_dist, pre["windows"])
        checks = checks_of(rooms, doors, windows)
        all_checks += checks
        out["storeys"].append({"key": key, "label": storey_label(key, pre), "layers": sorted(n for n, v in info.items() if v["storey"] == key),
                               "rooms": rooms, "doors": doors, "walls": walls_out, "windows": windows, "door_arcs_skipped": dict(skipped),
                               "window_groups_skipped": win_skipped, "checks": [c.as_dict() for c in checks]})
    if not keys:
        out["unknowns"].append("no storey: no layer belongs to a storey")
    accepted = pre.get("accepted_could_not_tell") or {}
    out["failures"] = [f"{c.id} {c.title}: {c.detail}" for c in all_checks if c.status == DIFF]
    out["unknowns"] += [f"{c.id} {c.title}: {c.detail}" for c in all_checks if c.status == UNK and c.id not in accepted]
    out["status"] = "FAIL" if out["failures"] else ("INDETERMINATE" if out["unknowns"] else "PASS")
    return out
