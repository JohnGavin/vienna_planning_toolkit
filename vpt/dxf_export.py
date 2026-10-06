"""A layout of the electrical editor written into a copy of its DXF, for the Elektroplaner (tools/export_layout_dxf.py).

Design: the WHOLE source drawing is kept unchanged (every layer, every storey, paper space) and the layout is ADDED on its own
layers, so the Elektroplaner can overlay it on the architect's plan or switch it off. Per symbol category one layer (presets/
dxf_export.json: DXF-safe names such as E_Licht), coloured from the print palette of presets/el_parameters.json (nearest
AutoCAD colour index, plus the exact colour as true colour). Every symbol of the library becomes one BLOCK (E_SYM_<code>),
drawn from its SVG (lines, circles, arcs, rectangles, filled polygons, texts; mm on the sheet, y turned up); each placed symbol
one INSERT at its model position, scaled from sheet mm to drawing units (scale 1:n of the plan, symbol_scale of the
parameters), turned by its rotation, with invisible ATTRIBs CODE, NAME_DE, ROOM, VERIFIED (false while the set is
unverified) and SYMBOL_ID. Links: LINEs on E_Verbindungen with a dashed linetype. A note says the symbols are UNVERIFIED.

belongs() decides first whether the layout belongs to the drawing (three outcomes, nothing is written unless "match"):
  match           the layout is valid, its checksum is the DXF's SHA-256, its storey is a storey of the DXF (and of the plan
                  file, when one is given, which must be of the same DXF)
  different       another drawing (checksum) or a storey the drawing does not have
  could-not-tell  not a valid layout, unknown symbols or rule set, units unknown or not the layout's, an unreadable DXF
verify() re-reads the written file: per code as many INSERTs as the layout has, each within position_tol_mm of its symbol, on
its layer, every link, the note, and every entity of the source drawing still there.

The output is deterministic (the same inputs give the same bytes): fixed header times, GUIDs derived from the inputs.
"""
from __future__ import annotations

import hashlib
import json
import math
import pathlib
import re
import uuid

from vpt import PRESETS, el_layout, el_params, el_symbols, plan_extract

PRESET = PRESETS / "dxf_export.json"
MATCH, DIFF, UNK = "match", "different", "could-not-tell"


def load(path: pathlib.Path = PRESET) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def validate(pre: dict, lib: dict) -> list[str]:
    """Problems of the export preset (empty = clean)."""
    out = []
    rx = re.compile(pre["name_regex"])
    names = list(pre["layers"].values()) + [pre["linetype"]] + [pre["block_prefix"] + "X"]
    for n in names:
        if not rx.match(n):
            out.append(f"{n!r} is not a DXF-safe name ({pre['name_regex']})")
    if len(set(pre["layers"].values())) != len(pre["layers"]):
        out.append("two layers share a name")
    for s in lib["sets"]:
        for c in s["categories"]:
            if c["key"] not in pre["layers"]:
                out.append(f"symbol category {c['key']} of set {s['id']} has no layer")
        for x in s["symbols"]:
            if not rx.match(pre["block_prefix"] + x["code"]):
                out.append(f"block name for {x['code']} is not DXF-safe")
    for k in ("links", "note"):
        if k not in pre["layers"]:
            out.append(f"layers.{k} missing")
    return out


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


# ---- colours ------------------------------------------------------------------------------------------------------------------

def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def aci_of(hex_colour: str) -> int:
    """The AutoCAD colour index nearest to a colour (RGB distance over 1..255; colour 7 stands for black and white, which CAD
    programs show black on white paper and white on a black screen)."""
    from ezdxf.colors import aci2rgb
    c = _rgb(hex_colour)
    if max(c) < 40 or min(c) > 215:
        return 7
    best, bd = 7, math.inf
    for i in range(1, 256):
        if i == 7:
            continue
        r = aci2rgb(i)
        d = (r[0] - c[0]) ** 2 + (r[1] - c[1]) ** 2 + (r[2] - c[2]) ** 2
        if d < bd:
            best, bd = i, d
    return best


# ---- the symbols as blocks ----------------------------------------------------------------------------------------------------

