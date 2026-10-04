#!/usr/bin/env python3
"""Validate a flat drawing (DXF) against the structural rules of the toolkit.

Checks are read from the DXF itself (not from the generator), so the same
validator works on any drawing that follows the layer conventions in a preset.

Exit codes: 0 PASS, 1 FAIL, 2 usage, 3 INDETERMINATE (drawing unreadable).

Usage:
    python3 tools/validate_flat.py samples/synthetic_flat.dxf \
        --preset presets/synthetic_flat.json [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import ezdxf
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
from synthetic_flat import layer_name, load_preset  # noqa: E402

EPS = 1e-6
AREA_RE = re.compile(r"([0-9]+(?:[.,][0-9]+)?)\s*m²")


def _close(a, b, tol=1e-5) -> bool:
    return math.dist((a[0], a[1]), (b[0], b[1])) <= tol


def _entities(doc, layer: str, types: str):
    return list(doc.modelspace().query(f'{types}[layer=="{layer}"]'))


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------
def room_outlines(doc, preset) -> list[dict]:
    out = []
    for pl in _entities(doc, layer_name(preset, "zone"), "LWPOLYLINE"):
        pts = [(p[0], p[1]) for p in pl.get_points("xy")]
        closed = bool(pl.closed) or (len(pts) > 2 and _close(pts[0], pts[-1]))
        poly = Polygon(pts) if len(pts) >= 3 else Polygon()
        out.append({"handle": pl.dxf.handle, "closed": closed, "poly": poly})
    return out


def room_labels(doc, preset) -> list[dict]:
    out = []
    for mt in _entities(doc, layer_name(preset, "room_stamp"), "MTEXT"):
        text = mt.plain_text()
        m = AREA_RE.search(text)
        area = float(m.group(1).replace(",", ".")) if m else None
        out.append({"name": text.split("\n")[0].strip(), "area": area,
                    "at": (mt.dxf.insert.x, mt.dxf.insert.y)})
    return out


def wall_like_lines(doc, preset) -> list[LineString]:
    roles = [r for r in preset["layers"] if r.startswith("wall_")] + ["window", "door"]
    lines = []
    for role in roles:
        for ln in _entities(doc, layer_name(preset, role), "LINE"):
            a, b = ln.dxf.start, ln.dxf.end
            if math.dist((a.x, a.y), (b.x, b.y)) > EPS:
                lines.append(LineString([(round(a.x, 6), round(a.y, 6)),
                                         (round(b.x, 6), round(b.y, 6))]))
    return lines


def outer_fill(doc, preset) -> Polygon | None:
    """Polygon enclosed by the outermost closed wall/opening line ring."""
    lines = wall_like_lines(doc, preset)
    if not lines:
        return None
    faces = list(polygonize(unary_union(lines)))
    if not faces:
        return None
    merged = unary_union(faces)
    parts = [merged] if merged.geom_type == "Polygon" else list(merged.geoms)
    biggest = max(parts, key=lambda p: Polygon(p.exterior).area)
    return Polygon(biggest.exterior)


# --------------------------------------------------------------------------
# checks: each returns a list of problem strings (empty = pass)
# --------------------------------------------------------------------------
def check_layers(doc, preset) -> list[str]:
    rx = re.compile(preset["layer_name_regex"])
    names = [lay.dxf.name for lay in doc.layers]
    problems = [f"layer name does not match pattern: {n!r}"
                for n in names if n not in ("0", "Defpoints") and not rx.match(n)]
    for role in preset["layers"]:
        if layer_name(preset, role) not in names:
            problems.append(f"missing layer for role {role}: {layer_name(preset, role)}")
    return problems


def check_rooms(doc, preset) -> list[str]:
    exp = preset["expectations"]
    outlines, labels = room_outlines(doc, preset), room_labels(doc, preset)
    problems = []
    lo, hi = exp["room_count"]
    if not lo <= len(outlines) <= hi:
        problems.append(f"room count {len(outlines)} outside [{lo}, {hi}]")
    for o in outlines:
        if not o["closed"]:
            problems.append(f"room outline {o['handle']} is not closed")
        if not o["poly"].is_valid or o["poly"].area <= 0:
            problems.append(f"room outline {o['handle']} is not a valid polygon")
    for lab in labels:
        hits = [o for o in outlines if o["poly"].is_valid and o["poly"].contains(Point(lab["at"]))]
        if len(hits) != 1:
            problems.append(f"label {lab['name']!r} lies inside {len(hits)} outlines (want 1)")
            continue
        area = hits[0]["poly"].area
        if lab["area"] is None:
            problems.append(f"label {lab['name']!r} has no area in m²")
        elif abs(lab["area"] - area) / area > exp["label_area_tolerance"]:
            problems.append(f"label {lab['name']!r} area {lab['area']} vs outline {area:.3f}")
    for o in outlines:
        n = sum(1 for lab in labels if o["poly"].is_valid and o["poly"].contains(Point(lab["at"])))
        if n != 1:
            problems.append(f"room outline {o['handle']} holds {n} labels (want 1)")
    total = sum(o["poly"].area for o in outlines if o["poly"].is_valid)
    lo, hi = exp["total_area_m2"]
    if not lo <= total <= hi:
        problems.append(f"total room area {total:.2f} outside [{lo}, {hi}]")
    return problems


def door_sides(doc, preset) -> tuple[list[dict], list[str]]:
    """Reconstruct each door from its arc + lines and find what it connects."""
    layer = layer_name(preset, "door")
    arcs = _entities(doc, layer, "ARC")
    lines = [((ln.dxf.start.x, ln.dxf.start.y), (ln.dxf.end.x, ln.dxf.end.y))
             for ln in _entities(doc, layer, "LINE")]
    outlines = [o for o in room_outlines(doc, preset) if o["poly"].is_valid]
    labels = room_labels(doc, preset)

    def room_name(o):
        for lab in labels:
            if o["poly"].contains(Point(lab["at"])):
                return lab["name"]
        return o["handle"]

    fill = outer_fill(doc, preset)
    problems, doors = [], []
    if not arcs:
        problems.append("no door arcs found")
    for arc in arcs:
        h = (arc.dxf.center.x, arc.dxf.center.y)
        r = arc.dxf.radius
        e1 = (arc.start_point.x, arc.start_point.y)
        e2 = (arc.end_point.x, arc.end_point.y)
        tag = f"door arc {arc.dxf.handle} at ({h[0]:.2f},{h[1]:.2f})"
        sweep = (arc.dxf.end_angle - arc.dxf.start_angle) % 360
        if abs(sweep - 90) > 1e-3:
            problems.append(f"{tag}: sweep {sweep:.2f}° (want 90)")
        leaf = closed = None
        for a, b in lines:
            for p, q in ((a, b), (b, a)):
                if _close(p, h) and (_close(q, e1) or _close(q, e2)):
                    other = e2 if _close(q, e1) else e1
                    if any(_close(t0, h) and _close(t1, other) or _close(t1, h) and _close(t0, other)
                           for t0, t1 in lines):
                        leaf, closed = q, other
        if leaf is None:
            problems.append(f"{tag}: no leaf line + threshold line matching the arc")
            continue
        width = math.dist(h, closed)  # threshold = clear opening width
        if abs(r - width) > 1e-5:
            problems.append(f"{tag}: arc radius {r:.3f} != door width {width:.3f}")
        if abs(math.dist(h, leaf) - r) > 1e-5:
            problems.append(f"{tag}: leaf length != arc radius")
        n = ((leaf[0] - h[0]) / r, (leaf[1] - h[1]) / r)
        mid = ((h[0] + closed[0]) / 2, (h[1] + closed[1]) / 2)

        def classify(sign, start, stop):
            d = start
            while d <= stop:
                p = Point(mid[0] + sign * n[0] * d, mid[1] + sign * n[1] * d)
                for o in outlines:
                    if o["poly"].contains(p):
                        return room_name(o)
                if fill is not None and not fill.contains(p):
                    return "outside"
                d += 0.02
            return None

        front, back = classify(+1, 0.05, 0.05), classify(-1, 0.02, 1.5)
        if front is None or front == "outside":
            problems.append(f"{tag}: swing side is not inside a room ({front})")
        if back is None:
            problems.append(f"{tag}: back side reaches neither a room nor outside")
        elif back == front:
            problems.append(f"{tag}: connects {front} to itself")
        doors.append({"arc": arc.dxf.handle, "width": round(r, 3), "connects": [front, back]})
    return doors, problems


def check_doors(doc, preset) -> list[str]:
    doors, problems = door_sides(doc, preset)
    per_room: dict[str, int] = {}
    for d in doors:
        for side in d["connects"]:
            if side and side != "outside":
                per_room[side] = per_room.get(side, 0) + 1
    want = preset["expectations"]["min_doors_in_one_room"]
    if doors and max(per_room.values(), default=0) < want:
        problems.append(f"no room has >= {want} doors")
    return problems


def check_outer_boundary(doc, preset) -> list[str]:
    fill = outer_fill(doc, preset)
    if fill is None:
        return ["wall/opening lines do not form any closed polygon"]
    problems = []
    for o in room_outlines(doc, preset):
        poly = o["poly"]
        if not poly.is_valid:
            continue
        if not fill.buffer(EPS).contains(poly):
            problems.append(f"room outline {o['handle']} is not inside the closed outer wall ring")
        elif fill.exterior.distance(poly) <= EPS:
            problems.append(f"room outline {o['handle']} touches the outer boundary "
                            "(outer wall face not closed)")
    return problems


CHECKS = {"layers": check_layers, "rooms": check_rooms, "doors": check_doors,
          "outer_boundary": check_outer_boundary}


def validate_doc(doc, preset) -> dict:
    results = {name: fn(doc, preset) for name, fn in CHECKS.items()}
    doors, _ = door_sides(doc, preset)
    return {
        "status": "PASS" if not any(results.values()) else "FAIL",
        "problems": results,
        "summary": {
            "rooms": [{"name": lab["name"], "area_m2": lab["area"]} for lab in room_labels(doc, preset)],
            "doors": doors,
            "layers": sorted(lay.dxf.name for lay in doc.layers),
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dxf")
    ap.add_argument("--preset", required=True)
    ap.add_argument("--json", help="write the full result as JSON to this path")
    args = ap.parse_args(argv)
    preset = load_preset(args.preset)
    try:
        doc = ezdxf.readfile(args.dxf)
    except (OSError, ezdxf.DXFError) as err:
        print(f"INDETERMINATE: cannot read {args.dxf}: {err}", file=sys.stderr)
        return 3
    result = validate_doc(doc, preset)
    if args.json:
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, probs in result["problems"].items():
        print(f"{name}: {'ok' if not probs else 'FAIL'}")
        for p in probs:
            print(f"  - {p}")
    print(result["status"])
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
