"""Rooms, doors and walls of the synthetic flat (vpt/plan_extract.py), checked against the preset that generated the drawing
(presets/synthetic_flat.json: the one home of the room and door counts and positions). Every check is falsified."""
import copy
import json
import math

import ezdxf
import pytest
from shapely.geometry import Point, box

import synthetic_flat as sf
from conftest import ROOT
from vpt import plan_extract as pe

PRE = json.loads((ROOT / "presets" / "plan_extract.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def flat(generated):
    return pe.extract(ezdxf.readfile(generated[0]), PRE)


def expected_doors(preset):
    """Per preset door: its hinge, closed end and the rooms on both sides, from the preset geometry (independent of the
    extraction): the rooms whose rectangle holds a point half a metre off the opening's middle, on each side of the wall."""
    walls = {w["id"]: sf.Wall(preset, w) for w in preset["walls"]}
    rooms = [(r["name"], box(*sf.rect_of(preset, r))) for r in preset["rooms"]]
    out = []
    for d in preset["doors"]:
        w = walls[d["wall"]]
        a0, a1 = d["from"], d["from"] + d["width"]
        c0, c1 = w.cross
        face = c1 if d["swing"] == "+" else c0
        hinge_a, free_a = (a0, a1) if d["hinge"] == "start" else (a1, a0)
        mid = (a0 + a1) / 2
        sides = set()
        for c in (c0 - 0.5, c1 + 0.5):
            p = Point(*w.pt(mid, c))
            sides.add(next((n for n, g in rooms if g.contains(p)), None))
        out.append({"hinge": w.pt(hinge_a, face), "closed": w.pt(free_a, face), "rooms": sides})
    return out


def test_counts_match_the_preset(flat, preset):
    (st,) = flat["storeys"]
    assert st["key"] == preset["storey"] and st["label"] == "2. Obergeschoss"
    assert len(st["rooms"]) == len(preset["rooms"])
    assert len(st["doors"]) == len(preset["doors"])
    assert {r["name"] for r in st["rooms"]} == {r["name"] for r in preset["rooms"]}
    assert flat["status"] == "PASS" and flat["k"] == 1.0 and flat["mm_per_unit"] == 1000.0


def test_every_room_has_its_outline_area_and_walls(flat, preset):
    (st,) = flat["storeys"]
    by_name = {r["name"]: r for r in st["rooms"]}
    for r in preset["rooms"]:
        x0, y0, x1, y1 = sf.rect_of(preset, r)
        got = by_name[r["name"]]
        assert got["area_outline_m2"] == pytest.approx((x1 - x0) * (y1 - y0), abs=1e-3)
        assert got["wall_ids"], r["name"]
    assert {r["name"] for r in st["rooms"] if r["wet"]} == {"Bad", "WC"}


def _match(st, exp):
    """Pair each extracted door with the expected door at the same hinge; returns [(door, expected)]."""
    pairs = []
    for e in exp:
        d = min(st["doors"], key=lambda d: math.dist(d["hinge"], e["hinge"]))
        assert math.dist(d["hinge"], e["hinge"]) < 1e-6
        pairs.append((d, e))
    return pairs


def closed_end_problems(st, exp) -> list[str]:
    return [d["id"] for d, e in _match(st, exp) if d["closed_end"] is None or math.dist(d["ends"][d["closed_end"]], e["closed"]) > 1e-6]


def test_door_swings_are_the_drawn_ones(flat, preset):
    (st,) = flat["storeys"]
    exp = expected_doors(preset)
    assert closed_end_problems(st, exp) == []
    # falsified: one door's closed end flipped is reported
    bad = copy.deepcopy(st)
    bad["doors"][0]["closed_end"] = "b" if bad["doors"][0]["closed_end"] == "a" else "a"
    assert closed_end_problems(bad, exp) == [bad["doors"][0]["id"]]


def test_door_rooms_are_the_rooms_on_both_sides(flat, preset):
    (st,) = flat["storeys"]
    names = {r["id"]: r["name"] for r in st["rooms"]}
    for d, e in _match(st, expected_doors(preset)):
        got = {names[r] for r in d["rooms"]} | ({None} if d["leads_to"] else set())
        assert got == e["rooms"], d["id"]


def test_the_two_door_room_is_the_wohnzimmer(flat, preset):
    (st,) = flat["storeys"]
    two = [r["name"] for r in st["rooms"] if len(r["doors"]) == preset["expectations"]["min_doors_in_one_room"]]
    assert "Wohnzimmer" in two
    wz = next(r for r in st["rooms"] if r["name"] == "Wohnzimmer")
    names = {r["id"]: r["name"] for r in st["rooms"]}
    assert sorted(names[x["to"]] for x in wz["doors"]) == ["Küche", "Vorraum"]


def test_checks_all_match(flat):
    (st,) = flat["storeys"]
    assert [c["status"] for c in st["checks"]] == ["match"] * 5


def test_no_door_arcs_could_not_tell(generated):
    doc = ezdxf.readfile(generated[0])
    for e in list(doc.modelspace().query("ARC")):
        doc.modelspace().delete_entity(e)
    r = pe.extract(doc, PRE)
    st = r["storeys"][0]
    assert st["doors"] == [] and r["status"] == "INDETERMINATE"
    assert {c["id"]: c["status"] for c in st["checks"]}["R2"] == "could-not-tell"


def test_missing_label_drops_a_room_and_its_door_side(generated):
    doc = ezdxf.readfile(generated[0])
    for e in list(doc.modelspace().query("MTEXT")):
        if "Küche" in e.plain_text():
            doc.modelspace().delete_entity(e)
    st = pe.extract(doc, PRE)["storeys"][0]
    assert "Küche" not in {r["name"] for r in st["rooms"]} and len(st["rooms"]) == 6


def test_unknown_units_are_indeterminate(generated):
    doc = ezdxf.readfile(generated[0])
    doc.units = 0
    r = pe.extract(doc, PRE)
    assert r["status"] == "INDETERMINATE" and r["storeys"] == [] and "units" in r["unknowns"][0]


def test_layer_info_and_storey_labels():
    info = pe.layer_info(["2OG_10_Wand_tragend", "2OG_11_Abbruch_Wand_nichttragend", "0"], PRE)
    assert info["2OG_11_Abbruch_Wand_nichttragend"] == {"storey": "2OG", "status": "Abbruch", "base": "Wand_nichttragend"}
    assert info["0"]["storey"] is None
    assert pe.layer_info(["Walls", "Doors"], PRE)["Walls"] == {"storey": "all", "status": None, "base": "Walls"}
    assert pe.storey_label("EG", PRE) == "Erdgeschoss" and pe.storey_label("3OG", PRE) == "3. Obergeschoss" and pe.storey_label("X", PRE) == "X"
