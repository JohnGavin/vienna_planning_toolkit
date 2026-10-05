"""The layout written into a copy of its DXF (vpt/dxf_export.py, tools/export_layout_dxf.py) on the synthetic flat and its
generated examples: written and verified, deterministic, the committed sample current; refused when the layout is of another
drawing or storey (nothing written); could-not-tell for an invalid layout or unknown units; the read-back check falsified."""
import copy
import json
import os
import subprocess
import sys

import ezdxf
import pytest

from conftest import ROOT, SAMPLE_PATH
from vpt import dxf_export, el_symbols

PLAN_PATH = ROOT / "samples" / "synthetic_flat.plan.json"
OUT_SAMPLE = ROOT / "samples" / "synthetic_flat_elektro.dxf"
PLAN = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
ST = next(s for s in PLAN["storeys"] if s["examples"])
PRE = dxf_export.load()
LIB = el_symbols.load()

import export_layout_dxf as tool  # noqa: E402


def layout_file(tmp_path, ex_id="complex", mutate=None):
    lay = copy.deepcopy(ST["examples"][ex_id])
    if mutate:
        mutate(lay)
    p = tmp_path / f"flat__{ex_id}.electrical.json"
    p.write_text(json.dumps(lay, ensure_ascii=False), encoding="utf-8")
    return p, lay


def run(*args):
    return tool.main([str(a) for a in args])


@pytest.mark.parametrize("ex_id", ["simple", "complex"])
def test_export_writes_every_symbol_in_place(tmp_path, ex_id):
    p, lay = layout_file(tmp_path, ex_id)
    out = tmp_path / "out.dxf"
    assert run("--dxf", SAMPLE_PATH, "--layout", p, "--plan", PLAN_PATH, "--out", out) == 0
    doc = ezdxf.readfile(out)
    ins = [e for e in doc.modelspace().query("INSERT") if e.dxf.name.startswith(PRE["block_prefix"])]
    want = {}
    for s in lay["symbols"]:
        want[s["code"]] = want.get(s["code"], 0) + 1
    got = {}
    for e in ins:
        c = e.get_attrib_text("CODE")
        got[c] = got.get(c, 0) + 1
    assert got == want
    by = {e.get_attrib_text("SYMBOL_ID"): e for e in ins}
    for s in lay["symbols"]:
        e = by[s["id"]]
        assert abs(e.dxf.insert.x - s["x"]) * 1000 < 1 and abs(e.dxf.insert.y - s["y"]) * 1000 < 1      # model in metres: within 1 mm
        assert e.get_attrib_text("VERIFIED") == "false" and e.get_attrib_text("ROOM") == (s["room"] or "")
        assert e.dxf.rotation == pytest.approx(s["rotation"])
    links = [e for e in doc.modelspace().query("LINE") if e.dxf.layer == PRE["layers"]["links"]]
    assert len(links) == len(lay["links"]) and all(e.dxf.linetype == PRE["linetype"] for e in links)
    assert any("UNVERIFIED" in e.dxf.text for e in doc.modelspace().query("TEXT") if e.dxf.layer == PRE["layers"]["note"])
    # the source drawing is all still there: every original layer, and as many entities on them
    src = ezdxf.readfile(SAMPLE_PATH)
    assert {x.dxf.name for x in src.layers} <= {x.dxf.name for x in doc.layers}
    assert sum(1 for _ in src.modelspace()) == sum(1 for e in doc.modelspace() if e.dxf.layer not in set(PRE["layers"].values()))


def test_committed_sample_is_current_and_deterministic(tmp_path):
    out = tmp_path / "again.dxf"
    assert run("--dxf", SAMPLE_PATH, "--plan", PLAN_PATH, "--example", "complex", "--out", out) == 0
    assert out.read_bytes() == OUT_SAMPLE.read_bytes(), \
        "run python3 tools/export_layout_dxf.py --dxf samples/synthetic_flat.dxf --plan samples/synthetic_flat.plan.json --example complex --out samples/synthetic_flat_elektro.dxf"


