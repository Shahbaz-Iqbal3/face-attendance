#!/usr/bin/env bash
# One-time setup (internet needed once). Works on Linux / macOS / Raspberry Pi OS.
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
if [ -d wheels ]; then pip install --no-index --find-links wheels -r requirements.txt; else pip install -r requirements.txt; fi
echo "Setup finished. Start with ./run.sh"
