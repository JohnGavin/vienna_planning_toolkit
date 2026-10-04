"""vpt/el_params.py and presets/el_parameters.json: colours (screen on black, print on white), contrast, one file for every
tunable value, schema, load/save with three outcomes."""
from vpt import el_layout, el_params, el_rules, el_symbols
import copy

import pytest


P = el_params.load()


def test_wcag_contrast_known_values():
    assert el_params.contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert el_params.contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)
    assert el_params.contrast("#123456", "#123456") == pytest.approx(1.0)
    assert el_params.blend("#ffffff", "#000000", 0.5) == "#808080"


def test_parameter_file_is_clean():
    assert el_params.validate(P) == []


def test_every_colour_has_3_to_1_against_its_background_in_both_palettes():
    tab = el_params.contrast_table(P)
    assert {n for n, *_ in tab} == set(el_params.PALETTES)
    assert len(tab) == 2 * len(el_params.COLOUR_KEYS)
    low = [(n, k, round(r, 2)) for n, k, _, _, r in tab if r < 3.0]
    assert low == []
    # the screen palette is on black, the print palette on white
    assert el_params.palette(P, "colours_screen")["background"] == "#000000"
    assert el_params.palette(P, "colours_print")["background"] == "#ffffff"


@pytest.mark.parametrize("palette,key,bad", [
    ("colours_screen", "schalter", "#1a4f9c"),      # the old print blue on black: about 2.6:1
    ("colours_print", "licht", "#ffd54f"),          # the screen amber on white
    ("colours_screen", "link", "#202020"),
    ("colours_screen", "marker", "#404040"),        # checked at the marker opacity
])
def test_contrast_gate_falsified(palette, key, bad):
    q = copy.deepcopy(P)
    q["sections"][palette]["values"][key]["value"] = bad
    probs = el_params.validate(q)
    assert any(f"{palette}.{key}" in x for x in probs), probs


def test_shape_problems_are_found():
    q = copy.deepcopy(P)
    q["sections"]["colours_print"]["values"]["daten"]["value"] = "green"
    assert any("not a #rrggbb" in x for x in el_params.validate(q))
    q = copy.deepcopy(P)
    q["sections"]["drawing_screen"]["values"]["saturation"]["value"] = 1.5
    assert any("0 to 1" in x for x in el_params.validate(q))
    q = copy.deepcopy(P)
    q["contrast_min"] = 2
    assert any("contrast_min" in x for x in el_params.validate(q))
    q = copy.deepcopy(P)
    del q["sections"]["screen_lines"]
    assert el_params.validate(q) == ["section screen_lines missing"]


def test_every_symbol_category_has_a_colour_in_both_palettes():
    lib = el_symbols.load()
    cats = {c["key"] for s in lib["sets"] for c in s["categories"]}
    for name in el_params.PALETTES:
        assert cats <= set(el_params.palette(P, name)), name


def test_screen_widths_are_at_least_the_visibility_minimum():
    # visible at every zoom: the screen widths are at least these
    assert el_params.value(P, "screen_lines", "symbol_stroke_px") >= 1.5
    assert el_params.value(P, "screen_lines", "link_stroke_px") >= 1.5
    assert el_params.value(P, "screen_lines", "marker_radius_px") >= 8


def test_no_colour_standard_is_claimed():
    note = P["standard_note"]
    assert "No Austrian colour standard" in note and "to verify" in note
    for s in el_params.PALETTES:
        assert P["sections"][s]["mark"] == "starting value – confirm"


# ---- one file for every tunable value, schema, load/save ----
import json  # noqa: E402



def test_schema_supported_and_the_file_validates():
    schema = el_params.load_schema()
    assert el_layout.unsupported_keywords(schema) == []
    assert el_params.schema_problems(P, schema) == []


def test_round_trip_save_then_load_is_identical_and_loads_as_match():
    text = el_params.dump(P)
    assert json.loads(text) == P
    assert el_params.check_file(text, P)[0] == "match"
    saved = dict(json.loads(text), saved="2026-10-04T12:00:00Z", saved_from="page")      # what the page's Save writes
    assert el_params.check_file(json.dumps(saved), P)[0] == "match"


