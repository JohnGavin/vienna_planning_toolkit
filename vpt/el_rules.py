"""Placement rules of the electrical editor: presets/el_rules_at.json (structure) and presets/el_parameters.json (the values;
one home for each), checked and applied here. The page only SHOWS what this module computes: the suggestions of every storey
and rule set are written into the plan file by tools/export_plan.py.

Two rule sets with the same keys: 'starting' (starting values, each marked 'starting value – confirm' with a note on where the
idea comes from, never a standard it was not checked against) and 'elektroplaner' (null until provided). A rule whose value is
null gives no suggestion; the notes say 'no value yet: <key>'.

Suggestions, in MODEL coordinates (the drawing's units; k = model units per metre), from the rooms and doors of a storey
(vpt/plan_extract.py: outline, anchor, hinge, ends, closed_end, opens_into / opens_from):
  switch   beside each door of a room, on the room's side, on the HANDLE side (the closed end of the swing arc, opposite the
           hinge), switch_from_frame_m (middle of the range) along the wall beyond the opening's edge and switch_inset_m
           (the side the door opens into: the opening line lies on that wall face) or switch_inset_other_m (the other side) into
           the room. A door whose swing could not be determined: no suggestion (said in the notes).
  socket   the centre of every piece of the room's outline between its door openings and its window openings (an opening cuts
           an outline edge when it runs along it within door_cut_max_m; a window's opening lengthened by window_margin_m at both
           ends), pieces of at least socket_min_piece_m, socket_inset_m off the wall, turned so the symbol's stem points to the
           wall. A room without an outline: could not tell (notes). Windows unknown (version-1 plan): said in the notes.
  light    the room centre: the outline's centroid when it lies inside the outline, else the label point.
  kitchen  rooms whose label contains a kitchen_keywords word: along every wall piece (doors and windows cut out as for
           sockets), kitchen_end_margin_m from its ends, then every kitchen_spacing_m.
Each suggestion: {kind, x, y, rot, room, door?, side?, method?}. Notes per kind: lists of 'id: reason' (ids only, no names).
"""
from __future__ import annotations

import json
import math
import pathlib

from vpt import PRESETS

PRESET = PRESETS / "el_rules_at.json"
MARK = "starting value – confirm"
KINDS = ("switch", "socket", "light", "kitchen")
COLLINEAR_DEG = 2.0         # outline edges within this angle of each other are one wall (simplified outlines split long walls)
PARALLEL_DEG = 10.0         # a door opening must run along an outline edge within this angle to cut it


def load(path: pathlib.Path = PRESET, params: dict | None = None) -> dict:
    """The rules as one dict: the structure from presets/el_rules_at.json (suggest, switching, links) and the PARAMETERS from
    presets/el_parameters.json (rules: default_rule_set, rule_sets, definitions -> "rules", values; sections.snap ->
    settings.snap_radius_m). Each value has one home; this merge is the only place they meet."""
    from vpt import el_params
    base = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    p = params or el_params.load()
    r, snap = p["rules"], p["sections"]["snap"]["values"]["snap_radius_m"]
    return dict(base, default_rule_set=r["default_rule_set"], rule_sets=r["rule_sets"], rules=r["definitions"], values=r["values"],
                settings={"snap_radius_m": snap["value"], "snap_radius_m_note": snap.get("note", "")})


def rule_set(rules: dict, set_id: str) -> dict | None:
    return next((s for s in rules["rule_sets"] if s["id"] == set_id), None)


def value(rules: dict, set_id: str, key: str):
    v = (rules["values"].get(set_id) or {}).get(key)
    return None if v is None else v.get("value")


