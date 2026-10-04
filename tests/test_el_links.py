"""Switch-light links (vpt/el_links.py): link validity by the symbols' connectable_to lists, light groups, the switch-type
proposal (1 / 2 / 3+ switches, push-buttons) and the layout hints with their three outcomes. Made-up symbols and coordinates
only (model units = metres). Every check is falsified (a planted defect must be caught)."""
from vpt import el_links, el_rules, el_symbols
import copy

import pytest


RULES = el_rules.load()
SW = RULES["switching"]
SET = el_symbols.default_set(el_symbols.load())


def sym(i, code, x=0.0, y=0.0, room="st1-R1"):
    return {"id": f"s{i}", "code": code, "x": x, "y": y, "rotation": 0, "room": room, "room_method": "outline" if room else "could-not-tell"}


def link(i, a, b):
    return {"id": f"l{i}", "from": f"s{a}", "to": f"s{b}"}


# ---- validity ---------------------------------------------------------------------------------------------------------------

def test_valid_links_have_no_problems():
    syms = [sym(1, "SA"), sym(2, "LD"), sym(3, "ST"), sym(4, "LW")]
    assert el_links.link_problems(syms, [link(1, 1, 2), link(2, 3, 4), link(3, 1, 4)], SET, SW) == []


@pytest.mark.parametrize("links, expect", [
    ([link(1, 2, 1)], "not a switch"),                       # from a light
    ([link(1, 1, 3)], "cannot be connected"),               # SA -> SS1 (not in SA's list)
    ([link(1, 1, 9)], "unknown"),                            # no such symbol
    ([link(1, 1, 2), link(2, 1, 2)], "twice"),               # the same pair twice
    ([link(1, 1, 2), link(1, 1, 4)], "duplicate link id"),
    ([link(1, 1, 1)], "itself"),
])
def test_invalid_links_are_caught(links, expect):
    syms = [sym(1, "SA"), sym(2, "LD"), sym(3, "SS1"), sym(4, "LW")]
    probs = el_links.link_problems(syms, links, SET, SW)
    assert probs and any(expect in p for p in probs), probs


def test_can_link_uses_the_library_lists():
    assert el_links.can_link(SET, SW, "SW", "LD") == (True, "")
    ok, why = el_links.can_link(SET, SW, "SA", "SS2")
    assert not ok and "LD" in why                            # the message names what is allowed
    ok, why = el_links.can_link(SET, SW, "LD", "SA")
    assert not ok and "not a switch" in why
    s2 = copy.deepcopy(SET)                                  # falsified: take LD out of SA's list -> refused
    next(x for x in s2["symbols"] if x["code"] == "SA")["connectable_to"].remove("LD")
    assert el_links.can_link(s2, SW, "SA", "LD")[0] is False


# ---- groups and the switch-type proposal ------------------------------------------------------------------------------------

def test_groups_are_lights_sharing_switches():
    syms = [sym(1, "SA"), sym(2, "SA"), sym(3, "LD"), sym(4, "LD"), sym(5, "SA"), sym(6, "LD")]
    g = el_links.groups(syms, [link(1, 1, 3), link(2, 2, 3), link(3, 2, 4), link(4, 5, 6)])
    assert g == [{"switches": ["s1", "s2"], "lights": ["s3", "s4"]}, {"switches": ["s5"], "lights": ["s6"]}]


@pytest.mark.parametrize("codes, typ, want", [
    (["SA"], "1", ["SA"]),
    (["SW"], "1", ["SA"]),
    (["SA", "SA"], "2", ["SW", "SW"]),
    (["SA", "SA", "SA"], "3", ["SW", "SW", "SK"]),
    (["SA", "SK", "SA", "SA"], "3", ["SW", "SK", "SW", "SK"]),   # an intermediate already placed stays one
])
def test_proposal_by_number_of_switches(codes, typ, want):
    p = el_links.proposal([(f"s{i}", c) for i, c in enumerate(codes, 1)], SW)
    assert p["type"] == typ and [p["codes"][f"s{i}"] for i in range(1, len(codes) + 1)] == want
    assert p["name"] == SW["names"][typ]
    assert p["matches"] == (codes == want)


def test_proposal_names_and_falsified():
    assert el_links.proposal([("s1", "SA"), ("s2", "SA")], SW)["name"] == "Wechselschaltung"
    assert el_links.proposal([("s1", "SW"), ("s2", "SW")], SW)["matches"] is True
    # falsified: a proposal that only looked at the first switch would say Ausschaltung for two
    assert el_links.proposal([("s1", "SA"), ("s2", "SA")], SW)["type"] != "1"


