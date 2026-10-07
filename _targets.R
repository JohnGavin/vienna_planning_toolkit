# Pipeline: preset + generator -> synthetic flat DXF -> validation result -> plan file -> editor pages, the complex
# example as an Elektro DXF; and the DXF tools on the sample: completeness check, electrical base, fitting recognition.
# Run inside the project shell:
#   nix-shell default.nix --run "Rscript -e 'targets::tar_make()'"
library(targets)
library(tarchetypes)

python <- function() {
  py <- Sys.which("python3")
  if (!nzchar(py)) {
    cli::cli_abort("python3 not on PATH; run inside {.file default.nix} shell")
  }
  py
}

run_python <- function(args) {
  out <- system2(python(), args, stdout = TRUE, stderr = TRUE)
  status <- attr(out, "status")
  list(status = if (is.null(status)) 0L else as.integer(status), output = out)
}

list(
  tar_file(preset_file, "presets/synthetic_flat.json"),
  tar_file(generator_file, "tools/synthetic_flat.py"),
  tar_file(validator_file, "tools/validate_flat.py"),
  tar_file(
    flat_dxf,
    {
      res <- run_python(c(
        generator_file,
        "--preset", preset_file,
        "--output", "samples/synthetic_flat.dxf"
      ))
      if (res$status != 0L) {
        cli::cli_abort(c("generator failed", res$output))
      }
      "samples/synthetic_flat.dxf"
    }
  ),
  tar_target(
    flat_validation,
    {
      res <- run_python(c(validator_file, flat_dxf, "--preset", preset_file))
      # 0 PASS, 1 FAIL, 3 INDETERMINATE: anything but PASS stops the pipeline
      if (res$status != 0L) {
        cli::cli_abort(c(
          "validation did not pass (exit {res$status})",
          res$output
        ))
      }
      res
    }
  ),
  # the DXF tools on the sample (outputs under _scratch/, git-ignored; exit 0 PASS, anything else stops the pipeline)
  tar_target(
    dxf_tool_sources,
    c(
      list.files("vpt", pattern = "[.]py$", full.names = TRUE, recursive = TRUE),
      file.path("presets", c(
        "dwg_convert.json", "layer_strip.json", "fittings.json",
        "plan_extract.json"
      )),
      "nix/libredwg.nix",
      file.path("tools", c("dwg_convert.py", "strip_layers.py", "recognise_fittings.py"))
    ),
    format = "file"
  ),
  tar_target(
    dwg_check,
    {
      dxf_tool_sources
      res <- run_python(c(
        "tools/dwg_convert.py", flat_dxf, "--outdir", "_scratch/dwg_convert"
      ))
      if (res$status != 0L) {
        cli::cli_abort(c("completeness check did not pass (exit {res$status})", res$output))
      }
      "_scratch/dwg_convert/synthetic_flat.convert.json"
    },
    format = "file"
  ),
  tar_target(
    electrical_base,
    {
      dxf_tool_sources
      res <- run_python(c(
        "tools/strip_layers.py", flat_dxf, "--outdir", "_scratch/strip"
      ))
      if (res$status != 0L) {
        cli::cli_abort(c("electrical base did not pass (exit {res$status})", res$output))
      }
      "_scratch/strip/synthetic_flat__2OG__electrical_base.dxf"
    },
    format = "file"
  ),
  tar_target(
    fittings_result,
    {
      dxf_tool_sources
      res <- run_python(c(
        "tools/recognise_fittings.py", flat_dxf,
        "--output", "_scratch/synthetic_flat.fittings.json"
      ))
      if (res$status != 0L) {
        cli::cli_abort(c("fitting recognition did not pass (exit {res$status})", res$output))
      }
      "_scratch/synthetic_flat.fittings.json"
    },
    format = "file"
  ),
  # the electrical editor: plan file of the sample, then the two pages built from it
  tar_target(
    editor_sources,
    c(
      list.files("vpt", pattern = "[.]py$", full.names = TRUE, recursive = TRUE),
      list.files("editor", full.names = TRUE),
      list.files("schema", pattern = "[.]json$", full.names = TRUE),
      file.path("presets", c(
        "plan_extract.json", "svg_drawing.json", "el_symbols_at.json",
        "el_parameters.json", "el_rules_at.json", "el_page.json",
        "editor_docs.json"
      )),
      "tools/export_plan.py", "tools/build_editor.py"
    ),
    format = "file"
  ),
  tar_target(
    flat_plan,
    {
      editor_sources
      flat_validation
      res <- run_python(c(
        "tools/export_plan.py", flat_dxf, "--synthetic",
        "--output", "samples/synthetic_flat.plan.json"
      ))
      # 0 PASS; 1 FAIL / 3 INDETERMINATE stop the pipeline
      if (res$status != 0L) {
        cli::cli_abort(c("plan export did not pass (exit {res$status})", res$output))
      }
      "samples/synthetic_flat.plan.json"
    },
    format = "file"
  ),
  # the complex example written into a copy of the sample DXF as Elektro layers (what the Elektroplaner gets)
  tar_target(
    elektro_sources,
    c("vpt/dxf_export.py", "presets/dxf_export.json", "tools/export_layout_dxf.py"),
    format = "file"
  ),
  tar_target(
    flat_elektro_dxf,
    {
      elektro_sources
      editor_sources
      res <- run_python(c(
        "tools/export_layout_dxf.py", "--dxf", flat_dxf, "--plan", flat_plan,
        "--example", "complex", "--out", "samples/synthetic_flat_elektro.dxf"
      ))
      # 0 written and verified; 1 refused or not verified, 3 could not tell: stop the pipeline
      if (res$status != 0L) {
        cli::cli_abort(c("Elektro DXF export did not pass (exit {res$status})", res$output))
      }
      "samples/synthetic_flat_elektro.dxf"
    },
    format = "file"
  ),
  tar_target(
    editor_pages,
    {
      editor_sources
      res <- run_python(c("tools/build_editor.py", "--plan", flat_plan))
      if (res$status != 0L) {
        cli::cli_abort(c("editor build failed its gates (exit {res$status})", res$output))
      }
      c("site/index.html", "artifact/electrical_planner.html")
    },
    format = "file"
  )
)
