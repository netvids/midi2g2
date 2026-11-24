#!/usr/bin/env bash
# Installs g2ools (GPL-2.0-or-later, github.com/msg/g2ools) at the tested commit and applies the fixes midi2g2 relies on.
# Usage: bash setup_g2ools.sh [target_dir]   (default: $HOME/g2ools). Prints the path to export as G2OOLS.
set -e
DEST="${1:-$HOME/g2ools}"
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMIT=689c6617d3ed6387fb95a6e7ecbcd9100fcdf77c
if [ ! -d "$DEST/nord" ]; then
  git clone -q https://github.com/msg/g2ools.git "$DEST"
  (cd "$DEST" && git checkout -q "$COMMIT")
fi
cd "$DEST"
if git apply --check "$HERE/g2ools-fixes.patch" 2>/dev/null; then git apply "$HERE/g2ools-fixes.patch"; echo "fixes applied"; else echo "fixes already applied (or tree differs)"; fi
python3 -c "import sys; sys.path.insert(0, '$DEST'); import nord.g2.file; print('g2ools OK')"
echo "export G2OOLS=$DEST"
