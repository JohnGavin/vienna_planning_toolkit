"""Vector SVG drawings of DXF content with one <g data-layer="..."> group per DXF layer (for the editor's layer toggles).

Rendering: ezdxf's own drawing add-on. The Frontend resolves everything CAD-specific (block INSERTs, hatches, texts as glyph
outlines, arcs, linetypes, lineweights, ACI/true colours); ezdxf's SVGBackend records that output, maps it onto the page
(viewBox in integer units, y down) and crops it at the page edge; this module only replaces the last step, the writer
(SVGRenderBackend), with one that puts every path into the group of the layer the Frontend resolved for it
(BackendProperties.layer: the entity's layer, or for content on layer "0" inside a block, the INSERT's layer, as CAD does).
Why not the stock writer: it puts every path into one flat group (no layer information survives). Why not render each layer
separately: one Frontend pass per layer re-resolves every block and font per layer and loses the drawing order between layers
less predictably than grouping does.

Drawing order: groups are written in the order in which their layer first appears in the Frontend's output, paths within a
group in drawing order (paths of different layers are no longer interleaved; for line drawings that is invisible).

Visibility: every layer is drawn, including layers that are off or frozen in the DXF; those groups carry data-default="off"
and display="none", so the reader can switch them on. Layers that have nothing to draw still get an (empty) group when the
caller names them, so the layer set of the SVG can be compared with the layer set of the DXF (inspect()).

Determinism: hatch patterns are drawn with a small RANDOM origin jiggle by ezdxf; render() seeds it per drawing key and
restores the caller's random state, so the same DXF always gives the same SVG text.

Texts: ezdxf would draw TEXT / MTEXT as glyph outlines of a SYSTEM font (whatever the machine has), so the same DXF would give
different SVGs on different computers. Texts are therefore written as SVG <text> elements (a generic sans-serif font chosen by
the browser) at the entity's position, height, rotation and alignment, in the group of their layer, coloured through the same
prefixed style classes as the paths (marked --vpt-text, so the page recolours them like lines, not like filled areas). Texts inside blocks and dimensions are
included (layer 0 inside a block takes the INSERT's / DIMENSION's layer).

Size: coordinates are integers in the viewBox; the caller chooses the viewBox size (view_units()). Style classes are prefixed
per drawing, because several SVGs may sit inline in one HTML page and their <style> rules are global to the page.
No <image> element is ever written (raster content is dropped, never embedded).
"""
from __future__ import annotations

import json
import pathlib
import random
import re
from collections import Counter
from xml.etree import ElementTree as ET

from vpt import PRESETS

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)
SETTINGS = PRESETS / "svg_drawing.json"


def settings(path: pathlib.Path = SETTINGS) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def view_units(page: dict, mm_per_unit: float | None, cfg: dict | None = None) -> int:
    """viewBox units for the long side of the page: model resolution (svg_model_resolution_mm, in model mm) when the units
    are known, else paper resolution (svg_paper_resolution_mm, in page mm); clamped to [svg_min_units, svg_max_units]."""
    cfg = cfg or settings()
    if mm_per_unit and page.get("limits"):
        x0, x1, y0, y1 = page["limits"]
        n = max(x1 - x0, y1 - y0) * mm_per_unit / float(cfg["svg_model_resolution_mm"])
    else:
        n = max(page["width_mm"], page["height_mm"]) / float(cfg["svg_paper_resolution_mm"])
    return int(min(max(round(n), int(cfg["svg_min_units"])), int(cfg["svg_max_units"])))


def _prefix(key: str) -> str:
    return "k" + re.sub(r"[^A-Za-z0-9]", "", key) + "-"


