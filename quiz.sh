#!/data/data/com.termux/files/usr/bin/env bash
# Termux / Linux launcher: pulls progress, runs the quiz, pushes on quit.
cd "$(dirname "$0")" && python quiz.py "$@"
