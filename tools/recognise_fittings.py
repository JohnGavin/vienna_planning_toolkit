#!/usr/bin/env python3
"""Recognise fittings by shape in a DXF and assign each to a room (vpt/fittings.py; settings in presets/fittings.json).

Usage:
    python3 tools/recognise_fittings.py DRAWING.dxf [--output NAME.fittings.json] [--preset presets/fittings.json]
                                                    [--extract-preset presets/plan_extract.json]

Per storey: symbols with their type (or 'unrecognised' / 'ambiguous'), their room, counts per type, and the checks F1-F3 (see
vpt/fittings.py). The DXF is only read; the JSON holds sizes, positions in drawing units and rooms by id, never drawing text.
Exit codes: 0 PASS, 1 FAIL (a wet room without a fitting), 2 usage (file missing, preset broken), 3 INDETERMINATE (an unrecognised
or ambiguous symbol, a fitting in no room, unknown units, the DXF cannot be read, or the step crashed).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vpt import fittings, plan  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dxf")
    ap.add_argument("--output", default=None, help="default: <dxf name without suffix>.fittings.json next to the DXF")
    ap.add_argument("--preset", default=str(fittings.PRESET))
    ap.add_argument("--extract-preset", default=str(plan.EXTRACT_PRESET))
    args = ap.parse_args(argv)
    src = pathlib.Path(args.dxf)
    if not src.is_file():
        print(f"usage: no such file: {src}", file=sys.stderr)
        return 2
    try:
        fp = fittings.load_preset(args.preset)
        pre = json.loads(pathlib.Path(args.extract_preset).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"usage: a preset cannot be read: {e}", file=sys.stderr)
        return 2
    if problems := fittings.validate(fp):
        print("usage: the fittings preset is broken: " + "; ".join(problems), file=sys.stderr)
        return 2
    out = pathlib.Path(args.output) if args.output else src.with_suffix(".fittings.json")
    try:
        import ezdxf
        doc = ezdxf.readfile(src)
        res = fittings.run(doc, pre, fp)
    except Exception as e:     # noqa: BLE001 - any failure to read is could-not-tell (exit 3), never a silent pass
        print(f"INDETERMINATE: {type(e).__name__}: {e}", file=sys.stderr)
        return 3
    res = {"schema": "vpt_fittings", "drawing": src.name, **res}
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{res['status']}: {out.name}")
    for s in res["storeys"]:
        print(f"  {s['key']}: " + (", ".join(f"{n} {t}" for t, n in s["counts"].items()) or "no fitting recognised"))
        for c in s["checks"]:
            print(f"  {s['key']} {c['id']:3s} {c['status']:15s} {c['detail'][:110]}")
    for u in res["unknowns"]:
        print(f"  could not tell: {u}")
    return {"PASS": 0, "FAIL": 1, "INDETERMINATE": 3}[res["status"]]


if __name__ == "__main__":
    sys.exit(main())
