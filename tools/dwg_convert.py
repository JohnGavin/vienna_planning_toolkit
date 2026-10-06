#!/usr/bin/env python3
"""DWG -> DXF conversion with a completeness check of the written file (vpt/dwg_convert.py, presets/dwg_convert.json).

Usage:
    python3 tools/dwg_convert.py INPUT.dwg|INPUT.dxf [--outdir DIR] [--preset presets/dwg_convert.json]

Writes DIR/<stem>.dxf (for a DWG), DIR/<stem>.convert.log and DIR/<stem>.convert.json. A DXF is accepted as it is. The
converter is the ODA File Converter when installed, else LibreDWG 0.14 from nix/libredwg.nix (see the preset).
Exit codes: 0 PASS, 1 FAIL (the DXF is cut off), 2 usage, 3 INDETERMINATE (could not confirm, or the step crashed).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vpt import dwg_convert  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("input")
    ap.add_argument("--outdir", default=None, help="default: _scratch/<today>_dwg_convert")
    ap.add_argument("--preset", default=str(dwg_convert.PRESET))
    args = ap.parse_args(argv)
    src = pathlib.Path(args.input).resolve()
    outdir = pathlib.Path(args.outdir).resolve() if args.outdir else dwg_convert.default_outdir()
    try:
        rec = dwg_convert.run(src, outdir, json.loads(pathlib.Path(args.preset).read_text(encoding="utf-8")))
    except dwg_convert.UsageError as e:
        print(f"usage: {e}", file=sys.stderr)
        return 2
    except Exception as e:     # noqa: BLE001 - a crash is could-not-tell with its text in the record, exit 3 (never 1)
        dwg_convert.write_crash_result(outdir / f"{src.stem}.convert.json", {"test": "dwg_convert", "input": src.name}, e)
        print(f"INDETERMINATE: step crashed: {type(e).__name__}: {e}", file=sys.stderr)
        return 3
    print(f"{rec['status']}: {rec.get('version')} ({rec.get('release')}) -> {rec['dxf']}  entities={rec.get('entities_total')}"
          + "".join(f"\n  - cut off: {f}" for f in rec["failures"]) + "".join(f"\n  - could not tell: {u}" for u in rec["unknowns"]))
    return {"PASS": 0, "FAIL": 1, "INDETERMINATE": 3}[rec["status"]]


if __name__ == "__main__":
    sys.exit(main())
