"""Layout checks H1-H9 (vpt/el_checks.py) on made-up rooms and symbols (model units = metres, k = 1) and on the generated
examples of the synthetic flat. Three outcomes each; every check is falsified (a planted defect turns it to 'different')."""
import copy
import json

import pytest

from conftest import ROOT
from vpt import el_checks, el_rules, el_symbols

RULES = el_rules.load()
SET = el_symbols.default_set(el_symbols.load())
V = lambda key: el_rules.value(RULES, "starting", key)
ROOMS = [{"id": "R1", "name": "Wohnzimmer", "wet": False}, {"id": "R2", "name": "Schlafzimmer", "wet": False},
         {"id": "R3", "name": "Küche", "wet": False}, {"id": "R4", "name": "Bad", "wet": True},
         {"id": "R5", "name": "Vorraum", "wet": False}, {"id": "R6", "name": "Abstellraum", "wet": False}]


def sym(i, code, room):
    return {"id": f"s{i}", "code": code, "x": float(i), "y": 0.0, "rotation": 0, "room": room, "room_method": "outline" if room else "could-not-tell"}


def full_layout():
    """A layout that meets every starting value: a light in every room that needs one, enough sockets, a cooker and appliance
    outlets in the kitchen, smoke alarms in the bedroom and the hall."""
    out, n = [], 0

    def add(code, room, times=1):
        nonlocal n
        for _ in range(times):
            n += 1
            out.append(sym(n, code, room))
    for r in ROOMS:
        t = el_checks.room_type(r, RULES, "starting")
        if t in V("check_light_room_types"):
            add("LD", r["id"])
        if t in el_checks.SOCKET_TYPES:
            add("SO", r["id"], V(f"check_min_sockets_{t}"))
        if t in V("check_smoke_room_types"):
            add("RM", r["id"])
    add("HE", "R3")
    add("GS", "R3", V("check_min_appliance_outlets_kitchen") - 1)
    return out


def run(symbols, rooms=ROOMS, set_id="starting", rooms_known=True, rules=RULES):
    return {c["id"]: c for c in el_checks.checks(symbols, [], rooms, [], 1.0, rules, set_id, SET, rooms_known)}


def test_room_types_from_labels_and_the_wet_flag():
    assert [el_checks.room_type(r, RULES, "starting") for r in ROOMS] == ["living", "bedroom", "kitchen", "wet", "hall", "storage"]
    assert el_checks.room_type({"id": "x", "name": "Raum 7", "wet": False}, RULES, "starting") is None


def test_full_layout_room_checks_pass():
    c = run(full_layout())
    assert [c[i]["status"] for i in ("H4", "H5", "H6", "H7", "H9")] == ["match"] * 5
    assert c["H8"]["status"] == "could-not-tell" and "no shower or bath zones" in c["H8"]["detail"]
    assert [x["id"] for x in el_checks.checks(full_layout(), [], ROOMS, [], 1.0, RULES, "starting", SET, True)] == list(el_checks.IDS)


@pytest.mark.parametrize("drop, check", [
    (lambda s: [x for x in s if not (x["code"] == "LD" and x["room"] == "R2")], "H4"),
    (lambda s: [x for x in s if not (x["code"] == "SO" and x["room"] == "R1")][:], "H5"),
    (lambda s: [x for x in s if x["code"] != "HE"], "H6"),
    (lambda s: [x for x in s if x["code"] != "GS"], "H6"),
    (lambda s: [x for x in s if not (x["code"] == "RM" and x["room"] == "R5")], "H7"),
])
def test_each_room_check_goes_red_on_a_planted_defect(drop, check):
    c = run(drop(full_layout()))
    assert c[check]["status"] == "different", c[check]
    assert any(i["status"] == "different" for i in c[check]["items"])


def test_double_socket_counts_two():
    s = [x for x in full_layout() if not (x["code"] == "SO" and x["room"] == "R1")]
    s += [sym(90 + i, "SS2", "R1") for i in range(V("check_min_sockets_living") // 2)]
    assert run(s)["H5"]["status"] == "match"
    s.pop()                                         # one double socket fewer: too few (falsified)
    assert run(s)["H5"]["status"] == "different"


def test_unknown_room_type_could_not_tell():
    rooms = ROOMS + [{"id": "R9", "name": "Raum 7", "wet": False}]
    c = run(full_layout(), rooms=rooms)
    for i in ("H4", "H5", "H7"):
        assert c[i]["status"] == "could-not-tell" and any(x.get("room") == "R9" and x["status"] == "could-not-tell" for x in c[i]["items"]), i


def test_symbol_outside_every_room_could_not_tell():
    s = full_layout() + [sym(99, "SO", None)]
    c = run(s)
    assert c["H9"]["status"] == "could-not-tell" and c["H9"]["items"] == [{"symbol": "s99", "status": "could-not-tell", "why": "outside every room"}]


def test_elektroplaner_null_values_could_not_tell():
    c = run(full_layout(), set_id="elektroplaner")
    for i in ("H3", "H4", "H5", "H6", "H7"):
        assert c[i]["status"] == "could-not-tell" and "no value yet" in c[i]["detail"], i


def test_one_null_threshold_only_switches_off_its_check():
    r = copy.deepcopy(RULES)
    r["values"]["starting"]["check_smoke_room_types"]["value"] = None
    c = run(full_layout(), rules=r)
    assert c["H7"]["status"] == "could-not-tell" and c["H4"]["status"] == c["H5"]["status"] == c["H6"]["status"] == "match"


def test_no_rooms_could_not_tell():
    c = run(full_layout(), rooms_known=False)
    assert all(c[i]["status"] == "could-not-tell" for i in ("H4", "H5", "H6", "H7"))


@pytest.mark.parametrize("plant, expect", [
    (lambda r: r["values"]["starting"]["check_min_sockets_living"].__setitem__("value", -1), "check_min_sockets_living"),
    (lambda r: r["values"]["starting"]["check_min_sockets_living"].__setitem__("value", 2.5), "check_min_sockets_living"),
    (lambda r: r["values"]["starting"]["check_smoke_room_types"].__setitem__("value", ["attic"]), "check_smoke_room_types"),
    (lambda r: r["values"]["starting"]["room_words_hall"].__setitem__("value", []), "room_words_hall"),
    (lambda r: r["checks"].__setitem__("cooker_codes", ["ZZ"]), "cooker_codes"),
    (lambda r: r["checks"].__setitem__("socket_category", "nope"), "socket_category"),
    (lambda r: r["checks"]["room_types"].append("attic"), "room_words_attic"),
])
def test_validate_catches_planted_check_defects(plant, expect):
    r = copy.deepcopy(RULES)
    plant(r)
    probs = el_rules.validate(r, el_symbols.load())
    assert probs and any(expect in p for p in probs), probs


def test_the_complex_example_meets_every_room_check():
    plan = json.loads((ROOT / "samples" / "synthetic_flat.plan.json").read_text(encoding="utf-8"))
    st = next(s for s in plan["storeys"] if s["examples"])
    ex = st["examples"]["complex"]
    c = {x["id"]: x for x in el_checks.checks(ex["symbols"], ex["links"], st["rooms"], st["doors"], plan["drawing"]["units_per_m"], RULES, "starting", SET, True)}
    assert [c[i]["status"] for i in ("H1", "H2", "H3", "H4", "H5", "H6", "H7")] == ["match"] * 7
    assert c["H8"]["status"] == "could-not-tell"
