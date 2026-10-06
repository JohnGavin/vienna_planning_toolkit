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

from vpt import ROOT, docs as dx, el_checks, el_examples, el_layout, el_params, el_rules, el_symbols, plan as plan_mod

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
                      f'<span class="el-hint-st"></span> <span class="el-hint-items"></span></li>' for h in el_checks.IDS)
    below = (f'<div class="el-below">'
             f'<details class="el-groups" open><summary class="tip" data-tip="{dx.esc(etip(d, "groups"))}">Switching groups</summary>'
             f'<div class="el-groups-body"></div></details>'
             f'<details class="el-hints" open><summary class="tip" data-tip="{dx.esc(etip(d, "hints"))}">{dx.esc(_c(d, "hints")["label"])}'
             f' <span class="el-check-counts"></span></summary>'
             f'<p class="el-hint-items el-windows"></p><ul class="el-hint-list">{hint_li}</ul></details></div>')
    return (f'<template id="el-page-tpl"><div class="el-page" role="tabpanel">'
            f'<p class="el-status" role="status" aria-live="polite"></p>' + bar
            + '<p class="el-example-banner" hidden><b class="el-example-text"></b> <span class="el-example-which"></span></p>'
            + '<p class="el-info" aria-live="polite"></p>' + view + below
            + '<input type="file" class="el-file" accept=".json,application/json" hidden aria-label="Open a layout file"></div></template>')


def params_panel(d: dx.Docs, v: dict) -> str:
    """The Parameters panel: its bar and the callout that explains Live / Needs re-export once (the tables are built by the page
    script from the parameters, so a loaded or reset file shows at once)."""
    pp = d.t["params_panel"]
    b = lambda act, label, key: f'<button type="button" class="tip" data-pact="{act}" data-tip="{dx.esc(etip(d, key))}">{label}</button>'
    bar = b("copy", "Copy parameters", "params_copy")
    if v["download"]:
        bar += b("save", "Save parameters", "params_save")
    if v["fs"]:
        bar += b("save-in-place", "Save to file…", "params_save")
    bar += b("load", "Load parameters…", "params_load") + b("reset", "Reset to the page's file", "params_reset")
    note = dx.callout(dx.bullets(pp["callout_" + ("pages" if v["download"] else "artifact")]))
    return (f'<details class="el-params"><summary class="tip" data-tip="{dx.esc(etip(d, "params"))}">Parameters</summary>'
            '<p class="el-params-status el-status" role="status" aria-live="polite"></p>'
            f'<div class="el-params-bar">{bar}</div>{note}'
            '<div class="el-params-body"></div><input type="file" class="el-params-file" accept=".json,application/json" hidden aria-label="Load a parameter file"></details>')


# ---- the Documentation tab ----------------------------------------------------------------------------------------------------
# Tabs (Start, How to, Controls, Symbols, Rules & parameters, Files, About) with pill sub-tabs; every text a short bullet from
# presets/editor_docs.json, detail folded into accordions; every old #doc-... anchor is an element id somewhere in it (a tab panel,
# an accordion or a table row), and core.js showDoc() opens the tabs and accordions around it.

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


def _status(d: dx.Docs, value, mark) -> str:
    """A status pill for a rule or parameter value: no value yet / to confirm / set."""
    sp = d.t["docs"]["status_pills"]
    if value is None:
        return dx.pill(sp["none"], "watch")
    if mark and "confirm" in str(mark).lower():
        return dx.pill(sp["confirm"], "check", title=str(mark))
    return dx.pill(sp["set"], "good")


def _short(text, n: int = 10) -> str:
    """Up to n words of a long note, the whole note on hover (title): the note's home stays its preset."""
    t = str(text or "")
    return f'<span class="hint" title="{dx.esc(t)}">{dx.esc(dx.short(t, n))}</span>' if len(t.split()) > n else dx.esc(t)