_TOK = re.compile(r"[A-Za-z]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _arc(p1, p2, r, large: int, sweep: int):
    """Centre, start and end angle (degrees, counter-clockwise) of an SVG elliptical-arc segment with rx = ry = r and no
    rotation, after y was turned up (SVG y down): the sweep direction flips with it."""
    fs = 1 - sweep
    x1p, y1p = (p1[0] - p2[0]) / 2, (p1[1] - p2[1]) / 2
    lam = (x1p * x1p + y1p * y1p) / (r * r)
    if lam > 1:
        r *= math.sqrt(lam)
    num = r * r * r * r - r * r * y1p * y1p - r * r * x1p * x1p
    den = r * r * y1p * y1p + r * r * x1p * x1p
    coef = (-1 if large == fs else 1) * math.sqrt(max(0.0, num / den)) if den else 0.0
    cxp, cyp = coef * y1p, -coef * x1p
    cx, cy = cxp + (p1[0] + p2[0]) / 2, cyp + (p1[1] + p2[1]) / 2
    t1 = math.degrees(math.atan2((y1p - cyp) / r, (x1p - cxp) / r))
    t2 = math.degrees(math.atan2((-y1p - cyp) / r, (-x1p - cxp) / r))
    dt = (t2 - t1) % 360.0
    if fs == 0 and dt > 0:
        dt -= 360.0
    start, end = (t1, t1 + dt) if dt >= 0 else (t1 + dt, t1)
    return (cx, cy), r, start % 360.0, end % 360.0


def _path(d: str) -> list[tuple]:
    """Absolute M / L / A / Z commands of an SVG path as [("line", p, q) | ("arc", centre, r, a0, a1)], y turned up; closed
    sub-paths also as their polygon [("poly", [points])]. Any other command raises ValueError (not drawn by this library)."""
    toks = _TOK.findall(d)
    out, i, cur, start, poly, cmd = [], 0, None, None, [], None
    num = lambda: float(toks[i])
    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]
            i += 1
            if cmd == "Z":
                if cur and start and cur != start:
                    out.append(("line", cur, start))
                if len(poly) >= 3:
                    out.append(("poly", list(poly)))
                cur, poly = start, []
                continue
        if cmd not in ("M", "L", "A"):
            raise ValueError(f"SVG path command {cmd!r} is not supported")
        if cmd == "A":
            r, _ry, _rot, large, sweep, x, y = (float(toks[i + j]) for j in range(7))
            i += 7
            p = (x, -y)
            out.append(("arc",) + _arc(cur, p, r, int(large), int(sweep)))
            cur = p
            poly.append(p)
            continue
        p = (num(), -float(toks[i + 1]))
        i += 2
        if cmd == "M":
            cur = start = p
            poly = [p]
            cmd = "L"
        else:
            out.append(("line", cur, p))
            cur = p
            poly.append(p)
    return out


def draw_block(blk, svg: str, pre: dict) -> int:
    """The symbol's SVG drawn into a block (mm on the sheet, y up); returns the number of entities. Layer 0 and BYBLOCK colour:
    the INSERT's layer gives them their colour."""
    from ezdxf.enums import TextEntityAlignment
    root = el_symbols.parse_fragment(svg)
    at = {"layer": "0", "color": 0}
    n = 0
    for e in list(root.iter())[1:]:
        tag = e.tag.rsplit("}", 1)[-1]
        g = lambda k, dflt=0.0: float(e.get(k, dflt))
        if tag == "line":
            blk.add_line((g("x1"), -g("y1")), (g("x2"), -g("y2")), dxfattribs=at)
        elif tag == "circle":
            blk.add_circle((g("cx"), -g("cy")), g("r"), dxfattribs=at)
        elif tag == "rect":
            x, y, w, h = g("x"), g("y"), g("width"), g("height")
            blk.add_lwpolyline([(x, -y), (x + w, -y), (x + w, -y - h), (x, -y - h)], close=True, dxfattribs=at)
        elif tag == "path":
            filled = e.get("fill", "none") not in ("none", "")
            for part in _path(e.get("d", "")):
                if part[0] == "line":
                    blk.add_line(part[1], part[2], dxfattribs=at)
                elif part[0] == "arc":
                    blk.add_arc(part[1], part[2], part[3], part[4], dxfattribs=at)
                elif part[0] == "poly" and filled:
                    hatch = blk.add_hatch(dxfattribs=at)
                    hatch.set_solid_fill(color=0)
                    hatch.paths.add_polyline_path(part[1], is_closed=True)
                    n += 1
                    continue
                else:
                    continue
                n += 1
            continue
        elif tag == "text":
            middle = e.get("text-anchor") == "middle"
            t = blk.add_text(e.text or "", height=g("font-size", 2.5), dxfattribs=dict(at, style="Standard"))
            t.set_placement((g("x"), -g("y")), align=TextEntityAlignment.CENTER if middle else TextEntityAlignment.LEFT)
        else:
            raise ValueError(f"SVG element <{tag}> is not supported")
        n += 1
    return n


