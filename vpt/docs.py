"""Hover popups, sortable tables and the Documentation building blocks of the editor page.

Prose lives once in presets/editor_docs.json. The Documentation tab is built from short bullets, numbered steps, callouts, pill
tabsets and folded accordions; doc_text_problems() is its gate (a paragraph at most DOC_MAX_PARA_WORDS words, a list item at most
DOC_MAX_ITEM_WORDS, every section with a list or table). Every popup is short (popup(): a bold title, at most TIP_MAX_BULLETS bullets of
about 12 words, keywords in **bold**) and ends with a "More" link to a section of the Documentation tab with a stable anchor
(#doc-...). popup_problems() is the gate: the editor build fails on a popup that is too long, and check_doc_links() on a More
link whose anchor is not on the page.
"""
from __future__ import annotations

import html as _html
import json
import pathlib
import re
import unicodedata

from vpt import PRESETS

PRESET = PRESETS / "editor_docs.json"
TIP_MAX_BULLETS = 4
TIP_MAX_WORDS = 14          # "about 12": a name or a number may push a bullet a little over
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_TAG = re.compile(r"<[^>]+>")


def esc(s) -> str:
    return _html.escape("" if s is None else str(s), quote=True)


def slug(text: str) -> str:
    """ASCII anchor slug: umlauts transliterated (ä -> ae), anything else not [a-z0-9] -> '-'."""
    t = str(text).lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "x"


def md_inline(s: str) -> str:
    """Escape s, then turn **x** into <b>x</b> (the only markup the bullet texts use)."""
    return _BOLD.sub(r"<b>\1</b>", esc(s))


def short(s, n: int = 12) -> str:
    w = str(s or "").split()
    return " ".join(w[:n]) + (" …" if len(w) > n else "")


def tip(text: str, popup_html: str, cls: str = "tip") -> str:
    """Inline text with a hover popup. popup_html is trusted HTML built by this module's callers."""
    return f'<span class="{cls}" data-tip="{esc(popup_html)}">{esc(text)}</span>'


def popup(title: str, items=(), more: str = "", extra: str = "") -> str:
    li = "".join(f"<li>{md_inline(x)}</li>" for x in items if x)
    return f'<p class="tip-h"><b>{esc(title)}</b></p>' + (f'<ul class="tipl">{li}</ul>' if li else "") + extra + more


def more(anchor: str) -> str:
    return f'<p class="more"><a class="doclink" href="#{esc(anchor)}">More &rarr;</a></p>'


def _words(fragment: str) -> int:
    return len(_html.unescape(_TAG.sub(" ", fragment)).split())


def popup_problems(body: str, max_bullets: int = TIP_MAX_BULLETS, max_words: int = TIP_MAX_WORDS) -> list[str]:
    """Why a popup body is too long (empty = fine): more than max_bullets bullets, a bullet or paragraph over max_words
    words, more than one paragraph besides the title and the More link. Tables (data) are not counted."""
    b = re.sub(r"<table\b.*?</table>", " ", body, flags=re.S | re.I)
    b = re.sub(r'<p class="(?:more|tip-h)">.*?</p>', " ", b, flags=re.S)
    items = re.findall(r"<li\b[^>]*>(.*?)</li>", b, flags=re.S)
    paras = re.findall(r"<p\b[^>]*>(.*?)</p>", b, flags=re.S)
    rest = re.sub(r"<(ul|ol)\b.*?</\1>|<p\b.*?</p>", " ", b, flags=re.S)
    out = []
    if len(items) > max_bullets:
        out.append(f"{len(items)} bullets (max {max_bullets})")
    out += [f"bullet of {_words(x)} words (max {max_words})" for x in items if _words(x) > max_words]
    out += [f"paragraph of {_words(x)} words (max {max_words})" for x in paras if _words(x) > max_words]
    if len(paras) > 1:
        out.append(f"{len(paras)} paragraphs (max 1 besides title and More)")
    if _words(rest) > max_words:
        out.append(f"{_words(rest)} words of loose text")
    return out


_POPUP = re.compile(r'data-tip=("[^"]*"|\'[^\']*\')')