def rules_tables(rules: dict, d: dx.Docs) -> str:
    """One table per rule set (pill sub-tabs), with a status pill per value; long notes and sources shortened, whole on hover."""
    st = rules["settings"]
    tabs = []
    for s in rules["rule_sets"]:
        rows = []
        for key, r in rules["rules"].items():
            v = rules["values"][s["id"]][key]
            rows.append([f"<b>{dx.esc(r['label'])}</b><br><code>{dx.esc(key)}</code>", f'<span class="num">{dx.esc(_shown(v.get("value")))}</span>',
                         dx.esc(r["unit"]), _status(d, v.get("value"), v.get("mark")), _short(r["text"]), _short(v.get("source") or "")])
        rows.append(["<b>Snap radius (both rule sets)</b><br><code>snap_radius_m</code>", f'<span class="num">{st["snap_radius_m"]:g}</span>', "m",
                     _status(d, st["snap_radius_m"], st["snap_radius_m_note"]), _short(st["snap_radius_m_note"]), ""])
        body = (dx.docsec(f"doc-el-rules-{dx.slug(s['id'])}", dx.bullets([f"**{s['name']}**: {s['status']}."]) + f'<p class="tbl-cap">{_short(s["note"], 16)}</p>'
                          + dx.table(["Rule", "Value", "Unit", "Status", "What it does", "Source"], rows, raw_cols={0, 1, 2, 3, 4, 5},
                                     caption="From presets/el_parameters.json (rules), the one home of these values.")))
        tabs.append((f"doc-el-rules-{dx.slug(s['id'])}", s["name"], body))
    return dx.tabset("ts-doc-rulesets", tabs)


def params_meta(params: dict) -> dict:
    return {"sha256": el_params.sha256(), "file_name": el_params.PRESET.name, "live_sections": list(el_params.LIVE_SECTIONS),
            "live_rules": el_params.live_rules(params), "colour_keys": list(el_params.COLOUR_KEYS), "anchor": anchor("params")}


def params_table(params: dict, d: dx.Docs) -> str:
    pp = d.t["params_panel"]
    rs = el_params.rows(params)
    return dx.table(["Group", "Parameter", "Value", "Unit", "Status", "Applies", "Source"],
                    [[dx.esc(r["section"]), f"<b>{dx.esc(r['label'])}</b><br><code>{dx.esc(r['key'])}</code>", f'<span class="num">{dx.esc(_shown(r["value"]))}</span>',
                      dx.esc(r["unit"]), _status(d, r["value"], r["mark"]),
                      dx.pill(pp["live"], "good") if r["live"] else dx.pill(pp["export"], "watch"), _short(r["source"])] for r in rs],
                    raw_cols=set(range(7)),
                    caption=f"From presets/el_parameters.json (SHA-256 {el_params.sha256()[:12]}…), the one home of these values.")


def colours_table(params: dict) -> str:
    rows = []
    for name, key, c, bg, ratio in el_params.contrast_table(params):
        lab = params["sections"][name]["values"][key]["label"]
        rows.append([dx.esc(params["sections"][name]["label"]), dx.esc(lab),
                     f'<svg class="el-swatch" width="14" height="14" aria-hidden="true"><rect width="14" height="14" fill="{dx.esc(c)}" stroke="#808080"></rect></svg> <span class="num">{dx.esc(c)}</span>',
                     f'<span class="num">{dx.esc(bg)}</span>', f'<span class="{"pass" if ratio >= params["contrast_min"] else "fail"} num">{ratio:.1f} : 1</span>'])
    return dx.table(["Palette", "Colour of", "Colour", "Background", "Contrast"], rows, raw_cols={0, 1, 2, 3, 4},
                    caption="From presets/el_parameters.json (the one home of these colours); contrast checked by the tests.")


def _kv(pairs) -> str:
    """A key-value list: [(key, value, hover note)]."""
    return '<ul class="kv">' + "".join(f'<li><span>{dx.esc(k)}</span><span class="v"{f" title={chr(34)}{dx.esc(n)}{chr(34)}" if n else ""}>{dx.esc(v)}</span></li>'
                                       for k, v, n in pairs) + "</ul>"


def _acc(d: dx.Docs, key: str, extra: str = "") -> str:
    c = _c(d, key)
    return dx.details(anchor(key), c["label"], dx.bullets(c["bullets"]) + extra, meta=(d.t["docs"].get("tags") or {}).get(key, ""))


