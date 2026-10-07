"""The reader options of vpt/plan_extract.py for real drawings (presets/plan_extract.json: text_reader, room_label_rule,
wall_reader). Each failure mode is reproduced on a small synthetic drawing built here: the default reader gets it wrong, the
option gets it right, and switching the option's repair off makes the test go red again (falsification)."""
import copy
import json
import math
import re

import ezdxf
import pytest
from shapely import STRtree
from shapely.geometry import LineString

from conftest import ROOT, SAMPLE_PATH
from vpt import plan_extract as pe

PRE = json.loads((ROOT / "presets" / "plan_extract.json").read_text(encoding="utf-8"))
LAB, ZON, WALL = "1OG_10_Raumstempel", "1OG_11_Zonen", "1OG_20_Wand_tragend"


def with_opts(**kw) -> dict:
    p = copy.deepcopy(PRE)
    for k, v in kw.items():
        p[k] = dict(p[k], **v) if isinstance(v, dict) else v
    return p


def new_doc():
    doc = ezdxf.new("R2018")
    doc.units = ezdxf.units.M
    for name in (LAB, ZON, WALL):
        doc.layers.add(name)
    return doc


def storey(doc, pre):
    ex = pe.extract(doc, pre)
    (st,) = ex["storeys"]
    return st


# ---- the defaults leave the synthetic flat as it was --------------------------------------------------------------------

def test_committed_preset_uses_the_default_readers():
    o = pe.options(PRE)
    assert (o["text_reader"], o["room_label_rule"]["rule"], o["wall_reader"]["reader"]) == ("plain", "every_text", "exploded_lines")


def test_defaults_equal_a_preset_without_the_keys():
    doc = ezdxf.readfile(SAMPLE_PATH)
    old = {k: v for k, v in PRE.items() if k not in ("text_reader", "text_reader_note", "room_label_rule", "wall_reader")}
    assert pe.extract(doc, old)["storeys"] == pe.extract(doc, PRE)["storeys"]


@pytest.mark.parametrize("bad, msg", [
    ({"text_reader": "fancy"}, "text_reader"),
    ({"room_label_rule": {"rule": "guess"}}, "room_label_rule.rule"),
    ({"wall_reader": {"reader": "all"}}, "wall_reader.reader"),
    ({"room_label_rule": {"rule": "area_with_name_above", "max_dx_heights": None}}, "max_dx_heights"),
    ({"wall_reader": {"reader": "top_level_paths", "flatten_m": 0}}, "flatten_m"),
])
def test_unknown_or_incomplete_options_are_refused(bad, msg):
    with pytest.raises(ValueError, match=re.escape(msg)):
        pe.options(with_opts(**bad))


# ---- text_reader: MTEXT codes ------------------------------------------------------------------------------------------

AREA_NBSP = r"Bad\P5,00\~m{\H.66x;\S2^ ;}"      # area with a non-breaking space and a small stacked superscript


def mtext_doc():
    doc = new_doc()
    msp = doc.modelspace()
    msp.add_mtext(AREA_NBSP, dxfattribs={"layer": LAB, "char_height": 0.2, "insert": (1, 2)})
    msp.add_lwpolyline([(0, 0), (3, 0), (3, 3), (0, 3)], close=True, dxfattribs={"layer": ZON})
    return doc


def test_plain_reader_loses_the_area_text():
    (r,) = storey(mtext_doc(), PRE)["rooms"]
    assert r["name"] == "Bad" and r["area_text"] is None


def test_mtext_clean_reads_the_area_text():
    (r,) = storey(mtext_doc(), with_opts(text_reader="mtext_clean"))["rooms"]
    assert (r["name"], r["area_text"]) == ("Bad", "5,00 m2")


def test_mtext_clean_repairs_each_code():
    assert pe.mtext_clean(r"{\H0.7x;12\~34}") == "12 34"
    assert pe.mtext_clean(r"12,50 m{\H.66x;2}") == "12,50 m2"
    assert pe.mtext_clean(r"m\S2^ ;") == "m2"
    assert pe.mtext_clean(r"a\\H.5") == r"a\H.5"          # an escaped backslash is text, not a code


def test_fast_reader_drops_the_nbsp_code():
    """Why mtext_clean uses the full parser: the fast reader (the default) loses the area unit after \\~."""
    m = new_doc().modelspace().add_mtext(r"5,00\~m{\H0.66x;\S2^ ;}")
    assert "m" not in m.plain_text() and pe.mtext_clean(m.text) == "5,00 m2"