def validate(rules: dict, lib: dict) -> list[str]:
    """Problems of the rules preset (empty = clean). The export and the editor build refuse a broken preset."""
    out: list[str] = []
    ids = [s.get("id") for s in rules.get("rule_sets") or []]
    if ids[:1] != ["starting"] or "elektroplaner" not in ids:
        out.append(f"rule_sets must be 'starting' (first) and 'elektroplaner', got {ids}")
    if rules.get("default_rule_set") not in ids:
        out.append(f"default_rule_set {rules.get('default_rule_set')!r} is not a rule set")
    keys = set(rules.get("rules") or {})
    for sid in ids:
        vals = (rules.get("values") or {}).get(sid)
        if vals is None:
            out.append(f"rule set {sid}: no values")
            continue
        for k in sorted(keys - set(vals)):
            out.append(f"rule set {sid}: value {k} missing")
        for k in sorted(set(vals) - keys):
            out.append(f"rule set {sid}: value {k} is not a rule")
        for k, v in vals.items():
            if v.get("value") is None:
                continue
            if sid == "starting" and v.get("mark") != MARK:
                out.append(f"rule set {sid}: {k} must carry mark {MARK!r}")
            if not v.get("source"):
                out.append(f"rule set {sid}: {k} has a value but no source")
            x = v["value"]
            if k.endswith("_m") and not (isinstance(x, (int, float)) and x > 0 or isinstance(x, list) and len(x) == 2
                                         and all(isinstance(t, (int, float)) and t >= 0 for t in x) and x[0] <= x[1]):
                out.append(f"rule set {sid}: {k} must be a positive number or a range [from, to] with from <= to, got {x!r}")
            if (k == "kitchen_keywords" or k.startswith("room_words_")) and not (isinstance(x, list) and x and all(isinstance(t, str) and t for t in x)):
                out.append(f"rule set {sid}: {k} must be a list of words")
            if k.endswith("_room_types") and not (isinstance(x, list) and all(t in (rules.get("checks") or {}).get("room_types", []) for t in x)):
                out.append(f"rule set {sid}: {k} must be a list of room types {(rules.get('checks') or {}).get('room_types')}")
            if k.startswith("check_min_") and not (isinstance(x, int) and not isinstance(x, bool) and x >= 0):
                out.append(f"rule set {sid}: {k} must be a whole number of at least 0")
            if k == "ceiling_light_at" and x != "centre":
                out.append(f"rule set {sid}: {k} must be 'centre' (the only rule built) or null")
    sets = lib.get("sets") or []
    all_codes = {x["code"] for s in sets for x in s["symbols"]}
    for kind in KINDS:
        sg = (rules.get("suggest") or {}).get(kind)
        if sg is None:
            out.append(f"suggest.{kind} missing")
            continue
        for c in sg.get("codes") or []:
            if c not in all_codes:
                out.append(f"suggest.{kind}: code {c} is not in the symbol library")
        for k in sg.get("values") or []:
            if k not in keys:
                out.append(f"suggest.{kind}: value {k} is not a rule")
    sw = rules.get("switching") or {}
    for f in ("one_way", "two_way", "intermediate", "push_button"):
        if sw.get(f) not in all_codes:
            out.append(f"switching.{f}: {sw.get(f)!r} is not a symbol code")
    cats = {c["key"] for s in sets for c in s["categories"]}
    for f in ("switch_category", "light_category"):
        if sw.get(f) not in cats:
            out.append(f"switching.{f}: {sw.get(f)!r} is not a symbol category")
    if not (rules.get("links") or {}).get("layer", "").startswith("Elektro"):
        out.append("links.layer must be an Elektro layer")
    ck = rules.get("checks") or {}
    for f in ("socket_category", "appliance_category"):
        if ck.get(f) not in cats:
            out.append(f"checks.{f}: {ck.get(f)!r} is not a symbol category")
    for f in ("cooker_codes", "smoke_codes"):
        if not ck.get(f) or any(c not in all_codes for c in ck[f]):
            out.append(f"checks.{f}: {ck.get(f)!r} must be symbol codes")
    for c, n in (ck.get("outlets_per_symbol") or {}).items():
        if c not in all_codes or not (isinstance(n, int) and n >= 1):
            out.append(f"checks.outlets_per_symbol: {c}: {n!r} must be a symbol code with a whole number of at least 1")
    rt = ck.get("room_types") or []
    if "kitchen" not in rt or "wet" not in rt:
        out.append("checks.room_types must hold kitchen and wet")
    for t in rt:
        if t not in ("kitchen", "wet") and f"room_words_{t}" not in keys:
            out.append(f"checks.room_types: {t} has no rule room_words_{t}")
    st = rules.get("settings") or {}
    if not (isinstance(st.get("snap_radius_m"), (int, float)) and st["snap_radius_m"] > 0):
        out.append("settings.snap_radius_m must be a positive number")
    return out


# ---- input: the rooms and doors of one storey -------------------------------------------------------------------------------

