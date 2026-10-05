#!/usr/bin/env python3
"""Browser check of the two built editor pages in headless Chrome (tools/cdp.py): what a user sees, not only the HTML.

Per page (site/index.html; artifact/electrical_planner.html wrapped in a minimal document skeleton under _scratch/, as the
artifact host would wrap it):
  C1  the drawing is visible: pixels of the stage that are not the black background (falsified: drawing layers hidden)
  C2  the page opens in a working state: the simple example on the synthetic flat, marked EXAMPLE, one Wechselschaltung group
  C3  a symbol dragged from the palette with real mouse events lands within 3 px of where it was let go (Snap off)
  C4  Connect (real clicks: Connect, a switch, a light) makes one link, drawn (link-coloured pixels appear between them)
  C5  Copy layout gives JSON that is valid against schema/el_layout.schema.json and opens on this drawing and storey
  C6  Open plan (a real file through the file input) refuses a malformed file (could-not-tell) and a layout file (different),
      and opens the valid sample plan (match)
  C7  at 400 px width (light and dark): no horizontal page scroll, Editor and Documentation tabs
  C8  text contrast >= 4.5:1 for every visible text element, in light and in dark page themes
  C9  the variant's buttons: Pages has Save / Save to file / Print view, the artifact has none of them (Copy instead)
  C10 no console error or uncaught exception
  C11 no network request except the page itself (falsified: an injected image from a non-allowed host is caught)
  C12 print view (Pages): every placed symbol is in the print sheet, visible in its print colour (pixels of its colour around it,
      against the same crop with the electrical layers off) and in the PDF (stroke colour operators of Page.printToPDF, against a
      PDF with the layers off); a symbol picked but not placed is named in a warning above the sheet. Falsified every run: with
      the symbols made white on paper (the bug, reintroduced) the pixel and PDF measures must drop, else the check cannot go red.
      The demo: no print view to reach.
  C13 every Documentation anchor (#doc-..., from the page's links and tests/doc_anchors.txt) opens its tab, sub-tab and
      accordion and is visible; a popup's More link clicked with real mouse events opens the right tab and sub-tab
  C14 the page's layout checks H1-H9 equal vpt/el_checks.py on both examples, both rule sets, and each example without its
      cooker outlet (falsified: removing it must turn H6 of the complex example from ok to 'to look at' in both); the panel
      shows nine checks, their counts and the plan's windows
  C15 a socket rotated by 180 degrees: its drawing is turned, its letters ("2") are not (net rotation 0 against the page)

Usage: check_editor.py [pages|artifact ...] [--browser chrome|edge] [--scheme light|dark] [--size 1440x900]
The page opens in the given colour scheme (default light) at the given window size; C7/C8 cover both schemes either way.
Exit codes: 0 PASS, 1 FAIL, 3 INDETERMINATE (browser missing or a step could not run).
Results: _scratch/check_<variant>[_<browser>_<scheme>].json.
"""
from __future__ import annotations

import json
import math
import pathlib
import sys
import traceback

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import base64  # noqa: E402
import re  # noqa: E402
import zlib  # noqa: E402

import cdp  # noqa: E402
from vpt import el_checks, el_layout, el_params, el_rules, el_symbols  # noqa: E402

SCRATCH = ROOT / "_scratch"
PAGES = {"pages": ROOT / "site" / "index.html", "artifact": ROOT / "artifact" / "electrical_planner.html"}
ALLOWED_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")
STOREY = "2OG"


def page_url(variant: str) -> str:
    src = PAGES[variant]
    if variant == "artifact":
        wrapped = SCRATCH / "artifact_wrapped.html"
        wrapped.write_text('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
                           "</head><body>\n" + src.read_text(encoding="utf-8") + "\n</body></html>\n", encoding="utf-8")
        return wrapped.resolve().as_uri()
    return src.resolve().as_uri()


def external(requests: list[str], own: str) -> list[str]:
    out = []
    for u in requests:
        if u.startswith(("data:", "blob:", "about:", "chrome")) or u == own or u.startswith("file:"):
            continue
        host = u.split("//", 1)[-1].split("/", 1)[0].split(":")[0].lower()
        if host not in ALLOWED_HOSTS:
            out.append(u)
    return out


