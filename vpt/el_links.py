"""Switch-light links of the electrical editor: which switch or push-button works which light, the light groups, the
switch-type proposal and the layout hints. The editor page mirrors these functions in JavaScript (same names, same rules);
tools/check_editor.py compares the page's groups and proposals with these on the example layouts.

A link goes FROM a symbol of the switch category (presets/el_rules_at.json switching.switch_category) TO a symbol whose code is
in the switch's connectable_to list (presets/el_symbols_at.json). A light group is a connected set of switches and lights.
Proposal from the number of switches n in a group: 1 Ausschaltung (one-way), 2 Wechselschaltung (two two-way), 3+
Kreuzschaltung (two two-way + n-2 intermediate); a group with a push-button: none (Tasterschaltung). The proposal keeps a
switch's code when the proposal needs that code, and fills the rest in id order.
Hints (each match / different / could-not-tell):
  H1 lights with no switch     H2 switches with no light
  H3 rooms with a light and a door without a switch within hint_switch_near_door_m of the door's opening (could not tell: no
     value yet, the light's room unknown, no door of the room known, or the plan has no rooms and doors).
"""
from __future__ import annotations

import math

MATCH, DIFF, UNK = "match", "different", "could-not-tell"


def _num(sid: str) -> int:
    return int(sid[1:]) if sid[1:].isdigit() else 0


def _def(set_def: dict, code: str) -> dict | None:
    return next((x for x in set_def["symbols"] if x["code"] == code), None)


def is_switch(set_def: dict, sw: dict, code: str) -> bool:
    d = _def(set_def, code)
    return bool(d) and d["category"] == sw["switch_category"]


def is_light(set_def: dict, sw: dict, code: str) -> bool:
    d = _def(set_def, code)
    return bool(d) and d["category"] == sw["light_category"]


def can_link(set_def: dict, sw: dict, from_code: str, to_code: str) -> tuple[bool, str]:
    d = _def(set_def, from_code)
    if d is None or not is_switch(set_def, sw, from_code):
        return False, f"{from_code} is not a switch or push-button: a link starts at a switch"
    if to_code not in d["connectable_to"]:
        return False, f"{to_code} cannot be connected to {from_code} (allowed: {', '.join(d['connectable_to']) or 'none'})"
    return True, ""


def link_problems(symbols: list[dict], links: list[dict], set_def: dict, sw: dict) -> list[str]:
    by_id = {s["id"]: s for s in symbols}
    out, seen_ids, seen_pairs = [], set(), set()
    for ln in links:
        if ln["id"] in seen_ids:
            out.append(f"duplicate link id {ln['id']}")
        seen_ids.add(ln["id"])
        a, b = by_id.get(ln["from"]), by_id.get(ln["to"])
        if a is None or b is None:
            out.append(f"link {ln['id']}: unknown symbol {ln['from'] if a is None else ln['to']}")
            continue
        if a["id"] == b["id"]:
            out.append(f"link {ln['id']}: a symbol linked to itself")
            continue
        ok, why = can_link(set_def, sw, a["code"], b["code"])
        if not ok:
            out.append(f"link {ln['id']}: {why}")
        if (a["id"], b["id"]) in seen_pairs:
            out.append(f"link {ln['id']}: {a['id']} -> {b['id']} linked twice")
        seen_pairs.add((a["id"], b["id"]))
    return out


def groups(symbols: list[dict], links: list[dict]) -> list[dict]:
    """Connected switch-light sets: [{"switches": [ids], "lights": [ids]}], ids in number order, groups ordered by their first
    light."""
    parent: dict[str, str] = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    known = {s["id"] for s in symbols}
    for ln in links:
        if ln["from"] in known and ln["to"] in known:
            parent[find(ln["from"])] = find(ln["to"])
    comp: dict[str, dict] = {}
    froms = {ln["from"] for ln in links}
    for ln in links:
        for x in (ln["from"], ln["to"]):
            if x not in known:
                continue
            g = comp.setdefault(find(x), {"switches": set(), "lights": set()})
            g["switches" if x in froms else "lights"].add(x)
    out = [{"switches": sorted(g["switches"], key=_num), "lights": sorted(g["lights"], key=_num)} for g in comp.values()]
    return sorted(out, key=lambda g: _num((g["lights"] or g["switches"])[0]))


