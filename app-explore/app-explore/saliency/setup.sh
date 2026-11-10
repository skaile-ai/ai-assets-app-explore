#!/usr/bin/env bash
# Install the saliency model of app-explore (feature `saliency`) once: a python3.11 venv with TensorFlow, tf-keras and
# Pillow, and the UMSI++ weights (umsi++.hdf5 from the UEyes model zip; downloaded here, never shipped with the skill).
# Idempotent: steps already done are skipped. On success stdout is exactly one line, the venv's python path; all
# progress goes to stderr. Exit 2: no python3.11 (TensorFlow has no wheels for newer Pythons); exit 3: the downloaded
# zip's sha256 is not ZIP_SHA256 (changed or corrupt, nothing unpacked); other non-zero: pip or download failed.
#   PY=$(bash saliency/setup.sh) && "$PY" saliency/run.py <stem>.data <stem>.media
# Location: $APP_EXPLORE_SALIENCY_HOME, default ~/.cache/app-explore/saliency.
set -euo pipefail

DIR="${APP_EXPLORE_SALIENCY_HOME:-$HOME/.cache/app-explore/saliency}"
URL="https://userinterfaces.aalto.fi/ueyeschi23/model_weights.zip"
MEMBER="model_weights/saliency_models/UMSI++/umsi++.hdf5"
# sha256 of model_weights.zip as downloaded on 2026-11-10 (umsi++.hdf5 inside: f4290c3f…99e9fe)
ZIP_SHA256="39e470e8b849a5e08c4ceefa3dffca134c68d88770866e98cf122f1f1b798569"

PY311="$(command -v python3.11 || true)"
if [ -z "$PY311" ]; then
  echo "saliency setup: python3.11 not found (TensorFlow has no wheels for newer Python); install it, e.g. 'brew install python@3.11' or 'uv python install 3.11'" >&2
  exit 2
fi
mkdir -p "$DIR"
VPY="$DIR/venv/bin/python"
if [ ! -x "$VPY" ]; then
  echo "saliency setup: creating venv in $DIR/venv" >&2
  "$PY311" -m venv "$DIR/venv" >&2
fi
if ! "$VPY" -c 'import tensorflow, tf_keras, PIL' >/dev/null 2>&1; then
  echo "saliency setup: installing tensorflow tf-keras pillow (about 1.4 GB)" >&2
  "$VPY" -m pip install --quiet --upgrade pip >&2
  "$VPY" -m pip install --quiet tensorflow tf-keras pillow >&2
fi
W="$DIR/umsi++.hdf5"
if [ ! -s "$W" ]; then
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  echo "saliency setup: downloading $URL (about 420 MB, only umsi++.hdf5 is kept)" >&2
  curl -fsSL --retry 2 -o "$TMP/weights.zip" "$URL" >&2
  GOT="$( (command -v sha256sum >/dev/null && sha256sum "$TMP/weights.zip" || shasum -a 256 "$TMP/weights.zip") | cut -d' ' -f1)"
  if [ "$GOT" != "$ZIP_SHA256" ]; then
    echo "saliency setup: $URL has sha256 $GOT, expected $ZIP_SHA256; not unpacked" >&2
    exit 3
  fi
  unzip -q -j -o "$TMP/weights.zip" "$MEMBER" -d "$TMP" >&2
  mv "$TMP/umsi++.hdf5" "$W"
fi
echo "$VPY"
