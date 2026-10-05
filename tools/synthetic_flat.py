#!/usr/bin/env python3
"""Generate a SYNTHETIC, simplified Viennese Altbau flat as a DXF drawing.

Every dimension, name and text comes from a JSON preset (default
``presets/synthetic_flat.json``); this script only holds drawing logic.
The output is deterministic: the same preset gives a byte-identical DXF
(header timestamps and GUIDs are taken from the preset).

Usage:
    python3 tools/synthetic_flat.py --preset presets/synthetic_flat.json \
        --output samples/synthetic_flat.dxf
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import ezdxf
from ezdxf import units
from ezdxf.tools.juliandate import juliandate
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

EPS = 1e-6
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PRESET = ROOT / "presets" / "synthetic_flat.json"
DEFAULT_OUTPUT = ROOT / "samples" / "synthetic_flat.dxf"


# --------------------------------------------------------------------------
# preset helpers
# --------------------------------------------------------------------------
def load_preset(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def layer_name(preset: dict, role: str) -> str:
    """Build `<storey>_<n>_[Abbruch_|Neubau_]<base>` for a layer role."""
    spec = preset["layers"][role]
    parts = [preset["storey"], spec["n"]]
    if spec.get("phase"):
        parts.append(spec["phase"])
    parts.append(spec["base"])
    return "_".join(parts)


def gx(preset: dict, key: str) -> float:
    return float(preset["grid"]["x"][key])


def gy(preset: dict, key: str) -> float:
    return float(preset["grid"]["y"][key])


def rect_of(preset: dict, item: dict) -> tuple[float, float, float, float]:
    """Return (x0, y0, x1, y1) for an item with grid keys `x` and `y`."""
    return (gx(preset, item["x"][0]), gy(preset, item["y"][0]),
            gx(preset, item["x"][1]), gy(preset, item["y"][1]))


def point_of(preset: dict, keys: list[str]) -> tuple[float, float]:
    return gx(preset, keys[0]), gy(preset, keys[1])


def fmt_area(preset: dict, area: float) -> str:
    dec = preset["meta"]["area_decimals"]
    txt = f"{area:.{dec}f}"
    return txt.replace(".", preset["meta"]["label_decimal_separator"])


def rnd(p) -> tuple[float, float]:
    return (round(float(p[0]), 6), round(float(p[1]), 6))


# --------------------------------------------------------------------------
# geometry derived from the preset (also used by the validator/tests)
# --------------------------------------------------------------------------
class Wall:
    def __init__(self, preset: dict, spec: dict):
        self.id = spec["id"]
        self.kind = spec["kind"]
        self.x0, self.y0, self.x1, self.y1 = rect_of(preset, spec)
        self.horizontal = (self.x1 - self.x0) >= (self.y1 - self.y0)

    @property
    def rect(self) -> Polygon:
        return box(self.x0, self.y0, self.x1, self.y1)

    @property
    def cross(self) -> tuple[float, float]:
        return (self.y0, self.y1) if self.horizontal else (self.x0, self.x1)

    @property
    def thickness(self) -> float:
        c0, c1 = self.cross
        return c1 - c0

    def pt(self, along: float, cross: float) -> tuple[float, float]:
        return (along, cross) if self.horizontal else (cross, along)

    def normal(self, sign: int) -> tuple[float, float]:
        return (0.0, float(sign)) if self.horizontal else (float(sign), 0.0)

    def opening(self, start: float, width: float) -> Polygon:
        c0, c1 = self.cross
        a0, a1 = start, start + width
        p0, p1 = self.pt(a0, c0), self.pt(a1, c1)
        return box(min(p0[0], p1[0]), min(p0[1], p1[1]),
                   max(p0[0], p1[0]), max(p0[1], p1[1]))


def interior_box(preset: dict) -> Polygon:
    """Union of all room rectangles' bounding box (the flat's clear interior)."""
    rooms = [box(*rect_of(preset, r)) for r in preset["rooms"]]
    return box(*unary_union(rooms).bounds)


def outer_side_sign(wall: Wall, centre: tuple[float, float]) -> int:
    """+1 if the positive-normal face is farther from the flat centre."""
    c0, c1 = wall.cross
    ref = centre[1] if wall.horizontal else centre[0]
    return 1 if abs(c1 - ref) > abs(c0 - ref) else -1


# --------------------------------------------------------------------------
# drawing
# --------------------------------------------------------------------------
def _segments(geom) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    polys = [geom] if geom.geom_type == "Polygon" else list(getattr(geom, "geoms", []))
    out = []
    for poly in polys:
        if poly.is_empty:
            continue
        poly = poly.simplify(1e-9)
        for ring in [poly.exterior, *poly.interiors]:
            coords = list(ring.coords)
            for a, b in zip(coords[:-1], coords[1:]):
                if math.dist(a, b) > EPS:
                    out.append((rnd(a), rnd(b)))
    return out


def draw_walls(msp, preset: dict, walls: list[Wall], openings: Polygon) -> int:
    placed = None
    drawn = []
    n_lines = 0
    for kind in preset["wall_priority"]:
        rects = [w.rect for w in walls if w.kind == kind]
        if not rects:
            continue
        geom = unary_union(rects)
        if placed is not None:
            geom = geom.difference(placed)
        geom = geom.difference(openings)
        covered = unary_union(drawn).buffer(EPS) if drawn else None
        layer = layer_name(preset, kind)
        for a, b in _segments(geom):
            seg = LineString([a, b])
            if covered is not None and covered.contains(seg):
                continue
            msp.add_line(a, b, dxfattribs={"layer": layer})
            drawn.append(seg)
            n_lines += 1
        placed = unary_union([placed, unary_union(rects)]) if placed is not None \
            else unary_union(rects)
    return n_lines


def draw_door(msp, preset: dict, wall: Wall, door: dict) -> None:
    layer = layer_name(preset, "door")
    a0, w = float(door["from"]), float(door["width"])
    a1 = a0 + w
    c0, c1 = wall.cross
    sign = 1 if door["swing"] == "+" else -1
    face = c1 if sign > 0 else c0
    other = c0 if sign > 0 else c1
    hinge_a, free_a = (a0, a1) if door["hinge"] == "start" else (a1, a0)
    hinge = wall.pt(hinge_a, face)
    closed = wall.pt(free_a, face)
    n = wall.normal(sign)
    opened = (hinge[0] + n[0] * w, hinge[1] + n[1] * w)
    # thresholds on both wall faces
    msp.add_line(rnd(wall.pt(a0, face)), rnd(wall.pt(a1, face)), dxfattribs={"layer": layer})
    msp.add_line(rnd(wall.pt(a0, other)), rnd(wall.pt(a1, other)), dxfattribs={"layer": layer})
    # leaf in open position
    msp.add_line(rnd(hinge), rnd(opened), dxfattribs={"layer": layer})
    # swing arc from closed to open position (counter-clockwise in DXF)
    ang_c = math.degrees(math.atan2(closed[1] - hinge[1], closed[0] - hinge[0]))
    ang_o = math.degrees(math.atan2(opened[1] - hinge[1], opened[0] - hinge[0]))
    cross = (closed[0] - hinge[0]) * (opened[1] - hinge[1]) - \
            (closed[1] - hinge[1]) * (opened[0] - hinge[0])
    start, end = (ang_c, ang_o) if cross > 0 else (ang_o, ang_c)
    msp.add_arc(rnd(hinge), round(w, 6), round(start % 360, 6), round(end % 360, 6),
                dxfattribs={"layer": layer})


def draw_window(msp, preset: dict, wall: Wall, win: dict, centre) -> None:
    layer = layer_name(preset, "window")
    sym = preset["window_symbol"]
    a0, w = float(win["from"]), float(win["width"])
    a1 = a0 + w
    c0, c1 = wall.cross
    out_sign = outer_side_sign(wall, centre)
    outer, inner = (c1, c0) if out_sign > 0 else (c0, c1)
    t = c1 - c0

    def line(ca, cb, aa=a0, ab=a1):
        msp.add_line(rnd(wall.pt(aa, ca)), rnd(wall.pt(ab, cb)), dxfattribs={"layer": layer})

    line(outer, outer)  # outer sill (Sohlbank) line on the outer face
    line(inner, inner)  # inner face line
    for frac in sym["frame_fractions"]:  # Kastenfenster: two frames
        c = outer - out_sign * frac * t
        line(c, c)
    # inner window board (Fensterbank) protruding into the room
    d = sym["inner_sill_depth"] * -out_sign
    o = sym["inner_sill_overhang"]
    p = [wall.pt(a0 - o, inner), wall.pt(a0 - o, inner + d),
         wall.pt(a1 + o, inner + d), wall.pt(a1 + o, inner)]
    for pa, pb in zip(p[:-1], p[1:]):
        msp.add_line(rnd(pa), rnd(pb), dxfattribs={"layer": layer})


def _rect(msp, x, y, w, h, layer) -> None:
    msp.add_lwpolyline([rnd((x, y)), rnd((x + w, y)), rnd((x + w, y + h)), rnd((x, y + h))],
                       close=True, dxfattribs={"layer": layer})


def draw_fitting(msp, preset: dict, f: dict) -> None:
    layer = layer_name(preset, f["layer"])
    sym = preset["symbols"]
    ins = sym["inset"]
    kind = f["type"]
    if kind == "hob":
        p = f["pitch"] / 2
        for dx in (-p, p):
            for dy in (-p, p):
                msp.add_circle(rnd((f["cx"] + dx, f["cy"] + dy)), f["r"],
                               dxfattribs={"layer": layer})
        return
    x, y, w, h = f["x"], f["y"], f["w"], f["h"]
    _rect(msp, x, y, w, h, layer)
    if kind in ("sink", "bathtub"):
        _rect(msp, x + ins, y + ins, w - 2 * ins, h - 2 * ins, layer)
    elif kind == "basin":
        r = sym["basin_bowl_ratio"]
        msp.add_ellipse(rnd((x + w / 2, y + h / 2)), major_axis=(round(w * r / 2, 6), 0, 0),
                        ratio=round(h / w, 6), dxfattribs={"layer": layer})
    elif kind == "toilet":
        td = sym["toilet_tank_depth"]
        # tank against the wall on the +x side, bowl ellipse in front of it
        msp.add_line(rnd((x + w - td, y)), rnd((x + w - td, y + h)), dxfattribs={"layer": layer})
        bowl = (w - td) / 2
        msp.add_ellipse(rnd((x + bowl, y + h / 2)), major_axis=(round(bowl - ins / 2, 6), 0, 0),
                        ratio=round((h / 2 - ins / 2) / (bowl - ins / 2), 6),
                        dxfattribs={"layer": layer})
    elif kind == "bed":
        pd, gap = sym["bed_pillow_depth"], sym["bed_pillow_gap"]
        pw = (h - 3 * gap) / 2
        for k in range(2):
            _rect(msp, x + w - pd - gap / 2, y + gap + k * (pw + gap), pd, pw, layer)


def draw_rooms(msp, preset: dict) -> list[dict]:
    zone, stamp = layer_name(preset, "zone"), layer_name(preset, "room_stamp")
    ceil = layer_name(preset, "ceiling")
    lab = preset["room_label"]
    cfg = preset["ceiling"]
    info = []
    for room in preset["rooms"]:
        x0, y0, x1, y1 = rect_of(preset, room)
        poly = box(x0, y0, x1, y1)
        msp.add_lwpolyline([rnd(p) for p in list(poly.exterior.coords)[:-1]], close=True,
                           dxfattribs={"layer": zone})
        at = room.get("label_at") or [poly.centroid.x, poly.centroid.y]
        area_txt = f"{fmt_area(preset, poly.area)} {lab['area_unit']}"
        msp.add_mtext(f"{room['name']}\\P{area_txt}", dxfattribs={
            "layer": stamp, "insert": rnd(at), "char_height": lab["text_height"],
            "attachment_point": 5, "line_spacing_factor": lab["line_spacing"]})
        rh = f"{cfg['room_height_prefix']} {fmt_area(preset, cfg['room_height_m'])} m"
        off = cfg["room_height_offset"]
        msp.add_text(rh, height=lab["text_height"] * 0.8, dxfattribs={"layer": ceil}).set_placement(
            rnd((at[0] + off[0], at[1] + off[1])), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
        info.append({"name": room["name"], "area": poly.area})
    for ros in cfg["rosettes"]:
        msp.add_circle(rnd((ros["cx"], ros["cy"])), ros["r"], dxfattribs={"layer": ceil})
    return info


def draw_dimensions(msp, preset: dict) -> None:
    layer = layer_name(preset, "dimension")
    for d in preset["dimensions"]:
        p1, p2 = point_of(preset, d["p1"]), point_of(preset, d["p2"])
        base = (p1[0] + d["base_offset"][0], p1[1] + d["base_offset"][1])
        dim = msp.add_linear_dim(base=rnd(base), p1=rnd(p1), p2=rnd(p2), angle=d["angle"],
                                 dimstyle=preset["dimstyle"], dxfattribs={"layer": layer})
        dim.render()
        # ezdxf draws the dimension and extension lines of the anonymous block on layer "0": keep them on the
        # dimension layer (the points on Defpoints are the CAD convention for non-plotting definition points)
        for part in msp.doc.blocks.get(dim.dimension.dxf.geometry):
            if part.dxf.layer == "0":
                part.dxf.layer = layer


def draw_paper(doc, preset: dict) -> None:
    pap = preset["paper"]
    layer = layer_name(preset, "title_block")
    psp = doc.paperspace()
    t, r, b, left = pap["margins_mm"]
    psp.page_setup(size=tuple(pap["size_mm"]), margins=(t, r, b, left), units="mm")
    vp = pap["viewport"]
    paper_per_model = 1000.0 / pap["scale_denominator"]  # mm paper per m model
    psp.add_viewport(center=tuple(vp["center_mm"]), size=tuple(vp["size_mm"]),
                     view_center_point=tuple(vp["model_center"]),
                     view_height=vp["size_mm"][1] / paper_per_model,
                     dxfattribs={"layer": layer})
    w, h = pap["size_mm"]
    _rect(psp, left, b, w - left - r, h - t - b, layer)  # frame
    tb = pap["title_block"]
    ox, oy = tb["origin_mm"]
    tw, th = tb["size_mm"]
    _rect(psp, w - r - tw, oy, tw, th, layer)
    x_text = w - r - tw + tb["text_height_mm"]
    for k, txt in enumerate(tb["lines"]):
        y = oy + th - (k + 1) * tb["line_pitch_mm"]
        psp.add_text(txt, height=tb["text_height_mm"], dxfattribs={"layer": layer}).set_placement(
            (x_text, y))


def stable_classes(doc) -> None:
    """Sort the CLASS entries ezdxf adds for the entity types in use. ezdxf adds them from a set
    (entitydb.dxf_types_in_use()), so their order followed Python's string hashing (PYTHONHASHSEED): the
    same preset gave a different DXF on another machine. The required classes keep ezdxf's order."""
    from ezdxf.sections.classes import REQ_R2004, REQUIRED_CLASSES
    required = REQUIRED_CLASSES.get(doc.dxfversion, REQ_R2004)      # the same default ezdxf uses
    items = list(doc.classes.classes.items())
    head = [kv for kv in items if kv[0][0] in required]
    rest = sorted((kv for kv in items if kv[0][0] not in required), key=lambda kv: kv[0])
    doc.classes.classes = dict(head + rest)


