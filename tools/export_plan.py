#!/usr/bin/env python3
"""Export a DXF drawing as a plan file for the electrical editor (<name>.plan.json, schema schema/plan.schema.json).

Run it on your own computer: the plan file is written next to where you ask, and the editor page reads it in the browser
(Open plan). Nothing is uploaded anywhere.

Usage:
    python3 tools/export_plan.py DRAWING.dxf [--output NAME.plan.json] [--preset presets/plan_extract.json] [--synthetic]

--synthetic marks the plan as the toolkit's synthetic sample (the page then says so); never use it for a real drawing.
Exit codes: 0 written and the rooms/doors/walls checks PASS; 1 written but a check FAILED; 3 written but a check could not
tell (INDETERMINATE), or the drawing could not be read (nothing written); 2 usage.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vpt import plan  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dxf")
    ap.add_argument("--output", default=None, help="default: <dxf name without suffix>.plan.json next to the DXF")
    ap.add_argument("--preset", default=str(plan.EXTRACT_PRESET))
    ap.add_argument("--synthetic", action="store_true", help="mark as the toolkit's synthetic sample")
    args = ap.parse_args(argv)
    src = pathlib.Path(args.dxf)
    if not src.is_file():
        print(f"usage: no such file: {src}", file=sys.stderr)
        return 2
    out = pathlib.Path(args.output) if args.output else src.with_suffix(".plan.json")
    try:
        pre = json.loads(pathlib.Path(args.preset).read_text(encoding="utf-8"))
        p = plan.export(src, synthetic=args.synthetic, pre=pre)
    except Exception as e:     # noqa: BLE001 - any failure to read is could-not-tell (exit 3), never a silent pass
        print(f"INDETERMINATE: {type(e).__name__}: {e}", file=sys.stderr)
        return 3
    text = plan.dumps(p)
    res = plan.check_text(text)
    if res[0] != "match":
        print(f"INDETERMINATE: the written plan does not check: {res[1]}", file=sys.stderr)
        return 3
    out.write_text(text, encoding="utf-8")
    ex = p["extract"]
    print(f"{ex['status']}: {out.name} ({len(text.encode('utf-8'))} bytes): {res[1]}")
    for s in p["storeys"]:
        for c in s["checks"]:
            print(f"  {s['key']} {c['id']:3s} {c['status']:15s} {c['detail'][:120]}")
    return {"PASS": 0, "FAIL": 1, "INDETERMINATE": 3}[ex["status"]]


if __name__ == "__main__":
    sys.exit(main())
