#!/bin/bash
# Double-click this file in Finder to launch the Macro Recorder.
# (You may need to right-click > Open the first time.)
cd "$(dirname "$0")"
exec ./.venv/bin/python macro_recorder_qt.py
