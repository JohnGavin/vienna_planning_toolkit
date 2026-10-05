#!/usr/bin/env python3
"""Write a layout of the electrical editor into a copy of its DXF, for the Elektroplaner: the whole drawing, plus the symbols as
blocks on Elektro layers (E_Licht, E_Schalter, ...), the links on E_Verbindungen and a note that the symbols are UNVERIFIED
(vpt/dxf_export.py; layer names and texts in presets/dxf_export.json).

Run it on your own computer (the browser page has no DXF writer):

    python3 tools/export_layout_dxf.py --dxf DRAWING.dxf --layout DRAWING__2OG.electrical.json [--plan DRAWING.plan.json] --out OUT.dxf
    python3 tools/export_layout_dxf.py --dxf DRAWING.dxf --plan DRAWING.plan.json --example complex --out OUT.dxf

--plan gives the storey's print scale (else presets/plan_extract.json render.scale_1_to) and is checked to be of the same DXF;
--example takes one of the plan's generated examples as the layout (for trying it out).

First it checks that the layout belongs to the drawing (its SHA-256 and storey); nothing is written unless it does. Then it
writes OUT and reads it back: every symbol there, on its layer, within position_tol_mm of its place, every link, the note, and
the source drawing unchanged.
Exit codes: 0 written and verified; 1 refused (another drawing or storey: nothing written) or the written file does not verify;
2 usage; 3 could not tell (an invalid layout, units unknown, an unreadable file: nothing written).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vpt import dxf_export, el_params, el_rules, el_symbols, plan_extract  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dxf", required=True, help="the drawing the layout was made on")
    ap.add_argument("--layout", help="the layout file (<drawing>__<storey>.electrical.json)")
    ap.add_argument("--plan", help="the drawing's plan file (tools/export_plan.py)")
    ap.add_argument("--example", choices=("simple", "complex"), help="use this generated example of the plan as the layout")
    ap.add_argument("--out", required=True, help="the DXF to write (never the source)")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    src, out = pathlib.Path(args.dxf), pathlib.Path(args.out)
    if bool(args.layout) == bool(args.example) or (args.example and not args.plan):
        print("usage: give --layout, or --example together with --plan", file=sys.stderr)
        return 2
    if not src.is_file():
        print(f"usage: no such file: {src}", file=sys.stderr)
        return 2
    if out.resolve() == src.resolve():
        print("usage: --out must not be the source drawing", file=sys.stderr)
        return 2
    try:
        import ezdxf
        plan = json.loads(pathlib.Path(args.plan).read_text(encoding="utf-8")) if args.plan else None
        if args.example:
            st = next((s for s in plan["storeys"] if s.get("examples")), None)
            if st is None or args.example not in st["examples"]:
                print(f"INDETERMINATE: the plan has no {args.example} example", file=sys.stderr)
                return 3
            layout, layout_name = st["examples"][args.example], f"{args.example} example of {pathlib.Path(args.plan).name}"
        else:
            layout, layout_name = json.loads(pathlib.Path(args.layout).read_text(encoding="utf-8")), pathlib.Path(args.layout).name
        sha = dxf_export.sha256_file(src)
        doc = ezdxf.readfile(src)
        pre, params, lib = dxf_export.load(), el_params.load(), el_symbols.load()
        probs = dxf_export.validate(pre, lib)
        if probs:
            print(f"INDETERMINATE: presets/dxf_export.json is broken: {probs[0]}", file=sys.stderr)
            return 3
        mm = plan_extract.mm_per_unit(doc)
        res = dxf_export.belongs(layout, dxf_sha=sha, dxf_storeys=dxf_export.storeys_of(doc), dxf_mm_per_unit=mm, plan=plan, lib=lib,
                                 rules=el_rules.load(params=params))
    except Exception as e:     # noqa: BLE001 - anything unreadable is could-not-tell (exit 3), never a silent pass
        print(f"INDETERMINATE: {type(e).__name__}: {e}", file=sys.stderr)
        return 3
    if res[0] != "match":
        print(f"{'REFUSED' if res[0] == 'different' else 'INDETERMINATE'}: {res[1]} (nothing written)", file=sys.stderr)
        return 1 if res[0] == "different" else 3
    storey = layout["drawing"]["storey"]
    n_src = sum(1 for _ in doc.modelspace())
    try:
        added = dxf_export.write(doc, layout, out=out, scale_1_to=dxf_export.default_scale(plan, storey), mm_per_unit=mm,
                                 layout_name=layout_name, seed=sha + json.dumps(layout, sort_keys=True), pre=pre, params=params, lib=lib)
    except Exception as e:     # noqa: BLE001 - a failure while writing is could-not-tell (exit 3), never a pass
        print(f"INDETERMINATE: could not write the layout: {type(e).__name__}: {e}", file=sys.stderr)
        return 3
    status, probs, nums = dxf_export.verify(out, layout, source_entities=n_src, mm_per_unit=mm, pre=pre, lib=lib)
    word = {"match": "PASS", "different": "FAIL", "could-not-tell": "INDETERMINATE"}[status]
    print(f"{word}: {out.name}: storey {storey}, {nums.get('inserts', 0)} symbol inserts {nums.get('per_code', {})}, {nums.get('links', 0)} link lines, "
          f"worst position {nums.get('worst_mm', 'n/a')} mm, layers {nums.get('layers', [])}, {nums.get('source_entities', 0)} source entities kept")
    for p in probs[:20]:
        print(f"  {p}")
    print(f"  note: {added['note']}")
    return {"PASS": 0, "FAIL": 1, "INDETERMINATE": 3}[word]


if __name__ == "__main__":
    sys.exit(main())
