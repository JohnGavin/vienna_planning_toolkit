"""The HTML of the electrical editor, one code base for two pages (tools/build_editor.py):

  pages     the GitHub Pages page (site/index.html): a whole HTML document; Save layout (download), Save to file (File
            System Access, Chrome/Edge), Save parameters, Print view (A3) besides everything below.
  artifact  the shareable demo (artifact/electrical_planner.html): page CONTENT only (no doctype/html/head/body; it starts
            with <title>); no download, file save, print or dialog (those are inert there): Copy layout / Copy parameters
            instead, the draft in localStorage, and a note pointing to the Pages version.

Both: Open plan / Open layout / Load parameters through <input type="file"> (read in the browser), paste of any of the three
file kinds, in-page confirmation instead of the browser's dialogs, the synthetic flat's plan embedded as the default with the simple
example shown, theme-aware page colours (the drawing stage stays black), a layout that works at phone width.

The storey stages are built by the page script from the plan file (so Open plan can replace them); this module builds the
static parts: the bar, palette and panels as a <template>, the Parameters panel, the Documentation tab, and the JSON blocks
the script reads (symbol library, schemas, rules with popup texts, parameters, page settings and messages, the plan).
Every symbol shown comes from the library (validated: the build fails on a broken library); every text from
presets/editor_docs.json.
"""
from __future__ import annotations

import json
import pathlib
import re

from vpt import ROOT, docs as dx, el_examples, el_layout, el_params, el_rules, el_symbols, plan as plan_mod

EDITOR = ROOT / "editor"
VARIANTS = {
    "pages": {"id": "pages", "download": True, "fs": True, "print": True, "clipboard": True},
    "artifact": {"id": "artifact", "download": False, "fs": False, "print": False, "clipboard": True},
}


def anchor(key: str) -> str:
    return "doc-el-" + dx.slug(key)


def sym_anchor(sid: str, code: str) -> str:
    return "doc-el-sym-" + dx.slug(sid) + "-" + dx.slug(code)


def set_anchor(sid: str) -> str:
    return "doc-el-set-" + dx.slug(sid)


def howto_anchor(key: str | None = None) -> str:
    return "doc-el-howto" + (f"-{dx.slug(key)}" if key else "")


def _c(d: dx.Docs, key: str) -> dict:
    return d.t["electrical"][key]


def howto_part(d: dx.Docs, key: str) -> str | None:
    return next((x["key"] for x in d.t["howto"]["parts"] if key in x["details"]), None)


def etip(d: dx.Docs, key: str, extra: str = "", more: str | None = None) -> str:
    """An editor popup: its label, the bullets of editor_docs.json tips["electrical.<key>"], a More link: to the How-to step
    that uses the control (which links on to the control's own section), else to the control's section."""
    part = howto_part(d, key)
    return dx.popup(_c(d, key)["label"], d.bl("electrical." + key), d.more(more or (howto_anchor(part) if part else anchor(key))), extra)


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def sym_tip(s: dict, x: dict, d: dx.Docs) -> str:
    conn = ", ".join(x["connectable_to"]) or "nothing"
    return dx.popup(f"{x['code']} {x['name_de']} / {x['name_en']}",
                    [f"**Layer**: {x['layer']}", f"**May be connected to**: {conn}",
                     "**UNVERIFIED**: drawn by us, not checked against the standard."], d.more(sym_anchor(s["id"], x["code"])))


def set_tip(s: dict, d: dx.Docs) -> str:
    return dx.popup(f"{s['name_en']}, version {s['version']}",
                    ["**UNVERIFIED**: not checked against the standard or Elektroplaner.",
                     f"**Claims** {s['standard'].split(' (')[0]}; installation {s['installation_standard'].split(' (')[0]}.",
                     f"**Edition**: {dx.short(s['edition'], 2)}"] + d.bl("electrical.unverified")[1:2],
                    d.more(set_anchor(s["id"])))


