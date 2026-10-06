"""Fitting recognition by shape (vpt/dxf_symbols.py, vpt/fittings.py, tools/recognise_fittings.py) on the synthetic flat.

The expected types and rooms are derived from presets/synthetic_flat.json (what the generator drew), not from the recogniser.
Each check is falsified: a broken rule list, an overlapping rule, a missing fitting layer, a fitting outside every room, a
demolished fitting and a unitless drawing."""
import copy
import json
from collections import Counter

import ezdxf
import pytest

import recognise_fittings as tool
from conftest import PRESET_PATH, SAMPLE_PATH
from vpt import dxf_symbols as ds
from vpt import fittings, plan

FP = fittings.load_preset()
PRE = json.loads(plan.EXTRACT_PRESET.read_text(encoding="utf-8"))
FLAT = json.loads(PRESET_PATH.read_text(encoding="utf-8"))
G = FLAT["grid"]

# generator type -> recognised type
EXPECT_TYPE = {"sink": "Spüle", "hob": "Kochplatte", "bathtub": "Badewanne", "basin": "Waschtisch", "toilet": "WC"}


def room_of(x, y):
    for r in FLAT["rooms"]:
        x0, x1, y0, y1 = G["x"][r["x"][0]], G["x"][r["x"][1]], G["y"][r["y"][0]], G["y"][r["y"][1]]
        if x0 <= x <= x1 and y0 <= y <= y1:
            return r["name"]
    return None


def expected():
    """Counter of (type, room name) of the fittings the generator drew on the sanitary and kitchen layers."""
    out = Counter()
    for f in FLAT["fittings"]:
        if f["layer"] not in ("sanitary", "kitchen"):
            continue
        if f["type"] == "hob":
            for dx in (-f["pitch"] / 2, f["pitch"] / 2):
                for dy in (-f["pitch"] / 2, f["pitch"] / 2):
                    out[("Kochplatte", room_of(f["cx"] + dx, f["cy"] + dy))] += 1
        else:
            kind = EXPECT_TYPE.get(f["type"], "Küchenzeile" if f["name"] == "Küchenzeile" else None)
            out[(kind, room_of(f["x"] + f["w"] / 2, f["y"] + f["h"] / 2))] += 1
    return out


@pytest.fixture(scope="module")
def result():
    return fittings.run(ezdxf.readfile(SAMPLE_PATH), PRE, FP)


def run_with(fp=None, doc=None):
    return fittings.run(doc or ezdxf.readfile(SAMPLE_PATH), PRE, fp or FP)


def test_every_drawn_fitting_is_recognised_in_its_room(result):
    assert result["status"] == "PASS", result["failures"] + result["unknowns"] + [str(f) for f in result["flagged"]]
    st = result["storeys"][0]
    names = {r["id"]: r for r in plan.export(SAMPLE_PATH, synthetic=True)["storeys"][0]["rooms"]}
    got = Counter((s["kind"], names[s["room"]]["name"]) for s in st["symbols"])
    assert got == expected()
    assert [c["status"] for c in st["checks"]] == ["match"] * 3 and st["demolished"]["symbols"] == 0
    assert st["counts"] == {"Badewanne": 1, "Kochplatte": 4, "Küchenzeile": 1, "Spüle": 1, "WC": 1, "Waschtisch": 2}


def test_features_are_in_metres_and_sized_like_the_drawing(result):
    k = result["units_per_m"]
    assert k == 1.0
    bath = next(s for s in result["storeys"][0]["symbols"] if s["kind"] == "Badewanne")
    tub = next(f for f in FLAT["fittings"] if f["type"] == "bathtub")
    assert (bath["w_m"], bath["d_m"]) == (max(tub["w"], tub["h"]), min(tub["w"], tub["h"]))


# ---- falsification ---------------------------------------------------------------------------------------------

def test_a_missing_rule_leaves_an_unrecognised_symbol_flagged(result):
    fp = copy.deepcopy(FP)
    fp["shape_rules"]["rules"] = [r for r in fp["shape_rules"]["rules"] if r["type"] != "WC"]
    res = run_with(fp)
    assert res["status"] == "INDETERMINATE" and [f["id"] for f in res["flagged"]] == ["F1"]
    st = res["storeys"][0]
    assert [s["kind"] for s in st["symbols"]].count("unrecognised") == 1 and "WC" not in st["counts"]
    assert st["checks"][0]["items"][0]["w_m"] == 0.65


def test_two_matching_rules_are_ambiguous_never_resolved(result):
    fp = copy.deepcopy(FP)
    twin = copy.deepcopy(next(r for r in fp["shape_rules"]["rules"] if r["type"] == "Badewanne"))
    twin["type"] = "Wanne"
    fp["shape_rules"]["rules"].append(twin)
    res = run_with(fp)
    amb = [s for s in res["storeys"][0]["symbols"] if s["kind"] == "ambiguous"]
    assert len(amb) == 1 and sorted(amb[0]["matches"]) == ["Badewanne", "Wanne"] and res["status"] == "INDETERMINATE"


def test_a_wet_room_without_a_fitting_fails(result):
    fp = copy.deepcopy(FP)
    fp["fitting_layers"] = ["Kuecheneinrichtung"]          # the sanitary layer is not read at all
    res = run_with(fp)
    assert res["status"] == "FAIL" and any("F3" in f for f in res["failures"])
    assert {r["id"] for r in res["storeys"][0]["rooms"] if r["wet"] and not r["fittings"]}


