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
Exit codes: 0 PASS, 1 FAIL, 3 INDETERMINATE (Chrome missing or a step could not run). Results: _scratch/check_<variant>.json.
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

import cdp  # noqa: E402
from vpt import el_layout, el_rules, el_symbols  # noqa: E402

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


def stage_rect(b) -> list[float]:
    return b.js(f"(function () {{ var s = document.querySelector('.el-page[data-storey=\"{STOREY}\"] svg.el-svg'); s.scrollIntoView({{block: 'start'}});"
                "var r = s.getBoundingClientRect(); return [r.left, r.top, r.width, Math.min(r.height, window.innerHeight - r.top)]; })()")


def run(variant: str) -> dict:
    res: dict = {"variant": variant, "checks": {}, "status": "PASS"}
    url = page_url(variant)

    def put(cid: str, ok, detail: str, **extra):
        res["checks"][cid] = dict({"status": "PASS" if ok is True else ("FAIL" if ok is False else "INDETERMINATE"), "detail": detail}, **extra)

    lib, schema = el_symbols.load(), el_layout.load_schema()
    plan = json.loads((ROOT / "samples" / "synthetic_flat.plan.json").read_text(encoding="utf-8"))
    sha = plan["drawing"]["sha256"]
    with cdp.Browser(size=(1400, 1000)) as b:
        b.colour_scheme("light")
        b.open(url, settle=1.5)
        P = f"window.elPages['{STOREY}']"
        # ---- C2 working state
        st = b.js(f"(function () {{ var p = {P}; var g = p.groups(); return {{ ex: p.exampleShown(), groups: g.length, type: g.length ? p.proposal(0).type : null,"
                  f" matches: g.length ? p.proposal(0).matches : null, banner: !document.querySelector('.el-page[data-storey=\"{STOREY}\"] .el-example-banner').hidden,"
                  " text: document.querySelector('.el-example-text').textContent, synth: !document.querySelector('[data-banner=\"synthetic\"]').hidden,"
                  " synthText: document.querySelector('[data-banner=\"synthetic\"]').textContent, n: p.layout().symbols.length }; })()")
        ok2 = (st["ex"] == "simple" and st["groups"] == 1 and st["type"] == "2" and st["matches"] and st["banner"]
               and "synthetic flat, not real data" in st["text"] and st["synth"] and "keine realen Gebäudedaten" in st["synthText"])
        put("C2", ok2, f"example {st['ex']}, {st['n']} symbols, {st['groups']} group(s) of type {st['type']} (matches {st['matches']}), banner {st['text']!r}")
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
            x1, y1 = rr[0] + rr[2] * fx, rr[1] + min(rr[3], 1000 - rr[1]) * fy
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
            con[scheme] = b.js(CONTRAST_JS)
            b.js("window.vptShowTab('vpt-pane-docs')")
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
    variants = (argv or sys.argv[1:]) or list(PAGES)
    status = 0
    for v in variants:
        try:
            res = run(v)
        except FileNotFoundError as e:
            print(f"INDETERMINATE {v}: Chrome not found ({e})")
            return 3
        except Exception as e:  # noqa: BLE001 - a crashed check is could-not-tell, never a pass
            res = {"variant": v, "status": "INDETERMINATE", "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-2000:]}
        (SCRATCH / f"check_{v}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{res['status']} {v}")
        for cid, c in (res.get("checks") or {}).items():
            print(f"  {cid:3s} {c['status']:13s} {c['detail'][:400]}")
        if res.get("error"):
            print("  error: " + res["error"])
        status = max(status, {"PASS": 0, "FAIL": 1, "INDETERMINATE": 3}[res["status"]])
    return status


if __name__ == "__main__":
    sys.exit(main())
