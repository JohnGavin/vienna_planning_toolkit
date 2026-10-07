"""The installable package (pyproject.toml, nix/vpt.nix): entry points, data shipped inside the package, the version's one
home. The installed package itself is checked by tools/check_installed.py (CI, and nix/vpt-shell.nix locally)."""
import importlib
import re
import tomllib

import pytest

import vpt
from conftest import ROOT

PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
TOOLS = {"vpt-export-plan": "export_plan", "vpt-export-layout-dxf": "export_layout_dxf", "vpt-dwg-convert": "dwg_convert",
         "vpt-strip-layers": "strip_layers", "vpt-recognise-fittings": "recognise_fittings"}
NEEDED = {"presets": "*.json", "schema": "*.json", "editor": "*", "nix": "libredwg.nix"}   # what vpt reads at run time


def data_problems(cfg: dict) -> list[str]:
    """Files vpt needs at run time that the package config would leave out, and mapped folders that do not exist."""
    st = cfg["tool"]["setuptools"]
    out = []
    for pkg, folder in st["package-dir"].items():
        if not (ROOT / folder).is_dir():
            out.append(f"{pkg}: no folder {folder}")
        elif pkg not in st["packages"]:
            out.append(f"{pkg}: mapped but not listed in packages")
    by_folder = {folder: pkg for pkg, folder in st["package-dir"].items()}
    for folder, pat in NEEDED.items():
        pkg = by_folder.get(folder)
        globs = st["package-data"].get(pkg, []) if pkg else []
        for f in sorted((ROOT / folder).glob(pat)):
            if f.is_file() and not any(f.match(g) for g in globs):
                out.append(f"{folder}/{f.name} is not shipped")
    return out


def test_data_shipped_inside_the_package():
    assert data_problems(PYPROJECT) == []


def test_data_check_falsified():
    bad = {"tool": {"setuptools": dict(PYPROJECT["tool"]["setuptools"], **{"package-data": dict(
        PYPROJECT["tool"]["setuptools"]["package-data"], **{"vpt.editor": ["*.js"]})})}}
    assert any(p.endswith(".css is not shipped") for p in data_problems(bad))
    gone = {"tool": {"setuptools": dict(PYPROJECT["tool"]["setuptools"], **{"package-dir": dict(
        PYPROJECT["tool"]["setuptools"]["package-dir"], **{"vpt.schema": "schemas"})})}}
    assert any("no folder schemas" in p for p in data_problems(gone))


def test_source_checkout_reads_the_repo_folders():
    assert not vpt.INSTALLED
    assert (vpt.PRESETS, vpt.SCHEMAS, vpt.EDITOR) == (ROOT / "presets", ROOT / "schema", ROOT / "editor")


@pytest.mark.parametrize("script, mod", TOOLS.items())
def test_entry_points_and_wrappers(script, mod):
    target = PYPROJECT["project"]["scripts"][script]
    assert target == f"vpt.cli.{mod}:main"
    main = importlib.import_module(f"vpt.cli.{mod}").main
    wrapper = importlib.import_module(mod)                 # tools/<mod>.py (conftest puts tools/ on sys.path)
    assert wrapper.main is main
    try:
        rc = main(["--help"])
    except SystemExit as e:
        rc = e.code
    assert rc in (0, None)


def test_version_has_one_home():
    assert re.fullmatch(r"\d+\.\d+\.\d+", vpt.__version__)
    assert "version" in PYPROJECT["project"]["dynamic"] and PYPROJECT["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "vpt.__version__"}
    # nix/vpt.nix reads it with this line pattern: it must find exactly one line
    hits = [m.group(1) for ln in (ROOT / "vpt" / "__init__.py").read_text(encoding="utf-8").splitlines()
            if (m := re.fullmatch(r'__version__ = "([^"]+)"', ln))]
    assert hits == [vpt.__version__]
    assert 'builtins.match "__version__ = \\"([^\\"]+)\\"" l' in (ROOT / "nix" / "vpt.nix").read_text(encoding="utf-8")
