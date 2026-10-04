# vienna_planning_toolkit

Generic tools for Vienna-style building plans: DWG/DXF layer handling and,
later, an electrical installation-plan editor.

The repository holds **no real building data**. The one sample drawing is a
synthetic flat produced by code.

## The synthetic sample flat

`samples/synthetic_flat.dxf` is a simplified Viennese Altbau flat on one
storey (DXF R2018, model units metres). It is invented. The title block says
so, and its address ("Musterstraße 1, 1010 Wien") is marked as fictitious.

It contains:

- seven rooms (Vorraum, Wohnzimmer, Schlafzimmer, Küche, Bad, WC,
  Abstellraum), each a closed outline with a label giving name and area;
- 0.5 m outer walls, 0.25 m bearing middle wall and 0.12 m partitions, drawn
  as face lines, plus one wall to demolish (`Abbruch`) and one new wall
  (`Neubau`);
- doors as leaf lines with swing arcs, box windows with two frames and a
  window board, and a few kitchen, sanitary and furniture outlines;
- dimensions, ceiling notes and a paper-space layout with a 1:100 viewport.

Every dimension, name and text lives in `presets/synthetic_flat.json`.
The generator in `tools/synthetic_flat.py` holds only drawing logic.

## Regenerate and check

The environment is defined with [rix](https://docs.ropensci.org/rix/) in
`default.R`, which generates `default.nix`. With Nix installed:

```bash
nix-shell default.nix --run "python3 tools/synthetic_flat.py"
nix-shell default.nix --run "python3 tools/validate_flat.py samples/synthetic_flat.dxf --preset presets/synthetic_flat.json"
nix-shell default.nix --run "python3 -m pytest tests -q"
nix-shell default.nix --run "Rscript -e 'targets::tar_make()'"
```

The same preset always produces a byte-identical DXF, and the tests fail if
the committed sample is out of date.

`tools/validate_flat.py` exits 0 when every check passes, 1 when a check
fails, and 3 when the drawing cannot be read.

## Layout

| Path | Content |
|------|---------|
| `presets/` | Sample definitions (all dimensions and texts) |
| `tools/` | Generator and validator |
| `samples/` | Generated sample drawings |
| `tests/` | pytest suite, including tests that break the drawing on purpose |
| `_targets.R` | Pipeline: preset and generator, then DXF, then validation |
| `default.R`, `default.nix` | Reproducible environment |

## Licence

MIT, see `LICENSE`.