def _howto_tab(d: dx.Docs, part: dict, v: dict, lib: dict, rules: dict, cfg: dict) -> tuple:
    st = part.get("steps") or part["steps_" + v["id"]]
    extras = {
        "rooms": _kv([("room_label_max_m", f"{cfg['room_label_max_m']:g} m", cfg["room_label_max_m_note"]),
                      ("symbol_scale", f"{cfg['symbol_scale']:g} × nominal mm", cfg["symbol_scale_note"])]),
        "example": _kv([("Example storey", dx.short(el_examples.STOREY_RULE, 8), el_examples.STOREY_RULE)]),
        "rules_select": dx.bullets([f"**{s['name']}**: {s['status']}." for s in rules["rule_sets"]]),
        "suggestions": dx.table(["Suggestion", "Symbols", "Values"], [[sg["name"], ", ".join(sg["codes"]), ", ".join(sg["values"])] for sg in rules["suggest"].values()],
                                caption="From the placement rules (presets/el_parameters.json)."),
    }
    stack = "".join(_acc(d, k, extras.get(k, "")) for k in part["details"])
    if part["key"] == "print":
        pr, pc = d.t["print"], d.print_cfg()
        demo = "" if v["print"] else dx.callout(f"<p>{dx.md_inline(pr['demo'])}</p>", "watch")
        stack += dx.details("doc-print", pr["label"], demo + dx.steps(pr["steps"]) + dx.bullets(pr["facts"])
                            + _kv([("Paper", f"{pr['paper']} {pr['orientation']}, {pc['paper_mm'][0]} × {pc['paper_mm'][1]} mm", ""),
                                   ("Margins", f"{pr['margin_mm']} mm", ""), ("Drawing area", f"{pc['draw_mm'][0]} × {pc['draw_mm'][1]} mm", pr["note"])]),
                            meta=(d.t["docs"].get("tags") or {}).get("print", ""), open_=True)
    alias = "".join(f' id="{howto_anchor(a)}"' for a in part.get("aliases", [])[:1])
    body = (dx.docsec(howto_anchor(part["key"]) + "-steps", dx.steps(st)) + f'<div class="dd-stack"{alias}>{stack}</div>')
    return (howto_anchor(part["key"]), part["label"], body)