def test_push_button_group_gets_no_proposal():
    p = el_links.proposal([("s1", "ST"), ("s2", "ST"), ("s3", "ST")], SW)
    assert p["type"] == "push" and p["codes"] == {"s1": "ST", "s2": "ST", "s3": "ST"} and p["matches"] is True


def test_apply_swaps_only_the_group_switches():
    syms = [sym(1, "SA"), sym(2, "SA"), sym(3, "LD"), sym(4, "SA"), sym(5, "LD")]
    links = [link(1, 1, 3), link(2, 2, 3), link(3, 4, 5)]
    out = el_links.apply_proposal(syms, links, 0, SW)
    assert [s["code"] for s in out] == ["SW", "SW", "LD", "SA", "LD"]
    assert [s["code"] for s in syms] == ["SA", "SA", "LD", "SA", "LD"]      # the input is not changed
    assert el_links.link_problems(out, links, SET, SW) == []                # the links stay valid after the swap


# ---- layout hints -------------------------------------------------------------------------------------------------------------

DOORS = [{"id": "st1-D1", "hinge": [1.0, 0.0], "ends": {"a": [2.0, 0.0], "b": [1.0, 1.0]}, "closed_end": "a", "rooms": ["st1-R1"]},
         {"id": "st1-D2", "hinge": [4.0, 1.0], "ends": {"a": [4.0, 2.0], "b": [3.0, 1.0]}, "closed_end": "a", "rooms": ["st1-R1", "st1-R2"]}]


def hints(syms, links, doors=DOORS, rooms_known=True, set_id="starting", rules=RULES):
    return {h["id"]: h for h in el_links.hints(syms, links, doors, 1.0, rules, set_id, SET, rooms_known)}


def test_hints_all_clear():
    syms = [sym(1, "SW", 2.15, 0.15), sym(2, "SW", 3.85, 2.15), sym(3, "LD", 2, 1.5)]
    h = hints(syms, [link(1, 1, 3), link(2, 2, 3)])
    assert [h[k]["status"] for k in ("H1", "H2", "H3")] == ["match", "match", "match"]


def test_hint_light_without_switch_and_switch_without_light():
    syms = [sym(1, "SA", 2.15, 0.15), sym(2, "LD", 2, 1.5), sym(3, "LD", 3, 2), sym(4, "SA", 3.85, 2.15)]
    h = hints(syms, [link(1, 1, 2)])
    assert h["H1"]["status"] == "different" and [i["symbol"] for i in h["H1"]["items"]] == ["s3"]
    assert h["H2"]["status"] == "different" and [i["symbol"] for i in h["H2"]["items"]] == ["s4"]


def test_hint_door_without_switch_nearby():
    syms = [sym(1, "SA", 2.15, 0.15), sym(2, "LD", 2, 1.5)]                # a switch at D1 only; D2 has none within 1 m
    h = hints(syms, [link(1, 1, 2)])
    assert h["H3"]["status"] == "different" and [(i["room"], i["door"]) for i in h["H3"]["items"] if i["status"] == "different"] == [("st1-R1", "st1-D2")]
    # falsified: the switch moved to D2 instead -> D1 is the one reported
    syms[0].update(x=3.85, y=2.15)
    h2 = hints(syms, [link(1, 1, 2)])
    assert [i["door"] for i in h2["H3"]["items"] if i["status"] == "different"] == ["st1-D1"]


def test_hints_could_not_tell():
    h = hints([], [])
    assert all(h[k]["status"] == "could-not-tell" for k in ("H1", "H2", "H3"))      # nothing placed: nothing to check
    h = hints([sym(1, "LD", 2, 1.5, room=None)], [])
    assert h["H3"]["status"] == "could-not-tell"                                    # the light's room could not be told
    h = hints([sym(1, "LD", 2, 1.5, room="st1-R7")], [])
    assert h["H3"]["status"] == "could-not-tell" and "no door" in h["H3"]["items"][0]["why"]
    h = hints([sym(1, "LD", 2, 1.5)], [], rooms_known=False)
    assert h["H3"]["status"] == "could-not-tell"
    h = hints([sym(1, "LD", 2, 1.5)], [], set_id="elektroplaner")
    assert h["H3"]["status"] == "could-not-tell" and "no value yet" in h["H3"]["detail"]
    assert h["H1"]["status"] == "different"                                         # H1 needs no rule value: still determinate
