"""Example layouts of the electrical editor, GENERATED from the rooms and doors of a plan and the parameters, never placed by
hand: every position is a placement suggestion of vpt/el_rules.py (rule set 'starting'), except the smoke alarm, which sits a
parameter's distance beside its room's ceiling-light suggestion.

  simple   one room: 1 ceiling light at the room-centre suggestion, a two-way switch at the switch suggestion of each of its
           doors (Wechselschaltung, as vpt/el_links.py proposes for two switches), both linked to the light, and
           examples.simple_sockets sockets at its first wall-centre suggestions.
  complex  the whole storey: per room a ceiling light, a switch at every door suggestion of the room with the switch type the
           proposal gives for that many switches, each linked to the light; a socket at every wall-centre suggestion; kitchen
           outlets (examples.kitchen_codes in turn) at every kitchen suggestion; a smoke alarm beside every ceiling light; one
           distribution board at the first wall-centre suggestion of the storey (that spot then gets no socket).

The example storey and room are chosen by STOREY_RULE (recorded in the file). Each example is a layout file of schema version 2
(schema/el_layout.schema.json) with an 'example' block saying so; the page shows it labelled EXAMPLE and only when the user has
no layout of that storey. Symbol codes, counts and the smoke-alarm distance come from presets/el_parameters.json
sections.examples (their one home).
"""
from __future__ import annotations

import math

from vpt import el_layout, el_links, el_params, el_rules, el_symbols

STOREY_RULE = ("the first storey (in plan order) with a room (in id order) that has an outline, a ceiling-light suggestion, "
               "exactly examples.simple_doors doors with a switch suggestion on the room's side, and at least "
               "examples.simple_sockets wall-centre socket suggestions")
GENERATED_BY = "vpt/el_examples.py"
SAVED = "generated (example, not saved by a user)"


def _ex(params: dict) -> dict:
    return {k: v["value"] for k, v in params["sections"]["examples"]["values"].items()}


def room_of(x: float, y: float, rooms: list[dict], max_units: float | None) -> tuple[str | None, str]:
    """The room a symbol stands in, as the page decides it (roomOf in the page script): inside an outline; else the nearest
    label of a room without an outline within max_units; else could-not-tell."""
    for r in rooms:
        if r.get("outline") and el_rules.inside((x, y), el_rules._ring(r["outline"])):
            return r["id"], "outline"
    best, bd = None, math.inf
    for r in rooms:
        if r.get("outline") or not r.get("anchor"):
            continue
        d = math.hypot(r["anchor"][0] - x, r["anchor"][1] - y)
        if d < bd:
            best, bd = r, d
    if best is not None and max_units is not None and bd <= max_units:
        return best["id"], "nearest label"
    return None, "could-not-tell"


def _door_switches(sug: dict, rid: str) -> list[dict]:
    """The switch suggestions on room rid's side, one per door, in door-id order."""
    seen, out = set(), []
    for s in sorted((s for s in sug["switch"] if s["room"] == rid),
                    key=lambda s: (el_links._num(s["door"].rsplit("-", 1)[-1]) if s.get("door") else 0, s.get("door") or "")):
        if s["door"] not in seen:
            seen.add(s["door"])
            out.append(s)
    return out


def choose(storeys: list[dict], k: float | None, rules: dict, params: dict) -> dict | None:
    """STOREY_RULE: {storey, room, sug, rooms, doors, k} or None when no storey qualifies. storeys: vpt/plan_extract.py storeys."""
    ex = _ex(params)
    for st in storeys:
        rooms, doors, kk = el_rules.storey_input(st, k)
        if not kk:
            continue
        sug = el_rules.suggestions(rooms, doors, kk, rules, "starting")
        for r in sorted(rooms, key=lambda r: (el_links._num(r["id"].rsplit("-", 1)[-1]), r["id"])):
            if (r.get("outline") and any(s["room"] == r["id"] for s in sug["light"])
                    and len(_door_switches(sug, r["id"])) == ex["simple_doors"]
                    and sum(1 for s in sug["socket"] if s["room"] == r["id"]) >= ex["simple_sockets"]):
                return {"storey": st["key"], "room": r["id"], "sug": sug, "rooms": rooms, "doors": doors, "k": kk}
    return None


class _Builder:
    def __init__(self, rooms, max_units):
        self.symbols, self.links, self.rooms, self.max = [], [], rooms, max_units

    def add(self, code: str, x: float, y: float, rot: int = 0) -> str:
        sid = f"s{len(self.symbols) + 1}"
        rid, how = room_of(x, y, self.rooms, self.max)
        self.symbols.append({"id": sid, "code": code, "x": x, "y": y, "rotation": rot, "room": rid, "room_method": how})
        return sid

    def link(self, a: str, b: str) -> None:
        self.links.append({"id": f"l{len(self.links) + 1}", "from": a, "to": b})


def _switch_codes(n: int, sw: dict) -> list[str]:
    """The codes the proposal gives n switches (vpt/el_links.py proposal: 1 one-way, 2 two-way, 3+ two two-way + intermediate)."""
    ids = [f"x{i}" for i in range(1, n + 1)]
    p = el_links.proposal([(i, sw["one_way"]) for i in ids], sw)
    return [p["codes"][i] for i in ids]