_SCRIPT = re.compile(r"<script\b.*?</script\s*>", re.S | re.I)


def page_popup_problems(page: str) -> list[str]:
    """popup_problems() of every data-tip in the page's markup (scripts left out: popups built by the page script are checked
    in the browser check), with the popup's title for finding it."""
    out = []
    for m in _POPUP.finditer(_SCRIPT.sub(" ", page)):
        body = _html.unescape(m.group(1)[1:-1])
        probs = popup_problems(body)
        if probs:
            ttl = re.search(r"<b>(.*?)</b>", body, flags=re.S)
            name = _html.unescape(_TAG.sub("", ttl.group(1)))[:40] if ttl else "(no title)"
            out.append(f"popup '{name}': " + "; ".join(probs))
    return out


_DOCLINK = re.compile(r'href=(?:"|&quot;)#(doc-[a-z0-9-]+)(?:"|&quot;)')
_DOC_ID = re.compile(r'\bid="(doc-[a-z0-9-]+)"')


def check_doc_links(page: str) -> list[str]:
    """Every #doc-... link on the page (also inside popups, where it is HTML-escaped) must have its anchor on the page."""
    ids = set(_DOC_ID.findall(page))
    return [f"dangling documentation link #{a}" for a in sorted(set(_DOCLINK.findall(page)) - ids)]


def table(columns: list[str], rows: list[list], caption: str | None = None, raw_cols: set[int] | None = None,
          row_ids: list[str] | None = None, cls: str = "") -> str:
    """The only way to put a table on the page: sortable (click a header) and filterable (one input per column), inside a
    wrapper that scrolls sideways on a narrow screen. Cells are escaped, except columns in raw_cols (trusted HTML). row_ids:
    an id per row (a Documentation anchor: a More link can point at one row)."""
    raw_cols = raw_cols or set()
    names = "".join(f'<th scope="col">{esc(c)}</th>' for c in columns)
    filters = "".join(f'<th><input type="search" aria-label="Filter {esc(c)}" placeholder="filter"></th>' for c in columns)
    ids = row_ids or [""] * len(rows)
    body = "".join((f'<tr id="{esc(i)}">' if i else "<tr>") + "".join(f"<td>{c if j in raw_cols else esc(c)}</td>" for j, c in enumerate(r)) + "</tr>"
                   for i, r in zip(ids, rows))
    cap = f'<p class="tbl-cap">{esc(caption)}</p>' if caption else ""
    return (f'<div class="tblwrap{" " + cls if cls else ""}">{cap}<p class="count"></p><div class="tblscroll tbl-scroll"><table class="sf"><thead><tr class="names">{names}</tr>'
            f'<tr class="filters">{filters}</tr></thead><tbody>{body}</tbody></table></div></div>')


# ---- Documentation building blocks (the template's components: pills, bullets, numbered steps, callout, accordions, tabsets) ----
# Every section body is wrapped by docsec() between data-docsec="<anchor>" and <!--/docsec-->, so doc_text_problems() can check
# each section of the built page: short paragraphs, short list items, at least one list or table per section.

DOC_MAX_PARA_WORDS = 35
DOC_MAX_ITEM_WORDS = 20
DOC_START, DOC_END = "<!--vpt-docs-->", "<!--/vpt-docs-->"
_DOCSEC = re.compile(r'data-docsec="([^"]+)"[^>]*>(.*?)<!--/docsec-->', re.S)


def pill(text: str, kind: str = "check", title: str = "") -> str:
    t = f' title="{esc(title)}"' if title else ""
    return f'<span class="pill pill--{esc(kind)}"{t}>{esc(text)}</span>'


def bullets(items, cls: str = "bl") -> str:
    li = "".join(f"<li>{md_inline(x)}</li>" for x in items if x)
    return f'<ul class="{cls}">{li}</ul>' if li else ""


def steps(items) -> str:
    return '<ol class="steps">' + "".join(f"<li><span>{md_inline(x)}</span></li>" for x in items) + "</ol>"