def render(doc, layout, page: dict, *, key: str, layers, units: int, filter_func=None, hatch_outlines: bool = False) -> dict:
    """Draw `layout` of `doc` onto `page` ({width_mm, height_mm, limits=(x0, x1, y0, y1) in layout units}).

    layers: the layers to give a group even when nothing is drawn on them. Returns {"root": the <svg> Element, "paths":
    {layer: number of paths}, "order": layers in group order, "off": layers off/frozen in the DXF, "to_view": a function
    mapping a layout point (x, y) to viewBox coordinates, "affine": the same mapping as [a, b, c, d, e, f] with
    X = a*x + c*y + e, Y = b*x + d*y + f, "scale": viewBox units per page mm}.
    hatch_outlines: draw every HATCH as its boundary outline instead of its pattern."""
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing import layout as dlayout
    from ezdxf.addons.drawing import svg as dsvg
    from ezdxf.addons.drawing.config import BackgroundPolicy, Configuration, HatchPolicy, TextPolicy
    from ezdxf.math import BoundingBox2d, Vec3

    prefix = _prefix(key)
    off: set[str] = set()

    def all_visible(layer_props):
        for lp in layer_props:
            if not lp.is_visible:
                off.add(lp.layer)
            lp.is_visible = True

    class Writer(dsvg.SVGRenderBackend):
        def __init__(self, pg, settings_):
            super().__init__(pg, settings_)
            self.root.remove(self.background)              # the paper is drawn by the page (a CSS class)
            self.root.remove(self.root.find("defs"))       # styles: one prefixed <style> element, written at the end
            self.entities.set("class", "dwg")
            self.groups: dict[str, ET.Element] = {}
            self.count: Counter = Counter()
            self.cls: dict[str, str] = {}

        def set_background(self, color) -> None:
            pass

        def _style(self, rule: str) -> str:
            if rule not in self.cls:
                self.cls[rule] = f"{prefix}{len(self.cls) + 1:x}"
            return self.cls[rule]

        def _add(self, d: str, properties, rule: str) -> None:
            if not d:
                return
            layer = properties.layer or "0"
            g = self.groups.get(layer)
            if g is None:
                g = self.groups[layer] = ET.SubElement(self.entities, "g", {"data-layer": layer})
            ET.SubElement(g, "path", {"d": d, "class": self._style(rule)})
            self.count[layer] += 1

        def add_strokes(self, d: str, properties) -> None:
            colour, opacity = self.resolve_color(properties.color)
            rule = f"fill:none;stroke:{colour};stroke-width:{self.resolve_stroke_width(properties.lineweight)}" + (
                f";stroke-opacity:{opacity:.3f}" if opacity < 1 else "")
            self._add(d, properties, rule)

        def add_filling(self, d: str, properties) -> None:
            colour, opacity = self.resolve_color(properties.color)
            self._add(d, properties, f"fill:{colour};stroke:none" + (f";fill-opacity:{opacity:.3f}" if opacity < 1 else ""))

    holder: dict = {}

    class Recorder(dsvg.SVGBackend):
        def make_backend(self, pg, settings_):     # noqa: D401 - ezdxf's hook for a customised writer
            holder["w"] = Writer(pg, settings_)
            return holder["w"]

    ctx = RenderContext(doc)
    ctx.set_layer_properties_override(all_visible)
    rec = Recorder()
    state = random.getstate()
    random.seed(f"dxf_svg:{key}")
    try:
        cfg = Configuration(background_policy=BackgroundPolicy.WHITE, text_policy=TextPolicy.IGNORE,
                            **({"hatch_policy": HatchPolicy.SHOW_OUTLINE} if hatch_outlines else {}))
        Frontend(ctx, rec, config=cfg).draw_layout(layout, finalize=True, filter_func=filter_func)
    finally:
        random.setstate(state)
    x0, x1, y0, y1 = page["limits"]
    pg = dlayout.Page(page["width_mm"], page["height_mm"], dlayout.Units.mm, margins=dlayout.Margins.all(0))
    lsettings = dlayout.Settings(output_coordinate_space=units, crop_at_margins=True, fit_page=True)
    root = rec.get_xml_root_element(pg, settings=lsettings, render_box=BoundingBox2d([(x0, y0), (x1, y1)]))
    w = holder.get("w")
    if w is None:          # ezdxf returns a bare <svg> for an empty page
        raise RuntimeError("the page has no size: nothing was rendered")
    m = rec.transformation_matrix
    _add_texts(doc, layout, filter_func, w, lambda x, y: (m.transform(Vec3(x, y, 0)).x, m.transform(Vec3(x, y, 0)).y))
    for name in sorted(set(layers) - set(w.groups)):
        w.groups[name] = ET.SubElement(w.entities, "g", {"data-layer": name})
    for name, g in w.groups.items():
        g.set("data-paths", str(w.count[name]))
        if name in off:
            g.set("data-default", "off")
            g.set("display", "none")
    style = ET.Element("style")
    style.text = "".join(f".{c}{{{rule}}}" for rule, c in w.cls.items())
    root.insert(0, style)
    vb_w = float(root.get("viewBox").split()[2])

    def to_view(x: float, y: float) -> tuple[float, float]:
        p = m.transform(Vec3(x, y, 0))
        return p.x, p.y
    o, ex, ey = to_view(0.0, 0.0), to_view(1.0, 0.0), to_view(0.0, 1.0)
    affine = [ex[0] - o[0], ex[1] - o[1], ey[0] - o[0], ey[1] - o[1], o[0], o[1]]
    return {"root": root, "paths": dict(w.count), "order": list(w.groups), "off": sorted(off), "to_view": to_view,
            "affine": affine, "scale": vb_w / pg.width_in_mm}


