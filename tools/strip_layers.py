#!/usr/bin/env python3
"""Make the electrical planning base of a DXF: delete the layers an electrical plan does not need (vpt/layer_strip.py).

A thin wrapper around vpt/cli/strip_layers.py (installed: the command `vpt-strip-layers`); see there for usage and exit codes."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from vpt.cli.strip_layers import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