CONTRAST_JS = r"""(function () {
  function rgb(s) { var m = String(s).match(/rgba?\(([^)]+)\)/); if (!m) return null; var p = m[1].split(/[ ,\/]+/).filter(Boolean).map(parseFloat); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
  function lum(c) { return [0, 1, 2].map(function (i) { var v = c[i] / 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); })
    .reduce(function (s, v, i) { return s + v * [0.2126, 0.7152, 0.0722][i]; }, 0); }
  function bgOf(el) { for (var e = el; e && e.nodeType === 1; e = e.parentElement) { var c = rgb(getComputedStyle(e).backgroundColor); if (c && c[3] > 0.5) return c; }
    return rgb(getComputedStyle(document.body).backgroundColor) || [255, 255, 255, 1]; }
  var worst = [], n = 0, all = document.querySelectorAll('body *');
  for (var i = 0; i < all.length; i++) { var el = all[i];
    if (el.closest('svg') || el.closest('#dwg-printsheet') || /^(SCRIPT|STYLE|TEMPLATE|OPTION)$/.test(el.tagName)) continue;
    var txt = Array.prototype.some.call(el.childNodes, function (c) { return c.nodeType === 3 && c.textContent.trim(); }); if (!txt) continue;
    var r = el.getBoundingClientRect(); if (!r.width || !r.height || el.closest('[hidden]')) continue;
    var cs = getComputedStyle(el); if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity < 0.6) continue;
    var fg = rgb(cs.color), bg = bgOf(el); if (!fg || !bg) continue;
    var dis = el.closest('button:disabled, select:disabled'); var a = lum(fg), b = lum(bg), ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    n++; if (ratio < 4.5 && !dis) worst.push([ratio.toFixed(2), el.tagName + '.' + (el.className && el.className.baseVal === undefined ? el.className : ''), el.textContent.trim().slice(0, 30)]); }
  worst.sort(function (x, y) { return x[0] - y[0]; });
  return { checked: n, low: worst.slice(0, 12), n_low: worst.length };
})()"""


def count_near(b, png: bytes, rgb, tol: int = 40) -> int:
    """Pixels of a PNG within tol of rgb in every channel (decoded in the page's canvas)."""
    b64 = base64.b64encode(png).decode()
    return b.js("new Promise(function (ok) { var im = new Image(); im.onload = function () { var c = document.createElement('canvas'); c.width = im.width; c.height = im.height;"
                " var x = c.getContext('2d'); x.drawImage(im, 0, 0); var d = x.getImageData(0, 0, c.width, c.height).data, n = 0;"
                f" for (var i = 0; i < d.length; i += 4) if (Math.abs(d[i] - {rgb[0]}) < {tol} && Math.abs(d[i+1] - {rgb[1]}) < {tol} && Math.abs(d[i+2] - {rgb[2]}) < {tol}) n++; ok(n); }};"
                f" im.src = 'data:image/png;base64,{b64}'; }})")


def hex_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def pdf_colour_ops(pdf: bytes, colours: dict) -> dict:
    """How often each colour is set as a stroke or fill colour (RG / rg operators) in the PDF's content streams."""
    text = b""
    for st in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.S):
        try:
            text += zlib.decompress(st)
        except zlib.error:
            pass
    ops = [tuple(float(v) for v in m.groups()[:3]) for m in re.finditer(rb"(-?[0-9.]+) (-?[0-9.]+) (-?[0-9.]+) (?:RG|rg)\b", text)]
    return {k: sum(1 for o in ops if all(abs(a - c / 255) < 0.02 for a, c in zip(o, hex_rgb(h)))) for k, h in colours.items()}


def centre(b, sel: str):
    return b.js(f"(function () {{ var e = document.querySelector('{sel}'); e.scrollIntoView({{block: 'center'}}); var r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()")


def pause(b, ms: int = 300) -> None:
    b.call("Runtime.evaluate", {"expression": f"new Promise(function (ok) {{ setTimeout(ok, {ms}); }})", "awaitPromise": True})


WHITE_ON_PAPER = ("body.dwg-printing g.el-layer .el-symg, body.dwg-printing g.el-layer .el-symg * { stroke: #ffffff !important; color: #ffffff !important; fill: none !important } "
                  "@media print { g.el-layer .el-symg, g.el-layer .el-symg * { stroke: #ffffff !important; color: #ffffff !important; fill: none !important } }")


