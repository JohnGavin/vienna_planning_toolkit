"""Fittings recognised by SHAPE in DXF geometry (vpt/fittings.py drives it; every rule, range and tolerance is in
presets/fittings.json, block "shape_rules").

Many drawings have no fitting objects: WCs, basins, baths and sinks are plain lines, arcs, circles, polylines and hatches on a
sanitary or kitchen layer, next to furniture. This module turns that geometry into candidate SYMBOLS and classifies each with
data-driven rules; nothing here is tuned to one drawing.

    primitives(msp, info, layers, flatten)   model-space entities on the fitting layers (INSERTs exploded into world coordinates),
                                             one Prim each
    segment(prims, join_tol, contain_max)    groups of primitives that form one symbol: connected when their geometry comes within
                                             join_tol of each other, or when one lies inside the convex hull of another that is no
                                             longer than contain_max (a drain circle inside a basin)
    features(prims, k, cfg)                  per symbol: oriented (minimum-area) box w >= d in metres, axis box, counts by primitive
                                             type, closed loops (faces of the linework), circles and radii, arc share, corner-to-corner
                                             diagonals, hull area, centroid
    texts_inside(feat, texts, tol)           texts whose insertion point lies inside the symbol's box (cues for rules, never reported)
    classify(f, texts, rules)                the fitting types whose rule the symbol satisfies: one -> that type; none -> "unrecognised";
                                             more than one -> "ambiguous" (listed, never resolved by guessing)

Units: the rules are in metres; drawing units are converted with k (drawing units per metre, from $INSUNITS).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np
import shapely
from ezdxf import path as ezpath
from ezdxf.math import Bezier3P, Bezier4P
from ezdxf.path import Command
from shapely import STRtree
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.ops import polygonize, unary_union

GEOM_TYPES = ("LINE", "ARC", "CIRCLE", "ELLIPSE", "LWPOLYLINE", "POLYLINE", "SPLINE", "HATCH")
EXPLODE_DEPTH = 4
UNRECOGNISED, AMBIGUOUS = "unrecognised", "ambiguous"


@dataclass
class Prim:
    idx: int
    storey: str            # storey key (or "all")
    status: str            # "none" / "Neubau" / "Abbruch"
    base: str              # base layer name
    type: str              # DXF type of the drawn entity (for an exploded INSERT: the inner entity's type)
    handle: str
    in_block: bool
    lines: list            # flattened pieces: list of [(x, y), ...] (drawing units)
    straight: list         # straight pieces (x1, y1, x2, y2)
    length: float
    curved_length: float
    radius: float | None   # CIRCLE only
    closed_paths: int
    geom: object = None    # shapely (Multi)LineString of `lines`


@dataclass
class Symbol:
    id: str
    storey: str
    status: str
    prims: list
    feat: dict = field(default_factory=dict)
    texts: list = field(default_factory=list)   # texts inside (cue rules only; never written to any output)
    kind: str = UNRECOGNISED                     # fitting type, "unrecognised" or "ambiguous"
    matches: list = field(default_factory=list)
    room: str | None = None
    method: str = ""
    method_note: str = ""


# ---- primitives -------------------------------------------------------------------------------------------

def _bezier_len(pts) -> float:
    b = Bezier3P(pts) if len(pts) == 3 else Bezier4P(pts)
    a = list(b.approximate(16))
    return sum(math.dist((p.x, p.y), (q.x, q.y)) for p, q in zip(a, a[1:]))


def _walk(p, flatten: float):
    """(flattened pieces, straight pieces, total length, curved length, closed sub-paths) of one ezdxf Path."""
    lines, straight, total, curved, closed = [], [], 0.0, 0.0, 0
    for sp in (p.sub_paths() if p.has_sub_paths else [p]):
        pts = [(v.x, v.y) for v in sp.flattening(flatten)]
        if sp.is_closed and len(pts) >= 3:
            closed += 1
            pts[-1] = pts[0]          # exactly closed (a flattened curve can end a rounding error away from its start)
        if len(pts) >= 2:
            lines.append(pts)
        start = sp.start
        for cmd in sp.commands():
            end = cmd.end
            if cmd.type == Command.LINE_TO:
                d = math.dist((start.x, start.y), (end.x, end.y))
                if d > 0:
                    straight.append((start.x, start.y, end.x, end.y))
                total += d
            elif cmd.type == Command.CURVE3_TO:
                d = _bezier_len([start, cmd.ctrl, end])
                total += d
                curved += d
            elif cmd.type == Command.CURVE4_TO:
                d = _bezier_len([start, cmd.ctrl1, cmd.ctrl2, end])
                total += d
                curved += d
            start = end
    return lines, straight, total, curved, closed


def _paths(e):
    if e.dxftype() == "HATCH":
        return list(ezpath.from_hatch(e))
    return [ezpath.make_path(e)]


def explode(e, layer_of_insert: str | None, depth: int):
    """(entity, effective layer, in_block) for a model-space entity; INSERTs exploded (nested up to EXPLODE_DEPTH). An entity on
    layer 0 inside a block takes the layer of its INSERT (the DXF rule)."""
    layer = e.dxf.get("layer", "0")
    if layer_of_insert is not None and layer == "0":
        layer = layer_of_insert
    if e.dxftype() == "INSERT":
        if depth >= EXPLODE_DEPTH:
            return
        try:
            inner = list(e.virtual_entities())
        except Exception:     # noqa: BLE001 - non-uniform scaling etc.: the insert contributes nothing
            return
        for v in inner:
            yield from explode(v, layer, depth + 1)
        return
    yield e, layer, depth > 0


def primitives(msp, info: dict, fitting_layers: list[str], flatten: float) -> tuple[list[Prim], dict]:
    """Primitives on the fitting layers (by BASE name) of every storey; `info` is plan_extract.layer_info's {layer: {storey, status,
    base}}. Returns (prims, skipped) where skipped counts what was not used, per DXF type."""
    prims: list[Prim] = []
    skipped: dict[str, int] = {}
    fit = set(fitting_layers)
    for top in msp:
        i0 = info.get(top.dxf.get("layer", "0"))
        if i0 is None or i0["base"] not in fit:      # an INSERT counts by its own layer (its layer-0 content takes that layer)
            continue
        for e, layer, in_block in explode(top, None, 0):
            i = info.get(layer)
            if i is None or i["base"] not in fit:
                skipped["block content on a non-fitting layer"] = skipped.get("block content on a non-fitting layer", 0) + 1
                continue
            t = e.dxftype()
            if t not in GEOM_TYPES:
                skipped[t] = skipped.get(t, 0) + 1
                continue
            try:
                paths = _paths(e)
            except (TypeError, ValueError, AttributeError):
                skipped[f"{t} (unreadable)"] = skipped.get(f"{t} (unreadable)", 0) + 1
                continue
            lines, straight, total, curved, closed = [], [], 0.0, 0.0, 0
            for p in paths:
                ln, st, tl, cv, cl = _walk(p, flatten)
                lines += ln
                straight += st
                total += tl
                curved += cv
                closed += cl
            if not lines:
                skipped[f"{t} (no extent)"] = skipped.get(f"{t} (no extent)", 0) + 1
                continue
            geom = MultiLineString(lines) if len(lines) > 1 else LineString(lines[0])
            prims.append(Prim(len(prims), i["storey"] or "?", i["status"] or "none", i["base"], t, e.dxf.get("handle", "") or "",
                              in_block, lines, straight, total, curved, float(e.dxf.radius) if t == "CIRCLE" else None, closed, geom))
    return prims, skipped


# ---- segmentation -----------------------------------------------------------------------------------------

class _UF:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, a: int) -> int:
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def segment(prims: list[Prim], join_tol: float, contain_max: float) -> list[list[Prim]]:
    """Connected groups of primitives (drawing units). Two primitives join when (1) their geometries come within join_tol of each
    other, or (2) one lies inside the convex hull (grown by join_tol) of the other and that other's axis box is no longer than
    contain_max on its long side (a drain circle inside a basin; not every item inside a room-sized outline)."""
    if not prims:
        return []
    geoms = [p.geom for p in prims]
    tree = STRtree(geoms)
    uf = _UF(len(prims))
    a, b = tree.query(geoms, predicate="dwithin", distance=join_tol)
    for i, j in zip(a.tolist(), b.tolist()):
        if i != j:
            uf.union(i, j)
    for i, g in enumerate(geoms):
        x0, y0, x1, y1 = g.bounds
        if max(x1 - x0, y1 - y0) > contain_max:
            continue
        hull = g.convex_hull
        if hull.area <= 0:
            continue
        for j in tree.query(hull.buffer(join_tol), predicate="contains").tolist():
            if j != i:
                uf.union(i, j)
    groups: dict[int, list[Prim]] = {}
    for i, p in enumerate(prims):
        groups.setdefault(uf.find(i), []).append(p)
    return list(groups.values())


# ---- features -----------------------------------------------------------------------------------------------

def _obb(geom):
    """(w, d, angle of the long side in degrees, corner list) of the minimum-area rectangle, w >= d."""
    with np.errstate(divide="ignore", invalid="ignore"):      # GEOS sets the floating-point flags on exact rectangles; the result is right
        r = geom.minimum_rotated_rectangle
    if isinstance(r, Polygon) and not r.is_empty:
        c = list(r.exterior.coords)[:4]
        e1, e2 = math.dist(c[0], c[1]), math.dist(c[1], c[2])
        long_a, long_b = (c[0], c[1]) if e1 >= e2 else (c[1], c[2])
        ang = math.degrees(math.atan2(long_b[1] - long_a[1], long_b[0] - long_a[0])) % 180.0
        return max(e1, e2), min(e1, e2), ang, c
    if isinstance(r, LineString):
        c = list(r.coords)
        ang = math.degrees(math.atan2(c[-1][1] - c[0][1], c[-1][0] - c[0][0])) % 180.0
        return r.length, 0.0, ang, [c[0], c[-1], c[-1], c[0]]
    return 0.0, 0.0, 0.0, []


def features(prims: list[Prim], k: float, cfg: dict) -> dict:
    """Features of one symbol in METRES (k = drawing units per metre). See the module docstring."""
    lines = [LineString(pts) for p in prims for pts in p.lines if len(pts) >= 2]
    ml = MultiLineString(lines)
    w, d, ang, corners = _obb(ml)
    x0, y0, x1, y1 = ml.bounds
    hull = ml.convex_hull
    counts: dict[str, int] = {}
    for p in prims:
        counts[p.type] = counts.get(p.type, 0) + 1
    non_hatch = [p for p in prims if p.type != "HATCH"]
    total = sum(p.length for p in non_hatch)
    curved = sum(p.curved_length for p in non_hatch)
    radii = sorted(p.radius / k for p in prims if p.radius is not None)
    min_face = cfg["min_face_m2"] * k * k
    try:
        snapped = shapely.set_precision(MultiLineString(lines), cfg["snap_m"] * k)    # near-coincident ends meet, so rings close
        faces = [f for f in polygonize(unary_union(snapped)) if f.area >= min_face]
    except Exception:     # noqa: BLE001 - degenerate linework (GEOS topology error): no faces counted, recorded as -1
        faces = None
    diag = math.hypot(w, d)
    tol = cfg["diagonal_corner_tol_frac"] * diag
    n_diag = 0
    if len(corners) == 4 and d > 0:
        for (ax, ay, bx, by) in (s for p in non_hatch for s in p.straight):
            ends = ((ax, ay), (bx, by))
            for c0, c1 in ((corners[0], corners[2]), (corners[1], corners[3])):
                if ((math.dist(ends[0], c0) <= tol and math.dist(ends[1], c1) <= tol)
                        or (math.dist(ends[0], c1) <= tol and math.dist(ends[1], c0) <= tol)):
                    n_diag += 1
                    break
    c = hull.centroid if not hull.is_empty else ml.centroid
    return {
        "w_m": round(w / k, 3), "d_m": round(d / k, 3), "aspect": round(w / d, 3) if d > 0 else None, "angle_deg": round(ang, 1),
        "bbox_w_m": round((x1 - x0) / k, 3), "bbox_h_m": round((y1 - y0) / k, 3),
        "primitives": len(prims), "by_type": counts, "closed_paths": sum(p.closed_paths for p in prims),
        "closed_loops": len(faces) if faces is not None else -1,
        "circles": len(radii), "circle_radii_m": [round(r, 3) for r in radii],
        "small_circles": sum(1 for r in radii if r <= cfg["small_circle_max_r_m"]),
        "arc_share": round(curved / total, 3) if total > 0 else 0.0, "diagonal_lines": n_diag,
        "curved_primitives": sum(1 for p in non_hatch if p.curved_length > 0),
        "hull_area_m2": round(hull.area / (k * k), 4) if not hull.is_empty else 0.0,
        "hull_fill": round(hull.area / (w * d), 3) if w * d > 0 else None,
        "cx": c.x, "cy": c.y, "xmin": x0, "ymin": y0, "xmax": x1, "ymax": y1,
        "corners": [[round(x, 4), round(y, 4)] for x, y in corners],
    }


def texts_inside(feat: dict, texts: list, tol: float) -> list[str]:
    """Texts (dicts with x, y, text) whose insertion point lies inside the symbol's oriented box (grown by tol)."""
    if len(feat["corners"]) != 4 or feat["d_m"] == 0:
        return []
    poly = Polygon(feat["corners"]).buffer(tol)
    return [t["text"] for t in texts if feat["xmin"] - tol <= t["x"] <= feat["xmax"] + tol and feat["ymin"] - tol <= t["y"] <= feat["ymax"] + tol
            and poly.contains(Point(t["x"], t["y"]))]


