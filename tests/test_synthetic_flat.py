"""Tests for the synthetic flat generator and the drawing validator.

Each positive check is paired with a falsification: a deliberately broken
drawing that the same check must reject. A check that cannot go red is not
a check.
"""
import json
import re
import subprocess
import sys

import ezdxf
import pytest
from ezdxf.tools.juliandate import juliandate
from datetime import datetime

from conftest import PRESET_PATH, ROOT, SAMPLE_PATH
import synthetic_flat as sf
import validate_flat as vf

VALIDATOR = ROOT / "tools" / "validate_flat.py"


# ---------------------------------------------------------------- basics
def test_dxf_opens_as_r2018_in_metres(doc):
    assert doc.dxfversion == "AC1032"  # R2018
    assert doc.units == ezdxf.units.M
    assert len(doc.modelspace()) > 0


def test_generator_summary_matches_preset(generated, preset):
    _, s = generated
    assert s["rooms"] == len(preset["rooms"])
    assert s["doors"] == len(preset["doors"])
    assert s["windows"] == len(preset["windows"])
    assert s["layers"] == len(preset["layers"])
    assert 75 <= s["total_area_m2"] <= 90


def test_room_names_are_the_required_set(doc, preset):
    names = {lab["name"] for lab in vf.room_labels(doc, preset)}
    assert {"Vorraum", "Wohnzimmer", "Schlafzimmer", "Küche", "Bad", "WC", "Abstellraum"} <= names


# ---------------------------------------------------------------- layers
def test_layer_names_match_pattern(doc, preset):
    assert vf.check_layers(doc, preset) == []


def test_layers_include_bestand_abbruch_neubau(doc, preset):
    names = [lay.dxf.name for lay in doc.layers]
    assert any("_Abbruch_" in n for n in names)
    assert any("_Neubau_" in n for n in names)
    for role in ("wall_abbruch", "wall_neubau", "wall_tragend", "wall_nichttragend"):
        layer = sf.layer_name(preset, role)
        assert len(doc.modelspace().query(f'LINE[layer=="{layer}"]')) >= 2, role


def test_falsify_bad_layer_name(doc, preset):
    doc.layers.add("Some Random Layer")
    assert any("Some Random Layer" in p for p in vf.check_layers(doc, preset))


# ---------------------------------------------------------------- rooms
def test_rooms_closed_labelled_and_areas_match(doc, preset):
    assert vf.check_rooms(doc, preset) == []


def _first_label(doc, preset):
    return doc.modelspace().query(f'MTEXT[layer=="{sf.layer_name(preset, "room_stamp")}"]')[0]


def test_falsify_label_moved_outside(doc, preset):
    _first_label(doc, preset).dxf.insert = (50.0, 50.0)
    assert any("inside 0 outlines" in p for p in vf.check_rooms(doc, preset))


def test_falsify_label_area_off_by_5_percent(doc, preset):
    mt = _first_label(doc, preset)
    text = mt.text
    num = re.search(r"([0-9]+,[0-9]+) m²", text).group(1)
    wrong = f"{float(num.replace(',', '.')) * 1.05:.2f}".replace(".", ",")
    mt.text = text.replace(num, wrong)
    assert any("area" in p for p in vf.check_rooms(doc, preset))


def test_falsify_open_outline(doc, preset):
    pl = doc.modelspace().query(f'LWPOLYLINE[layer=="{sf.layer_name(preset, "zone")}"]')[0]
    pl.closed = False
    assert any("not closed" in p for p in vf.check_rooms(doc, preset))


# ---------------------------------------------------------------- doors
def test_doors_radius_equals_width_and_connect_rooms(doc, preset):
    assert vf.check_doors(doc, preset) == []
    doors, _ = vf.door_sides(doc, preset)
    assert len(doors) == len(preset["doors"])
    assert {d["width"] for d in doors} == {round(d["width"], 3) for d in preset["doors"]}
    assert sum("outside" in d["connects"] for d in doors) == 1  # one entrance door


def test_a_room_has_two_doors_for_two_way_switching(doc, preset):
    doors, _ = vf.door_sides(doc, preset)
    rooms = [side for d in doors for side in d["connects"]]
    assert rooms.count("Wohnzimmer") >= 2


def test_falsify_arc_radius(doc, preset):
    arc = doc.modelspace().query(f'ARC[layer=="{sf.layer_name(preset, "door")}"]')[0]
    arc.dxf.radius = arc.dxf.radius + 0.1
    assert vf.check_doors(doc, preset) != []


def test_falsify_door_moved_into_void(doc, preset):
    for e in doc.modelspace().query(f'*[layer=="{sf.layer_name(preset, "door")}"]'):
        e.translate(0, 40, 0)
    assert any("not inside a room" in p or "neither" in p for p in vf.check_doors(doc, preset))


# ---------------------------------------------------------------- walls
def test_walls_form_closed_outer_boundary(doc, preset):
    assert vf.check_outer_boundary(doc, preset) == []
    fill = vf.outer_fill(doc, preset)
    g = preset["grid"]
    expected = (g["x"]["xO"] - g["x"]["xo"]) * (g["y"]["yO"] - g["y"]["yo"])
    assert fill.area == pytest.approx(expected, rel=1e-9)


def test_outer_walls_are_altbau_thick(preset):
    walls = [sf.Wall(preset, w) for w in preset["walls"]]
    outer = [w for w in walls if w.id.startswith("outer_")]
    assert outer and all(w.thickness == pytest.approx(0.5) for w in outer)
    inner = {round(w.thickness, 3) for w in walls if not w.id.startswith("outer_")}
    assert inner <= {0.12, 0.25}


