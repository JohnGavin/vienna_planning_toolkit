"""The command-line tools: one module per tool, each with main(argv) -> exit code (0 PASS, 1 FAIL, 2 usage, 3 INDETERMINATE).

Installed (pyproject.toml [project.scripts]) as vpt-export-plan, vpt-export-layout-dxf, vpt-dwg-convert, vpt-strip-layers and
vpt-recognise-fittings; in a source checkout tools/<name>.py runs the same main().
"""
