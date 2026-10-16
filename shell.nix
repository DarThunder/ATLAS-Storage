{ pkgs ? import <nixpkgs> {} }:

let
  fastcdc = pkgs.python3Packages.buildPythonPackage rec {
    pname = "fastcdc";
    version = "1.7.0";

    pyproject = true;

    src = pkgs.python3Packages.fetchPypi {
      inherit pname version;
      hash = "sha256-Y0tPvqhSlkhOiWtv9w5DvNlHJJiVMMhjmm5bJTEF7tI=";
    };

    build-system = [
      pkgs.python3Packages.setuptools
      pkgs.python3Packages.poetry-core
      pkgs.python3Packages.cython
    ];

    doCheck = false;
    dontCheckRuntimeDeps = true;
  };
in
pkgs.mkShell {
  packages = [
    (pkgs.python3.withPackages (ps: with ps; [
      fastapi
      uvicorn
      sqlalchemy
      python-multipart
      blake3
      httpx
      fastcdc
    ]))
    pkgs.sqlite
  ];

  shellHook = ''
    export PYTHONPYCACHEPREFIX="''$PWD/.cache/holder"
    echo "Hello World!"
  '';
}