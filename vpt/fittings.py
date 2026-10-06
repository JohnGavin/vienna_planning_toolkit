"""Recognise fittings (WC, basin, bath, sink, hotplate, ...) by shape in a DXF and put each in a room (tools/recognise_fittings.py).

Settings: presets/fittings.json (fitting layers by base name, the shape rules, tolerances); every value is a starting value to
confirm against your own drawing. The shape logic is vpt/dxf_symbols.py; the rooms are those of vpt/plan_extract.py (used read
only: its labels, outlines and walls, and its `assign` rule for the room of a point).

Per storey: the primitives on the fitting layers are grouped into symbols (join_tol_m / contain_max_m), each symbol is classified by
the rules (one rule matches: that type; none: "unrecognised"; several: "ambiguous"; never resolved by guessing), and each recognised
fitting gets the room of its centre (plan_extract.assign). Symbols on layers of an excluded status (Abbruch: demolished) are
classified too but reported as demolished and left out of every count and check. Groups shorter than min_symbol_m are fragments.

Checks (match / different / could-not-tell; could-not-tell is never a match):
    F1 every symbol is classified     an unrecognised or ambiguous symbol: could-not-tell, FLAGGED (listed with its size, never a name)
    F2 every fitting is in a room     a recognised fitting whose centre is in no room: could-not-tell, FLAGGED
    F3 every wet room has a fitting   a room whose label matches the wet-room pattern (plan_extract.json) and holds no recognised
                                      fitting: different
Result: FAIL when a check is different, INDETERMINATE when one could not tell (a flag included) or the drawing's units are unknown,
else PASS.
"""
from __future__ import annotations

import json
import pathlib
from collections import Counter

from shapely import STRtree
from shapely.geometry import LineString, Polygon

from vpt import PRESETS, dxf_symbols as ds, plan_extract
from vpt.plan_extract import DIFF, MATCH, UNK, Check

PRESET = PRESETS / "fittings.json"


def load_preset(path: pathlib.Path = PRESET) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def validate(fp: dict) -> list[str]:
    """Problems with the preset: a rule without a type or ranges, duplicate rule types."""
    out = []
    rules = (fp.get("shape_rules") or {}).get("rules") or []
    if not fp.get("fitting_layers"):
        out.append("no fitting_layers")
    if not rules:
        out.append("no shape_rules.rules")
    types = [r.get("type") for r in rules]
    if len(set(types)) != len(types):
        out.append("duplicate rule type")
    for r in rules:
        if not r.get("type") or not (isinstance(r.get("w_m"), list) and isinstance(r.get("d_m"), list) and len(r["w_m"]) == len(r["d_m"]) == 2):
            out.append(f"rule {r.get('type')!r}: needs a type and w_m / d_m ranges [lo, hi]")
    return out


def _symbols(prims, key, status, rules, k, texts):
    groups = ds.segment(prims, rules["join_tol_m"] * k, rules["contain_max_m"] * k)
    syms, fragments = [], 0
    for g in groups:
        f = ds.features(g, k, rules)
        if f["w_m"] < rules["min_symbol_m"]:
            fragments += 1
            continue
        s = ds.Symbol("", key, status, g, f)
        s.texts = ds.texts_inside(f, texts, rules["text_tol_m"] * k)
        s.kind, s.matches = ds.classify(f, s.texts, rules["rules"])
        syms.append(s)
    syms.sort(key=lambda s: (-round(s.feat["cy"] / k, 1), s.feat["cx"]))
    return syms, fragments