def palette(lib: dict, d: dx.Docs) -> str:
    out = []
    for s in lib["sets"]:
        cats = []
        for c in s["categories"]:
            # the popup sits on the item's own UNVERIFIED badge, not on the button: a popup opening on the button would cover the
            # next items and the drawing while a symbol is dragged
            items = "".join(
                f'<li><button type="button" class="el-sym-btn" data-code="{dx.esc(x["code"])}" data-set="{dx.esc(s["id"])}" aria-pressed="false">'
                f'<span class="el-chip">{el_symbols.preview_svg(s, x, 30)}</span>'
                f'<span class="el-names"><span class="el-de">{dx.esc(x["name_de"])}</span> <span class="el-en">{dx.esc(x["name_en"])}</span></span>'
                f'<span class="el-code">{dx.esc(x["code"])}</span></button>'
                f'<span class="tip el-badge el-badge-s" data-code="{dx.esc(x["code"])}" data-tip="{dx.esc(sym_tip(s, x, d))}">'
                f'{"verified" if x["verified"] else "UNVERIFIED"}</span></li>'
                for x in s["symbols"] if x["category"] == c["key"])
            if items:
                cats.append(f'<div class="el-cat"><p class="el-cat-h">{dx.esc(c["name_de"])} <span class="el-en">/ {dx.esc(c["name_en"])}</span></p>'
                            f'<ul class="el-syms">{items}</ul></div>')
        hidden = "" if s["id"] == lib["default_set"] else " hidden"
        out.append(f'<div class="el-pal-set" data-set="{dx.esc(s["id"])}"{hidden}>'
                   f'<p class="el-unv-line"><span class="tip el-badge" data-tip="{dx.esc(set_tip(s, d))}">UNVERIFIED</span> '
                   f'{dx.esc(s["name_de"])}</p>' + "".join(cats) + "</div>")
    return (f'<details class="el-palette" open><summary class="tip" data-tip="{dx.esc(etip(d, "palette"))}">Symbols</summary>'
            + "".join(out) + "</details>")


