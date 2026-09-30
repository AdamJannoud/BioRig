#!/usr/bin/env bash
# forge inspect storageLayout of a given source placed at src/BioRigCoreV5.sol; restores the real file.
# usage: evidence/i6/inspect_layout.sh <source.sol> <out-prefix>   -> <out-prefix>.json/.txt/.normalized.json
set -eu
cd "$(dirname "$0")/../.."
src="$1"; out="$2"
cp src/BioRigCoreV5.sol evidence/i6/.BioRigCoreV5.sol.keep
restore() { cp evidence/i6/.BioRigCoreV5.sol.keep src/BioRigCoreV5.sol && rm evidence/i6/.BioRigCoreV5.sol.keep; }
trap restore EXIT
[ "$src" = src/BioRigCoreV5.sol ] || cp "$src" src/BioRigCoreV5.sol
forge inspect BioRigCoreV5 storageLayout --json > "$out.json"
forge inspect BioRigCoreV5 storageLayout > "$out.txt"
python3 evidence/normalize_layout.py "$out.json" > "$out.normalized.json"
