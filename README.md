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
the door, socket mid-wall, light in the room centre) snap symbols into place,
and keep the result as a layout file.

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
(one group per layer), the rooms, doors and walls it found, the placement
suggestions and, for one storey, generated examples. It prints the checks
R1-R5 (rooms with an id, doors connecting rooms, outlines, door swings, walls)
with three outcomes; exit code 0 PASS, 1 FAIL, 3 INDETERMINATE.

Then click **Open plan…** in either page and pick that file. How layer names
map to storeys, rooms, walls and doors is set in `presets/plan_extract.json`
(the default follows this toolkit's `<storey>_<nn>_[Abbruch_|Neubau_]<base>`
naming).

### Privacy

- The pages are self-contained files: no server, no analytics, nothing loaded
  from other sites (the build checks this; so does the browser check).
- A file you open or paste is read by your browser only. Drafts stay in your
  browser's storage.
- `tools/export_plan.py` runs locally; the plan file holds the DXF's file name
  and SHA-256, never its folder.
- Never commit your own plan files or drawings to this repository.

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
```

The same inputs always give byte-identical outputs (the DXF, the plan file and
the pages); CI (`.github/workflows/ci.yml`) rebuilds them and fails when a
committed file is out of date.

| Tool | Exit codes |
|------|------------|
| `tools/validate_flat.py` | 0 every check passes, 1 a check fails, 3 the drawing cannot be read |
| `tools/export_plan.py` | 0 PASS, 1 FAIL, 3 INDETERMINATE (or unreadable: nothing written), 2 usage |
| `tools/build_editor.py` | 0 built and the page gates pass, 1 a gate fails or (`--check`) a page is out of date, 3 inputs unreadable |
| `tools/check_editor.py` | 0 PASS, 1 FAIL, 3 INDETERMINATE (e.g. Chrome missing) |

## Layout

| Path | Content |
|------|---------|
| `presets/` | Sample definition; plan extraction; symbol library; parameters (rules, colours); page texts |
| `schema/` | JSON Schemas of the plan file, the layout file and the parameter file |
| `vpt/` | Python package: DXF to SVG, rooms/doors/walls, plan file, rules, links, examples, page builder |
| `editor/` | The page's CSS and scripts (one code base for both pages) |
| `tools/` | Generator, validator, plan export, page build, browser check |
| `samples/` | Generated sample drawing and its plan file |
| `site/`, `artifact/` | The two built pages |
| `tests/` | pytest suite, including tests that break things on purpose |
| `_targets.R` | Pipeline: preset -> DXF -> validation -> plan file -> pages |
| `default.R`, `default.nix` | Reproducible environment |

## Licence

MIT, see `LICENSE`.