def print_check(b, P: str, lib: dict) -> tuple:
    """C12: see the module docstring. Returns (ok, detail, extra)."""
    pcol = el_params.palette(el_params.load(), "colours_print")
    sdef = el_symbols.default_set(lib)
    cat = {x["code"]: x["category"] for x in sdef["symbols"]}
    name = {x["code"]: x["name_de"] for x in sdef["symbols"]}
    placed = b.js(f"{P}.layout().symbols")
    pick = next(c for c in ("SS2", "SO", "TV") if c not in {s["code"] for s in placed})
    b.click(*centre(b, f'.el-page[data-storey="{STOREY}"] .el-sym-btn[data-code="{pick}"]'))
    b.click(*centre(b, f'.el-page[data-storey="{STOREY}"] [data-act="print"]'))
    pause(b, 400)
    notes = b.js("Array.prototype.map.call(document.querySelectorAll('#dwg-printsheet .ps-note'), function (p) { return [p.className, p.textContent]; })")
    still_armed = b.js("document.querySelectorAll('.el-sym-btn[aria-pressed=\"true\"]').length")
    vis = b.js(r"""(function () {
      return Array.prototype.map.call(document.querySelectorAll('#dwg-printsheet svg.el-svg g.el-layer .el-sym'), function (g) {
        var r = g.getBoundingClientRect(), shown = true, op = 1, sg = g.querySelector('.el-symg'), ch = sg && sg.firstElementChild;
        for (var e = g; e && e.nodeType === 1; e = e.parentElement) { var cs = getComputedStyle(e); if (cs.display === 'none' || cs.visibility === 'hidden') shown = false; op *= +cs.opacity; }
        var cs2 = ch ? getComputedStyle(ch) : null, m = ch ? ch.getScreenCTM() : null;
        return { id: g.getAttribute('data-id'), code: g.getAttribute('data-code'), rect: [r.left - 2, r.top - 2, r.width + 4, r.height + 4], shown: shown, opacity: op,
                 stroke: cs2 ? cs2.stroke : '', px: cs2 && m ? parseFloat(cs2.strokeWidth) * Math.hypot(m.a, m.b) : 0 };
      }); })()""")

    def crops() -> dict:
        return {v["id"]: count_near(b, b.screenshot(v["rect"]), hex_rgb(pcol[cat[v["code"]]])) for v in vis}

    def el_layers(on: bool) -> None:
        b.js("document.querySelectorAll('.el-page[data-storey=\"" + STOREY + "\"] input[data-toggle-layer][data-base=\"Elektro\"]').forEach(function (i) { i.checked = "
             + ("true" if on else "false") + "; i.dispatchEvent(new Event('change')); })")
        pause(b, 150)

    def pdf() -> dict:
        data = base64.b64decode(b.call("Page.printToPDF", {"printBackground": True, "preferCSSPageSize": True}, timeout=90)["data"])
        return pdf_colour_ops(data, {c: pcol[c] for c in sorted({cat[s["code"]] for s in placed})})
    on, pdf_on = crops(), pdf()
    b.js(f"(function () {{ var s = document.createElement('style'); s.id = 'c12-falsify'; s.textContent = {json.dumps(WHITE_ON_PAPER)}; document.head.appendChild(s); }})()")
    pause(b, 150)
    fals, pdf_fals = crops(), pdf()
    b.js("document.getElementById('c12-falsify').remove()")
    el_layers(False)
    off, pdf_off = crops(), pdf()
    el_layers(True)
    b.click(*centre(b, '#dwg-printsheet [data-act="exit-print"]'))
    pause(b, 200)
    want_rgb = {v["id"]: "rgb(%d, %d, %d)" % hex_rgb(pcol[cat[v["code"]]]) for v in vis}
    ids_ok = sorted(v["id"] for v in vis) == sorted(s["id"] for s in placed)
    vis_ok = all(v["shown"] and v["opacity"] >= 0.9 and v["rect"][2] > 6 and v["rect"][3] > 6 and v["stroke"] == want_rgb[v["id"]] and v["px"] >= 0.75 for v in vis)
    px_ok = all(on[i] - off[i] >= 12 for i in on)
    px_red = all(fals[i] - off[i] < (on[i] - off[i]) / 2 for i in on)
    pdf_ok = all(pdf_on[c] > pdf_off[c] for c in pdf_on)
    pdf_red = all(pdf_fals[c] < pdf_on[c] for c in pdf_on)
    warn = [t for c, t in notes if "ps-note-warn" in c]
    notes_ok = (any(name[pick] in t for t in warn) and any(f"{len(placed)} placed" in t for c, t in notes if "ps-note-ok" in c) and still_armed == 0)
    detail = (f"{len(vis)} of {len(placed)} placed symbols in the print sheet, visible in print colour: {vis_ok} (stroke px {[round(v['px'], 2) for v in vis]}); "
              f"pixels on/off/falsified {[(on[i], off[i], fals[i]) for i in on]}; PDF colour ops on/off/falsified {[(c, pdf_on[c], pdf_off[c], pdf_fals[c]) for c in pdf_on]}; "
              f"notes {[t[:70] for c, t in notes]}; picked {pick} left armed: {still_armed}")
    if not (px_red and pdf_red):
        return None, "the falsified run (symbols white on paper) did not drop the measures: the check cannot go red. " + detail, {}
    return ids_ok and vis_ok and px_ok and pdf_ok and notes_ok, detail, {"pixels": [on, off, fals], "pdf": [pdf_on, pdf_off, pdf_fals]}


ANCHOR_JS = r"""(function (ids) {
  var bad = [];
  ids.forEach(function (id) {
    if (!window.vptShowDoc(id)) { bad.push(id + ': missing'); return; }
    var t = document.getElementById(id), ok = t.getClientRects().length > 0 && !document.getElementById('vpt-pane-docs').hidden;
    for (var e = t; e && e.nodeType === 1; e = e.parentElement) {
      if (e.classList.contains('tabpanel') && !e.classList.contains('active')) ok = false;
      if (e.tagName === 'DETAILS' && e !== t && !e.open) ok = false;
      if (e.hidden) ok = false; }
    if (!ok) bad.push(id); });
  return bad; })"""


