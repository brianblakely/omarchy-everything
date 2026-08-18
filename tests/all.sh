#!/bin/bash
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd -- "$ROOT_DIR"

python -m compileall -q "$ROOT_DIR/everything" "$ROOT_DIR/helper"
python -m unittest discover -s "$ROOT_DIR/tests" -p 'test_*.py'
node "$ROOT_DIR/tests/model.test.js"
"$ROOT_DIR/tests/qml.test.sh"
omarchy plugin validate "$ROOT_DIR"

echo "all tests passed"
