"""Placement rules and suggestions (vpt/el_rules.py; values in presets/el_parameters.json): the two rule sets, and the
suggestion geometry on SYNTHETIC rooms and doors (made-up coordinates, model units = metres, k = 1). Every check is falsified
(a planted defect must be caught)."""
from vpt import el_rules, el_symbols
import copy
import math

import pytest


RULES = el_rules.load()
LIB = el_symbols.load()
SQ = [[0.0, 0.0], [4.0, 0.0], [4.0, 3.0], [0.0, 3.0], [0.0, 0.0]]       # 4 x 3 m room, counter-clockwise, closed ring


def door(did="st1-D1", hinge=(1.0, 0.0), a=(2.0, 0.0), b=(1.0, 1.0), closed="a", into="st1-R1", frm="st1-R2"):
    """A door in the bottom wall: hinge at x=1, closed leaf along the wall to x=2 (end a), open leaf up into R1 (end b)."""
    return {"id": did, "hinge": list(hinge), "ends": {"a": list(a), "b": list(b)}, "closed_end": closed,
            "opens_into": into, "opens_from": frm, "rooms": [r for r in (into, frm) if r]}


def room(rid="st1-R1", outline=SQ, anchor=(2.0, 1.5), name="Zimmer"):
    return {"id": rid, "outline": copy.deepcopy(outline), "anchor": list(anchor), "name": name}


def sug(rooms, doors, set_id="starting", rules=RULES):
    return el_rules.suggestions(rooms, doors, 1.0, rules, set_id)


# ---- the preset ---------------------------------------------------------------------------------------------------------

def test_preset_is_valid():
    assert el_rules.validate(RULES, LIB) == []


def test_two_rule_sets_same_keys_starting_marked_elektroplaner_null():
    ids = [s["id"] for s in RULES["rule_sets"]]
    assert ids == ["starting", "elektroplaner"] and RULES["default_rule_set"] == "starting"
    keys = set(RULES["rules"])
    for sid in ids:
        assert set(RULES["values"][sid]) == keys
    for k, v in RULES["values"]["starting"].items():
        assert v["value"] is not None and v["mark"] == "starting value – confirm" and v["source"], k
        assert "standard" not in v["source"] or "Not checked" in v["source"] or "not from" in v["source"].lower(), k
    assert all(v["value"] is None for v in RULES["values"]["elektroplaner"].values())


@pytest.mark.parametrize("plant, expect", [
    (lambda r: r["values"]["starting"].pop("socket_inset_m"), "socket_inset_m"),
    (lambda r: r["values"]["starting"]["socket_inset_m"].pop("mark"), "mark"),
    (lambda r: r["values"]["starting"]["socket_inset_m"].__setitem__("source", ""), "source"),
    (lambda r: r["values"]["elektroplaner"]["socket_inset_m"].__setitem__("value", 0.2), "source"),
    (lambda r: r["suggest"]["socket"]["codes"].append("ZZ"), "ZZ"),
    (lambda r: r["suggest"]["socket"]["values"].append("nope"), "nope"),
    (lambda r: r.__setitem__("default_rule_set", "x"), "default_rule_set"),
    (lambda r: r["switching"].__setitem__("two_way", "ZZ"), "two_way"),
    (lambda r: r["values"]["starting"]["switch_from_frame_m"].__setitem__("value", [0.3, 0.1]), "switch_from_frame_m"),
])
def test_validate_catches_planted_defects(plant, expect):
    r = copy.deepcopy(RULES)
    plant(r)
    probs = el_rules.validate(r, LIB)
    assert probs and any(expect in p for p in probs), probs


# ---- switch beside the door, handle side, inside the room ---------------------------------------------------------------

def test_switch_handle_side_inside_both_rooms():
    s = sug([room(), room("st1-R2", None, (2.0, -1.5))], [door()])["switch"]
    by_room = {x["room"]: x for x in s}
    assert set(by_room) == {"st1-R1", "st1-R2"}
    # swing side (R1, above the wall): closed end x=2, plus 0.15 (middle of 0.1-0.2) along the wall away from the hinge,
    # plus switch_inset_m 0.15 into the room
    assert (by_room["st1-R1"]["x"], by_room["st1-R1"]["y"]) == pytest.approx((2.15, 0.15))
    # the other side (R2, below): switch_inset_other_m 0.35 the other way
    assert (by_room["st1-R2"]["x"], by_room["st1-R2"]["y"]) == pytest.approx((2.15, -0.35))
    assert all(x["door"] == "st1-D1" and x["kind"] == "switch" for x in s)


