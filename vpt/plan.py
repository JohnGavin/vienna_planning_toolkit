"""The plan file (<name>.plan.json): everything the electrical editor needs about one drawing, in one file (schema
schema/plan.schema.json, the one home of the format). Written by tools/export_plan.py on the user's own computer; the editor
reads it in the browser (Open plan, or paste) and never sends it anywhere.

Per storey: the drawing as SVG with one group per DXF layer, the layer list (base name, status, paths, shown at start), the
model -> SVG affine, rooms / doors / walls (vpt/plan_extract.py), the checks R1-R5, the placement suggestions of every rule
set (vpt/el_rules.py) and, for the example storey, the generated example layouts (vpt/el_examples.py).

check_text() gives the page's three outcomes for an opened file: "match" (a valid plan file), "different" (a valid JSON file of
another kind, e.g. a layout or parameter file: refused, saying what it is), "could-not-tell" (not JSON, not valid against the
schema, an SVG that does not parse, an affine that cannot be inverted: refused).
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from xml.etree import ElementTree as ET

from vpt import PRESETS, SCHEMAS, dxf_svg, el_examples, el_layout, el_params, el_rules, el_symbols, plan_extract

SCHEMA = SCHEMAS / "plan.schema.json"
EXTRACT_PRESET = PRESETS / "plan_extract.json"
KIND = "vpt_plan"
VERSION = 1


def load_schema(path: pathlib.Path = SCHEMA) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def _status_word(s) -> str:
    return s or "Bestand"


def _storey_page(doc, info: dict, key: str, k: float, pre: dict) -> dict | None:
    """{width_mm, height_mm, limits} of a storey: its model-space extent plus render.margin_m, at 1:render.scale_1_to."""
    from ezdxf import bbox
    ents = [e for e in doc.modelspace() if (info.get(e.dxf.get("layer", "0")) or {}).get("storey") == key]
    ext = bbox.extents(ents, fast=True)
    if not ext.has_data:
        return None
    m = pre["render"]["margin_m"] * k
    x0, y0, x1, y1 = ext.extmin.x - m, ext.extmin.y - m, ext.extmax.x + m, ext.extmax.y + m
    mm_per_unit = 1000.0 / k
    sc = pre["render"]["scale_1_to"]
    return {"width_mm": (x1 - x0) * mm_per_unit / sc, "height_mm": (y1 - y0) * mm_per_unit / sc, "limits": (x0, x1, y0, y1)}


def export(dxf_path: pathlib.Path, *, synthetic: bool = False, pre: dict | None = None, params: dict | None = None,
           params_sha256: str | None = None) -> dict:
    """The plan file's content for a DXF (deterministic: the same DXF and presets give the same JSON)."""
    import ezdxf
    dxf_path = pathlib.Path(dxf_path)
    pre = pre or json.loads(EXTRACT_PRESET.read_text(encoding="utf-8"))
    params = params or el_params.load()
    rules = el_rules.load(params=params)
    lib = el_symbols.load()
    for name, probs in (("symbol library", el_symbols.validate(lib)), ("placement rules", el_rules.validate(rules, lib)),
                        ("parameters", el_params.validate(params))):
        if probs:
            raise ValueError(f"the {name} preset is broken: " + "; ".join(probs[:5]))
    doc = ezdxf.readfile(dxf_path)
    ex = plan_extract.extract(doc, pre)
    k, mm = ex["k"], ex["mm_per_unit"]
    sha = sha256_file(dxf_path)
    psha = params_sha256 or el_params.sha256()
    out = {"schema": KIND, "schema_version": VERSION,
           "drawing": {"file": dxf_path.name, "sha256": sha, "mm_per_unit": mm, "units_per_m": k},
           "synthetic": bool(synthetic), "exported_by": "tools/export_plan.py",
           "extract": {"status": ex["status"], "failures": ex["failures"], "unknowns": ex["unknowns"]},
           "parameters": {"id": params["id"], "version": params["version"], "sha256": psha}, "storeys": []}
    if not k:
        raise ValueError("the drawing's units are unknown ($INSUNITS): positions in metres cannot be applied")
    info = ex["layers"]
    backgrounds, storeys = {}, []
    for st in ex["storeys"]:
        key = st["key"]
        page = _storey_page(doc, info, key, k, pre)
        if page is None:
            continue
        mine = set(st["layers"])
        r = dxf_svg.render(doc, doc.modelspace(), page, key=key, layers=mine, units=dxf_svg.view_units(page, mm),
                           filter_func=lambda e, mine=mine: e.dxf.get("layer", "0") in mine)
        svg = dxf_svg.finish(r["root"], key=key)
        layers = [{"layer": n, "base": info.get(n, {}).get("base", n), "status": _status_word(info.get(n, {}).get("status")),
                   "paths": int(r["paths"].get(n, 0)), "default_on": n not in r["off"]} for n in sorted(r["order"])]
        vb = [float(v) for v in r["root"].get("viewBox").split()]
        on = [x["layer"] for x in layers if x["default_on"]]
        backgrounds[key] = {"layers": on, "hidden_layers": len(layers) - len(on)}
        rooms, doors, kk = el_rules.storey_input(st, k)
        storeys.append({"key": key, "label": st["label"], "svg": svg, "layers": layers,
                        "affine": [round(v, 9) for v in r["affine"]], "view_box": vb,
                        "page_mm": [round(page["width_mm"], 3), round(page["height_mm"], 3)], "scale_1_to": pre["render"]["scale_1_to"],
                        "rooms": [{"id": x["id"], "name": x["name"], "area_text": x["area_text"], "area_outline_m2": x["area_outline_m2"],
                                   "wet": x["wet"], "outline": x["outline"], "anchor": x["anchor"]} for x in st["rooms"]],
                        "doors": [{f: d[f] for f in ("id", "hinge", "ends", "closed_end", "opens_into", "opens_from", "rooms", "width_m",
                                                     "swing_method", "leads_to", "pair") if f in d} for d in st["doors"]],
                        "walls": [{f: w[f] for f in ("id", "base", "status", "p", "q", "rooms")} for w in st["walls"]],
                        "checks": [{f: c[f] for f in ("id", "title", "status", "detail")} for c in st["checks"]],
                        "suggest": {rs["id"]: el_rules.suggestions(rooms, doors, kk, rules, rs["id"]) for rs in rules["rule_sets"]},
                        "examples": None})
    exs = el_examples.build(ex["storeys"], k=k, mm_per_unit=mm, drawing_file=dxf_path.name, sha256=sha, background=backgrounds,
                            rules=rules, params=params, lib=lib, params_sha256=psha)
    schema = el_layout.load_schema()
    for ex_id, exd in exs["examples"].items():
        chk = el_layout.check_layout(exd, sha256=sha, storey=exs["storey"], lib=lib, schema=schema, rules=rules)
        if chk[0] != "match":
            raise ValueError(f"the {ex_id} example does not open on its own storey: {chk[1]}")
    for s in storeys:
        if s["key"] == exs["storey"]:
            s["examples"] = exs["examples"]
    out["example_rule"] = exs["why"]
    out["storeys"] = storeys
    return out