def page_template(lib: dict, d: dx.Docs, rules: dict, v: dict) -> str:
    """One storey's stage, without the drawing (the script clones it per storey and fills in the SVG and the drawing layers)."""
    sdef = el_symbols.default_set(lib)
    link_layer = rules["links"]["layer"]
    btn = lambda act, label, key, extra="": (f'<button type="button" class="tip" data-el="{act}" data-tip="{dx.esc(etip(d, key))}"{extra}>'
                                             f'{label}</button>')
    sets = "".join(f'<option value="{dx.esc(x["id"])}"{" selected" if x["id"] == lib["default_set"] else ""}>{dx.esc(x["name_de"])} '
                   f'(v{dx.esc(x["version"])}{", ungeprüft" if not x["verified"] else ""})</option>' for x in lib["sets"])
    files = btn("open", "Open layout…", "open")
    if v["download"]:
        files += btn("save", "Save layout", "save")
    if v["fs"]:
        files += btn("save-in-place", "Save to file…", "save_in_place", " hidden")
    files += btn("copy", "Copy layout", "copy_layout")
    bar = (f'<div class="el-bar" role="toolbar" aria-label="Electrical plan">'
           f'<label class="tip el-set-wrap" data-tip="{dx.esc(etip(d, "set"))}">Symbol set <select class="el-set">{sets}</select></label>'
           + files + '<span class="el-sep"></span>'
           + btn("undo", "Undo", "undo", " disabled") + btn("redo", "Redo", "undo", " disabled")
           + btn("rotate", "Rotate 90°", "rotate", " disabled") + btn("delete", "Delete", "delete", " disabled")
           + btn("discard", "Discard draft", "autosave", " hidden")
           + '<span class="el-sep"></span>'
           + btn("connect", "Connect", "connect", ' aria-pressed="false"')
           + f'<label class="tip el-rules-wrap" data-tip="{dx.esc(etip(d, "rules_select"))}">Rules <select class="el-rules">'
           + "".join(f'<option value="{dx.esc(x["id"])}"{" selected" if x["id"] == rules["default_rule_set"] else ""}>{dx.esc(x["name"])}</option>'
                     for x in rules["rule_sets"]) + '</select></label>'
           + f'<label class="tip el-snap-wrap" data-tip="{dx.esc(etip(d, "snap"))}"><input type="checkbox" class="el-snap" checked> Snap</label>'
           + f'<label class="tip el-sugall-wrap" data-tip="{dx.esc(etip(d, "sug_all", more=anchor("suggestions")))}"><input type="checkbox" class="el-sugall"> Suggestions</label>'
           + f'<span class="el-example-ctl" hidden><span class="el-sep"></span><label class="tip el-example-wrap" data-tip="{dx.esc(etip(d, "example"))}">Example '
             '<select class="el-example"><option value="none">none</option><option value="simple">simple</option>'
             '<option value="complex">complex</option></select></label>'
           + btn("example-clear", "Clear example", "example_clear") + '</span></div>')
    ctl = lambda act, label, k, aria="": (f'<button type="button" class="tip" data-act="{act}"{f" aria-label={chr(34)}{dx.esc(aria)}{chr(34)}" if aria else ""} '
                                          f'data-tip="{dx.esc(d.control_tip(k))}">{label}</button>')
    tools = ('<div class="dwg-tools">' + ctl("in", "+", "in", "Zoom in") + ctl("out", "&minus;", "out", "Zoom out") + ctl("reset", "Reset view", "reset")
             + ctl("all-on", "All layers on", "all-on") + ctl("all-off", "All layers off", "all-off")
             + (ctl("print", "Print view", "print") if v["print"] else "")
             + dx.tip("pinch or Ctrl/⌘ + wheel: zoom · drag the drawing: pan · drag a symbol: move", d.control_tip("pan"), cls="tip dwg-hint")
             + "</div>")
    el_lay = ("".join(f'<label><input type="checkbox" data-toggle-layer="{dx.esc(L)}" data-base="Elektro" checked> {dx.esc(L)} '
                      f'<span class="el-n" data-el-count="{dx.esc(L)}">0</span></label>' for L in el_symbols.layers(sdef))
              + f'<label><input type="checkbox" data-toggle-layer="{dx.esc(link_layer)}" data-base="Elektro" checked> '
                f'{dx.tip(link_layer, etip(d, "links_layer"))} <span class="el-n" data-el-count="{dx.esc(link_layer)}">0</span></label>')
    panel = (f'<details class="dwg-panel" open><summary class="tip" data-tip="{dx.esc(d.control_tip("collapse"))}">Layers</summary>'
             f'<div class="dwg-panel-body"><fieldset class="el-layers"><legend>{dx.tip("Electrical layers", etip(d, "el_layers"))}</legend>{el_lay}</fieldset>'
             f'<fieldset class="dwg-layers"><legend>{dx.tip("Drawing layers", etip(d, "layers"))}</legend>'
             f'<div class="dwg-status"></div><p class="dwg-count"></p>'
             f'<input type="search" class="dwg-filter tip" aria-label="Filter layers" placeholder="filter layers" data-tip="{dx.esc(d.control_tip("filter"))}">'
             f'<div class="dwg-bases"></div></fieldset></div></details>')
    view = (f'<div class="el-view" role="group" aria-label="Electrical plan" tabindex="0">' + tools
            + f'<div class="dwg-body"><div class="dwg-paper"></div><div class="el-side">{palette(lib, d)}{panel}</div></div></div>')
    hint_li = "".join(f'<li class="el-hint" data-hint="{h}">{dx.tip(_c(d, "hint_" + h.lower())["label"], etip(d, "hint_" + h.lower()))}: '
                      f'<span class="el-hint-st"></span> <span class="el-hint-items"></span></li>' for h in ("H1", "H2", "H3"))
    below = (f'<div class="el-below">'
             f'<details class="el-groups" open><summary class="tip" data-tip="{dx.esc(etip(d, "groups"))}">Switching groups</summary>'
             f'<div class="el-groups-body"></div></details>'
             f'<details class="el-hints" open><summary class="tip" data-tip="{dx.esc(etip(d, "hints"))}">Layout hints</summary>'
             f'<ul class="el-hint-list">{hint_li}</ul></details></div>')
    return (f'<template id="el-page-tpl"><div class="el-page" role="tabpanel">'
            f'<p class="el-status" role="status" aria-live="polite"></p>' + bar
            + '<p class="el-example-banner" hidden><b class="el-example-text"></b> <span class="el-example-which"></span></p>'
            + '<p class="el-info" aria-live="polite"></p>' + view + below
            + '<input type="file" class="el-file" accept=".json,application/json" hidden aria-label="Open a layout file"></div></template>')