def test_falsify_outer_face_line_removed(doc, preset):
    yo = preset["grid"]["y"]["yo"]
    layer = sf.layer_name(preset, "wall_tragend")
    outer = [ln for ln in doc.modelspace().query(f'LINE[layer=="{layer}"]')
             if abs(ln.dxf.start.y - yo) < 1e-9 and abs(ln.dxf.end.y - yo) < 1e-9]
    assert outer, "expected outer face lines on the south side"
    doc.modelspace().delete_entity(outer[0])
    assert vf.check_outer_boundary(doc, preset) != []


# ---------------------------------------------------------------- paper space
def test_viewport_is_1_to_100(doc, preset):
    psp = doc.paperspace()
    vps = [v for v in psp.query("VIEWPORT") if v.dxf.id != 1]
    assert len(vps) == 1
    vp = vps[0]
    assert vp.dxf.height / vp.dxf.view_height == pytest.approx(1000 / 100)


def test_title_block_is_obviously_fake(doc):
    texts = " ".join(t.dxf.text for t in doc.paperspace().query("TEXT"))
    assert "synthetisches Beispiel" in texts
    assert "fiktive Adresse" in texts
    assert "KEINE REALEN" in texts


# ---------------------------------------------------------------- determinism
def test_generation_is_byte_identical(tmp_path):
    a, b = tmp_path / "a.dxf", tmp_path / "b.dxf"
    sf.generate(PRESET_PATH, a)
    sf.generate(PRESET_PATH, b)
    assert a.read_bytes() == b.read_bytes()


def _raw_header(path, var):
    # read the written tags directly: ezdxf.readfile() refreshes some
    # timestamps on load, so the in-memory header is the wrong object to test
    lines = path.read_text(encoding="utf-8").splitlines()
    i = lines.index(var)
    return lines[i + 2].strip()


def test_header_timestamps_come_from_preset(generated, preset):
    path = generated[0]
    jd = juliandate(datetime.fromisoformat(preset["meta"]["created_utc"]))
    for var in ("$TDCREATE", "$TDUCREATE", "$TDUPDATE", "$TDUUPDATE"):
        assert float(_raw_header(path, var)) == pytest.approx(jd, abs=1e-9), var
    assert _raw_header(path, "$VERSIONGUID") == preset["meta"]["version_guid"]
    assert _raw_header(path, "$FINGERPRINTGUID") == preset["meta"]["fingerprint_guid"]
    # ezdxf marker strings must carry its fixed constant date, not the wall clock
    stamps = re.findall(r"@ (\d{4}-\d{2}-\d{2})T", path.read_text(encoding="utf-8"))
    assert stamps and set(stamps) == {"2000-01-01"}


def test_falsify_determinism_detects_a_change(tmp_path, preset):
    changed = json.loads(json.dumps(preset))
    changed["rooms"][0]["name"] = "Diele"
    p = tmp_path / "p.json"
    p.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
    a, b = tmp_path / "a.dxf", tmp_path / "b.dxf"
    sf.generate(PRESET_PATH, a)
    sf.generate(p, b)
    assert a.read_bytes() != b.read_bytes()


def test_committed_sample_is_up_to_date(generated):
    assert SAMPLE_PATH.read_bytes() == generated[0].read_bytes(), \
        "samples/synthetic_flat.dxf is stale: re-run tools/synthetic_flat.py"


# ---------------------------------------------------------------- CLI exit codes
def _run_validator(path):
    return subprocess.run([sys.executable, str(VALIDATOR), str(path), "--preset", str(PRESET_PATH)],
                          capture_output=True, text=True).returncode


def test_cli_exit_codes(generated, tmp_path, preset):
    assert _run_validator(generated[0]) == 0
    broken = ezdxf.readfile(generated[0])
    _first_label(broken, preset).dxf.insert = (50.0, 50.0)
    bad = tmp_path / "bad.dxf"
    broken.saveas(bad)
    assert _run_validator(bad) == 1
    garbage = tmp_path / "garbage.dxf"
    garbage.write_text("not a dxf file\n")
    assert _run_validator(garbage) == 3


def test_dimension_parts_are_on_the_dimension_layer(doc, preset):
    """The anonymous dimension blocks hold no entity on layer "0" (ezdxf puts the dimension and extension lines there);
    only Defpoints (CAD's non-plotting layer) may differ. Model and paper space hold nothing on "0" either. The named
    arrowhead blocks keep layer 0 on purpose: content on "0" takes the layer of the INSERT that places it."""
    dim_layer = sf.layer_name(preset, "dimension")
    anon = [b for b in doc.blocks if b.name.startswith("*D")]
    assert len(anon) == len(preset["dimensions"])
    for b in anon:
        assert {e.dxf.layer for e in b} <= {dim_layer, "Defpoints"}, b.name
        assert any(e.dxf.layer == dim_layer and e.dxftype() == "LINE" for e in b)
    for space in (doc.modelspace(), doc.paperspace()):
        assert all(e.dxf.layer != "0" for e in space)


def test_dimension_layer_check_falsified(doc, preset):
    """The same predicate goes red when a dimension line is put back on layer 0."""
    dim_layer = sf.layer_name(preset, "dimension")
    b = next(b for b in doc.blocks if b.name.startswith("*D"))
    next(e for e in b if e.dxftype() == "LINE").dxf.layer = "0"
    assert not {e.dxf.layer for e in b} <= {dim_layer, "Defpoints"}