_MTEXT_ALIGN = {1: ("start", 0.0), 2: ("middle", 0.0), 3: ("end", 0.0), 4: ("start", 0.5), 5: ("middle", 0.5), 6: ("end", 0.5),
                7: ("start", 1.0), 8: ("middle", 1.0), 9: ("end", 1.0)}      # (text-anchor, share of the block height above the point)
_TEXT_ANCHOR = {0: "start", 1: "middle", 2: "end", 4: "middle"}


def _colour(e, layer: str, doc, parent=None) -> str:
    """#rrggbb of an entity: its true colour, its ACI colour, BYLAYER (the layer's), BYBLOCK (the parent's); ACI 7 and white
    draw black (white paper, as the stock writer does)."""
    from ezdxf import colors
    if e.dxf.hasattr("true_color"):
        r, g, b = colors.int2rgb(e.dxf.true_color)
    else:
        aci = e.dxf.get("color", 256)
        if aci == 0 and parent is not None:
            return _colour(parent, layer, doc)
        if aci in (0, 256):
            lay = doc.layers.get(layer) if layer in doc.layers else None
            aci = abs(lay.dxf.color) if lay is not None else 7
        r, g, b = colors.aci2rgb(aci if 0 < aci < 256 else 7)
    if min(r, g, b) >= 240:
        r = g = b = 0
    return f"#{r:02x}{g:02x}{b:02x}"


def _texts(doc, layout, filter_func):
    """(entity, layer, parent) of every TEXT / MTEXT of the layout, also inside INSERTs and DIMENSIONs."""
    def walk(e, layer, parent, depth):
        t = e.dxftype()
        if t in ("TEXT", "MTEXT"):
            yield e, layer, parent
        elif t in ("INSERT", "DIMENSION", "ARC_DIMENSION", "LARGE_RADIAL_DIMENSION") and depth < 16:
            try:
                parts = list(e.virtual_entities())
            except Exception:          # noqa: BLE001 - a block that cannot be exploded draws no text, it does not stop the drawing
                return
            for v in parts:
                lay = v.dxf.get("layer", "0")
                yield from walk(v, layer if lay == "0" else lay, e, depth + 1)
    for e in layout:
        if filter_func is not None and not filter_func(e):
            continue
        yield from walk(e, e.dxf.get("layer", "0"), None, 0)


