#!/usr/bin/env python3
"""Export a DXF drawing as a plan file for the electrical editor (<name>.plan.json, schema schema/plan.schema.json).

A thin wrapper around vpt/cli/export_plan.py (installed: the command `vpt-export-plan`); see there for usage and exit codes."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vpt.cli.export_plan import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