def fix_metadata(doc, preset: dict) -> None:
    """Make header timestamps/GUIDs come from the preset, and the CLASS order stable, at write time
    (ezdxf adds the classes just before it updates the metadata)."""
    meta = preset["meta"]
    jd = juliandate(datetime.fromisoformat(meta["created_utc"]))
    original = doc._update_metadata

    def _update_metadata():
        original()
        stable_classes(doc)
        for var in ("$TDCREATE", "$TDUCREATE", "$TDUPDATE", "$TDUUPDATE"):
            doc.header[var] = jd
        doc.header["$TDINDWG"] = 0.0
        doc.header["$TDUSRTIMER"] = 0.0
        doc.header["$FINGERPRINTGUID"] = meta["fingerprint_guid"]
        doc.header["$VERSIONGUID"] = meta["version_guid"]

    doc._update_metadata = _update_metadata


def build(preset: dict):
    doc = ezdxf.new(preset["meta"]["dxf_version"], setup=True)
    doc.units = units.M
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LUNITS"] = 2
    for role, spec in preset["layers"].items():
        attrs = {"color": spec["color"]}
        if spec.get("linetype"):
            attrs["linetype"] = spec["linetype"]
        doc.layers.add(layer_name(preset, role), **attrs)
    msp = doc.modelspace()

    walls = [Wall(preset, s) for s in preset["walls"]]
    by_id = {w.id: w for w in walls}
    ib = interior_box(preset)
    centre = (ib.centroid.x, ib.centroid.y)
    openings = unary_union(
        [by_id[d["wall"]].opening(d["from"], d["width"]) for d in preset["doors"]]
        + [by_id[f["wall"]].opening(f["from"], f["width"]) for f in preset["windows"]])

    n_wall_lines = draw_walls(msp, preset, walls, openings)
    for d in preset["doors"]:
        draw_door(msp, preset, by_id[d["wall"]], d)
    for f in preset["windows"]:
        draw_window(msp, preset, by_id[f["wall"]], f, centre)
    for f in preset["fittings"]:
        draw_fitting(msp, preset, f)
    rooms = draw_rooms(msp, preset)
    draw_dimensions(msp, preset)
    draw_paper(doc, preset)
    fix_metadata(doc, preset)
    summary = {"rooms": len(rooms), "total_area_m2": round(sum(r["area"] for r in rooms), 2),
               "doors": len(preset["doors"]), "windows": len(preset["windows"]),
               "wall_lines": n_wall_lines,
               "layers": len([layer for layer in doc.layers if layer.dxf.name not in ("0", "Defpoints")])}
    return doc, summary


def generate(preset_path: str | Path, output: str | Path) -> dict:
    preset = load_preset(preset_path)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    saved = ezdxf.options.write_fixed_meta_data_for_testing
    # no wall-clock CREATED_BY/WRITTEN_BY marker strings (set at new() and at save)
    ezdxf.options.write_fixed_meta_data_for_testing = True
    try:
        doc, summary = build(preset)
        doc.saveas(output, encoding="utf-8")
    finally:
        ezdxf.options.write_fixed_meta_data_for_testing = saved
    summary["bytes"] = output.stat().st_size
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--preset", default=str(DEFAULT_PRESET))
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = ap.parse_args(argv)
    summary = generate(args.preset, args.output)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