def doc_tab(lib: dict, rules: dict, params: dict, cfg: dict, d: dx.Docs, v: dict, plan: dict) -> str:
    t, D = d.t, d.t["docs"]
    T = D["tabs"]
    sdef = el_symbols.default_set(lib)
    chips = D["chips"]
    chip_html = '<div class="chips">' + "".join(f'<span class="chip"><span class="dot"></span>{dx.md_inline(x)}</span>' for x in (
        chips["symbols"].format(n=len(sdef["symbols"])), chips["unverified"], chips["rule_sets"].format(n=len(rules["rule_sets"])),
        chips["storeys"].format(n=len(plan["storeys"])), chips["local"])) + "</div>"
    # Start
    start = (dx.section_head(T["start"]["label"], T["start"]["note"]) + dx.callout(f'<p>{dx.md_inline(D["short_answer"])}</p>') + chip_html
             + f'<p class="lede">{dx.esc(t["intro"])}</p>'
             + f'<h3 class="subhead">{dx.esc(_c(d, "page")["label"])}</h3>' + dx.docsec(anchor("page"), dx.bullets(_c(d, "page")["bullets"]), el_id=anchor("page"))
             + f'<h3 class="subhead">{dx.esc(D["quick_start_label"])}</h3>' + dx.docsec("doc-el-quickstart", dx.steps(D["quick_start"])))
    # How to
    howto = (dx.section_head(T["howto"]["label"], T["howto"]["note"])
             + dx.tabset("ts-doc-howto", [_howto_tab(d, p, v, lib, rules, cfg) for p in t["howto"]["parts"]]))
    # Controls
    ctl_rows, ctl_ids = [], []
    for k, c in t["controls"].items():
        ctl_rows.append([dx.tip(c["label"], d.control_tip(k)), dx.esc(c["does"]), f'<span class="keys">{dx.esc(c["keys"])}</span>' if c["keys"] else ""])
        ctl_ids.append(d.a_control(k))
    controls = (dx.section_head(T["controls"]["label"], T["controls"]["note"])
                + dx.docsec("doc-controls-table", dx.table(["Control", "What it does", "Keys"], ctl_rows, raw_cols={0, 1, 2}, row_ids=ctl_ids, cls="tbl-controls")))
    # Symbols
    sym = (dx.section_head(T["symbols"]["label"], T["symbols"]["note"]) + dx.callout(f'<p>{dx.md_inline(D["symbols_unverified"])}</p>', "watch"))
    sp = D["status_pills"]
    for s in lib["sets"]:
        rows = [[f'<span class="el-chip">{el_symbols.preview_svg(s, x, 28)}</span>', f'<code>{dx.esc(x["code"])}</code>', dx.esc(x["name_de"]), dx.esc(x["name_en"]),
                 dx.esc(el_symbols.category(s, x["category"])["name_de"]), dx.esc(x["layer"]), dx.esc(", ".join(x["connectable_to"]) or "none"),
                 dx.pill(sp["verified"], "good") if x["verified"] else dx.pill(sp["unverified"], "check", title=s["status"])] for x in s["symbols"]]
        meta_rows = [["Id", s["id"]], ["Version", s["version"]], ["Name", f"{s['name_de']} / {s['name_en']}"], ["Standard claimed", s["standard"]],
                     ["Installation standard", s["installation_standard"]], ["Edition", s["edition"]], ["Status", s["status"]],
                     ["Verified", "yes" if s["verified"] else "no"], ["Verified against", s["verified_against"] or "nothing yet"],
                     ["Provenance", s["provenance"]], ["To verify", s["to_verify"]], ["Units", s["units"]], ["Symbols", str(len(s["symbols"]))]]
        sid = anchor("symbols") + "-" + dx.slug(s["id"])
        sym += (f'<h3 class="subhead">{dx.esc(s["name_de"])} <span class="s-meta">v{dx.esc(s["version"])}</span></h3>'
                + dx.docsec(sid, dx.bullets(_c(d, "symbols")["bullets"])
                            + dx.table(["Symbol", "Code", "Name (DE)", "Name (EN)", "Category", "Layer", "Connects to", "Status"], rows,
                                       raw_cols=set(range(8)), row_ids=[sym_anchor(s["id"], x["code"]) for x in s["symbols"]],
                                       caption="From presets/el_symbols_at.json."), el_id=sid)
                + dx.details(set_anchor(s["id"]), f"Set {s['id']}: metadata", dx.table(["Field", "Value"], meta_rows, caption="From presets/el_symbols_at.json."), meta="verify"))
    sym += '<div class="dd-stack">' + _acc(d, "unverified") + _acc(d, "set") + "</div>"
    # Rules & parameters
    rp = (dx.section_head(T["rules"]["label"], T["rules"]["note"]) + dx.tabset("ts-doc-rules", [
        (anchor("rules"), _c(d, "rules")["label"].split(" and ")[0], dx.docsec(anchor("rules") + "-about", dx.bullets(_c(d, "rules")["bullets"])) + rules_tables(rules, d)),
        (anchor("colours"), _c(d, "colours")["label"], dx.docsec(anchor("colours") + "-body", dx.bullets(_c(d, "colours")["bullets"]) + colours_table(params)
                                                                 + f'<p class="tbl-cap">{_short(params["standard_note"], 14)} {_short(params["contrast_min_note"], 12)}</p>')),
        ("doc-el-params-table", _c(d, "params")["label"].split(" (")[0], dx.docsec("doc-el-params-table-body", params_table(params, d))),
    ]))
    # Files (a detail tab)
    layout_schema, plan_schema, params_schema = el_layout.load_schema(), plan_mod.load_schema(), el_params.load_schema()
    ftab = lambda sch, src: dx.table(["Field", "Type", "Required", "What it is"], _schema_rows(sch), caption=f"From {src}.")
    files = (dx.section_head(T["files"]["label"], T["files"]["note"]) + '<div class="dd-stack">'
             + _acc(d, "file", ftab(layout_schema, "schema/el_layout.schema.json")) + _acc(d, "plan_file", ftab(plan_schema, "schema/plan.schema.json"))
             + dx.details("doc-el-params-file", D["params_file"]["label"], dx.bullets(D["params_file"]["bullets"]) + ftab(params_schema, "schema/el_parameters.schema.json"))
             + "</div>")
    # About
    w = t["whatsnew"]
    news = "".join(f'<h3 class="subhead">{dx.esc(e["date"])} · {dx.esc(e["title"])}</h3>' + dx.bullets(e["items"]) for e in w["entries"])
    pages_link = f'<div class="linkrow"><a href="{dx.esc(t["pages_url"])}">GitHub Pages version</a></div>'
    build = (dx.bullets(D["build"]["bullets"]) + _kv([("Parameters", f"{params['id']} v{params['version']}", f"SHA-256 {el_params.sha256()}"),
                                                       ("Symbol set", f"{sdef['id']} v{sdef['version']}", sdef["status"]),
                                                       ("Texts", "presets/editor_docs.json", ""), ("Builder", "tools/build_editor.py", "")]))
    about = (dx.section_head(T["about"]["label"], T["about"]["note"]) + dx.tabset("ts-doc-about", [
        (anchor("privacy"), "Privacy", dx.docsec(anchor("privacy") + "-body", dx.bullets(_c(d, "privacy")["bullets"]))),
        (anchor("variants"), _c(d, "variants")["label"], dx.docsec(anchor("variants") + "-body", dx.bullets(_c(d, "variants")["bullets"]) + pages_link)),
        ("doc-el-whatsnew", w["label"], dx.docsec("doc-el-whatsnew-body", news)),
        ("doc-el-build", D["build"]["label"], dx.docsec("doc-el-build-body", build), {"internal": True}),
    ]))
    tog = (f'<span class="nav-right"><button type="button" class="internals-toggle tip" id="vpt-internals" aria-pressed="false" aria-label="{dx.esc(D["internals"]["hidden"])}" '
           f'data-tip="{dx.esc(dx.popup(D["internals"]["label"], d.bl("docs.internals")))}">⚙</button></span>')
    top = dx.tabset("ts-docs", [("doc-electrical", T["start"]["label"], start), ("doc-el-howto", T["howto"]["label"], howto),
                                ("doc-controls", T["controls"]["label"], controls), ("doc-el-symbols", T["symbols"]["label"], sym),
                                ("doc-el-rulesparams", T["rules"]["label"], rp), ("doc-el-files", T["files"]["label"], files, {"internal": True}),
                                ("doc-el-about", T["about"]["label"], about)], cls="tabset-top", nav_extra=tog)
    foot = f'<footer class="vpt-foot"><p>{dx.md_inline(D["footer"])}</p></footer>'
    return dx.DOC_START + '<div class="docs">' + top + foot + "</div>" + dx.DOC_END


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
                    anchors={k: anchor(k) for k in ("suggestions", "groups", "apply", "links_layer", "rules", "connect", "layers", "storeys", "plan",
                                                    "dxf_export") + tuple("hint_" + h.lower() for h in el_checks.IDS)},
                    labels={"hint_" + h.lower(): _c(d, "hint_" + h.lower())["label"] for h in el_checks.IDS},
                    tips={"layer": d.bl("electrical.layer"), "storeys": d.bl("electrical.storeys")},
                    print=d.print_cfg(), params_panel=t["params_panel"], docs_ui={"internals": t["docs"]["internals"], "fs": t["docs"]["fs"]})
    note_key = "artifact_note" if variant == "artifact" else "pages_note"
    note = dx.esc(t["banners"][note_key]).replace("{url}", f'<a href="{dx.esc(t["pages_url"])}">{dx.esc(t["pages_url"])}</a>')
    head = (f'<header class="vpt-head"><h1>{dx.esc(t["title"])}</h1>'
            f'<p class="vpt-banner vpt-synth" data-banner="synthetic"><b>{dx.esc(t["banners"]["synthetic"])}</b> '
            f'<span>{dx.esc(t["banners"]["synthetic_more"])}</span></p>'
            f'<p class="vpt-banner vpt-own" data-banner="own" hidden></p>'
            f'<p class="el-unv-banner"><span class="tip el-badge" data-tip="{dx.esc(set_tip(sdef, d))}">UNVERIFIED</span> '
            f'{dx.esc(sdef["name_de"])} (version {dx.esc(sdef["version"])}): {dx.esc(sdef["status"])}.</p>'
            f'<p class="vpt-note">{note}</p></header>')
    fs = t["docs"]["fs"]
    tabs = ('<div class="vpt-navrow"><div class="vpt-tabs" role="tablist" aria-label="Page">'
            '<button type="button" role="tab" id="vpt-tab-editor" aria-controls="vpt-pane-editor" aria-selected="true">Editor</button>'
            '<button type="button" role="tab" id="vpt-tab-docs" aria-controls="vpt-pane-docs" aria-selected="false" tabindex="-1">Documentation</button></div>'
            f'<span class="fs-toggle" role="group" aria-label="Text size"><button type="button" class="fs-btn" id="vpt-fs-dec" title="{dx.esc(fs["smaller"])}" '
            f'aria-label="{dx.esc(fs["smaller"])}">A−</button><button type="button" class="fs-btn" id="vpt-fs-inc" title="{dx.esc(fs["larger"])}" '
            f'aria-label="{dx.esc(fs["larger"])}">A+</button></span></div>')
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
                 + doc_tab(lib, rules, params, cfg, d, v, plan) + '</section>')
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
    """The page's own gate: popups short, no dangling More link, Documentation text short (bullets, not prose)."""
    return dx.page_popup_problems(page) + dx.check_doc_links(page) + dx.doc_text_problems(page)


def load_plan(path: pathlib.Path) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
