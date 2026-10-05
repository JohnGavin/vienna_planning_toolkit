# vienna_planning_toolkit

Generic tools for Vienna-style building plans: DWG/DXF layer handling and an
electrical installation-plan editor that runs in the browser.

The repository holds **no real building data**. The one sample drawing is a
synthetic flat produced by code.

## The electrical editor

Plan where the sockets, switches and lights of a flat go, on top of the
architect's drawing: drag symbols from a palette onto the plan, connect
switches to the lights they work (the page proposes Ausschaltung,
Wechselschaltung or Kreuzschaltung), let placement suggestions (switch beside
the door, socket mid-wall clear of the windows, light in the room centre) snap
symbols into place, read the layout checks (lights, switches, sockets per room,
kitchen outlets, smoke alarms; each ok, to look at or could not tell), and keep
the result as a layout file. The layout can then be written into a copy of the
DXF for the Elektroplaner (see below).

One code base builds two pages (`tools/build_editor.py`):

| Page | File | For |
|------|------|-----|
| GitHub Pages version | `site/index.html`, published at <https://johngavin.github.io/vienna_planning_toolkit/> | Real work: Save layout, Save to file (Chrome/Edge, in place), Save parameters, Print view (A3, ⌘P → PDF) |
| Shareable demo | `artifact/electrical_planner.html` (a claude.ai artifact) | Trying it out: Copy layout / Copy parameters instead of downloads; no printing |

Both open with the synthetic flat and its generated simple example, marked
as an example and as synthetic. Both can open a plan, layout or parameter
file from your computer, or take its text by paste.

The Pages address works once the repository is public: GitHub Pages does not
serve a private repository on a free plan. `.github/workflows/pages.yml`
publishes `site/` on every push to `main` (Settings > Pages > Source: GitHub
Actions).

The symbols are drawn from general knowledge of IEC 60617 installation-plan
conventions and are marked **UNVERIFIED** everywhere: they have not been
checked against the standard text or an Elektroplaner's legend. Every
placement rule and colour is a starting value to confirm
(`presets/el_parameters.json`).

### Your own drawing

Export it on your own computer:

```bash
nix-shell default.nix --run "python3 tools/export_plan.py /path/to/your.dxf"
```

This writes `your.plan.json` next to the DXF: per storey the drawing as SVG
(one group per layer), the rooms, doors, walls and windows it found, the
placement suggestions and, for one storey, generated examples. It prints the
checks R1-R6 (rooms with an id, doors connecting rooms, outlines, door swings,
walls, windows in a room's wall) with three outcomes; exit code 0 PASS,
1 FAIL, 3 INDETERMINATE. A drawing without window lines gives R6 could not
tell: the socket suggestions cannot keep clear of windows they do not know.
An older plan file (format version 1, no windows) still opens; the page then
says the windows are unknown.

Then click **Open plan…** in either page and pick that file. How layer names
map to storeys, rooms, walls and doors is set in `presets/plan_extract.json`
(the default follows this toolkit's `<storey>_<nn>_[Abbruch_|Neubau_]<base>`
naming).

### CAD for the Elektroplaner

The page cannot write a DXF (the browser has no DXF writer), so this is a
step on your own computer. Keep the storey's layout as a file (Save layout or
Copy layout), then:

```bash
nix-shell default.nix --run "python3 tools/export_layout_dxf.py --dxf your.dxf --layout your__2OG.electrical.json --plan your.plan.json --out your_elektro.dxf"
```

- It first checks that the layout belongs to that drawing (its SHA-256) and
  storey; otherwise nothing is written.
- It keeps the whole drawing unchanged and adds the layout on its own layers,
  one per symbol category plus one for the links (DXF-safe names in
  `presets/dxf_export.json`), coloured from the print palette, so the
  Elektroplaner can overlay it or switch it off.
- Every symbol is a block insert at its place, turned and scaled to the plan's
  scale, with attributes code, German name, room, `VERIFIED = false` and its id;
  the links are dashed lines; a note on the drawing says the symbols are
  UNVERIFIED.
- It reads the written file back: every symbol there, on its layer, within
  `position_tol_mm` of its place (`presets/dxf_export.json`), every link, and
  the source drawing unchanged.

`samples/synthetic_flat_elektro.dxf` is the synthetic flat's complex example
written this way (`--example complex` takes an example from the plan file).

### Privacy

- The pages are self-contained files: no server, no analytics, nothing loaded
  from other sites (the build checks this; so does the browser check).
- A file you open or paste is read by your browser only. Drafts stay in your
  browser's storage.
- `tools/export_plan.py` runs locally; the plan file holds the DXF's file name
  and SHA-256, never its folder.
- Never commit your own plan files or drawings to this repository.

## Prepare your own DXF

Three command-line tools work on the DXF of your own drawing, on your own computer. All three have the same three outcomes
(PASS, FAIL, INDETERMINATE: "could not tell"), and a result that could not be confirmed is never reported as a pass.

```bash
nix-shell default.nix --run "python3 tools/dwg_convert.py /path/to/your.dwg"            # DWG -> DXF, then check the DXF is complete
nix-shell default.nix --run "python3 tools/strip_layers.py /path/to/your.dxf"           # the electrical base: delete the layers it does not need
nix-shell default.nix --run "python3 tools/recognise_fittings.py /path/to/your.dxf"     # WC, basin, bath, sink ... by shape, each in its room
```

