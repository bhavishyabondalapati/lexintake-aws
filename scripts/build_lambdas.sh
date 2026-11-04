#!/usr/bin/env bash
# Builds build/<function>/ for each Lambda: the shared code (src/common), the function's handler,
# and its pip packages downloaded for Lambda's platform (Linux x86_64, Python 3.12) even though
# this runs on a Mac. Terraform then zips each folder.
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
FUNCTIONS=(parse extract score review_request)

# Start clean: only this repo's own build/ folder is emptied.
if [ -d build ]; then
  find build -mindepth 1 -delete
fi
mkdir -p build

for fn in "${FUNCTIONS[@]}"; do
  out="build/$fn"
  mkdir -p "$out"
  if [ -s "src/$fn/requirements.txt" ]; then
    "$PYTHON" -m pip install --quiet --upgrade --target "$out" \
      --platform manylinux2014_x86_64 --python-version 3.12 --implementation cp \
      --only-binary=:all: -r "src/$fn/requirements.txt"
  fi
  cp -R src/common "$out/common"
  # everything in src/<fn> except the requirements file (handler.py, the playbook, ...)
  find "src/$fn" -maxdepth 1 -type f ! -name requirements.txt -exec cp {} "$out/" \;
  find "$out" -name __pycache__ -type d -prune -exec rm -r {} +
  find "$out" -name '*.pyc' -delete
  echo "built $out ($(du -sh "$out" | cut -f1))"
done