# ---- does the layout belong to the drawing? -----------------------------------------------------------------------------------

def belongs(layout, *, dxf_sha: str, dxf_storeys: list[str], dxf_mm_per_unit: float | None, plan: dict | None, lib: dict, rules: dict) -> tuple[str, str]:
    """(match | different | could-not-tell, why); see the module docstring."""
    if not isinstance(layout, dict):
        return UNK, "the layout is not a JSON object"
    probs = el_layout.validate(layout, el_layout.load_schema())
    if probs:
        return UNK, f"not a valid layout file ({len(probs)} problem(s), first: {probs[0]})"
    storey = layout["drawing"]["storey"]
    if layout["drawing"]["sha256"] != dxf_sha:
        return DIFF, f"the layout belongs to another drawing ({layout['drawing']['file']}, checksum {layout['drawing']['sha256'][:12]}…), not to this DXF ({dxf_sha[:12]}…)"
    if storey not in dxf_storeys:
        return DIFF, f"the layout is of storey {storey}, which the drawing does not have (storeys: {', '.join(dxf_storeys) or 'none'})"
    if plan is not None:
        if plan.get("drawing", {}).get("sha256") != dxf_sha:
            return DIFF, "the plan file is of another drawing than the DXF"
        if storey not in [s["key"] for s in plan.get("storeys", [])]:
            return DIFF, f"the plan file has no storey {storey}"
    res = el_layout.check_layout(layout, sha256=dxf_sha, storey=storey, lib=lib, schema=el_layout.load_schema(), rules=rules)
    if res[0] != MATCH:
        return res
    if not dxf_mm_per_unit:
        return UNK, "the drawing's units are unknown ($INSUNITS): sheet millimetres cannot be turned into drawing units"
    if layout.get("model_units_mm") is not None and abs(layout["model_units_mm"] - dxf_mm_per_unit) > 1e-9:
        return UNK, f"the layout says {layout['model_units_mm']} mm per drawing unit, the DXF {dxf_mm_per_unit}"
    return MATCH, f"checksum and storey {storey} match; {len(layout['symbols'])} symbol(s), {len(layout['links'])} link(s)"


# ---- writing ------------------------------------------------------------------------------------------------------------------

def _stable_classes(doc) -> None:
    from ezdxf.sections.classes import REQ_R2004, REQUIRED_CLASSES
    required = REQUIRED_CLASSES.get(doc.dxfversion, REQ_R2004)
    items = list(doc.classes.classes.items())
    doc.classes.classes = dict([kv for kv in items if kv[0][0] in required] + sorted((kv for kv in items if kv[0][0] not in required), key=lambda kv: kv[0]))


def _fix_metadata(doc, seed: str) -> None:
    """Deterministic header: ezdxf's fixed test date for the four time stamps (ezdxf does not keep the source's on reading),
    no editing timers, and a version GUID derived from the inputs (the same DXF and layout give the same bytes)."""
    from datetime import datetime
    from ezdxf.tools.juliandate import juliandate
    jd = juliandate(datetime(2000, 1, 1, 0, 0))
    original = doc._update_metadata

    def update():
        original()
        _stable_classes(doc)
        for v in ("$TDCREATE", "$TDUCREATE", "$TDUPDATE", "$TDUUPDATE"):
            doc.header[v] = jd
        doc.header["$TDINDWG"] = 0.0
        doc.header["$TDUSRTIMER"] = 0.0
        g = "{" + str(uuid.uuid5(uuid.NAMESPACE_URL, "vpt-dxf-export:" + seed)).upper() + "}"
        doc.header["$VERSIONGUID"] = g
        doc.header["$FINGERPRINTGUID"] = g
    doc._update_metadata = update