- **DWG to DXF** (`tools/dwg_convert.py`, `presets/dwg_convert.json`): converts with the ODA File Converter when it is installed,
  else with LibreDWG 0.14 built from `nix/libredwg.nix` (the 0.13 of nixpkgs has been seen to write a DXF that stops after the
  BLOCKS section while exiting 0, on one real drawing; hence the check below). The written DXF is checked whatever the converter's exit code says: no EOF marker or no ENTITIES / OBJECTS section
  is a FAIL; converter lines about errors or unsupported objects, an exit code other than 0, or a DXF ezdxf cannot load are
  INDETERMINATE. A DXF given directly is only checked.
- **Electrical base** (`tools/strip_layers.py`, `presets/layer_strip.json`): per storey, layers are deleted (not hidden) by their
  base name (keep / drop lists), by status (`Abbruch`, to demolish, goes) and for other storeys. A layer with content on neither list
  is kept and flagged. Each output is read back and checked, among others that its layers are exactly the kept set. The lists in the
  preset are written for the synthetic flat: replace them with the base names of your drawing.
- **Fittings by shape** (`tools/recognise_fittings.py`, `presets/fittings.json`): plain lines, arcs and circles on the fitting
  layers are grouped into symbols and classified by size and shape rules; a symbol that no rule or several rules match is listed as
  unrecognised or ambiguous, never guessed. Rooms come from the same extraction as the editor's plan file. The rules are starting
  values to confirm.

## The synthetic sample flat

`samples/synthetic_flat.dxf` is a simplified Viennese Altbau flat on one
storey (DXF R2018, model units metres). It is invented: the title block says
so, and its address is marked as fictitious.

It contains:

- the rooms listed under `rooms` in `presets/synthetic_flat.json`, each a
  closed outline with a label giving name and area;
- 0.5 m outer walls, 0.25 m bearing middle wall and 0.12 m partitions, drawn
  as face lines, plus one wall to demolish (`Abbruch`) and one new wall
  (`Neubau`);
- doors as leaf lines with swing arcs, box windows with two frames and a
  window board, and a few kitchen, sanitary and furniture outlines;
- dimensions, ceiling notes and a paper-space layout with a 1:100 viewport.

Every dimension, name and text lives in `presets/synthetic_flat.json`.
The generator in `tools/synthetic_flat.py` holds only drawing logic.
`samples/synthetic_flat.plan.json` is its plan file for the editor.

## Regenerate and check

The environment is defined with [rix](https://docs.ropensci.org/rix/) in
`default.R`, which generates `default.nix`. With Nix installed:

```bash
nix-shell default.nix --run "Rscript -e 'targets::tar_make()'"     # DXF -> validation -> plan file -> both pages
nix-shell default.nix --run "python3 -m pytest tests -q"
nix-shell default.nix --run "python3 tools/check_editor.py"         # headless Chrome check of both pages
nix-shell default.nix --run "python3 tools/check_editor.py --scheme dark --size 1440x900"   # Chrome, dark page theme
nix-shell default.nix --run "python3 tools/check_editor.py --browser edge"                   # Microsoft Edge, light
```

The same inputs always give byte-identical outputs (the DXF, the plan file and
the pages); CI (`.github/workflows/ci.yml`) rebuilds them and fails when a
committed file is out of date.

| Tool | Exit codes |
|------|------------|
| `tools/validate_flat.py` | 0 every check passes, 1 a check fails, 3 the drawing cannot be read |
| `tools/export_plan.py` | 0 PASS, 1 FAIL, 3 INDETERMINATE (or unreadable: nothing written), 2 usage |
| `tools/export_layout_dxf.py` | 0 written and verified, 1 refused (another drawing or storey: nothing written) or not verified, 2 usage, 3 could not tell (nothing written) |
| `tools/build_editor.py` | 0 built and the page gates pass, 1 a gate fails or (`--check`) a page is out of date, 3 inputs unreadable |
| `tools/check_editor.py` | 0 PASS, 1 FAIL, 3 INDETERMINATE (e.g. the browser missing) |
| `tools/dwg_convert.py` | 0 PASS, 1 FAIL (the DXF is cut off), 3 INDETERMINATE, 2 usage |
| `tools/strip_layers.py` | 0 PASS, 1 FAIL (a check differs), 3 INDETERMINATE (an unclassified layer, ...), 2 usage |
| `tools/recognise_fittings.py` | 0 PASS, 1 FAIL (a wet room without a fitting), 3 INDETERMINATE (an unrecognised symbol, ...), 2 usage |

## Layout

| Path | Content |
|------|---------|
| `presets/` | Sample definition; plan extraction; symbol library; parameters (rules, checks, colours); page texts; DXF export layers; DWG conversion; layer lists; fitting rules |
| `schema/` | JSON Schemas of the plan file, the layout file and the parameter file |
| `vpt/` | Python package: DXF to SVG, rooms/doors/walls/windows, plan file, rules, links, layout checks, examples, DXF export, page builder, DWG conversion, layer stripping, fittings |
| `editor/` | The page's CSS and scripts (one code base for both pages) |
| `tools/` | Generator, validator, plan export, layout-to-DXF export, page build, browser check, DWG conversion, layer stripping, fitting recognition |
| `nix/` | LibreDWG 0.14 as a stand-alone nix shell (the DWG converter route without the ODA File Converter) |
| `samples/` | Generated sample drawing, its plan file, and its complex example as an Elektro DXF |
| `site/`, `artifact/` | The two built pages |
| `tests/` | pytest suite, including tests that break things on purpose |
| `_targets.R` | Pipeline: preset -> DXF -> validation -> plan file -> pages, the Elektro DXF, and the three DXF tools on the sample |
| `default.R`, `default.nix` | Reproducible environment |

## Licence

MIT, see `LICENSE`.
