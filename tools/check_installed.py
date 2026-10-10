#!/usr/bin/env python3
"""Check the INSTALLED package (pip install ., or nix/vpt.nix) from outside the repo: vpt is imported from the install, not
from the source checkout; its data (presets, schemas, editor assets) is found inside the package; the entry point
vpt-export-plan writes the synthetic flat's plan file byte-identical to the committed one; the installed editor_page builds
site/index.html exactly; every other entry point answers --help.

Usage (run it where the package is installed, with any cwd outside the repo):
    nix-shell /path/to/repo/nix/vpt-shell.nix --run "python3 /path/to/repo/tools/check_installed.py /path/to/repo"
    python3 -m pip install /path/to/repo; python3 /path/to/repo/tools/check_installed.py /path/to/repo      (CI)

This script never puts the repo on sys.path. Exit codes: 0 PASS, 1 FAIL, 2 usage (the repo path has no sample).
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

SCRIPTS = ("vpt-export-plan", "vpt-export-layout-dxf", "vpt-dwg-convert", "vpt-strip-layers", "vpt-recognise-fittings")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or not (pathlib.Path(argv[0]) / "samples" / "synthetic_flat.dxf").is_file():
        print("usage: check_installed.py REPO (the checkout holding samples/synthetic_flat.dxf)", file=sys.stderr)
        return 2
    repo = pathlib.Path(argv[0]).resolve()
    sys.path[:] = [p for p in sys.path if pathlib.Path(p or ".").resolve() not in (repo, repo / "tools")]
    work = pathlib.Path(tempfile.mkdtemp(prefix="vpt_installed_"))
    os.chdir(work)
    fails: list[str] = []

    def ok(cond: bool, what: str) -> None:
        print(("ok   " if cond else "FAIL ") + what)
        if not cond:
            fails.append(what)
    try:
        import vpt
        from vpt import editor_page, plan_extract
    except ImportError as e:
        print(f"FAIL: vpt is not installed: {e}")
        return 1
    here = pathlib.Path(vpt.__file__).resolve()
    ok(repo not in here.parents, f"vpt imported from the install, not the checkout: {here.parent}")
    ok(vpt.INSTALLED and pathlib.Path(vpt.PRESETS).resolve().parent == here.parent, f"data found inside the package: {vpt.PRESETS}")
    for d, pat in ((vpt.PRESETS, "*.json"), (vpt.SCHEMAS, "*.json"), (vpt.EDITOR, "*.js")):
        ok(sorted(p.name for p in d.glob(pat)) == sorted(p.name for p in (repo / d.name).glob(pat)), f"{d.name}/{pat} complete")
    ok(bool(plan_extract.options(json.loads((vpt.PRESETS / "plan_extract.json").read_text(encoding="utf-8")))), "plan_extract preset readable")
    exe = shutil.which("vpt-export-plan")
    ok(bool(exe), f"entry point vpt-export-plan on PATH: {exe}")
    if exe:
        out = work / "flat.plan.json"
        r = subprocess.run([exe, str(repo / "samples/synthetic_flat.dxf"), "--output", str(out), "--synthetic"], capture_output=True, text=True)
        ok(r.returncode == 0, f"vpt-export-plan exit {r.returncode}: {(r.stdout or r.stderr).splitlines()[:1]}")
        ok(out.is_file() and out.read_bytes() == (repo / "samples/synthetic_flat.plan.json").read_bytes(),
           "plan file byte-identical to samples/synthetic_flat.plan.json")
    plan = json.loads((repo / "samples/synthetic_flat.plan.json").read_text(encoding="utf-8"))
    ok(editor_page.build(plan) == (repo / "site/index.html").read_text(encoding="utf-8"), "installed editor_page builds site/index.html exactly")
    for tool in SCRIPTS[1:]:
        h = subprocess.run([tool, "--help"], capture_output=True, text=True) if shutil.which(tool) else None
        ok(h is not None and h.returncode == 0 and "usage" in h.stdout, f"{tool} --help")
    print("PASS" if not fails else f"FAIL: {len(fails)} check(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
