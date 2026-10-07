#!/usr/bin/env python3
"""DWG -> DXF conversion with a completeness check of the written file (vpt/dwg_convert.py, presets/dwg_convert.json).

A thin wrapper around vpt/cli/dwg_convert.py (installed: the command `vpt-dwg-convert`); see there for usage and exit codes."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vpt.cli.dwg_convert import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