def scale_units(mm_per_unit: float, scale_1_to: float, symbol_scale: float) -> float:
    """Drawing units per mm on the sheet (times the symbol size factor)."""
    return scale_1_to / mm_per_unit * symbol_scale


def write(doc, layout: dict, *, out: pathlib.Path, scale_1_to: float, mm_per_unit: float, layout_name: str, seed: str,
          pre: dict | None = None, params: dict | None = None, lib: dict | None = None) -> dict:
    """Add the layout to doc (the source drawing, read with ezdxf) and save it as out. Returns what was added."""
    import ezdxf
    from ezdxf import const
    pre, params, lib = pre or load(), params or el_params.load(), lib or el_symbols.load()
    sset = next(s for s in lib["sets"] if s["id"] == layout["symbol_set"]["id"])
    pal = el_params.palette(params, "colours_print")
    sym_scale = el_params.value(params, "page", "symbol_scale")
    s = scale_units(mm_per_unit, scale_1_to, sym_scale)
    sheet = scale_units(mm_per_unit, scale_1_to, 1.0)
    L = pre["layers"]
    for cat, name in L.items():
        colour = pal["link"] if cat == "links" else pal.get(cat, pal["verteiler"])
        lay = doc.layers.get(name) if name in doc.layers else doc.layers.add(name)
        lay.color = aci_of(colour)
        lay.rgb = _rgb(colour)
    dash = el_params.value(params, "print_lines", "link_dash_mm")
    if pre["linetype"] not in doc.linetypes:
        on, off = dash[0] * sheet, dash[1] * sheet
        doc.linetypes.add(pre["linetype"], pattern=[on + off, on, -off], description="Elektro link __ __ __")
    codes = sorted({x["code"] for x in layout["symbols"]})
    defs = {x["code"]: x for x in sset["symbols"]}
    ah = pre["attrib_height_mm"]
    for code in codes:
        bname = pre["block_prefix"] + code
        if bname in doc.blocks:
            doc.blocks.delete_block(bname, safe=False)
        blk = doc.blocks.new(bname, base_point=(0, 0))
        draw_block(blk, defs[code]["svg"], pre)
        for i, tag in enumerate(pre["attribs"]):
            blk.add_attdef(tag, insert=(0, -(i + 1) * ah * 1.2), dxfattribs={"height": ah, "flags": const.ATTRIB_INVISIBLE, "layer": "0"})
    msp = doc.modelspace()
    cat = {x["code"]: x["category"] for x in sset["symbols"]}
    by_id = {x["id"]: x for x in layout["symbols"]}
    verified = "true" if sset.get("verified") else "false"
    for x in layout["symbols"]:
        ins = msp.add_blockref(pre["block_prefix"] + x["code"], (x["x"], x["y"]),
                               dxfattribs={"layer": L[cat[x["code"]]], "xscale": s, "yscale": s, "zscale": s, "rotation": float(x["rotation"])})
        ins.add_auto_attribs({"CODE": x["code"], "NAME_DE": defs[x["code"]]["name_de"], "ROOM": x.get("room") or "",
                              "VERIFIED": verified, "SYMBOL_ID": x["id"]})
    for ln in layout["links"]:
        a, b = by_id[ln["from"]], by_id[ln["to"]]
        msp.add_line((a["x"], a["y"]), (b["x"], b["y"]), dxfattribs={"layer": L["links"], "linetype": pre["linetype"]})
    xs = [x["x"] for x in layout["symbols"]] or [0.0]
    ys = [x["y"] for x in layout["symbols"]] or [0.0]
    note = pre["note_template"].format(set_id=sset["id"], set_version=sset["version"], layout_file=layout_name,
                                       storey=layout["drawing"]["storey"], n=len(layout["symbols"]), l=len(layout["links"]))
    msp.add_text(note, height=pre["text_height_mm"] * sheet, dxfattribs={"layer": L["note"], "style": "Standard"}).set_placement(
        (min(xs), max(ys) + pre["note_offset_mm"] * sheet))
    _fix_metadata(doc, seed)
    saved = ezdxf.options.write_fixed_meta_data_for_testing
    ezdxf.options.write_fixed_meta_data_for_testing = True
    try:
        doc.saveas(out, encoding="utf-8")
    finally:
        ezdxf.options.write_fixed_meta_data_for_testing = saved
    return {"symbols": len(layout["symbols"]), "links": len(layout["links"]), "blocks": len(codes), "note": note, "scale": s}


