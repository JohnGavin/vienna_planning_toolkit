"""DXF -> SVG with one group per layer (vpt/dxf_svg.py) on the synthetic flat: every layer gets its group, the output is
deterministic, the affine agrees with the renderer's own mapping, no raster content."""
import ezdxf
import pytest

from vpt import dxf_svg

PAGE = {"width_mm": 130.0, "height_mm": 110.0, "limits": (-1.5, 11.5, -1.5, 9.5)}


@pytest.fixture(scope="module")
def drawn(generated):
    doc = ezdxf.readfile(generated[0])
    layers = {lay.dxf.name for lay in doc.layers if lay.dxf.name.startswith("2OG_")}
    r = dxf_svg.render(doc, doc.modelspace(), PAGE, key="2OG", layers=layers, units=dxf_svg.view_units(PAGE, 1000.0))
    return doc, layers, r


def test_one_group_per_layer_and_no_raster(drawn):
    _, layers, r = drawn
    info = dxf_svg.inspect(dxf_svg.finish(r["root"], key="2OG"))
    assert layers <= set(info["groups"]) and not info["duplicates"] and info["images"] == 0
    assert info["storey"] == "2OG" and info["paths"] == sum(r["paths"].values()) > 0
    assert info["groups"]["2OG_21_Tueren"] == r["paths"]["2OG_21_Tueren"] > 0


def test_deterministic(drawn, generated):
    _, layers, _ = drawn
    texts = []
    for _ in range(2):                       # two fresh renders (finish() adds the paper to the tree it is given)
        d = ezdxf.readfile(generated[0])
        r = dxf_svg.render(d, d.modelspace(), PAGE, key="2OG", layers=layers, units=dxf_svg.view_units(PAGE, 1000.0))
        texts.append(dxf_svg.finish(r["root"], key="2OG"))
    assert texts[0] == texts[1]


def test_affine_matches_to_view(drawn):
    _, _, r = drawn
    for x, y in ((0, 0), (10.5, 8.5), (-0.5, 9.0)):
        assert dxf_svg.apply_affine(r["affine"], x, y) == pytest.approx(r["to_view"](x, y))
    # falsified: a y flip forgotten would map the top of the flat below its bottom
    assert dxf_svg.apply_affine(r["affine"], 0, 9.0)[1] < dxf_svg.apply_affine(r["affine"], 0, 0)[1]


def test_inspect_finds_raster_and_bad_root():
    assert dxf_svg.inspect('<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,AA"/></svg>')["images"] == 2
    with pytest.raises(ValueError):
        dxf_svg.inspect('<g xmlns="http://www.w3.org/2000/svg"></g>')


def test_view_units_clamped():
    cfg = dxf_svg.settings()
    assert dxf_svg.view_units({"width_mm": 1, "height_mm": 1, "limits": (0, 0.001, 0, 0.001)}, 1000.0) == cfg["svg_min_units"]
    assert dxf_svg.view_units(PAGE, 1000.0) == 13000
    assert dxf_svg.view_units(PAGE, None) == max(round(130 / cfg["svg_paper_resolution_mm"]), cfg["svg_min_units"])


def test_texts_are_svg_text_not_font_outlines(drawn, preset):
    """Texts are <text> elements (browser font: the same SVG on every computer), not glyph outlines of a system font."""
    import re
    _, _, r = drawn
    svg = dxf_svg.finish(r["root"], key="2OG")
    stamp = re.search(r'<g data-layer="2OG_41_Raumstempel"[^>]*>(.*?)</g>', svg).group(1)
    assert "<path" not in stamp
    assert {n["name"] for n in preset["rooms"]} <= set(re.findall(r"<tspan[^>]*>([^<]+)</tspan>", stamp))
    dims = re.search(r'<g data-layer="2OG_50_Bemassung"[^>]*>(.*?)</g>', svg).group(1)
    # the vertical dimension text (90 degrees counter-clockwise in the model) turns counter-clockwise on screen: rotate(-90)
    assert re.search(r'rotate\(-90\)"[^>]*><tspan[^>]*>950<', dims)
    assert "rotate(90)" not in dims
