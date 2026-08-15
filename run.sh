#!/bin/bash
# Launch Whisper VTT
cd "$(dirname "$0")"
exec .venv/bin/python -m src
