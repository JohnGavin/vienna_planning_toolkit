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
  )
)