def anchor_check(b, variant: str) -> tuple:
    page = PAGES[variant].read_text(encoding="utf-8")
    ids = sorted(set(re.findall(r'(?:href=(?:"|&quot;)#)(doc-[a-z0-9-]+)', page)) | set((ROOT / "tests" / "doc_anchors.txt").read_text(encoding="utf-8").split()))
    bad = b.js(ANCHOR_JS + "(" + json.dumps(ids) + ")")
    # falsified: an id that is not on the page must be reported
    fbad = b.js(ANCHOR_JS + '(["doc-not-there"])')
    # a real More click from a popup: hover the Snap label, click the popup's More link
    b.js("window.vptShowTab('vpt-pane-editor')")
    x, y = centre(b, f'.el-page[data-storey="{STOREY}"] .el-snap-wrap')
    b.mouse("mouseMoved", x, y, buttons=0)
    pause(b, 200)
    link = b.js("(function () { var a = document.querySelector('#tipbox:not([hidden]) a.doclink'); if (!a) return null; var r = a.getBoundingClientRect();"
                " return [r.left + r.width / 2, r.top + r.height / 2, a.getAttribute('href')]; })()")
    got = None
    if link:
        b.mouse("mouseMoved", link[0], link[1], buttons=0)
        b.click(link[0], link[1])
        pause(b, 300)
        got = b.js("(function () { var sel = function (ts) { var t = document.querySelector('#' + ts + ' > .tabset-nav > .tab[aria-selected=\"true\"]'); return t ? t.getAttribute('data-tab') : null; };"
                   " return [!document.getElementById('vpt-pane-docs').hidden, sel('ts-docs'), sel('ts-doc-howto')]; })()")
    want = [True, "doc-el-howto", link[2][1:] if link else None]
    ok = not bad and fbad == ["doc-not-there: missing"] and got == want
    return ok, f"{len(ids)} anchors opened, {len(bad)} not visible {bad[:5]} (falsified: {fbad}); popup More {link[2] if link else 'not found'} -> docs shown, tab, sub-tab {got}"


def stage_rect(b) -> list[float]:
    return b.js(f"(function () {{ var s = document.querySelector('.el-page[data-storey=\"{STOREY}\"] svg.el-svg'); s.scrollIntoView({{block: 'start'}});"
                "var r = s.getBoundingClientRect(); return [r.left, r.top, r.width, Math.min(r.height, window.innerHeight - r.top)]; })()")


def checks_mirror(b, P: str, plan: dict, lib: dict) -> tuple:
    """C14: see the module docstring. Returns (ok, detail)."""
    st = next(s for s in plan["storeys"] if s["key"] == STOREY)
    rules, sdef, k = el_rules.load(), el_symbols.default_set(lib), plan["drawing"]["units_per_m"]
    cooker = set(rules["checks"]["cooker_codes"])
    diffs, n, h6 = [], 0, {}
    for ex_id in ("simple", "complex"):
        ex = st["examples"][ex_id]
        for what, syms in (("as generated", ex["symbols"]), ("without cooker outlet", [s for s in ex["symbols"] if s["code"] not in cooker])):
            for rs in rules["rule_sets"]:
                py = el_checks.checks(syms, ex["links"], st["rooms"], st["doors"], k, rules, rs["id"], sdef, True)
                js = b.js(f"{P}.checksOf({json.dumps(syms)}, {json.dumps(ex['links'])}, {json.dumps(rs['id'])})")
                n += 1
                if json.loads(json.dumps(py)) != js:
                    bad = [p["id"] for p, j in zip(py, js or []) if json.loads(json.dumps(p)) != j]
                    diffs.append(f"{ex_id} {what} {rs['id']}: {bad or 'shape'}")
                if ex_id == "complex" and rs["id"] == "starting":
                    h6[what] = (py[5]["status"], js[5]["status"] if js else None)
    red = h6.get("as generated") == ("match", "match") and h6.get("without cooker outlet") == ("different", "different")
    panel = b.js(f"(function () {{ var p = document.querySelector('.el-page[data-storey=\"{STOREY}\"]');"
                 " return { n: p.querySelectorAll('.el-hint[data-hint]').length, st: Array.prototype.map.call(p.querySelectorAll('.el-hint[data-hint]'), function (l) { return l.getAttribute('data-status'); }),"
                 " counts: p.querySelector('.el-check-counts').textContent, windows: p.querySelector('.el-windows').getAttribute('data-windows') }; })()")
    cur = b.js(f"{P}.hints()")
    want_counts = el_checks.counts(cur)
    counts_ok = panel["counts"] == f"({want_counts['match']} ok · {want_counts['different']} to look at · {want_counts['could-not-tell']} could not tell)"
    ok = not diffs and red and panel["n"] == len(el_checks.IDS) and panel["st"] == [c["status"] for c in cur] and counts_ok and panel["windows"] == str(len(st["windows"]))
    return (ok if red else None), (f"{n} comparisons page vs vpt/el_checks.py, {len(diffs)} different {diffs[:3]}; H6 complex (py, page): {h6} (falsified by removing the cooker outlet);"
                                   f" panel {panel['n']} checks {panel['counts']}, windows {panel['windows']}")


