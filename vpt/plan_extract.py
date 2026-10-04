"""Rooms, doors and walls per storey of a DXF: the input for the electrical editor's placement suggestions and room lookup.

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
Checks (match / different / could-not-tell; could-not-tell is never a match):
    R1 every room has an id and a storey      R2 every door connects at least one room (never a room to itself)
    R3 every room has an outline              R4 every door's swing is determined
    R5 every room with an outline has a wall segment along it
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


def _text_of(e) -> tuple[str, tuple[float, float], float] | None:
    t = e.dxftype()
    if t == "MTEXT":
        p = e.dxf.insert
        return e.plain_text(), (float(p.x), float(p.y)), float(e.dxf.get("char_height", 0) or 0)
    if t == "TEXT":
        p = e.dxf.align_point if e.dxf.hasattr("align_point") and (e.dxf.get("halign", 0) or e.dxf.get("valign", 0)) else e.dxf.insert
        return e.dxf.text, (float(p.x), float(p.y)), float(e.dxf.get("height", 0) or 0)
    return None


def ingest(doc, info: dict[str, dict]) -> dict:
    """Model-space content by kind: texts [{text, x, y, h, layer}], polygons [{geom, layer, handle}], segments [{p, q, layer}],
    arcs [{hinge, a, b, r, sweep, layer, handle}] (world coordinates)."""
    from ezdxf.math import Vec3
    texts, polys, segs, arcs = [], [], [], []
    for top in doc.modelspace():
        for e, layer in _explode(top, top.dxf.get("layer", "0")):
            t = e.dxftype()
            handle = top.dxf.get("handle", "") or ""
            if t in ("MTEXT", "TEXT"):
                tx = _text_of(e)
                if tx and tx[0].strip():
                    texts.append({"text": tx[0], "x": tx[1][0], "y": tx[1][1], "h": tx[2], "layer": layer})
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


def checks_of(rooms: list[dict], doors: list[dict]) -> list[Check]:
    """R1-R5 (items carry ids, never a name)."""
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
    return [r1, r2, r3, r4, r5]


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
    ing = ingest(doc, info)
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
        labels = labels_of([t for t in ing["texts"] if here(t["layer"]) and base(t["layer"]) in L["room_labels"]], area_re, key)
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
        checks = checks_of(rooms, doors)
        all_checks += checks
        out["storeys"].append({"key": key, "label": storey_label(key, pre), "layers": sorted(n for n, v in info.items() if v["storey"] == key),
                               "rooms": rooms, "doors": doors, "walls": walls_out, "door_arcs_skipped": dict(skipped),
                               "checks": [c.as_dict() for c in checks]})
    if not keys:
        out["unknowns"].append("no storey: no layer belongs to a storey")
    accepted = pre.get("accepted_could_not_tell") or {}
    out["failures"] = [f"{c.id} {c.title}: {c.detail}" for c in all_checks if c.status == DIFF]
    out["unknowns"] += [f"{c.id} {c.title}: {c.detail}" for c in all_checks if c.status == UNK and c.id not in accepted]
    out["status"] = "FAIL" if out["failures"] else ("INDETERMINATE" if out["unknowns"] else "PASS")
    return out