def callout(inner_html: str, kind: str = "") -> str:
    return f'<div class="callout{" callout--" + kind if kind else ""}">{inner_html}</div>'


def docsec(anchor: str, body: str, tag: str = "div", cls: str = "docsec-body", el_id: str = "") -> str:
    i = f' id="{esc(el_id)}"' if el_id else ""
    return f'<{tag} class="{cls}"{i} data-docsec="{esc(anchor)}">{body}</{tag}><!--/docsec-->'


def details(anchor: str, label: str, body: str, meta: str = "", open_: bool = False) -> str:
    """A folded section (accordion) with a caret, its label and a small mono tag on the right; the body is a docsec."""
    m = f'<span class="s-meta">{esc(meta)}</span>' if meta else ""
    return (f'<details class="acc" id="{esc(anchor)}"{" open" if open_ else ""}><summary><span class="caret" aria-hidden="true">▶</span>'
            f'<span class="s-label">{esc(label)}</span>{m}</summary>' + docsec(anchor, body, cls="dd-body") + "</details>")


def section_head(title: str, note: str = "") -> str:
    return f'<div class="section-head"><h2>{esc(title)}</h2>' + (f'<p class="section-note">{md_inline(note)}</p>' if note else "") + "</div>"


def tabset(ts_id: str, tabs: list[tuple], cls: str = "", nav_extra: str = "") -> str:
    """Pill tabs: tabs = [(panel_id, label, body_html, extra)] where extra may hold "internal" (hidden until the detail tabs are
    shown) and "pill" (a small pill after the label). The first tab is selected. Panel ids are Documentation anchors."""
    nav, panels = [], []
    for i, t in enumerate(tabs):
        pid, label, body = t[0], t[1], t[2]
        extra = t[3] if len(t) > 3 else {}
        internal = ' data-internal="1"' if extra.get("internal") else ""
        sel = "true" if i == 0 else "false"
        nav.append(f'<button type="button" class="tab" role="tab" id="tab-{esc(pid)}" data-tab="{esc(pid)}" aria-controls="{esc(pid)}" '
                   f'aria-selected="{sel}"{"" if i == 0 else " tabindex=-1"}{internal}>{esc(label)}{extra.get("pill", "")}</button>')
        panels.append(f'<div class="tabpanel{" active" if i == 0 else ""}" role="tabpanel" id="{esc(pid)}" data-panel="{esc(pid)}" '
                      f'aria-labelledby="tab-{esc(pid)}"{internal}>{body}</div>')
    return (f'<div class="tabset{" " + cls if cls else ""}" id="{esc(ts_id)}"><div class="tabset-nav" role="tablist">' + "".join(nav) + "</div>" + nav_extra
            + "".join(panels) + "</div>")


def _doc_region(page: str) -> str | None:
    a, b = page.find(DOC_START), page.find(DOC_END)
    return page[a + len(DOC_START):b] if a >= 0 and b > a else None


def _visible(fragment: str) -> str:
    """The text a reader sees as running prose: tables (data) and popup bodies (attributes, checked by their own gate) left out."""
    f = re.sub(r"<table\b.*?</table>", " ", fragment, flags=re.S | re.I)
    return re.sub(r'\s(?:data-tip|title)="[^"]*"', "", f)


def doc_stats(page_or_docs: str) -> dict:
    """Numbers of the Documentation text: paragraphs and list items with their words, longest of each, sections."""
    region = _doc_region(page_or_docs)
    v = _visible(region if region is not None else page_or_docs)
    paras = [_words(x) for x in re.findall(r"<p\b[^>]*>(.*?)</p>", v, flags=re.S)]
    items = [_words(x) for x in re.findall(r"<li\b[^>]*>(.*?)</li>", v, flags=re.S)]
    secs = _DOCSEC.findall(v)
    return {"words": _words(v), "paragraphs": len(paras), "paragraph_words": sum(paras), "longest_paragraph": max(paras or [0]),
            "list_items": len(items), "list_item_words": sum(items), "longest_list_item": max(items or [0]), "sections": len(secs)}