@pytest.mark.parametrize("seed", ["0", "1"])
def test_same_bytes_for_any_hash_seed(tmp_path, seed):
    out = tmp_path / f"seed{seed}.dxf"
    env = dict(os.environ, PYTHONHASHSEED=seed)
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "export_layout_dxf.py"), "--dxf", str(SAMPLE_PATH), "--plan", str(PLAN_PATH),
                        "--example", "complex", "--out", str(out)], env=env, capture_output=True, text=True, timeout=200)
    assert r.returncode == 0, r.stderr
    assert out.read_bytes() == OUT_SAMPLE.read_bytes()


@pytest.mark.parametrize("mutate, want, why", [
    (lambda lay: lay["drawing"].__setitem__("sha256", "ab" * 32), 1, "another drawing"),
    (lambda lay: lay["drawing"].__setitem__("storey", "9OG"), 1, "storey 9OG"),
    (lambda lay: lay.__setitem__("schema_version", 7), 3, "not a valid layout"),
    (lambda lay: lay["symbols"][0].__setitem__("code", "ZZ"), 3, "ZZ"),
    (lambda lay: lay.__setitem__("model_units_mm", 1.0), 3, "mm per drawing unit"),
])
def test_refused_and_nothing_written(tmp_path, capsys, mutate, want, why):
    p, _ = layout_file(tmp_path, "simple", mutate)
    out = tmp_path / "refused.dxf"
    assert run("--dxf", SAMPLE_PATH, "--layout", p, "--out", out) == want
    assert not out.exists() and why in capsys.readouterr().err


def test_plan_of_another_drawing_refused(tmp_path, capsys):
    p, _ = layout_file(tmp_path, "simple")
    other = copy.deepcopy(PLAN)
    other["drawing"]["sha256"] = "cd" * 32
    pp = tmp_path / "other.plan.json"
    pp.write_text(json.dumps(other), encoding="utf-8")
    out = tmp_path / "x.dxf"
    assert run("--dxf", SAMPLE_PATH, "--layout", p, "--plan", pp, "--out", out) == 1 and not out.exists()
    assert "plan file is of another drawing" in capsys.readouterr().err


def test_unknown_units_could_not_tell(tmp_path):
    doc = ezdxf.readfile(SAMPLE_PATH)
    doc.units = 0
    src = tmp_path / "nounits.dxf"
    doc.saveas(src)
    sha = dxf_export.sha256_file(src)
    p, _ = layout_file(tmp_path, "simple", lambda lay: lay["drawing"].__setitem__("sha256", sha))
    out = tmp_path / "x.dxf"
    assert run("--dxf", src, "--layout", p, "--out", out) == 3 and not out.exists()


def test_usage(tmp_path):
    p, _ = layout_file(tmp_path, "simple")
    assert run("--dxf", SAMPLE_PATH, "--layout", p, "--out", SAMPLE_PATH) == 2
    assert run("--dxf", SAMPLE_PATH, "--out", tmp_path / "x.dxf") == 2
    assert run("--dxf", SAMPLE_PATH, "--example", "simple", "--out", tmp_path / "x.dxf") == 2
    assert run("--dxf", tmp_path / "missing.dxf", "--layout", p, "--out", tmp_path / "x.dxf") == 2
    assert run("--dxf", SAMPLE_PATH, "--layout", tmp_path / "missing.json", "--out", tmp_path / "x.dxf") == 3


# ---- the read-back check can go red -------------------------------------------------------------------------------------------

@pytest.fixture
def written(tmp_path):
    lay = ST["examples"]["complex"]
    out = tmp_path / "w.dxf"
    assert run("--dxf", SAMPLE_PATH, "--plan", PLAN_PATH, "--example", "complex", "--out", out) == 0
    n_src = sum(1 for _ in ezdxf.readfile(SAMPLE_PATH).modelspace())
    return out, lay, n_src


