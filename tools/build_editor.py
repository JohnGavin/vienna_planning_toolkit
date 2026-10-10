#!/usr/bin/env python3
"""Build the electrical editor page from one code base (vpt/editor_page.py, editor/*.css|js, presets/, schema/):

    site/index.html     the GitHub Pages page (a whole HTML document: save, save to file, print, copy)

It embeds the synthetic flat's plan (samples/synthetic_flat.plan.json, from tools/export_plan.py) as the default plan.
The output is deterministic (no timestamps): the same inputs give a byte-identical page.

Usage:
    python3 tools/build_editor.py [--plan samples/synthetic_flat.plan.json] [--check]

--check builds into memory and compares with the committed file: exit 1 when it is out of date (CI). Exit codes: 0 built
(or up to date) and the page gates pass (popups short, no dangling Documentation link, theme tokens, no external resources); 1 a gate failed or
the file is out of date; 3 the inputs could not be read.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vpt import editor_page  # noqa: E402

OUTPUT = ROOT / "site" / "index.html"
PLAN = ROOT / "samples" / "synthetic_flat.plan.json"
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


def theme_problems(page: str) -> list[str]:
    out = []
    if not re.search(r"@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme=\"light\"\]\)", page):
        out.append("no dark-mode token block guarded by :root:not([data-theme=\"light\"])")
    if ':root[data-theme="dark"]' not in page:
        out.append('no :root[data-theme="dark"] token block')
    if not re.search(r"\bbody \{[^}]*background: var\(--bg\)", page):
        out.append("body has no explicit token background")
    return out


def gates(page: str) -> list[str]:
    probs = editor_page.problems(page) + external_resources(page) + theme_problems(page)
    if not page.startswith("<!doctype html>"):
        probs.append("the page is not a whole HTML document")
    return probs


def build(plan_path: pathlib.Path = PLAN) -> str:
    return editor_page.build(editor_page.load_plan(plan_path))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--plan", default=str(PLAN))
    ap.add_argument("--check", action="store_true", help="compare with the committed files instead of writing")
    args = ap.parse_args(argv)
    try:
        page = build(pathlib.Path(args.plan))
    except (OSError, ValueError) as e:
        print(f"INDETERMINATE: {type(e).__name__}: {e}", file=sys.stderr)
        return 3
    status = 0
    probs = gates(page)
    if probs:
        status = 1
        print(f"FAIL: {len(probs)} problem(s): " + "; ".join(probs[:10]), file=sys.stderr)
    size = len(page.encode("utf-8"))
    if args.check:
        old = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else None
        if old != page:
            status = 1
            print(f"FAIL: {OUTPUT.relative_to(ROOT)} is out of date: run python3 tools/build_editor.py", file=sys.stderr)
        else:
            print(f"ok: {OUTPUT.relative_to(ROOT)} up to date ({size} bytes)")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(page, encoding="utf-8")
        print(f"{'built' if not probs else 'built WITH PROBLEMS'}: {OUTPUT.relative_to(ROOT)} ({size} bytes)")
    return status


if __name__ == "__main__":
    sys.exit(main())