@pytest.mark.parametrize("mutate,want", [
    (lambda q: "not json {", "could-not-tell"),
    (lambda q: json.dumps({k: v for k, v in q.items() if k != "sections"}), "could-not-tell"),
    (lambda q: json.dumps(dict(q, id="another-page")), "different"),
    (lambda q: json.dumps(dict(q, sections=dict(q["sections"], extra={"label": "x", "mark": "", "source": "", "values": {}}))), "different"),
    (lambda q: json.dumps(dict(q, unknown_top=1)), "could-not-tell"),
])
def test_check_file_three_outcomes(mutate, want):
    assert el_params.check_file(mutate(copy.deepcopy(P)), P)[0] == want


def test_check_file_refuses_poor_contrast():
    q = copy.deepcopy(P)
    q["sections"]["colours_screen"]["values"]["link"]["value"] = "#101010"
    assert el_params.check_file(json.dumps(q), P)[0] == "could-not-tell"


def test_every_value_has_one_home():
    assert el_params.single_home_problems() == []


def test_single_home_falsified():
    rules = json.loads((el_params.OTHER_PRESETS["el_rules_at.json"]).read_text(encoding="utf-8"))
    planted = dict(rules, settings={"snap_radius_m": 0.5})
    assert any("snap_radius_m" in x for x in el_params.single_home_problems(P, {"el_rules_at.json": planted}))
    lib = json.loads((el_params.OTHER_PRESETS["el_symbols_at.json"]).read_text(encoding="utf-8"))
    lib["sets"][0]["categories"][0]["colour"] = "#7a5200"
    probs = el_params.single_home_problems(P, {"el_symbols_at.json": lib})
    assert any("colour" in x for x in probs)
    page = json.loads((el_params.OTHER_PRESETS["el_page.json"]).read_text(encoding="utf-8"))
    assert any("symbol_scale" in x for x in el_params.single_home_problems(P, {"el_page.json": dict(page, symbol_scale=1.0)}))


def test_loaders_merge_the_parameters():
    r = el_rules.load()
    assert r["values"] == P["rules"]["values"] and r["settings"]["snap_radius_m"] == el_params.value(P, "snap", "snap_radius_m")
    assert r["default_rule_set"] == P["rules"]["default_rule_set"] and r["rules"] == P["rules"]["definitions"]
    cfg = el_layout.load_page()
    assert cfg["symbol_scale"] == el_params.value(P, "page", "symbol_scale") and cfg["room_label_max_m"] == el_params.value(P, "page", "room_label_max_m")
    # a parameter changed in the file reaches the loaders
    q = copy.deepcopy(P)
    q["sections"]["snap"]["values"]["snap_radius_m"]["value"] = 0.9
    assert el_rules.load(params=q)["settings"]["snap_radius_m"] == 0.9


def test_layout_file_records_the_parameters():
    schema = el_layout.load_schema()
    base = {"schema": "el_layout", "schema_version": 2, "drawing": {"file": "a.dwg", "sha256": "0" * 64, "storey": "st1", "storey_label": "Storey one"},
            "model_units_mm": 10.0, "symbol_set": {"id": "at-iec60617-draft1", "version": "0.1.0", "verified": False},
            "background": {"layers": [], "hidden_layers": 0}, "symbols": [], "links": [], "rule_set": "starting", "saved": "x", "app": "t"}
    good = dict(base, parameters={"id": P["id"], "version": P["version"], "sha256": el_params.sha256(), "edited": False})
    assert el_layout.validate(good, schema) == []
    assert el_layout.validate(base, schema) == []                                    # optional: a file may have no parameters block
    bad = dict(base, parameters={"id": P["id"], "version": P["version"], "sha256": "xyz", "edited": False})
    assert el_layout.validate(bad, schema) != []


def test_rows_cover_every_value_with_a_mark_or_source():
    rows = el_params.rows(P)
    n = sum(len(s["values"]) for s in P["sections"].values()) + len(P["rules"]["rule_sets"]) * len(P["rules"]["definitions"])
    assert len(rows) == n
    assert all(r["mark"] or r["source"] or r["value"] is None for r in rows)
