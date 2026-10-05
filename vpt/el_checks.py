"""The layout checks of the electrical editor (step 4): what a finished layout of one storey should have, each with three
outcomes: match (shown as "ok"), different ("to look at") and could-not-tell. The page mirrors checks() in JavaScript (same
ids, details and items; tools/check_editor.py compares the two on the example layouts).

    H1  every light is worked by a switch                        (vpt/el_links.py hints)
    H2  every switch works a light                               (vpt/el_links.py hints)
    H3  every door of a room with a light has a switch nearby    (vpt/el_links.py hints; hint_switch_near_door_m)
    H4  every room of the check_light_room_types has a light
    H5  every room has at least check_min_sockets_<type> socket outlets (living, bedroom, kitchen, wet, hall)
    H6  every kitchen has a cooker outlet and at least check_min_appliance_outlets_kitchen appliance outlets
    H7  every room of the check_smoke_room_types has a smoke alarm (the Austrian rules on smoke alarms were not checked)
    H8  sockets in wet rooms outside the shower and bath zones: always could-not-tell (the plan knows no zones)
    H9  no symbol outside every room (a symbol whose room could not be told: could-not-tell)

A room's type (room_type()): kitchen (a kitchen_keywords word in its label), wet (the plan marks it a wet room), then living,
bedroom, hall, storage (a room_words_<type> word); none fits: could not tell. Which symbols count: presets/el_rules_at.json
checks. The thresholds and word lists are rules of presets/el_parameters.json: starting values to confirm, and the Elektroplaner
set is null (a check that needs a null value: could not tell, "no value yet"). None of them comes from a standard.
"""
from __future__ import annotations

from vpt import el_links

MATCH, DIFF, UNK = "match", "different", "could-not-tell"
IDS = ("H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8", "H9")
SOCKET_TYPES = ("living", "bedroom", "kitchen", "wet", "hall")


def _val(rules: dict, set_id: str, key: str):
    v = (rules["values"].get(set_id) or {}).get(key)
    return None if v is None else v.get("value")


def _missing(rules: dict, set_id: str, keys: list[str]) -> dict | None:
    gone = [k for k in keys if _val(rules, set_id, k) is None]
    return {"items": [], "status": UNK, "detail": f"no value yet: {', '.join(gone)} (rule set {set_id})"} if gone else None


def type_keys(rules: dict) -> list[str]:
    """The rules a room's type is told from."""
    return ["kitchen_keywords"] + [f"room_words_{t}" for t in rules["checks"]["room_types"] if t not in ("kitchen", "wet")]


def room_type(room: dict, rules: dict, set_id: str) -> str | None:
    """kitchen / wet / living / bedroom / hall / storage, or None (could not tell). The type words must have values."""
    name = (room.get("name") or "").lower()
    for t in rules["checks"]["room_types"]:
        if t == "kitchen":
            if any(w.lower() in name for w in _val(rules, set_id, "kitchen_keywords") or []):
                return t
        elif t == "wet":
            if room.get("wet"):
                return t
        elif any(w.lower() in name for w in _val(rules, set_id, f"room_words_{t}") or []):
            return t
    return None


def _status(items: list[dict], nothing: bool) -> str:
    return el_links._status(items, nothing)


def _cat(set_def: dict, code: str) -> str | None:
    d = el_links._def(set_def, code)
    return d["category"] if d else None


