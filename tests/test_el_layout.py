"""The layout file (vpt/el_layout.py, schema/el_layout.schema.json): schema subset validator, round trip, the model <-> view
transform (inverse of dxf_svg's affine) and the drawing/storey check with its three outcomes. Every check is falsified."""
from vpt import el_layout, el_symbols
from vpt.dxf_svg import apply_affine
import copy
import json
import math

import pytest


SHA = "ab" * 32
SCHEMA = el_layout.load_schema()
LIB = el_symbols.load()
SET = el_symbols.default_set(LIB)
# the shape of a real storey's affine (model metres -> viewBox units, y flipped), made-up numbers
AFFINE = [999.662, 0.0, 0.0, -999.662, 1234.5, 18000.25]


def layout(**kw):
    syms = kw.pop("symbols", [{"id": "s1", "code": "SS2", "x": 12.3456, "y": 4.5, "rotation": 90, "room": "st1-R3", "room_method": "outline"},
                              {"id": "s2", "code": "LD", "x": 10.0, "y": 6.0, "rotation": 0, "room": None, "room_method": "could-not-tell"}])
    return el_layout.make_layout(drawing_file="plan.dwg", sha256=SHA, storey="st1", storey_label="Storey one", model_units_mm=1000.0,
                                 symbol_set=SET, background={"layers": ["A", "B"], "hidden_layers": 3, "copied": "2026-10-04T10:00:00Z"},
                                 symbols=syms, saved="2026-10-04T10:05:00Z", **kw)


def test_made_layout_is_valid():
    assert el_layout.validate(layout(), SCHEMA) == []


def test_round_trip_through_json_text():
    a = layout()
    b = json.loads(json.dumps(a, ensure_ascii=False))
    assert el_layout.validate(b, SCHEMA) == []
    assert b == a


@pytest.mark.parametrize("plant, expect", [
    (lambda d: d.pop("drawing"), "drawing"),
    (lambda d: d.__setitem__("schema", "other"), "const"),
    (lambda d: d["drawing"].__setitem__("sha256", "xyz"), "pattern"),
    (lambda d: d["symbols"][0].__setitem__("rotation", 45), "enum"),
    (lambda d: d["symbols"][0].__setitem__("x", "12"), "type"),
    (lambda d: d["symbols"][0].__setitem__("id", "7"), "pattern"),
    (lambda d: d["symbols"][0].__setitem__("extra", 1), "additional"),
    (lambda d: d.__setitem__("links", [{"a": 1}]), "required"),
    (lambda d: d.__setitem__("links", [{"id": "l1", "from": "s1", "to": "x2"}]), "pattern"),
    (lambda d: d.__setitem__("schema_version", 3), "enum"),
    (lambda d: d.__setitem__("rule_set", ""), "minLength"),
    (lambda d: d["background"].__setitem__("hidden_layers", -1), "minimum"),
    (lambda d: d.__setitem__("model_units_mm", 0), "exclusiveMinimum"),
    (lambda d: d["symbols"][1].__setitem__("room_method", "guess"), "enum"),
])
def test_validator_catches_planted_defects(plant, expect):
    d = layout()
    plant(d)
    problems = el_layout.validate(d, SCHEMA)
    assert problems and any(expect in p for p in problems), problems


def test_schema_uses_only_supported_keywords():
    assert el_layout.unsupported_keywords(SCHEMA) == []
    bad = copy.deepcopy(SCHEMA)
    bad["properties"]["symbols"]["uniqueItems"] = True
    assert el_layout.unsupported_keywords(bad) == ["uniqueItems"]
    with pytest.raises(ValueError):
        el_layout.validate(layout(), bad)


@pytest.mark.parametrize("affine", [AFFINE, [0.5, 0.2, -0.3, -0.4, 10.0, 20.0], [2000.0, 0.0, 0.0, 2000.0, -5.0, 7.0]])
def test_model_view_round_trip_within_one_mm(affine):
    mm_per_unit = 1000.0
    for x, y in [(0.0, 0.0), (12.3456, 4.5), (-3.2, 25.75), (100.0, -40.0)]:
        X, Y = apply_affine(affine, x, y)
        x2, y2 = el_layout.view_to_model(affine, X, Y)
        assert math.hypot(x2 - x, y2 - y) * mm_per_unit < 1.0
        X2, Y2 = el_layout.model_to_view(affine, x2, y2)
        assert math.hypot(X2 - X, Y2 - Y) < 1e-6


def test_round_trip_falsified_by_a_wrong_inverse():
    # a plausible bug: forgetting the y flip (using d's absolute value) moves the point far more than 1 mm
    wrong = AFFINE[:3] + [abs(AFFINE[3])] + AFFINE[4:]
    X, Y = apply_affine(AFFINE, 12.0, 4.0)
    x2, y2 = el_layout.view_to_model(wrong, X, Y)
    assert math.hypot(x2 - 12.0, y2 - 4.0) * 1000 > 1.0