def storey_input(storey: dict | None, k: float | None) -> tuple[list[dict], list[dict], float | None]:
    """(rooms, doors, k) of one storey of vpt/plan_extract.py extract() (or of a plan file's storey); k = model units per metre
    (None when the drawing's units are unknown)."""
    if not storey:
        return [], [], None
    rooms = [{"id": r["id"], "outline": r.get("outline") or None, "anchor": r.get("anchor"), "name": r.get("name")}
             for r in storey.get("rooms") or []]
    doors = [{"id": d["id"], "hinge": d.get("hinge"), "ends": d.get("ends"), "closed_end": d.get("closed_end"),
              "opens_into": d.get("opens_into"), "opens_from": d.get("opens_from"), "rooms": d.get("rooms") or []}
             for d in storey.get("doors") or []]
    return rooms, doors, k


def storey_windows(storey: dict | None) -> list[dict] | None:
    """The window openings [{id, p, q, rooms}] of one storey, or None when the storey does not list them (a version-1 plan
    file: windows unknown)."""
    if not storey or "windows" not in storey:
        return None
    return [{"id": w["id"], "p": w["p"], "q": w["q"], "rooms": w.get("rooms") or []} for w in storey["windows"]]


def window_cuts(windows: list[dict] | None, margin: float) -> list[tuple]:
    """Each window opening p -> q lengthened by margin (model units) at both ends: the stretch of wall the socket and kitchen
    suggestions keep clear of."""
    out = []
    for w in windows or []:
        p, q = tuple(w["p"]), tuple(w["q"])
        u = _unit((q[0] - p[0], q[1] - p[1]))
        out.append(((p[0] - u[0] * margin, p[1] - u[1] * margin), (q[0] + u[0] * margin, q[1] + u[1] * margin)))
    return out


# ---- geometry -----------------------------------------------------------------------------------------------------------------

def _unit(v):
    n = math.hypot(v[0], v[1])
    return (v[0] / n, v[1] / n) if n > 0 else (0.0, 0.0)


def _ring(outline) -> list[tuple[float, float]]:
    pts = [(float(p[0]), float(p[1])) for p in outline]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


def _area2(pts) -> float:
    return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))


def inside(p, pts) -> bool:
    c = False
    j = len(pts) - 1
    for i in range(len(pts)):
        a, b = pts[i], pts[j]
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]:
            c = not c
        j = i
    return c


def centroid(pts) -> tuple[float, float] | None:
    a = _area2(pts)
    if abs(a) < 1e-12:
        return None
    cx = sum((pts[i][0] + pts[(i + 1) % len(pts)][0]) * (pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1])
             for i in range(len(pts)))
    cy = sum((pts[i][1] + pts[(i + 1) % len(pts)][1]) * (pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1])
             for i in range(len(pts)))
    return cx / (3 * a), cy / (3 * a)


def walls_of(outline) -> list[tuple[tuple[float, float], tuple[float, float], tuple[float, float]]]:
    """The outline's walls: (start, end, inward unit normal), consecutive collinear edges merged."""
    pts = _ring(outline)
    if len(pts) < 3:
        return []
    ccw = _area2(pts) > 0
    edges = [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts)) if pts[i] != pts[(i + 1) % len(pts)]]
    tol = math.sin(math.radians(COLLINEAR_DEG))
    merged: list[list] = []
    for a, b in edges:
        u = _unit((b[0] - a[0], b[1] - a[1]))
        if merged:
            pa, pb, pu = merged[-1]
            if abs(pu[0] * u[1] - pu[1] * u[0]) <= tol and pu[0] * u[0] + pu[1] * u[1] > 0:
                merged[-1] = [pa, b, _unit((b[0] - pa[0], b[1] - pa[1]))]
                continue
        merged.append([a, b, u])
    if len(merged) > 1:                      # the ring's last and first edge may be one wall
        pa, pb, pu = merged[-1]
        qa, qb, qu = merged[0]
        if abs(pu[0] * qu[1] - pu[1] * qu[0]) <= tol and pu[0] * qu[0] + pu[1] * qu[1] > 0:
            merged[0] = [pa, qb, _unit((qb[0] - pa[0], qb[1] - pa[1]))]
            merged.pop()
    out = []
    for a, b, u in merged:
        n = (-u[1], u[0]) if ccw else (u[1], -u[0])         # left normal points inside a counter-clockwise ring
        out.append((a, b, n))
    return out


def openings(door: dict) -> list[tuple]:
    """The door's opening segment(s) (hinge -> closed end); both possible ones when the swing could not be determined."""
    if not door.get("hinge") or not door.get("ends"):
        return []
    h = tuple(door["hinge"])
    if door.get("closed_end") in ("a", "b"):
        return [(h, tuple(door["ends"][door["closed_end"]]))]
    return [(h, tuple(door["ends"]["a"])), (h, tuple(door["ends"]["b"]))]


