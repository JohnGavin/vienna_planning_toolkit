"""The plan file (vpt/plan.py, schema/plan.schema.json, tools/export_plan.py) on the synthetic flat: valid, deterministic, the
committed sample up to date, and the three outcomes of check() (each falsified with a broken or foreign file)."""
import copy
import json

import pytest

from conftest import ROOT, SAMPLE_PATH
from vpt import dxf_svg, el_examples, el_params, el_rules, plan

PLAN_PATH = ROOT / "samples" / "synthetic_flat.plan.json"


@pytest.fixture(scope="module")
def exported():
    return plan.export(SAMPLE_PATH, synthetic=True)


def test_export_is_valid_and_checks(exported):
    assert plan.check(exported) == ("match", "1 storey(s), 7 rooms, 8 doors")
    assert exported["drawing"]["file"] == "synthetic_flat.dxf" and "/" not in exported["drawing"]["file"]
    assert exported["drawing"]["sha256"] == plan.sha256_file(SAMPLE_PATH)
    assert exported["synthetic"] is True and exported["extract"]["status"] == "PASS"
    assert exported["parameters"]["sha256"] == el_params.sha256()


def test_export_is_deterministic_and_the_committed_sample_is_current(exported):
    again = plan.export(SAMPLE_PATH, synthetic=True)
    assert plan.dumps(again) == plan.dumps(exported)
    assert PLAN_PATH.read_text(encoding="utf-8") == plan.dumps(exported), "run python3 tools/export_plan.py samples/synthetic_flat.dxf --synthetic"


def test_storey_drawing_has_every_layer_and_no_raster(exported):
    st = exported["storeys"][0]
    info = dxf_svg.inspect(st["svg"])
    assert info["storey"] == st["key"] and info["images"] == 0 and not info["duplicates"]
    assert {x["layer"] for x in st["layers"]} == set(info["groups"])
    assert sum(x["paths"] for x in st["layers"]) == info["paths"] > 0
    # the affine maps model metres to viewBox units, y flipped (CAD y up, SVG y down)
    a = st["affine"]
    assert a[0] > 0 and a[3] < 0 and a[1] == a[2] == 0


def test_suggestions_are_those_of_el_rules(exported):
    st = exported["storeys"][0]
    rules = el_rules.load()
    rooms, doors, k = el_rules.storey_input(st, exported["drawing"]["units_per_m"])
    for rs in rules["rule_sets"]:
        assert st["suggest"][rs["id"]] == json.loads(json.dumps(el_rules.suggestions(rooms, doors, k, rules, rs["id"])))
    assert all(not v for kk, v in st["suggest"]["elektroplaner"].items() if kk != "notes")      # null values: no suggestion


def test_examples_are_in_the_example_storey(exported):
    st = exported["storeys"][0]
    assert set(st["examples"]) == {"simple", "complex"}
    assert el_examples.STOREY_RULE in exported["example_rule"]


@pytest.mark.parametrize("text, want, why", [
    ('{"schema": "vpt_plan", "storeys": [', "could-not-tell", "not JSON"),
    ("[1, 2]", "could-not-tell", "not a JSON object"),
    ('{"schema": "el_layout", "schema_version": 2}', "different", "layout file"),
    ('{"name": "el_parameters"}', "different", "parameter file"),
    ('{"hello": 1}', "different", "unknown kind"),
    ('{"schema": "vpt_plan", "schema_version": 1}', "could-not-tell", "not a valid plan file"),
])
def test_check_text_three_outcomes(text, want, why):
    got = plan.check_text(text)
    assert got[0] == want and why in got[1], got


@pytest.mark.parametrize("plant, why", [
    (lambda p: p["storeys"][0].__setitem__("svg", "<svg><g>"), "does not parse"),
    (lambda p: p["storeys"][0].__setitem__("svg", '<svg xmlns="http://www.w3.org/2000/svg"><image href="x.png"/></svg>'), "raster"),
    (lambda p: p["storeys"][0].__setitem__("affine", [1, 2, 2, 4, 0, 0]), "affine"),
    (lambda p: p["drawing"].__setitem__("file", "/home/someone/plan.dxf"), "pattern"),
    (lambda p: p["drawing"].__setitem__("sha256", "xyz"), "pattern"),
    (lambda p: p.__setitem__("schema_version", 2), "enum"),
    (lambda p: p["storeys"][0]["doors"][0].__setitem__("closed_end", "c"), "enum"),
])
def test_broken_plans_could_not_tell(exported, plant, why):
    p = copy.deepcopy(exported)
    plant(p)
    got = plan.check(p)
    assert got[0] == "could-not-tell" and why in got[1], got


def test_export_tool_writes_and_reports(tmp_path):
    import export_plan
    out = tmp_path / "x.plan.json"
    assert export_plan.main([str(SAMPLE_PATH), "--output", str(out), "--synthetic"]) == 0
    assert plan.check_text(out.read_text(encoding="utf-8"))[0] == "match"
    assert export_plan.main([str(tmp_path / "missing.dxf")]) == 2
    bad = tmp_path / "bad.dxf"
    bad.write_text("not a dxf", encoding="utf-8")
    assert export_plan.main([str(bad), "--output", str(tmp_path / "bad.plan.json")]) == 3
    assert not (tmp_path / "bad.plan.json").exists()
