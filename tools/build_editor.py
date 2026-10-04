#!/usr/bin/env python3
"""Build the electrical editor's two pages from one code base (vpt/editor_page.py, editor/*.css|js, presets/, schema/):

    site/index.html                     the GitHub Pages version (a whole HTML document: save, save to file, print)
    artifact/electrical_planner.html    the shareable demo (claude.ai artifact: page content only, copy/paste instead)

Both embed the synthetic flat's plan (samples/synthetic_flat.plan.json, from tools/export_plan.py) as the default plan.
The output is deterministic (no timestamps): the same inputs give byte-identical pages.

Usage:
    python3 tools/build_editor.py [--plan samples/synthetic_flat.plan.json] [--check]

--check builds into memory and compares with the committed files: exit 1 when they are out of date (CI). Exit codes: 0 built
(or up to date) and the page gates pass (popups short, no dangling Documentation link, artifact contract); 1 a gate failed or
the files are out of date; 3 the inputs could not be read.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vpt import editor_page  # noqa: E402

OUTPUTS = {"pages": ROOT / "site" / "index.html", "artifact": ROOT / "artifact" / "electrical_planner.html"}
PLAN = ROOT / "samples" / "synthetic_flat.plan.json"
MAX_BYTES = 16 * 1024 * 1024
ALLOWED_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")
_RES = re.compile(r"""(?:\b(?:src|href|action|data|poster|srcset|formaction)\s*=\s*["']?\s*|url\(\s*["']?|@import\s+["']?|fetch\(\s*["'])((?:https?:)?//[^"'\s)>]+)""", re.I)
_LINK_A = re.compile(r"""<a\b[^>]*\bhref=["'](https?://[^"']+)["']""", re.I)


def external_resources(page: str) -> list[str]:
    """URLs the page would LOAD (src/href of resources, CSS url()/@import, fetch) outside the allowed hosts. A plain <a href>
    link to another site is navigation, not a load, and is not counted."""
    links = set(_LINK_A.findall(page))
    out = []
    for m in _RES.finditer(page):
        url = m.group(1)
        if url in links:
            continue
        host = re.sub(r"^(?:https?:)?//", "", url).split("/", 1)[0].lower()
        if host not in ALLOWED_HOSTS:
            out.append(url)
    return sorted(set(out))


def artifact_problems(page: str) -> list[str]:
    """The claude.ai artifact contract, as far as it can be read from the text."""
    out = []
    if not page.startswith("<title>"):
        out.append("does not start with <title>")
    if "<title>" not in page[:8192]:
        out.append("no <title> within the first 8 KB")
    for tag in re.findall(r"<(?:!doctype|/?html|/?head|/?body)(?=[\s>])", page, re.I):
        out.append(f"contains {tag}")
    size = len(page.encode("utf-8"))
    if size > MAX_BYTES:
        out.append(f"{size} bytes > 16 MB")
    for pat, what in ((r'data-act="print"', "a Print view button"), (r'data-el="save"', "a Save layout button"),
                      (r'data-el="save-in-place"', "a Save to file button"), (r'data-pact="save', "a Save parameters button"),
                      (r"\bconfirm\s*\(", "a confirm call"), (r"\balert\s*\(", "an alert call"), (r"\bprompt\s*\(", "a prompt call"),
                      (r"\bshow(?:Save|Open)FilePicker\s*\(", "a file picker call")):
        if re.search(pat, page):
            out.append(f"has {what} (inert in an artifact)")
    return out


def theme_problems(page: str) -> list[str]:
    out = []
    if not re.search(r"@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme=\"light\"\]\)", page):
        out.append("no dark-mode token block guarded by :root:not([data-theme=\"light\"])")
    if ':root[data-theme="dark"]' not in page:
        out.append('no :root[data-theme="dark"] token block')
    if not re.search(r"\bbody \{[^}]*background: var\(--bg\)", page):
        out.append("body has no explicit token background")
    return out


def gates(variant: str, page: str) -> list[str]:
    probs = editor_page.problems(page) + external_resources(page) + theme_problems(page)
    if variant == "artifact":
        probs += artifact_problems(page)
    elif not page.startswith("<!doctype html>"):
        probs.append("the Pages version is not a whole HTML document")
    return probs


def build_all(plan_path: pathlib.Path = PLAN) -> dict[str, str]:
    plan = editor_page.load_plan(plan_path)
    return {v: editor_page.build(plan, v) for v in OUTPUTS}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--plan", default=str(PLAN))
    ap.add_argument("--check", action="store_true", help="compare with the committed files instead of writing")
    args = ap.parse_args(argv)
    try:
        pages = build_all(pathlib.Path(args.plan))
    except (OSError, ValueError) as e:
        print(f"INDETERMINATE: {type(e).__name__}: {e}", file=sys.stderr)
        return 3
    status = 0
    for v, page in pages.items():
        probs = gates(v, page)
        if probs:
            status = 1
            print(f"FAIL {v}: {len(probs)} problem(s): " + "; ".join(probs[:10]), file=sys.stderr)
        out = OUTPUTS[v]
        if args.check:
            old = out.read_text(encoding="utf-8") if out.is_file() else None
            if old != page:
                status = 1
                print(f"FAIL {v}: {out.relative_to(ROOT)} is out of date: run python3 tools/build_editor.py", file=sys.stderr)
            else:
                print(f"ok {v}: {out.relative_to(ROOT)} up to date ({len(page.encode('utf-8'))} bytes)")
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(page, encoding="utf-8")
            print(f"{'built' if not probs else 'built WITH PROBLEMS'} {v}: {out.relative_to(ROOT)} ({len(page.encode('utf-8'))} bytes)")
    return status


if __name__ == "__main__":
    sys.exit(main())