def params_panel(d: dx.Docs, v: dict) -> str:
    b = lambda act, label, key: f'<button type="button" class="tip" data-pact="{act}" data-tip="{dx.esc(etip(d, key))}">{label}</button>'
    bar = b("copy", "Copy parameters", "params_copy")
    if v["download"]:
        bar += b("save", "Save parameters", "params_save")
    if v["fs"]:
        bar += b("save-in-place", "Save to file…", "params_save")
    bar += b("load", "Load parameters…", "params_load") + b("reset", "Reset to the page's file", "params_reset")
    return (f'<details class="el-params"><summary class="tip" data-tip="{dx.esc(etip(d, "params"))}">Parameters</summary>'
            '<p class="el-params-status el-status" role="status" aria-live="polite"></p>'
            f'<div class="el-params-bar">{bar}</div>'
            '<div class="el-params-body"></div><input type="file" class="el-params-file" accept=".json,application/json" hidden aria-label="Load a parameter file"></details>')


# ---- the Documentation tab ----------------------------------------------------------------------------------------------------

def _section(a: str, heading: str, body: str) -> str:
    return f'<section class="docsec" id="{dx.esc(a)}"><h4>{dx.esc(heading)}</h4>{body}</section>'


def _shown(x) -> str:
    if x is None:
        return "no value yet"
    if isinstance(x, list):
        return " – ".join(f"{v:g}" for v in x) if all(isinstance(v, (int, float)) for v in x) else ", ".join(map(str, x))
    return f"{x:g}" if isinstance(x, (int, float)) else str(x)


def _schema_rows(schema: dict) -> list[list]:
    rows = []

    def walk(s: dict, prefix: str, required: set, depth: int = 0) -> None:
        for k, v in (s.get("properties") or {}).items():
            if "$ref" in v:
                v = schema["$defs"][v["$ref"].rsplit("/", 1)[-1]]
            t = v.get("type") or ("one of " + ", ".join(json.dumps(e) for e in v["enum"]) if "enum" in v else f"= {json.dumps(v.get('const'))}")
            t = "/".join(t) if isinstance(t, list) else t
            rows.append([prefix + k, t, "yes" if k in required else "no", v.get("description", "")])
            if depth > 3:
                continue
            if v.get("type") == "object":
                walk(v, prefix + k + ".", set(v.get("required", [])), depth + 1)
            if isinstance(v.get("items"), dict):
                it = v["items"]
                it = schema["$defs"][it["$ref"].rsplit("/", 1)[-1]] if "$ref" in it else it
                if it.get("type") == "object":
                    walk(it, prefix + k + "[].", set(it.get("required", [])), depth + 1)
    walk(schema, "", set(schema.get("required", [])))
    return rows


def rules_table(rules: dict) -> str:
    sets = rules["rule_sets"]
    rows = []
    for key, r in rules["rules"].items():
        row = [dx.esc(key), dx.esc(r["label"]), dx.esc(r["unit"]), dx.esc(r["text"])]
        for s in sets:
            v = rules["values"][s["id"]][key]
            cls = "unk" if v.get("value") is None or v.get("mark") else "pass"
            row.append(f'<span class="{cls}">{dx.esc(_shown(v.get("value")))}</span>'
                       + (f'<br>{dx.esc(v["mark"])}' if v.get("mark") else "") + (f'<br>{dx.esc(v["source"])}' if v.get("source") else ""))
        rows.append(row)
    st = rules["settings"]
    rows.append(["snap_radius_m", "Snap radius (both rule sets)", "m", dx.esc(st["snap_radius_m_note"])] + [dx.esc(f"{st['snap_radius_m']:g}")] * len(sets))
    return dx.table(["Key", "Rule", "Unit", "What it does"] + [s["name"] for s in sets], rows, raw_cols=set(range(4 + len(sets))),
                    caption="From presets/el_parameters.json (rules, sections.snap: the one home of these values).")


def params_meta(params: dict) -> dict:
    return {"sha256": el_params.sha256(), "file_name": el_params.PRESET.name, "live_sections": list(el_params.LIVE_SECTIONS),
            "live_rules": list(el_params.LIVE_RULES), "colour_keys": list(el_params.COLOUR_KEYS), "anchor": anchor("params")}


def params_table(params: dict) -> str:
    rs = el_params.rows(params)
    return dx.table(["Group", "Key", "Parameter", "Value", "Unit", "Mark", "Source", "Applies"],
                    [[r["section"], r["key"], r["label"], _shown(r["value"]), r["unit"], r["mark"], r["source"], "at once" if r["live"] else "after export"] for r in rs],
                    caption=f"From presets/el_parameters.json (SHA-256 {el_params.sha256()[:12]}…), the one home of these values; schema schema/el_parameters.schema.json.")