def test_switch_follows_the_hinge_mirror():
    # hinge on the right (x=2), closed end at x=1: the switch goes to the left of the opening
    d = door(hinge=(2.0, 0.0), a=(1.0, 0.0), b=(2.0, 1.0))
    p = [x for x in sug([room()], [d])["switch"] if x["room"] == "st1-R1"][0]
    assert (p["x"], p["y"]) == pytest.approx((0.85, 0.15))


def test_switch_handle_side_falsified():
    # the same opening (x=1..2) hinged on the other side must give the other spot: a rule that ignored the hinge (e.g. always
    # the opening's right end) would give the same spot for both and is caught here
    good = [x for x in sug([room()], [door()])["switch"] if x["room"] == "st1-R1"][0]
    other = [x for x in sug([room()], [door(hinge=(2.0, 0.0), a=(1.0, 0.0), b=(2.0, 1.0))])["switch"] if x["room"] == "st1-R1"][0]
    hinge, closed = (1.0, 0.0), (2.0, 0.0)
    assert math.dist((good["x"], good["y"]), closed) < math.dist((good["x"], good["y"]), hinge)
    assert math.dist((good["x"], good["y"]), (other["x"], other["y"])) > 1.0


def test_switch_undetermined_swing_gives_no_suggestion_and_says_so():
    d = dict(door(closed=None, into=None, frm=None), rooms=["st1-R1"])     # the plan: both possible openings gave the same room
    out = sug([room()], [d])
    assert out["switch"] == [] and any("st1-D1" in n and "could not tell" in n for n in out["notes"]["switch"])


def test_switch_side_without_room():
    s = sug([room()], [door(frm=None)])["switch"]
    assert [x["room"] for x in s] == ["st1-R1"]


# ---- sockets: centre of each wall piece between openings ----------------------------------------------------------------

def _pts(lst):
    return sorted((round(x["x"], 6), round(x["y"], 6), x["rot"]) for x in lst)


def test_socket_centres_cut_at_doors_and_turned_to_their_wall():
    s = sug([room()], [door()])["socket"]
    # bottom wall cut by the opening x=1..2: pieces 0..1 (centre 0.5) and 2..4 (centre 3); right, top, left whole.
    # 0.1 off the wall face; the stem points to the wall: bottom 0, right 90, top 180, left 270 (counter-clockwise)
    assert _pts(s) == sorted([(0.5, 0.1, 0), (3.0, 0.1, 0), (3.9, 1.5, 90), (2.0, 2.9, 180), (0.1, 1.5, 270)])
    assert all(x["room"] == "st1-R1" for x in s)


def test_socket_clockwise_outline_same_result():
    cw = list(reversed(SQ))
    assert _pts(sug([room(outline=cw)], [door()])["socket"]) == _pts(sug([room()], [door()])["socket"])


def test_socket_collinear_edges_merged_and_short_pieces_dropped():
    ring = [[0, 0], [2, 0], [4, 0], [4, 3], [0, 3], [0, 0]]                 # bottom wall in two collinear edges
    d = door(hinge=(0.5, 0.0), a=(1.5, 0.0), b=(0.5, 1.0))                  # leaves a 0.5 m piece (< 0.6) at the left
    s = sug([room(outline=ring)], [d])["socket"]
    bottom = [x for x in s if abs(x["y"] - 0.1) < 1e-9]
    assert [round(x["x"], 6) for x in bottom] == [2.75]                     # one piece 1.5..4, not two; 0..0.5 dropped


def test_socket_door_cut_falsified():
    # without the door the bottom wall is one piece: its centre (2, 0.1) appears; with the door it must not
    with_door = _pts(sug([room()], [door()])["socket"])
    no_door = _pts(sug([room()], [])["socket"])
    assert (2.0, 0.1, 0) in no_door and (2.0, 0.1, 0) not in with_door


def test_socket_room_without_outline_could_not_tell():
    out = sug([room(outline=None)], [door()])
    assert out["socket"] == [] and any("st1-R1" in n and "could not tell" in n for n in out["notes"]["socket"])


# ---- ceiling light at the room centre ------------------------------------------------------------------------------------

def test_light_at_outline_centre():
    (p,) = sug([room(anchor=(0.5, 0.5))], [])["light"]
    assert (p["x"], p["y"]) == pytest.approx((2.0, 1.5)) and p["method"] == "outline centre"