@pytest.mark.parametrize("attr, raw, wrong", [
    ("_MT_BARE_DOT", r"12,50 m{\H.66x;2}", "12,50 m2"),
    ("_CARET", r"m\S2^ ;", "m2"),
])
def test_mtext_clean_falsified(monkeypatch, attr, raw, wrong):
    monkeypatch.setattr(pe, attr, re.compile(r"(?!x)x"))     # the repair switched off: matches nothing
    assert pe.mtext_clean(raw) != wrong


def test_mtext_clean_falsified_on_the_drawing(monkeypatch):
    monkeypatch.setattr(pe, "_MT_BARE_DOT", re.compile(r"(?!x)x"))
    (r,) = storey(mtext_doc(), with_opts(text_reader="mtext_clean"))["rooms"]
    assert r["area_text"] != "5,00 m2"


# ---- room_label_rule: a label layer that also holds notes, dimensions and a table ---------------------------------------

def label_doc():
    doc = new_doc()
    msp = doc.modelspace()
    t = lambda s, x, y: msp.add_text(s, dxfattribs={"layer": LAB, "height": 0.2, "insert": (x, y)})
    t("Kueche", 1, 3.0)
    t("12,34 m2", 1, 2.7)
    t("Fliesen", 1, 2.35)        # floor finish below the area text
    t("RH 2,80", 2.5, 3.0)       # room height beside the name
    t("Zimmer", 6, 3.0)
    t("20,00 m2", 6, 2.7)
    t("3,45", 5, 1.0)            # a dimension
    t("TOP 1", 10, 5.0)          # a table: header and rows
    t("Kueche", 10, 4.7)
    t("12,34 m2", 10, 4.4)
    return doc


AREA_RULE = {"rule": "area_with_name_above", "table_header_regex": r"^TOP\b"}


def test_every_text_makes_a_room_of_every_note():
    rooms = storey(label_doc(), PRE)["rooms"]
    assert len(rooms) == 7
    assert {"Fliesen", "RH 2,80", "3,45", "TOP 1"} <= {r["name"] for r in rooms}


def test_area_with_name_above_keeps_only_the_rooms():
    rooms = storey(label_doc(), with_opts(room_label_rule=AREA_RULE))["rooms"]
    assert [(r["name"], r["area_text"], r["anchor"]) for r in rooms] == [
        ("Kueche", "12,34 m2", [1.0, 2.7]), ("Zimmer", "20,00 m2", [6.0, 2.7])]


def test_area_with_name_above_falsified_without_the_table_rule():
    rooms = storey(label_doc(), with_opts(room_label_rule=dict(AREA_RULE, table_header_regex="")))["rooms"]
    assert len(rooms) == 3                                       # the table row is taken as a room


def test_area_with_name_above_falsified_with_a_tight_window():
    rooms = storey(label_doc(), with_opts(room_label_rule=dict(AREA_RULE, max_dy_heights=1.0)))["rooms"]
    assert [r["name"] for r in rooms] == [None, None]          # the name 1.5 heights above is out of reach


def test_multi_line_mtext_label():
    doc = new_doc()
    doc.modelspace().add_mtext(r"Abstellraum\P2,10 m2\PFliesen", dxfattribs={"layer": LAB, "char_height": 0.2, "insert": (1, 2)})
    doc.modelspace().add_text("Fliesen", dxfattribs={"layer": LAB, "height": 0.2, "insert": (4, 2)})
    rooms = storey(doc, with_opts(room_label_rule=AREA_RULE))["rooms"]
    assert [(r["name"], r["area_text"]) for r in rooms] == [("Abstellraum", "2,10 m2")]


# ---- wall_reader: walls drawn as hatches; a block on a wall layer ------------------------------------------------------

def assign_with(st, x, y):
    walls = [LineString([w["p"], w["q"]]) for w in st["walls"]]
    labels = [{"id": r["id"], "px": r["anchor"][0], "py": r["anchor"][1]} for r in st["rooms"]]
    return pe.assign(x, y, labels, [], STRtree(walls) if walls else None, PRE["label_max_dist_m"])[0]