def colours_table(params: dict) -> str:
    rows = []
    for name, key, c, bg, ratio in el_params.contrast_table(params):
        lab = params["sections"][name]["values"][key]["label"]
        rows.append([dx.esc(params["sections"][name]["label"]), dx.esc(lab),
                     f'<svg class="el-swatch" width="14" height="14" aria-hidden="true"><rect width="14" height="14" fill="{dx.esc(c)}" stroke="#808080"></rect></svg> {dx.esc(c)}',
                     dx.esc(bg), f'<span class="{"pass" if ratio >= params["contrast_min"] else "fail"}">{ratio:.1f} : 1</span>'])
    return (dx.table(["Palette", "Colour of", "Colour", "Background", "Contrast"], rows, raw_cols={0, 1, 2, 3, 4},
                     caption="From presets/el_parameters.json (the one home of these colours); contrast checked by the tests.")
            + f'<p class="unk">{dx.esc(params["standard_note"])}</p><p>{dx.esc(params["contrast_min_note"])}</p>')


def howto_sections(d: dx.Docs, v: dict) -> list[tuple[str, str, str]]:
    h, w = d.t["howto"], d.t["whatsnew"]
    out = [(howto_anchor(), h["label"], f"<p>{dx.md_inline(h['intro'])}</p><ol>" + "".join(
        f'<li><a class="doclink" href="#{howto_anchor(x["key"])}">{dx.esc(x["label"])}</a></li>' for x in h["parts"]) + "</ol>")]
    for x in h["parts"]:
        steps = x.get("steps") or x["steps_" + v["id"]]
        det = " · ".join(f'<a class="doclink" href="#{anchor(k)}">{dx.esc(_c(d, k)["label"])}</a>' for k in x["details"])
        out.append((howto_anchor(x["key"]), x["label"], "<ol>" + "".join(f"<li>{dx.md_inline(s)}</li>" for s in steps) + "</ol>"
                    + f"<p>Details: {det}</p>"))
    out.append(("doc-el-whatsnew", w["label"], "".join(f"<p><b>{dx.esc(e['date'])}: {dx.esc(e['title'])}</b></p><ul>"
                                                       + "".join(f"<li>{dx.md_inline(i)}</li>" for i in e["items"]) + "</ul>" for e in w["entries"])))
    return out


