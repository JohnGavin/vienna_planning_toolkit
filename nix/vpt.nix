# The toolkit as a Python package (import vpt; console scripts vpt-export-plan, vpt-export-layout-dxf, vpt-dwg-convert,
# vpt-strip-layers, vpt-recognise-fittings), built from this repo's source with pyproject.toml.
#
# In this repo:      nix-build nix/vpt.nix
# From a consumer, pinned to a commit of the repo:
#   vptSrc = pkgs.fetchFromGitHub { owner = "JohnGavin"; repo = "vienna_planning_toolkit"; rev = "<commit>"; hash = "<sri>"; };
#   vpt = import "${vptSrc}/nix/vpt.nix" { inherit pkgs; python3Packages = pkgs.python312Packages; };
#   ... then put vpt in the shell (e.g. pkgs.python312.withPackages (ps: [ vpt ]), or buildInputs = [ vpt ]).
{ pkgs ? import (fetchTarball "https://github.com/rstats-on-nix/nixpkgs/archive/2026-02-02.tar.gz") {}
, python3Packages ? pkgs.python312Packages
, src ? ../.
}:
let
  # the version's one home is vpt/__init__.py (__version__ = "x.y.z"); pyproject.toml reads it from there too
  lines = builtins.filter builtins.isString (builtins.split "\n" (builtins.readFile (src + "/vpt/__init__.py")));
  hits = builtins.filter (m: m != null) (map (l: builtins.match "__version__ = \"([^\"]+)\"" l) lines);
  version = if hits == [] then throw "vpt.nix: no __version__ in vpt/__init__.py" else builtins.head (builtins.head hits);
in
python3Packages.buildPythonPackage {
  pname = "vpt";
  inherit version;
  pyproject = true;
  src = pkgs.lib.cleanSourceWith {
    inherit src;
    # the package needs only its code, data folders and build files; built pages, samples and tests stay out
    filter = path: type:
      let rel = pkgs.lib.removePrefix (toString src + "/") (toString path);
          top = builtins.head (pkgs.lib.splitString "/" rel);
      in builtins.elem top [ "vpt" "presets" "schema" "editor" "nix" "pyproject.toml" "README.md" "LICENSE" ]
         && baseNameOf (toString path) != "__pycache__" && !(pkgs.lib.hasSuffix ".pyc" rel);
  };
  build-system = [ python3Packages.setuptools ];
  dependencies = with python3Packages; [ ezdxf shapely numpy pillow ];
  pythonImportsCheck = [ "vpt" "vpt.plan_extract" "vpt.cli.export_plan" ];
  doCheck = false;   # the pytest suite runs on the source checkout (it needs samples/ and tools/), not on the installed package
  meta = {
    description = "Generic DXF tools and an electrical installation-plan editor for Vienna-style building plans";
    license = pkgs.lib.licenses.mit;
  };
}
