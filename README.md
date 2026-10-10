# vienna_planning_toolkit

Plan the electrics of a Vienna-style flat in your browser. Plus DWG/DXF layer tools.

- **Live editor:** <https://johngavin.github.io/vienna_planning_toolkit/>
- **Privacy:** files are read in your browser only. Nothing is uploaded.
- **No real building data** in this repo. The sample flat is synthetic.

## Quick start

1. Open the [live editor](https://johngavin.github.io/vienna_planning_toolkit/). It starts with the synthetic flat.
2. **Open plan…** to load your own drawing, or keep the sample.
3. Drag symbols from the palette onto the plan.
4. Connect switches to lights. The page proposes Ausschaltung, Wechselschaltung or Kreuzschaltung.
5. Read the layout checks: **ok**, **to look at** or **could not tell**.
6. **Save layout**, then print (A3, ⌘P to PDF) or export a DXF.

## Your own drawing

Run on your own computer. Replace the paths with yours.

1. DWG to DXF (skip if you have a DXF):
   `nix-shell default.nix --run "python3 tools/dwg_convert.py /path/to/your.dwg"`
2. Make the plan file for the editor:
   `nix-shell default.nix --run "python3 tools/export_plan.py /path/to/your.dxf"`
3. In the editor, click **Open plan…** and pick `your.plan.json`.
4. Place symbols, then **Save layout**.
5. Write the layout into a DXF for the Elektroplaner:
   `nix-shell default.nix --run "python3 tools/export_layout_dxf.py --dxf your.dxf --layout your__2OG.electrical.json --plan your.plan.json --out your_elektro.dxf"`

What step 5 does:

- **Checks first** that the layout matches the drawing (SHA-256) and storey. Otherwise nothing is written.
- **Keeps your drawing unchanged.** Symbols go on their own layers, so you can switch them off.
- **Reads the file back** to verify every symbol and link.
- Use `--example complex` instead of `--layout` to export a generated example.

Layer names map to storeys, rooms, walls and doors in `presets/plan_extract.json`.

Real drawings often need three reader options there (pass your copy with `--preset`):

| Key | Default | Use instead when |
|-----|---------|------------------|
| `text_reader` | `plain` | `mtext_clean`: area texts come out wrong or missing (MTEXT codes such as `\~`, `\H.66x;`) |
| `room_label_rule.rule` | `every_text` | `area_with_name_above`: the label layer also holds notes, finishes, heights or dimensions |
| `wall_reader.reader` | `exploded_lines` | `top_level_paths`: walls are hatches, or blocks on wall layers are details |

## Use as a Python package

- Package `vpt` (version in `vpt/__init__.py`), built from `pyproject.toml`.
- Presets, schemas and editor files ship inside the package.
- Pin a commit of this repo in your own nix file:

```nix
vptSrc = pkgs.fetchFromGitHub { owner = "JohnGavin"; repo = "vienna_planning_toolkit"; rev = "<commit>"; hash = "<sri>"; };
vpt = import "${vptSrc}/nix/vpt.nix" { inherit pkgs; python3Packages = pkgs.python312Packages; };
# then: pkgs.python312.withPackages (ps: [ vpt ])  ->  import vpt, and the vpt-* commands
```

- Without nix: `python3 -m pip install .` from a checkout.

## Tools

| Tool | Command when installed | What it does |
|------|------------------------|--------------|
| `tools/dwg_convert.py` | `vpt-dwg-convert` | DWG to DXF, then checks the DXF is complete |
| `tools/export_plan.py` | `vpt-export-plan` | DXF to plan file for the editor |
| `tools/export_layout_dxf.py` | `vpt-export-layout-dxf` | Layout into a DXF for the Elektroplaner |
| `tools/strip_layers.py` | `vpt-strip-layers` | Deletes layers the electrical base does not need |
| `tools/recognise_fittings.py` | `vpt-recognise-fittings` | Finds WC, basin, bath, sink by shape |
| `tools/validate_flat.py` | (repo only) | Checks the synthetic flat |
| `tools/build_editor.py` | (repo only) | Builds the editor page |
| `tools/check_editor.py` | (repo only) | Headless browser check of the page |
| `tools/check_installed.py` | (repo only) | Checks the installed package from outside the repo |

Every check has three outcomes: **PASS**, **FAIL**, **INDETERMINATE** ("could not tell"). Unconfirmed is never reported as a pass.

## Editor page

- **GitHub Pages** (`site/index.html`): Save layout, Print view, Save parameters, Copy layout.
- It opens a plan, layout or parameter file from disk, or takes pasted text.
- The page is self-contained: no server, no analytics, nothing loaded from other sites.
- Never commit your own plans or drawings here.

## Status and limits

- **Symbols are UNVERIFIED.** Drawn from general knowledge of IEC 60617, not checked against the standard.
- **Starting values only.** Placement rules and colours are not from a standard (`presets/el_parameters.json`).
- **Windows needed.** A drawing without window lines gives R6 "could not tell". Sockets cannot avoid unknown windows.
- **Old plan files** (format version 1) still open. The page says the windows are unknown.
- **Layer lists** in `presets/layer_strip.json` suit the synthetic flat. Replace them with your base names.
- **Fitting rules** are starting values. Unmatched or ambiguous symbols are listed, never guessed.

## Repo layout

| Path | Content |
|------|---------|
| `presets/` | All settings: sample, symbols, rules, texts, layers |
| `schema/` | JSON Schemas for plan, layout and parameter files |
| `vpt/` | Python package behind the tools (`vpt/cli/`: the commands) |
| `pyproject.toml` | Package build: `vpt`, its data and commands |
| `editor/` | Page CSS and scripts |
| `tools/` | Command-line tools (thin wrappers of `vpt/cli/`) |
| `nix/` | `vpt.nix` (the package), `vpt-shell.nix`, LibreDWG 0.14 shell |
| `samples/` | Synthetic flat, its plan file, an Elektro DXF |
| `site/` | The built page |
| `tests/` | pytest suite, including deliberate-failure tests |
| `_targets.R` | Pipeline: preset to DXF to plan to page |
| `default.R`, `default.nix` | Reproducible environment |

<details>
<summary>Develop and check</summary>

Environment: [rix](https://docs.ropensci.org/rix/) in `default.R` generates `default.nix`. Needs Nix.

```bash
nix-shell default.nix --run "Rscript -e 'targets::tar_make()'"     # DXF -> validation -> plan file -> page
nix-shell default.nix --run "python3 -m pytest tests -q"
nix-shell default.nix --run "python3 tools/check_editor.py"         # headless Chrome check of the page
nix-shell default.nix --run "python3 tools/check_editor.py --scheme dark --size 1440x900"
nix-shell default.nix --run "python3 tools/check_editor.py --browser edge"
nix-shell nix/vpt-shell.nix --run "python3 tools/check_installed.py ."   # the installed package
```

- **Reproducible:** same inputs give byte-identical outputs.
- **CI** (`.github/workflows/ci.yml`) rebuilds them and fails if a committed file is stale.
- **Pages:** `.github/workflows/pages.yml` publishes `site/` on every push to `main`.
- **Pages need a public repo** on a free plan (Settings > Pages > Source: GitHub Actions).

DWG conversion:

- Uses ODA File Converter if installed, else LibreDWG 0.14 from `nix/libredwg.nix`.
- ODA runs hidden; real-ODA tests are opt-in (`VPT_TEST_ODA=1`).
- nixpkgs LibreDWG 0.13 was seen to write a truncated DXF while exiting 0. So the output is always checked.
- A missing EOF marker or ENTITIES/OBJECTS section is FAIL.
- Converter errors, a non-zero exit or an unloadable DXF are INDETERMINATE.

Exit codes:

| Tool | Exit codes |
|------|------------|
| `validate_flat.py` | 0 all pass, 1 a check fails, 3 unreadable |
| `export_plan.py` | 0 PASS, 1 FAIL, 3 INDETERMINATE, 2 usage |
| `export_layout_dxf.py` | 0 written and verified, 1 refused or unverified, 2 usage, 3 could not tell |
| `build_editor.py` | 0 built, 1 a gate fails or a page is stale, 3 inputs unreadable |
| `check_editor.py` | 0 PASS, 1 FAIL, 3 INDETERMINATE (e.g. no browser) |
| `dwg_convert.py` | 0 PASS, 1 FAIL (DXF cut off), 3 INDETERMINATE, 2 usage |
| `strip_layers.py` | 0 PASS, 1 FAIL, 3 INDETERMINATE (unclassified layer), 2 usage |
| `recognise_fittings.py` | 0 PASS, 1 FAIL (wet room without fitting), 3 INDETERMINATE, 2 usage |
| `check_installed.py` | 0 PASS, 1 FAIL (not installed, data missing, output differs), 2 usage |

Synthetic sample (`samples/synthetic_flat.dxf`):

- Simplified Altbau flat, one storey, DXF R2018, metres. Invented; the title block says so.
- Every dimension and text lives in `presets/synthetic_flat.json`. `tools/synthetic_flat.py` is drawing logic only.

</details>

## Licence

- **MIT**, see `LICENSE`.