def doc_tab(lib: dict, rules: dict, params: dict, cfg: dict, d: dx.Docs, v: dict) -> str:
    t = d.t
    p = lambda key: f"<p>{dx.esc(_c(d, key)['text'])}</p>"
    sec = lambda key, body="": (anchor(key), _c(d, key)["label"], p(key) + body)
    layout_schema, plan_schema = el_layout.load_schema(), plan_mod.load_schema()
    el = [sec("page")] + howto_sections(d, v) + [sec("variants"), sec("privacy"), sec("plan"), sec("paste"), sec("storeys"), sec("layers"),
                                                   sec("el_layers"), sec("unverified"), sec("set")]
    for s in lib["sets"]:
        rows = [["Id", s["id"]], ["Version", s["version"]], ["Name", f"{s['name_de']} / {s['name_en']}"], ["Standard claimed", s["standard"]],
                ["Installation standard", s["installation_standard"]], ["Edition", s["edition"]], ["Status", s["status"]],
                ["Verified", "yes" if s["verified"] else "no"], ["Verified against", s["verified_against"] or "nothing yet"],
                ["Provenance", s["provenance"]], ["To verify", s["to_verify"]], ["Units", s["units"]], ["Symbols", str(len(s["symbols"]))]]
        el.append((set_anchor(s["id"]), f"Set {s['id']}", dx.table(["Field", "Value"], rows, caption="From presets/el_symbols_at.json.")))
    el += [sec("palette"), sec("place"), sec("select"), sec("rotate"), sec("delete"), sec("undo"),
           sec("rooms", f"<p>room_label_max_m = {cfg['room_label_max_m']:g} m: {dx.esc(cfg['room_label_max_m_note'])}</p>"
                        f"<p>symbol_scale = {cfg['symbol_scale']:g}: {dx.esc(cfg['symbol_scale_note'])}</p>"),
           sec("connect"), sec("links_layer", f"<p>{dx.esc(rules['links']['note'])}</p>"),
           sec("groups", f"<p>{dx.esc(rules['switching']['note'])}</p>"), sec("apply"),
           sec("rules_select", "".join(f"<p><b>{dx.esc(s['name'])}</b>: {dx.esc(s['status'])}. {dx.esc(s['note'])}</p>" for s in rules["rule_sets"])),
           sec("snap"), sec("sug_all"),
           sec("suggestions", "<ul>" + "".join(f"<li><b>{dx.esc(sg['name'])}</b>: symbols {dx.esc(', '.join(sg['codes']))}; values "
                                               f"{dx.esc(', '.join(sg['values']))}.</li>" for sg in rules["suggest"].values()) + "</ul>"),
           sec("rules", rules_table(rules)), sec("colours", colours_table(params)), sec("params", params_table(params)),
           sec("example", f"<p>{dx.esc(el_examples.STOREY_RULE)}.</p>"), sec("example_clear"),
           sec("params_copy"), sec("params_save"), sec("params_load"), sec("params_reset"),
           sec("hints"), sec("hint_h1"), sec("hint_h2"), sec("hint_h3"),
           sec("save"), sec("save_in_place"), sec("copy_layout"), sec("open"), sec("autosave"),
           sec("file", dx.table(["Field", "Type", "Required", "What it is"], _schema_rows(layout_schema), caption="From schema/el_layout.schema.json.")),
           sec("plan_file", dx.table(["Field", "Type", "Required", "What it is"], _schema_rows(plan_schema), caption="From schema/plan.schema.json.")),
           sec("print")]
    for s in lib["sets"]:
        rows = [[el_symbols.preview_svg(s, x, 28), dx.esc(x["code"]), dx.esc(x["name_de"]), dx.esc(x["name_en"]),
                 dx.esc(el_symbols.category(s, x["category"])["name_de"]), dx.esc(x["layer"]), dx.esc(", ".join(x["connectable_to"]) or "none"),
                 "yes" if x["verified"] else '<span class="unk">no</span>'] for x in s["symbols"]]
        el.append((anchor("symbols") + "-" + dx.slug(s["id"]), f"{_c(d, 'symbols')['label']}: {s['id']}",
                   p("symbols") + dx.table(["Symbol", "Code", "Name (DE)", "Name (EN)", "Category", "Layer", "Connects to", "Verified"], rows,
                                           raw_cols={0, 1, 2, 3, 4, 5, 6, 7})))
        for x in s["symbols"]:
            el.append((sym_anchor(s["id"], x["code"]), f"{x['code']} {x['name_de']} / {x['name_en']}",
                       f'<p><span class="el-chip">{el_symbols.preview_svg(s, x, 44)}</span> Category {dx.esc(el_symbols.category(s, x["category"])["name_de"])}, '
                       f'layer {dx.esc(x["layer"])}, connects to {dx.esc(", ".join(x["connectable_to"]) or "none")}.</p><p>{dx.esc(x.get("note") or "")}</p>'
                       f'<p class="{"pass" if x["verified"] else "unk"}">Verified: {"yes" if x["verified"] else "no"} '
                       f'(verified_against: {dx.esc(x["verified_against"] or "none")}). {dx.esc(s["status"])}.</p>'))
    pr = t["print"]
    pcfg = d.print_cfg()
    print_sec = _section("doc-print", "How to print to PDF",
                         ("" if v["print"] else f'<p class="unk">{dx.esc(_c(d, "print")["text"].split(". Only")[0])}. Not available in this demo: use the GitHub Pages version.</p>')
                         + "<ol>" + "".join(f"<li>{dx.esc(s)}</li>" for s in pr["steps"]) + "</ol>"
                         + f"<p>The print view fills one {dx.esc(pr['paper'])} {dx.esc(pr['orientation'])} page ({pcfg['paper_mm'][0]} x {pcfg['paper_mm'][1]} mm, "
                         f"margins {pr['margin_mm']} mm): a title row, the drawing ({pcfg['draw_mm'][0]} x {pcfg['draw_mm'][1]} mm), and a legend.</p>"
                         f"<p>{dx.esc(pr['scale_text'])}</p><p>{dx.esc(pr['browsers'])}</p>")
    ctl = "".join(_section(d.a_control(k), c["label"], f"<p>{dx.esc(c['text'])}</p>") for k, c in t["controls"].items())
    index = [f'<a class="doclink" href="#{howto_anchor()}">How to use</a>', '<a class="doclink" href="#doc-el-whatsnew">What\'s new</a>',
             f'<a class="doclink" href="#{anchor("privacy")}">Privacy</a>', '<a class="doclink" href="#doc-electrical">Editor</a>',
             '<a class="doclink" href="#doc-controls">Controls</a>', '<a class="doclink" href="#doc-print">Print</a>']
    return ('<div class="docs">' + f'<p>{dx.esc(t["intro"])}</p><p class="docindex">' + " · ".join(index) + "</p>"
            + f'<section class="docsec" id="doc-electrical"><h3>The editor</h3>' + "".join(_section(a, h, b) for a, h, b in el) + "</section>"
            + f'<section class="docsec" id="doc-controls"><h3>Controls</h3>{ctl}</section>' + print_sec + "</div>")


