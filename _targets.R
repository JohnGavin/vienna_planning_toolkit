# Pipeline: preset + generator -> synthetic flat DXF -> validation result.
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
  # the electrical editor: plan file of the sample, then the two pages built from it
  tar_target(
    editor_sources,
    c(
      list.files("vpt", pattern = "[.]py$", full.names = TRUE),
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