def doc_text_problems(page: str, max_para: int = DOC_MAX_PARA_WORDS, max_item: int = DOC_MAX_ITEM_WORDS) -> list[str]:
    """Why the Documentation text is too verbose (empty = fine): a paragraph over max_para words, a list item over max_item words,
    a section (docsec) with no list or table. Could-not-tell is a problem too: no Documentation region, or no section in it."""
    region = _doc_region(page)
    if region is None:
        return ["no Documentation region (<!--vpt-docs--> markers) on the page: its text cannot be checked"]
    v = _visible(region)
    out = []
    for x in re.findall(r"<p\b[^>]*>(.*?)</p>", v, flags=re.S):
        if _words(x) > max_para:
            out.append(f"paragraph of {_words(x)} words (max {max_para}): {_html.unescape(_TAG.sub('', x))[:60]!r}")
    for x in re.findall(r"<li\b[^>]*>(.*?)</li>", v, flags=re.S):
        if _words(x) > max_item:
            out.append(f"list item of {_words(x)} words (max {max_item}): {_html.unescape(_TAG.sub('', x))[:60]!r}")
    secs = _DOCSEC.findall(region)
    if not secs:
        out.append("no Documentation section (data-docsec) found: nothing to check")
    for anchor, body in secs:
        if not re.search(r"<(?:ul|ol|table)\b", body):
            out.append(f"section {anchor} has no list or table")
    return out


class Docs:
    """The texts of presets/editor_docs.json with the popup helpers."""

    def __init__(self, texts: dict):
        self.t = texts

    @classmethod
    def load(cls, path: pathlib.Path = PRESET) -> "Docs":
        return cls(json.loads(pathlib.Path(path).read_text(encoding="utf-8")))

    def bl(self, key: str) -> list[str]:
        v = (self.t.get("tips") or {}).get(key, [])
        return [v] if isinstance(v, str) else list(v)

    @staticmethod
    def more(anchor: str) -> str:
        return more(anchor)

    @staticmethod
    def a_control(key: str) -> str:
        return "doc-control-" + slug(key)

    def control_tip(self, key: str) -> str:
        c = self.t["controls"][key]
        return popup(c["label"], self.bl("control." + key), self.more(self.a_control(key)))

    def print_cfg(self) -> dict:
        p = self.t["print"]
        w, h = p["paper_mm"]
        inner_w, inner_h = w - 2 * p["margin_mm"], h - 2 * p["margin_mm"] - 1       # 1 mm slack: never a second page
        return {"paper": p["paper"], "orientation": p["orientation"], "paper_mm": [w, h], "sheet_mm": [inner_w, inner_h],
                "title_mm": p["title_mm"], "legend_mm": p["legend_mm"], "draw_mm": [inner_w, inner_h - p["title_mm"] - p["legend_mm"]],
                "tips": {k: self.control_tip(k) for k in ("fit", "exit-print", "print")}}

    def print_css(self) -> str:
        """The print stylesheet, generated from editor_docs.json print."""
        c = self.print_cfg()
        return ("@media print { "
                f"@page {{ size: {c['paper']} {c['orientation']}; margin: {self.t['print']['margin_mm']}mm }} "
                "html, body { background: #ffffff !important; color: #000000 !important; margin: 0 !important; padding: 0 !important; } "
                "* { print-color-adjust: exact; -webkit-print-color-adjust: exact; } "
                "body.dwg-printing #dwg-printsheet { position: static; padding: 0; overflow: visible; } "
                "body.dwg-printing .ps-bar, body.dwg-printing .ps-notes, #tipbox { display: none !important; } "
                f"body.dwg-printing .ps-sheet {{ width: {c['sheet_mm'][0]}mm; height: {c['sheet_mm'][1]}mm; max-width: none; max-height: none; "
                "aspect-ratio: auto; margin: 0; border: none; box-shadow: none; } "
                f"body.dwg-printing .ps-title {{ height: {c['title_mm']}mm; }} "
                f"body.dwg-printing .ps-draw {{ height: {c['draw_mm'][1]}mm; flex: none; }} "
                f"body.dwg-printing .ps-legend {{ height: {c['legend_mm']}mm; }} "
                "}")
