"""The two editor pages (tools/build_editor.py, vpt/editor_page.py): built from the same code, deterministic, committed and up to
date, the page gates (short popups, no dangling Documentation link, theme tokens, no external resources) and the claude.ai
artifact contract. Every gate is falsified with a planted defect."""
import re

import pytest

import build_editor as be
from conftest import ROOT
from vpt import docs, editor_page


@pytest.fixture(scope="module")
def built():
    return be.build_all()


@pytest.mark.parametrize("variant", ["pages", "artifact"])
def test_gates_pass_and_files_are_current(built, variant):
    page = built[variant]
    assert be.gates(variant, page) == []
    assert be.OUTPUTS[variant].read_text(encoding="utf-8") == page, "run python3 tools/build_editor.py"


def test_deterministic(built):
    assert be.build_all() == built


def test_artifact_contract(built):
    a = built["artifact"]
    assert a.startswith("<title>Elektroplan Editor</title>") and len(a.encode()) <= 16 * 1024 * 1024
    assert not re.search(r"<(?:!doctype|/?html|/?head|/?body)[\s>]", a, re.I)
    for s in ('data-el="save"', 'data-el="save-in-place"', 'data-act="print"', 'data-pact="save', "showSaveFilePicker(", "showOpenFilePicker(",
              "window.print(", "a.download"):
        assert s not in a, s
    for s in ('data-el="copy"', 'data-pact="copy"', "navigator.clipboard.writeText", "FileReader", "addEventListener('paste'",
              "https://johngavin.github.io/vienna_planning_toolkit/"):
        assert s in a, s


def test_pages_version_has_save_and_print(built):
    p = built["pages"]
    assert p.startswith("<!doctype html>") and '<meta name="viewport"' in p
    for s in ('data-el="save"', 'data-el="save-in-place"', 'data-act="print"', 'data-pact="save"', "showSaveFilePicker(", "window.print("):
        assert s in p, s


@pytest.mark.parametrize("variant", ["pages", "artifact"])
def test_banners_and_sample(built, variant):
    p = built[variant]
    t = docs.Docs.load().t
    assert t["banners"]["synthetic"] in p and "UNVERIFIED" in p
    assert t["electrical"]["messages"]["example_banner_synthetic"] in p
    assert '"synthetic":true' in p


@pytest.mark.parametrize("plant, expect", [
    (lambda a: "<!doctype html>" + a, "does not start with <title>"),
    (lambda a: a + "<body>", "contains <body"),
    (lambda a: a + '<button data-act="print">', "Print view button"),
    (lambda a: a + "<script>if (confirm('x')) {}</script>", "confirm call"),
    (lambda a: a + "<script>window.showSaveFilePicker({})</script>", "file picker call"),
    (lambda a: a + "x" * (16 * 1024 * 1024), "16 MB"),
])
def test_artifact_gate_falsified(built, plant, expect):
    probs = be.artifact_problems(plant(built["artifact"]))
    assert any(expect in p for p in probs), probs


def test_external_resource_gate_falsified(built):
    a = built["artifact"]
    assert be.external_resources(a) == []
    assert be.external_resources(a + '<script src="https://cdn.example.com/x.js"></script>') == ["https://cdn.example.com/x.js"]
    assert be.external_resources(a + '<style>@import url("//evil.example/x.css");</style>') == ["//evil.example/x.css"]
    assert be.external_resources(a + "<script>fetch('https://api.example.com/x')</script>") == ["https://api.example.com/x"]
    assert be.external_resources('<link href="https://fonts.googleapis.com/css2?family=X" rel="stylesheet">') == []
    assert be.external_resources('<a href="https://example.com/">a link is not a load</a>') == []


def test_theme_gate_falsified(built):
    a = built["artifact"]
    assert be.theme_problems(a) == []
    assert be.theme_problems(a.replace(':root[data-theme="dark"]', ":root.x")) != []
    assert be.theme_problems(a.replace("@media (prefers-color-scheme: dark)", "@media (min-width: 1px)")) != []


def test_popup_and_doc_link_gates_falsified(built):
    a = built["artifact"]
    long_tip = docs.popup("T", ["one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen"])
    assert editor_page.problems(a + docs.tip("x", long_tip)) != []
    assert editor_page.problems(a + docs.tip("x", docs.popup("T", ["a", "b", "c", "d", "e"]))) != []
    assert editor_page.problems(a + '<a href="#doc-nowhere">x</a>') == ["dangling documentation link #doc-nowhere"]


def test_pages_only_regions_are_balanced_and_stripped():
    for name in ("core.js", "editor.js"):
        text = (ROOT / "editor" / name).read_text(encoding="utf-8")
        assert text.count("@pages-only-start") == text.count("@pages-only-end") > 0
        assert "@pages-only" not in editor_page._asset(name, "artifact")
