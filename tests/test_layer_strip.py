"""Layer stripping (vpt/layer_strip.py, tools/strip_layers.py) on the synthetic flat: the electrical base keeps exactly the kept
layers, every check goes red on a deliberately broken run, and unclassified layers are flagged, never quietly kept or dropped."""
import json

import ezdxf
import pytest

import strip_layers as tool
from conftest import ROOT, SAMPLE_PATH
from vpt import layer_strip as ls
from vpt import plan

LP = ls.load_preset()
PRE = json.loads(plan.EXTRACT_PRESET.read_text(encoding="utf-8"))


def layers_of(path) -> set:
    return {layer.dxf.name for layer in ezdxf.readfile(path).layers}


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    out = tmp_path_factory.mktemp("strip")
    return ls.run(SAMPLE_PATH, out), out


def test_the_base_keeps_exactly_the_kept_layers(result):
    res, out = result
    assert res["status"] == "PASS", res["failures"] + res["unknowns"] + [str(f) for f in res["flagged"]]
    assert [s["key"] for s in res["storeys"]] == ["2OG"]
    src = layers_of(SAMPLE_PATH)
    # derived here from the preset, not from the code under test: dropped = the drop bases and the Abbruch status
    gone = {n for n in src if n.endswith(tuple("_" + b for b in LP["drop"])) or "_Abbruch_" in n}
    assert len(gone) == len(LP["drop"]) + 1
    produced = layers_of(out / "synthetic_flat__2OG__electrical_base.dxf")
    assert produced == src - gone
    assert [c["status"] for c in res["storeys"][0]["checks"]] == ["match"] * 7


def test_the_base_still_exports_as_a_plan(result, tmp_path):
    """Rooms, walls and doors survive the strip: the electrical base opens in the editor's plan export with every check passing."""
    _, out = result
    p = plan.export(out / "synthetic_flat__2OG__electrical_base.dxf", synthetic=True)
    assert p["extract"]["status"] == "PASS" and len(p["storeys"][0]["rooms"]) == 7
    names = {x["layer"] for x in p["storeys"][0]["layers"]}
    assert not any("Bemassung" in n or "Abbruch" in n for n in names)


def test_deleted_not_hidden_and_the_source_is_untouched(result):
    _, out = result
    doc = ezdxf.readfile(out / "synthetic_flat__2OG__electrical_base.dxf")
    for e in list(doc.modelspace()) + list(doc.paperspace()):
        assert not e.dxf.layer.endswith(("Bemassung", "Decke", "Plankopf")) and "_Abbruch_" not in e.dxf.layer
    for b in doc.blocks:
        assert all(not e.dxf.layer.endswith("Bemassung") for e in b)
    assert any(layer.endswith("Bemassung") for layer in layers_of(SAMPLE_PATH))


# ---- falsification: every check must be able to go red ---------------------------------------------------------

def test_x1_x3_x4_go_red_when_nothing_is_stripped(tmp_path, monkeypatch):
    from collections import Counter
    monkeypatch.setattr(ls, "strip", lambda doc, drop: Counter())
    res = ls.run(SAMPLE_PATH, tmp_path)
    assert res["status"] == "FAIL"
    red = {c["id"] for c in res["checks"] if c["status"] == "different"}
    assert {"X1", "X3", "X4"} <= red


def test_x2_x4_go_red_when_a_kept_layer_is_stripped_too(tmp_path, monkeypatch):
    real = ls.strip
    monkeypatch.setattr(ls, "strip", lambda doc, drop: real(doc, set(drop) | {"2OG_20_Fenster"}))
    res = ls.run(SAMPLE_PATH, tmp_path)
    red = {c["id"] for c in res["checks"] if c["status"] == "different"}
    assert res["status"] == "FAIL" and {"X2", "X4"} <= red


