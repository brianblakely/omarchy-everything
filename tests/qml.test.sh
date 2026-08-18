#!/bin/bash
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
OMARCHY_SOURCE=${OMARCHY_PATH:-/usr/share/omarchy}
QMLLINT_BIN=$(command -v qmllint 2>/dev/null || true)
[[ -n $QMLLINT_BIN ]] || QMLLINT_BIN=/usr/lib/qt6/bin/qmllint
RUNTIME_TMP=$(mktemp -d)
cleanup() { rm -rf -- "$RUNTIME_TMP"; }
trap cleanup EXIT
mkdir -p -- "$RUNTIME_TMP/config" "$RUNTIME_TMP/runtime" "$RUNTIME_TMP/home" \
  "$RUNTIME_TMP/lint/qs"
chmod 0700 "$RUNTIME_TMP/runtime"

if [[ -x $QMLLINT_BIN ]]; then
  cp -- "$ROOT_DIR/Service.qml" "$ROOT_DIR/Everything.qml" \
    "$ROOT_DIR/EverythingModel.js" "$RUNTIME_TMP/lint/"
  ln -s -- "$OMARCHY_SOURCE/shell/Commons" "$RUNTIME_TMP/lint/qs/Commons"
  ln -s -- "$OMARCHY_SOURCE/shell/Ui" "$RUNTIME_TMP/lint/qs/Ui"
  if ! "$QMLLINT_BIN" --signal-handler-parameters disable -I "$RUNTIME_TMP/lint" \
      "$RUNTIME_TMP/lint/Service.qml" "$RUNTIME_TMP/lint/Everything.qml" \
      >"$RUNTIME_TMP/qmllint.log" 2>&1; then
    sed -n '1,260p' "$RUNTIME_TMP/qmllint.log" >&2
    exit 1
  fi
fi

cp -- "$ROOT_DIR/tests/fixtures/qml-entrypoints/shell.qml" "$RUNTIME_TMP/config/shell.qml"
ln -s -- "$OMARCHY_SOURCE/shell/Commons" "$RUNTIME_TMP/config/Commons"
cp -a -- "$OMARCHY_SOURCE/shell/Ui" "$RUNTIME_TMP/config/Ui"
cp -- "$ROOT_DIR/tests/fixtures/qml-entrypoints/KeyboardPanel.qml" \
  "$RUNTIME_TMP/config/Ui/KeyboardPanel.qml"

env \
  QT_QPA_PLATFORM=offscreen \
  XDG_RUNTIME_DIR="$RUNTIME_TMP/runtime" \
  HOME="$RUNTIME_TMP/home" \
  OMARCHY_PATH="$OMARCHY_SOURCE" \
  EVERYTHING_SOURCE_DIR="$ROOT_DIR" \
  QML2_IMPORT_PATH="$OMARCHY_SOURCE/shell${QML2_IMPORT_PATH:+:$QML2_IMPORT_PATH}" \
  QML_IMPORT_PATH="$OMARCHY_SOURCE/shell${QML_IMPORT_PATH:+:$QML_IMPORT_PATH}" \
  timeout 20 quickshell -p "$RUNTIME_TMP/config" --no-color >"$RUNTIME_TMP/quickshell.log" 2>&1

if ! grep -Fq 'EVERYTHING_LOAD_OK service' "$RUNTIME_TMP/quickshell.log" \
    || ! grep -Fq 'EVERYTHING_LOAD_OK widget' "$RUNTIME_TMP/quickshell.log" \
    || ! grep -Fq 'EVERYTHING_LEASE_OK' "$RUNTIME_TMP/quickshell.log"; then
  sed -n '1,260p' "$RUNTIME_TMP/quickshell.log" >&2
  exit 1
fi
if grep -Fq 'EVERYTHING_LOAD_ERROR' "$RUNTIME_TMP/quickshell.log" \
    || grep -Fq 'EVERYTHING_CREATE_ERROR' "$RUNTIME_TMP/quickshell.log" \
    || grep -Fq 'EVERYTHING_LEASE_ERROR' "$RUNTIME_TMP/quickshell.log"; then
  sed -n '1,260p' "$RUNTIME_TMP/quickshell.log" >&2
  exit 1
fi

echo "qml.test.sh: entrypoints loaded"
