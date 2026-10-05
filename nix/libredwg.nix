# LibreDWG (dwg2dxf, dxf2dwg) newer than nixpkgs' 0.13.x, as a standalone shell. Kept out of default.nix.
#
# Why: LibreDWG 0.13.x has been seen to convert a DWG file (AC1027 = DWG 2013) only partly: "Some section size or address
# out of bounds" errors and a DXF cut off before ENTITIES, with exit code 0. This file builds the upstream release 0.14.
# vpt/dwg_convert.py checks every converted DXF for completeness, so a cut-off file is reported whichever version made it.
#
# Same pinned nixpkgs as default.nix. doCheck = false (the upstream tests do not pass with macOS clang). Same build recipe
# as nixpkgs' libredwg (autoreconfHook from the git tree); the version is pinned via postPatch's git-version-gen
# replacement, which nixpkgs derives from `version`.
#
# Use (from any directory, absolute path):
#   nix-shell /path/to/vienna_planning_toolkit/nix/libredwg.nix --run "dwg2dxf --version"
{ rev ? "release" }:
let
  pkgs = import (fetchTarball "https://github.com/rstats-on-nix/nixpkgs/archive/2026-02-02.tar.gz") {};
  revs = {
    release = {
      version = "0.14";
      commit = "d9468ae948b8f07a08efa756c19f8916052358c0";
      hash = "sha256-851VivSnXs0rAUE/z32/G9EYvn6LHkyxbhL4bNh+Alo=";
    };
  };
  r = revs.${rev};
  libredwg = pkgs.libredwg.overrideAttrs (_: {
    version = r.version;
    src = pkgs.fetchFromGitHub {
      owner = "LibreDWG";
      repo = "libredwg";
      rev = r.commit;
      hash = r.hash;
      fetchSubmodules = true;
    };
    doCheck = false;
  });
in
pkgs.mkShell {
  buildInputs = [ libredwg ];
}