def _add_texts(doc, layout, filter_func, w, to_view) -> None:
    import math
    o = to_view(0.0, 0.0)
    ex, ey = to_view(1.0, 0.0), to_view(0.0, 1.0)
    scale = math.hypot(ex[0] - o[0], ex[1] - o[1])
    # a counter-clockwise angle in the model is counter-clockwise on screen too; with the y axis flipped (SVG y down) that is a
    # NEGATIVE SVG rotation
    flip = -1.0 if (ex[0] - o[0]) * (ey[1] - o[1]) - (ex[1] - o[1]) * (ey[0] - o[0]) < 0 else 1.0
    fmt = lambda v: f"{v:.2f}".rstrip("0").rstrip(".")
    for e, layer, parent in _texts(doc, layout, filter_func):
        if e.dxftype() == "MTEXT":
            lines = [x for x in e.plain_text().split("\n")]
            h = float(e.dxf.get("char_height", 0) or 0)
            p = e.dxf.insert
            rot = float(e.dxf.get("rotation", 0) or 0)
            anchor, above = _MTEXT_ALIGN.get(e.dxf.get("attachment_point", 1), ("start", 0.0))
            pitch = 1.667 * float(e.dxf.get("line_spacing_factor", 1) or 1)
        else:
            lines = [e.plain_text()]
            h = float(e.dxf.get("height", 0) or 0)
            ha, va = e.dxf.get("halign", 0), e.dxf.get("valign", 0)
            p = e.dxf.align_point if (ha or va) and e.dxf.hasattr("align_point") else e.dxf.insert
            rot = float(e.dxf.get("rotation", 0) or 0)
            anchor = _TEXT_ANCHOR.get(ha, "start")
            above = {0: 1.0, 1: 1.0, 2: 0.5, 3: 0.0}.get(va, 1.0) if ha != 4 else 0.5
            pitch = 1.667
        lines = [x for x in lines if x.strip()] or []
        if not lines or h <= 0:
            continue
        fs = h * scale
        X, Y = to_view(float(p.x), float(p.y))
        n = len(lines)
        # the block's top relative to the point (cap height ~ font size): first baseline = top + fs
        block = fs + (n - 1) * fs * pitch
        top = -above * block
        g = w.groups.get(layer)
        if g is None:
            g = w.groups[layer] = ET.SubElement(w.entities, "g", {"data-layer": layer})
        attrs = {"class": w._style(f"fill:{_colour(e, layer, doc, parent)};stroke:none;--vpt-text:1"), "font-size": fmt(fs), "text-anchor": anchor,
                 "font-family": "sans-serif", "transform": f"translate({fmt(X)} {fmt(Y)})" + (f" rotate({fmt(flip * rot)})" if rot else "")}
        t = ET.SubElement(g, "text", attrs)
        for i, line in enumerate(lines):
            sp = ET.SubElement(t, "tspan", {"x": "0", "y": fmt(top + fs + i * fs * pitch)})
            sp.text = line
        w.count[layer] += 1


def apply_affine(affine: list[float], x: float, y: float) -> tuple[float, float]:
    """A model point in viewBox coordinates with the affine returned by render()."""
    a, b, c, d, e, f = affine
    return a * x + c * y + e, b * x + d * y + f


def finish(root: ET.Element, *, key: str) -> str:
    """Serialise: data-storey on the root, a paper rectangle first (class "paper"), no XML declaration (the SVG is inlined
    into the plan file and the editor page)."""
    root.set("data-storey", key)
    root.set("class", "dwg-svg")
    vb = root.get("viewBox").split()
    paper = ET.Element("rect", {"class": "paper", "x": "0", "y": "0", "width": vb[2], "height": vb[3], "fill": "#ffffff"})
    root.insert(1, paper)
    return ET.tostring(root, encoding="unicode")


def inspect(text: str) -> dict:
    """What an SVG drawing holds, read from its text (independent of render()): storey, viewBox, layer groups with their
    path counts (and duplicates), raster content, size."""
    root = ET.fromstring(text)
    tag = lambda e: e.tag.rsplit("}", 1)[-1]
    if tag(root) != "svg":
        raise ValueError(f"root element is <{tag(root)}>, not <svg>")
    groups: dict[str, int] = {}
    dup: list[str] = []
    images = 0
    for e in root.iter():
        t = tag(e)
        if t in ("image", "foreignObject", "script"):
            images += 1
        if t == "g" and e.get("data-layer") is not None:
            name = e.get("data-layer")
            if name in groups:
                dup.append(name)
            groups[name] = groups.get(name, 0) + sum(1 for c in e.iter() if tag(c) in ("path", "text"))
    images += len(re.findall(r"data:image/", text))
    return {"storey": root.get("data-storey"), "view_box": [float(v) for v in (root.get("viewBox") or "0 0 0 0").split()],
            "groups": groups, "duplicates": dup, "paths": sum(groups.values()), "images": images,
            "off": sorted(e.get("data-layer") for e in root.iter() if e.get("data-default") == "off"),
            "bytes": len(text.encode("utf-8"))}
