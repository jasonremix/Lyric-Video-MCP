#!/usr/bin/env bash
set -euo pipefail

command -v ffmpeg >/dev/null || { echo 'FFmpeg fehlt. Installiere es zuerst, z.B. mit: sudo apt-get install ffmpeg' >&2; exit 1; }
command -v ffprobe >/dev/null || { echo 'ffprobe fehlt. Installiere FFmpeg vollständig.' >&2; exit 1; }
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
echo
printf 'Installation abgeschlossen. Start: %s\n' "$PWD/.venv/bin/python $PWD/server.py"
