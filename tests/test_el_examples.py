"""Generated example layouts (vpt/el_examples.py) on the synthetic flat: the simple example is the Wohnzimmer (the room with
exactly two doors) with a Wechselschaltung; every position is a suggestion; both examples open on their storey. Falsified."""
import copy

import ezdxf
import pytest

from conftest import ROOT
from vpt import el_examples, el_layout, el_links, el_params, el_rules, el_symbols, plan_extract

PARAMS = el_params.load()
RULES = el_rules.load(params=PARAMS)
LIB = el_symbols.load()


@pytest.fixture(scope="module")
def ex(generated):
    import json
    pre = json.loads((ROOT / "presets" / "plan_extract.json").read_text(encoding="utf-8"))
    flat = plan_extract.extract(ezdxf.readfile(generated[0]), pre)
    bg = {s["key"]: {"layers": ["a"], "hidden_layers": 0} for s in flat["storeys"]}
    out = el_examples.build(flat["storeys"], k=flat["k"], mm_per_unit=flat["mm_per_unit"], drawing_file="flat.dxf", sha256="ab" * 32,
                            background=bg, rules=RULES, params=PARAMS, lib=LIB)
    return flat, out


def test_simple_example_is_the_wohnzimmer_with_two_way_switching(ex):
    flat, out = ex
    st = flat["storeys"][0]
    wz = next(r["id"] for r in st["rooms"] if r["name"] == "Wohnzimmer")
    simple = out["examples"]["simple"]
    assert out["storey"] == st["key"] and simple["example"]["rooms"] == [wz]
    codes = sorted(s["code"] for s in simple["symbols"])
    assert codes == sorted(["LD", "SW", "SW"] + [PARAMS["sections"]["examples"]["values"]["socket_code"]["value"]] * 2)
    g = el_links.groups(simple["symbols"], simple["links"])
    assert len(g) == 1 and len(g[0]["switches"]) == 2 and len(g[0]["lights"]) == 1
    p = el_links.proposal([(i, next(s["code"] for s in simple["symbols"] if s["id"] == i)) for i in g[0]["switches"]], RULES["switching"])
    assert p["name"] == "Wechselschaltung" and p["matches"] is True
    assert all(s["room"] == wz and s["room_method"] == "outline" for s in simple["symbols"])


@pytest.mark.parametrize("ex_id", ["simple", "complex"])
def test_examples_are_valid_derived_and_open(ex, ex_id):
    flat, out = ex
    doc = out["examples"][ex_id]
    rooms, doors, k = el_rules.storey_input(flat["storeys"][0], flat["k"])
    sug = el_rules.suggestions(rooms, doors, k, RULES, "starting", windows=el_rules.storey_windows(flat["storeys"][0]))
    assert el_examples.off_suggestion(doc, sug, RULES, PARAMS, k) == []
    assert el_layout.check_layout(doc, sha256="ab" * 32, storey=out["storey"], lib=LIB, schema=el_layout.load_schema(), rules=RULES)[0] == "match"
    assert doc["example"]["id"] == ex_id and el_links.link_problems(doc["symbols"], doc["links"], el_symbols.default_set(LIB), RULES["switching"]) == []


def test_off_suggestion_falsified(ex):
    flat, out = ex
    doc = copy.deepcopy(out["examples"]["simple"])
    doc["symbols"][0]["x"] += 0.3
    rooms, doors, k = el_rules.storey_input(flat["storeys"][0], flat["k"])
    sug = el_rules.suggestions(rooms, doors, k, RULES, "starting", windows=el_rules.storey_windows(flat["storeys"][0]))
    assert el_examples.off_suggestion(doc, sug, RULES, PARAMS, k) == [doc["symbols"][0]["id"]]


def test_complex_example_covers_every_room(ex):
    flat, out = ex
    cx = out["examples"]["complex"]
    assert cx["example"]["rooms"] == [r["id"] for r in flat["storeys"][0]["rooms"]]
    codes = [s["code"] for s in cx["symbols"]]
    ev = PARAMS["sections"]["examples"]["values"]
    assert codes.count(ev["board_code"]["value"]) == 1 and codes.count(ev["smoke_code"]["value"]) == len(flat["storeys"][0]["rooms"])


def test_no_room_qualifies_no_example(ex):
    flat, _ = ex
    q = copy.deepcopy(PARAMS)
    q["sections"]["examples"]["values"]["simple_doors"]["value"] = 9
    out = el_examples.build(flat["storeys"], k=flat["k"], mm_per_unit=flat["mm_per_unit"], drawing_file="flat.dxf", sha256="ab" * 32,
                            background={}, rules=RULES, params=q, lib=LIB)
    assert out["storey"] is None and out["examples"] == {} and "no storey meets the rule" in out["why"]
