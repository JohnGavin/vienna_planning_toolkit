#!/usr/bin/env python3
"""Recognise fittings by shape in a DXF and assign each to a room (vpt/fittings.py; settings in presets/fittings.json).

A thin wrapper around vpt/cli/recognise_fittings.py (installed: the command `vpt-recognise-fittings`); see there for usage and exit codes."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vpt.cli.recognise_fittings import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