def run(doc, pre: dict, fp: dict) -> dict:
    """{"status", "failures", "unknowns", "flagged", "storeys": [...], "skipped"}; see the module docstring."""
    if problems := validate(fp):
        raise ValueError("the fittings preset is broken: " + "; ".join(problems))
    rules = fp["shape_rules"]
    ex = plan_extract.extract(doc, pre)
    out = {"status": "INDETERMINATE", "failures": [], "unknowns": [], "flagged": [], "storeys": [], "skipped": {}, "units_per_m": ex["k"]}
    if not ex["k"]:
        out["unknowns"].append("drawing units unknown ($INSUNITS): sizes in metres cannot be applied")
        return out
    k = ex["k"]
    info = ex["layers"]
    prims, out["skipped"] = ds.primitives(doc.modelspace(), info, fp["fitting_layers"], rules["flatten_m"] * k)
    texts = plan_extract.ingest(doc, info)["texts"]
    exclude = set(rules.get("exclude_status") or [])
    all_checks: list[tuple[str, Check]] = []
    for st in ex["storeys"]:
        key = st["key"]
        mine = [p for p in prims if p.storey == key]
        live, demolished = [p for p in mine if p.status not in exclude], [p for p in mine if p.status in exclude]
        syms, fragments = _symbols(live, key, "none", rules, k, texts)
        dsyms, dfragments = _symbols(demolished, key, "Abbruch", rules, k, texts)
        labels = [{"id": r["id"], "px": r["anchor"][0], "py": r["anchor"][1]} for r in st["rooms"]]
        outlines = [Polygon(r["outline"]) for r in st["rooms"] if r["outline"]]
        wall_geoms = [LineString([w["p"], w["q"]]) for w in st["walls"]]
        tree = STRtree(wall_geoms) if wall_geoms else None
        for n, s in enumerate(syms, 1):
            s.id = f"{key}-S{n}"
            s.room, s.method, s.method_note = ds_assign(s, labels, outlines, tree, rules["label_max_dist_m"] * k)
        by_room = {r["id"]: [] for r in st["rooms"]}
        for s in syms:
            if s.room and s.kind not in (ds.UNRECOGNISED, ds.AMBIGUOUS):
                by_room[s.room].append(s.kind)
        unrec = [s for s in syms if s.kind in (ds.UNRECOGNISED, ds.AMBIGUOUS)]
        recognised = [s for s in syms if s not in unrec]
        noroom = [s for s in recognised if not s.room]
        wet = [r for r in st["rooms"] if r["wet"]]
        dry_wet = [r for r in wet if not by_room[r["id"]]]
        checks = [
            Check("F1", "Every symbol is classified", UNK if unrec else MATCH,
                  (f"{len(unrec)} of {len(syms)} symbols are unrecognised or ambiguous (listed with their size, kept out of the counts)" if unrec else
                   f"all {len(syms)} symbols are recognised"), [{"symbol": s.id, "kind": s.kind, "matches": s.matches, "w_m": s.feat["w_m"], "d_m": s.feat["d_m"],
                                                               "status": UNK} for s in unrec]),
            Check("F2", "Every recognised fitting is in a room", UNK if noroom else MATCH,
                  (f"{len(noroom)} of {len(recognised)} recognised fittings are in no room" if noroom else
                   f"all {len(recognised)} recognised fittings are in a room"), [{"symbol": s.id, "kind": s.kind, "status": UNK} for s in noroom]),
            Check("F3", "Every wet room holds a recognised fitting", DIFF if dry_wet else (MATCH if wet else UNK),
                  (f"{len(dry_wet)} of {len(wet)} wet rooms hold no recognised fitting" if dry_wet else
                   (f"all {len(wet)} wet rooms hold a recognised fitting" if wet else "no wet room found: nothing to check")),
                  [{"room": r["id"], "status": DIFF} for r in dry_wet]),
        ]
        for c in checks:
            all_checks.append((key, c))
        out["storeys"].append({
            "key": key, "label": st["label"], "fragments": fragments,
            "counts": dict(sorted(Counter(s.kind for s in recognised).items())),
            "symbols": [{"id": s.id, "kind": s.kind, "matches": s.matches, "room": s.room, "room_method": s.method, "w_m": s.feat["w_m"],
                         "d_m": s.feat["d_m"], "centre": [round(s.feat["cx"], 6), round(s.feat["cy"], 6)], "primitives": s.feat["primitives"]} for s in syms],
            "rooms": [{"id": r["id"], "wet": r["wet"], "fittings": sorted(by_room[r["id"]])} for r in st["rooms"]],
            "demolished": {"symbols": len(dsyms), "fragments": dfragments, "kinds": dict(sorted(Counter(s.kind for s in dsyms).items()))},
            "checks": [c.as_dict() for c in checks]})
    flagged_ids = ("F1", "F2")
    out["failures"] = [f"[{k_}] {c.id} {c.title}: {c.detail}" for k_, c in all_checks if c.status == DIFF]
    out["flagged"] = [{"scope": k_, "id": c.id, "title": c.title, "detail": c.detail} for k_, c in all_checks if c.status == UNK and c.id in flagged_ids]
    out["unknowns"] = [f"[{k_}] {c.id} {c.title}: {c.detail}" for k_, c in all_checks if c.status == UNK and c.id not in flagged_ids]
    if not ex["storeys"]:
        out["unknowns"].append("no storey: no layer belongs to a storey")
    out["status"] = "FAIL" if out["failures"] else ("INDETERMINATE" if (out["unknowns"] or out["flagged"]) else "PASS")
    return out


def ds_assign(s, labels, outlines, tree, max_dist):
    """(room id or None, method, note) of a symbol: plan_extract.assign at the symbol's centre."""
    return plan_extract.assign(s.feat["cx"], s.feat["cy"], labels, outlines, tree, max_dist)