def pieces(a, b, cuts: list[tuple], max_off: float) -> list[tuple[float, float]]:
    """The intervals [t0, t1] (distance along a->b) of the wall a->b left after cutting out every opening (P, Q) that runs along
    it (within PARALLEL_DEG) and lies within max_off of its line."""
    L = math.dist(a, b)
    u = _unit((b[0] - a[0], b[1] - a[1]))
    tol = math.sin(math.radians(PARALLEL_DEG))
    holes = []
    for p, q in cuts:
        w = _unit((q[0] - p[0], q[1] - p[1]))
        if abs(u[0] * w[1] - u[1] * w[0]) > tol:
            continue
        off = lambda r: abs((r[0] - a[0]) * u[1] - (r[1] - a[1]) * u[0])
        if off(p) > max_off or off(q) > max_off:
            continue
        t = sorted(((p[0] - a[0]) * u[0] + (p[1] - a[1]) * u[1], (q[0] - a[0]) * u[0] + (q[1] - a[1]) * u[1]))
        if t[1] > 0 and t[0] < L:
            holes.append((max(0.0, t[0]), min(L, t[1])))
    out, cur = [], 0.0
    for t0, t1 in sorted(holes):
        if t0 > cur:
            out.append((cur, t0))
        cur = max(cur, t1)
    if cur < L:
        out.append((cur, L))
    return out


def stem_rotation(to_wall) -> int:
    """The rotation (0/90/180/270, counter-clockwise in the model) that turns a symbol's stem (+y on the sheet = model -y at
    rotation 0) towards the wall direction to_wall."""
    best, bd = 0, -2.0
    for r in (0, 90, 180, 270):
        s = (math.sin(math.radians(r)), -math.cos(math.radians(r)))
        d = s[0] * to_wall[0] + s[1] * to_wall[1]
        if d > bd + 1e-9:
            best, bd = r, d
    return best


def _r(v: float) -> float:
    return round(v, 6)


# ---- the suggestions ----------------------------------------------------------------------------------------------------------

