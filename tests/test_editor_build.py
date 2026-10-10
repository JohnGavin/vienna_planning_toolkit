"""The editor page (tools/build_editor.py, vpt/editor_page.py): deterministic, committed and up to date, the page gates (short
popups, no dangling Documentation link, theme tokens, no external resources, a whole HTML document). Every gate is falsified with
a planted defect."""
import re

import pytest

import build_editor as be
from conftest import ROOT
from vpt import docs, editor_page


@pytest.fixture(scope="module")
def built():
    return be.build()


def test_gates_pass_and_file_is_current(built):
    assert be.gates(built) == []
    assert be.OUTPUT.read_text(encoding="utf-8") == built, "run python3 tools/build_editor.py"


def test_deterministic(built):
    assert be.build() == built


def test_page_has_save_print_and_copy(built):
    assert built.startswith("<!doctype html>") and '<meta name="viewport"' in built
    for s in ('data-el="save"', 'data-el="save-in-place"', 'data-act="print"', 'data-pact="save"', "showSaveFilePicker(", "window.print(",
              'data-el="copy"', 'data-pact="copy"', "navigator.clipboard.writeText", "FileReader", "addEventListener('paste'"):
        assert s in built, s


def test_whole_document_gate_falsified(built):
    assert "the page is not a whole HTML document" in be.gates(built[len("<!doctype html>"):])


def test_banners_and_sample(built):
    t = docs.Docs.load().t
    assert t["banners"]["synthetic"] in built and "UNVERIFIED" in built
    assert t["electrical"]["messages"]["example_banner_synthetic"] in built
    assert '"synthetic":true' in built


def test_external_resource_gate_falsified(built):
    a = built
    assert be.external_resources(a) == []
    assert be.external_resources(a + '<script src="https://cdn.example.com/x.js"></script>') == ["https://cdn.example.com/x.js"]
    assert be.external_resources(a + '<style>@import url("//evil.example/x.css");</style>') == ["//evil.example/x.css"]
    assert be.external_resources(a + "<script>fetch('https://api.example.com/x')</script>") == ["https://api.example.com/x"]
    assert be.external_resources('<link href="https://fonts.googleapis.com/css2?family=X" rel="stylesheet">') == []
    assert be.external_resources('<a href="https://example.com/">a link is not a load</a>') == []


def test_theme_gate_falsified(built):
    a = built
    assert be.theme_problems(a) == []
    assert be.theme_problems(a.replace(':root[data-theme="dark"]', ":root.x")) != []
    assert be.theme_problems(a.replace("@media (prefers-color-scheme: dark)", "@media (min-width: 1px)")) != []


def test_popup_and_doc_link_gates_falsified(built):
    a = built
    long_tip = docs.popup("T", ["one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen"])
    assert editor_page.problems(a + docs.tip("x", long_tip)) != []
    assert editor_page.problems(a + docs.tip("x", docs.popup("T", ["a", "b", "c", "d", "e"]))) != []
    assert editor_page.problems(a + '<a href="#doc-nowhere">x</a>') == ["dangling documentation link #doc-nowhere"]


def test_no_pages_only_markers_left():
    for name in ("core.js", "editor.js"):
        assert "@pages-only" not in (ROOT / "editor" / name).read_text(encoding="utf-8")


def test_parameters_is_a_page_tab(built):
    """Parameters sits in the page tab row between Editor and Documentation, not inside the Editor pane (it used to push the storey
    out of view). Planted defect: the panel put back into the Editor pane must fail the same measure."""
    def structure(page):
        tabs = re.findall(r'role="tab" id="vpt-tab-(\w+)"', page)
        pane = lambda n: re.search(rf'<section[^>]*id="vpt-pane-{n}".*?</section>', page, re.S).group(0)
        return tabs, 'class="el-params"' in pane("params"), 'class="el-params"' in pane("editor")
    tabs, in_params, in_editor = structure(built)
    assert tabs == ["editor", "params", "docs"] and in_params and not in_editor
    broken = built.replace('<div class="el-storey-tabs"', '<div class="el-params"></div><div class="el-storey-tabs"', 1)
    assert structure(broken)[2], "the planted defect is not seen"
