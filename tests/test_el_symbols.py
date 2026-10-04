"""The symbol library (presets/el_symbols_at.json, checked by vpt/el_symbols.py). Every symbol must carry the required
fields, a parseable SVG of plain vector elements only, a category and layer that exist, connectable codes that exist, and be
marked unverified. Each test is falsified by a planted defect in a copy of the library."""
from vpt import el_symbols
import copy

import pytest


LIB = el_symbols.load()


def test_library_is_clean():
    assert el_symbols.validate(LIB) == []


def test_starting_set_has_the_asked_symbols():
    s = el_symbols.default_set(LIB)
    names = {x["name_en"] for x in s["symbols"]}
    for want in ("Ceiling light", "Wall light", "Switch (one-way)", "Two-way switch", "Intermediate switch", "Push-button",
                 "Socket with protective earth, single", "Socket with protective earth, double", "Cooker outlet 400 V",
                 "Dishwasher socket", "Oven outlet", "Fridge socket", "Washing machine socket", "Network outlet RJ45",
                 "TV/SAT outlet", "Smoke alarm", "Distribution board"):
        assert want in names, want
    assert {c["name_de"] for c in s["categories"]} == {"Licht", "Schalter", "Steckdosen", "Küche/Geräte", "Daten/TV", "Sicherheit", "Verteiler"}


def test_whole_set_and_every_symbol_marked_unverified():
    s = el_symbols.default_set(LIB)
    assert s["verified"] is False and s["verified_against"] is None
    assert "UNVERIFIED" in s["status"] and "Elektroplaner" in s["status"]
    assert "60617" in s["standard"] and "8101" in s["installation_standard"]
    assert all(x["verified"] is False and x["verified_against"] is None for x in s["symbols"])


def test_layers_are_elektro_layers_one_per_category():
    s = el_symbols.default_set(LIB)
    by_cat = {}
    for x in s["symbols"]:
        by_cat.setdefault(x["category"], set()).add(x["layer"])
    assert all(len(v) == 1 for v in by_cat.values())
    assert all(next(iter(v)).startswith("Elektro – ") for v in by_cat.values())
    assert el_symbols.layers(s) == [next(iter(by_cat[c["key"]])) for c in s["categories"]]


@pytest.mark.parametrize("plant, expect", [
    (lambda s: s["symbols"][0].pop("name_de"), "name_de"),
    (lambda s: s["symbols"][0].__setitem__("svg", "<circle r='3'>"), "SVG"),
    (lambda s: s["symbols"][0].__setitem__("svg", "<image href='x.png'/>"), "image"),
    (lambda s: s["symbols"][0].__setitem__("svg", "<use href='#a'/>"), "use"),
    (lambda s: s["symbols"][0].__setitem__("category", "nope"), "category"),
    (lambda s: s["symbols"][1].__setitem__("code", s["symbols"][0]["code"]), "duplicate"),
    (lambda s: s["symbols"][0].__setitem__("connectable_to", ["XX"]), "connectable"),
    (lambda s: s["symbols"][0].__setitem__("verified", True), "verified"),
    (lambda s: s.__setitem__("verified_against", "something"), "verified"),
    (lambda s: s["symbols"][0].__setitem__("box", [0, 0, -1, 2]), "box"),
    (lambda s: s["symbols"][2].__setitem__("layer", "Elektro – Licht"), "layer"),
])
def test_validate_catches_planted_defects(plant, expect):
    bad = copy.deepcopy(LIB)
    plant(bad["sets"][0])
    problems = el_symbols.validate(bad)
    assert problems and any(expect in p for p in problems), problems


def test_default_set_must_exist():
    bad = copy.deepcopy(LIB)
    bad["default_set"] = "missing"
    assert any("default_set" in p for p in el_symbols.validate(bad))


def test_preview_svg_parses_and_carries_colour():
    s = el_symbols.default_set(LIB)
    for x in s["symbols"]:
        svg = el_symbols.preview_svg(s, x, size_px=28)
        root = el_symbols.parse_fragment(svg, wrap=False)
        assert root.tag.endswith("svg")
        assert el_symbols.colour(s, x) in svg