def run(variant: str, browser: str = "chrome", scheme: str = "light", size: tuple = (1400, 1000)) -> dict:
    res: dict = {"variant": variant, "browser": browser, "scheme": scheme, "size": list(size), "checks": {}, "status": "PASS"}
    url = page_url(variant)

    def put(cid: str, ok, detail: str, **extra):
        res["checks"][cid] = dict({"status": "PASS" if ok is True else ("FAIL" if ok is False else "INDETERMINATE"), "detail": detail}, **extra)

    lib, schema = el_symbols.load(), el_layout.load_schema()
    plan = json.loads((ROOT / "samples" / "synthetic_flat.plan.json").read_text(encoding="utf-8"))
    sha = plan["drawing"]["sha256"]
    with cdp.Browser(size=size, binary=cdp.BROWSERS[browser]) as b:
        b.viewport(*size)
        b.colour_scheme(scheme)
        b.open(url, settle=1.5)
        res["user_agent"] = b.js("navigator.userAgent")          # which browser actually ran (Edge says Edg/)
        P = f"window.elPages['{STOREY}']"
        # ---- C2 working state
        st = b.js(f"(function () {{ var p = {P}; var g = p.groups(); return {{ ex: p.exampleShown(), groups: g.length, type: g.length ? p.proposal(0).type : null,"
                  f" matches: g.length ? p.proposal(0).matches : null, banner: !document.querySelector('.el-page[data-storey=\"{STOREY}\"] .el-example-banner').hidden,"
                  " text: document.querySelector('.el-example-text').textContent, synth: !document.querySelector('[data-banner=\"synthetic\"]').hidden,"
                  " synthText: document.querySelector('[data-banner=\"synthetic\"]').textContent, n: p.layout().symbols.length }; })()")
        ok2 = (st["ex"] == "simple" and st["groups"] == 1 and st["type"] == "2" and st["matches"] and st["banner"]
               and "synthetic flat, not real data" in st["text"] and st["synth"] and "keine realen Gebäudedaten" in st["synthText"])
        put("C2", ok2, f"example {st['ex']}, {st['n']} symbols, {st['groups']} group(s) of type {st['type']} (matches {st['matches']}), banner {st['text']!r}")
        # ---- C14 layout checks: the page mirrors vpt/el_checks.py
        ok14, d14 = checks_mirror(b, P, plan, lib)
        put("C14", ok14, d14)
        # ---- C1 drawing visible, falsified by hiding the drawing layers and the symbols
        r = stage_rect(b)
        n_on = b.pixels(b.screenshot(r), (0, 0, 0))
        b.js(f"(function () {{ var p = document.querySelector('.el-page[data-storey=\"{STOREY}\"]'); p.querySelector('[data-act=\"all-off\"]').click();"
             " p.querySelectorAll('input[data-toggle-layer][data-base=\"Elektro\"]').forEach(function (i) { i.checked = false; i.dispatchEvent(new Event('change')); }); })()")
        n_off = b.pixels(b.screenshot(stage_rect(b)), (0, 0, 0))
        b.js(f"(function () {{ var p = document.querySelector('.el-page[data-storey=\"{STOREY}\"]'); p.querySelector('[data-act=\"all-on\"]').click();"
             " p.querySelectorAll('input[data-toggle-layer][data-base=\"Elektro\"]').forEach(function (i) { i.checked = true; i.dispatchEvent(new Event('change')); }); })()")
        n_back = b.pixels(b.screenshot(stage_rect(b)), (0, 0, 0))
        put("C1", n_on > 3000 and n_off < n_on / 20 and n_back > 3000,
            f"{n_on} non-background pixels shown; {n_off} with every layer off (falsified); {n_back} after turning them on again", pixels=[n_on, n_off, n_back])
        # ---- C3 drag-drop with real mouse events (Snap off), on an empty storey
        b.js(f"(function () {{ var s = document.querySelector('.el-page[data-storey=\"{STOREY}\"] select.el-example'); s.value = 'none'; s.dispatchEvent(new Event('change'));"
             f" document.querySelector('.el-page[data-storey=\"{STOREY}\"] input.el-snap').checked = false; }})()")
        r = stage_rect(b)

        def drag_symbol(code: str, fx: float, fy: float):
            btn = b.js(f"(function () {{ var e = document.querySelector('.el-page[data-storey=\"{STOREY}\"] .el-sym-btn[data-code=\"{code}\"]'); e.scrollIntoView({{block: 'nearest'}});"
                       " var r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
            rr = b.js(f"(function () {{ var r = document.querySelector('.el-page[data-storey=\"{STOREY}\"] svg.el-svg').getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; }})()")
            x1, y1 = rr[0] + rr[2] * fx, rr[1] + min(rr[3], size[1] - rr[1]) * fy
            before = b.js(f"{P}.layout().symbols.length")
            b.drag(btn[0], btn[1], x1, y1, steps=10)
            syms = b.js(f"{P}.layout().symbols")
            if len(syms) != before + 1:
                return None, (x1, y1), None
            sid = syms[-1]["id"]
            at = b.js(f"{P}.anchor('{sid}')")
            return sid, (x1, y1), at
        sid1, drop1, at1 = drag_symbol("SS1", 0.30, 0.45)
        d1 = math.dist(drop1, at1) if at1 else None
        put("C3", d1 is not None and d1 <= 3.0, f"dropped at ({drop1[0]:.1f}, {drop1[1]:.1f}); symbol {sid1} drawn at "
            f"{'(%.1f, %.1f)' % tuple(at1) if at1 else 'nowhere'}: {('%.2f px' % d1) if d1 is not None else 'not placed'}", distance_px=d1)
        # ---- C4 Connect with real clicks
        sid_l, _, at_l = drag_symbol("LD", 0.55, 0.35)
        sid_s, _, at_s = drag_symbol("SA", 0.70, 0.60)
        mid = ((at_l[0] + at_s[0]) / 2, (at_l[1] + at_s[1]) / 2) if at_l and at_s else None
        box = [mid[0] - 12, mid[1] - 12, 24, 24] if mid else None
        lc = b.js("JSON.parse(document.getElementById('el-params').textContent).sections.colours_screen.values.link.value").lstrip("#")
        link_rgb = tuple(int(lc[i:i + 2], 16) for i in (0, 2, 4))

        def cyan(png) -> int:      # pixels close to the link colour
            return b.js("new Promise(function (ok) { var im = new Image(); im.onload = function () { var c = document.createElement('canvas'); c.width = im.width; c.height = im.height;"
                        " var x = c.getContext('2d'); x.drawImage(im, 0, 0); var d = x.getImageData(0, 0, c.width, c.height).data, n = 0;"
                        f" for (var i = 0; i < d.length; i += 4) if (Math.abs(d[i] - {link_rgb[0]}) < 60 && Math.abs(d[i+1] - {link_rgb[1]}) < 60 && Math.abs(d[i+2] - {link_rgb[2]}) < 60) n++; ok(n); }};"
                        " im.src = 'data:image/png;base64," + __import__("base64").b64encode(png).decode() + "'; })")
        c0 = cyan(b.screenshot(box)) if box else None
        if at_l and at_s:
            cb = b.js(f"(function () {{ var e = document.querySelector('.el-page[data-storey=\"{STOREY}\"] [data-el=\"connect\"]'); e.scrollIntoView({{block: 'center'}});"
                      " var r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()")
            b.click(*cb)
            stage_rect(b)                     # back to the same scroll position as before
            at_s2, at_l2 = b.js(f"{P}.anchor('{sid_s}')"), b.js(f"{P}.anchor('{sid_l}')")
            b.click(*at_s2)
            b.click(*at_l2)
        links = b.js(f"{P}.layout().links")
        if at_l and at_s:
            at_l3, at_s3 = b.js(f"{P}.anchor('{sid_l}')"), b.js(f"{P}.anchor('{sid_s}')")
            mid = ((at_l3[0] + at_s3[0]) / 2, (at_l3[1] + at_s3[1]) / 2)
            box = [mid[0] - 12, mid[1] - 12, 24, 24]
        c1 = cyan(b.screenshot(box)) if box else None
        ok4 = bool(links) and len(links) == 1 and links[0]["from"] == sid_s and links[0]["to"] == sid_l and c1 is not None and c1 > max(10, 3 * (c0 or 0))
        put("C4", ok4, f"links {links}; link-coloured pixels at the midpoint {c0} before, {c1} after", before=c0, after=c1)
        # ---- C15 a symbol's letters stay upright when the symbol is rotated (socket "2", rotated by 180 degrees, falsified by
        #      measuring the symbol's own drawing group, which must be turned by 180 while its letters are not)
        sid14, _, _ = drag_symbol("SS2", 0.25, 0.80)
        if sid14:
            sel14 = f".el-page[data-storey=\"{STOREY}\"] .el-sym[data-id=\"{sid14}\"]"
            probe14 = ("(function () { var ang = function (e) { var m = e.getScreenCTM(); return Math.atan2(m.b, m.a) * 180 / Math.PI; };"
                       f" var g = document.querySelector('{sel14}'), root = ang(g.ownerSVGElement), norm = function (a) {{ a = (a - root) % 360; return a < 0 ? a + 360 : a; }};"
                       " var ts = g.querySelectorAll('text'); return { n: ts.length, text: ts.length ? norm(ang(ts[0])) : null, drawing: norm(ang(g.querySelector('.el-symg'))) }; })()")
            b.js(f"{P}.select('{sid14}')")
            for _ in range(2):
                b.js(f"document.querySelector('.el-page[data-storey=\"{STOREY}\"] [data-el=\"rotate\"]').click()")
            rot14 = b.js(f"{P}.layout().symbols.filter(function (s) {{ return s.id === '{sid14}'; }})[0].rotation")
            m14 = b.js(probe14)
            up = lambda a: a is not None and min(a, 360 - a) < 0.5      # noqa: E731 - upright: no net turn
            put("C15", rot14 == 180 and m14["n"] >= 1 and up(m14["text"]) and abs(m14["drawing"] - 180) < 0.5,
                f"socket 2 rotated {rot14} degrees: its drawing is turned {m14['drawing']:.1f} degrees, its {m14['n']} letter(s) {m14['text']} (upright: 0)", measure=m14)
            b.js(f"{P}.select('{sid14}')")
            b.js(f"document.querySelector('.el-page[data-storey=\"{STOREY}\"] [data-el=\"delete\"]').click()")
        else:
            put("C15", None, "the socket could not be placed with a real drag")
        # ---- C12 print view: the placed symbols (SS1, LD, SA above, placed by real pointer events) on paper and in the PDF
        if variant == "pages":
            ok12, d12, x12 = print_check(b, P, lib)
            put("C12", ok12, d12, **x12)
        else:
            put("C12", not b.js("!!document.querySelector('[data-act=\"print\"]')"), "the demo has no print view a user could reach (no Print view button)")
        # ---- C13 Documentation anchors and a real More click
        ok13, d13 = anchor_check(b, variant)
        put("C13", ok13, d13)
        b.js("window.vptShowTab('vpt-pane-editor')")
        # ---- C5 Copy layout -> JSON valid against the schema and opening on this drawing (match)
        try:
            b.call("Browser.grantPermissions", {"permissions": ["clipboardReadWrite", "clipboardSanitizedWrite"]})
        except cdp.CDPError:
            pass
        b.js(f"document.querySelector('.el-page[data-storey=\"{STOREY}\"] [data-el=\"copy\"]').click()")
        b.call("Runtime.evaluate", {"expression": "new Promise(function (ok) { setTimeout(ok, 400); })", "awaitPromise": True})
        how, text = b.js("(function () { var box = document.querySelector('.vpt-copybox'); if (!box.hidden) return Promise.resolve(['box', box.querySelector('textarea').value]);"
                         " return navigator.clipboard.readText().then(function (t) { return ['clipboard', t]; }, function (e) { return ['none', String(e)]; }); })()")
        try:
            doc = json.loads(text)
            probs = el_layout.validate(doc, schema)
            chk = el_layout.check_layout(doc, sha256=sha, storey=STOREY, lib=lib, schema=schema, rules=el_rules.load())
        except (json.JSONDecodeError, TypeError) as e:
            doc, probs, chk = None, [f"not JSON: {e}"], ("could-not-tell", "")
        put("C5", how in ("box", "clipboard") and not probs and chk[0] == "match" and len(doc["symbols"]) == 3 and len(doc["links"]) == 1,
            f"copied via {how}: {len(text)} chars, schema problems {probs[:2]}, open check {chk[0]}: {chk[1]}")
        b.js("document.querySelector('.vpt-copybox').hidden = true")
        # C5b the clipboard refused (as an artifact host may do): the text is shown in the copy box, selected
        b.js("navigator.clipboard.writeText = function () { return Promise.reject(new Error('refused')); };"
             f" document.querySelector('.el-page[data-storey=\"{STOREY}\"] [data-el=\"copy\"]').click()")
        b.call("Runtime.evaluate", {"expression": "new Promise(function (ok) { setTimeout(ok, 300); })", "awaitPromise": True})
        fb = b.js("(function () { var box = document.querySelector('.vpt-copybox'), ta = box.querySelector('textarea');"
                  " return [box.hidden, ta.value, ta.selectionStart === 0 && ta.selectionEnd === ta.value.length]; })()")
        try:
            fb_ok = (not fb[0]) and fb[2] and el_layout.validate(json.loads(fb[1]), schema) == []
        except (json.JSONDecodeError, TypeError):
            fb_ok = False
        put("C5b", fb_ok, f"clipboard refused: copy box shown {not fb[0]}, text selected {fb[2]}, {len(fb[1])} chars of valid layout JSON: {fb_ok}")
        b.js("document.querySelector('.vpt-copybox').hidden = true")
        # ---- C6 Open plan through the real file input: malformed (could-not-tell), a layout file (different), the sample (match)
        bad = SCRATCH / "malformed.plan.json"
        bad.write_text('{"schema": "vpt_plan", "schema_version": 1, "storeys": [', encoding="utf-8")
        lay = SCRATCH / "a_layout.electrical.json"
        lay.write_text(text, encoding="utf-8")
        outcomes = []
        root = b.call("DOM.getDocument", {"depth": -1})["root"]["nodeId"]
        for f in (bad, lay, ROOT / "samples" / "synthetic_flat.plan.json"):
            node = b.call("DOM.querySelector", {"nodeId": root, "selector": "input.vpt-plan-file"})["nodeId"]
            b.js("document.getElementById('vpt').removeAttribute('data-plan-open')")
            b.call("DOM.setFileInputFiles", {"nodeId": node, "files": [str(f.resolve())]})
            got = None
            for _ in range(40):
                got = b.js("document.getElementById('vpt').getAttribute('data-plan-open')")
                if got:
                    break
                b.call("Runtime.evaluate", {"expression": "new Promise(function (ok) { setTimeout(ok, 100); })", "awaitPromise": True})
            outcomes.append((f.name, got, b.js("document.querySelector('.vpt-status').textContent")[:120]))
            root = b.call("DOM.getDocument", {"depth": -1})["root"]["nodeId"]
        put("C6", [o[1] for o in outcomes] == ["could-not-tell", "different", "match"], "; ".join(f"{n}: {o} ({m})" for n, o, m in outcomes))
        # ---- C9 the variant's buttons
        has = b.js("(function () { var q = function (s) { return !!document.querySelector(s); }; return { save: q('[data-el=\"save\"]'), fs: q('[data-el=\"save-in-place\"]'),"
                   " print: q('[data-act=\"print\"]'), psave: q('[data-pact=\"save\"]'), copy: q('[data-el=\"copy\"]'), pcopy: q('[data-pact=\"copy\"]') }; })()")
        want = {"save": variant == "pages", "fs": variant == "pages", "print": variant == "pages", "psave": variant == "pages", "copy": True, "pcopy": True}
        put("C9", has == want, f"buttons {has}")
        # ---- C11 network, falsified by an injected image from a non-allowed host
        ext = external(b.requests, url)
        b.js("(function () { var i = new Image(); i.src = 'http://127.0.0.1:9/falsify.png'; document.body.appendChild(i); })()")
        b.call("Runtime.evaluate", {"expression": "new Promise(function (ok) { setTimeout(ok, 500); })", "awaitPromise": True})
        ext2 = external(b.requests, url)
        b.js("document.querySelectorAll('img[src*=\"falsify\"]').forEach(function (i) { i.remove(); })")
        put("C11", not ext and any("falsify" in u for u in ext2), f"{len(b.requests)} requests, external: {ext or 'none'} (falsified: injected image seen as {ext2})")
        errors_main = [e for e in b.errors if "falsify" not in e and "127.0.0.1:9" not in e]
        # ---- C8 contrast, light and dark; C7 phone width
        con = {}
        for scheme in ("light", "dark"):
            b.colour_scheme(scheme)
            b.call("Runtime.evaluate", {"expression": "new Promise(function (ok) { setTimeout(ok, 200); })", "awaitPromise": True})
            b.js("document.querySelector('.el-params').open = true")      # the Parameters tables and pills are checked too
            con[scheme] = b.js(CONTRAST_JS)
            b.js("document.querySelector('.el-params').open = false; window.vptShowTab('vpt-pane-docs')")
            con[scheme + "_docs"] = b.js(CONTRAST_JS)
            b.js("window.vptShowTab('vpt-pane-editor')")
        put("C8", all(v["n_low"] == 0 and v["checked"] > 20 for v in con.values()),
            "; ".join(f"{k}: {v['checked']} text elements, {v['n_low']} below 4.5:1 {v['low'][:3]}" for k, v in con.items()))
        phone = {}
        b.viewport(400, 860, mobile=True)
        for scheme in ("light", "dark"):
            b.colour_scheme(scheme)
            b.open(url, settle=1.5)
            w = b.js("[document.documentElement.scrollWidth, document.documentElement.clientWidth, document.body.scrollWidth]")
            b.js("window.vptShowTab('vpt-pane-docs')")
            wd = b.js("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
            b.js("window.vptShowTab('vpt-pane-editor')")
            pr = b.js("(function () { var s = document.querySelector('svg.el-svg').getBoundingClientRect(); return [s.left, s.right]; })()")
            phone[scheme] = {"editor": w, "docs": wd, "stage": pr}
        ok7 = all(v["editor"][0] <= v["editor"][1] and v["docs"][0] <= v["docs"][1] and v["stage"][0] >= 15 and v["stage"][1] <= 385 for v in phone.values())
        put("C7", ok7, "; ".join(f"{k}: editor scroll {v['editor'][0]} / client {v['editor'][1]}, docs {v['docs'][0]} / {v['docs'][1]}, stage x {v['stage'][0]:.0f}-{v['stage'][1]:.0f}"
                                 for k, v in phone.items()))
        errors = errors_main + [e for e in b.errors if "falsify" not in e]
        put("C10", not errors, f"{len(errors)} console error(s)/exception(s): {errors[:3]}")
    if any(c["status"] == "FAIL" for c in res["checks"].values()):
        res["status"] = "FAIL"
    elif any(c["status"] != "PASS" for c in res["checks"].values()):
        res["status"] = "INDETERMINATE"
    return res


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Browser check of the editor pages")
    ap.add_argument("variants", nargs="*", help=f"any of {', '.join(PAGES)} (default: both)")
    ap.add_argument("--browser", choices=sorted(cdp.BROWSERS), default="chrome")
    ap.add_argument("--scheme", choices=("light", "dark"), default="light")
    ap.add_argument("--size", default="1400x1000", help="window size WIDTHxHEIGHT in CSS pixels")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    try:
        size = tuple(int(x) for x in args.size.lower().split("x"))
        assert len(size) == 2 and min(size) > 0
    except (ValueError, AssertionError):
        print(f"usage: --size WIDTHxHEIGHT, got {args.size!r}", file=sys.stderr)
        return 2
    variants = args.variants or list(PAGES)
    if any(v not in PAGES for v in variants):
        print(f"usage: variants are {', '.join(PAGES)}, got {variants}", file=sys.stderr)
        return 2
    tag = "" if (args.browser, args.scheme, size) == ("chrome", "light", (1400, 1000)) else f"_{args.browser}_{args.scheme}"
    status = 0
    for v in variants:
        try:
            res = run(v, args.browser, args.scheme, size)
        except FileNotFoundError as e:
            print(f"INDETERMINATE {v}: {args.browser} not found ({e})")
            return 3
        except Exception as e:  # noqa: BLE001 - a crashed check is could-not-tell, never a pass
            res = {"variant": v, "status": "INDETERMINATE", "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-2000:]}
        (SCRATCH / f"check_{v}{tag}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{res['status']} {v} ({args.browser}, {args.scheme}, {size[0]}x{size[1]}; {res.get('user_agent', '?')})")
        for cid, c in (res.get("checks") or {}).items():
            print(f"  {cid:3s} {c['status']:13s} {c['detail'][:400]}")
        if res.get("error"):
            print("  error: " + res["error"])
        status = max(status, {"PASS": 0, "FAIL": 1, "INDETERMINATE": 3}[res["status"]])
    return status


if __name__ == "__main__":
    sys.exit(main())
