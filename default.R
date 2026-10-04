# Generates default.nix for vienna_planning_toolkit via rix.
# Regenerate (cwd-safe, from the project root):
#   (cd <project> && nix-shell ~/docs_gh/llm/default.nix --run "Rscript default.R")
library(rix)

r_pkgs <- c("targets", "tarchetypes") |> sort()

py_conf <- list(
  py_version = "3.12",
  py_pkgs = c("ezdxf", "shapely", "numpy", "pytest") |> sort()
)

system_pkgs <- c("quarto") |> sort()

rix(
  date = "2026-02-02",
  project_path = ".",
  overwrite = TRUE,
  r_pkgs = r_pkgs,
  py_conf = py_conf,
  system_pkgs = system_pkgs,
  ide = "none"
)
