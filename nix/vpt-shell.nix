# A shell with Python and the toolkit INSTALLED from nix/vpt.nix (not the source checkout): what a consumer gets.
#   nix-shell nix/vpt-shell.nix --run "python3 tools/check_installed.py ."
{ pkgs ? import (fetchTarball "https://github.com/rstats-on-nix/nixpkgs/archive/2026-02-02.tar.gz") {} }:
let
  vpt = import ./vpt.nix { inherit pkgs; python3Packages = pkgs.python312Packages; };
in
pkgs.mkShell { packages = [ (pkgs.python312.withPackages (ps: [ vpt ])) ]; }