def test_an_empty_preset_cannot_pass(tmp_path):
    """No decisions at all: every layer with content is unclassified, flagged and kept: could-not-tell, never PASS."""
    res = ls.run(SAMPLE_PATH, tmp_path, dict(LP, keep=[], drop=[], drop_status=[]))
    assert res["status"] == "INDETERMINATE" and res["storeys"][0]["unclassified"]
    assert any(f["id"] == "X5" for f in res["flagged"])
    assert layers_of(tmp_path / "synthetic_flat__2OG__electrical_base.dxf") == layers_of(SAMPLE_PATH)


def test_a_new_layer_is_flagged_and_kept(tmp_path):
    doc = ezdxf.readfile(SAMPLE_PATH)
    doc.layers.add("2OG_77_Neuheit")
    doc.modelspace().add_line((0, 0), (1, 1), dxfattribs={"layer": "2OG_77_Neuheit"})
    src = tmp_path / "flat_plus.dxf"
    doc.saveas(src)
    res = ls.run(src, tmp_path / "out")
    assert res["status"] == "INDETERMINATE" and res["storeys"][0]["unclassified"] == ["2OG_77_Neuheit"]
    assert "2OG_77_Neuheit" in layers_of(tmp_path / "out" / "flat_plus__2OG__electrical_base.dxf")
    # an empty new layer is not flagged (no content)
    doc2 = ezdxf.readfile(SAMPLE_PATH)
    doc2.layers.add("2OG_78_Leer")
    src2 = tmp_path / "flat_empty.dxf"
    doc2.saveas(src2)
    assert ls.run(src2, tmp_path / "out2")["status"] == "PASS"


def test_several_storeys_give_one_base_each_and_flag_stray_layers(tmp_path):
    doc = ezdxf.readfile(SAMPLE_PATH)
    for name, layer in (("a", "3OG_10_Wand_tragend"), ("b", "3OG_50_Bemassung"), ("c", "Stray")):
        doc.layers.add(layer)
        doc.modelspace().add_line((0, 0), (2, 2), dxfattribs={"layer": layer})
    src = tmp_path / "two.dxf"
    doc.saveas(src)
    res = ls.run(src, tmp_path / "out")
    assert [s["key"] for s in res["storeys"]] == ["2OG", "3OG"]
    two, three = (layers_of(tmp_path / "out" / f"two__{k}__electrical_base.dxf") for k in ("2OG", "3OG"))
    assert "3OG_10_Wand_tragend" not in two and "2OG_10_Wand_tragend" not in three
    assert "3OG_10_Wand_tragend" in three and "3OG_50_Bemassung" not in three
    assert "Stray" in two and "Stray" in three                       # kept in every base, never assigned by guessing
    assert res["status"] == "INDETERMINATE"
    assert {(f["id"], f["scope"]) for f in res["flagged"]} == {("X8", "2OG"), ("X8", "3OG")}


# ---- the preset and the tool -----------------------------------------------------------------------------------

def test_overlapping_lists_are_a_usage_error(tmp_path):
    assert ls.validate(dict(LP, drop=LP["drop"] + [LP["keep"][0]]))
    with pytest.raises(ls.UsageError):
        ls.run(SAMPLE_PATH, tmp_path, dict(LP, drop=LP["drop"] + [LP["keep"][0]]))


def test_tool_exit_codes(tmp_path):
    assert tool.main([str(SAMPLE_PATH), "--outdir", str(tmp_path / "a")]) == 0
    assert tool.main([str(tmp_path / "missing.dxf"), "--outdir", str(tmp_path / "b")]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(dict(LP, drop=LP["drop"] + [LP["keep"][0]])))
    assert tool.main([str(SAMPLE_PATH), "--outdir", str(tmp_path / "c"), "--preset", str(bad)]) == 2
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps(dict(LP, keep=[], drop=[], drop_status=[])))
    assert tool.main([str(SAMPLE_PATH), "--outdir", str(tmp_path / "d"), "--preset", str(empty)]) == 3
    junk = tmp_path / "junk.dxf"
    junk.write_text("not a drawing\n" * 20)
    assert tool.main([str(junk), "--outdir", str(tmp_path / "e")]) == 3