# ---- the page --------------------------------------------------------------------------------------------------------------------

_REGION = re.compile(r"[ \t]*// @pages-only-start[^\n]*\n.*?// @pages-only-end[^\n]*\n", re.S)


def _asset(name: str, variant: str = "pages") -> str:
    """An editor asset; for the artifact the pages-only regions (downloads, file pickers, print) are left out."""
    text = (EDITOR / name).read_text(encoding="utf-8")
    if text.count("@pages-only-start") != text.count("@pages-only-end"):
        raise ValueError(f"editor/{name}: unbalanced @pages-only markers")
    return _REGION.sub("", text) if variant == "artifact" else text


def build(plan: dict, variant: str) -> str:
    """The page for one variant: a whole document (pages) or page content starting with <title> (artifact)."""
    v = VARIANTS[variant]
    d = dx.Docs.load()
    lib = el_symbols.load()
    problems = el_symbols.validate(lib)
    if problems:
        raise ValueError("the symbol library presets/el_symbols_at.json is broken: " + "; ".join(problems[:5]))
    params = el_params.load()
    rules = el_rules.load(params=params)
    for name, probs in (("placement rules", el_rules.validate(rules, lib)), ("parameter file", el_params.validate(params))):
        if probs:
            raise ValueError(f"the {name} is broken: " + "; ".join(probs[:5]))
    layout_schema, plan_schema, params_schema = el_layout.load_schema(), plan_mod.load_schema(), el_params.load_schema()
    for nm, sc in (("layout", layout_schema), ("plan", plan_schema), ("parameter", params_schema)):
        if el_layout.unsupported_keywords(sc):
            raise ValueError(f"the {nm} schema uses unsupported keywords: {el_layout.unsupported_keywords(sc)}")
    res = plan_mod.check(plan, plan_schema)
    if res[0] != "match":
        raise ValueError(f"the embedded plan does not check: {res[1]}")
    cfg = el_layout.load_page(params=params)
    sdef = el_symbols.default_set(lib)
    t = d.t
    page_cfg = dict(cfg, messages=t["electrical"]["messages"], banners=t["banners"], pages_url=t["pages_url"], variant=v,
                    anchors={k: anchor(k) for k in ("suggestions", "groups", "apply", "links_layer", "rules", "hint_h1", "hint_h2", "hint_h3",
                                                    "connect", "layers", "storeys", "plan")},
                    labels={k: _c(d, k)["label"] for k in ("hint_h1", "hint_h2", "hint_h3")},
                    tips={"layer": d.bl("electrical.layer"), "storeys": d.bl("electrical.storeys")},
                    print=d.print_cfg())
    note_key = "artifact_note" if variant == "artifact" else "pages_note"
    note = dx.esc(t["banners"][note_key]).replace("{url}", f'<a href="{dx.esc(t["pages_url"])}">{dx.esc(t["pages_url"])}</a>')
    head = (f'<header class="vpt-head"><h1>{dx.esc(t["title"])}</h1>'
            f'<p class="vpt-banner vpt-synth" data-banner="synthetic"><b>{dx.esc(t["banners"]["synthetic"])}</b> '
            f'<span>{dx.esc(t["banners"]["synthetic_more"])}</span></p>'
            f'<p class="vpt-banner vpt-own" data-banner="own" hidden></p>'
            f'<p class="el-unv-banner"><span class="tip el-badge" data-tip="{dx.esc(set_tip(sdef, d))}">UNVERIFIED</span> '
            f'{dx.esc(sdef["name_de"])} (version {dx.esc(sdef["version"])}): {dx.esc(sdef["status"])}.</p>'
            f'<p class="vpt-note">{note}</p></header>')
    tabs = ('<div class="vpt-tabs" role="tablist" aria-label="Page">'
            '<button type="button" role="tab" id="vpt-tab-editor" aria-controls="vpt-pane-editor" aria-selected="true">Editor</button>'
            '<button type="button" role="tab" id="vpt-tab-docs" aria-controls="vpt-pane-docs" aria-selected="false" tabindex="-1">Documentation</button></div>')
    intro = (f'<div class="el-intro"><p>{dx.tip("How this page works", etip(d, "page", more=howto_anchor()))} · '
             f'{dx.tip("How to use, step by step", dx.popup(t["howto"]["label"], d.bl("electrical.howto"), d.more(howto_anchor())))} · '
             f'{dx.tip("What is new", dx.popup(t["whatsnew"]["label"], d.bl("electrical.whatsnew"), d.more("doc-el-whatsnew")))} · '
             f'{dx.tip("Privacy", etip(d, "privacy"))}</p></div>')
    filebar = (f'<div class="vpt-filebar"><button type="button" class="tip" data-vpt="open-plan" data-tip="{dx.esc(etip(d, "plan"))}">Open plan…</button>'
               f' {dx.tip("or paste a file", etip(d, "paste"))}'
               '<input type="file" class="vpt-plan-file" accept=".json,application/json" hidden aria-label="Open a plan file">'
               '<p class="vpt-status el-status" role="status" aria-live="polite"></p></div>')
    editor = (f'<section class="vpt-pane" role="tabpanel" id="vpt-pane-editor" aria-labelledby="vpt-tab-editor">{intro}{filebar}'
              + params_panel(d, v)
              + f'<div class="el-storey-tabs" role="tablist" aria-label="Storeys"></div><div class="el-storeys"></div>'
              + page_template(lib, d, rules, v) + '</section>')
    docs_pane = (f'<section class="vpt-pane" role="tabpanel" id="vpt-pane-docs" aria-labelledby="vpt-tab-docs" hidden>'
                 + doc_tab(lib, rules, params, cfg, d, v) + '</section>')
    overlays = ('<div class="vpt-ask" role="alertdialog" aria-modal="false" aria-labelledby="vpt-ask-msg" hidden><p id="vpt-ask-msg"></p>'
                f'<button type="button" data-ask="yes">{dx.esc(t["electrical"]["messages"]["ask_yes"])}</button> '
                f'<button type="button" data-ask="no">{dx.esc(t["electrical"]["messages"]["ask_no"])}</button></div>'
                '<div class="vpt-copybox" role="dialog" aria-label="Text to copy" hidden><p class="vpt-copymsg"></p>'
                '<textarea readonly rows="8" aria-label="Text to copy"></textarea><button type="button" data-copybox="close">Close</button></div>')
    data = (f'<script type="application/json" id="vpt-plan">{_json(plan)}</script>'
            f'<script type="application/json" id="el-symbols">{_json(lib)}</script>'
            f'<script type="application/json" id="el-schema">{_json(layout_schema)}</script>'
            f'<script type="application/json" id="el-plan-schema">{_json(plan_schema)}</script>'
            f'<script type="application/json" id="el-config">{_json(page_cfg)}</script>'
            f'<script type="application/json" id="el-rules">{_json(dict(rules, tips=el_rules.tips(rules)))}</script>'
            f'<script type="application/json" id="el-params">{_json(params)}</script>'
            f'<script type="application/json" id="el-params-schema">{_json(params_schema)}</script>'
            f'<script type="application/json" id="el-params-meta">{_json(params_meta(params))}</script>')
    css = _asset("editor.css") + "\n" + d.print_css()
    body = (f'<div class="vpt" id="vpt" data-variant="{variant}">{head}{tabs}{editor}{docs_pane}</div>{overlays}{data}'
            f'<script>\n{_asset("core.js", variant)}\n</script>\n<script>\n{_asset("editor.js", variant)}\n</script>\n')
    title = f"<title>{dx.esc(t['title'])}</title>"
    if variant == "artifact":
        return f"{title}\n<style>\n{css}\n</style>\n{body}"
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<meta name=\"description\" content=\"{dx.esc(t['intro'][:150])}\">\n{title}\n<style>\n{css}\n</style>\n</head>\n<body>\n{body}</body>\n</html>\n")


def problems(page: str) -> list[str]:
    """The page's own gate: popups short, no dangling More link."""
    return dx.page_popup_problems(page) + dx.check_doc_links(page)


def load_plan(path: pathlib.Path) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
