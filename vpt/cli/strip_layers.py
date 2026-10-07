"""Make the electrical planning base of a DXF: delete the layers an electrical plan does not need (vpt/layer_strip.py).

Usage:
    vpt-strip-layers DRAWING.dxf [--outdir DIR] [--preset presets/layer_strip.json] [--extract-preset presets/plan_extract.json]

Writes DIR/<stem>[__<storey>]__electrical_base.dxf per storey and DIR/strip.json (default DIR: _scratch/strip). The original is
only read. Layers go by storey, status (Abbruch) and base name; a layer on neither list is kept and flagged. Each output is read
back and checked (X1-X8, see vpt/layer_strip.py), among them: the output's layers are exactly the kept set.
Exit codes: 0 PASS, 1 FAIL (a check is different), 2 usage (not a DXF, lists overlap), 3 INDETERMINATE (a check could not tell,
a layer is unclassified or has no storey, the DXF cannot be read, or the step crashed).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from vpt import ROOT, dwg_convert, layer_strip, plan


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dxf")
    ap.add_argument("--outdir", default=str(ROOT / "_scratch" / "strip"))
    ap.add_argument("--preset", default=str(layer_strip.PRESET))
    ap.add_argument("--extract-preset", default=str(plan.EXTRACT_PRESET))
    args = ap.parse_args(argv)
    src, outdir = pathlib.Path(args.dxf).resolve(), pathlib.Path(args.outdir).resolve()
    try:
        res = layer_strip.run(src, outdir, layer_strip.load_preset(args.preset),
                              json.loads(pathlib.Path(args.extract_preset).read_text(encoding="utf-8")))
    except layer_strip.UsageError as e:
        print(f"usage: {e}", file=sys.stderr)
        return 2
    except Exception as e:     # noqa: BLE001 - a crash is could-not-tell with its text in the record, exit 3 (never 1)
        dwg_convert.write_crash_result(outdir / "strip.json", {"test": "layer_strip", "input": src.name}, e)
        print(f"INDETERMINATE: step crashed: {type(e).__name__}: {e}", file=sys.stderr)
        return 3
    print(f"{res['status']}: {len(res['storeys'])} base(s) in {outdir.name}/")
    for s in res["storeys"]:
        e = s.get("entities") or {}
        print(f"  {s['key']:6s} {s['status']:14s} {s['output_dxf']}  entities {e.get('source')} -> {e.get('output')}")
    for c in res["checks"]:
        print(f"  {c['scope']:6s} {c['id']:3s} {c['status']:15s} {c['detail'][:110]}")
    return {"PASS": 0, "FAIL": 1, "INDETERMINATE": 3}[res["status"]]


if __name__ == "__main__":
    sys.exit(main())
