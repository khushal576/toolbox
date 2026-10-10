#!/usr/bin/env bash
# Pre-download all wheels for the Docker image's platform/Python version into
# wheelhouse/ (gitignored), so the Docker build installs from disk instead of
# the network. Run this once, and again whenever requirements.txt changes.
set -euo pipefail
cd "$(dirname "$0")"

rm -rf wheelhouse
mkdir -p wheelhouse

pip3 download -r requirements.txt -d wheelhouse \
  --platform manylinux2014_x86_64 \
  --python-version 311 \
  --implementation cp \
  --abi cp311 \
  --only-binary=:all: \
  --timeout 120 --retries 15

echo "wheelhouse/ ready — $(ls wheelhouse | wc -l) files"