def dumps(plan: dict) -> str:
    """The file's text: compact JSON (the SVGs are large), UTF-8, a final newline; deterministic."""
    return json.dumps(plan, ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n"


def check(plan, schema: dict | None = None) -> tuple[str, str]:
    """Three outcomes for a parsed JSON value (see the module docstring)."""
    if not isinstance(plan, dict):
        return "could-not-tell", "not a JSON object"
    kind = plan.get("schema") or plan.get("name")
    if kind != KIND:
        what = {"el_layout": "a layout file (use Open layout)", "el_parameters": "a parameter file (use Load parameters)"}.get(kind, f"a file of kind {kind!r}" if kind else "a JSON file of unknown kind")
        return "different", f"this is {what}, not a plan file"
    probs = el_layout.validate(plan, schema or load_schema())
    if probs:
        return "could-not-tell", f"not a valid plan file ({len(probs)} problem(s), first: {probs[0]})"
    for st in plan["storeys"]:
        try:
            info = dxf_svg.inspect(st["svg"])
        except (ET.ParseError, ValueError) as e:
            return "could-not-tell", f"storey {st['key']}: the drawing does not parse ({e})"
        if info["images"]:
            return "could-not-tell", f"storey {st['key']}: the drawing holds raster images or scripts"
        a = st["affine"]
        if abs(a[0] * a[3] - a[1] * a[2]) < 1e-12:
            return "could-not-tell", f"storey {st['key']}: the drawing's affine cannot be inverted"
    n = len(plan["storeys"])
    return "match", f"{n} storey(s), {sum(len(s['rooms']) for s in plan['storeys'])} rooms, {sum(len(s['doors']) for s in plan['storeys'])} doors"


def check_text(text: str, schema: dict | None = None) -> tuple[str, str]:
    try:
        plan = json.loads(text)
    except (json.JSONDecodeError, TypeError) as e:
        return "could-not-tell", f"not JSON ({e})"
    return check(plan, schema)