def _verify(out, lay, n_src):
    return dxf_export.verify(out, lay, source_entities=n_src, mm_per_unit=1000.0, pre=PRE, lib=LIB)


def _edit(out, fn):
    doc = ezdxf.readfile(out)
    fn(doc.modelspace())
    doc.saveas(out)


def test_verify_passes_on_the_written_file(written):
    st, probs, nums = _verify(*written)
    assert st == "match" and probs == [] and nums["worst_mm"] < 1e-6 and nums["inserts"] == len(written[1]["symbols"])


@pytest.mark.parametrize("edit, expect", [
    (lambda msp: msp.query("INSERT")[0].dxf.__setattr__("insert", msp.query("INSERT")[0].dxf.insert + (0.002, 0, 0)), "mm from its place"),
    (lambda msp: msp.delete_entity(msp.query("INSERT")[0]), "inserts per code"),
    (lambda msp: msp.delete_entity([e for e in msp.query("LINE") if e.dxf.layer == "E_Verbindungen"][0]), "link lines"),
    (lambda msp: msp.query("INSERT")[0].dxf.__setattr__("layer", "E_Licht" if msp.query("INSERT")[0].dxf.layer != "E_Licht" else "E_Schalter"), "on layer"),
    (lambda msp: msp.delete_entity([e for e in msp.query("TEXT") if e.dxf.layer == "E_Hinweis"][0]), "UNVERIFIED note"),
    (lambda msp: msp.delete_entity([e for e in msp.query("LINE") if e.dxf.layer.endswith("_Wand_tragend")][0]), "entities of the source drawing"),
])
def test_verify_falsified(written, edit, expect):
    out, lay, n_src = written
    _edit(out, edit)
    st, probs, _ = _verify(out, lay, n_src)
    assert st == "different" and any(expect in p for p in probs), probs


# ---- blocks, colours, preset ----------------------------------------------------------------------------------------------------

def test_socket_block_stem_points_down_and_arc_away_from_it():
    doc = ezdxf.new()
    blk = doc.blocks.new("T")
    so = next(x for x in el_symbols.default_set(LIB)["symbols"] if x["code"] == "SO")
    dxf_export.draw_block(blk, so["svg"], PRE)
    arc = next(e for e in blk if e.dxftype() == "ARC")
    line = next(e for e in blk if e.dxftype() == "LINE")
    # SVG +y (the wall side) becomes -y: the stem runs down to (0, -3); the half circle is the upper one (0..180 degrees)
    assert (round(line.dxf.end.y, 6), round(arc.dxf.start_angle % 360, 6), round(arc.dxf.end_angle % 360, 6)) == (-3.0, 0.0, 180.0)
    assert arc.dxf.radius == pytest.approx(3.0)


def test_every_library_symbol_draws_and_unsupported_svg_is_refused():
    doc = ezdxf.new()
    for x in el_symbols.default_set(LIB)["symbols"]:
        assert dxf_export.draw_block(doc.blocks.new("B_" + x["code"]), x["svg"], PRE) > 0, x["code"]
    with pytest.raises(ValueError):
        dxf_export.draw_block(doc.blocks.new("bad"), '<ellipse cx="0" cy="0" rx="2" ry="1"/>', PRE)
    with pytest.raises(ValueError):
        dxf_export.draw_block(doc.blocks.new("bad2"), '<path d="m 0 0 l 1 1"/>', PRE)


def test_aci_from_the_print_palette():
    assert dxf_export.aci_of("#000000") == 7 and dxf_export.aci_of("#ff0000") == 1 and dxf_export.aci_of("#0000ff") == 5


def test_preset_valid_and_falsified():
    assert dxf_export.validate(PRE, LIB) == []
    bad = copy.deepcopy(PRE)
    bad["layers"]["licht"] = "Elektro – Licht"
    assert any("DXF-safe" in p for p in dxf_export.validate(bad, LIB))
    bad = copy.deepcopy(PRE)
    del bad["layers"]["daten"]
    assert any("daten" in p for p in dxf_export.validate(bad, LIB))
