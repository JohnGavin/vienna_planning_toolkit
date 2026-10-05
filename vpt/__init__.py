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
    editor_page    the HTML of the editor page (both variants)
    dwg_convert    DWG -> DXF (ODA File Converter or LibreDWG) and the completeness check of the DXF
    layer_strip    the electrical base: layers deleted by storey, status and base name, with read-back checks
    dxf_symbols    shape features and rules: symbols from plain DXF geometry
    fittings       fittings recognised by shape and assigned to rooms
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PRESETS = ROOT / "presets"
SCHEMAS = ROOT / "schema"