def test_singular_affine_is_refused():
    with pytest.raises(ValueError):
        el_layout.view_to_model([1.0, 2.0, 2.0, 4.0, 0, 0], 1, 1)


def test_check_three_outcomes():
    ok = el_layout.check_layout(layout(), sha256=SHA, storey="st1", lib=LIB, schema=SCHEMA)
    assert ok[0] == "match"
    other_drawing = el_layout.check_layout(layout(), sha256="cd" * 32, storey="st1", lib=LIB, schema=SCHEMA)
    assert other_drawing[0] == "different" and "drawing" in other_drawing[1]
    other_storey = el_layout.check_layout(layout(), sha256=SHA, storey="st2", lib=LIB, schema=SCHEMA)
    assert other_storey[0] == "different" and "storey" in other_storey[1]
    broken = layout()
    broken.pop("symbols")
    assert el_layout.check_layout(broken, sha256=SHA, storey="st1", lib=LIB, schema=SCHEMA)[0] == "could-not-tell"
    assert el_layout.check_layout(layout(), sha256=None, storey="st1", lib=LIB, schema=SCHEMA)[0] == "could-not-tell"
    unknown_code = layout(symbols=[{"id": "s1", "code": "ZZ", "x": 1, "y": 1, "rotation": 0, "room": None, "room_method": "could-not-tell"}])
    assert el_layout.check_layout(unknown_code, sha256=SHA, storey="st1", lib=LIB, schema=SCHEMA)[0] == "could-not-tell"
    other_set = layout()
    other_set["symbol_set"]["id"] = "another-set"
    assert el_layout.check_layout(other_set, sha256=SHA, storey="st1", lib=LIB, schema=SCHEMA)[0] == "could-not-tell"
    assert el_layout.check_text("{not json", sha256=SHA, storey="st1", lib=LIB, schema=SCHEMA)[0] == "could-not-tell"


def test_file_name():
    assert el_layout.file_name("Plan A.dwg", "st1", ".electrical.json") == "Plan A__st1.electrical.json"


# ---- version 2: links and the rule set; version-1 files still open --------------------------------------------------------

SW_LD = [{"id": "s1", "code": "SA", "x": 1.0, "y": 1.0, "rotation": 0, "room": "st1-R1", "room_method": "outline"},
         {"id": "s2", "code": "LD", "x": 2.0, "y": 2.0, "rotation": 0, "room": "st1-R1", "room_method": "outline"},
         {"id": "s3", "code": "SS1", "x": 3.0, "y": 1.0, "rotation": 0, "room": "st1-R1", "room_method": "outline"}]


def check(doc, **kw):
    return el_layout.check_layout(doc, sha256=SHA, storey="st1", lib=LIB, schema=SCHEMA, **kw)


def test_version_2_with_links_round_trip():
    d = layout(symbols=SW_LD, links=[{"id": "l1", "from": "s1", "to": "s2"}], rule_set="elektroplaner")
    assert d["schema_version"] == 2 and el_layout.validate(d, SCHEMA) == []
    back = json.loads(json.dumps(d))
    assert back["links"] == [{"id": "l1", "from": "s1", "to": "s2"}] and back["rule_set"] == "elektroplaner"
    assert check(back)[0] == "match" and "1 link" in check(back)[1]


def v1(**kw):
    d = layout(**kw)
    d["schema_version"] = 1
    d.pop("rule_set")
    return d


def test_version_1_file_still_opens_and_is_migrated():
    d = v1()
    assert el_layout.validate(d, SCHEMA) == []
    assert check(d)[0] == "match"
    m, why = el_layout.migrate(d, "starting")
    assert why == "" and m["schema_version"] == 2 and m["links"] == [] and m["rule_set"] == "starting"
    assert d["schema_version"] == 1                                    # the input is not changed


def test_version_1_with_links_or_rule_set_refused():
    d = v1(symbols=SW_LD)
    d["links"] = [{"id": "l1", "from": "s1", "to": "s2"}]
    assert check(d)[0] == "could-not-tell" and "version-1" in check(d)[1]
    d2 = v1()
    d2["rule_set"] = "starting"
    assert check(d2)[0] == "could-not-tell"


@pytest.mark.parametrize("links, expect", [
    ([{"id": "l1", "from": "s1", "to": "s3"}], "cannot be connected"),     # SA -> socket: not in SA's list
    ([{"id": "l1", "from": "s2", "to": "s1"}], "not a switch"),            # from a light
    ([{"id": "l1", "from": "s1", "to": "s9"}], "unknown"),
])
def test_invalid_links_refuse_the_file(links, expect):
    d = layout(symbols=SW_LD, links=links)
    assert el_layout.validate(d, SCHEMA) == []                         # valid against the schema, refused by the link rules
    res = check(d)
    assert res[0] == "could-not-tell" and expect in res[1], res


def test_unknown_rule_set_refused():
    assert check(layout(rule_set="nope"))[0] == "could-not-tell"
    assert check(layout(rule_set="starting"))[0] == "match"            # control