def checks(symbols: list[dict], links: list[dict], rooms: list[dict], doors: list[dict], k: float | None, rules: dict, set_id: str,
           set_def: dict, rooms_known: bool) -> list[dict]:
    """[H1 .. H9]: {"id", "status", "detail", "items": [{"symbol"|"room", "door"?, "status", "why"}]}. rooms: [{id, name, wet}]."""
    out = {h["id"]: h for h in el_links.hints(symbols, links, doors, k, rules, set_id, set_def, rooms_known)}
    ck = rules["checks"]
    in_room: dict[str, list[dict]] = {}
    for s in symbols:
        if s.get("room"):
            in_room.setdefault(s["room"], []).append(s)
    no_rooms = {"items": [], "status": UNK, "detail": "the plan has no rooms: could not tell"} if not rooms_known or not rooms else None
    types = {r["id"]: room_type(r, rules, set_id) for r in rooms}
    unk_type = lambda r: {"room": r["id"], "status": UNK, "why": "the room's type could not be told from its label"}

    # H4 a light in every room that needs one
    h = no_rooms or _missing(rules, set_id, type_keys(rules) + ["check_light_room_types"])
    if h is None:
        need, items = _val(rules, set_id, "check_light_room_types"), []
        for r in rooms:
            if types[r["id"]] is None:
                items.append(unk_type(r))
            elif types[r["id"]] in need:
                n = sum(1 for s in in_room.get(r["id"], []) if el_links.is_light(set_def, rules["switching"], s["code"]))
                items.append({"room": r["id"], "status": MATCH if n else DIFF, "why": f"{n} light(s)" if n else "no light"})
        bad = sum(1 for i in items if i["status"] == DIFF)
        h = {"items": items, "status": _status(items, not items),
             "detail": f"{bad} of {sum(1 for i in items if i['status'] != UNK)} room(s) that need a light have none"
                       if items else "no room of the types that need a light: nothing to check"}
    out["H4"] = dict(h, id="H4")

    # H5 socket outlets per room
    keys = [f"check_min_sockets_{t}" for t in SOCKET_TYPES]
    h = no_rooms or _missing(rules, set_id, type_keys(rules) + keys)
    if h is None:
        items = []
        per = ck.get("outlets_per_symbol") or {}
        for r in rooms:
            t = types[r["id"]]
            if t is None:
                items.append(unk_type(r))
                continue
            if t not in SOCKET_TYPES:
                continue
            want = _val(rules, set_id, f"check_min_sockets_{t}")
            n = sum(per.get(s["code"], 1) for s in in_room.get(r["id"], []) if _cat(set_def, s["code"]) == ck["socket_category"])
            items.append({"room": r["id"], "status": MATCH if n >= want else DIFF, "why": f"{n} of at least {want} socket outlet(s) ({t})"})
        bad = sum(1 for i in items if i["status"] == DIFF)
        h = {"items": items, "status": _status(items, not items),
             "detail": f"{bad} room(s) with fewer socket outlets than our starting minimum" if items else "no room of a type with a minimum: nothing to check"}
    out["H5"] = dict(h, id="H5")

    # H6 kitchens: a cooker outlet and enough appliance outlets
    h = no_rooms or _missing(rules, set_id, type_keys(rules) + ["check_min_appliance_outlets_kitchen"])
    if h is None:
        want, items = _val(rules, set_id, "check_min_appliance_outlets_kitchen"), []
        for r in rooms:
            if types[r["id"]] != "kitchen":
                continue
            mine = in_room.get(r["id"], [])
            cooker = any(s["code"] in ck["cooker_codes"] for s in mine)
            n = sum(1 for s in mine if _cat(set_def, s["code"]) == ck["appliance_category"])
            ok = cooker and n >= want
            items.append({"room": r["id"], "status": MATCH if ok else DIFF,
                          "why": f"{'a' if cooker else 'no'} cooker outlet, {n} of at least {want} appliance outlet(s)"})
        bad = sum(1 for i in items if i["status"] == DIFF)
        h = {"items": items, "status": _status(items, not items),
             "detail": f"{bad} of {len(items)} kitchen(s) without a cooker outlet or with too few appliance outlets" if items else "no kitchen in the plan: nothing to check"}
    out["H6"] = dict(h, id="H6")

    # H7 smoke alarms
    h = no_rooms or _missing(rules, set_id, type_keys(rules) + ["check_smoke_room_types"])
    if h is None:
        need, items = _val(rules, set_id, "check_smoke_room_types"), []
        for r in rooms:
            if types[r["id"]] is None:
                items.append(unk_type(r))
            elif types[r["id"]] in need:
                ok = any(s["code"] in ck["smoke_codes"] for s in in_room.get(r["id"], []))
                items.append({"room": r["id"], "status": MATCH if ok else DIFF, "why": "a smoke alarm" if ok else "no smoke alarm"})
        bad = sum(1 for i in items if i["status"] == DIFF)
        h = {"items": items, "status": _status(items, not items),
             "detail": (f"{bad} room(s) without a smoke alarm (our starting rule; Austrian rules not checked)" if items
                        else "no room of the types that need a smoke alarm: nothing to check")}
    out["H7"] = dict(h, id="H7")

    # H8 wet-room zones: out of scope
    wet = {r["id"] for r in rooms if r.get("wet")}
    ws = [s for s in symbols if s.get("room") in wet and _cat(set_def, s["code"]) == ck["socket_category"]]
    out["H8"] = {"id": "H8", "status": UNK, "items": [{"symbol": s["id"], "status": UNK, "why": "zones unknown"} for s in ws],
                 "detail": f"no shower or bath zones are known in the plan: could not tell ({len(ws)} socket(s) in wet rooms)"}

    # H9 symbols outside every room
    lost = [{"symbol": s["id"], "status": UNK, "why": "outside every room"} for s in symbols if not s.get("room")]
    out["H9"] = {"id": "H9", "items": lost, "status": UNK if lost or not symbols else MATCH,
                 "detail": "no symbol placed: nothing to check" if not symbols else f"{len(lost)} of {len(symbols)} symbol(s) outside every room"}
    return [out[i] for i in IDS]


def counts(results: list[dict]) -> dict[str, int]:
    return {s: sum(1 for c in results if c["status"] == s) for s in (MATCH, DIFF, UNK)}
