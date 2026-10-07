#!/usr/bin/env python3
"""Write a layout of the electrical editor into a copy of its DXF, for the Elektroplaner.

A thin wrapper around vpt/cli/export_layout_dxf.py (installed: the command `vpt-export-layout-dxf`); see there for usage and exit codes."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vpt.cli.export_layout_dxf import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