def hatch_doc(with_zones=False):
    """Two rooms; the wall between them (x 4.0-4.2) is drawn only as a solid HATCH."""
    doc = new_doc()
    msp = doc.modelspace()
    msp.add_text("Raum A", dxfattribs={"layer": LAB, "height": 0.2, "insert": (2.5, 1.5)})
    msp.add_text("Raum B", dxfattribs={"layer": LAB, "height": 0.2, "insert": (4.6, 1.5)})
    h = msp.add_hatch(dxfattribs={"layer": WALL})
    h.paths.add_polyline_path([(4.0, 0), (4.2, 0), (4.2, 3), (4.0, 3)], is_closed=True)
    if with_zones:
        msp.add_lwpolyline([(0, 0), (4.0, 0), (4.0, 3), (0, 3)], close=True, dxfattribs={"layer": ZON})
        msp.add_lwpolyline([(4.2, 0), (8, 0), (8, 3), (4.2, 3)], close=True, dxfattribs={"layer": ZON})
    return doc


TOP_LEVEL = {"reader": "top_level_paths"}


def test_hatch_walls_default_sees_no_wall():
    st = storey(hatch_doc(), PRE)
    assert st["walls"] == []
    assert assign_with(st, 3.9, 1.5) == "1OG-R2"               # wrong: room B's label, through the wall


def test_hatch_walls_top_level_paths():
    st = storey(hatch_doc(), with_opts(wall_reader=TOP_LEVEL))
    assert len(st["walls"]) == 4
    assert assign_with(st, 3.9, 1.5) == "1OG-R1"               # right: B is behind the wall


def test_hatch_walls_r5():
    r5 = lambda pre: next(c for c in storey(hatch_doc(with_zones=True), pre)["checks"] if c["id"] == "R5")["status"]
    assert r5(PRE) == pe.UNK
    assert r5(with_opts(wall_reader=TOP_LEVEL)) == pe.MATCH


def test_top_level_paths_falsified_without_hatches(monkeypatch):
    monkeypatch.setattr(pe, "wall_segments_top_level", lambda doc, layers, f: [])     # the reader switched off
    st = storey(hatch_doc(), with_opts(wall_reader=TOP_LEVEL))
    assert assign_with(st, 3.9, 1.5) == "1OG-R2"


def block_doc():
    """One room with line walls; a detail block (a line on layer 0) inserted on the wall layer inside the room."""
    doc = new_doc()
    msp = doc.modelspace()
    msp.add_text("Raum A", dxfattribs={"layer": LAB, "height": 0.2, "insert": (1.5, 1.5)})
    for p, q in (((0, 0), (5, 0)), ((5, 0), (5, 3)), ((5, 3), (0, 3)), ((0, 3), (0, 0))):
        msp.add_line(p, q, dxfattribs={"layer": WALL})
    blk = doc.blocks.new("DETAIL")
    blk.add_line((0, 0.2), (0, 2.8), dxfattribs={"layer": "0"})
    msp.add_blockref("DETAIL", (3.4, 0), dxfattribs={"layer": WALL})
    return doc


def test_block_on_wall_layer_default_blocks_the_room():
    st = storey(block_doc(), PRE)
    assert len(st["walls"]) == 5
    assert assign_with(st, 3.6, 1.5) is None                   # wrong: the detail line counts as a wall


def test_block_on_wall_layer_top_level_paths():
    st = storey(block_doc(), with_opts(wall_reader=TOP_LEVEL))
    assert len(st["walls"]) == 4
    assert assign_with(st, 3.6, 1.5) == "1OG-R1"


def test_top_level_paths_flattens_arcs():
    doc = new_doc()
    doc.modelspace().add_text("Raum A", dxfattribs={"layer": LAB, "height": 0.2, "insert": (0, 0)})
    doc.modelspace().add_arc((0, 0), 2.0, 0, 90, dxfattribs={"layer": WALL})
    fine = storey(doc, with_opts(wall_reader=dict(TOP_LEVEL, flatten_m=0.001)))["walls"]
    coarse = storey(doc, with_opts(wall_reader=dict(TOP_LEVEL, flatten_m=0.1)))["walls"]
    assert storey(doc, PRE)["walls"] == []                      # the default reader skips arcs
    assert len(fine) > len(coarse) >= 2
    assert all(abs(math.dist(w["p"], (0, 0)) - 2.0) < 0.001 for w in fine)
