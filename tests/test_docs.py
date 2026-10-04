"""Popups, tables and Documentation links (vpt/docs.py), and the texts preset (presets/editor_docs.json): every popup is short,
every How-to part names existing sections, every variant-specific How-to part has both variants."""
from vpt import docs, editor_page


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


def test_doc_links_and_slug():
    assert docs.check_doc_links('<a href="#doc-a">x</a><section id="doc-a"></section>') == []
    assert docs.check_doc_links('<span data-tip="&lt;a href=&quot;#doc-b&quot;&gt;">') == ["dangling documentation link #doc-b"]
    assert docs.slug("Küche/Geräte") == "kueche-geraete" and editor_page.anchor("hint_h1") == "doc-el-hint-h1"


def test_table_is_sortable_filterable_and_escaped():
    t = docs.table(["A", "B"], [["<x>", 1]])
    assert 'class="sf"' in t and 'type="search"' in t and "&lt;x&gt;" in t and "tblscroll" in t