# ---- classification -----------------------------------------------------------------------------------------

def _cond(c: dict, f: dict, texts: list[str]) -> bool:
    name = c["feature"]
    if name == "text_cue":
        rx = re.compile(c["regex"])
        return any(rx.search(t) for t in texts)
    if name == "circles" and "r_m" in c:
        lo, hi = c["r_m"]
        v = sum(1 for r in f["circle_radii_m"] if lo <= r <= hi)
    else:
        v = f.get(name)
        if v is None:
            return False
    return (c.get("min") is None or v >= c["min"]) and (c.get("max") is None or v <= c["max"])


def rule_matches(rule: dict, f: dict, texts: list[str]) -> bool:
    (wl, wh), (dl, dh) = rule["w_m"], rule["d_m"]
    if not (wl <= f["w_m"] <= wh and dl <= f["d_m"] <= dh):
        return False
    if rule.get("max_aspect") is not None and (f["aspect"] is None or f["aspect"] > rule["max_aspect"]):
        return False
    if not all(_cond(c, f, texts) for c in rule.get("all", [])):
        return False
    anys = rule.get("any", [])
    return not anys or any(_cond(c, f, texts) for c in anys)


def classify(f: dict, texts: list[str], rules: list[dict]) -> tuple[str, list[str]]:
    """(kind, matching rule types): one match -> its type, none -> unrecognised, more -> ambiguous."""
    hits = [r["type"] for r in rules if rule_matches(r, f, texts)]
    if len(hits) == 1:
        return hits[0], hits
    return (AMBIGUOUS if hits else UNRECOGNISED), hits