def proposal(switches: list[tuple[str, str]], sw: dict) -> dict:
    """switches: [(id, current code)]. {"type": "1"|"2"|"3"|"push", "name", "name_en", "codes": {id: code}, "matches"}."""
    sw_sorted = sorted(switches, key=lambda t: _num(t[0]))
    if any(c == sw["push_button"] for _, c in sw_sorted):
        return {"type": "push", "name": sw["names"]["push"], "name_en": sw["names_en"]["push"], "codes": dict(sw_sorted), "matches": True}
    n = len(sw_sorted)
    typ = "1" if n == 1 else "2" if n == 2 else "3"
    want = [sw["one_way"]] if n == 1 else [sw["two_way"]] * 2 + [sw["intermediate"]] * max(0, n - 2)
    pool = list(want)
    codes, rest = {}, []
    for sid, c in sw_sorted:
        if c in pool:
            codes[sid] = c
            pool.remove(c)
        else:
            rest.append(sid)
    for sid in rest:
        codes[sid] = pool.pop(0)
    return {"type": typ, "name": sw["names"][typ], "name_en": sw["names_en"][typ], "codes": codes,
            "matches": all(codes[sid] == c for sid, c in sw_sorted)}


def apply_proposal(symbols: list[dict], links: list[dict], group_index: int, sw: dict) -> list[dict]:
    """A copy of symbols with the switches of group group_index swapped to the proposed codes (the input is not changed)."""
    g = groups(symbols, links)[group_index]
    by_id = {s["id"]: s for s in symbols}
    p = proposal([(sid, by_id[sid]["code"]) for sid in g["switches"]], sw)
    return [dict(s, code=p["codes"].get(s["id"], s["code"])) for s in symbols]


def _seg_dist(p, a, b) -> float:
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def _door_segments(d: dict) -> list:
    if not d.get("hinge") or not d.get("ends"):
        return []
    if d.get("closed_end") in ("a", "b"):
        return [(d["hinge"], d["ends"][d["closed_end"]])]
    return [(d["hinge"], d["ends"]["a"]), (d["hinge"], d["ends"]["b"])]


def _status(items: list[dict], nothing: bool) -> str:
    if nothing:
        return UNK
    if any(i["status"] == DIFF for i in items):
        return DIFF
    if any(i["status"] == UNK for i in items):
        return UNK
    return MATCH


def hints(symbols: list[dict], links: list[dict], doors: list[dict], k: float | None, rules: dict, set_id: str, set_def: dict,
          rooms_known: bool) -> list[dict]:
    """[H1, H2, H3]: {"id", "status", "detail", "items": [{"symbol"|"room", "door"?, "status", "why"}]}."""
    sw = rules["switching"]
    lights = [s for s in symbols if is_light(set_def, sw, s["code"])]
    switches = [s for s in symbols if is_switch(set_def, sw, s["code"])]
    linked_to = {ln["to"] for ln in links}
    linked_from = {ln["from"] for ln in links}
    i1 = [{"symbol": s["id"], "status": DIFF, "why": "no switch works this light"} for s in lights if s["id"] not in linked_to]
    i2 = [{"symbol": s["id"], "status": DIFF, "why": "this switch works no light"} for s in switches if s["id"] not in linked_from]
    h1 = {"id": "H1", "items": i1, "status": _status(i1, not lights),
          "detail": "no light placed: nothing to check" if not lights else f"{len(i1)} of {len(lights)} light(s) without a switch"}
    h2 = {"id": "H2", "items": i2, "status": _status(i2, not switches),
          "detail": "no switch placed: nothing to check" if not switches else f"{len(i2)} of {len(switches)} switch(es) without a light"}
    near = (rules["values"].get(set_id) or {}).get("hint_switch_near_door_m", {}).get("value")
    if not lights:
        h3 = {"id": "H3", "items": [], "status": UNK, "detail": "no light placed: nothing to check"}
    elif near is None:
        h3 = {"id": "H3", "items": [], "status": UNK, "detail": f"no value yet: hint_switch_near_door_m (rule set {set_id})"}
    elif not rooms_known or not k:
        h3 = {"id": "H3", "items": [], "status": UNK, "detail": "the plan has no rooms and doors: could not tell"}
    else:
        items = []
        for s in lights:
            if not s.get("room"):
                items.append({"symbol": s["id"], "status": UNK, "why": "the light's room could not be told"})
        for rid in sorted({s["room"] for s in lights if s.get("room")}, key=lambda r: (len(r), r)):
            ds = [d for d in doors if rid in (d.get("rooms") or [])]
            if not ds:
                items.append({"room": rid, "status": UNK, "why": "no door of this room known (plan file)"})
                continue
            for d in ds:
                segs = _door_segments(d)
                if not segs:
                    items.append({"room": rid, "door": d["id"], "status": UNK, "why": "the door's position is not known"})
                    continue
                dist = min((_seg_dist((s["x"], s["y"]), a, b) for s in switches for a, b in segs), default=math.inf)
                items.append({"room": rid, "door": d["id"], "status": MATCH if dist <= near * k else DIFF,
                              "why": "a switch at the door" if dist <= near * k else f"no switch within {near:g} m of the door"})
        bad = sum(1 for i in items if i["status"] == DIFF)
        h3 = {"id": "H3", "items": items, "status": _status(items, not items),
              "detail": f"{bad} door(s) of rooms with a light have no switch within {near:g} m"}
    return [h1, h2, h3]
