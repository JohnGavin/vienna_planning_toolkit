"""vienna_planning_toolkit: generic tools for Vienna-style building plans.

Modules:
    dxf_svg        DXF -> SVG with one group per DXF layer (deterministic hatch seeding)
    plan_extract   rooms, doors and walls of each storey of a DXF
    plan           the plan file (<name>.plan.json) the electrical editor opens
    el_symbols     the electrical symbol library (presets/el_symbols_at.json)
    el_layout      the layout file of the editor and the JSON Schema subset validator
    el_params      the editor's parameter file (presets/el_parameters.json)
    el_rules       placement rules and suggestions
    el_links       switch-light links, switching groups, the switch-type proposal, layout hints
    el_examples    generated example layouts (simple, complex)
    docs           popups (short bullets, with a gate), sortable tables, Documentation sections
    editor_page    the HTML of the editor page
    dwg_convert    DWG -> DXF (ODA File Converter or LibreDWG) and the completeness check of the DXF
    layer_strip    the electrical base: layers deleted by storey, status and base name, with read-back checks
    dxf_symbols    shape features and rules: symbols from plain DXF geometry
    fittings       fittings recognised by shape and assigned to rooms
    cli            the command-line tools (console scripts vpt-export-plan, vpt-export-layout-dxf, vpt-dwg-convert,
                   vpt-strip-layers, vpt-recognise-fittings; tools/*.py are thin wrappers around them)

Data (presets/, schema/, editor/, nix/libredwg.nix): found with importlib.resources. An installed package carries them
inside the package (pyproject.toml maps the repo's top-level folders there); a source checkout reads them from the repo
root, their one home.
"""
from __future__ import annotations

import importlib.resources
import pathlib

__version__ = "0.2.0"


def _data_root() -> tuple[pathlib.Path, bool]:
    """(the folder holding presets/, schema/, editor/, nix/; True when that is the installed package)."""
    pkg = importlib.resources.files(__name__)
    if pkg.joinpath("presets").is_dir():
        return pathlib.Path(str(pkg)), True
    return pathlib.Path(str(pkg)).resolve().parent, False


DATA, INSTALLED = _data_root()
ROOT = DATA if not INSTALLED else pathlib.Path.cwd()    # where relative work folders (_scratch/) go: the repo, else the cwd
PRESETS = DATA / "presets"
SCHEMAS = DATA / "schema"
EDITOR = DATA / "editor"