def simple(ch: dict, rules: dict, params: dict, max_units: float | None) -> tuple[list[dict], list[dict], list[str]]:
    ex, sug, rid = _ex(params), ch["sug"], ch["room"]
    b = _Builder(ch["rooms"], max_units)
    li = next(s for s in sug["light"] if s["room"] == rid)
    light = b.add(rules["suggest"]["light"]["codes"][0], li["x"], li["y"], li["rot"])
    sws = _door_switches(sug, rid)
    for s, code in zip(sws, _switch_codes(len(sws), rules["switching"])):
        b.link(b.add(code, s["x"], s["y"], s["rot"]), light)
    for s in [s for s in sug["socket"] if s["room"] == rid][:ex["simple_sockets"]]:
        b.add(ex["socket_code"], s["x"], s["y"], s["rot"])
    return b.symbols, b.links, [rid]


def complex_(ch: dict, rules: dict, params: dict, max_units: float | None) -> tuple[list[dict], list[dict], list[str]]:
    ex, sug, k = _ex(params), ch["sug"], ch["k"]
    b = _Builder(ch["rooms"], max_units)
    first_socket = sug["socket"][0] if sug["socket"] else None
    if first_socket:
        b.add(ex["board_code"], first_socket["x"], first_socket["y"], first_socket["rot"])
    used = []
    for r in ch["rooms"]:
        li = next((s for s in sug["light"] if s["room"] == r["id"]), None)
        if li is None:
            continue
        used.append(r["id"])
        light = b.add(rules["suggest"]["light"]["codes"][0], li["x"], li["y"], li["rot"])
        b.add(ex["smoke_code"], round(li["x"] + ex["smoke_offset_m"] * k, 6), li["y"], 0)
        sws = _door_switches(sug, r["id"])
        for s, code in zip(sws, _switch_codes(len(sws), rules["switching"]) if sws else []):
            b.link(b.add(code, s["x"], s["y"], s["rot"]), light)
        for s in sug["socket"]:
            if s["room"] == r["id"] and s is not first_socket:
                b.add(ex["socket_code"], s["x"], s["y"], s["rot"])
        kc = ex["kitchen_codes"]
        for i, s in enumerate(s for s in sug["kitchen"] if s["room"] == r["id"]):
            b.add(kc[i % len(kc)], s["x"], s["y"], s["rot"])
    return b.symbols, b.links, used


def build(storeys: list[dict], *, k: float | None, mm_per_unit: float | None, drawing_file: str, sha256: str,
          background: dict[str, dict], rules: dict | None = None, params: dict | None = None, lib: dict | None = None,
          params_sha256: str | None = None) -> dict:
    """{"storey": key or None, "why": text, "examples": {"simple": layout, "complex": layout}}. storeys: vpt/plan_extract.py
    storeys (key, label, rooms, doors); background: {storey key: {"layers": [shown layers], "hidden_layers": n}}."""
    rules, params, lib = rules or el_rules.load(), params or el_params.load(), lib or el_symbols.load()
    ch = choose(storeys, k, rules, params)
    if ch is None:
        return {"storey": None, "why": "no storey meets the rule: " + STOREY_RULE, "examples": {}}
    st = next(s for s in storeys if s["key"] == ch["storey"])
    cfg = el_layout.load_page(params=params)
    max_units = cfg["room_label_max_m"] * 1000.0 / mm_per_unit if mm_per_unit else None
    sdef = el_symbols.default_set(lib)
    out = {}
    for ex_id, fn, label in (("simple", simple, "simple: one room, two-way switching"), ("complex", complex_, "complex: the whole storey")):
        syms, links, used = fn(ch, rules, params, max_units)
        doc = el_layout.make_layout(drawing_file=drawing_file, sha256=sha256, storey=ch["storey"], storey_label=st.get("label", ch["storey"]),
                                    model_units_mm=mm_per_unit, symbol_set=sdef, background=dict(background[ch["storey"]], copied="example"),
                                    symbols=syms, links=links, saved=SAVED, rule_set="starting", app=GENERATED_BY)
        doc["parameters"] = {"id": params["id"], "version": params["version"], "sha256": params_sha256 or el_params.sha256(), "edited": False}
        doc["example"] = {"id": ex_id, "label": label, "generated_by": GENERATED_BY, "storey_rule": STOREY_RULE, "rooms": used}
        out[ex_id] = doc
    return {"storey": ch["storey"], "why": f"storey {ch['storey']}, room {ch['room']} (rule: {STOREY_RULE})", "examples": out}


def off_suggestion(doc: dict, sug: dict, rules: dict, params: dict, k: float) -> list[str]:
    """Ids of the example's symbols that are NOT where the generator rule puts them: a light, switch, socket, kitchen outlet or
    board on a suggestion point of its kind (socket suggestions for the board), a smoke alarm at examples.smoke_offset_m beside a
    ceiling-light suggestion. Empty = every position is derived (the tests and the browser check use it)."""
    ex = _ex(params)
    kind_of = {c: kind for kind, sg in rules["suggest"].items() for c in sg["codes"]}
    kind_of[ex["socket_code"]] = "socket"
    kind_of[ex["board_code"]] = "socket"
    for c in ex["kitchen_codes"]:
        kind_of[c] = "kitchen"
    at = lambda pts, x, y: any(abs(p["x"] - x) < 1e-6 and abs(p["y"] - y) < 1e-6 for p in pts)
    bad = []
    for s in doc["symbols"]:
        if s["code"] == ex["smoke_code"]:
            ok = any(abs(li["x"] + ex["smoke_offset_m"] * k - s["x"]) < 1e-6 and abs(li["y"] - s["y"]) < 1e-6 for li in sug["light"])
        else:
            ok = s["code"] in kind_of and at(sug[kind_of[s["code"]]], s["x"], s["y"])
        if not ok:
            bad.append(s["id"])
    return bad