def suggestions(rooms: list[dict], doors: list[dict], k: float | None, rules: dict, set_id: str,
                windows: list[dict] | None = None) -> dict:
    """{kind: [suggestion], "notes": {kind: [text]}} for one storey and one rule set (see the module docstring). windows: the
    storey's window openings (storey_windows()); None = unknown (said in the socket and kitchen notes)."""
    out: dict = {kind: [] for kind in KINDS}
    notes: dict = {kind: [] for kind in KINDS}
    out["notes"] = notes
    if not k:
        for kind in KINDS:
            notes[kind].append("the drawing's units are unknown (mm_per_unit): could not tell any position")
        return out
    val = lambda key: value(rules, set_id, key)
    missing = {kind: [key for key in rules["suggest"][kind]["values"] if val(key) is None] for kind in KINDS}
    for kind in KINDS:
        if missing[kind]:
            notes[kind].append("no value yet: " + ", ".join(missing[kind]) + f" (rule set {set_id})")
    room_ids = {r["id"] for r in rooms}
    doors_of: dict[str, list[dict]] = {}
    for d in doors:
        for rid in d.get("rooms") or []:
            doors_of.setdefault(rid, []).append(d)

    if not missing["switch"]:
        rng = val("switch_from_frame_m")
        along = (sum(rng) / 2.0 if isinstance(rng, list) else float(rng)) * k
        ins, ins_o = val("switch_inset_m") * k, val("switch_inset_other_m") * k
        for d in doors:
            if d.get("closed_end") not in ("a", "b") or not d.get("ends") or not d.get("hinge"):
                if any(r in room_ids for r in d.get("rooms") or []):
                    notes["switch"].append(f"{d['id']}: swing (hinge side) could not tell: no switch suggestion")
                continue
            h, c = d["hinge"], d["ends"][d["closed_end"]]
            o = d["ends"]["b" if d["closed_end"] == "a" else "a"]
            u = _unit((c[0] - h[0], c[1] - h[1]))
            n = (-u[1], u[0])
            if n[0] * (o[0] - h[0]) + n[1] * (o[1] - h[1]) < 0:
                n = (-n[0], -n[1])                           # n points to the side the door opens into
            for side, sgn, rid, dist in (("into", 1.0, d.get("opens_into"), ins), ("from", -1.0, d.get("opens_from"), ins_o)):
                if not rid or rid not in room_ids:
                    continue
                out["switch"].append({"kind": "switch", "x": _r(c[0] + u[0] * along + sgn * n[0] * dist),
                                      "y": _r(c[1] + u[1] * along + sgn * n[1] * dist), "rot": 0, "room": rid, "door": d["id"], "side": side})

    if windows is None:
        for kind in ("socket", "kitchen"):
            notes[kind].append("windows unknown (the plan file does not list them): suggestions may sit in a window niche")
    win_cuts = window_cuts(windows, (val("window_margin_m") or 0.0) * k)

    def wall_pieces(r):
        cuts = [s for d in doors_of.get(r["id"], []) for s in openings(d)] + win_cuts
        for a, b, n in walls_of(r["outline"]):
            u = _unit((b[0] - a[0], b[1] - a[1]))
            for t0, t1 in pieces(a, b, cuts, val("door_cut_max_m") * k):
                yield a, u, n, t0, t1

    if not missing["socket"]:
        lo, ins = val("socket_min_piece_m") * k, val("socket_inset_m") * k
        for r in rooms:
            if not r.get("outline"):
                notes["socket"].append(f"{r['id']}: no outline: could not tell its walls")
                continue
            for a, u, n, t0, t1 in wall_pieces(r):
                if t1 - t0 < lo:
                    continue
                t = (t0 + t1) / 2.0
                out["socket"].append({"kind": "socket", "x": _r(a[0] + u[0] * t + n[0] * ins), "y": _r(a[1] + u[1] * t + n[1] * ins),
                                      "rot": stem_rotation((-n[0], -n[1])), "room": r["id"]})

    if not missing["light"]:
        for r in rooms:
            c, method = None, None
            if r.get("outline"):
                pts = _ring(r["outline"])
                cc = centroid(pts) if len(pts) >= 3 else None
                if cc and inside(cc, pts):
                    c, method = cc, "outline centre"
                else:
                    method = "label point (the outline's centre lies outside it)"
            else:
                method = "label point (no outline)"
            if c is None:
                if not r.get("anchor"):
                    notes["light"].append(f"{r['id']}: no outline and no label point: could not tell")
                    continue
                c = r["anchor"]
            out["light"].append({"kind": "light", "x": _r(c[0]), "y": _r(c[1]), "rot": 0, "room": r["id"], "method": method})

    if not missing["kitchen"]:
        words = [w.lower() for w in val("kitchen_keywords")]
        step, margin, ins = val("kitchen_spacing_m") * k, val("kitchen_end_margin_m") * k, val("socket_inset_m") * k
        for r in rooms:
            name = (r.get("name") or "").lower()
            if not any(w in name for w in words):
                continue
            if not r.get("outline"):
                notes["kitchen"].append(f"{r['id']}: a kitchen without an outline: could not tell its walls")
                continue
            for a, u, n, t0, t1 in wall_pieces(r):
                t = t0 + margin
                while t <= t1 - margin + 1e-9:
                    out["kitchen"].append({"kind": "kitchen", "x": _r(a[0] + u[0] * t + n[0] * ins), "y": _r(a[1] + u[1] * t + n[1] * ins),
                                           "rot": stem_rotation((-n[0], -n[1])), "room": r["id"]})
                    t += step
    return out


def tips(rules: dict) -> dict:
    """Per rule set and kind: the popup text of its suggestions (rule names, values with their marks, the rule set): written
    once into the page; each marker adds its room and door."""
    out = {}
    for s in rules["rule_sets"]:
        out[s["id"]] = {}
        for kind, sg in rules["suggest"].items():
            vals = []
            for key in sg["values"]:
                v = rules["values"][s["id"]][key]
                x = v.get("value")
                shown = "no value yet" if x is None else ("–".join(f"{t:g}" for t in x) if isinstance(x, list) and all(isinstance(t, (int, float)) for t in x)
                                                          else ", ".join(x) if isinstance(x, list) else (f"{x:g}" if isinstance(x, (int, float)) else str(x)))
                vals.append({"key": key, "label": rules["rules"][key]["label"], "value": shown, "unit": rules["rules"][key]["unit"],
                             "mark": v.get("mark") or ("" if x is None else "Elektroplaner value"), "source": v.get("source") or ""})
            out[s["id"]][kind] = {"name": sg["name"], "rule_set": s["name"], "status": s["status"], "values": vals}
    return out