def test_light_label_point_without_outline_or_when_centre_outside():
    (p,) = sug([room(outline=None, anchor=(7.0, 8.0))], [])["light"]
    assert (p["x"], p["y"]) == (7.0, 8.0) and "label" in p["method"]
    ell = [[0, 0], [4, 0], [4, 1], [1, 1], [1, 4], [0, 4], [0, 0]]          # L-shape: its centroid lies outside it
    (q,) = sug([room(outline=ell, anchor=(0.5, 0.5))], [])["light"]
    assert (q["x"], q["y"]) == (0.5, 0.5) and "label" in q["method"]


def test_light_centre_falsified():
    (p,) = sug([room(anchor=(0.5, 0.5))], [])["light"]
    assert (p["x"], p["y"]) != pytest.approx((0.5, 0.5))                   # the label point is not the centre: caught


# ---- kitchen outlets -------------------------------------------------------------------------------------------------------

def test_kitchen_outlets_spaced_along_the_walls_only_in_kitchens():
    k_ring = [[0, 0], [3, 0], [3, 2], [0, 2], [0, 0]]
    rooms = [room("st1-R1", k_ring, (1.5, 1.0), "Küche"), room("st1-R2", [[5, 0], [8, 0], [8, 2], [5, 2], [5, 0]], (6.5, 1), "Bad")]
    s = sug(rooms, [])["kitchen"]
    assert {x["room"] for x in s} == {"st1-R1"}
    bottom = sorted(round(x["x"], 6) for x in s if abs(x["y"] - 0.1) < 1e-9)
    assert bottom == [0.3, 0.9, 1.5, 2.1, 2.7]                               # margin 0.3, spacing 0.6 along a 3 m wall
    side = sorted(round(x["y"], 6) for x in s if abs(x["x"] - 2.9) < 1e-9)
    assert side == [0.3, 0.9, 1.5]                                          # 2 m wall: 0.3, 0.9, 1.5 (1.7 is the last allowed)


def test_kitchen_keyword_case_and_falsified():
    k_ring = [[0, 0], [3, 0], [3, 2], [0, 2], [0, 0]]
    assert sug([room("st1-R1", k_ring, (1, 1), "WOHNKÜCHE")], [])["kitchen"]
    assert sug([room("st1-R1", k_ring, (1, 1), "Wohnen")], [])["kitchen"] == []
    assert sug([room("st1-R1", k_ring, (1, 1), None)], [])["kitchen"] == []


# ---- the Elektroplaner set: null values give no suggestion ---------------------------------------------------------------

def test_elektroplaner_null_values_give_no_suggestion():
    out = sug([room(name="Küche")], [door()], set_id="elektroplaner")
    for kind in ("switch", "socket", "light", "kitchen"):
        assert out[kind] == [], kind
        assert any("no value yet" in n for n in out["notes"][kind]), kind


def test_one_null_value_switches_off_only_its_rules_falsified():
    r = copy.deepcopy(RULES)
    r["values"]["starting"]["switch_inset_m"]["value"] = None
    out = sug([room()], [door()], rules=r)
    assert out["switch"] == [] and any("switch_inset_m" in n for n in out["notes"]["switch"])
    assert out["socket"] and out["light"]                                   # the others still suggest
    assert sug([room()], [door()])["switch"]                                # control: with the value there is a suggestion


def test_storey_input_from_a_plan_storey():
    st = {"key": "st1", "rooms": [{"id": "st1-R1", "name": "Küche", "outline": SQ, "anchor": [2, 1.5]},
                                  {"id": "st1-R2", "name": "x", "outline": None, "anchor": [9, 9]}],
          "doors": [{"id": "st1-D1", "hinge": [1, 0], "ends": {"a": [2, 0], "b": [1, 1]}, "closed_end": "a",
                     "opens_into": "st1-R1", "opens_from": None, "rooms": ["st1-R1"]}]}
    rooms, doors, k = el_rules.storey_input(st, 1.0)
    assert [r["id"] for r in rooms] == ["st1-R1", "st1-R2"] and [d["id"] for d in doors] == ["st1-D1"] and k == 1.0
    assert rooms[1]["outline"] is None and rooms[0]["name"] == "Küche"
    assert doors[0]["hinge"] == [1, 0] and doors[0]["ends"]["a"] == [2, 0]
    assert el_rules.storey_input(st, 1000.0)[2] == 1000.0                     # a drawing in mm: 1000 model units per metre
    assert el_rules.storey_input(None, 1.0) == ([], [], None)                 # no storey: nothing, could not tell