def test_furniture_on_a_fitting_layer_is_flagged_not_guessed(result):
    fp = copy.deepcopy(FP)
    fp["fitting_layers"] = FP["fitting_layers"] + ["Moeblierung"]
    res = run_with(fp)
    assert res["status"] == "INDETERMINATE" and [f["id"] for f in res["flagged"]] == ["F1"]
    unknown = [s for s in res["storeys"][0]["symbols"] if s["kind"] in ("unrecognised", "ambiguous")]
    assert len(unknown) == 6
    # shape alone cannot tell a plain 1.7 x 0.6 m rectangle on a furniture layer (a wardrobe) from a kitchen counter: it is
    # recognised as one. That is why the furniture layer is not in the preset's fitting_layers.
    assert res["storeys"][0]["counts"] == dict(result["storeys"][0]["counts"], Küchenzeile=2)


def test_a_fitting_outside_every_room_is_flagged():
    doc = ezdxf.readfile(SAMPLE_PATH)
    msp = doc.modelspace()
    layer = next(n.dxf.name for n in doc.layers if n.dxf.name.endswith("_Sanitaereinrichtung"))
    pts = [(40, 40), (40.65, 40), (40.65, 40.4), (40, 40.4)]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})
    msp.add_lwpolyline([(40.1, 40.1), (40.55, 40.1), (40.55, 40.3), (40.1, 40.3)], close=True, dxfattribs={"layer": layer})
    res = run_with(doc=doc)
    assert any(f["id"] == "F2" for f in res["flagged"]) and res["status"] == "INDETERMINATE"
    far = [s for s in res["storeys"][0]["symbols"] if s["room"] is None]
    assert len(far) == 1 and far[0]["room_method"] == "none"


def test_a_demolished_fitting_is_reported_but_not_counted(result):
    doc = ezdxf.readfile(SAMPLE_PATH)
    layer = "2OG_31_Abbruch_Sanitaereinrichtung"
    doc.layers.add(layer)
    msp = doc.modelspace()
    for pts in ([(1, 7), (1.65, 7), (1.65, 7.4), (1, 7.4)], [(1.05, 7.05), (1.6, 7.05), (1.6, 7.35), (1.05, 7.35)]):
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})
    res = run_with(doc=doc)
    st = res["storeys"][0]
    assert st["demolished"]["symbols"] == 1 and st["counts"] == result["storeys"][0]["counts"]
    assert len(st["symbols"]) == len(result["storeys"][0]["symbols"]) and res["status"] == "PASS"


def test_unknown_units_are_could_not_tell():
    doc = ezdxf.readfile(SAMPLE_PATH)
    doc.units = 0
    res = run_with(doc=doc)
    assert res["status"] == "INDETERMINATE" and res["storeys"] == [] and "units unknown" in res["unknowns"][0]


def test_a_broken_preset_is_refused():
    assert fittings.validate(dict(FP, fitting_layers=[]))
    dup = copy.deepcopy(FP)
    dup["shape_rules"]["rules"].append(dup["shape_rules"]["rules"][0])
    assert "duplicate rule type" in fittings.validate(dup)
    with pytest.raises(ValueError):
        run_with(dup)


# ---- the shape logic on its own ----------------------------------------------------------------------------------

def test_classify_none_one_many():
    rules = [{"type": "A", "w_m": [0.4, 0.8], "d_m": [0.2, 0.5]}, {"type": "B", "w_m": [0.6, 1.0], "d_m": [0.2, 0.5], "max_aspect": 2.0}]
    f = {"w_m": 0.5, "d_m": 0.3, "aspect": 1.67, "circle_radii_m": []}
    assert ds.classify(f, [], rules) == ("A", ["A"])
    assert ds.classify(dict(f, w_m=0.7, aspect=2.3), [], rules) == ("A", ["A"])             # B refuses an aspect above 2.0
    assert ds.classify(dict(f, w_m=0.7, aspect=1.9), [], rules)[0] == "ambiguous"
    assert ds.classify(dict(f, w_m=2.0), [], rules) == ("unrecognised", [])
    cue = [{"type": "M", "w_m": [0.5, 0.7], "d_m": [0.5, 0.7], "any": [{"feature": "text_cue", "regex": "^WM$"}]}]
    sq = {"w_m": 0.6, "d_m": 0.6, "aspect": 1.0, "circle_radii_m": []}
    assert ds.classify(sq, ["WM"], cue)[0] == "M" and ds.classify(sq, ["xx"], cue)[0] == "unrecognised"


# ---- the tool --------------------------------------------------------------------------------------------------------

def test_tool_exit_codes(tmp_path):
    out = tmp_path / "f.json"
    assert tool.main([str(SAMPLE_PATH), "--output", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema"] == "vpt_fittings" and data["drawing"] == "synthetic_flat.dxf"
    assert tool.main([str(tmp_path / "missing.dxf")]) == 2
    broken = tmp_path / "p.json"
    broken.write_text(json.dumps(dict(FP, fitting_layers=[])))
    assert tool.main([str(SAMPLE_PATH), "--output", str(out), "--preset", str(broken)]) == 2
    flagged = tmp_path / "q.json"
    q = copy.deepcopy(FP)
    q["shape_rules"]["rules"] = [r for r in q["shape_rules"]["rules"] if r["type"] != "WC"]
    flagged.write_text(json.dumps(q))
    assert tool.main([str(SAMPLE_PATH), "--output", str(out), "--preset", str(flagged)]) == 3
    only_kitchen = tmp_path / "r.json"
    only_kitchen.write_text(json.dumps(dict(FP, fitting_layers=["Kuecheneinrichtung"])))
    assert tool.main([str(SAMPLE_PATH), "--output", str(out), "--preset", str(only_kitchen)]) == 1
    junk = tmp_path / "junk.dxf"
    junk.write_text("junk\n" * 30)
    assert tool.main([str(junk), "--output", str(out)]) == 3
