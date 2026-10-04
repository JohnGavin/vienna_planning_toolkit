"""Popups, tables and Documentation (vpt/docs.py), and the texts preset (presets/editor_docs.json): every popup is short, the
Documentation is short bullets in tabs (a measurable limit, falsified), every old #doc-... anchor still resolves, every How-to part
names existing sections, every variant-specific How-to part has both variants, the Parameters panel texts cover every section."""
import re

import pytest

import build_editor as be
from conftest import ROOT
from vpt import docs, editor_page, el_params


@pytest.fixture(scope="module")
def built():
    return be.build_all()


def test_popup_gate_counts_bullets_and_words():
    ok = docs.popup("Title", ["**Bold** short bullet.", "Another one."], docs.more("doc-x"))
    assert docs.popup_problems(ok) == []
    assert docs.popup_problems(docs.popup("T", ["a"] * 5)) == ["5 bullets (max 4)"]
    assert docs.popup_problems(docs.popup("T", [" ".join(["w"] * 15)])) == ["bullet of 15 words (max 14)"]
    assert docs.popup_problems('<p class="tip-h"><b>T</b></p><p>one</p><p>two</p>') == ["2 paragraphs (max 1 besides title and More)"]


def test_every_tip_in_the_preset_is_short():
    d = docs.Docs.load()
    for key, items in d.t["tips"].items():
        assert docs.popup_problems(docs.popup(key, items)) == [], key


def test_howto_parts_reference_existing_sections():
    d = docs.Docs.load()
    for p in d.t["howto"]["parts"]:
        assert all(k in d.t["electrical"] for k in p["details"]), p["key"]
        assert "steps" in p or ("steps_pages" in p and "steps_artifact" in p), p["key"]


def test_sections_are_bullets_not_prose():
    """Every section text of the preset is a list of bullets (the old one-paragraph "text" is gone)."""
    d = docs.Docs.load()
    for k, c in d.t["electrical"].items():
        if k == "messages":
            continue
        assert "text" not in c and c["bullets"], k
        assert all(len(b.split()) <= docs.DOC_MAX_ITEM_WORDS for b in c["bullets"]), k
    for k, c in d.t["controls"].items():
        assert "text" not in c and c["does"], k


def test_doc_links_and_slug():
    assert docs.check_doc_links('<a href="#doc-a">x</a><section id="doc-a"></section>') == []
    assert docs.check_doc_links('<span data-tip="&lt;a href=&quot;#doc-b&quot;&gt;">') == ["dangling documentation link #doc-b"]
    assert docs.slug("Küche/Geräte") == "kueche-geraete" and editor_page.anchor("hint_h1") == "doc-el-hint-h1"


def test_table_is_sortable_filterable_and_escaped():
    t = docs.table(["A", "B"], [["<x>", 1]], row_ids=["doc-r1"])
    assert 'class="sf"' in t and 'type="search"' in t and "&lt;x&gt;" in t and "tblscroll" in t and '<tr id="doc-r1">' in t


@pytest.mark.parametrize("variant", ["pages", "artifact"])
def test_documentation_is_short(built, variant):
    page = built[variant]
    assert docs.doc_text_problems(page) == []
    st = docs.doc_stats(page)
    # bullets, not prose: list items outnumber paragraphs many times over, and no paragraph or item is over the limit
    assert st["sections"] >= 40 and st["list_items"] > 5 * st["paragraphs"]
    assert st["longest_paragraph"] <= docs.DOC_MAX_PARA_WORDS and st["longest_list_item"] <= docs.DOC_MAX_ITEM_WORDS


@pytest.mark.parametrize("plant, expect", [
    (lambda r: r.replace("</div><!--/docsec-->", "<p>" + "word " * 36 + "</p></div><!--/docsec-->", 1), "paragraph of 36 words"),
    (lambda r: r.replace("</div><!--/docsec-->", "<ul><li>" + "word " * 21 + "</li></ul></div><!--/docsec-->", 1), "list item of 21 words"),
    (lambda r: r.replace(docs.DOC_END, docs.docsec("doc-planted", "<p>only prose</p>") + docs.DOC_END), "section doc-planted has no list or table"),
    (lambda r: r.replace(docs.DOC_START, ""), "no Documentation region"),
    (lambda r: re.sub(r'data-docsec="[^"]+"', "", r), "no Documentation section"),
])
def test_documentation_gate_falsified(built, plant, expect):
    probs = docs.doc_text_problems(plant(built["pages"]))
    assert any(expect in p for p in probs), probs
    assert editor_page.problems(plant(built["pages"])) != []


def test_documentation_gate_on_the_old_page_fails():
    """The previous Documentation (one long page of paragraphs) would not pass: its longest paragraph had 194 words."""
    old = '<!--vpt-docs--><div class="docs"><section class="docsec" data-docsec="doc-old"><p>' + "word " * 194 + "</p></section><!--/docsec--></div><!--/vpt-docs-->"
    probs = docs.doc_text_problems(old)
    assert any("paragraph of 194 words" in p for p in probs) and any("no list or table" in p for p in probs)


@pytest.mark.parametrize("variant", ["pages", "artifact"])
def test_every_old_anchor_still_resolves(built, variant):
    ids = set(re.findall(r'\bid="(doc-[a-z0-9-]+)"', built[variant]))
    old = (ROOT / "tests" / "doc_anchors.txt").read_text(encoding="utf-8").split()
    assert len(old) > 80
    assert sorted(set(old) - ids) == []
    assert docs.check_doc_links(built[variant]) == []


@pytest.mark.parametrize("variant", ["pages", "artifact"])
def test_no_at_once_wording(built, variant):
    """The Parameters panel and the Documentation say Live / Needs re-export, never 'at once' / 'on export'."""
    page = built[variant]
    assert not re.search(r"\bat once\b", page, re.I) and "'on export'" not in page


def test_parameter_panel_tabs_cover_every_section_once():
    d = docs.Docs.load()
    p = el_params.load()
    named = [s for t in d.t["params_panel"]["tabs"] for s in t.get("sections", [])]
    assert sorted(named) == sorted(p["sections"]) and len(named) == len(set(named))
    rules = sorted(t["rules"] for t in d.t["params_panel"]["tabs"] if "rules" in t)
    assert rules == ["export", "live"]
    # the "live" rules tab is not empty, and every section outside LIVE_SECTIONS is shown as needing a re-export
    assert set(el_params.LIVE_RULES) <= set(p["rules"]["definitions"])
    assert set(p["sections"]) - set(el_params.LIVE_SECTIONS) == {"examples"}