def verify(out: pathlib.Path, layout: dict, *, source_entities: int, mm_per_unit: float, pre: dict | None = None,
           lib: dict | None = None) -> tuple[str, list[str], dict]:
    """Read the written file again: (match | different | could-not-tell, problems, numbers)."""
    import ezdxf
    pre, lib = pre or load(), lib or el_symbols.load()
    try:
        doc = ezdxf.readfile(out)
    except Exception as e:          # noqa: BLE001 - a file that does not read back is could-not-tell
        return UNK, [f"the written file does not read back ({type(e).__name__}: {e})"], {}
    sset = next(s for s in lib["sets"] if s["id"] == layout["symbol_set"]["id"])
    cat = {x["code"]: x["category"] for x in sset["symbols"]}
    L = pre["layers"]
    msp = doc.modelspace()
    inserts = [e for e in msp.query("INSERT") if e.dxf.name.startswith(pre["block_prefix"])]
    probs = []
    want_codes, got_codes = {}, {}
    for x in layout["symbols"]:
        want_codes[x["code"]] = want_codes.get(x["code"], 0) + 1
    by_sid = {}
    for e in inserts:
        code = e.dxf.name[len(pre["block_prefix"]):]
        got_codes[code] = got_codes.get(code, 0) + 1
        by_sid[e.get_attrib_text("SYMBOL_ID")] = e
    if want_codes != got_codes:
        probs.append(f"inserts per code {got_codes}, layout {want_codes}")
    tol = pre["position_tol_mm"] / mm_per_unit
    worst = 0.0
    for x in layout["symbols"]:
        e = by_sid.get(x["id"])
        if e is None:
            probs.append(f"{x['id']}: no insert")
            continue
        d = math.dist((e.dxf.insert.x, e.dxf.insert.y), (x["x"], x["y"]))
        worst = max(worst, d * mm_per_unit)
        if d > tol:
            probs.append(f"{x['id']}: {d * mm_per_unit:.3f} mm from its place")
        if e.dxf.layer != L[cat[x["code"]]] or e.get_attrib_text("CODE") != x["code"]:
            probs.append(f"{x['id']}: on layer {e.dxf.layer}, code {e.get_attrib_text('CODE')}")
        if abs((e.dxf.rotation - x["rotation"] + 180) % 360 - 180) > 1e-6:
            probs.append(f"{x['id']}: rotation {e.dxf.rotation}, layout {x['rotation']}")
    used = {L[cat[x["code"]]] for x in layout["symbols"]} | {L["note"]} | ({L["links"]} if layout["links"] else set())
    missing = sorted(n for n in used if n not in doc.layers)
    if missing:
        probs.append(f"layers missing: {missing}")
    links = [e for e in msp.query("LINE") if e.dxf.layer == L["links"]]
    if len(links) != len(layout["links"]):
        probs.append(f"{len(links)} link lines, layout {len(layout['links'])}")
    notes = [e for e in msp.query("TEXT") if e.dxf.layer == L["note"] and "UNVERIFIED" in e.dxf.text]
    if not notes:
        probs.append("no UNVERIFIED note")
    mine = set(L.values())
    others = sum(1 for e in msp if e.dxf.layer not in mine)
    if others != source_entities:
        probs.append(f"{others} entities of the source drawing, the source had {source_entities}")
    nums = {"inserts": len(inserts), "per_code": got_codes, "links": len(links), "worst_mm": round(worst, 6), "source_entities": others,
            "layers": sorted(n for n in used if n in doc.layers)}
    return (DIFF if probs else MATCH), probs, nums


def storeys_of(doc) -> list[str]:
    pre = json.loads((PRESETS / "plan_extract.json").read_text(encoding="utf-8"))
    info = plan_extract.layer_info([lay.dxf.name for lay in doc.layers], pre)
    return sorted({v["storey"] for v in info.values() if v["storey"]})


def default_scale(plan: dict | None, storey: str) -> float:
    if plan is not None:
        return next(s["scale_1_to"] for s in plan["storeys"] if s["key"] == storey)
    pre = json.loads((PRESETS / "plan_extract.json").read_text(encoding="utf-8"))
    return pre["render"]["scale_1_to"]

